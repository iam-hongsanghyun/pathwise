"""Assemble an :class:`OptimisationProblem` from a generic workbook + scenario.

This translation is **domain-agnostic**: it reads the canonical generic sheets
(``assets``, ``technologies``, ``carriers``, …) and produces the core IR. A
sector pack therefore does not need bespoke mapping code — it supplies the
schema/terminology and (optionally) post-processes the assembled problem.

Generic sheet contract (columns; ``*`` = optional sheet/column):

* ``meta``                   ``key, value`` (``base_period``, ``discount_rate`` …)
* ``assets``                 ``asset_id, group, capacity, technology_id``
                             ``[, size, built_year, retire_year, activity,``
                             `` is_candidate]``
* ``technologies``           ``technology_id, specific_energy[, fixed_opex]``
* ``carriers``               ``carrier_id, intensity, cost[, class]``
* ``carrier_compatibility``  ``technology_id, carrier_id``
* ``baseline_mix``           ``technology_id, carrier_id, share``
* ``periods``                ``year[, duration_years, activity_multiplier]``
* ``transitions*``           ``from_technology_id, to_technology_id,``
                             ``capex_per_size[, lifetime, earliest_year]``
* ``measures*``              ``measure_id, abatement, capex``
                             ``[, applicable_asset, block, energy_saving,``
                             `` lifetime, earliest_year]``
* ``new_build_options*``     ``option_id, group, technology_id, capacity,``
                             ``unit_capex[, size, lifetime, lead_time,``
                             `` earliest_year, max_units]``
* ``targets*``               ``target_set, group, target_type, year, limit``
* ``carbon_price*``          ``price_set, year, price``
* ``emission_intensity*``    ``carrier_id, year, intensity``
* ``carrier_cost*``          ``carrier_id, year, multiplier``

Time-varying inputs use a long (one-row-per-year) layout and are interpolated
onto the modelled horizon.
"""

from __future__ import annotations

import math
from typing import Any

from pathwise.core.entities import (
    Asset,
    Carrier,
    MaccBlock,
    Measure,
    Period,
    Target,
    TargetType,
    Technology,
    Transition,
)
from pathwise.core.problem import CostToggles, OptimisationProblem, SolveOptions
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.trajectory import interpolate
from pathwise.data.workbook import Workbook

Rows = list[dict[str, Any]]


def _rows(workbook: Workbook, sheet: str) -> Rows:
    return workbook.get(sheet, [])


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    return float(value)


def _int(value: Any, default: int | None = None) -> int | None:
    n = _num(value, None)
    return int(n) if n is not None else default


def _str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value).strip()


def _meta(workbook: Workbook) -> dict[str, Any]:
    return {str(r.get("key")): r.get("value") for r in _rows(workbook, "meta")}


