"""LCIA factor library: bundled methods + importers for open datasets.

Two things turn the raw per-flow inventory into a *characterised* multi-impact LCA:

* **Characterisation factors (CFs)** — map an elementary-flow impact to an impact
  CATEGORY (e.g. CO₂/CH₄/N₂O → GWP). Fed to the engine via the ``characterisation``
  sheet (see :mod:`pathwise.core.build`).
* **Background factors** — cradle-to-gate impact per unit of a *purchased* commodity
  (grid electricity, fuels, …). Fed via the ``commodity_impacts`` sheet.

This module bundles a small, well-established **GWP100 (IPCC AR6)** seed and a few
representative background factors so the layer works out of the box, and provides
**CSV importers** so a user can drop in a full published method (EF 3.1 / ReCiPe CF
tables from the JRC) or an open background dataset (USEEIO / EXIOBASE / IEA). The
engine is method-agnostic — it only consumes the resulting rows.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from pathwise.data.workbook import Workbook

#: IPCC AR6 GWP100 characterisation factors [kg CO₂e / kg]. Non-fossil CH₄; the
#: fossil value is ~29.8. Authoritative, widely-cited — safe to bundle.
GWP100_AR6: dict[str, float] = {"CO2": 1.0, "CH4": 27.0, "N2O": 273.0}

#: Bundled methods: ``method_id -> {category_id -> {flow_impact_id -> factor}}``.
#: Only GWP100 is shipped with real values; a full method (EF 3.1 / ReCiPe) is
#: imported from its published CF table via :func:`load_method_csv`.
METHODS: dict[str, dict[str, dict[str, float]]] = {
    "ipcc_gwp100": {"GWP": GWP100_AR6},
}

#: Representative cradle-to-gate CO₂ factors for common purchased carriers — a
#: *seed* for demos, NOT a substitute for a real background dataset. Keyed by a
#: generic commodity id (rename to the model's ids, or import a real dataset).
BACKGROUND_SEED: dict[str, dict[str, float]] = {
    "electricity": {"CO2": 0.40},  # kg CO₂ / kWh, world-average grid (order-of-magnitude)
    "natural_gas": {"CO2": 0.20},  # kg CO₂ / kWh (combustion + upstream)
    "coal": {"CO2": 0.34},
    "diesel": {"CO2": 0.27},
}


def characterisation_rows(method: str = "ipcc_gwp100") -> list[dict[str, Any]]:
    """``characterisation`` sheet rows for a bundled method id.

    Raises:
        KeyError: if ``method`` is not bundled (use :func:`load_method_csv`).
    """
    cats = METHODS[method]
    return [
        {"flow_impact_id": flow, "category_id": cat, "factor": factor}
        for cat, flows in cats.items()
        for flow, factor in flows.items()
    ]


def background_rows(factors: dict[str, dict[str, float]] | None = None) -> list[dict[str, Any]]:
    """``commodity_impacts`` sheet rows from a ``{commodity: {impact: factor}}`` map
    (defaults to the bundled :data:`BACKGROUND_SEED`)."""
    src = BACKGROUND_SEED if factors is None else factors
    return [
        {"commodity_id": commodity, "impact_id": impact, "factor": factor}
        for commodity, impacts in src.items()
        for impact, factor in impacts.items()
    ]


def load_method_csv(text: str) -> list[dict[str, Any]]:
    """Parse a characterisation-factor CSV into ``characterisation`` rows.

    Columns (header, case-insensitive): ``flow_impact_id, category_id, factor`` —
    the shape a published method's CF table is reduced to. Use this to import the
    official EF 3.1 / ReCiPe tables (download from the JRC) instead of the bundled
    GWP seed.
    """
    out: list[dict[str, Any]] = []
    for r in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        flow, cat, fac = row.get("flow_impact_id"), row.get("category_id"), row.get("factor")
        if flow and cat and fac:
            out.append({"flow_impact_id": flow, "category_id": cat, "factor": float(fac)})
    return out


def load_background_csv(text: str) -> list[dict[str, Any]]:
    """Parse an open background-factor CSV into ``commodity_impacts`` rows.

    Columns: ``commodity_id, impact_id, factor`` — the shape an open EEIO/energy
    dataset (USEEIO / EXIOBASE / IEA) is reduced to.
    """
    out: list[dict[str, Any]] = []
    for r in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        c, i, fac = row.get("commodity_id"), row.get("impact_id"), row.get("factor")
        if c and i and fac:
            out.append({"commodity_id": c, "impact_id": i, "factor": float(fac)})
    return out


def apply_lcia(
    workbook: Workbook,
    *,
    characterisation: list[dict[str, Any]] | None = None,
    background: list[dict[str, Any]] | None = None,
) -> Workbook:
    """Return a copy of ``workbook`` with characterisation / background rows merged in.

    Existing rows are kept; the new rows are appended (later rows win at solve time
    only if they duplicate a key, which the engine reads last-writes). The base
    workbook is not mutated.
    """
    wb: Workbook = dict(workbook)
    if characterisation:
        wb["characterisation"] = [*wb.get("characterisation", []), *characterisation]
    if background:
        wb["commodity_impacts"] = [*wb.get("commodity_impacts", []), *background]
    return wb
