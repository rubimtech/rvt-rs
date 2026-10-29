"""Export tools: IFC4, glTF, plan SVG, and a one-call bundle of all of them."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..envelope import Artifact, Result, artifact_for, build
from ..errors import fail, wrap
from ..paths import resolve_output
from ._common import entry_for

__all__ = ["register"]

HandleArg = Annotated[
    str | None, Field(description="Handle from rvt_open. Pass this or `path`.")
]
PathArg = Annotated[str | None, Field(description="File path. Pass this or `handle`.")]

_MODES = {"scaffold", "typed-no-geometry", "geometry", "strict"}


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rvt_export_glb",
        tags={"export", "geometry"},
        annotations={"readOnlyHint": False, "openWorldHint": False},
    )
    def rvt_export_glb(
        handle: HandleArg = None,
        path: PathArg = None,
        out: Annotated[
            str | None,
            Field(description="Output .glb path. Omit to write next to the input."),
        ] = None,
        saved_meshes: Annotated[
            str,
            Field(
                description="none, auto (doors and windows on 2023-2027) or all — draw bodies from Revit's saved display meshes."
            ),
        ] = "auto",
        diagnostics: Annotated[
            bool, Field(description="Also write the export diagnostics sidecar.")
        ] = False,
    ) -> Result:
        """glTF 2.0 binary (.glb) — metres, Y-up, ready for Three.js, Blender or any viewer.

        Each element is drawn as the body the IFC writer gives it; `saved_meshes`
        additionally recovers furniture, fixtures and equipment from the meshes
        Revit saved for display, which is what makes a model look complete
        rather than boxy.
        """
        entry = entry_for(handle, path)
        _check_saved_meshes(saved_meshes)
        try:
            with entry.lock:
                data = bytes(
                    entry.file.write_glb("scaffold", False, saved_meshes, False)
                )
                sidecar = entry.file.export_diagnostics() if diagnostics else None
        except (ValueError, OSError) as exc:
            wrap(
                "export_failed", exc, hint="check rvt_inspect for what the file yields"
            )
        target = resolve_output(
            out, default_name=f"{entry.path.stem}.glb", source=entry.path
        )
        target.write_bytes(data)
        warnings: list[str] = []
        if sidecar is not None:
            sidecar_path = target.with_suffix(".diagnostics.json")
            sidecar_path.write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            warnings.extend(_diagnostic_warnings(sidecar))
        return build(
            "rvt_export_glb",
            handle=entry.handle,
            summary={"unit": "metres", "up_axis": "Y", "saved_meshes": saved_meshes},
            artifact=artifact_for(target, "glb"),
            warnings=warnings,
        )

    @mcp.tool(
        name="rvt_export_ifc",
        tags={"export"},
        annotations={"readOnlyHint": False, "openWorldHint": False},
    )
    def rvt_export_ifc(
        handle: HandleArg = None,
        path: PathArg = None,
        out: Annotated[
            str | None,
            Field(description="Output .ifc path. Omit to write next to the input."),
        ] = None,
        mode: Annotated[
            str,
            Field(
                description="scaffold, typed-no-geometry, geometry or strict. strict refuses to write unless the export is complete."
            ),
        ] = "scaffold",
        allow_partial: Annotated[
            bool,
            Field(
                description="Write even when a resource limit left part of the file unread."
            ),
        ] = False,
        saved_meshes: Annotated[str, Field(description="none, auto or all.")] = "auto",
        revit_property_sets: Annotated[
            bool,
            Field(
                description="Add Revit's own property sets, as Revit's exporter does."
            ),
        ] = False,
        diagnostics: Annotated[
            bool, Field(description="Also write the diagnostics sidecar.")
        ] = False,
    ) -> Result:
        """IFC4 STEP export — the open exchange format for BIM coordination.

        The quality `mode` is a gate, not a knob: `strict` exits without writing
        while anything is approximated, which is the honest way to check whether
        a file is ready for exchange.
        """
        entry = entry_for(handle, path)
        if mode not in _MODES:
            fail(
                "bad_mode",
                f"unknown export mode {mode!r}",
                hint="use " + ", ".join(sorted(_MODES)),
            )
        _check_saved_meshes(saved_meshes)
        target = resolve_output(
            out, default_name=f"{entry.path.stem}.ifc", source=entry.path
        )
        try:
            with entry.lock:
                text = entry.file.write_ifc_full(
                    mode, allow_partial, saved_meshes, revit_property_sets
                )
            target.write_text(text, encoding="utf-8")
            sidecar = None
            if diagnostics:
                with entry.lock:
                    sidecar = entry.file.export_diagnostics()
        except (ValueError, OSError) as exc:
            wrap(
                "export_failed", exc, hint="relax `mode`, or open with large_model=true"
            )
        warnings: list[str] = []
        if sidecar is not None:
            sidecar_path = target.with_suffix(".diagnostics.json")
            sidecar_path.write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            warnings.extend(_diagnostic_warnings(sidecar))
        return build(
            "rvt_export_ifc",
            handle=entry.handle,
            summary={
                "mode": mode,
                "allow_partial": allow_partial,
                "saved_meshes": saved_meshes,
            },
            artifact=artifact_for(target, "ifc"),
            warnings=warnings,
        )

    @mcp.tool(
        name="rvt_export_svg",
        tags={"export", "geometry"},
        annotations={"readOnlyHint": False, "openWorldHint": False},
    )
    def rvt_export_svg(
        handle: HandleArg = None,
        path: PathArg = None,
        out: Annotated[
            str | None,
            Field(description="Output .svg path. Omit to write next to the input."),
        ] = None,
        width: Annotated[
            int, Field(description="Plot width in pixels.", ge=100, le=20000)
        ] = 1200,
        height: Annotated[
            int, Field(description="Plot height in pixels.", ge=100, le=20000)
        ] = 800,
        margin: Annotated[
            float, Field(description="Interior margin in pixels.", ge=0.0)
        ] = 40.0,
        labels: Annotated[bool, Field(description="Draw element name labels.")] = True,
        background: Annotated[
            str | None,
            Field(description="Background fill, e.g. '#FFFFFF'. null for transparent."),
        ] = "#FFFFFF",
    ) -> Result:
        """2D plan view as SVG, per-category coloured.

        The quickest visual check of a file: footprints only, no meshes, so it
        renders in a browser and can be printed or laser-cut.
        """
        entry = entry_for(handle, path)
        try:
            with entry.lock:
                svg = entry.file.render_plan_svg(
                    width, height, margin, labels, background
                )
        except (ValueError, OSError) as exc:
            wrap(
                "export_failed", exc, hint="check rvt_inspect for what the file yields"
            )
        target = resolve_output(
            out, default_name=f"{entry.path.stem}.svg", source=entry.path
        )
        target.write_text(svg, encoding="utf-8")
        return build(
            "rvt_export_svg",
            handle=entry.handle,
            summary={"width": width, "height": height, "labels": labels},
            artifact=artifact_for(target, "svg"),
        )

    @mcp.tool(
        name="rvt_export_report",
        tags={"export"},
        annotations={"readOnlyHint": False, "openWorldHint": False},
    )
    def rvt_export_report(
        handle: HandleArg = None,
        path: PathArg = None,
        out_dir: Annotated[
            str | None,
            Field(
                description="Directory for the bundle. Omit for <stem>-report beside the input."
            ),
        ] = None,
        include: Annotated[
            list[str] | None,
            Field(
                description="Subset of ifc, glb, svg, elements, schedule, diagnostics. Omit for all."
            ),
        ] = None,
        mode: Annotated[str, Field(description="IFC quality mode.")] = "scaffold",
    ) -> Result:
        """One call, one directory: IFC, GLB, plan SVG, elements JSON, schedule CSV, diagnostics.

        The hand-off bundle. A `manifest.json` inside lists every artifact with
        its size and checksum, so a later step can verify what it received
        without re-reading the model.
        """
        entry = entry_for(handle, path)
        if mode not in _MODES:
            fail(
                "bad_mode",
                f"unknown export mode {mode!r}",
                hint="use " + ", ".join(sorted(_MODES)),
            )
        wanted = {
            item.lower()
            for item in include
            or ["ifc", "glb", "svg", "elements", "schedule", "diagnostics"]
        }
        unknown = wanted - {"ifc", "glb", "svg", "elements", "schedule", "diagnostics"}
        if unknown:
            fail(
                "bad_include", f"unknown bundle member(s): {', '.join(sorted(unknown))}"
            )
        directory = resolve_output(
            out_dir, default_name=f"{entry.path.stem}-report", source=entry.path
        )
        directory.mkdir(parents=True, exist_ok=True)
        artifacts: list[Artifact] = []
        warnings: list[str] = []

        if "ifc" in wanted:
            target = directory / f"{entry.path.stem}.ifc"
            with entry.lock:
                target.write_text(
                    entry.file.write_ifc_full(mode, True, "auto", False),
                    encoding="utf-8",
                )
            artifacts.append(artifact_for(target, "ifc"))
        if "glb" in wanted:
            target = directory / f"{entry.path.stem}.glb"
            with entry.lock:
                target.write_bytes(
                    bytes(entry.file.write_glb("scaffold", True, "auto", False))
                )
            artifacts.append(artifact_for(target, "glb"))
        if "svg" in wanted:
            target = directory / f"{entry.path.stem}.svg"
            with entry.lock:
                target.write_text(
                    entry.file.render_plan_svg(1200, 800, 40.0, True, "#FFFFFF"),
                    encoding="utf-8",
                )
            artifacts.append(artifact_for(target, "svg"))
        if "elements" in wanted:
            target = directory / f"{entry.path.stem}.elements.json"
            with entry.lock:
                rows = list(entry.file.decoded_elements())
            target.write_text(
                json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            artifacts.append(artifact_for(target, "json"))
        if "schedule" in wanted:
            target = directory / f"{entry.path.stem}.elements.csv"
            with entry.lock:
                target.write_text(
                    entry.file.schedule_csv("elements", True, True), encoding="utf-8"
                )
            artifacts.append(artifact_for(target, "csv"))
        if "diagnostics" in wanted:
            target = directory / f"{entry.path.stem}.diagnostics.json"
            with entry.lock:
                sidecar = entry.file.export_diagnostics()
            target.write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            artifacts.append(artifact_for(target, "json"))
            warnings.extend(_diagnostic_warnings(sidecar))

        manifest = directory / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "source": str(entry.path),
                    "revit_version": entry.version,
                    "mode": mode,
                    "artifacts": [item.model_dump() for item in artifacts],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return build(
            "rvt_export_report",
            handle=entry.handle,
            summary={"directory": str(directory), "artifacts": len(artifacts) + 1},
            items=[item.model_dump() for item in artifacts],
            artifact=artifact_for(manifest, "json"),
            warnings=warnings,
        )


def _check_saved_meshes(value: str) -> None:
    if value not in {"none", "auto", "all"}:
        fail(
            "bad_saved_meshes",
            f"unknown saved_meshes {value!r}",
            hint="use none, auto or all",
        )


def _diagnostic_warnings(diagnostics: Any) -> list[str]:
    """The two things a caller must know before trusting an export."""
    warnings: list[str] = []
    if not isinstance(diagnostics, dict):
        return warnings
    unsupported = diagnostics.get("unsupported") or diagnostics.get("warnings") or []
    if isinstance(unsupported, list) and unsupported:
        first = unsupported[0]
        text = first.get("message") if isinstance(first, dict) else str(first)
        warnings.append(f"{len(unsupported)} export warning(s); first: {text}")
    exported = diagnostics.get("exported_elements")
    if isinstance(exported, int) and exported == 0:
        warnings.append(
            "no elements were exported: the result is a scaffold, not a model"
        )
    return warnings
