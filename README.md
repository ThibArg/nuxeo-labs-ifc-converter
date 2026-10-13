nuxeo-labs-ifc-converter
========================

> [!IMPORTANT]
> This repository has moved to
> [nuxeo-sandbox/nuxeo-labs-ifc-converter](https://github.com/nuxeo-sandbox/nuxeo-labs-ifc-converter)
> and is archived. Please use the new location.

### TL;DR

* Provides a Docker container that converts (via a HTTP service) an `IFC` file to `GLB`, `OBJ`, `SVG`
  (floor plan), or `PNG` (preview).

> [!IMPORTANT]
> The converter supports only BIM/CAD and IFC-SPF

* You build yourself a Docker image ("ifc-converter") and deploy a container alongside Nuxeo (The Nuxeo
  image is never modified.)

* Nuxeo calls the service using `curl` from a `CommandLineConverter` contribution (Failures are returned
  as plain text with a meaningful HTTP status code) and `Blob.RunConverter` provides the desired rendition.

* [Deployment](#build-deploy)/[Usage](#usage-with-nuxeo):

  * Deployment:
    * Copy the `ifc-converter` folder next to your `docker-compose.yml`
    * Add the `ifc-converter` service to your `docker-compose.yml`
    * Then either deploy the whole stack or just this container if the rest is already running)
      * The first build downloads about 1 GB and the image is about 1.4 GB
  * Usage: Copy the misc. XML declarations and use `Blob.RunConverter`.

* **Security**. In current version, the service has no authentication and it processes files uploaded by users:
  * Never give it a `ports:` mapping in production
  * Only the containers of the compose network must reach it.

* Building the image and running it inside your organization creates no licensing obligation: **do not
  redistribute the built image**.

## Build-Deploy

### 1. Setup for Docker Compose

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

### 2. Build/Start

If your Nuxeo/Mongo/etc. containers were already running:

```bash
docker compose up -d --build ifc-converter
```

> [!NOTE]
> The first build downloads about 1 GB (VTK is the biggest part); the image is about 1.4 GB.

**Check Nuxeo can reach it** (here, the service name `nuxeo`)):

```bash
docker compose exec nuxeo curl -s http://ifc-converter:8080/health
```

Expected: `{"status":"ok","ifcconvert":"IfcOpenShell IfcConvert 0.9.0alpha0-8c614fa"}`

### 3. API

`POST /convert?format=<format>[&view=3d|plan][&size=1024]` with the IFC file as the **raw request body**.

| `format` | Returns | Content-Type |
|---|---|---|
| `glb` | Binary glTF, one file, colors included | `model/gltf-binary` |
| `obj` | The `.obj` alone (no colors: the `.mtl` is not included) | `model/obj` |
| `objzip` | Zip with `model.obj` + `model.mtl` (colors) | `application/zip` |
| `svg` | 2D floor plans (walls cut, rooms named, door arcs), one layer (`<g class="IfcBuildingStorey">`) per storey | `image/svg+xml` |
| `png` | Preview image. `view=3d` (default): isometric 3D render. `view=plan`: the floor plan of the storey with the most elements. `size` = width in pixels, 64 to 4096, default 1024 | `image/png` |

`GET /health` returns `{"status":"ok", ...}` (used by the Docker healthcheck).

### 4. `curl` examples (from the Nuxeo container)**

Use `-f` so curl exits with an error code (22) when the conversion fails.

```bash
curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=png" -o preview.png

curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=png&view=plan&size=2048" -o plan.png

curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=glb" -o model.glb

curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=objzip" -o model.zip

curl -sf --data-binary @model.ifc "http://ifc-converter:8080/convert?format=svg" -o plan.svg
```

### 5. Errors

Errors come back as plain text explaining the problem (without `-f`, curl writes it to the output file).

| Status | When |
|---|---|
| 400 | Empty body, not an IFC file (no `ISO-10303-21` header; ifcXML and ifcZIP are not supported), unknown `format`/`view`, invalid `size` |
| 413 | File larger than `MAX_UPLOAD_MB` |
| 500 | The conversion failed or produced nothing (e.g. no geometry); the body has the end of the tool's log |
| 504 | The conversion took longer than `CONVERT_TIMEOUT_S` (the process is killed). The caller must allow more time than `CONVERT_TIMEOUT_S`, otherwise it gives up before this answer is sent |


## Usage with Nuxeo

Nuxeo needs contributions to three services:

* The Mime-Type service
* The CommandLine service
* And the converter service

In all cases, create the XML and paste the contributions below as-is. You can - of course - centralize everying
in a single contribution if you prefer

> [!TIP]
> Conversions are cached by Nuxeo on the blob plus the parameters: converting the same IFC twice with the same
> parameters runs `curl` only once (as long as the file is still in the cache).


### 1. Register the mime types

Nuxeo has no mime type for `.ifc`, `.glb` or `.obj`. Without this contribution an uploaded IFC is stored as
`text/plain` (IFC is a text format) and no converter is ever selected.

