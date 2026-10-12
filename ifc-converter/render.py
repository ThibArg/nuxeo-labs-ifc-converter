# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Hyland Software, Inc.
"""Headless render of a GLB/OBJ to PNG with PyVista/VTK (EGL + Mesa llvmpipe, no X server, no GPU).

Usage: render.py <in.glb|in.obj> <out.png> [size=1024] [frame=main|all]
glTF is Y-up (IfcConvert converts IFC Z-up to Y-up for GLB); OBJ from IfcConvert stays Z-up.

frame=main ignores stray objects far from the model (geo-reference markers, survey points...):
objects are grouped when their bounding boxes are closer than max(5 m, 10% of the overall
diagonal), and the camera frames the group with the most objects.
"""
import sys
import time

import numpy as np
import pyvista as pv

src, dst = sys.argv[1], sys.argv[2]
size = int(sys.argv[3]) if len(sys.argv) > 3 else 1024
frame = sys.argv[4] if len(sys.argv) > 4 else "main"
up = "y" if src.lower().endswith((".glb", ".gltf")) else "z"

t0 = time.time()
pl = pv.Plotter(off_screen=True, window_size=(size, size))
pl.set_background("white")
if src.lower().endswith((".glb", ".gltf")):
    pl.import_gltf(src, set_camera=False)
elif src.lower().endswith(".obj"):
    pl.import_obj(src)  # also reads the .mtl next to it
else:
    pl.add_mesh(pv.read(src))


def main_group(actors):
    """Single-linkage grouping of actor bounding boxes; returns the actors of the biggest group."""
    boxes = np.array([a.GetBounds() for a in actors]).reshape(-1, 3, 2)  # (n, axis, min/max)
    lo, hi = boxes[:, :, 0], boxes[:, :, 1]
    threshold = max(5.0, 0.1 * np.linalg.norm(hi.max(0) - lo.min(0)))
    parent = list(range(len(actors)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(actors)):
        gap = np.maximum(0, np.maximum(lo[i] - hi, lo - hi[i])).max(axis=1)  # per-axis gap, worst axis
        for j in np.nonzero(gap <= threshold)[0]:
            parent[root(i)] = root(int(j))
    groups = {}
    for i in range(len(actors)):
        groups.setdefault(root(i), []).append(actors[i])
    return max(groups.values(), key=len), len(groups)


actors = [a for a in pl.renderer.actors.values() if a.GetVisibility()]
hidden = 0
if frame == "main" and len(actors) > 1:
    keep, ngroups = main_group(actors)
    for a in actors:
        if a not in keep:
            a.SetVisibility(False)
            hidden += 1

# Isometric view from the south-east, above the model
xmin, xmax, ymin, ymax, zmin, zmax = pl.bounds
center = np.array([(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2])
if up == "y":
    direction, view_up = np.array([1.0, 0.8, 1.0]), (0, 1, 0)
else:
    direction, view_up = np.array([1.0, -1.0, 0.8]), (0, 0, 1)
pl.camera_position = [tuple(center + direction), tuple(center), view_up]
pl.reset_camera()
pl.enable_anti_aliasing("ssaa")
pl.screenshot(dst)

print(f"render window: {pl.render_window.GetClassName()}  actors: {len(actors)}  hidden: {hidden}  "
      f"time: {time.time() - t0:.2f}s")
pl.close()
