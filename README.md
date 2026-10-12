nuxeo-labs-ifc-converter
========================

> [!CAUTION]
> This is **Work in Progress**. ⚠️ Do not use as is for now ⚠️.
>
> Once ready it will be forked to `nuxeo-sandbox`and archived here.

<hr>

These tools allow for converting a **IFC file to GLB**, **OBJ**, **SVG** (floor plan) or **PNG** (preview).

* Build/Deploy a Docker image/container that deploys a small HTTP service that performs the conversion
* Run the container next to Nuxeo: Nuxeo sends the IFC file with `curl` and gets the converted
file back. The Nuxeo image is not modified.

Once deployed, your Nuxeo instance can use a `CommandLineConverter` with `curl` (see below) to get the rendition of the IFC file.

> [!IMPORTANT]
> This repository contains only source files: **you build the image yourself**, nothing is published to a
registry. See [Licenses](#licenses). If you _publish_ the image you must check the licensing.

## Usage

* Add the `ifc-converter` service to your docker-compose (so it creates the Docker image and spreads a container from it, on the same VM as Nuxeo for direct http access)
* Then, contribute XML extension(s) to the CommandLineConverter service.
* From Automation, use `Blob.RunConverter` to get the rendition you need.

### Build/Deploy the `ifc-converter` Docker Image

* **Create/Deploy**

  * Copy the whole `ifc-converter` folder to your docker-compose folder (next to your `docker-compose.yml)`
   (for example, clone the repository into that folder).)
  * Update your `docker-compose.yml` file, add the ` ifc-converter` service:

```yml
services
  nuxeo:
    . . .
  ifc-converter:
    build:
      context: ./ifc-converter
    image: ifc-converter
    hostname: ifc-converter
    restart: unless-stopped
    logging: *default-logging
    expose:
      # HTTP API, reachable only by the other containers (no "ports:" on purpose: no authentication)
      - 8080
    mem_limit: 4g
    cpus: 2
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    volumes:
      - ifc-converter-tmp:/tmp
    # Optional, defaults are:
    # environment:
    #   - MAX_UPLOAD_MB=500
    #   - CONVERT_TIMEOUT_S=150
    #   - MAX_CONCURRENT=2
    #   - IFC_THREADS=4
  . . . other services . . .
volumes:
  . . . other vooumes . . .
  ifc-converter-tmp
```

  * Optional: add `ifc-converter` to the `depends_on:` list of the `nuxeo` service (short form), so that
   `docker compose up nuxeo` also starts it. Don't use `condition: service_healthy`: Nuxeo would not start
   when the converter is unhealthy, while it only needs it to convert IFC files.

* **Build, Start**

If your Nuxeo/Mongo/etc. containers were already running:

```bash
docker compose up -d --build ifc-converter
```

> [!NOTE]
> The first build downloads about 1 GB (VTK is the biggest part); the image is about 1.4 GB.

* **Check** that Nuxeo can reach it:

```bash
docker compose exec nuxeo curl -s http://ifc-converter:8080/health
```

Expected: `{"status":"ok","ifcconvert":"IfcOpenShell IfcConvert 0.9.0alpha0-8c614fa"}`

#### API

`POST /convert?format=<format>[&view=3d|plan][&size=1024]` with the IFC file as the **raw request body**.

| `format` | Returns | Content-Type |
|---|---|---|
| `glb` | Binary glTF, one file, colors included | `model/gltf-binary` |
| `obj` | The `.obj` alone (no colors: the `.mtl` is not included) | `model/obj` |
| `objzip` | Zip with `model.obj` + `model.mtl` (colors) | `application/zip` |
| `svg` | 2D floor plans (walls cut, rooms named, door arcs), one layer (`<g class="IfcBuildingStorey">`) per storey | `image/svg+xml` |
| `png` | Preview image. `view=3d` (default): isometric 3D render. `view=plan`: the floor plan of the storey with the most elements. `size` = width in pixels, 64 to 4096, default 1024 | `image/png` |

`GET /health` returns `{"status":"ok", ...}` (used by the Docker healthcheck).

**`curl` examples (from the Nuxeo container)**

Use `-f` so curl exits with an error code (22) when the conversion fails.

```bash
curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=png" -o preview.png

curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=png&view=plan&size=2048" -o plan.png

curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=glb" -o model.glb

curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=objzip" -o model.zip

curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=svg" -o plan.svg
```

#### Errors

Errors come back as plain text explaining the problem (without `-f`, curl writes it to the output file).

| Status | When |
|---|---|
| 400 | Empty body, not an IFC file (no `ISO-10303-21` header; ifcXML and ifcZIP are not supported), unknown `format`/`view`, invalid `size` |
| 413 | File larger than `MAX_UPLOAD_MB` |
| 500 | The conversion failed or produced nothing (e.g. no geometry); the body has the end of the tool's log |
| 504 | The conversion took longer than `CONVERT_TIMEOUT_S` (the process is killed) |


### Usage from Nuxeo

You need to register a CommandLineCOnvert that `curl` to the `ifc-converter` container

## Tune Your Docker-Compose

* **Settings (environment variables)**

| Variable | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_MB` | 500 | Maximum IFC size |
| `CONVERT_TIMEOUT_S` | 300 | Maximum time for one conversion (all steps) |
| `MAX_CONCURRENT` | 2 | Conversions running at the same time; extra requests wait their turn |
| `IFC_THREADS` | 4 | Threads used by IfcConvert for each conversion |

Each request is logged on one line: `convert format=png view=3d in=92542B status=200 time=0.65s`
(`docker compose logs ifc-converter`).* **

* **Content**

| File | Role |
|---|---|
| `ifc-converter/Dockerfile` | Debian 13 image with [IfcConvert (IfcOpenShell)](https://docs.ifcopenshell.org/ifcconvert.html), [PyVista/VTK](https://tutorial.pyvista.org/) (headless rendering), [`rsvg-convert`](https://gitlab.gnome.org/GNOME/librsvg) and the service. Builds for the host architecture (arm64 on a Mac, x86_64 on EC2). |
| `ifc-converter/app.py` | The HTTP service (FastAPI + uvicorn) on port 8080. |
| `ifc-converter/render.py` | Renders a GLB/OBJ to PNG (isometric view), used by `app.py`. |
| `samples/` | Two public IFC files (CC BY 4.0) to try it. |
| `ifc-converter/THIRD-PARTY-NOTICES.md` | Licensing used in the image (summary: Business friendly). |

Why Debian and not Oracle Linux 9 (the Nuxeo base image): IfcOpenShell 0.9 needs glibc 2.38, Oracle Linux 9 has 2.34.

## Try ifc-converter without a Nuxeo Container

From the repository folder:

```bash
docker build -t ifc-converter .
```

```bash
docker run --rm -d --name ifc-converter -p 127.0.0.1:18080:8080 ifc-converter
```

```bash
curl -sf --data-binary @samples/Duplex_A_20110907.ifc "http://localhost:18080/convert?format=png" -o duplex.png
```

```bash
docker stop ifc-converter
```

The port is published on `127.0.0.1` only, for this test. In a real deployment, don't publish it at all (see below).

## Good to know

- **GLB rather than OBJ**: GLB is one file with the colors, and it is much smaller (2.3 MB vs 47.7 MB for the Gymzaal sample).
- **Orientation**: GLB is Y-up (glTF standard). OBJ keeps IFC's Z-up; if a viewer shows the OBJ lying on its side, prefer GLB.
- **3D framing**: `render.py` ignores small objects far from the model (geo-reference markers, survey points).
  It groups objects closer than 5 m (or 10% of the model size) and frames the group with the most objects.
- **Floor plan**: only meaningful for buildings with storeys. For other models (infrastructure, single equipment)
  the plan can be empty or a filled shape; use the 3D PNG.
- **Security**: the service has no authentication and processes uploaded files. Keep it without a `ports:` mapping,
  so only containers on the compose network can reach it.
- **Upgrading IfcConvert**: change `ARG IFCCONVERT_VERSION` in the `Dockerfile` and rebuild.


## Support
**These features are not part of the Nuxeo Production platform.**

These solutions are provided for inspiration and we encourage customers to use them as code samples and learning
resources.

This is a moving project (no API maintenance, no deprecation process, etc.) If any of these solutions are found to be
useful for the Nuxeo Platform in general, they will be integrated directly into platform, not maintained here.

## Licenses

### This Repository's Code

This repository's code is licensed under the [Apache License, Version 2.0](http://www.apache.org/licenses/LICENSE-2.0).

### Sample Files

The files in `samples/` are licensed under CC BY 4.0, see [samples/README.md](samples/README.md).

### Other

- The repository contains no third-party software. Building the image downloads open-source components, each
  under its own license: IfcConvert/IfcOpenShell (LGPL-3.0), VTK (BSD-3-Clause), PyVista (MIT), FastAPI (MIT),
  uvicorn (BSD-3-Clause), Mesa (MIT), librsvg (LGPL-2.1+), Debian packages, etc.
  The full list is in [THIRD-PARTY-NOTICES.md](`ifc-converter/THIRD-PARTY-NOTICES.md).
- The build removes 3 optional IfcConvert plugins that contain GPL-3.0 code (CGAL). This service doesn't use them.
- **Building the image and running it inside your organization creates no obligation** (none of the components
  is AGPL). **Do not push the built image to a public registry or give it to another company**: that would be
  distributing it, with the obligations listed in THIRD-PARTY-NOTICES.md. Share this repository instead.


## About Nuxeo

Nuxeo Platform is an open source highly scalable, cloud-native, enterprise content management product with rich multimedia support, written in Java. Data can be stored in both SQL & NoSQL databases.

The development of the Nuxeo Platform is mostly done by Nuxeo employees with an open development model.

The source code, documentation, roadmap, issue tracker, testing, benchmarks are all public.

More information is available at [Hyland/Nuxeo](https://www.hyland.com/en/solutions/products/nuxeo-platform).