> [!IMPORTANT]
> There is no IANA mime type for IFC; `model/ifc` below is a de facto choice. Any value works as long as the
> same one is used in the `<sourceMimeType>` of the converters.

```xml
<extension target="org.nuxeo.ecm.platform.mimetype.service.MimetypeRegistryService" point="mimetype">

  <mimetype normalized="model/ifc" binary="false" iconPath="file.png">
    <mimetypes>
      <mimetype>model/ifc</mimetype>
      <mimetype>application/x-ifc</mimetype>
      <mimetype>application/x-step</mimetype>
    </mimetypes>
    <extensions>
      <extension>ifc</extension>
    </extensions>
  </mimetype>

  <mimetype normalized="model/gltf-binary" binary="true" iconPath="file.png">
    <mimetypes>
      <mimetype>model/gltf-binary</mimetype>
      <mimetype>model/gltf_binary</mimetype>
    </mimetypes>
    <extensions>
      <extension>glb</extension>
    </extensions>
  </mimetype>

  <mimetype normalized="model/obj" binary="false" iconPath="file.png">
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

### 2. Register the misc. `ifc-to*` command lines

The `ifc-converter` HTTP servioce is not multipart, so everything must be passed in one shot as query parameters (can't use `-F` switch of `curl`for example). It makes it a bit more comple for endpoints which don't need a `view` and a `size`. This is why we register one command line per output.

> [!TIP]
> Prefixing the output with `nxblob-...` makes Nuxeo name the file with the original file + the correct extension. No need to pass a `destFileName` parameter 

> [!IMPORTANT]
> Of course, you can tune these as you wish. For example, the url is hard coded, you can adapt it or even pass it as a parameter (like `#{serviceUrl}`))

```xml
<extension target="org.nuxeo.ecm.platform.commandline.executor.service.CommandLineExecutorComponent"
           point="command">
  
  <!-- ifc-to-png requires to pass the view (3d or plan) and the size (>= 64, <= 4096) -->
  <command name="ifc-to-png" enabled="true">
    <commandLine>curl</commandLine>
    <parameterString>-sS --fail-with-body --max-time 170 -H "Expect:" -o #{outDirPath}/nxblob-preview.png --data-binary @#{sourceFilePath} "http://ifc-converter:8080/convert?format=png&amp;view=#{view}&amp;size=#{size}"</parameterString>
    <timeout>180s</timeout>
    <installationDirective>
      Start the "ifc-converter" service and make sure it is reachable at http://ifc-converter:8080/ from the Nuxeo container.
    </installationDirective>
  </command>

  <command name="ifc-to-svg" enabled="true">
    <commandLine>curl</commandLine>
    <parameterString>-sS --fail-with-body --max-time 170 -H "Expect:" -o #{outDirPath}/nxblob-preview.svg --data-binary @#{sourceFilePath} "http://ifc-converter:8080/convert?format=svg"</parameterString>
    <timeout>180s</timeout>
    <installationDirective>
      Start the "ifc-converter" service and make sure it is reachable at http://ifc-converter:8080/ from the Nuxeo container.
    </installationDirective>
  </command>

  <command name="ifc-to-glb" enabled="true">
    <commandLine>curl</commandLine>
    <parameterString>-sS --fail-with-body --max-time 170 -H "Expect:" -o #{outDirPath}/nxblob-preview.glb --data-binary @#{sourceFilePath} "http://ifc-converter:8080/convert?format=glb"</parameterString>
    <timeout>180s</timeout>
    <installationDirective>
      Start the "ifc-converter" service and make sure it is reachable at http://ifc-converter:8080/ from the Nuxeo container.
    </installationDirective>
  </command>

  <command name="ifc-to-obj" enabled="true">
    <commandLine>curl</commandLine>
    <parameterString>-sS --fail-with-body --max-time 170 -H "Expect:" -o #{outDirPath}/nxblob-preview.obj --data-binary @#{sourceFilePath} "http://ifc-converter:8080/convert?format=obj"</parameterString>
    <timeout>180s</timeout>
    <installationDirective>
      Start the "ifc-converter" service and make sure it is reachable at http://ifc-converter:8080/ from the Nuxeo container.
    </installationDirective>
  </command>

  <command name="ifc-to-objzip" enabled="true">
    <commandLine>curl</commandLine>
    <parameterString>-sS --fail-with-body --max-time 170 -H "Expect:" -o #{outDirPath}/nxblob-preview.zip --data-binary @#{sourceFilePath} "http://ifc-converter:8080/convert?format=objzip"</parameterString>
    <timeout>180s</timeout>
    <installationDirective>
      Start the "ifc-converter" service and make sure it is reachable at http://ifc-converter:8080/ from the Nuxeo container.
    </installationDirective>
  </command>
</extension>
```

Points that matter:

