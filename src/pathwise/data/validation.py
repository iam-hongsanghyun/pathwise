"""Workbook validation — structural and referential checks.

Returns a :class:`ValidationReport` (errors + warnings) rather than raising, so
the API can fold validation into the run result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathwise.data.aliases import normalize_workbook
from pathwise.data.hierarchy import load_hierarchy
from pathwise.data.schema import REQUIRED_SHEETS
from pathwise.data.sheets import (
    ASSETS,
    DEMAND,
    EDGES,
    FLOW_PROPERTIES,
    FLOWS,
    IMPACTS,
    IO,
    LEVERS,
    LINKS,
    NODES,
    PROCESS_INPUTS,
    PROCESS_OUTPUTS,
    PROCESSES,
    TECHNOLOGIES,
)
from pathwise.data.workbook import Workbook
from pathwise.units import CoefficientConverter, dimension_of, is_parseable

#: A flow may legitimately be measured outside its kind's dimension (e.g. a
#: fuel in tonnes rather than GJ) when it carries a factor that bridges back —
#: an ``energy_content`` property or any calorific-value (``lhv*``) key.
_ENERGY_CONTENT_KEYS = ("energy_content", "lhv")


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
    (baseline technologies, edge endpoints, input/output streams, lever targets,
    demand products).

    Args:
        workbook: The in-memory workbook.

    Returns:
        A :class:`ValidationReport`.
    """
    # Normalise any old-vocabulary sheet/column names before checking.
    workbook = normalize_workbook(workbook)
    report = ValidationReport()

    # A node hierarchy synthesises its `processes` from `assets` at assemble
    # time, so a hierarchy model is valid without a `processes` sheet.
    has_hierarchy = bool(workbook.get(NODES))

    for sheet in REQUIRED_SHEETS:
        if sheet == PROCESSES and has_hierarchy:
            if not workbook.get(ASSETS):
                report.errors.append("hierarchy model has no 'assets'")
            continue
        if sheet not in workbook or not workbook[sheet]:
            report.errors.append(f"missing required sheet '{sheet}'")
    # Technology I/O comes from the unified `io` table OR the legacy pair.
    has_io = bool(workbook.get(IO))
    has_legacy_io = bool(workbook.get(PROCESS_INPUTS)) and bool(workbook.get(PROCESS_OUTPUTS))
    if not has_io and not has_legacy_io:
        report.errors.append(
            "missing technology I/O: provide an 'io' sheet (or process_inputs + process_outputs)"
        )
    if not report.ok:
        return report  # further checks would be noise

    techs = _ids(workbook, TECHNOLOGIES, "technology_id")
    flows = _ids(workbook, FLOWS, "flow_id")
    # In a hierarchy model the assets are the facilities (one process each).
    processes = _ids(workbook, PROCESSES, "process_id") | _ids(workbook, ASSETS, "asset_id")
    impacts = _ids(workbook, IMPACTS, "impact_id")

    for r in workbook.get(ASSETS, []):
        bt = str(r.get("baseline_technology", ""))
        if bt and bt not in techs:
            report.errors.append(
                f"asset '{r.get('asset_id')}' references unknown technology '{bt}'"
            )

    # Node hierarchy: structural integrity (dangling parents, parent cycles,
    # asset/kind mismatches, connection endpoints) + connection stream refs.
    if has_hierarchy:
        h = load_hierarchy(workbook)
        if h is not None:
            report.errors.extend(h.check())  # node/cycle/kind/endpoint checks
            for r in workbook.get(LINKS, []):
                c = str(r.get("flow_id", ""))
                if c and c not in flows:
                    report.errors.append(f"connection references unknown stream '{c}'")
            # A connection only flows if some asset in the source subtree OUTPUTS
            # the flow and some asset in the target subtree INPUTS it; else
            # it silently expands to zero edges (assemble._expand_hierarchy).
            asset_tech = {
                str(r.get("asset_id")): str(r.get("baseline_technology") or "")
                for r in workbook.get(ASSETS, [])
            }
            io_out: dict[str, set[str]] = {}
            io_in: dict[str, set[str]] = {}
            for r in workbook.get(IO, []):
                tech, tgt = str(r.get("technology_id") or ""), str(r.get("target") or "")
                role = str(r.get("role") or "input")
                if role == "output":
                    io_out.setdefault(tech, set()).add(tgt)
                elif role == "input":
                    io_in.setdefault(tech, set()).add(tgt)
            for r in workbook.get(LINKS, []):
                fn, tn = str(r.get("from_node", "")), str(r.get("to_node", ""))
                com = str(r.get("flow_id", ""))
                if not (fn in h.nodes and tn in h.nodes and com):
                    continue
                makes = any(
                    com in io_out.get(asset_tech.get(m, ""), set()) for m in h.leaf_machines(fn)
                )
                takes = any(
                    com in io_in.get(asset_tech.get(m, ""), set()) for m in h.leaf_machines(tn)
                )
                if not (makes and takes):
                    report.warnings.append(
                        f"connection '{fn}'→'{tn}' on '{com}' expands to no edges "
                        "(no producing/consuming asset in the subtrees)"
                    )

    # Blend / slate share bounds must admit a feasible mix: per (technology,
    # role, group), each share_min ≤ share_max and Σ share_min ≤ 1 ≤ Σ share_max.
    group_lo: dict[tuple[str, str, str], float] = {}
    group_hi: dict[tuple[str, str, str], float] = {}
    for r in workbook.get(IO, []):
        k = str(r.get("technology_id", ""))
        if k and k not in techs:
            report.errors.append(f"io: unknown technology '{k}'")
        tgt, role = str(r.get("target", "")), str(r.get("role", "input"))
        pool = impacts if role == "impact" else flows
        if tgt and tgt not in pool:
            report.errors.append(f"io: unknown target '{tgt}' for role '{role}'")
        g = r.get("group")
        if g not in (None, "") and role in ("input", "output"):
            lo_raw, hi_raw = r.get("share_min"), r.get("share_max")
            try:
                lo = float(str(lo_raw)) if lo_raw not in (None, "") else 0.0
                hi = float(str(hi_raw)) if hi_raw not in (None, "") else 1.0
            except (TypeError, ValueError):
                continue
            if lo > hi:
                report.errors.append(
                    f"io: '{k}' group '{g}' member '{tgt}': share_min {lo} > share_max {hi}"
                )
            key = (k, role, str(g))
            group_lo[key] = group_lo.get(key, 0.0) + max(lo, 0.0)
            group_hi[key] = group_hi.get(key, 0.0) + min(hi, 1.0)
    for (k, role, g), lo_sum in group_lo.items():
        if lo_sum > 1.0 + 1e-9:
            report.errors.append(
                f"io: '{k}' {role} group '{g}': share_min values sum to {lo_sum:.3f} > 1 "
                "(no feasible mix)"
            )
    for (k, role, g), hi_sum in group_hi.items():
        if hi_sum < 1.0 - 1e-9:
            report.errors.append(
                f"io: '{k}' {role} group '{g}': share_max values sum to {hi_sum:.3f} < 1 "
                "(no feasible mix)"
            )

    for r in workbook.get(PROCESSES, []):
        bt = str(r.get("baseline_technology", ""))
        if bt and bt not in techs:
            report.errors.append(
                f"process '{r.get('process_id')}' references unknown technology '{bt}'"
            )

    for sheet, col in [(PROCESS_INPUTS, "flow_id"), (PROCESS_OUTPUTS, "flow_id")]:
        for r in workbook.get(sheet, []):
            c = str(r.get(col, ""))
            if c and c not in flows:
                report.errors.append(f"{sheet}: unknown stream '{c}'")
            k = str(r.get("technology_id", ""))
            if k and k not in techs:
                report.errors.append(f"{sheet}: unknown technology '{k}'")

    for r in workbook.get(EDGES, []):
        for end in ("from_process", "to_process"):
            p = str(r.get(end, ""))
            if p and p not in processes:
                report.errors.append(f"edge references unknown facility '{p}'")
        c = str(r.get("flow_id", ""))
        if c and c not in flows:
            report.errors.append(f"edge references unknown stream '{c}'")

    for r in workbook.get(LEVERS, []):
        ap = str(r.get("applies_to", ""))
        if ap and ap not in processes:
            report.warnings.append(
                f"lever '{r.get('lever_id')}' applies to unknown facility '{ap}'"
            )
        tgt, mtype = str(r.get("target", "")), str(r.get("type", ""))
        pool = flows if mtype == "energy_efficiency" else impacts
        if tgt and tgt not in pool:
            report.warnings.append(f"lever '{r.get('lever_id')}' targets unknown '{tgt}'")

    product_ids = {
        str(r["flow_id"])
        for r in workbook.get(PROCESS_OUTPUTS, [])
        if r.get("is_product") and r.get("flow_id")
    }
    product_ids |= {
        str(r["target"])
        for r in workbook.get(IO, [])
        if str(r.get("role", "")) == "output" and r.get("is_product") and r.get("target")
    }
    product_ids |= {
        str(r["flow_id"])
        for r in workbook.get(FLOWS, [])
        if str(r.get("kind", "")) == "product" and r.get("flow_id")
    }
    for r in workbook.get(DEMAND, []):
        q = str(r.get("flow_id", ""))
        if q and q not in product_ids:
            report.warnings.append(f"demand for '{q}' which is not produced as a product")

    _check_units(workbook, report)
    return report


