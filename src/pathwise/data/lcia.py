"""LCIA factor library: bundled methods + importers for open datasets.

Two things turn the raw per-flow inventory into a *characterised* multi-impact LCA:

* **Characterisation factors (CFs)** — map an elementary-flow impact to an impact
  CATEGORY (e.g. CO₂/CH₄/N₂O → GWP). Fed to the engine via the ``characterisation``
  sheet (see :mod:`pathwise.core.build`).
* **Background factors** — cradle-to-gate impact per unit of a *purchased* flow
  (grid electricity, fuels, …). Fed via the ``flow_impacts`` sheet.

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

#: Acidification — EF 3.1 "Accumulated Exceedance" [mol H⁺ eq / kg flow].
#: Representative midpoint CFs (JRC EF 3.1); replace with the official table via
#: :func:`load_method_csv` for a certified study.
ACIDIFICATION_EF31: dict[str, float] = {"SO2": 1.31, "NOx": 0.74, "NH3": 3.02}

#: Eutrophication, freshwater — EF 3.1 [kg P eq / kg flow] (P-limited waters).
EUTROPHICATION_FW_EF31: dict[str, float] = {"P": 1.0, "PO4": 0.33}

#: Eutrophication, marine — EF 3.1 [kg N eq / kg flow] (N content of the species).
EUTROPHICATION_MARINE_EF31: dict[str, float] = {"NOx": 0.30, "NH3": 0.82, "N": 1.0}

#: Particulate-matter formation — EF 3.1 [disease incidence / kg flow]. Tiny
#: absolute magnitudes (a health endpoint), so this category lives on a different
#: scale from the others — expected, each category is independent.
PARTICULATE_EF31: dict[str, float] = {
    "PM25": 6.30e-4,
    "SO2": 2.90e-5,
    "NOx": 1.10e-5,
    "NH3": 2.70e-5,
}

#: Photochemical ozone formation — EF 3.1 [kg NMVOC eq / kg flow].
PHOTOCHEM_EF31: dict[str, float] = {"NMVOC": 1.0, "NOx": 1.22, "SO2": 0.0857}

#: Bundled methods: ``method_id -> {category_id -> {flow_impact_id -> factor}}``.
#: ``ipcc_gwp100`` is GWP only; ``ef31`` is a representative multi-category EF 3.1
#: seed (GWP + acidification + eutrophication + PM + photochemical ozone). For a
#: certified study, import the full published CF table via :func:`load_method_csv`.
METHODS: dict[str, dict[str, dict[str, float]]] = {
    "ipcc_gwp100": {"GWP": GWP100_AR6},
    "ef31": {
        "GWP": GWP100_AR6,
        "AP": ACIDIFICATION_EF31,
        "EP_freshwater": EUTROPHICATION_FW_EF31,
        "EP_marine": EUTROPHICATION_MARINE_EF31,
        "PM": PARTICULATE_EF31,
        "POCP": PHOTOCHEM_EF31,
    },
}

#: Representative cradle-to-gate background factors for common purchased carriers
#: and materials — a *seed* for demos, NOT a substitute for a real LCI database.
#: Each inner map is ``{elementary_flow: factor per unit of the flow}``; the
#: flows feed the same characterisation CFs above, so background burdens land in
#: every category. Sources: IEA/IPCC energy factors + ecoinvent-order-of-magnitude
#: process emissions. Keyed by a generic flow id and a generic unit (noted
#: per row) — rename / rescale to the model's ids, or import a real dataset via
#: :func:`load_background_csv`.
BACKGROUND_SEED: dict[str, dict[str, float]] = {
    # per kWh electricity (world-average grid)
    "electricity": {"CO2": 0.40, "CH4": 7.0e-4, "SO2": 9.0e-4, "NOx": 7.0e-4, "PM25": 4.0e-5},
    # per kWh of fuel (combustion + upstream)
    "natural_gas": {"CO2": 0.20, "CH4": 4.0e-4, "NOx": 1.5e-4},
    "coal": {"CO2": 0.34, "CH4": 1.2e-3, "SO2": 1.1e-3, "NOx": 8.0e-4, "PM25": 6.0e-5},
    "diesel": {"CO2": 0.27, "SO2": 2.0e-4, "NOx": 1.3e-3, "PM25": 5.0e-5},
    # per kg material (cradle-to-gate)
    "iron_ore": {"CO2": 0.03, "SO2": 6.0e-5, "NOx": 1.0e-4, "PM25": 8.0e-5},
    "scrap": {"CO2": 0.02, "NOx": 4.0e-5},
    "limestone": {"CO2": 0.02, "PM25": 3.0e-5},
    "coke": {"CO2": 0.45, "SO2": 1.5e-3, "NOx": 9.0e-4, "CH4": 1.0e-3},
    # per tonne-km road freight
    "transport": {"CO2": 0.10, "NOx": 6.0e-4, "PM25": 2.0e-5},
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
    """``flow_impacts`` sheet rows from a ``{flow: {impact: factor}}`` map
    (defaults to the bundled :data:`BACKGROUND_SEED`)."""
    src = BACKGROUND_SEED if factors is None else factors
    return [
        {"flow_id": flow, "impact_id": impact, "factor": factor}
        for flow, impacts in src.items()
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
    """Parse an open background-factor CSV into ``flow_impacts`` rows.

    Columns: ``flow_id, impact_id, factor`` — the shape an open EEIO/energy
    dataset (USEEIO / EXIOBASE / IEA) is reduced to.
    """
    out: list[dict[str, Any]] = []
    for r in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        c, i, fac = row.get("flow_id"), row.get("impact_id"), row.get("factor")
        if c and i and fac:
            out.append({"flow_id": c, "impact_id": i, "factor": float(fac)})
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
        wb["flow_impacts"] = [*wb.get("flow_impacts", []), *background]
    return wb
