"""Geometry tools: the shapes behind the elements, as data rather than as a file.

Three detail levels, each from the most reliable source available:

* `location` — the element's origin, rotation and storey, straight from the
  exported model;
* `boundary` / `solid` — the profile and extrusion the IFC writer uses, so the
  numbers match what a STEP export would contain;
* `mesh` — the triangles the glTF writer produced, read back from the GLB. This
  is the only level that reflects bodies recovered from Revit's saved display
  meshes.
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..adapters.glb import read_glb
from ..envelope import Result, artifact_for, build
from ..errors import fail
from ..paths import resolve_output
from ._common import METRES_TO_FEET, entry_for, units_for

__all__ = ["register"]

HandleArg = Annotated[
    str | None, Field(description="Handle from rvt_open. Pass this or `path`.")
]
PathArg = Annotated[str | None, Field(description="File path. Pass this or `handle`.")]


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rvt_geometry",
        tags={"geometry"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_geometry(
        handle: HandleArg = None,
        path: PathArg = None,
        detail: Annotated[
            str, Field(description="location, boundary, solid or mesh.")
        ] = "location",
        categories: Annotated[
            list[str] | None,
            Field(
                description="IFC types to keep, e.g. ['IFCWALL','IFCSLAB']. Omit for all."
            ),
        ] = None,
        names: Annotated[
            list[str] | None,
            Field(
                description="Keep elements whose name contains one of these substrings."
            ),
        ] = None,
        element_ids: Annotated[
            list[int] | None,
            Field(
                description="Revit ElementIds; resolved through the decoded element names."
            ),
        ] = None,
        metric: Annotated[bool, Field(description="Metres instead of feet.")] = True,
        include_vertices: Annotated[
            bool,
            Field(
                description="Include mesh vertices (detail=mesh). Large; prefer `out`."
            ),
        ] = False,
        out: Annotated[
            str | None,
            Field(
                description="Write the full geometry JSON here instead of returning it."
            ),
        ] = None,
        limit: Annotated[
            int, Field(description="Maximum elements to describe.", ge=1, le=2000)
        ] = 200,
    ) -> Result:
        """Element geometry as JSON: placement, plan boundary, solid or triangles.

        Filter before you export. An unfiltered mesh dump of a real project is
        hundreds of megabytes; with `out` the payload goes to disk and only a
        summary and a sample come back.

        Coordinates are in the model's own system, converted from Revit's feet
        when `metric=true`; the response says which unit it used.
        """
        if detail not in {"location", "boundary", "solid", "mesh"}:
            fail(
                "bad_detail",
                f"unknown detail {detail!r}",
                hint="use location, boundary, solid or mesh",
            )
        entry = entry_for(handle, path)
        unit, factor = units_for(metric)
        if detail == "mesh":
            records, total = _mesh_records(
                entry, categories, names, metric, include_vertices
            )
        else:
            model = _export_model(entry)
            wanted = _wanted_names(entry, element_ids)
            records = [
                _describe(element, detail, factor, unit)
                for element in _iter_elements(model)
                if _keep(element, categories, names, wanted)
            ]
            total = len(records)
            records = records[:limit]
        summary = {
            "path": str(entry.path),
            "detail": detail,
            "unit": unit,
            "elements": total,
            "returned": len(records),
        }
        if out is not None:
            target = resolve_output(
                out, default_name=f"{entry.path.stem}.{detail}.json", source=entry.path
            )
            target.write_text(
                json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return build(
                "rvt_geometry",
                handle=entry.handle,
                summary=summary,
                items=records,
                preview_limit=min(3, limit),
                artifact=artifact_for(target, "json"),
            )
        return build(
            "rvt_geometry",
            handle=entry.handle,
            summary=summary,
            items=records,
            preview_limit=limit,
        )

    @mcp.tool(
        name="rvt_export_obj",
        tags={"geometry", "export"},
        annotations={"readOnlyHint": False, "openWorldHint": False},
    )
    def rvt_export_obj(
        handle: HandleArg = None,
        path: PathArg = None,
        out: Annotated[
            str | None,
            Field(description="OBJ path. A matching .mtl is written beside it."),
        ] = None,
        names: Annotated[
            list[str] | None,
            Field(
                description="Keep meshes whose name contains one of these substrings."
            ),
        ] = None,
        include_materials: Annotated[
            bool, Field(description="Write the .mtl and reference it from the .obj.")
        ] = True,
    ) -> Result:
        """Wavefront OBJ of the model's bodies, grouped by element.

        The interchange format every DCC tool reads. Triangles come from the
        same GLB `rvt_export_glb` writes, so the two never disagree; metres and
        Y-up, as glTF requires.
        """
        entry = entry_for(handle, path)
        with entry.lock:
            glb = bytes(entry.file.write_glb("scaffold", False, "auto", False))
        document = read_glb(glb)
        meshes = [
            mesh
            for mesh in document.meshes()
            if not names or any(token.lower() in mesh.name.lower() for token in names)
        ]
        if not meshes:
            fail(
                "no_geometry",
                "the export produced no triangle meshes",
                hint="check rvt_inspect: the file may decode to a scaffold, or the filter matched nothing",
            )
        target = resolve_output(
            out, default_name=f"{entry.path.stem}.obj", source=entry.path
        )
        mtl_path = target.with_suffix(".mtl")
        obj_text, mtl_text = _write_obj(
            meshes, mtl_path.name if include_materials else None
        )
        target.write_text(obj_text, encoding="utf-8")
        if include_materials and mtl_text:
            mtl_path.write_text(mtl_text, encoding="utf-8")
        summary = {
            "objects": len(meshes),
            "vertices": sum(len(mesh.positions) for mesh in meshes),
            "triangles": sum(len(mesh.indices) // 3 for mesh in meshes),
            "materials": len({mesh.material for mesh in meshes if mesh.material}),
            "unit": "metres",
        }
        return build(
            "rvt_export_obj",
            handle=entry.handle,
            summary=summary,
            artifact=artifact_for(target, "obj"),
        )


def _export_model(entry) -> dict[str, Any]:
    with entry.lock:
        return json.loads(
            entry.file.export_model_json("scaffold", False, "auto", False)
        )


def _iter_elements(model: dict[str, Any]):
    for entity in model.get("entities", []):
        element = entity.get("BuildingElement")
        if element is not None:
            yield element


def _wanted_names(entry, element_ids: list[int] | None) -> set[str] | None:
    """Map ElementIds to element names through the decoded elements.

    The exported model carries names, not ElementIds, so an id filter is
    resolved once here instead of being guessed per element.
    """
    if not element_ids:
        return None
    with entry.lock:
        decoded = list(entry.file.decoded_elements())
    wanted = set(element_ids)
    return {
        str(row.get("name") or row.get("class_name") or "")
        for row in decoded
        if row.get("id") in wanted
    } or {""}


def _keep(
    element: dict[str, Any],
    categories: list[str] | None,
    names: list[str] | None,
    wanted: set[str] | None,
) -> bool:
    if categories and str(element.get("ifc_type", "")).upper() not in {
        name.upper() for name in categories
    }:
        return False
    label = str(element.get("name", ""))
    if names and not any(token.lower() in label.lower() for token in names):
        return False
    if wanted is not None and label not in wanted:
        return False
    return True


def _describe(
    element: dict[str, Any], detail: str, factor: float, unit: str
) -> dict[str, Any]:
    location = element.get("location_feet")
    record: dict[str, Any] = {
        "name": element.get("name"),
        "ifc_type": element.get("ifc_type"),
        "predefined_type": element.get("predefined_type"),
        "storey_index": element.get("storey_index"),
        "unit": unit,
    }
    if location:
        record["location"] = [round(float(value) * factor, 6) for value in location]
    if element.get("rotation_radians") is not None:
        record["rotation_radians"] = element["rotation_radians"]
    if detail == "location":
        return record

    profile = _profile_ring(element.get("extrusion"))
    if profile is not None:
        ring = _place(profile, location, element.get("rotation_radians"), factor)
        record["boundary"] = ring
        record["area"] = round(abs(_area(profile)) * factor * factor, 6)
    extrusion = element.get("extrusion")
    if extrusion:
        record["extrusion"] = {
            "width": round(float(extrusion.get("width_feet", 0.0)) * factor, 6),
            "depth": round(float(extrusion.get("depth_feet", 0.0)) * factor, 6),
            "height": round(float(extrusion.get("height_feet", 0.0)) * factor, 6),
            "profile": extrusion.get("profile_override"),
        }
    if element.get("solid_shape"):
        record["solid_shape"] = element["solid_shape"]
    return record


def _profile_ring(extrusion: dict[str, Any] | None) -> list[tuple[float, float]] | None:
    """The closed 2D outline an extrusion sweeps, in element-local feet."""
    if not extrusion:
        return None
    profile = extrusion.get("profile_override")
    if not profile:
        width = float(extrusion.get("width_feet", 0.0))
        depth = float(extrusion.get("depth_feet", 0.0))
        if width <= 0.0 or depth <= 0.0:
            return None
        half_w, half_d = width / 2.0, depth / 2.0
        return [
            (-half_w, -half_d),
            (half_w, -half_d),
            (half_w, half_d),
            (-half_w, half_d),
        ]
    if "Rectangle" in profile:
        width = float(profile["Rectangle"]["width_feet"])
        depth = float(profile["Rectangle"]["depth_feet"])
        half_w, half_d = width / 2.0, depth / 2.0
        return [
            (-half_w, -half_d),
            (half_w, -half_d),
            (half_w, half_d),
            (-half_w, half_d),
        ]
    if "Circle" in profile:
        radius = float(profile["Circle"]["radius_feet"])
        return [
            (
                radius * math.cos(2 * math.pi * step / 32),
                radius * math.sin(2 * math.pi * step / 32),
            )
            for step in range(32)
        ]
    for key in ("ArbitraryClosed", "ArbitraryWithVoids", "IndexedPolyCurve"):
        if key in profile:
            points = profile[key].get("points") or []
            return [(float(x), float(y)) for x, y in points] or None
    return None


def _place(
    ring: list[tuple[float, float]],
    location: list[float] | None,
    rotation: float | None,
    factor: float,
) -> list[list[float]]:
    """Rotate the local ring and move it to the element's plan position."""
    angle = float(rotation or 0.0)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    x0, y0 = (float(location[0]), float(location[1])) if location else (0.0, 0.0)
    return [
        [
            round((x * cos_a - y * sin_a + x0) * factor, 6),
            round((x * sin_a + y * cos_a + y0) * factor, 6),
        ]
        for x, y in ring
    ]