def _check_units(workbook: Workbook, report: ValidationReport) -> None:
    """Warn (never block) on unitless / unparseable / mis-dimensioned streams.

    Units are metadata: a missing or wrong unit can't make the solve infeasible,
    so every finding here is a warning. Checks each flow / impact declares a
    real, pint-parseable unit, and that an ``energy`` stream is energy-dimensioned
    unless it carries an ``energy_content`` factor (the legitimate tonnes-of-fuel
    case — see flow-specific conversions).
    """
    # flow_id -> set of property names it declares (for the fuel exception).
    props: dict[str, set[str]] = {}
    for r in workbook.get(FLOW_PROPERTIES, []):
        cid, prop = str(r.get("flow_id", "")), str(r.get("property", "")).lower()
        if cid and prop:
            props.setdefault(cid, set()).add(prop)

    def _has_energy_content(cid: str) -> bool:
        return any(key.startswith(_ENERGY_CONTENT_KEYS) for key in props.get(cid, set()))

    def _check_unit(label: str, unit: str) -> bool:
        """Common placeholder / parseability check; True if the unit is real."""
        if unit in ("", "unit"):
            report.warnings.append(f"{label} has no real unit (still the 'unit' placeholder)")
            return False
        if not is_parseable(unit):
            report.warnings.append(f"{label} has an unrecognised unit '{unit}'")
            return False
        return True

    for r in workbook.get(FLOWS, []):
        cid = str(r.get("flow_id", ""))
        if not cid:
            continue
        unit = str(r.get("unit", "") or "")
        if not _check_unit(f"flow '{cid}'", unit):
            continue
        kind = str(r.get("kind", "") or "")
        if kind == "energy" and dimension_of(unit) != "energy" and not _has_energy_content(cid):
            report.warnings.append(
                f"energy flow '{cid}' has non-energy unit '{unit}' and no energy_content "
                "factor — add one so it can be converted to energy"
            )

    for r in workbook.get(IMPACTS, []):
        iid = str(r.get("impact_id", ""))
        if iid:
            _check_unit(f"impact '{iid}'", str(r.get("unit", "") or ""))

    _check_io_units(workbook, report)


