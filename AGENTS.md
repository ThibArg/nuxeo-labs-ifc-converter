# AGENTS.md

Instructions for AI coding agents working on this repository. `README.md` is the user documentation;
keep both consistent.

## What this is

A small HTTP service converting an IFC file to GLB, OBJ, SVG (floor plan) or PNG (preview). It runs as its
own container next to Nuxeo, which calls it with `curl --data-binary @file.ifc`. This repository is
**source only**: each user builds their own image. No image is published.

| File | Role |
|---|---|
| `Dockerfile` | Debian 13 image: IfcConvert (official IfcOpenShell zip), Mesa EGL, `rsvg-convert`, Python venv, the service |
| `app.py` | FastAPI service: streams the body to a temp dir, runs the tools as subprocesses, returns the file |
| `render.py` | GLB/OBJ → PNG with PyVista/VTK, headless (EGL + Mesa llvmpipe), isometric view |
| `samples/` | Public IFC files (CC BY 4.0), credited in `samples/README.md` |
| `THIRD-PARTY-NOTICES.md` | Apache-2.0 for this code; licenses of everything the build downloads |

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
- **Comparing outputs**: with `-j` > 1, IfcConvert's output order changes from run to run. Compare files
  produced with `-j 1` only.

## Build, run, verify

There is no automated test suite: this procedure is the test. Build only after the user agreed, and use the
image tag the user gives you (`ifc-converter` below is an example).

Build, from the repository root (on Apple silicon, the amd64 build is emulated and about 3× slower):

```bash
docker build -t <image> .
docker build --platform linux/amd64 -t <image-for-amd64> .
```

Run a temporary container, published on localhost only:

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
procedure, then update `THIRD-PARTY-NOTICES.md` and the timings in `README.md` if they changed.

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

- The Nuxeo side (converters, automation, UI) is configured in Nuxeo, not in this repository.
- Publishing images to a registry: distributing the image brings license obligations
  (see `THIRD-PARTY-NOTICES.md`). This repository only ships source.
