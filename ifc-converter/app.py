# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Hyland Software, Inc.
"""ifc-converter: converts an IFC file (sent as the raw request body) to GLB, OBJ, SVG or PNG.

    POST /convert?format=glb|obj|objzip|svg|png[&view=3d|plan][&size=1024]
    GET  /health

Example:
    curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=png" -o preview.png

Every tool runs as a subprocess, so a crash or a hang in IfcConvert/VTK never takes the server down.
"""
import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.background import BackgroundTask

MAX_UPLOAD_MB = float(os.environ.get("MAX_UPLOAD_MB", "500"))
CONVERT_TIMEOUT_S = float(os.environ.get("CONVERT_TIMEOUT_S", "150"))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
IFC_THREADS = int(os.environ.get("IFC_THREADS", "4"))

RENDER_SCRIPT = Path(__file__).with_name("render.py")
MEDIA_TYPES = {
    "glb": "model/gltf-binary",
    "obj": "model/obj",
    "objzip": "application/zip",
    "svg": "image/svg+xml",
    "png": "image/png",
}
VIEWS = ("3d", "plan")
# For SVG, IfcConvert includes only IfcSpace by default; an explicit --exclude replaces that
# default so walls, slabs... are drawn too. --include/--exclude must not be the last option
# before the input file, hence the flags after it.
SVG_OPTIONS = ["--exclude", "entities", "IfcOpeningElement",
               "--bounds", "1024x1024", "--print-space-names", "--door-arcs"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ifc-converter")
app = FastAPI(title="ifc-converter")
semaphore = asyncio.Semaphore(MAX_CONCURRENT)


class ConversionError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def ifcconvert_version():
    try:
        out = subprocess.run(["IfcConvert", "--version"], capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return None


IFCCONVERT_VERSION = ifcconvert_version()


def ifcconvert(src, dst, *options):
    # No -q: on failure, the log IfcConvert prints is what we send back to the caller
    return ["IfcConvert", "-y", "--no-progress", "-j", str(IFC_THREADS), *options, str(src), str(dst)]


async def run(cmd, deadline):
    """Run a tool, kill it if the request deadline is reached."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=max(0.0, deadline - time.monotonic()))
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ConversionError(504, f"conversion timed out after {CONVERT_TIMEOUT_S:g}s")
    if proc.returncode != 0:
        tail = "\n".join(out.decode(errors="replace").splitlines()[-15:])
        raise ConversionError(500, f"{Path(cmd[0]).name} failed (exit {proc.returncode}):\n{tail}")


def expect(path):
    if not path.exists() or path.stat().st_size == 0:
        raise ConversionError(500, f"no {path.suffix} produced: the IFC may contain no convertible geometry")
    return path


async def save_body(request, path):
    """Stream the request body to disk, enforcing the size limit."""
    limit = MAX_UPLOAD_MB * 1024 * 1024
    if int(request.headers.get("content-length") or 0) > limit:
        raise ConversionError(413, f"file larger than {MAX_UPLOAD_MB:g} MB")
    size = 0
    with open(path, "wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise ConversionError(413, f"file larger than {MAX_UPLOAD_MB:g} MB")
            f.write(chunk)
    return size


def check_ifc(path, size):
    if size == 0:
        raise ConversionError(400, "empty body: send the IFC as the raw request body (curl --data-binary @model.ifc)")
    with open(path, "rb") as f:
        if not f.read(64).lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"ISO-10303-21"):
            raise ConversionError(400, "not an IFC file: missing the ISO-10303-21 header (ifcXML and ifcZIP are not supported)")


def main_storey_svg(svg, out):
    """Keep only the storey with the most elements. IfcConvert draws each storey as a layer
    (<g class="IfcBuildingStorey">) at the same place, so rasterizing them all overlaps the plans."""
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    try:
        tree = ET.parse(svg)
    except ET.ParseError:
        return svg  # rasterize as is rather than fail
    root = tree.getroot()
    storeys = [g for g in root if g.get("class") == "IfcBuildingStorey"]
    if len(storeys) > 1:
        keep = max(storeys, key=len)
        for g in storeys:
            if g is not keep:
                root.remove(g)
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


async def produce(fmt, view, size, src, workdir, deadline):
    if fmt == "glb" or (fmt == "png" and view == "3d"):
        glb = workdir / "model.glb"
        await run(ifcconvert(src, glb), deadline)
        if fmt == "glb":
            return expect(glb)
        png = workdir / "model.png"
        await run([sys.executable, str(RENDER_SCRIPT), str(expect(glb)), str(png), str(size)], deadline)
        return expect(png)

    if fmt in ("obj", "objzip"):
        obj = workdir / "model.obj"
        await run(ifcconvert(src, obj), deadline)
        expect(obj)
        if fmt == "obj":
            return obj
        archive = workdir / "model.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(obj, obj.name)
            mtl = obj.with_suffix(".mtl")
            if mtl.exists():
                z.write(mtl, mtl.name)
        return archive

    # svg, or png of the floor plan
    svg = workdir / "model.svg"
    await run(ifcconvert(src, svg, *SVG_OPTIONS), deadline)
    if fmt == "svg":
        return expect(svg)
    plan = await asyncio.to_thread(main_storey_svg, expect(svg), workdir / "plan.svg")
    png = workdir / "model.png"
    await run(["rsvg-convert", "-w", str(size), "-b", "white", "-o", str(png), str(plan)], deadline)
    return expect(png)


@app.get("/health")
def health():
    if not IFCCONVERT_VERSION:
        return JSONResponse({"status": "error", "detail": "IfcConvert not runnable"}, status_code=503)
    return {"status": "ok", "ifcconvert": IFCCONVERT_VERSION}


@app.post("/convert")
async def convert(request: Request):
    started = time.monotonic()
    fmt = request.query_params.get("format", "").lower()
    view = request.query_params.get("view", "3d").lower()
    size_param = request.query_params.get("size", "1024")
    workdir = Path(tempfile.mkdtemp(prefix="ifc-"))
    status, received = 500, 0
    try:
        if fmt not in MEDIA_TYPES:
            raise ConversionError(400, f"format must be one of: {', '.join(MEDIA_TYPES)}")
        if view not in VIEWS:
            raise ConversionError(400, f"view must be one of: {', '.join(VIEWS)}")
        if not size_param.isdigit() or not 64 <= int(size_param) <= 4096:
            raise ConversionError(400, "size must be an integer between 64 and 4096")
        src = workdir / "model.ifc"
        received = await save_body(request, src)
        check_ifc(src, received)
        async with semaphore:
            deadline = time.monotonic() + CONVERT_TIMEOUT_S
            result = await produce(fmt, view, int(size_param), src, workdir, deadline)
        status = 200
        return FileResponse(result, media_type=MEDIA_TYPES[fmt], filename=result.name,
                            background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True))
    except ConversionError as e:
        status = e.status
        shutil.rmtree(workdir, ignore_errors=True)
        return PlainTextResponse(e.message + "\n", status_code=e.status)
    except Exception:
        log.exception("unexpected error")
        shutil.rmtree(workdir, ignore_errors=True)
        return PlainTextResponse("internal error, see the ifc-converter logs\n", status_code=500)
    finally:
        log.info("convert format=%s view=%s in=%dB status=%d time=%.2fs",
                 fmt or "-", view, received, status, time.monotonic() - started)
