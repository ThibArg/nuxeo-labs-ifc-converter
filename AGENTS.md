# AGENTS.md

Instructions for AI coding agents working on this repository. `README.md` is the user documentation;
keep both consistent.

## What this is

A small HTTP service converting an IFC file to GLB, OBJ, SVG (floor plan) or PNG (preview). It runs as its
own container next to Nuxeo, which calls it with `curl --data-binary @file.ifc`. This repository is
**source only**: each user builds their own image. No image is published.

| File | Role |
|---|---|
| `ifc-converter/Dockerfile` | Debian 13 image: IfcConvert (official IfcOpenShell zip), Mesa EGL, `rsvg-convert`, Python venv, the service |
| `ifc-converter/app.py` | FastAPI service: streams the body to a temp dir, runs the tools as subprocesses, returns the file |
| `ifc-converter/render.py` | GLB/OBJ → PNG with PyVista/VTK, headless (EGL + Mesa llvmpipe), isometric view |
| `ifc-converter/THIRD-PARTY-NOTICES.md` | Apache-2.0 for this code; licenses of everything the build downloads |
| `samples/` | Public IFC files (CC BY 4.0), credited in `samples/README.md` |

The image sources live in `ifc-converter/`, which is also the Docker build context: the user copies that
folder next to their `docker-compose.yml`. `samples/` and `README.md` stay at the repository root and are
not part of the image.

## Repo facts

- No CI, no test suite, no build step for the repository itself. The only verification is the "Build, run,
  verify" procedure below; don't look for a Makefile, a workflow or a package manifest.
- `AGENTS.md` is committed on purpose here and must **not** be added to `.gitignore`.
- Work happens directly on `master`, and `README.md` still carries a work-in-progress banner. Don't remove
  that banner on your own initiative.
- Runtime knobs, read once at import (`app.py` top), so changing one needs a container restart:
  `MAX_UPLOAD_MB=500`, `CONVERT_TIMEOUT_S=150`, `MAX_CONCURRENT=2`, `IFC_THREADS=4`.
- **No `LICENSE` file, on purpose**: the Apache-2.0 licensing is stated in the "Licenses" section of
  `README.md` and at the top of `THIRD-PARTY-NOTICES.md`. Don't add one. Don't turn those pointers into
  relative links either: `THIRD-PARTY-NOTICES.md` is copied into the image (`Dockerfile`) and ships alone
  with the `ifc-converter/` folder, where `README.md` and `samples/` do not exist.

## Hard rules

- **Docker**: ask the user before building, rebuilding or pulling an image (a build downloads about 1 GB and
  takes minutes), and before deleting any Docker object. If no image is available to test with, stop and
  ask. Never use `docker image prune` / `docker system prune`: they also delete other projects' images.
- **Nothing third-party in the repo**: no binaries, wheels, built images or vendored code. The build
  downloads them.
- **No customer or prospect data**: never commit IFC files or outputs received from users. Add a sample only
  if its license allows redistribution, and credit it in `samples/README.md`.
- **No sensitive information** in any file: no secrets, tokens, internal URLs or hostnames, personal paths,
  user names, customer or prospect names.
- **Licenses**: no AGPL dependency. New dependencies must be permissive, or LGPL used unmodified. Update
  `THIRD-PARTY-NOTICES.md` whenever what the image contains changes.
- **No GPL code in the image**: the Dockerfile deletes IfcConvert's 3 CGAL-based plugins
  (`ifcopenshell_geometry_kernel_cgal.so`, `..._kernel_cgalsimple.so`, `..._svgfill.so`, GPL-3.0). Keep it
  that way and never use `--kernel cgal`; the default OpenCASCADE kernel is used.
- **Stable API**: Nuxeo integrations depend on `POST /convert?format=glb|obj|objzip|svg|png[&view=3d|plan][&size=N]`,
  the raw request body, the content types, the status codes (400, 413, 500, 504) and plain-text error bodies
  (so `curl -f` fails). Only add optional parameters; don't change existing behavior.
- **Security model**: no authentication, so the service must never publish a port in production. Keep it
  non-root, working on a read-only filesystem with a `/tmp` volume, every tool run as a subprocess with a
  timeout, the upload size limit and the concurrency limit. Log metadata only (format, size, status,
  duration), never file content.
- **New source files** start with:
  `# SPDX-License-Identifier: Apache-2.0` and `# Copyright 2026 Hyland Software, Inc.`

## Why things are the way they are

- **Debian 13**: IfcOpenShell 0.9 needs glibc ≥ 2.38. It doesn't run on Oracle Linux 9 (the Nuxeo base
  image, glibc 2.34) or Debian 12 (2.36). The PyPI `ifcopenshell` 0.9.0 wheel is tagged `manylinux_2_31`
  but also needs 2.38.
