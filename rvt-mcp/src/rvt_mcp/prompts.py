"""Prompt templates for the three jobs this server exists to do.

A prompt is not a tool: it is the shape of the question. These carry the order of
operations that the tools cannot enforce — inspect before exporting, filter
before dumping geometry, check diagnostics before trusting a comparison.
"""

from __future__ import annotations

from fastmcp import FastMCP

__all__ = ["register"]


def register(mcp: FastMCP) -> None:
    @mcp.prompt(name="inspect_revit_file", tags={"inspect"})
    def inspect_revit_file(path: str) -> str:
        """Work out what a Revit file is and whether it can be exported."""
        return f"""Inspect the Revit file at {path} and report what it is and what can be done with it.

Steps:
1. `rvt_open` with the path; keep the returned handle.
2. `rvt_metadata` for release, build, last save and worksharing state.
3. `rvt_inspect` for missing streams, schema quality and decoded element counts.
4. `rvt_counts` to see which classes are present.
5. `rvt_capabilities` with the file's release.

Then answer, in this order:
- which Revit release saved it, and whether that release is in the validated range;
- whether the element walk found real elements or only a scaffold;
- whether an IFC export would carry geometry, and which mode is honest to use;
- anything that would make an export misleading (missing streams, resource limits).

Do not export yet."""

    @mcp.prompt(name="export_model_bundle", tags={"export"})
    def export_model_bundle(path: str, out_dir: str) -> str:
        """Produce the full artifact set for a file and check it."""
        return f"""Export the Revit file at {path} into {out_dir}.

Steps:
1. `rvt_open` the file; stop if `rvt_inspect` reports missing required streams.
2. `rvt_export_report` with out_dir={out_dir}, mode="scaffold".
3. Read the warnings it returns and the diagnostics sidecar it wrote.
4. `rvt_elements` with limit=5 to show what was decoded.

Then report: the artifact paths with sizes, the element count, and every
approximation the diagnostics list. Say plainly whether the result is a real
model or a scaffold, and never present a scaffold as a model."""

    @mcp.prompt(name="compare_revisions", tags={"compare"})
    def compare_revisions(old_path: str, new_path: str) -> str:
        """Explain what changed between two saves of the same model."""
        return f"""Compare {old_path} and {new_path}.

Steps:
1. `rvt_diff` with both paths and decompress=true.
2. `rvt_counts` on each file, and compare the per-class totals.
3. `rvt_elements` on each file, filtered to the classes whose counts differ.
4. If both exports exist as IFC, `rvt_ifc_compare` them.

Then report: which streams changed, which classes gained or lost elements, and
which differences are likely format-level noise (recompression, GUID churn)
rather than model changes. Distinguish what you measured from what you inferred."""