def _check_io_units(workbook: Workbook, report: ValidationReport) -> None:
    """Warn (never block) on io rows whose declared unit can't reach the stream's.

    Dry-runs the SAME :class:`CoefficientConverter` the assembler uses (the single
    source of truth for "is this convertible"), so the warning matches exactly what
    assembly does — leave the coefficient as authored. Only rows that actually declare
    a unit are checked, so libraries without units stay silent.
    """
    io_rows = workbook.get(IO, [])
    if not any(str(r.get("unit", "") or "").strip() for r in io_rows):
        return
    props: dict[str, dict[str, float]] = {}
    for r in workbook.get(FLOW_PROPERTIES, []):
        cid, prop, val = r.get("flow_id"), r.get("property"), r.get("value")
        if cid and prop and isinstance(val, (int, float)):
            props.setdefault(str(cid), {})[str(prop)] = float(val)
    converter = CoefficientConverter(
        flow_units={
            str(r["flow_id"]): str(r.get("unit", "") or "")
            for r in workbook.get(FLOWS, [])
            if r.get("flow_id")
        },
        flow_props=props,
        impact_units={
            str(r["impact_id"]): str(r.get("unit", "") or "")
            for r in workbook.get(IMPACTS, [])
            if r.get("impact_id")
        },
    )
    for r in io_rows:
        unit = str(r.get("unit", "") or "").strip()
        target = str(r.get("target", "") or "")
        if unit and target:
            role = (str(r.get("role", "") or "input")).lower()
            converter.to_canonical(1.0, unit, target, role)  # value is irrelevant here
    report.warnings.extend(f"io unit: {issue}" for issue in converter.issues)