- **SVG options**: for SVG, IfcConvert includes only `IfcSpace` by default. An explicit
  `--exclude entities IfcOpeningElement` replaces that default, so walls, slabs, doors are drawn.
  `--include`/`--exclude` must not be the last option before the input file ("Input file not specified").
- **SVG storeys**: the SVG has one `<g class="IfcBuildingStorey">` layer per storey, all at the same place.
  The plan PNG keeps only the storey with the most elements (`main_storey_svg` in `app.py`); the SVG output
  keeps them all. `--auto-elevation` produced empty SVGs with IfcConvert 0.9.0.
- **Orientation and size**: GLB is Y-up (glTF), OBJ keeps IFC's Z-up. OBJ is far bigger than GLB
  (47.7 MB vs 2.3 MB for the Gymzaal sample).
- **3D framing**: IFC files often contain small objects far from the model (geo-reference markers, survey
  points). `render.py` groups objects closer than max(5 m, 10% of the model diagonal) and frames the group
  with the most objects.
- **Headless rendering**: EGL + Mesa llvmpipe (CPU), no X server, no GPU. `VTK_DEFAULT_OPENGL_WINDOW` skips
  the X11 probe; `HOME` and `MPLCONFIGDIR` point to `/tmp` because the filesystem is read-only.
- **Comparing outputs**: IfcConvert's `-j` comes from `IFC_THREADS`, and with more than one thread its
  output order changes from run to run. Run the container with `-e IFC_THREADS=1` to get byte-identical
  files between two runs; any other value makes a checksum comparison meaningless.
- **Timeout accounting**: `CONVERT_TIMEOUT_S` is a deadline armed *after* the request acquires the
  concurrency semaphore (`convert()` in `app.py`), not when it arrives. A request queued behind
  `MAX_CONCURRENT` others can therefore take much longer than `CONVERT_TIMEOUT_S` wall-clock, which is
  why the client timeout has to be the larger one.

## Build, run, verify

There is no automated test suite: this procedure is the test. Build only after the user agreed, and use the
image tag the user gives you (`ifc-converter` below is an example).

Run `docker ps` first: another project's compose stack may already be running an `ifc-converter` container.
Never stop or reuse a container you did not start, and pick a port nothing else uses.

**A change limited to `app.py` or `render.py` needs no rebuild**: mount the files over `/app` in an
existing image and restart the container. Use this for every Python iteration and only rebuild when the
`Dockerfile` changes.

```bash
docker run --rm -d --name ifc-converter-check -p 127.0.0.1:18080:8080 \
  -v "$PWD/ifc-converter/app.py:/app/app.py:ro" -v "$PWD/ifc-converter/render.py:/app/render.py:ro" \
  ifc-converter:latest
```

Build, from the repository root — the build context is `ifc-converter/`, not the root (on Apple silicon, the
amd64 build is emulated and about 3× slower):

```bash
docker build -t <image> ./ifc-converter
docker build --platform linux/amd64 -t <image-for-amd64> ./ifc-converter
```

Run a temporary container, published on localhost only. `/health` returns 503 when IfcConvert is not
runnable, so check for `"status":"ok"`, not just for a reply:

```bash
IMAGE=ifc-converter   # the tag confirmed by the user
docker run --rm -d --name ifc-converter-check -p 127.0.0.1:18080:8080 "$IMAGE"
curl -s http://127.0.0.1:18080/health
```

All formats on all samples (every line must show 200; then check the types with `file`):

```bash
OUT=$(mktemp -d)
for f in samples/*.ifc; do
  n=$(basename "$f" .ifc)
  for spec in glb:glb obj:obj objzip:zip svg:svg png:png "png&view=plan:plan.png"; do
    q=${spec%%:*}; ext=${spec##*:}
    curl -s -o "$OUT/$n.$ext" -w "$n $q %{http_code} %{time_total}s\n" \
      --data-binary @"$f" "http://127.0.0.1:18080/convert?format=$q"
  done
done
file "$OUT"/*
```

Look at the PNGs: the 3D view must show the whole building, centered; the plan must show one storey.