def _area(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    for index, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(index + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _mesh_records(
    entry,
    categories: list[str] | None,
    names: list[str] | None,
    metric: bool,
    include_vertices: bool,
) -> tuple[list[dict[str, Any]], int]:
    """Triangles from the GLB, which is metres and Y-up by construction."""
    with entry.lock:
        glb = bytes(entry.file.write_glb("scaffold", False, "auto", False))
    document = read_glb(glb)
    types_by_name = _types_by_name(entry)
    divisor = 1.0 if metric else METRES_TO_FEET
    unit = "metres" if metric else "feet"
    records: list[dict[str, Any]] = []
    for mesh in document.meshes():
        if names and not any(token.lower() in mesh.name.lower() for token in names):
            continue
        if categories and types_by_name.get(mesh.name, "").upper() not in {
            name.upper() for name in categories
        }:
            continue
        xs = [point[0] for point in mesh.positions]
        ys = [point[1] for point in mesh.positions]
        zs = [point[2] for point in mesh.positions]
        record: dict[str, Any] = {
            "name": mesh.name,
            "ifc_type": types_by_name.get(mesh.name),
            "material": mesh.material,
            "vertices": len(mesh.positions),
            "triangles": len(mesh.indices) // 3,
            "bbox": {
                "min": [
                    round(min(xs) / divisor, 6),
                    round(min(ys) / divisor, 6),
                    round(min(zs) / divisor, 6),
                ],
                "max": [
                    round(max(xs) / divisor, 6),
                    round(max(ys) / divisor, 6),
                    round(max(zs) / divisor, 6),
                ],
            },
            "unit": unit,
        }
        if include_vertices:
            record["positions"] = [
                [
                    round(point[0] / divisor, 6),
                    round(point[1] / divisor, 6),
                    round(point[2] / divisor, 6),
                ]
                for point in mesh.positions
            ]
            record["indices"] = mesh.indices
        records.append(record)
    return records, len(records)


def _types_by_name(entry) -> dict[str, str]:
    """Element name to IFC type, so a mesh can be filtered by category."""
    try:
        model = _export_model(entry)
    except Exception:  # noqa: BLE001 - the filter degrades to "no category match"
        return {}
    return {
        str(element.get("name")): str(element.get("ifc_type"))
        for element in _iter_elements(model)
        if element.get("name")
    }


def _write_obj(meshes, material_library: str | None) -> tuple[str, str]:
    """Serialise meshes as OBJ, one object per element, one group per material."""
    lines: list[str] = ["# rvt-rs OBJ export (metres, Y-up)"]
    if material_library:
        lines.append(f"mtllib {material_library}")
    materials: dict[str, str] = {}
    material_lines: list[str] = []
    vertex_offset = 1
    for mesh in meshes:
        lines.append(f"o {_obj_name(mesh.name)}")
        if mesh.material:
            if mesh.material not in materials:
                materials[mesh.material] = _obj_name(mesh.material)
                material_lines.extend(
                    [
                        f"newmtl {materials[mesh.material]}",
                        "Kd 0.800 0.800 0.800",
                        "Ka 0.200 0.200 0.200",
                        "",
                    ]
                )
            lines.append(f"usemtl {materials[mesh.material]}")
        for x, y, z in mesh.positions:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        for index in range(0, len(mesh.indices), 3):
            a, b, c = mesh.indices[index : index + 3]
            lines.append(
                f"f {a + vertex_offset} {b + vertex_offset} {c + vertex_offset}"
            )
        vertex_offset += len(mesh.positions)
    return "\n".join(lines) + "\n", "\n".join(material_lines)


def _obj_name(raw: str | None) -> str:
    cleaned = (raw or "element").strip().replace(" ", "_")
    return "".join(ch for ch in cleaned if ch.isalnum() or ch in "_-.") or "element"