- `enabled="true"` is **required**: the default is `false` and the command would be silently ignored.
- `-o #{outDirPath}/nxblob-preview...etc..` is **required** too: Without it, the `CommandLineConverter`
   lists the content of `outDirPath`, turning every file found there into a result blob.
- **The timeouts form a chain, keep them in this order**:

  | Step | Value | Set in |
  |---|---|---|
  | The service gives up and answers `504` | `CONVERT_TIMEOUT_S` = 150s | `docker-compose.yml` (default) |
  | `curl` gives up | `--max-time 170` | the `<parameterString>` above |
  | Nuxeo kills `curl` | `<timeout>180s</timeout>` | the `<command>` above |
  | The transaction expires | 300s | `nuxeo.db.transactiontimeout` |

  Each step must be longer than the one above it, so that a conversion that takes too long comes back as the
  service's plain-text `504` instead of `curl` being killed first and leaving nothing to report.

> [!IMPORTANT]
> Two traps when you change these numbers:
> * `<timeout>` is parsed as a duration, so the unit is **mandatory**: `180s`, not `180`.
> * Nuxeo applies `min(<timeout>, time left in the transaction)`. If the transaction is already half spent
>   when the converter runs, the 180s above is silently shortened.

> [!NOTE]
> Under load the chain can still break: `CONVERT_TIMEOUT_S` only starts counting once the request gets one of
> the `MAX_CONCURRENT` slots, not when it arrives. A request waiting behind others can therefore exceed
> `--max-time` before the service even begins converting. If that happens, raise `MAX_CONCURRENT` (and the
> container's CPU/memory) rather than just stretching the timeouts.

### 3. Register the `ifc-to...` Converters

(A reminder that the mimetypes must have been contributed)

```xml
<extension target="org.nuxeo.ecm.core.convert.service.ConversionServiceImpl"
           point="converter">

  <!-- ifc-to-png requires to pass the view (3d or plan) and the size (>= 64, <= 4096) parameters -->
  <converter name="ifc-to-png"
             class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>image/png</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifc-to-png</parameter>
    </parameters>
  </converter>
  
  <converter name="ifc-to-svg"
             class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>image/svg+xml</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifc-to-svg</parameter>
    </parameters>
  </converter>
  
  <converter name="ifc-to-glb"
             class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>model/gltf-binary</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifc-to-glb</parameter>
    </parameters>
  </converter>
  
  <converter name="ifc-to-obj"
             class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>model/obj</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifc-to-obj</parameter>
    </parameters>
  </converter>
  
  <converter name="ifc-to-objzip"
             class="org.nuxeo.ecm.platform.convert.plugins.CommandLineConverter">
    <sourceMimeType>model/ifc</sourceMimeType>
    <destinationMimeType>application/zip</destinationMimeType>
    <parameters>
      <parameter name="CommandLineName">ifc-to-objzip</parameter>
    </parameters>
  </converter>
</extension>
```

### 4. Call it from Automation: `Blob.RunConverter`

In all the examples, `ifcBlob` holds the .ifc file. (maybe a simple prior call to `ifcBlob = input["file:content"];`).

* Converting to PNG

`view` and `size` (64 to 4096) are required.

```js
var png3d = Blob.RunConverter(ifcBlob, {'converter': "ifc-to-png", 'parameters': 'view=3d\nsize=1024'});
var pngPlan2048 = Blob.RunConverter(ifcBlob, {'converter': "ifc-to-png", 'parameters': 'view=plan\nsize=2048'});
```

* Converting to other formats

For these, no need to pass parameters, the call ios very simple:

```js
var svg = Blob.RunConverter(ifcBlob, {'converter': 'ifc-to-svg'});
var glb = Blob.RunConverter(ifcBlob, {'converter': 'ifc-to-glb'});
var obj = Blob.RunConverter(ifcBlob, {'converter': 'ifc-to-obj'});
var zip = Blob.RunConverter(ifcBlob, {'converter': 'ifc-to-objzip'});
```


## Tune your Docker-Compose

### Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_MB` | 500 | Maximum IFC size |
| `CONVERT_TIMEOUT_S` | 150 | Maximum time for one conversion (all steps). Whoever calls the service must allow more time than this, see the timeout chain in [Usage with Nuxeo](#usage-with-nuxeo) |
| `MAX_CONCURRENT` | 2 | Conversions running at the same time; extra requests wait their turn. `CONVERT_TIMEOUT_S` starts only once a request gets a slot, so waiting time is not counted in it |
| `IFC_THREADS` | 4 | Threads used by IfcConvert for each conversion |

Each request is logged on one line: `convert format=png view=3d in=92542B status=200 time=0.65s`
(`docker compose logs ifc-converter`).

### Content

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

docker run --rm -d --name ifc-converter -p 127.0.0.1:18080:8080 ifc-converter

curl -sf --data-binary @samples/Duplex_A_20110907.ifc "http://localhost:18080/convert?format=png" -o duplex.png

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