Errors (each must print 400):

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST --data-binary @/dev/null "http://127.0.0.1:18080/convert?format=glb"
printf 'hello' | curl -s -o /dev/null -w '%{http_code}\n' --data-binary @- "http://127.0.0.1:18080/convert?format=glb"
curl -s -o /dev/null -w '%{http_code}\n' --data-binary @samples/Duplex_A_20110907.ifc "http://127.0.0.1:18080/convert?format=pdf"
curl -s -o /dev/null -w '%{http_code}\n' --data-binary @samples/Duplex_A_20110907.ifc "http://127.0.0.1:18080/convert?format=png&size=10"
```

Production shape: in `docker-compose.yml` the service runs `read_only: true` with a `/tmp` volume and all
capabilities dropped, which a plain `docker run` does not exercise. Any code writing outside `/tmp` passes
the tests above and fails in production, so re-run at least one conversion per format this way:

```bash
docker run --rm -d --name ifc-converter-ro -p 127.0.0.1:18081:8080 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true "$IMAGE"
curl -s http://127.0.0.1:18081/health
```

No CGAL in the image (both counts must be 0; the IfcConvert binary itself only mentions CGAL in its help text):

```bash
docker exec ifc-converter-check sh -c 'ls /opt/ifcconvert | grep -ci -e cgal -e svgfill; grep -l CGAL /opt/ifcconvert/*.so* | wc -l'
```

Python packages and licenses, to compare with `THIRD-PARTY-NOTICES.md`:

```bash
docker run --rm --entrypoint python "$IMAGE" -c "import importlib.metadata as m; [print(d.metadata['Name'], d.version, d.metadata.get('License-Expression') or '; '.join(c.split('::')[-1].strip() for c in (d.metadata.get_all('Classifier') or []) if c.startswith('License'))) for d in sorted(m.distributions(), key=lambda d: d.metadata['Name'].lower())]"
```

Stop the container (it is removed automatically):

```bash
docker stop ifc-converter-check
```

## Upgrading

Upgrades need a rebuild: ask the user first. After any upgrade, run the whole "Build, run, verify"
procedure, then update `THIRD-PARTY-NOTICES.md` and, if they changed, the image size and the IfcConvert
version shown in `README.md`.

- **Debian (security fixes)**: rebuild with a fresh base image, `docker build --pull ...`. Debian 13 has full
  security support until August 2028, then LTS until June 2030; move to the next Debian release before that.
- **IfcConvert**: change `ARG IFCCONVERT_VERSION` in the `Dockerfile`. Releases:
  https://github.com/IfcOpenShell/IfcOpenShell/releases?q=ifcconvert. Then check that:
  - the binary runs on the base image: `docker run --rm --entrypoint sh "$IMAGE" -c 'ldd /opt/ifcconvert/IfcConvert | grep "not found"'`
    prints nothing;
  - the 3 CGAL plugins still have the same names (otherwise the `rm` fails and so does the build) and no new
    GPL component was added to the zip;
  - the SVG options used in `app.py` (`SVG_OPTIONS`) still exist: `IfcConvert --help`.
- **Python**: only `vtk`, `pyvista`, `fastapi` and `uvicorn` are pinned in the `Dockerfile`; their
  dependencies are resolved at build time. Check what is outdated with
  `docker run --rm --entrypoint pip "$IMAGE" list --outdated`.

## Out of scope

- The Nuxeo side (mime types, command line, converters, automation, UI) is configured in Nuxeo, not in this
  repository. `README.md` documents it as a ready-to-copy example; no Nuxeo code or bundle is built here.
  Keep that example in sync with the service API, and don't simplify away the parts that look redundant.
  The semantics below are verified against the LTS 2025 sources, they are the reason each part is there:
  - `enabled="true"`: the default is `false` and the command is silently ignored.
  - `-o #{outDirPath}/nxblob-preview.<ext>`: without `-o`, `CommandLineConverter` lists `#{outDirPath}` and
    turns **every** file it finds there into a result blob. The `nxblob-` prefix makes Nuxeo rename the
    rendition to the source base name plus the *first extension registered for the destination mime type*
    (`ConversionServiceImpl.updateResultBlobFileName`), which is why the mime type contributions are
    required for correct naming.
  - `--fail-with-body` keeps the service's plain-text error (`-f` discards it); `-H "Expect:"` avoids
    curl's 100-continue handshake on large bodies; the IFC goes out as `--data-binary @#{sourceFilePath}`.
  - Timeout chain, each step longer than the previous one: `CONVERT_TIMEOUT_S` (150) < `curl --max-time`
    (170) < the command `<timeout>` (180s) < the transaction timeout (`nuxeo.db.transactiontimeout`, 300s
    by default), so the service answers 504 before the client gives up. `<timeout>` is parsed as a
    `Duration`, so its unit is mandatory (`180s`, not `180`), and Nuxeo enforces
    `min(<timeout>, remaining transaction TTL)` by prefixing the command with `timeout -s 9`.
- Publishing images to a registry: distributing the image brings license obligations
  (see `THIRD-PARTY-NOTICES.md`). This repository only ships source.
