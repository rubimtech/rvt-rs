"""Unit tests for the geometry helpers.

The repository's fixtures decode to zero building elements, so the shape
arithmetic is tested directly: a rectangle profile, a rotated placement and the
feet-to-metres conversion are the three places a sign or a factor can go wrong.
"""

from __future__ import annotations

import math

import pytest
from rvt_mcp.adapters.glb import MeshInstance, read_glb
from rvt_mcp.tools.geometry import _area, _describe, _place, _profile_ring, _write_obj

FEET = 0.3048


def test_rectangle_profile_is_centred_on_the_origin():
    extrusion = {"width_feet": 10.0, "depth_feet": 2.0}
    ring = _profile_ring(extrusion)
    assert ring == [(-5.0, -1.0), (5.0, -1.0), (5.0, 1.0), (-5.0, 1.0)]


def test_circle_profile_is_a_closed_ring_of_32_points():
    ring = _profile_ring(
        {"radius_feet": 2.0, "profile_override": {"Circle": {"radius_feet": 2.0}}}
    )
    assert len(ring) == 32
    assert all(abs(math.hypot(x, y) - 2.0) < 1e-9 for x, y in ring)


def test_arbitrary_profile_points_are_kept():
    ring = _profile_ring(
        {
            "width_feet": 1.0,
            "depth_feet": 1.0,
            "profile_override": {
                "ArbitraryClosed": {"points": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]}
            },
        }
    )
    assert ring == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]


def test_missing_extrusion_has_no_boundary():
    assert _profile_ring(None) is None
    assert _profile_ring({"width_feet": 0.0, "depth_feet": 0.0}) is None


def test_placement_rotates_then_translates_and_converts_units():
    ring = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    placed = _place(ring, [10.0, 20.0, 0.0], math.pi / 2, FEET)
    # A quarter turn maps (1, 0) to (0, 1) before the offset is added.
    assert placed[0] == [round((10.0 + 1.0) * FEET, 6), round((20.0 - 1.0) * FEET, 6)]
    assert placed[2] == [round((10.0 - 1.0) * FEET, 6), round((20.0 + 1.0) * FEET, 6)]


def test_area_of_a_rectangle_ring():
    assert _area([(0.0, 0.0), (2.0, 0.0), (2.0, 3.0), (0.0, 3.0)]) == 6.0


def test_describe_location_only_reports_placement():
    element = {
        "name": "Wall 1",
        "ifc_type": "IFCWALL",
        "location_feet": [1.0, 2.0, 3.0],
        "rotation_radians": 0.0,
        "extrusion": {"width_feet": 10.0, "depth_feet": 1.0, "height_feet": 9.0},
    }
    record = _describe(element, "location", FEET, "metres")
    assert record["location"] == [
        round(1.0 * FEET, 6),
        round(2.0 * FEET, 6),
        round(3.0 * FEET, 6),
    ]
    assert "boundary" not in record
    assert "extrusion" not in record


def test_describe_solid_reports_extrusion_in_the_requested_unit():
    element = {
        "name": "Wall 1",
        "ifc_type": "IFCWALL",
        "location_feet": [0.0, 0.0, 0.0],
        "extrusion": {"width_feet": 10.0, "depth_feet": 1.0, "height_feet": 9.0},
    }
    metric = _describe(element, "solid", FEET, "metres")
    imperial = _describe(element, "solid", 1.0, "feet")
    assert metric["extrusion"]["width"] == 10.0 * FEET
    assert imperial["extrusion"]["width"] == 10.0
    assert metric["area"] == round(10.0 * 1.0 * FEET * FEET, 6)


def test_obj_writer_emits_vertices_faces_and_a_material():
    meshes = [
        MeshInstance(
            name="Wall 1",
            material="Brick",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            indices=[0, 1, 2],
        )
    ]
    obj, mtl = _write_obj(meshes, "model.mtl")
    assert "mtllib model.mtl" in obj
    assert "o Wall_1" in obj
    assert "usemtl Brick" in obj
    assert obj.count("\nv ") == 3
    assert "f 1 2 3" in obj
    assert "newmtl Brick" in mtl


def test_obj_writer_offsets_indices_between_objects():
    meshes = [
        MeshInstance(
            "a", None, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [0, 1, 2]
        ),
        MeshInstance(
            "b", None, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [0, 1, 2]
        ),
    ]
    obj, _ = _write_obj(meshes, None)
    assert "f 4 5 6" in obj


def test_glb_reader_rejects_a_non_glb_payload():
    with pytest.raises(Exception) as error:
        read_glb(b"not a glb at all")
    assert "bad_glb" in str(error.value)