def assemble_problem(workbook: Workbook, scenario: ScenarioConfig) -> OptimisationProblem:
    """Translate a generic workbook + scenario into an :class:`OptimisationProblem`.

    Args:
        workbook: The in-memory generic workbook (``{sheet: rows[]}``).
        scenario: The validated run definition.

    Returns:
        The assembled core problem instance.
    """
    meta = _meta(workbook)
    econ = scenario.economics
    sel = scenario.selection

    # ── Periods ──────────────────────────────────────────────────────────────
    period_rows = _rows(workbook, "periods")
    years = sorted(int(r["year"]) for r in period_rows)
    if scenario.horizon.start is not None:
        years = [y for y in years if y >= scenario.horizon.start]
    if scenario.horizon.end is not None:
        years = [y for y in years if y <= scenario.horizon.end]
    duration = {int(r["year"]): _num(r.get("duration_years"), 1.0) for r in period_rows}
    activity_mult = {int(r["year"]): _num(r.get("activity_multiplier"), 1.0) for r in period_rows}
    periods = [Period(year=y, duration_years=duration.get(y) or 1.0) for y in years]
    base_year = econ.base_period or _int(meta.get("base_period")) or (years[0] if years else 0)

    # ── Carriers (with optional price/intensity trajectories) ────────────────
    cost_traj: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, "carrier_cost"):
        cost_traj.setdefault(str(r["carrier_id"]), {})[int(r["year"])] = (
            _num(r.get("multiplier"), 1.0) or 1.0
        )
    intensity_traj: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, "emission_intensity"):
        intensity_traj.setdefault(str(r["carrier_id"]), {})[int(r["year"])] = (
            _num(r.get("intensity"), 0.0) or 0.0
        )

    carriers: list[Carrier] = []
    for r in _rows(workbook, "carriers"):
        cid = str(r["carrier_id"])
        base_cost = _num(r.get("cost"), 0.0) or 0.0
        base_int = _num(r.get("intensity"), 0.0) or 0.0
        price_by_year: dict[int, float] = {}
        if cid in cost_traj:
            mult = interpolate(cost_traj[cid], years)
            price_by_year = {y: base_cost * mult[y] for y in years}
        intensity_by_year: dict[int, float] = {}
        if cid in intensity_traj:
            intensity_by_year = interpolate(intensity_traj[cid], years)
        carriers.append(
            Carrier(
                carrier_id=cid,
                intensity_default=base_int,
                price_default=base_cost,
                intensity_by_year=intensity_by_year,
                price_by_year=price_by_year,
                carrier_class=_str(r.get("class")),
            )
        )

    # ── Technologies + compatibility ─────────────────────────────────────────
    compat: dict[str, set[str]] = {}
    for r in _rows(workbook, "carrier_compatibility"):
        compat.setdefault(str(r["technology_id"]), set()).add(str(r["carrier_id"]))
    technologies: list[Technology] = []
    for r in _rows(workbook, "technologies"):
        tid = str(r["technology_id"])
        technologies.append(
            Technology(
                technology_id=tid,
                specific_energy=_num(r.get("specific_energy"), 1.0) or 1.0,
                allowed_carriers=frozenset(compat.get(tid, set())),
                fixed_opex_default=_num(r.get("fixed_opex"), 0.0) or 0.0,
                technology_class=_str(r.get("class")),
            )
        )

    # ── Baseline mix → per-technology dominant carrier (initial state) ────────
    # The baseline carrier shares pin the starting fuel blend; the core's
    # baseline-lock uses the asset's baseline technology only, so we keep the
    # mix for reference but rely on technology baseline for the lock.

    # ── Assets (existing) ────────────────────────────────────────────────────
    assets: list[Asset] = []
    for r in _rows(workbook, "assets"):
        aid = str(r["asset_id"])
        base_activity = _num(r.get("activity"), None)
        activity_by_year: dict[int, float] = {}
        if base_activity is not None:
            activity_by_year = {y: base_activity * (activity_mult.get(y) or 1.0) for y in years}
        assets.append(
            Asset(
                asset_id=aid,
                group=str(r.get("group", "all")),
                capacity=_num(r.get("capacity"), 1e18) or 1e18,
                size=_num(r.get("size"), 1.0) or 1.0,
                baseline_technology=_str(r.get("technology_id")),
                feasible_technologies=frozenset(),  # widened below if transitions exist
                built_year=_int(r.get("built_year")),
                retire_year=_int(r.get("retire_year")),
                is_candidate=bool(r.get("is_candidate", False)),
                activity_by_year=activity_by_year,
            )
        )

    # ── Transitions (and feasible-technology widening) ───────────────────────
    transitions: list[Transition] = []
    targets_from: dict[str, set[str]] = {}
    for r in _rows(workbook, "transitions"):
        frm, to = str(r["from_technology_id"]), str(r["to_technology_id"])
        transitions.append(
            Transition(
                from_technology=frm,
                to_technology=to,
                capex_per_size=_num(r.get("capex_per_size"), 0.0) or 0.0,
                lifetime_years=_int(r.get("lifetime")),
                earliest_year=_int(r.get("earliest_year")),
            )
        )
        targets_from.setdefault(frm, set()).add(to)

    if transitions:
        widened: list[Asset] = []
        for a in assets:
            if a.baseline_technology is None:
                widened.append(a)
                continue
            reachable = {a.baseline_technology} | targets_from.get(a.baseline_technology, set())
            widened.append(
                Asset(
                    asset_id=a.asset_id,
                    group=a.group,
                    capacity=a.capacity,
                    size=a.size,
                    baseline_technology=a.baseline_technology,
                    feasible_technologies=frozenset(reachable),
                    built_year=a.built_year,
                    retire_year=a.retire_year,
                    is_candidate=a.is_candidate,
                    activity_by_year=a.activity_by_year,
                )
            )
        assets = widened

    # ── New-build options → candidate assets ─────────────────────────────────
    for r in _rows(workbook, "new_build_options"):
        oid = str(r["option_id"])
        max_units = _int(r.get("max_units"), 1) or 1
        for u in range(max_units):
            assets.append(
                Asset(
                    asset_id=f"{oid}#{u}",
                    group=str(r.get("group", "all")),
                    capacity=_num(r.get("capacity"), 0.0) or 0.0,
                    size=_num(r.get("size"), 1.0) or 1.0,
                    baseline_technology=None,
                    feasible_technologies=frozenset({str(r["technology_id"])}),
                    built_year=None,
                    retire_year=None,
                    is_candidate=True,
                    build_capex_per_size=_num(r.get("unit_capex"), 0.0) or 0.0,
                    build_lifetime_years=_int(r.get("lifetime")),
                    build_lead_years=_int(r.get("lead_time"), 0) or 0,
                )
            )

    # ── Measures (MACC), grouped into blocks per measure ─────────────────────
    measure_blocks: dict[str, dict[int, MaccBlock]] = {}
    measure_meta: dict[str, dict[str, Any]] = {}
    for r in _rows(workbook, "measures"):
        mid = str(r["measure_id"])
        block_idx = _int(r.get("block"), 0) or 0
        measure_blocks.setdefault(mid, {})[block_idx] = MaccBlock(
            abatement=_num(r.get("abatement"), 0.0) or 0.0,
            energy_saving=_num(r.get("energy_saving"), 0.0) or 0.0,
            capex=_num(r.get("capex"), 0.0) or 0.0,
        )
        measure_meta.setdefault(mid, {})
        applicable = _str(r.get("applicable_asset"))
        if applicable:
            measure_meta[mid].setdefault("assets", set()).add(applicable)
        if r.get("lifetime") is not None:
            measure_meta[mid]["lifetime"] = _int(r.get("lifetime"))
        if r.get("earliest_year") is not None:
            measure_meta[mid]["earliest_year"] = _int(r.get("earliest_year"))
    measures: list[Measure] = []
    for mid, blocks in measure_blocks.items():
        ordered = tuple(blocks[i] for i in sorted(blocks))
        info = measure_meta.get(mid, {})
        measures.append(
            Measure(
                measure_id=mid,
                applicable_assets=frozenset(info.get("assets", set())),
                blocks=ordered,
                lifetime_years=info.get("lifetime"),
                earliest_year=info.get("earliest_year"),
            )
        )

    # ── Targets (selected set) ───────────────────────────────────────────────
    targets: list[Target] = []
    by_group: dict[tuple[str, str], dict[int, float]] = {}
    for r in _rows(workbook, "targets"):
        if sel.target_set and _str(r.get("target_set")) != sel.target_set:
            continue
        grp = str(r["group"])
        ttype = str(r.get("target_type", TargetType.INTENSITY_CAP.value))
        by_group.setdefault((grp, ttype), {})[int(r["year"])] = _num(r.get("limit"), 0.0) or 0.0
    for (grp, ttype), limits in by_group.items():
        dense = interpolate(limits, years) if limits else {}
        targets.append(Target(group=grp, target_type=TargetType(ttype), limit_by_year=dense))

    # ── Carbon price (selected set) ──────────────────────────────────────────
    carbon_points: dict[int, float] = {}
    for r in _rows(workbook, "carbon_price"):
        if sel.carbon_price_set and _str(r.get("price_set")) != sel.carbon_price_set:
            continue
        carbon_points[int(r["year"])] = _num(r.get("price"), 0.0) or 0.0
    carbon_by_year = interpolate(carbon_points, years) if carbon_points else {}

    # ── Options + toggles from the scenario ──────────────────────────────────
    cc = scenario.cost_components
    options = SolveOptions(
        discount_rate=econ.discount_rate,
        base_year=base_year,
        capex_convention=econ.capex_convention,
        carbon_price_by_year=carbon_by_year if scenario.features.include_carbon_price else {},
        include_measures=scenario.features.include_measures,
        include_new_build=scenario.features.include_new_build,
        include_transitions=scenario.features.include_transitions,
        max_transitions_per_asset=scenario.max_transitions_per_asset,
        min_dwell_years=scenario.min_dwell_years,
        slack_penalty=scenario.slack_penalty,
        default_measure_lifetime_years=econ.default_measure_lifetime,
        default_newbuild_lifetime_years=econ.default_newbuild_lifetime,
    )
    toggles = CostToggles(
        fuel=cc.carrier_cost,
        fixed_opex=cc.fixed_opex,
        transition_capex=cc.transition_capex and scenario.features.include_capex,
        newbuild_capex=cc.newbuild_capex and scenario.features.include_capex,
        measure_capex=cc.measure_capex and scenario.features.include_capex,
        carbon_cost=cc.carbon_cost,
    )

    return OptimisationProblem(
        periods=periods,
        assets=assets,
        technologies=technologies,
        carriers=carriers,
        transitions=transitions,
        measures=measures,
        targets=targets,
        toggles=toggles,
        options=options,
    )
