"""A minimal glTF 2.0 binary reader.

The exporter writes one `.glb` for the whole model; the geometry tools need the
triangles back. Reading them from the GLB rather than re-deriving bodies keeps a
single source of truth: whatever `rvt-gltf` draws is what `rvt_export_obj` and
`rvt_geometry(detail="mesh")` report.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any, Iterator

from ..errors import fail

__all__ = ["GlbDocument", "MeshInstance", "read_glb"]

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942

_COMPONENT_TYPES = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


@dataclass
class MeshInstance:
    """One mesh in world space, with the material it is drawn in."""

    name: str
    material: str | None
    positions: list[tuple[float, float, float]]
    indices: list[int]


@dataclass
class GlbDocument:
    json: dict[str, Any]
    binary: bytes

    def accessor(self, index: int) -> list[Any]:
        accessor = self.json["accessors"][index]
        view = self.json["bufferViews"][accessor["bufferView"]]
        component = _COMPONENT_TYPES[accessor["componentType"]]
        width = _TYPE_WIDTH[accessor["type"]]
        offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        count = accessor["count"]
        stride = view.get("byteStride") or struct.calcsize(component) * width
        fmt = "<" + component * width
        out: list[Any] = []
        for i in range(count):
            values = struct.unpack_from(fmt, self.binary, offset + i * stride)
            out.append(values[0] if width == 1 else values)
        return out

    def material_name(self, index: int | None) -> str | None:
        if index is None:
            return None
        material = self.json.get("materials", [])[index]
        return material.get("name")

    def meshes(self) -> Iterator[MeshInstance]:
        """Every triangle mesh, transformed by its node's world matrix."""
        nodes = self.json.get("nodes", [])
        scene = self.json.get("scenes", [{}])[self.json.get("scene", 0)]
        roots = scene.get("nodes", list(range(len(nodes))))
        stack: list[tuple[int, list[float]]] = [
            (index, matrix_identity()) for index in reversed(roots)
        ]
        while stack:
            index, parent = stack.pop()
            node = nodes[index]
            world = matrix_multiply(parent, node_matrix(node))
            for child in reversed(node.get("children", [])):
                stack.append((child, world))
            mesh_index = node.get("mesh")
            if mesh_index is None:
                continue
            for primitive in self.json["meshes"][mesh_index].get("primitives", []):
                if primitive.get("mode", 4) != 4:
                    continue
                positions = [
                    _transform(world, point)
                    for point in self.accessor(primitive["attributes"]["POSITION"])
                ]
                indices: list[int] = []
                if "indices" in primitive:
                    indices = list(self.accessor(primitive["indices"]))
                else:
                    indices = list(range(len(positions)))
                yield MeshInstance(
                    name=node.get("name")
                    or self.json["meshes"][mesh_index].get("name", ""),
                    material=self.material_name(primitive.get("material")),
                    positions=positions,
                    indices=indices,
                )


def read_glb(data: bytes) -> GlbDocument:
    if len(data) < 12:
        fail("bad_glb", "the GLB is shorter than its 12-byte header")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC or version != 2:
        fail("bad_glb", f"not a glTF 2.0 binary (magic={magic:#x}, version={version})")
    offset = 12
    document: dict[str, Any] | None = None
    binary = b""
    while offset + 8 <= min(total, len(data)):
        length, kind = struct.unpack_from("<II", data, offset)
        body = data[offset + 8 : offset + 8 + length]
        offset += 8 + length
        if kind == _CHUNK_JSON:
            document = json.loads(body.decode("utf-8").rstrip(" \x00"))
        elif kind == _CHUNK_BIN:
            binary = body
    if document is None:
        fail("bad_glb", "the GLB has no JSON chunk")
    return GlbDocument(json=document, binary=binary)


def matrix_identity() -> list[float]:
    return [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]


def node_matrix(node: dict[str, Any]) -> list[float]:
    if "matrix" in node:
        return [float(value) for value in node["matrix"]]
    tx, ty, tz = (float(value) for value in node.get("translation", (0.0, 0.0, 0.0)))
    qx, qy, qz, qw = (
        float(value) for value in node.get("rotation", (0.0, 0.0, 0.0, 1.0))
    )
    sx, sy, sz = (float(value) for value in node.get("scale", (1.0, 1.0, 1.0)))
    xx, yy, zz = qx * qx, qy * qy, qz * qz
    xy, xz, yz = qx * qy, qx * qz, qy * qz
    wx, wy, wz = qw * qx, qw * qy, qw * qz
    return [
        (1 - 2 * (yy + zz)) * sx,
        (2 * (xy + wz)) * sx,
        (2 * (xz - wy)) * sx,
        0.0,
        (2 * (xy - wz)) * sy,
        (1 - 2 * (xx + zz)) * sy,
        (2 * (yz + wx)) * sy,
        0.0,
        (2 * (xz + wy)) * sz,
        (2 * (yz - wx)) * sz,
        (1 - 2 * (xx + yy)) * sz,
        0.0,
        tx,
        ty,
        tz,
        1.0,
    ]


def matrix_multiply(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for column in range(4):
        for row in range(4):
            out[column * 4 + row] = sum(
                a[k * 4 + row] * b[column * 4 + k] for k in range(4)
            )
    return out


def _transform(
    matrix: list[float], point: tuple[float, ...]
) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )
