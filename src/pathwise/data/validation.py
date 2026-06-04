"""Workbook validation — structural and referential checks.

Returns a :class:`ValidationReport` (errors + warnings) rather than raising, so
the API can fold validation into the run result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathwise.data.schema import REQUIRED_SHEETS
from pathwise.data.workbook import Workbook


@dataclass(slots=True)
class ValidationReport:
    """Collected validation findings."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """``True`` if there are no errors."""
        return not self.errors

    def as_dict(self) -> dict[str, list[str]]:
        """JSON-serialisable form."""
        return {"errors": list(self.errors), "warnings": list(self.warnings)}


def _ids(workbook: Workbook, sheet: str, col: str) -> set[str]:
    return {str(r[col]) for r in workbook.get(sheet, []) if r.get(col) not in (None, "")}


def validate(workbook: Workbook) -> ValidationReport:
    """Validate a process-network workbook.

    Checks required sheets are present and that cross-references resolve
    (baseline technologies, edge endpoints, input/output streams, measure targets,
    demand products).

    Args:
        workbook: The in-memory workbook.

    Returns:
        A :class:`ValidationReport`.
    """
    report = ValidationReport()

    for sheet in REQUIRED_SHEETS:
        if sheet not in workbook or not workbook[sheet]:
            report.errors.append(f"missing required sheet '{sheet}'")
    # Technology I/O comes from the unified `io` table OR the legacy pair.
    has_io = bool(workbook.get("io"))
    has_legacy_io = bool(workbook.get("process_inputs")) and bool(workbook.get("process_outputs"))
    if not has_io and not has_legacy_io:
        report.errors.append(
            "missing technology I/O: provide an 'io' sheet (or process_inputs + process_outputs)"
        )
    if not report.ok:
        return report  # further checks would be noise

    techs = _ids(workbook, "technologies", "technology_id")
    commodities = _ids(workbook, "commodities", "commodity_id")
    processes = _ids(workbook, "processes", "process_id")
    impacts = _ids(workbook, "impacts", "impact_id")

    for r in workbook.get("io", []):
        k = str(r.get("technology_id", ""))
        if k and k not in techs:
            report.errors.append(f"io: unknown technology '{k}'")
        tgt, role = str(r.get("target", "")), str(r.get("role", "input"))
        pool = impacts if role == "impact" else commodities
        if tgt and tgt not in pool:
            report.errors.append(f"io: unknown target '{tgt}' for role '{role}'")

    for r in workbook.get("processes", []):
        bt = str(r.get("baseline_technology", ""))
        if bt and bt not in techs:
            report.errors.append(
                f"process '{r.get('process_id')}' references unknown technology '{bt}'"
            )

    for sheet, col in [("process_inputs", "commodity_id"), ("process_outputs", "commodity_id")]:
        for r in workbook.get(sheet, []):
            c = str(r.get(col, ""))
            if c and c not in commodities:
                report.errors.append(f"{sheet}: unknown stream '{c}'")
            k = str(r.get("technology_id", ""))
            if k and k not in techs:
                report.errors.append(f"{sheet}: unknown technology '{k}'")

    for r in workbook.get("edges", []):
        for end in ("from_process", "to_process"):
            p = str(r.get(end, ""))
            if p and p not in processes:
                report.errors.append(f"edge references unknown facility '{p}'")
        c = str(r.get("commodity_id", ""))
        if c and c not in commodities:
            report.errors.append(f"edge references unknown stream '{c}'")

    for r in workbook.get("measures", []):
        ap = str(r.get("applies_to", ""))
        if ap and ap not in processes:
            report.warnings.append(
                f"measure '{r.get('measure_id')}' applies to unknown facility '{ap}'"
            )
        tgt, mtype = str(r.get("target", "")), str(r.get("type", ""))
        pool = commodities if mtype == "energy_efficiency" else impacts
        if tgt and tgt not in pool:
            report.warnings.append(f"measure '{r.get('measure_id')}' targets unknown '{tgt}'")

    product_ids = {
        str(r["commodity_id"])
        for r in workbook.get("process_outputs", [])
        if r.get("is_product") and r.get("commodity_id")
    }
    product_ids |= {
        str(r["target"])
        for r in workbook.get("io", [])
        if str(r.get("role", "")) == "output" and r.get("is_product") and r.get("target")
    }
    product_ids |= {
        str(r["commodity_id"])
        for r in workbook.get("commodities", [])
        if str(r.get("kind", "")) == "product" and r.get("commodity_id")
    }
    for r in workbook.get("demand", []):
        q = str(r.get("commodity_id", ""))
        if q and q not in product_ids:
            report.warnings.append(f"demand for '{q}' which is not produced as a product")

    return report
