nuxeo-labs-ifc-converter
========================

> [!CAUTION]
> This is **Work in Progress**. ⚠️ Do not use as is for now ⚠️.
>
> Once ready it will be forked to `nuxeo-sandbox`and archived here.

<hr>

## TL;DR

**What it is.** A small HTTP service converting an **IFC** file (BIM/CAD, IFC-SPF only) to **GLB**, **OBJ**,
**SVG** (floor plan) or **PNG** (preview). It ships as a Docker image **you build yourself** from this
repository, and runs in its own container **next to** Nuxeo. The Nuxeo image is never modified.

**How Nuxeo uses it.** Nuxeo calls the service with `curl`, from a `CommandLineConverter` contribution, and
gets the converted file back:

```bash
curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=png" -o preview.png
```

From Automation, `Blob.RunConverter` then returns the rendition you need (thumbnail, source for a 3D viewer,
floor plan…). The ready-to-copy XML contributions are in [Usage from Nuxeo](#usage-from-nuxeo).

**The API** is one endpoint, `POST /convert?format=…`, with the IFC as the **raw request body**
(plus `GET /health`):

| `format` | What you get | Typical use |
|---|---|---|
| `glb` | Binary glTF, one file, colors included | Web 3D viewer (recommended: ~20× smaller than OBJ) |
| `obj` / `objzip` | The `.obj` alone, or a zip with `.obj` + `.mtl` | Pipelines that require OBJ |
| `svg` | Vector floor plans, one `<g>` layer per storey | Printable / zoomable plans |
| `png` | `view=3d` isometric (default) or `view=plan`; `size` 64–4096, default 1024 | Thumbnails, previews |

Failures come back as **plain text** with a meaningful status (`400` bad input, `413` too large, `500`
conversion failed, `504` timeout), so `curl -f` fails and Nuxeo reports the error instead of storing it.

**Deploying it** takes three steps: copy the `ifc-converter` folder next to your `docker-compose.yml`, add
the `ifc-converter` service there (build context `./ifc-converter`, `expose: 8080`, **no** `ports:`), then
`docker compose up -d --build ifc-converter`. Check it with
`docker compose exec nuxeo curl -s http://ifc-converter:8080/health`. The first build downloads about 1 GB
and the image is about 1.4 GB (VTK is the biggest part).

**What is inside.** Debian 13 (IfcOpenShell 0.9 needs glibc 2.38; Oracle Linux 9, the Nuxeo base image, has
2.34), IfcConvert for the geometry, PyVista/VTK for the headless 3D render (Mesa llvmpipe, CPU only, no GPU
and no X server), `rsvg-convert` for SVG → PNG, FastAPI/uvicorn for the HTTP layer. Four environment
variables tune it: `MAX_UPLOAD_MB` (500), `CONVERT_TIMEOUT_S` (150), `MAX_CONCURRENT` (2), `IFC_THREADS` (4).

**Security.** The service has **no authentication** and processes files uploaded by users: never give it a
`ports:` mapping in production, only the containers of the compose network must reach it. It runs as a
non-root user, on a read-only filesystem with a `/tmp` volume, every tool in a killable subprocess, with an
upload size limit and a concurrency limit. Logs hold metadata only, never file content.

**Licensing, in one line:** building the image and running it **inside your organization creates no
obligation** (nothing is AGPL, and the 3 GPL CGAL plugins shipped by IfcConvert are deleted at build time);
**do not redistribute the built image** — share this repository instead. Details in
[Licenses](#licenses) and [THIRD-PARTY-NOTICES.md](ifc-converter/THIRD-PARTY-NOTICES.md).

**Known limits.** Only IFC-SPF is accepted (no ifcXML, no ifcZIP). The floor plan only makes sense for
buildings with storeys: for infrastructure or a single piece of equipment, use the 3D PNG. GLB is Y-up (glTF
standard), OBJ keeps IFC's Z-up.

## Usage

* Add the `ifc-converter` service to your docker-compose (so it creates the Docker image and spreads a container from it, on the same VM as Nuxeo for direct http access)
* Then, contribute XML extension(s) to the CommandLineConverter service.
* From Automation, use `Blob.RunConverter` to get the rendition you need.

### Build/Deploy the `ifc-converter` Docker Image

* **Create/Deploy**

  * Copy the whole `ifc-converter` folder to your docker-compose folder, next to your `docker-compose.yml`
    (for example, clone the repository into that folder).
  * Update your `docker-compose.yml` file, add the `ifc-converter` service:

```yml
services:
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
  . . . other volumes . . .
  ifc-converter-tmp:
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

Nuxeo needs three contributions: the `.ifc` mime type (Nuxeo doesn't know it), one `curl` command line, and
one converter per format. Everything below goes in your own Studio project or plugin, nothing is installed in
Nuxeo by this repository.

`curl` is already in the Nuxeo image, no extra installation is needed. Check it with
`docker compose exec nuxeo curl --version`.

#### 1. Register the mime types

Nuxeo has no mime type for `.ifc`, `.glb` or `.obj`. Without this contribution an uploaded IFC is stored as
`text/plain` (IFC is a text format) and no converter is ever selected.

There is no IANA mime type for IFC; `model/ifc` below is a de facto choice. Any value works as long as the
same one is used in the `<sourceMimeType>` of the converters.

```xml
<extension target="org.nuxeo.ecm.platform.mimetype.service.MimetypeRegistryService" point="mimetype">

  <mimetype normalized="model/ifc" binary="false" iconPath="application.png">
    <mimetypes>
      <mimetype>model/ifc</mimetype>
      <mimetype>application/x-ifc</mimetype>
      <mimetype>application/x-step</mimetype>
    </mimetypes>
    <extensions>
      <extension>ifc</extension>
    </extensions>
  </mimetype>

  <mimetype normalized="model/gltf-binary" binary="true" iconPath="application.png">
    <mimetypes>
      <mimetype>model/gltf-binary</mimetype>
    </mimetypes>
    <extensions>
      <extension>glb</extension>
    </extensions>
  </mimetype>

  <mimetype normalized="model/obj" binary="false" iconPath="application.png">
    <mimetypes>
      <mimetype>model/obj</mimetype>
    </mimetypes>
    <extensions>
      <extension>obj</extension>
    </extensions>
  </mimetype>

</extension>

<extension target="org.nuxeo.ecm.platform.mimetype.service.MimetypeRegistryService" point="extension">
  <!-- Takes precedence over content sniffing, which sees IFC as plain text -->
  <fileExtension name="ifc" mimetype="model/ifc" ambiguous="false" />
  <fileExtension name="glb" mimetype="model/gltf-binary" ambiguous="false" />
  <fileExtension name="obj" mimetype="model/obj" ambiguous="false" />
</extension>
```

`image/png`, `image/svg+xml` and `application/zip` are already registered by Nuxeo.

#### 2. Register the `curl` command line

One command is enough for every format: the query string is passed as a parameter. The `<require>` must be a
direct child of your `<component>`, it makes sure the default command line contributions are loaded first.

```xml
<require>org.nuxeo.ecm.platform.commandline.executor.service.defaultContrib</require>

<extension target="org.nuxeo.ecm.platform.commandline.executor.service.CommandLineExecutorComponent"
           point="command">

  <command name="ifcConverter" enabled="true">
    <commandLine>curl</commandLine>
    <parameterString>-sf --max-time 170 -o #{targetFilePath} --data-binary @#{sourceFilePath} #{serviceUrl}/convert?#{query}</parameterString>
    <testParameterString>--version</testParameterString>
    <timeout>180s</timeout>
    <installationDirective>curl must be available in the Nuxeo container, and the ifc-converter container must be reachable.</installationDirective>
  </command>

</extension>
```

Points that matter:

- `enabled="true"` is **required**: the default is `false` and the command would be silently ignored.
- `#{sourceFilePath}` (the uploaded IFC, written to a temp file) and `#{targetFilePath}` (the file to produce)
  are provided by `CommandLineConverter`. `#{serviceUrl}` and `#{query}` come from the converters below.
- `-f` is **required**: without it `curl` exits 0 on an HTTP 400/500 and Nuxeo would store the plain-text
  error message as if it were the converted file. With `-f`, `curl` exits 22, the conversion fails and the
  service's error message ends up in the `ConversionException`.
- `-o #{targetFilePath}` is **required** too: the converter collects the files written in the output
  directory, it ignores the command's standard output.
- Nuxeo runs the command as a real process, not through a shell, so `?`, `&` and `=` are never interpreted.
  In the XML, `&` must still be written `&amp;` (see the converters below).
- **Timeouts must increase along the chain**: `CONVERT_TIMEOUT_S` (150 s, in the container) <
  `curl --max-time` (170 s) < the command `<timeout>` (180 s) < the transaction time to live
  (`nuxeo.db.transactiontimeout`, 300 s by default). Nuxeo caps the command at the *remaining* transaction
  time, so a conversion started late in a long transaction can still be killed (exit code 137). Big models
  are better converted in an asynchronous listener or a worker.

#### 3. Register one converter per format

```xml
<extension target="org.nuxeo.ecm.core.convert.service.ConversionServiceImpl" point="converter">

  <converter name="ifc2glb" class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>model/gltf-binary</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifcConverter</parameter>
      <parameter name="serviceUrl">http://ifc-converter:8080</parameter>
      <parameter name="query">format=glb</parameter>
    </parameters>
  </converter>

  <converter name="ifc2png" class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>image/png</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifcConverter</parameter>
      <parameter name="serviceUrl">http://ifc-converter:8080</parameter>
      <parameter name="query">format=png&amp;view=3d&amp;size=1024</parameter>
    </parameters>
  </converter>

  <converter name="ifc2plan" class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>image/png</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifcConverter</parameter>
      <parameter name="serviceUrl">http://ifc-converter:8080</parameter>
      <parameter name="query">format=png&amp;view=plan&amp;size=2048</parameter>
    </parameters>
  </converter>

  <converter name="ifc2svg" class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>image/svg+xml</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifcConverter</parameter>
      <parameter name="serviceUrl">http://ifc-converter:8080</parameter>
      <parameter name="query">format=svg</parameter>
    </parameters>
  </converter>

  <converter name="ifc2objzip" class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>application/zip</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifcConverter</parameter>
      <parameter name="serviceUrl">http://ifc-converter:8080</parameter>
      <parameter name="query">format=objzip</parameter>
    </parameters>
  </converter>

</extension>
```

#### 4. Call it from Automation

```js
function run(input, params) {
  var glb = Blob.RunConverter(input, {
    'converter': 'ifc2glb',
    'parameters': { 'targetFileName': 'model.glb' }
  });
  return glb;
}
```

`targetFileName` is optional but recommended: it gives the result blob a readable name instead of a
temporary one.

> [!NOTE]
> The converter parameters declared in the XML **win over** those passed at run time, so `query` cannot be
> overridden from Automation. To choose the format or the size at run time, declare one converter without a
> `query` parameter and pass the whole `query` (for example `format=png&view=3d&size=2048`) in the
> `parameters` of `Blob.RunConverter`.

Conversions are cached by Nuxeo on the blob plus the parameters: converting the same IFC twice with the same
parameters runs `curl` only once.

## Tune Your Docker-Compose

* **Settings (environment variables)**

| Variable | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_MB` | 500 | Maximum IFC size |
| `CONVERT_TIMEOUT_S` | 150 | Maximum time for one conversion (all steps) |
| `MAX_CONCURRENT` | 2 | Conversions running at the same time; extra requests wait their turn |
| `IFC_THREADS` | 4 | Threads used by IfcConvert for each conversion |

Each request is logged on one line: `convert format=png view=3d in=92542B status=200 time=0.65s`
(`docker compose logs ifc-converter`).

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

From the repository root (the `Dockerfile` is in the `ifc-converter` folder, hence the build context):

```bash
docker build -t ifc-converter ./ifc-converter
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
  The full list is in [THIRD-PARTY-NOTICES.md](ifc-converter/THIRD-PARTY-NOTICES.md).
- The build removes 3 optional IfcConvert plugins that contain GPL-3.0 code (CGAL). This service doesn't use them.
- **Building the image and running it inside your organization creates no obligation** (none of the components
  is AGPL). **Do not push the built image to a public registry or give it to another company**: that would be
  distributing it, with the obligations listed in THIRD-PARTY-NOTICES.md. Share this repository instead.


## About Nuxeo

Nuxeo Platform is an open source highly scalable, cloud-native, enterprise content management product with rich multimedia support, written in Java. Data can be stored in both SQL & NoSQL databases.

The development of the Nuxeo Platform is mostly done by Nuxeo employees with an open development model.

The source code, documentation, roadmap, issue tracker, testing, benchmarks are all public.

More information is available at [Hyland/Nuxeo](https://www.hyland.com/en/solutions/products/nuxeo-platform).

