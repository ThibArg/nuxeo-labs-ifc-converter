# Third-party notices

This repository contains only:
- Hyland's own files (Dockerfile, `app.py`, `render.py`, documentation), under the Apache License 2.0
  (https://www.apache.org/licenses/LICENSE-2.0). There is no `LICENSE` file on purpose: the licensing is
  stated in the "Licenses" section of the repository's `README.md` and in this document.
- two sample IFC files under CC BY 4.0, credited in the `samples` folder of the repository

**No third-party software is included in this repository.** When you build the image, Docker downloads
the components below from their official sources. Each one stays under its own license.

## What the build downloads

### Base image and system packages
| Component | Downloaded from | License |
|---|---|---|
| Debian 13 "trixie" slim (`debian:trixie-slim`) | Docker Hub (Docker Official Image) | Debian "main" packages, all free software (DFSG). Includes GPL-licensed tools such as `bash` and `coreutils`. Each package's terms are in `/usr/share/doc/<package>/copyright` inside the image. |
| `python3` | Debian | PSF-2.0 |
| Mesa (`libegl1`, `libgl1-mesa-dri`, incl. the llvmpipe CPU renderer) | Debian | MIT |
| LLVM (pulled in by Mesa) | Debian | Apache-2.0 WITH LLVM-exception |
| `libgl1`, `libegl1` (libglvnd), `libx11-6`, `libxrender1` | Debian | MIT / X11-style |
| `librsvg2-bin` (`rsvg-convert`) | Debian | LGPL-2.1-or-later |
| `curl`, `unzip`, `ca-certificates` | Debian | curl license / Info-ZIP / MPL-2.0 |

Their dependencies come from Debian "main" as well.

### IfcConvert (IfcOpenShell)
| Component | Downloaded from | License |
|---|---|---|
| IfcConvert 0.9.0 and the IfcOpenShell libraries | GitHub release `ifcconvert-0.9.0-linux64.zip` / `ifcconvert-0.9.0-linuxarm64.zip` | LGPL-3.0-or-later |
| Libraries bundled in that zip, among others: Open CASCADE Technology 7.8 | | LGPL-2.1 with the OCCT exception |
| Boost.Program_options | | BSL-1.0 |
| OpenCOLLADA, libxml2, nlohmann/json | | MIT |
| PCRE | | BSD-3-Clause |
| manifold | | Apache-2.0 |
| wgpu-native | | MIT OR Apache-2.0 |
| GMP / MPFR (only used by the removed CGAL plugins) | | LGPL-3.0-or-later OR GPL-2.0-or-later / LGPL-3.0-or-later |

The IfcConvert zip ships no license files. The license texts and the full list of dependencies are in
the IfcOpenShell source repository: https://github.com/IfcOpenShell/IfcOpenShell (`COPYING`, `COPYING.LESSER`).

**Removed at build time:** the zip also contains 3 optional plugins built on CGAL packages licensed
GPL-3.0-or-later: `ifcopenshell_geometry_kernel_cgal.so`, `ifcopenshell_geometry_kernel_cgalsimple.so`
and `ifcopenshell_geometry_svgfill.so`. This service uses the default OpenCASCADE kernel, and its output
is identical without them, so the Dockerfile deletes them. The image contains no CGAL code.

### Python packages (PyPI)
Pinned in the Dockerfile: `vtk==9.7.1`, `pyvista==0.49.1`, `fastapi==0.143.0`, `uvicorn==0.54.0`.
Their dependencies, as resolved on 2026-10-12:

| License | Packages |
|---|---|
| BSD (2- or 3-Clause) | vtk, numpy (plus 0BSD/MIT/Zlib/CC0 parts), starlette, uvicorn, click, contourpy, cycler, idna, kiwisolver, pooch, Pygments |
| MIT | pyvista, pyvista-validation, fastapi, pydantic, pydantic_core, annotated-doc, annotated-types, anyio, attrs, charset-normalizer, docstring_parser, fonttools, h11, markdown-it-py, mdurl, platformdirs, pyparsing, rich, rich-rst, scooby, six, typing-inspection, urllib3, pip |
| MIT-CMU | pillow |
| Apache-2.0 | cyclopts, opentelemetry-api, requests |
| Apache-2.0 OR BSD-2-Clause | packaging |
| BSD OR Apache-2.0 | python-dateutil |
| PSF | matplotlib (Matplotlib license, PSF-based), typing_extensions |
| MPL-2.0 | certifi |

Each package's license text is in `/opt/venv/lib/python3*/site-packages/<package>.dist-info/` inside the image.

## Using the image

Building the image and running it inside your organization, including as an HTTP service called by
Nuxeo, creates no copyleft obligation. None of the components above is under the AGPL, and the
obligations of the GPL and the LGPL only apply when the software is distributed to someone else.

## If you distribute the built image

Pushing the image to a registry that people outside your organization can pull, or giving it to
another company, makes you a distributor of every component above. You must then, among others:
- include the license texts and notices: Debian packages (`/usr/share/doc/*/copyright`), Python packages
  (`*.dist-info/`), IfcOpenShell (`COPYING`, `COPYING.LESSER`) and Open CASCADE
- provide, or offer in writing, the corresponding source code of the GPL and LGPL components: IfcOpenShell
  at the `ifcconvert-0.9.0` tag, the Debian source packages, etc.
- keep the LGPL libraries replaceable by the user. They are shared libraries in this image, so this holds.

The simplest way to avoid all of this is to not distribute the image: share this repository and let
each organization build its own image.

This document is a summary, not legal advice.
