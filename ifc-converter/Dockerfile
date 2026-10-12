# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Hyland Software, Inc.
#
# ifc-converter: HTTP service converting IFC to GLB / OBJ / SVG / PNG
# Third-party components downloaded by this build and their licenses: see THIRD-PARTY-NOTICES.md
# Debian 13 (glibc 2.41) because IfcOpenShell 0.9 needs glibc >= 2.38 (Oracle Linux 9 has 2.34).
# Builds for the host architecture: arm64 (Mac) or x86_64 (EC2).
FROM debian:trixie-slim

ARG IFCCONVERT_VERSION=0.9.0
ENV DEBIAN_FRONTEND=noninteractive

# - libegl1 + libgl1-mesa-dri: Mesa EGL with llvmpipe (CPU) for headless rendering, no X server
# - librsvg2-bin: rsvg-convert (SVG -> PNG)
# - curl: healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip \
      python3 python3-venv \
      libegl1 libgl1-mesa-dri libgl1 libxrender1 libx11-6 \
      librsvg2-bin \
 && rm -rf /var/lib/apt/lists/*

# IfcConvert: official IfcOpenShell build matching the CPU architecture.
# The zip also ships 3 optional plugins built on CGAL packages licensed GPL-3.0-or-later (the CGAL
# geometry kernels and svgfill). This service only uses the default OpenCASCADE kernel and its
# output is identical without them, so they are removed to keep GPL code out of the image.
RUN case "$(uname -m)" in \
      aarch64) ARCH=linuxarm64 ;; \
      x86_64)  ARCH=linux64 ;; \
      *) echo "unsupported arch $(uname -m)"; exit 1 ;; \
    esac \
 && mkdir -p /opt/ifcconvert && cd /opt/ifcconvert \
 && curl -fsSL -o ifcconvert.zip "https://github.com/IfcOpenShell/IfcOpenShell/releases/download/ifcconvert-${IFCCONVERT_VERSION}/ifcconvert-${IFCCONVERT_VERSION}-${ARCH}.zip" \
 && unzip -q ifcconvert.zip && rm ifcconvert.zip \
 && rm ifcopenshell_geometry_kernel_cgal.so ifcopenshell_geometry_kernel_cgalsimple.so ifcopenshell_geometry_svgfill.so

RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir \
      vtk==9.7.1 pyvista==0.49.1 fastapi==0.143.0 uvicorn==0.54.0

RUN useradd --system --uid 10001 --home-dir /tmp --shell /usr/sbin/nologin ifc

WORKDIR /app
COPY app.py render.py THIRD-PARTY-NOTICES.md ./

ENV PATH=/opt/venv/bin:/opt/ifcconvert:$PATH \
    VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER ifc
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fs http://localhost:8080/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
