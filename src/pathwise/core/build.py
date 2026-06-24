"""Assemble the ``linopy`` model: variables → constraints → objective.

Constraint families are **vectorised over xarray dims** — each family issues one
(or a small constant number of) ``m.add_constraints`` call rather than one per
scalar cell.  The ``feas`` / ``member_da`` / ``foutmask`` patterns near the top
of :func:`_technology` and :func:`_blend` set the idiom; the heavier families
(flow balance, impacts, lifecycle, vintage gate) follow the same approach.

Linopy/xarray idioms used throughout:
* Sum over a dim:       ``ctx.u.sum("tech")``
* Previous-period ref: ``ctx.u.shift(period=1)``  (NaN in t₀ → mask it away)
* Coefficient array:   precompute as ``xr.DataArray``, broadcast multiply, then
                       ``.sum(dim)`` to contract.
* Infeasible cells:    ``mask=bool_DataArray`` skips them instead of adding a
                       trivially-false constraint.
"""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr
from linopy import Model

from pathwise.core.entities import (
    CommodityKind,
    MeasureType,
    ObjectiveMode,
    Transition,
    TransitionAction,
)
from pathwise.core.problem import Problem
from pathwise.core.variables import BuildContext, build_context
from pathwise.logger import get_logger

logger = get_logger(__name__)

#: Big-M for the indicator/throughput links: a value safely above any feasible
#: throughput. Scaled off the largest nameplate capacity plus a floor so it stays
#: valid even when every capacity is tiny.
_BIG_M_CAPACITY_SCALE = 1.0e3
_BIG_M_FLOOR = 1.0e6


def _big_m(problem: Problem) -> float:
    """A Big-M safely above any feasible throughput in ``problem``."""
    peak = max((p.capacity for p in problem.processes), default=1.0) or 1.0
    return peak * _BIG_M_CAPACITY_SCALE + _BIG_M_FLOOR


def _lin_sum(terms: list[Any]) -> Any:
    """Sum a list of ``linopy`` expressions (``None`` if empty)."""
    if not terms:
        return None
    acc = terms[0]
    for t in terms[1:]:
        acc = acc + t
    return acc


def build(problem: Problem) -> BuildContext:
    """Build the full ``linopy`` model for ``problem`` and return its context."""
    model = Model()
    ctx = build_context(model, problem)
    logger.info(
        "model built: %d processes, %d techs, %d commodities, %d impacts, %d periods, "
        "%d edges, %d measure-slots",
        len(ctx.procs),
        len(ctx.techs),
        len(ctx.comms),
        len(ctx.impacts),
        len(ctx.years),
        len(problem.edges),
        len(ctx.slots),
    )
    _technology(ctx)
    _lifecycle(ctx)
    _vintage_gate(ctx)
    _blend(ctx)
    _output_blend(ctx)
    _flow_balance(ctx)
    _purchase_caps(ctx)
    _storage(ctx)
    _markets(ctx)
    _impacts(ctx)
    _macc(ctx)
    _controls(ctx)
    _adoption_caps(ctx)
    _fleet(ctx)
    _objective(ctx)
    return ctx


def _prev(years: list[int]) -> dict[int, int | None]:
    return {y: (years[i - 1] if i > 0 else None) for i, y in enumerate(years)}


def _technology(ctx: BuildContext) -> None:
    """One active technology per process; capacity link; baseline lock; events.

    Vectorised over (process, tech, period) in a single pass per constraint
    family — no scalar-cell Python loops.

    Constraint families
    -------------------
    ufeas / wfeas / xfeas
        Infeasible (process, tech, period) cells are forbidden by clamping the
        binary/continuous variables to zero via the pre-built ``feas`` array.
    one_tech
        sum_k u[p,k,t] == on[p,t]  (one active technology while operating)
    cap
        x[p,k,t] <= cap[p,t] * u[p,k,t]  (throughput bounded by capacity)
    mincf
        x[p,k,t] >= mincf[p,k,t] * cap[p,t] * u[p,k,t]  (must-run floor)
    decomm
        on[p,t] == 0  for t > decommission_year_p
    baseline
        u[p,baseline_p,t0] == on[p,t0]  (starts on baseline; no prior switch)
    w0 / event
        w[p,k,t0] == 0 ;  w[p,k,t] >= u[p,k,t] - u[p,k,t-1]  (switch-in event)
    """
    m, prob = ctx.model, ctx.problem
    avail = {p.process_id: p for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}

    # ── Feasibility array (process, tech, period) ────────────────────────────
    # A transition target additionally respects its ``introduction_year`` (not
    # adoptable before it); the BASELINE is exempt — it is already installed.
    # Phase-out binds every technology (including the installed baseline) —
    # after it the facility must transition or switch off.
    def _feas(p: str, k: str, t: int) -> float:
        # Forced switch (simulate only): the machine may run ONLY its baseline
        # before the forced year and ONLY the target technology from it. With the
        # one-active-technology constraint this alone pins the timed schedule, and
        # it overrides the normal availability gating (the switch is a user decree,
        # not an optimiser choice).
        forced = prob.forced_switches.get(p)
        if forced is not None:
            to_tech, year = forced
            if k == to_tech:
                return 1.0 if t >= year else 0.0
            if k == baseline[p]:
                return 1.0 if t < year else 0.0
            return 0.0
        if k not in ctx.feasible[p]:
            return 0.0
        if k != baseline[p]:
            intro = prob.technologies[k].introduction_year
            if intro is not None and t < intro:
                return 0.0
        # phase_out_year is the EXCLUSIVE end of availability (usable until it,
        # gone from it) — e.g. phase_out 2040 ⇒ unusable from 2040.
        out = prob.technologies[k].phase_out_year
        if out is not None and t >= out:
            return 0.0
        return 1.0

    feas_arr = np.array(
        [[[_feas(p, k, t) for t in ctx.years] for k in ctx.techs] for p in ctx.procs]
    )
    feas = xr.DataArray(
        feas_arr,
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )
    big = _big_m(prob)
    # Infeasible cells forced to zero (vectorised over all dims at once).
    m.add_constraints(ctx.u <= feas, name="ufeas")
    m.add_constraints(ctx.w <= feas, name="wfeas")
    m.add_constraints(ctx.x <= big * feas, name="xfeas")

    # ── one_tech: sum_k u[p,k,t] == on[p,t] ────────────────────────────────
    # u is already 0 on infeasible cells (via ufeas), so summing over ALL techs
    # is identical to summing over feasible techs.
    m.add_constraints(ctx.u.sum("tech") == ctx.on, name="one_tech")

    # ── capacity & must-run (vectorised over process × tech × period) ────────
    # Precompute available capacity[p,t] and min_cf[p,k,t] as DataArrays.
    cap_arr = np.array([[avail[p].available(t) for t in ctx.years] for p in ctx.procs])
    cap_da = xr.DataArray(
        cap_arr,
        coords={"process": ctx.procs, "period": ctx.years},
        dims=["process", "period"],
    )
    # cap_da broadcasts over the tech dim when multiplied by u (process,tech,period).
    m.add_constraints(ctx.x <= cap_da * ctx.u, name="cap")

    # Must-run floor: min_cf[p,k,t] > 0 only for active technologies.
    min_cf_arr = np.array(
        [
            [[prob.technologies[k].min_cf_at(t) for t in ctx.years] for k in ctx.techs]
            for p in ctx.procs
        ]
    )
    min_cf_da = xr.DataArray(
        min_cf_arr,
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )
    # Only add mincf where the floor is positive (skip trivial 0 >= 0 cells).
    mincf_mask = (min_cf_da > 0.0) & (feas > 0.0)
    if bool(mincf_mask.any()):
        m.add_constraints(
            ctx.x >= min_cf_da * cap_da * ctx.u,
            mask=mincf_mask,
            name="mincf",
        )

    # Utilisation ceiling (per-machine max capacity factor): x ≤ max_cf · cap · u.
    # Per process (broadcasts over tech); only where max_cf < 1 (1.0 ⇒ the plain
    # `cap` constraint already binds, so skip to avoid a redundant row).
    max_cf_arr = np.array([[avail[p].max_cf_at(t) for t in ctx.years] for p in ctx.procs])
    max_cf_da = xr.DataArray(
        max_cf_arr,
        coords={"process": ctx.procs, "period": ctx.years},
        dims=["process", "period"],
    )
    maxcf_mask = (max_cf_da < 1.0) & (feas > 0.0)
    if bool(maxcf_mask.any()):
        m.add_constraints(
            ctx.x <= max_cf_da * cap_da * ctx.u,
            mask=maxcf_mask,
            name="maxcf",
        )

    # ── Active window: on[p,t] == 0 outside [build_year, close_year) ─────────
    # A machine exists only within its build/close window: off before its build
    # year (introduced_year) and off from its close year (decommission_year,
    # EXCLUSIVE — close 2038 ⇒ runs through 2037). This window overrides the
    # technical lifespan. Either bound is optional (None ⇒ unbounded that side).
    window_mask = np.zeros((len(ctx.procs), len(ctx.years)), dtype=bool)
    for i, p in enumerate(ctx.procs):
        build = avail[p].introduced_year
        close = avail[p].decommission_year
        for j, t in enumerate(ctx.years):
            if (build is not None and t < build) or (close is not None and t >= close):
                window_mask[i, j] = True
    if window_mask.any():
        window_da = xr.DataArray(
            window_mask,
            coords={"process": ctx.procs, "period": ctx.years},
            dims=["process", "period"],
        )
        m.add_constraints(ctx.on == 0, mask=window_da, name="active_window")

    # ── baseline[p]: u[p,baseline,t0] == on[p,t0] ───────────────────────────
    t0 = ctx.years[0]
    base_mask = np.zeros((len(ctx.procs), len(ctx.techs)), dtype=bool)
    for i, p in enumerate(ctx.procs):
        if p in prob.forced_switches:
            continue  # forced schedule already sets the t0 technology via feasibility
        j = ctx.techs.index(baseline[p])
        base_mask[i, j] = True
    base_da = xr.DataArray(
        base_mask,
        coords={"process": ctx.procs, "tech": ctx.techs},
        dims=["process", "tech"],
    )
    # sel on period=t0 reduces u to (process, tech); on is (process, period) so
    # sel on period=t0 gives (process,).  Broadcast via mask over (process,tech).
    m.add_constraints(
        ctx.u.sel(period=t0) == ctx.on.sel(period=t0),
        mask=base_da,
        name="baseline",
    )

    # ── w-event: w[p,k,t0]==0 ; w[p,k,t]>=u[p,k,t]-u[p,k,t-1] ─────────────
    # shift(period=1) fills t0 with NaN (propagated as "missing") — linopy
    # treats NaN coefficients as zero in constraints, so the event constraint
    # would be trivially 0 >= 0 at t0.  We split into two vectorised calls:
    #   (a) t0 slice: w == 0   (only where feas > 0)
    #   (b) t>t0:     w >= u - u.shift(period=1)  (only where feas > 0)

    # t0 mask: (process, tech) where feasible
    feas_t0 = feas.sel(period=t0) > 0.0  # (process, tech) bool DataArray
    m.add_constraints(ctx.w.sel(period=t0) == 0, mask=feas_t0, name="w0")

    # t>t0 mask: (process, tech, period) where feasible and period != t0
    not_t0 = xr.DataArray(
        np.array([t != t0 for t in ctx.years]),
        coords={"period": ctx.years},
        dims=["period"],
    )
    event_mask = (feas > 0.0) & not_t0
    if bool(event_mask.any()):
        u_prev = ctx.u.shift(period=1)  # NaN at t0; harmless given the mask
        m.add_constraints(ctx.w >= ctx.u - u_prev, mask=event_mask, name="event")


def _lifecycle(ctx: BuildContext) -> None:
    r"""Asset end-of-life: force a renewal or replacement when a vintage expires.

    A technology may be active in year ``t`` only if a *live vintage* covers it:
    the original baseline install (while ``t < introduced_year + lifespan``), a
    replacement switch-in (``w``), or a renewal rebuild (``ren``) that happened
    within the trailing ``lifespan`` window. Once the window lapses the facility
    must renew the same technology, replace it, or switch off — capturing the
    capital wear-out the engine previously ignored.

    Algorithm:
        For process ``p``, technology ``k`` of life ``L`` and year ``t``::

            u[p,k,t] <= live0[p,k,t]
                        + Σ_{t' in years, t-L < t' <= t} refresh[p,k,t']

        refresh = ren                  (k is the baseline — a rebuild)
                = w + ren              (k reached by replacement — switch-in or rebuild)
        live0   = 1 if k is baseline and t < introduced_year + L, else 0

    Only processes that declare ``introduced_year`` are lifecycle-tracked; every
    other process (and every model with no install dates) is left untouched, so
    existing scenarios are unchanged. A renewal is permitted only for a
    technology whose ``actions`` include :attr:`TransitionAction.RENEW` and only
    while it is the active technology.

    Full vectorisation strategy
    ---------------------------
    All four constraint families are vectorised over the tracked (process, tech,
    period) cube in a small constant number of ``add_constraints`` calls:

    renact
        ren[p,k,t] <= u[p,k,t]  where can_renew[k] is True and (p,k) is tracked.
        Build a boolean mask over the full (process, tech, period) cube; True where
        (p tracked AND k feasible for p AND can_renew[k] AND feas[p,k,t]>0).

    renfeas
        ren[p,k,t] == 0  where can_renew[k] is False or (p,k) not tracked.
        Complement of renact, also as a single vectorised constraint.

    live-vintage window
        u[p,k,t] <= live0[p,k,t] + Σ_{tp: t-L_k<tp<=t} refresh[p,k,tp]

        refresh_coeff[is_base] x_coeff:
            refresh[p,k,tp] = ren[p,k,tp]               (k == baseline_p)
            refresh[p,k,tp] = w[p,k,tp] + ren[p,k,tp]   (k is a replacement target)

        Precompute window matrix W_k[t, tp] = 1 iff t-L_k < tp <= t (per tech k).
        Then for all tracked (p, k) simultaneously:
            window_sum[p,k,t] = Σ_tp W[k,t,tp] * refresh[p,k,tp]
        expressed as (W_da * refresh_renamed_tp).sum("tp").

        Two separate constraints for baseline and non-baseline techs keep the
        coordinate structures uniform (no mixed fout-vs-yield alignment issue).
    """
    if ctx.ren is None:
        return
    m, prob = ctx.model, ctx.problem
    # Forced (simulate) machines are exempt from end-of-life vintage gating — the
    # forced switch is a decree, and its stranded-asset cost is booked separately.
    tracked = [
        p
        for p in prob.processes
        if p.introduced_year is not None and p.process_id not in prob.forced_switches
    ]
    if not tracked:
        return
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    tracked_pids = {p.process_id for p in tracked}

    T = len(ctx.years)

    # ── Build tracked-feasible masks ─────────────────────────────────────────
    # can_renew_mask[p,k,t]: True iff p is tracked, k is feasible for p,
    #   tech k allows renewal, AND feas[p,k,t] > 0.
    # no_renew_mask: complement within tracked-feasible space.
    can_renew_arr = np.zeros((len(ctx.procs), len(ctx.techs), T), dtype=bool)
    no_renew_arr = np.zeros((len(ctx.procs), len(ctx.techs), T), dtype=bool)
    for i, pid in enumerate(ctx.procs):
        if pid not in tracked_pids:
            continue
        for j, k in enumerate(ctx.techs):
            if k not in ctx.feasible[pid]:
                continue
            tech = prob.technologies[k]
            can = TransitionAction.RENEW in tech.actions
            for li in range(T):
                if can:
                    can_renew_arr[i, j, li] = True
                else:
                    no_renew_arr[i, j, li] = True

    # Recompute the same feasibility array used in _technology (no shared state).
    def _feas_lc(pid: str, k: str, t: int) -> float:
        if k not in ctx.feasible[pid]:
            return 0.0
        if k != baseline[pid]:
            intro = prob.technologies[k].introduction_year
            if intro is not None and t < intro:
                return 0.0
        out = prob.technologies[k].phase_out_year
        if out is not None and t >= out:  # exclusive end (see _feas)
            return 0.0
        return 1.0

    feas_arr = np.array(
        [[[_feas_lc(pid, k, t) for t in ctx.years] for k in ctx.techs] for pid in ctx.procs]
    )

    renact_mask = xr.DataArray(
        can_renew_arr & (feas_arr > 0),
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )
    renfeas_mask = xr.DataArray(
        no_renew_arr,
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )
    if bool(renact_mask.any()):
        m.add_constraints(ctx.ren <= ctx.u, mask=renact_mask, name="renact")
    if bool(renfeas_mask.any()):
        m.add_constraints(ctx.ren == 0, mask=renfeas_mask, name="renfeas")

    # ── Per-machine renewal-count cap ─────────────────────────────────────────
    # A machine that declares ``max_renewals`` may rebuild (renew) at most that
    # many times over the whole horizon, summed across every technology it runs:
    #     Σ_{k, t} ren[p, k, t] <= max_renewals[p]
    # ``0`` forbids renewal (it must replace at end of life); ``None`` (the
    # default) adds no row, leaving renewals unlimited. The window constraint then
    # forces a *replacement* once the budget is spent and a vintage expires.
    proc_by_id = {p.process_id: p for p in prob.processes}
    cap_vals = np.zeros(len(ctx.procs), dtype=float)
    capped = np.zeros(len(ctx.procs), dtype=bool)
    for i, pid in enumerate(ctx.procs):
        n = proc_by_id[pid].max_renewals
        if n is not None:
            cap_vals[i] = float(n)
            capped[i] = True
    if capped.any():
        cap_da = xr.DataArray(cap_vals, coords={"process": ctx.procs}, dims=["process"])
        cap_mask = xr.DataArray(capped, coords={"process": ctx.procs}, dims=["process"])
        m.add_constraints(ctx.ren.sum(["tech", "period"]) <= cap_da, mask=cap_mask, name="rencap")

    # ── Live-vintage window constraint ────────────────────────────────────────
    # Group techs by lifespan so each group shares one window matrix.
    # Build window_da[k, t, tp]: 1 iff years[t] - L_k < years[tp] <= years[t].
    life_by_tech = {k: max(int(prob.technologies[k].lifespan), 1) for k in ctx.techs}

    # Window tensor: (tech, period, tp)
    W_arr = np.zeros((len(ctx.techs), T, T), dtype=float)
    for j, k in enumerate(ctx.techs):
        life = life_by_tech[k]
        for ti, t in enumerate(ctx.years):
            for tpi, tp in enumerate(ctx.years):
                if t - life < tp <= t:
                    W_arr[j, ti, tpi] = 1.0
    window_da = xr.DataArray(
        W_arr,
        coords={"tech": ctx.techs, "period": ctx.years, "tp": ctx.years},
        dims=["tech", "period", "tp"],
    )

    # live0[p,k,t]: initial-install coverage for tracked processes
    live0_arr = np.zeros((len(ctx.procs), len(ctx.techs), T), dtype=float)
    for i, pid in enumerate(ctx.procs):
        if pid not in tracked_pids:
            continue
        # Find the Process object for introduced_year
        proc_obj = next(p for p in tracked if p.process_id == pid)
        inst = proc_obj.introduced_year or ctx.years[0]
        k_base = baseline[pid]
        j_base = ctx.techs.index(k_base)
        tech = prob.technologies[k_base]
        life = max(int(tech.lifespan), 1)
        for li, t in enumerate(ctx.years):
            if t < inst + life:
                live0_arr[i, j_base, li] = 1.0
    live0_da = xr.DataArray(
        live0_arr,
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )

    # tracked-feasible mask for the life constraint (only add where meaningful)
    tracked_feas = xr.DataArray(
        np.array(
            [
                [
                    [
                        1.0 if (pid in tracked_pids and k in ctx.feasible[pid]) else 0.0
                        for t in ctx.years
                    ]
                    for k in ctx.techs
                ]
                for pid in ctx.procs
            ]
        ),
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )
    life_mask = tracked_feas > 0.0

    # refresh variable:  for the baseline tech:     refresh = ren  (rebuild only)
    #                    for a replacement target:  refresh = w + ren
    #
    # The baseline must be refreshed by `ren` ONLY — not the switch-in `w`. `w` is
    # uncharged for the baseline (the objective skips capex on the baseline tech)
    # and only lower-bounded by the switch event, so allowing it into the covering
    # sum would let an expired baseline vintage rebuild itself FOR FREE in any year
    # past t0 (w == 1 costs nothing and satisfies the window), bypassing both the
    # renewal cost and the per-machine renewal cap. Zeroing w's coefficient on the
    # baseline (p, k) forces those rebuilds through the priced, capped `ren`.
    # w_coeff[p,k] = 0 iff k == baseline[p], else 1.
    w_coeff_arr = np.ones((len(ctx.procs), len(ctx.techs)), dtype=float)
    for i, pid in enumerate(ctx.procs):
        w_coeff_arr[i, ctx.techs.index(baseline[pid])] = 0.0
    w_coeff_da = xr.DataArray(
        w_coeff_arr,
        coords={"process": ctx.procs, "tech": ctx.techs},
        dims=["process", "tech"],
    )

    # Rename period → tp for ren and w to enable the window contraction.
    ren_tp = ctx.ren.rename({"period": "tp"})  # (process, tech, tp)
    w_tp = ctx.w.rename({"period": "tp"})  # (process, tech, tp)

    # refresh = w·w_coeff + ren  →  baseline: ren only; target: w + ren.
    refresh_tp = w_coeff_da * w_tp + ren_tp  # (process, tech, tp)

    # window_sum[p,k,t] = Σ_tp W[k,t,tp] * refresh[p,k,tp]
    # window_da has dims (tech, period, tp); refresh_tp has (process, tech, tp).
    # Multiply → (process, tech, period, tp), then sum over tp.
    window_sum = (window_da * refresh_tp).sum("tp")  # (process, tech, period)

    rhs = live0_da + window_sum
    # Add constraint over the entire tracked-feasible subspace in one call.
    m.add_constraints(ctx.u <= rhs, mask=life_mask, name="life")


def _vintage_gate(ctx: BuildContext) -> None:
    r"""Vintage timing: switch/rebuild only at end-of-life boundaries.

    When ``problem.vintage_timing`` is set, a facility may replace (``w``) or renew
    (``ren``) a technology ONLY in years where its asset reaches end of life —
    ``(year - introduced_year) % lifespan == 0`` (lifespan of its baseline
    technology) — and must continue in between. Off by default; opt-in for fleets
    that turn over on a fixed vintage schedule. Facilities with no install date are
    left free.

    Algorithm:
        boundary(p, t) ⇔ (t − introduced_year_p) mod L_p == 0
        ¬boundary ⇒ w[p,k,t] = 0 and ren[p,k,t] = 0  for every technology k

    Vectorisation: build a boolean mask (process, tech, period) that is True where
    ``t`` is NOT a boundary, then add two single vectorised constraints.
    """
    if not ctx.problem.vintage_timing:
        return
    m, prob = ctx.model, ctx.problem

    # non_boundary_mask[p, k, t] = True means "not at a boundary ⇒ force w/ren=0"
    non_boundary = np.zeros((len(ctx.procs), len(ctx.techs), len(ctx.years)), dtype=bool)
    for p in prob.processes:
        if p.introduced_year is None:
            continue
        tech = prob.technologies.get(p.baseline_technology)
        life = max(int(tech.lifespan), 1) if tech is not None else 1
        pi = ctx.procs.index(p.process_id)
        for j, k in enumerate(ctx.techs):
            if k not in ctx.feasible[p.process_id]:
                continue
            for li, t in enumerate(ctx.years):
                if (t - p.introduced_year) % life != 0:
                    non_boundary[pi, j, li] = True

    if not non_boundary.any():
        return

    nb_da = xr.DataArray(
        non_boundary,
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )
    m.add_constraints(ctx.w == 0, mask=nb_da, name="vint_w")
    if ctx.ren is not None:
        m.add_constraints(ctx.ren == 0, mask=nb_da, name="vint_ren")


def _produced(ctx: BuildContext, p: str, r: str, t: int) -> Any:
    """Output of commodity ``r`` at process ``p`` in ``t`` (expression or None).

    A commodity in a technology's output slate group is produced via the slate
    flow variable ``fout`` (so the optimiser picks its share within bounds);
    other outputs keep the fixed form ``yield · throughput``.
    """
    terms = []
    for k in ctx.feasible[p]:
        tech = ctx.problem.technologies[k]
        if r in tech.grouped_outputs():
            terms.append(ctx.fout.sel(process=p, tech=k, commodity=r, period=t))
        else:
            coef = tech.output_yield_at(r, t)
            if coef != 0.0:
                terms.append(coef * ctx.x.sel(process=p, tech=k, period=t))
    return _lin_sum(terms)


def _gross_consumed(ctx: BuildContext, p: str, r: str, t: int) -> Any:
    """Gross input of commodity ``r`` at ``p`` (before efficiency savings).

    A commodity that is part of a technology's blend group is consumed via the
    mix flow variable ``fin`` (so the optimiser picks the share); other inputs
    keep the fixed form ``intensity · throughput``.
    """
    terms = []
    for k in ctx.feasible[p]:
        tech = ctx.problem.technologies[k]
        if r in tech.grouped_inputs():
            terms.append(ctx.fin.sel(process=p, tech=k, commodity=r, period=t))
        else:
            coef = tech.input_intensity_at(r, t)
            if coef != 0.0:
                terms.append(coef * ctx.x.sel(process=p, tech=k, period=t))
    return _lin_sum(terms)


def _blend(ctx: BuildContext) -> None:
    """Blend-group mix: members sum to the group requirement; shares bounded.

    For each technology blend group ``g`` (members ``C_g``, requirement
    ``R_g = Σ intensity_c``) and throughput ``x``::

        Σ_{c∈C_g} fin_c = R_g · x ;   s_min_c·R_g·x ≤ fin_c ≤ s_max_c·R_g·x

    Grouped commodities not used by a technology are pinned to zero.
    """
    if not ctx.grouped_comms:
        return
    m, prob = ctx.model, ctx.problem
    gc = ctx.grouped_comms
    # The mix flow is non-zero only for (process, feasible tech, member commodity);
    # everything else is killed by ONE vectorised bound — not a per-cell Python
    # loop — so blend models scale to many facilities/technologies.
    member = np.zeros((len(ctx.procs), len(ctx.techs), len(gc)))
    for i, p in enumerate(ctx.procs):
        fset = set(ctx.feasible[p])
        for j, k in enumerate(ctx.techs):
            if k not in fset:
                continue
            member_set = prob.technologies[k].grouped_inputs()
            for li, c in enumerate(gc):
                if c in member_set:
                    member[i, j, li] = 1.0
    big = _big_m(prob)
    member_da = xr.DataArray(
        member,
        coords={"process": ctx.procs, "tech": ctx.techs, "commodity": gc},
        dims=["process", "tech", "commodity"],
    )
    m.add_constraints(ctx.fin <= big * member_da, name="finmask")

    # Group sum + share bounds — only over feasible (process, technology) pairs
    # that actually carry a blend group.
    for p in ctx.procs:
        for k in ctx.feasible[p]:
            tech = prob.technologies[k]
            if not tech.share_groups:
                continue
            for t in ctx.years:
                xpkt = ctx.x.sel(process=p, tech=k, period=t)
                for g, members in tech.share_groups.items():
                    req = tech.group_requirement_at(g, t)
                    m.add_constraints(
                        _lin_sum(
                            [ctx.fin.sel(process=p, tech=k, commodity=c, period=t) for c in members]
                        )
                        == req * xpkt,
                        name=f"mix[{p},{k},{g},{t}]",
                    )
                    for c in members:
                        lo, hi = tech.input_share_at(g, c, t)
                        f = ctx.fin.sel(process=p, tech=k, commodity=c, period=t)
                        if lo > 0.0:
                            m.add_constraints(f >= lo * req * xpkt, name=f"mixlo[{p},{k},{c},{t}]")
                        if hi < 1.0:
                            m.add_constraints(f <= hi * req * xpkt, name=f"mixhi[{p},{k},{c},{t}]")


def _output_blend(ctx: BuildContext) -> None:
    """Output slate mix: members sum to the slate requirement; shares bounded.

    The production-side mirror of :func:`_blend`. For each technology output
    slate group ``G`` (members, requirement ``R_G = Σ yield_c``) and throughput
    ``x``::

        Σ_{c∈G} fout_c = R_G · x ;   s_min_c·R_G·x ≤ fout_c ≤ s_max_c·R_G·x

    so a multi-product unit (e.g. a naphtha cracker) can shift its co-product
    slate toward the most valuable mix within its physical flexibility. Slate
    commodities not produced by a technology are pinned to zero.
    """
    if not ctx.grouped_out_comms:
        return
    m, prob = ctx.model, ctx.problem
    go = ctx.grouped_out_comms
    # The slate flow is non-zero only for (process, feasible tech, member
    # commodity); everything else is killed by ONE vectorised bound.
    member = np.zeros((len(ctx.procs), len(ctx.techs), len(go)))
    for i, p in enumerate(ctx.procs):
        fset = set(ctx.feasible[p])
        for j, k in enumerate(ctx.techs):
            if k not in fset:
                continue
            member_set = prob.technologies[k].grouped_outputs()
            for li, c in enumerate(go):
                if c in member_set:
                    member[i, j, li] = 1.0
    big = _big_m(prob)
    member_da = xr.DataArray(
        member,
        coords={"process": ctx.procs, "tech": ctx.techs, "commodity": go},
        dims=["process", "tech", "commodity"],
    )
    m.add_constraints(ctx.fout <= big * member_da, name="foutmask")

    for p in ctx.procs:
        for k in ctx.feasible[p]:
            tech = prob.technologies[k]
            if not tech.output_share_groups:
                continue
            for t in ctx.years:
                xpkt = ctx.x.sel(process=p, tech=k, period=t)
                for g, members in tech.output_share_groups.items():
                    req = tech.output_group_requirement_at(g, t)
                    m.add_constraints(
                        _lin_sum(
                            [
                                ctx.fout.sel(process=p, tech=k, commodity=c, period=t)
                                for c in members
                            ]
                        )
                        == req * xpkt,
                        name=f"slate[{p},{k},{g},{t}]",
                    )
                    for c in members:
                        lo, hi = tech.output_share_at(g, c, t)
                        f = ctx.fout.sel(process=p, tech=k, commodity=c, period=t)
                        if lo > 0.0:
                            m.add_constraints(
                                f >= lo * req * xpkt, name=f"slatelo[{p},{k},{c},{t}]"
                            )
                        if hi < 1.0:
                            m.add_constraints(
                                f <= hi * req * xpkt, name=f"slatehi[{p},{k},{c},{t}]"
                            )


def _efficiency_savings(ctx: BuildContext, p: str, r: str, t: int) -> Any:
    """MACC energy-efficiency savings on commodity ``r`` at ``p`` (LP-safe)."""
    terms = [
        s.reduction_at(t) * ctx.ref_consumption.get((p, r), 0.0) * ctx.z.sel(slot=s.key, period=t)
        for s in ctx.slots
        if s.measure_type == MeasureType.ENERGY_EFFICIENCY and s.process == p and s.target == r
    ]
    return _lin_sum(terms)


def _edges_in(ctx: BuildContext, p: str, r: str) -> list[int]:
    return [i for i, e in enumerate(ctx.problem.edges) if e.to_process == p and e.commodity_id == r]


def _edges_out(ctx: BuildContext, p: str, r: str) -> list[int]:
    return [
        i for i, e in enumerate(ctx.problem.edges) if e.from_process == p and e.commodity_id == r
    ]


def _flow_balance(ctx: BuildContext) -> None:
    """Per-commodity node balance + edge caps + demand delivery (slack-softened).

    Vectorisation strategy
    ----------------------
    The node balance is::

        buy[p,r,t] + produced[p,r,t] + inflow[p,r,t]
            == sell[p,r,t] + deliver[p,r,t] + consumed[p,r,t] + outflow[p,r,t]

    For commodities whose I/O is NOT in a blend/slate group, produced and
    consumed are bilinear in yield/intensity × x.  We precompute coefficient
    DataArrays over (process, tech, commodity, period) and contract over the
    ``tech`` dimension to get a (process, commodity, period) linear expression:

        produced_expr[p,r,t]  = Σ_k yield[p,k,r,t]     * x[p,k,t]
        consumed_expr[p,r,t]  = Σ_k intensity[p,k,r,t] * x[p,k,t]

    For grouped commodities (blend/slate) the ``fin``/``fout`` variables carry
    the flow; they are already shaped (process, tech, commodity, period) and are
    summed over ``tech``.

    All three "zero-flow" families (nodeliver, nosell, nobuy) are also vectorised
    into single ``add_constraints`` calls with boolean masks.

    MACC efficiency savings are per-slot (typically zero or very few slots) and
    kept as a small scalar loop — their contribution to the balance is expressed
    as a coefficient × z variable and summed into the consumed side.
    """
    m, prob = ctx.model, ctx.problem
    products = {r for r, c in prob.commodities.items() if c.kind == CommodityKind.PRODUCT}
    produced_anywhere = {
        r for k in prob.technologies.values() for r, y in k.output_yield.items() if y != 0.0
    }
    raw_kinds = {CommodityKind.ENERGY, CommodityKind.MATERIAL, CommodityKind.INDIRECT}
    market_commodities = {mk.target for mk in ctx.cmarkets}

    def _purchasable(r: str) -> bool:
        c = prob.commodities[r]
        if r in market_commodities:
            return True
        if c.purchasable is not None:
            return c.purchasable
        return c.kind in raw_kinds and r not in produced_anywhere

    # ── Precompute yield/intensity coefficient arrays ─────────────────────────
    # yield_coeff[p, k, r, t]: output of commodity r per unit x at (p,k,t)
    # Only for commodities NOT in a slate group; slate members use fout.
    yield_arr = np.zeros((len(ctx.procs), len(ctx.techs), len(ctx.comms), len(ctx.years)))
    for i, p in enumerate(ctx.procs):
        for j, k in enumerate(ctx.techs):
            if k not in ctx.feasible[p]:
                continue
            tech = prob.technologies[k]
            grouped_outs = tech.grouped_outputs()
            for li, r in enumerate(ctx.comms):
                if r in grouped_outs:
                    continue  # fout handles this
                coef_base = tech.output_yield.get(r, 0.0)
                traj = tech.output_yield_by_year.get(r)
                for mi, t in enumerate(ctx.years):
                    coef = traj[t] if (traj is not None and t in traj) else coef_base
                    yield_arr[i, j, li, mi] = coef

    # intensity_coeff[p, k, r, t]: input of r per unit x at (p,k,t)
    # Only for commodities NOT in a blend group; blend members use fin.
    intensity_arr = np.zeros((len(ctx.procs), len(ctx.techs), len(ctx.comms), len(ctx.years)))
    for i, p in enumerate(ctx.procs):
        for j, k in enumerate(ctx.techs):
            if k not in ctx.feasible[p]:
                continue
            tech = prob.technologies[k]
            grouped_ins = tech.grouped_inputs()
            for li, r in enumerate(ctx.comms):
                if r in grouped_ins:
                    continue  # fin handles this
                coef_base = tech.input_intensity.get(r, 0.0)
                traj = tech.input_intensity_by_year.get(r)
                for mi, t in enumerate(ctx.years):
                    coef = traj[t] if (traj is not None and t in traj) else coef_base
                    intensity_arr[i, j, li, mi] = coef

    yield_da = xr.DataArray(
        yield_arr,
        coords={
            "process": ctx.procs,
            "tech": ctx.techs,
            "commodity": ctx.comms,
            "period": ctx.years,
        },
        dims=["process", "tech", "commodity", "period"],
    )
    intensity_da = xr.DataArray(
        intensity_arr,
        coords={
            "process": ctx.procs,
            "tech": ctx.techs,
            "commodity": ctx.comms,
            "period": ctx.years,
        },
        dims=["process", "tech", "commodity", "period"],
    )

    # produced_expr[p,r,t] = Σ_k yield_da[p,k,r,t] * x[p,k,t]
    # x is (process,tech,period); yield_da is (process,tech,commodity,period)
    # multiplication broadcasts x over the commodity dim.
    produced_expr = (yield_da * ctx.x).sum("tech")  # (process, commodity, period)

    # consumed_expr[p,r,t] = Σ_k intensity_da[p,k,r,t] * x[p,k,t]
    consumed_expr = (intensity_da * ctx.x).sum("tech")  # (process, commodity, period)

    # fin / fout contributions (if blend/slate groups exist): sum over tech dim.
    # fin is (process, tech, grouped_commodity, period); sum over tech gives
    # (process, grouped_commodity, period).
    fin_sum = ctx.fin.sum("tech") if ctx.fin is not None and ctx.grouped_comms else None
    fout_sum = ctx.fout.sum("tech") if ctx.fout is not None and ctx.grouped_out_comms else None

    # ── Determine which (process, commodity) pairs need edge or savings terms ─
    # For the vectorised path: most cells have no edges and no savings.
    # Cells with edges or savings are handled by the scalar fallback.
    has_edges = bool(prob.edges)
    has_savings = bool(ctx.z is not None and ctx.slots)

    # ── Zero-flow masks ───────────────────────────────────────────────────────
    # nodeliver: r not a product → deliver == 0
    # nosell:    r is a product OR not sellable → sell == 0
    # nobuy:     not purchasable OR not available(t) → buy == 0
    nodeliver_mask = np.zeros((len(ctx.procs), len(ctx.comms), len(ctx.years)), dtype=bool)
    nosell_mask = np.zeros((len(ctx.procs), len(ctx.comms), len(ctx.years)), dtype=bool)
    nobuy_mask = np.zeros((len(ctx.procs), len(ctx.comms), len(ctx.years)), dtype=bool)
    for li, r in enumerate(ctx.comms):
        comm = prob.commodities[r]
        is_product = r in products
        is_sellable = comm.sellable
        purch = _purchasable(r)
        for mi, t in enumerate(ctx.years):
            avail_t = comm.available(t)
            for i in range(len(ctx.procs)):
                if not is_product:
                    nodeliver_mask[i, li, mi] = True
                if is_product or not is_sellable:
                    nosell_mask[i, li, mi] = True
                if not purch or not avail_t:
                    nobuy_mask[i, li, mi] = True

    nodeliver_da = xr.DataArray(
        nodeliver_mask,
        coords={"process": ctx.procs, "commodity": ctx.comms, "period": ctx.years},
        dims=["process", "commodity", "period"],
    )
    nosell_da = xr.DataArray(
        nosell_mask,
        coords={"process": ctx.procs, "commodity": ctx.comms, "period": ctx.years},
        dims=["process", "commodity", "period"],
    )
    nobuy_da = xr.DataArray(
        nobuy_mask,
        coords={"process": ctx.procs, "commodity": ctx.comms, "period": ctx.years},
        dims=["process", "commodity", "period"],
    )

    m.add_constraints(ctx.deliver == 0, mask=nodeliver_da, name="nodeliver")
    m.add_constraints(ctx.sell == 0, mask=nosell_da, name="nosell")
    m.add_constraints(ctx.buy == 0, mask=nobuy_da, name="nobuy")

    # ── Main balance constraint ───────────────────────────────────────────────
    # IMPORTANT: linopy does NOT re-align coordinate arrays by label when
    # forming a constraint (lhs == rhs) — it matches by position.  When two
    # linopy expressions have DIFFERENT coordinate orders (which xarray can
    # produce silently when merging a subset-indexed expression into a
    # full-indexed one), the constraint rows get mis-matched.
    #
    # Safe solution: partition the commodity dimension into disjoint subsets so
    # that EVERY call to add_constraints receives expressions with the SAME
    # commodity index on both sides.  Within each partition, all operands are
    # selected with the same index (pd.Index) before any arithmetic, so the
    # coordinate order is guaranteed to match.
    #
    # Partitions (by commodity membership in blend / slate groups):
    #   (A) in grouped_out (slate): fout.sum('tech') appears on LHS
    #   (B) in grouped_in but NOT grouped_out: fin.sum('tech') on RHS
    #   (C) in neither group: pure yield/intensity × x terms
    # A commodity may belong to both (A) and (B) (e.g. a commodity produced by
    # a slate and consumed by a blend); this is handled within partition (A) by
    # also selecting fin_sum at those positions.
    if not has_edges and not has_savings:
        go_set = set(ctx.grouped_out_comms)  # slate (output) group members
        gi_set = set(ctx.grouped_comms)  # blend (input) group members

        # Disjoint partition maintaining the original ctx.comms ordering.
        comms_A = [r for r in ctx.comms if r in go_set]  # slate
        comms_B = [r for r in ctx.comms if r in gi_set and r not in go_set]  # blend only
        comms_C = [r for r in ctx.comms if r not in go_set and r not in gi_set]  # plain

        def _csel(expr: Any, comms: list[str]) -> Any:
            """Select commodity slice; identity if comms equals full comm list."""
            if len(comms) == len(ctx.comms):
                return expr
            return expr.sel(commodity=pd.Index(comms, name="commodity"))

        # (C) Plain: no fin / fout variables involved.
        if comms_C:
            lhs_C = _csel(ctx.buy, comms_C) + _csel(produced_expr, comms_C)
            rhs_C = (
                _csel(ctx.sell, comms_C)
                + _csel(ctx.deliver, comms_C)
                + _csel(consumed_expr, comms_C)
            )
            m.add_constraints(lhs_C == rhs_C, name="bal")

        # (B) Blend-only: fin.sum('tech') added to RHS.
        if comms_B:
            lhs_B = _csel(ctx.buy, comms_B) + _csel(produced_expr, comms_B)
            rhs_B = (
                _csel(ctx.sell, comms_B)
                + _csel(ctx.deliver, comms_B)
                + _csel(consumed_expr, comms_B)
            )
            if fin_sum is not None:
                # fin_sum.sel selects comms_B from grouped_comms — guaranteed subset.
                rhs_B = rhs_B + fin_sum.sel(commodity=pd.Index(comms_B, name="commodity"))
            m.add_constraints(lhs_B == rhs_B, name="bal_blend")

        # (A) Slate: fout.sum('tech') added to LHS.  A slate commodity may also
        # be in a blend group (extremely rare: produced as a co-product AND
        # consumed as a blend input).  In that case fall back to the scalar
        # loop for those specific (p, r, t) cells to avoid the partial-index
        # alignment problem described above.
        if comms_A and fout_sum is not None:
            comms_A_in_gi = [r for r in comms_A if r in gi_set]
            if not comms_A_in_gi:
                # Fast path: no overlap with blend inputs.
                lhs_A = (
                    _csel(ctx.buy, comms_A)
                    + _csel(produced_expr, comms_A)
                    + fout_sum.sel(commodity=pd.Index(comms_A, name="commodity"))
                )
                rhs_A = (
                    _csel(ctx.sell, comms_A)
                    + _csel(ctx.deliver, comms_A)
                    + _csel(consumed_expr, comms_A)
                )
                m.add_constraints(lhs_A == rhs_A, name="bal_slate")
            else:
                # Overlap case: scalar loop over affected cells only.
                for p in ctx.procs:
                    for r in comms_A:
                        for t in ctx.years:
                            produced = _produced(ctx, p, r, t)
                            gross = _gross_consumed(ctx, p, r, t)
                            lhs_terms = [ctx.buy.sel(process=p, commodity=r, period=t)]
                            if produced is not None:
                                lhs_terms.append(produced)
                            rhs_terms = [
                                ctx.sell.sel(process=p, commodity=r, period=t),
                                ctx.deliver.sel(process=p, commodity=r, period=t),
                            ]
                            if gross is not None:
                                rhs_terms.append(gross)
                            m.add_constraints(
                                _lin_sum(lhs_terms) == _lin_sum(rhs_terms),
                                name=f"bal[{p},{r},{t}]",
                            )

    else:
        # Fallback: scalar loop for (process, commodity, period) cells that
        # have edges or MACC savings (or both).  In practice, models with edges
        # are small (shipping etc.), so this loop is fast.
        year_set = set(ctx.years)
        for p in ctx.procs:
            for r in ctx.comms:
                comm = prob.commodities[r]
                for t in ctx.years:
                    produced = _produced(ctx, p, r, t)
                    gross = _gross_consumed(ctx, p, r, t)
                    savings = _efficiency_savings(ctx, p, r, t)
                    consumed = gross
                    if savings is not None:
                        consumed = (gross - savings) if gross is not None else (-1.0) * savings
                    in_edges = _edges_in(ctx, p, r)
                    out_edges = _edges_out(ctx, p, r)
                    # A lagged edge delivers what left the producer `lag` years ago:
                    # the consumer's inflow at t draws flow[edge, t-lag]. Flow whose
                    # arrival year predates the horizon is simply not received.
                    in_terms = []
                    for i in in_edges:
                        lag = prob.edges[i].lag_years
                        src_t = t - lag
                        if lag == 0:
                            in_terms.append(ctx.flow.sel(edge=i, period=t))
                        elif src_t in year_set:
                            in_terms.append(ctx.flow.sel(edge=i, period=src_t))
                    inflow = _lin_sum(in_terms)
                    outflow = _lin_sum([ctx.flow.sel(edge=i, period=t) for i in out_edges])

                    lhs_terms = [ctx.buy.sel(process=p, commodity=r, period=t)]
                    if produced is not None:
                        lhs_terms.append(produced)
                    if inflow is not None:
                        lhs_terms.append(inflow)
                    rhs_terms = [
                        ctx.sell.sel(process=p, commodity=r, period=t),
                        ctx.deliver.sel(process=p, commodity=r, period=t),
                    ]
                    if consumed is not None:
                        rhs_terms.append(consumed)
                    if outflow is not None:
                        rhs_terms.append(outflow)
                    m.add_constraints(
                        _lin_sum(lhs_terms) == _lin_sum(rhs_terms), name=f"bal[{p},{r},{t}]"
                    )

    # ── Edge capacity + floor + availability constraints ──────────────────────
    for i, e in enumerate(prob.edges):
        for t in ctx.years:
            if not e.available(t):
                # Outside the link's window it carries no flow (overrides min/max).
                m.add_constraints(ctx.flow.sel(edge=i, period=t) == 0, name=f"eoff[{i},{t}]")
                continue
            mf = e.max_flow_at(t)
            if mf is not None:
                m.add_constraints(ctx.flow.sel(edge=i, period=t) <= mf, name=f"emax[{i},{t}]")
            nf = e.min_flow_at(t)
            if nf is not None:
                m.add_constraints(ctx.flow.sel(edge=i, period=t) >= nf, name=f"emin[{i},{t}]")

    # ── Demand constraints ────────────────────────────────────────────────────
    for c, q, y in ctx.demand_keys:
        procs = [p.process_id for p in prob.processes if p.in_scope(c)]
        delivered = _lin_sum([ctx.deliver.sel(process=p, commodity=q, period=y) for p in procs])
        key = f"{c}|{q}|{y}"
        rhs = prob.demand[(c, q, y)]
        if prob.objective_of(c) == ObjectiveMode.PROFIT:
            if delivered is not None:
                m.add_constraints(delivered <= rhs, name=f"sellcap[{key}]")
        else:
            slack = ctx.slk_dem.sel(dkey=key)
            if delivered is None:
                m.add_constraints(slack >= rhs, name=f"demand[{key}]")
            else:
                m.add_constraints(delivered + slack >= rhs, name=f"demand[{key}]")


def _purchase_caps(ctx: BuildContext) -> None:
    r"""Per-year ceiling on a commodity's total external purchase (volume cap).

    When :attr:`Commodity.max_purchase_by_year` is set for a stream, the total
    bought across every process (or, for a stored stream, the store's external
    purchase) in that year is bounded::

        Σ_p buy[p, r, t] <= max_purchase_r(t)

    Unset commodities/years are unconstrained, so this is inert unless a model
    (or a value-chain ``volume`` link) supplies a cap.
    """
    m, prob = ctx.model, ctx.problem
    stored = {s.commodity_id: s for s in prob.storages}
    stores_of: dict[str, list[Any]] = {}
    for st in prob.storages:
        stores_of.setdefault(st.commodity_id, []).append(st)
    for r in ctx.comms:
        comm = prob.commodities[r]
        if not comm.max_purchase_by_year:
            continue
        for t in ctx.years:
            cap = comm.max_purchase(t)
            if cap is None:
                continue
            if r in stored:
                total = _lin_sum(
                    [ctx.extbuy.sel(store=st.storage_id, period=t) for st in stores_of[r]]
                )
            else:
                total = _lin_sum([ctx.buy.sel(process=p, commodity=r, period=t) for p in ctx.procs])
            if total is not None:
                m.add_constraints(total <= cap, name=f"buycap[{r},{t}]")


def _abatement(ctx: BuildContext, p: str, i: str, t: int) -> Any:
    """MACC emission/environmental abatement of impact ``i`` at ``p`` (LP-safe)."""
    terms = [
        s.reduction_at(t) * ctx.ref_impact.get((p, i), 0.0) * ctx.z.sel(slot=s.key, period=t)
        for s in ctx.slots
        if s.measure_type in (MeasureType.EMISSION_REDUCTION, MeasureType.ENVIRONMENTAL)
        and s.process == p
        and s.target == i
    ]
    return _lin_sum(terms)


def _impacts(ctx: BuildContext) -> None:
    """Define ``emit`` per (process, impact, period) and apply caps (slack-softened).

    Vectorisation strategy
    ----------------------
    The emission definition is::

        emit[p,i,t] = Σ_{r,k} factor[r,i,t] · intensity[p,k,r,t] · x[p,k,t]
                    + Σ_k   (direct_tech[k,i,t] + direct_proc[p,i,t]) · x[p,k,t]
                    − abatement[p,i,t]

    We precompute a coefficient array
    ``impact_coeff[p,k,i,t] = Σ_r factor[r,i,t]·intensity[p,k,r,t]
                               + direct_tech[k,i,t] + direct_proc[p,i,t]``
    then express emit_expr = (impact_coeff * x).sum("tech").

    MACC abatement terms (few slots, typically absent) are kept as a small
    scalar loop and subtracted from the RHS after the vectorised part.

    The ``emitpos`` (emit >= 0) constraint is added as a single vectorised call.
    """
    m, prob = ctx.model, ctx.problem
    if not ctx.impacts:
        return  # no impacts declared — constraint family is vacuous
    proc_by = {p.process_id: p for p in prob.processes}

    # LCIA characterisation: an impact CATEGORY (e.g. GWP) is a linear combination
    # of base elementary flows (CO2, CH4, …) via factors. Base flows come from the
    # io/commodity factors below; categories are *linked* to them afterwards, so
    # pricing / caps / ETS / the inventory all see categories like any other impact.
    category_set = {cat for (_flow, cat) in prob.characterisation}
    base_impacts = [i for i in ctx.impacts if i not in category_set]
    categories = [i for i in ctx.impacts if i in category_set]

    # ── Precompute impact coefficient array over BASE impacts (process,tech,i,t) ─
    # impact_coeff[p,k,i,t] = Σ_r factor[r,i,t]*intensity[p,k,r,t]
    #                        + direct_tech[k,i,t] + direct_proc[p,i,t]
    if base_impacts:
        impact_coeff = np.zeros((len(ctx.procs), len(ctx.techs), len(base_impacts), len(ctx.years)))
        for i_p, p in enumerate(ctx.procs):
            proc = proc_by[p]
            for j_k, k in enumerate(ctx.techs):
                if k not in ctx.feasible[p]:
                    continue
                tech = prob.technologies[k]
                for l_i, imp in enumerate(base_impacts):
                    for m_t, t in enumerate(ctx.years):
                        # Commodity-driven term: Σ_r factor[r,i,t] * intensity[p,k,r,t]
                        val = 0.0
                        for r in ctx.comms:
                            factor = prob.commodity_impact(r, imp, t)
                            if factor == 0.0:
                                continue
                            intensity = tech.input_intensity_at(r, t)
                            if intensity == 0.0:
                                continue
                            val += factor * intensity
                        # Direct technology emission
                        val += tech.direct_impact_at(imp, t)
                        # Direct process (facility-level) emission
                        val += proc.direct_impact_at(imp, t)
                        impact_coeff[i_p, j_k, l_i, m_t] = val

        impact_coeff_da = xr.DataArray(
            impact_coeff,
            coords={
                "process": ctx.procs,
                "tech": ctx.techs,
                "impact": base_impacts,
                "period": ctx.years,
            },
            dims=["process", "tech", "impact", "period"],
        )
        # emit_expr[p,i,t] = Σ_k impact_coeff[p,k,i,t] * x[p,k,t]
        # x is (process,tech,period); impact_coeff broadcasts x over the impact dim.
        emit_expr = (impact_coeff_da * ctx.x).sum("tech")  # (process, base_impact, period)

        # ── MACC abatement (small scalar loop; typically absent) ──────────────
        has_abatement = ctx.z is not None and any(
            s.measure_type in (MeasureType.EMISSION_REDUCTION, MeasureType.ENVIRONMENTAL)
            for s in ctx.slots
        )

        if has_abatement:
            for p in ctx.procs:
                for imp in base_impacts:
                    for t in ctx.years:
                        abate = _abatement(ctx, p, imp, t)
                        if abate is not None:
                            rhs = emit_expr.sel(process=p, impact=imp, period=t) - abate
                        else:
                            rhs = emit_expr.sel(process=p, impact=imp, period=t)
                        m.add_constraints(
                            ctx.emit.sel(process=p, impact=imp, period=t) == rhs,
                            name=f"emit[{p},{imp},{t}]",
                        )
        else:
            # Fully vectorised: emit == emit_expr over all (process, base impact, period)
            base_idx = pd.Index(base_impacts, name="impact")
            m.add_constraints(ctx.emit.sel(impact=base_idx) == emit_expr, name="emit")

        # Base emissions are physical → non-negative. (Categories are NOT bounded
        # here: a characterisation factor may be negative, e.g. an avoided burden.)
        m.add_constraints(
            ctx.emit.sel(impact=pd.Index(base_impacts, name="impact")) >= 0, name="emitpos"
        )

    # ── Characterisation linkage: emit[category] = Σ_flow CF · emit[flow] ──────
    for cat in categories:
        terms = [
            fac * ctx.emit.sel(impact=flow)
            for (flow, c), fac in prob.characterisation.items()
            if c == cat and flow in ctx.impacts
        ]
        if not terms:
            continue
        rhs = terms[0]
        for term in terms[1:]:
            rhs = rhs + term
        m.add_constraints(ctx.emit.sel(impact=cat) == rhs, name=f"char[{cat}]")

    # ── Impact caps ───────────────────────────────────────────────────────────
    # Each cap triple (c, i, y) bounds Σ_{p∈scope(c)} emit[p,i,y].
    # Group by (scope c, impact i) to share the process-sum computation.
    products = {r for r, comm in prob.commodities.items() if comm.kind == CommodityKind.PRODUCT}
    # Cache process-sum expressions per (scope, impact) to avoid recomputing.
    scope_impact_sum: dict[tuple[str, str], Any] = {}
    for c, i, y in ctx.cap_keys:
        cache_key = (c, i)
        if cache_key not in scope_impact_sum:
            procs_in_scope = [p.process_id for p in prob.processes if p.in_scope(c)]
            if procs_in_scope:
                scope_idx = pd.Index(procs_in_scope, name="process")
                # Vectorised sum over the scope's processes: shape (impact, period)
                scope_impact_sum[cache_key] = ctx.emit.sel(process=scope_idx).sum("process")
            else:
                scope_impact_sum[cache_key] = None

        total_by_period = scope_impact_sum[cache_key]
        total = total_by_period.sel(impact=i, period=y) if total_by_period is not None else None
        key = f"{c}|{i}|{y}"
        slack = ctx.slk_cap.sel(ckey=key)
        limit = prob.impact_caps[(c, i, y)]
        if prob.impact_cap_intensity.get((c, i), False):
            procs_in_scope = [p.process_id for p in prob.processes if p.in_scope(c)]
            prod_terms = [_produced(ctx, p, r, y) for p in procs_in_scope for r in products]
            production = _lin_sum([t for t in prod_terms if t is not None])
            cap_rhs: Any = limit * production if production is not None else 0.0
        else:
            cap_rhs = limit
        soft = prob.impact_cap_soft.get((c, i), True)
        if not soft:
            m.add_constraints(slack == 0, name=f"caphard[{key}]")
        if total is not None:
            m.add_constraints(total - slack <= cap_rhs, name=f"cap[{key}]")


def _macc(ctx: BuildContext) -> None:
    """MACC adoption: cumulative blocks + persistence across periods."""
    m, prob = ctx.model, ctx.problem
    prev = _prev(ctx.years)
    by_measure: dict[str, list[str]] = {}
    for s in ctx.slots:
        by_measure.setdefault(s.measure_id, []).append(s.key)
    for keys in by_measure.values():
        for a, b in itertools.pairwise(keys):  # block a adopted before b
            for t in ctx.years:
                m.add_constraints(
                    ctx.z.sel(slot=a, period=t) >= ctx.z.sel(slot=b, period=t),
                    name=f"mono[{a},{b},{t}]",
                )
    for s in ctx.slots:
        for t in ctx.years:
            pt = prev[t]
            if pt is not None:
                m.add_constraints(
                    ctx.z.sel(slot=s.key, period=t) >= ctx.z.sel(slot=s.key, period=pt),
                    name=f"persist[{s.key},{t}]",
                )
    _ = prob  # referenced for symmetry; measures already flattened into slots


def _scope_processes(ctx: BuildContext, scope: str) -> list[str]:
    """Process ids matched by ``scope`` (facility / company / group / ``"all"``)."""
    return [p.process_id for p in ctx.problem.processes if p.in_scope(scope)]


def _transition_index(prob: Problem) -> dict[tuple[str, str], Transition]:
    """Map ``(process_id, target tech)`` → the Transition that enables the switch."""
    out: dict[tuple[str, str], Transition] = {}
    for tr in prob.transitions:
        for proc in prob.processes:
            if tr.from_technology == proc.baseline_technology:
                out[(proc.process_id, tr.to_technology)] = tr
    return out


def _replacement_capex(
    prob: Problem,
    trans_idx: dict[tuple[str, str], Transition],
    process_id: str,
    tech: str,
    capacity: float,
    year: int,
) -> float:
    """Nominal capital cost of switching ``process`` to ``tech`` in ``year``.

    Uses the transition row's (possibly year-varying) ``capex_per_capacity`` when
    one defines the switch, otherwise the target technology's own year-varying
    ``capex``. Nominal (capacity × per-capacity cost); the convention/discount is
    applied by the caller via :meth:`Problem.capex_charge`.
    """
    tr = trans_idx.get((process_id, tech))
    per_cap = tr.capex_at(year) if tr is not None else prob.technologies[tech].capex(year)
    return per_cap * capacity


def _storage(ctx: BuildContext) -> None:
    """Inter-year inventory dynamics + market linkage for each store.

    Algorithm (per store ``s`` of commodity ``r``, year ``t``):
        level_t = (1−loss)·level_{t-1} + η_c·charge_t − discharge_t/η_d
        extbuy_t = Σ_{p∈scope} buy_{p,r,t} + charge_t − discharge_t   (≥ 0)
        0 ≤ level_t, charge_t, discharge_t ≤ cap_built ≤ max_capacity

    ``charge`` draws commodity from the market (raises external purchase),
    ``discharge`` returns it (lowers external purchase). Only the external
    purchase ``extbuy`` is priced — process ``buy`` of a stored commodity is the
    internal draw (repriced in the objective).
    """
    m, prob = ctx.model, ctx.problem
    if not prob.storages:
        return
    prev = _prev(ctx.years)
    for s in prob.storages:
        sid = s.storage_id
        m.add_constraints(ctx.cap_built.sel(store=sid) <= s.max_capacity, name=f"scap[{sid}]")
        scope = _scope_processes(ctx, s.company)
        for t in ctx.years:
            charge_t = ctx.charge.sel(store=sid, period=t)
            dis_t = ctx.discharge.sel(store=sid, period=t)
            lvl_t = ctx.level.sel(store=sid, period=t)
            pt = prev[t]
            decay = 1.0 - s.standing_loss_at(t)
            # Discharge efficiency divides the draw, so a zero (e.g. an authored
            # year-trajectory cell) would blow up the build; clamp to a tiny floor.
            dis_eff = max(s.discharge_efficiency_at(t), 1.0e-6)
            gain = s.charge_efficiency_at(t) * charge_t - (1.0 / dis_eff) * dis_t
            prior = decay * ctx.level.sel(store=sid, period=pt) if pt is not None else None
            rhs = (gain + prior) if prior is not None else (gain + decay * s.initial_level)
            m.add_constraints(lvl_t == rhs, name=f"slevel[{sid},{t}]")
            m.add_constraints(lvl_t <= ctx.cap_built.sel(store=sid), name=f"slcap[{sid},{t}]")
            m.add_constraints(charge_t <= ctx.cap_built.sel(store=sid), name=f"schg[{sid},{t}]")
            m.add_constraints(dis_t <= ctx.cap_built.sel(store=sid), name=f"sdis[{sid},{t}]")
            buys = _lin_sum(
                [ctx.buy.sel(process=p, commodity=s.commodity_id, period=t) for p in scope]
            )
            link = charge_t - dis_t
            if buys is not None:
                link = link + buys
            m.add_constraints(ctx.extbuy.sel(store=sid, period=t) == link, name=f"smkt[{sid},{t}]")


def _markets(ctx: BuildContext) -> None:
    """Commodity-market clearing (least-cost mixture) + tradable ETS balance.

    Commodity markets supply a stream's external need (process draw, or the
    store's external purchase if storable):
        Σ_m (mbuy_{m,t} − msell_{m,t}) = external_need_{r,t}
    ETS markets cover emissions with allowances (deficit bought, surplus sold):
        allocation_t + abuy_{m,t} − asell_{m,t} = Σ_{p∈scope} emit_{p,i,t}
    """
    m, prob = ctx.model, ctx.problem

    # ── Commodity markets ────────────────────────────────────────────────────
    by_commodity: dict[str, list[Any]] = {}
    for mk in ctx.cmarkets:
        by_commodity.setdefault(mk.target, []).append(mk)
    storages_of: dict[str, list[Any]] = {}
    for st in prob.storages:
        storages_of.setdefault(st.commodity_id, []).append(st)

    for r, mkts in by_commodity.items():
        scope_companies = {mk.company for mk in mkts}
        procs = (
            ctx.procs
            if "all" in scope_companies
            else [
                p.process_id for p in prob.processes if any(p.in_scope(c) for c in scope_companies)
            ]
        )
        for t in ctx.years:
            net = _lin_sum(
                [ctx.mbuy.sel(cmarket=mk.market_id, period=t) for mk in mkts]
                + [(-1.0) * ctx.msell.sel(cmarket=mk.market_id, period=t) for mk in mkts]
            )
            if r in storages_of:
                target = _lin_sum(
                    [ctx.extbuy.sel(store=s.storage_id, period=t) for s in storages_of[r]]
                )
            else:
                target = _lin_sum([ctx.buy.sel(process=p, commodity=r, period=t) for p in procs])
            rhs = target if target is not None else 0.0
            m.add_constraints(net == rhs, name=f"mclear[{r},{t}]")
        for mk in mkts:
            for t in ctx.years:
                if not mk.available_in(t):
                    m.add_constraints(
                        ctx.mbuy.sel(cmarket=mk.market_id, period=t) == 0,
                        name=f"mclosedb[{mk.market_id},{t}]",
                    )
                    m.add_constraints(
                        ctx.msell.sel(cmarket=mk.market_id, period=t) == 0,
                        name=f"mcloseds[{mk.market_id},{t}]",
                    )
                    continue
                mb = mk.max_buy_at(t)
                if mb is not None:
                    m.add_constraints(
                        ctx.mbuy.sel(cmarket=mk.market_id, period=t) <= mb,
                        name=f"mmaxbuy[{mk.market_id},{t}]",
                    )
                ms = mk.max_sell_at(t)
                if ms is not None:
                    m.add_constraints(
                        ctx.msell.sel(cmarket=mk.market_id, period=t) <= ms,
                        name=f"mmaxsell[{mk.market_id},{t}]",
                    )

    # ── ETS allowance markets ─────────────────────────────────────────────────
    for mk in ctx.imarkets:
        scope = _scope_processes(ctx, mk.company)
        for t in ctx.years:
            emit = _lin_sum([ctx.emit.sel(process=p, impact=mk.target, period=t) for p in scope])
            held = ctx.abuy.sel(imarket=mk.market_id, period=t) - ctx.asell.sel(
                imarket=mk.market_id, period=t
            )
            lhs = held if emit is None else (held - emit)
            m.add_constraints(lhs == -mk.allocation(t), name=f"ets[{mk.market_id},{t}]")
            mb = mk.max_buy_at(t)
            if mb is not None:
                m.add_constraints(
                    ctx.abuy.sel(imarket=mk.market_id, period=t) <= mb,
                    name=f"etsmaxbuy[{mk.market_id},{t}]",
                )
            ms = mk.max_sell_at(t)
            if ms is not None:
                m.add_constraints(
                    ctx.asell.sel(imarket=mk.market_id, period=t) <= ms,
                    name=f"etsmaxsell[{mk.market_id},{t}]",
                )


def _controls(ctx: BuildContext) -> None:
    """Company decision controls: investment budget cap + minimum production."""
    m, prob = ctx.model, ctx.problem
    prev = _prev(ctx.years)
    company_of = {p.process_id: p.company for p in prob.processes}
    trans_idx = _transition_index(prob)
    cap = {p.process_id: p.capacity for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    slot_company = {s.key: company_of.get(s.process, "all") for s in ctx.slots}

    def _in_scope(company: str, target: str) -> bool:
        return company == "all" or target == company

    # Investment-budget cap (nominal capex per company-year).
    for (c, y), limit in prob.investment_budget.items():
        terms: list[Any] = []
        for p in ctx.procs:
            if not _in_scope(c, company_of[p]):
                continue
            for k in ctx.feasible[p]:
                if k == baseline[p]:
                    continue
                cost = _replacement_capex(prob, trans_idx, p, k, cap[p], y)
                if cost:
                    terms.append(cost * ctx.w.sel(process=p, tech=k, period=y))
        for s in ctx.slots:
            if not _in_scope(c, slot_company[s.key]) or not s.capex_at(y):
                continue
            inc = ctx.z.sel(slot=s.key, period=y)
            pt = prev[y]
            if pt is not None:
                inc = inc - ctx.z.sel(slot=s.key, period=pt)
            terms.append(s.capex_at(y) * inc)
        if y == ctx.years[0]:
            for st in prob.storages:
                build_cost = st.capex_per_capacity_at(y)
                if _in_scope(c, st.company) and build_cost:
                    terms.append(build_cost * ctx.cap_built.sel(store=st.storage_id))
        total = _lin_sum(terms)
        if total is not None:
            m.add_constraints(total <= limit, name=f"budget[{c},{y}]")

    # Minimum annual production (hard floor on delivered product).
    for (c, q, y), amount in prob.min_production.items():
        delivered = _lin_sum(
            [ctx.deliver.sel(process=p, commodity=q, period=y) for p in _scope_processes(ctx, c)]
        )
        if delivered is not None:
            m.add_constraints(delivered >= amount, name=f"minprod[{c},{q},{y}]")

    # Maximum annual production (hard ceiling on delivered product).
    for (c, q, y), amount in prob.max_production.items():
        delivered = _lin_sum(
            [ctx.deliver.sel(process=p, commodity=q, period=y) for p in _scope_processes(ctx, c)]
        )
        if delivered is not None:
            m.add_constraints(delivered <= amount, name=f"maxprod[{c},{q},{y}]")

    # Per-machine intake bounds (the consumer side): the machine's gross consumption
    # of a commodity, summed over its providers. min = required offtake (take-or-pay
    # floor), max = maximum purchase (intake ceiling).
    for (c, q, y), amount in prob.min_consumption.items():
        terms = [_gross_consumed(ctx, p, q, y) for p in _scope_processes(ctx, c)]
        consumed = _lin_sum([t for t in terms if t is not None])
        if consumed is not None:
            m.add_constraints(consumed >= amount, name=f"mincons[{c},{q},{y}]")
    for (c, q, y), amount in prob.max_consumption.items():
        terms = [_gross_consumed(ctx, p, q, y) for p in _scope_processes(ctx, c)]
        consumed = _lin_sum([t for t in terms if t is not None])
        if consumed is not None:
            m.add_constraints(consumed <= amount, name=f"maxcons[{c},{q},{y}]")


def _adoption_caps(ctx: BuildContext) -> None:
    r"""Fleet-wide cap on the number of processes running a technology each year.

    For a technology ``k`` with cap ``N_k`` (``Problem.technology_caps``)::

        Σ_p u[p, k, t] ≤ N_k   ∀ t

    i.e. at most ``N_k`` facilities may have ``k`` active in any year — e.g. a
    limited number of greenfield plants of a new route. Inert unless caps are set.

    Vectorised over techs that have a cap; within each tech, sum over the
    feasible-process subset with one ``sum("process")`` call, then add a single
    constraint against the scalar cap.  For each tech this is one linopy call
    covering all periods at once, cutting the call count from T per tech to 1.
    """
    if not ctx.problem.technology_caps:
        return
    m, prob = ctx.model, ctx.problem
    for k, cap in prob.technology_caps.items():
        if k not in ctx.techs:
            continue
        feasible_procs = [p for p in ctx.procs if k in ctx.feasible[p]]
        if not feasible_procs:
            continue
        # Sum u over the feasible-process subset → (period,) expression.
        u_k = ctx.u.sel(process=pd.Index(feasible_procs, name="process"), tech=k).sum(
            "process"
        )  # (period,)
        m.add_constraints(u_k <= cap, name=f"techcap[{k}]")


def _fleet(ctx: BuildContext) -> None:
    r"""Layer 1b: a shared pool of ships allocated across routes (integer MILP).

    A fleet-managed transport process ``p`` (``Problem.fleet_routes``) has its
    throughput supplied by an integer count of ships rather than a fixed capacity::

        Σ_k x[p, k, t] ≤ share_p · units[p, t]              (capacity from fleet)
        Σ_{p ∈ archetype a} units[p, t] ≤ available_{a, t}   (one shared pool)
        min_p ≤ units[p, t] ≤ max_p                          (per-route bounds)

    So ships of an archetype reallocate across its routes year by year — the
    carrier's "which ships on which lane" decision. Inert unless a ``fleet_routes``
    sheet is present (the machine's own ``capacity`` should be set high enough that
    the fleet is the binding limit).
    """
    prob = ctx.problem
    if not prob.fleet_routes:
        return
    m = ctx.model
    routes = [p for p in prob.fleet_routes if p in ctx.procs]
    # (C1) throughput ≤ share·units, and (C3) per-route unit bounds.
    for p in routes:
        fr = prob.fleet_routes[p]
        for t in ctx.years:
            u = ctx.units.sel(process=p, period=t)
            m.add_constraints(
                ctx.x.sel(process=p, period=t).sum("tech") <= fr.share * u,
                name=f"fleetcap[{p},{t}]",
            )
            if fr.max_units is not None:
                m.add_constraints(u <= fr.max_units, name=f"fleetmax[{p},{t}]")
            if fr.min_units:
                m.add_constraints(u >= fr.min_units, name=f"fleetmin[{p},{t}]")
    # (C2) one shared pool per archetype: Σ over its routes ≤ ships available.
    by_arch: dict[str, list[str]] = {}
    for p in routes:
        by_arch.setdefault(prob.fleet_routes[p].archetype, []).append(p)
    for a, ps in by_arch.items():
        for t in ctx.years:
            avail = prob.fleet_available.get((a, t))
            if avail is None:
                continue
            total = _lin_sum([ctx.units.sel(process=p, period=t) for p in ps])
            if total is not None:
                m.add_constraints(total <= avail, name=f"fleetpool[{a},{t}]")


def _objective(ctx: BuildContext) -> None:
    """Discounted total system cost + slack penalties (minimise).

    Vectorisation strategy
    ----------------------
    The objective is a sum of many independent cost components, each expressible
    as a dot product of a coefficient DataArray and a linopy variable:

        obj = Σ_component  coeff_component[dims] · var_component[dims]

    We precompute coefficient DataArrays over all relevant dims (period, process,
    tech, commodity, impact) and evaluate each component as a single linopy
    expression using broadcast-multiply + ``.sum(dims)`` — the same idiom used
    in the constraint families.  This reduces the linopy merge / xarray alignment
    overhead from O(N_terms) to O(N_components), where N_components is small
    (opex, fixed_opex, commodity_buy, commodity_sell, impact_price, capex,
    renewal_capex, measure_capex, measure_opex, storage, markets, slacks).

    ``add_objective`` is called once at the end with the combined expression.
    """
    m, prob = ctx.model, ctx.problem
    tog = prob.toggles
    prev = _prev(ctx.years)
    dur = {p.year: p.duration_years for p in prob.periods}
    cap = {p.process_id: p.capacity for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    proc_by_id = {p.process_id: p for p in prob.processes}
    trans_idx = _transition_index(prob)

    stored = {s.commodity_id for s in prob.storages}
    market_comms = {mk.target for mk in ctx.cmarkets}
    ets_impacts = {mk.target for mk in ctx.imarkets}

    # Discount-weight vector: w[t] = discount_factor(t) * duration(t)
    w_arr = np.array([prob.discount_factor(t) * dur[t] for t in ctx.years])
    w_da = xr.DataArray(w_arr, coords={"period": ctx.years}, dims=["period"])

    obj_terms: list[Any] = []

    # ── Freight: w[t] * (cost_e + Σ_i price[i,t]·emissions_e[i]) * flow[e,t] ──
    # Optional per-edge transport physics (the spatial layer). Untagged edges have
    # cost = 0 and emissions = {}, so they contribute nothing (today's free flow).
    # Freight emissions are impact-AGNOSTIC: each is priced at its OWN impact's price
    # (unpriced impacts cost 0 but are still reported in outputs.transport). No
    # privileged impact. (Folding freight emissions into the characterised inventory
    # + hard impact caps is the next increment — they would need to enter ctx.emit,
    # which is process-indexed.)
    if ctx.flow is not None and any(e.cost or e.emissions for e in prob.edges):

        def _freight_coeff(e: Any, t: int) -> float:
            emit_cost = sum(
                fac * prob.impacts[i].price(t)
                for i, fac in e.emissions.items()
                if i in prob.impacts
            )
            return float(e.cost) + float(emit_cost)

        freight_arr = np.array([[_freight_coeff(e, t) for t in ctx.years] for e in prob.edges])
        freight_da = xr.DataArray(
            freight_arr,
            coords={"edge": list(range(len(prob.edges))), "period": ctx.years},
            dims=["edge", "period"],
        )
        obj_terms.append((w_da * freight_da * ctx.flow).sum(["edge", "period"]))

    # ── Variable opex: w[t] * opex[k,t] * x[p,k,t] ──────────────────────────
    if tog.opex:
        opex_arr = np.array([[prob.technologies[k].opex(t) for t in ctx.years] for k in ctx.techs])
        opex_da = xr.DataArray(
            opex_arr, coords={"tech": ctx.techs, "period": ctx.years}, dims=["tech", "period"]
        )
        # opex_coeff[k,t] * w[t] broadcasts with x[p,k,t] → sum over all dims → scalar
        obj_terms.append((w_da * opex_da * ctx.x).sum(["process", "tech", "period"]))

        # Fixed facility O&M: w[t] * fox[p,t] * on[p,t]
        fox_arr = np.array([[proc_by_id[p].fixed_opex_at(t) for t in ctx.years] for p in ctx.procs])
        fox_da = xr.DataArray(
            fox_arr, coords={"process": ctx.procs, "period": ctx.years}, dims=["process", "period"]
        )
        obj_terms.append((w_da * fox_da * ctx.on).sum(["process", "period"]))

    # ── Commodity buy/sell: w[t] * price[r,t] * buy/sell[p,r,t] ─────────────
    if tog.commodity_cost:
        # Only commodities not priced via storage or market.
        priced_comms = [r for r in ctx.comms if r not in stored and r not in market_comms]
        if priced_comms:
            price_arr = np.array(
                [[prob.commodities[r].price(t) for t in ctx.years] for r in priced_comms]
            )
            sale_arr = np.array(
                [[prob.commodities[r].sale_price(t) for t in ctx.years] for r in priced_comms]
            )
            price_da = xr.DataArray(
                price_arr,
                coords={"commodity": priced_comms, "period": ctx.years},
                dims=["commodity", "period"],
            )
            sale_da = xr.DataArray(
                sale_arr,
                coords={"commodity": priced_comms, "period": ctx.years},
                dims=["commodity", "period"],
            )
            buy_sel = ctx.buy.sel(commodity=pd.Index(priced_comms, name="commodity"))
            sell_sel = ctx.sell.sel(commodity=pd.Index(priced_comms, name="commodity"))
            obj_terms.append((w_da * price_da * buy_sel).sum(["process", "commodity", "period"]))
            obj_terms.append(
                (-1.0 * w_da * sale_da * sell_sel).sum(["process", "commodity", "period"])
            )

    # ── Impact prices: w[t] * price[i,t] * emit[p,i,t] ──────────────────────
    if tog.impact_price and ctx.impacts:
        priced_impacts = [i for i in ctx.impacts if i not in ets_impacts]
        if priced_impacts:
            imp_price_arr = np.array(
                [[prob.impacts[i].price(t) for t in ctx.years] for i in priced_impacts]
            )
            imp_price_da = xr.DataArray(
                imp_price_arr,
                coords={"impact": priced_impacts, "period": ctx.years},
                dims=["impact", "period"],
            )
            emit_sel = ctx.emit.sel(impact=pd.Index(priced_impacts, name="impact"))
            obj_terms.append((w_da * imp_price_da * emit_sel).sum(["process", "impact", "period"]))

    # ── Storage external purchase + fixed O&M ────────────────────────────────
    if tog.commodity_cost and prob.storages:
        for t in ctx.years:
            w = prob.discount_factor(t) * dur[t]
            for st in prob.storages:
                if st.commodity_id not in market_comms:
                    price = prob.commodities[st.commodity_id].price(t)
                    if price:
                        obj_terms.append(
                            (w * price) * ctx.extbuy.sel(store=st.storage_id, period=t)
                        )
                st_fox = st.fixed_opex_per_capacity_at(t)
                if st_fox:
                    obj_terms.append((w * st_fox) * ctx.cap_built.sel(store=st.storage_id))

    # ── Commodity markets ─────────────────────────────────────────────────────
    if tog.commodity_cost and ctx.cmarkets:
        for t in ctx.years:
            w = prob.discount_factor(t) * dur[t]
            for mk in ctx.cmarkets:
                if mk.price(t):
                    obj_terms.append(
                        (w * mk.price(t)) * ctx.mbuy.sel(cmarket=mk.market_id, period=t)
                    )
                if mk.sell_price(t):
                    obj_terms.append(
                        (-w * mk.sell_price(t)) * ctx.msell.sel(cmarket=mk.market_id, period=t)
                    )

    # ── ETS allowance markets ─────────────────────────────────────────────────
    if tog.impact_price and ctx.imarkets:
        for t in ctx.years:
            w = prob.discount_factor(t) * dur[t]
            for mk in ctx.imarkets:
                if mk.price(t):
                    obj_terms.append(
                        (w * mk.price(t)) * ctx.abuy.sel(imarket=mk.market_id, period=t)
                    )
                if mk.sell_price(t):
                    obj_terms.append(
                        (-w * mk.sell_price(t)) * ctx.asell.sel(imarket=mk.market_id, period=t)
                    )

    # ── Replacement capex: charge(t,L) * capex(p,k,t) * w[p,k,t] ────────────
    if tog.capex:
        # capex_coeff[p,k,t] = capex_charge(t, life_k) * replacement_capex(p,k,t)
        # Only for non-baseline (p,k) pairs.
        capex_arr = np.zeros((len(ctx.procs), len(ctx.techs), len(ctx.years)))
        for i, p in enumerate(ctx.procs):
            for j, k in enumerate(ctx.techs):
                if k not in ctx.feasible[p] or k == baseline[p]:
                    continue
                for li, t in enumerate(ctx.years):
                    c = _replacement_capex(prob, trans_idx, p, k, cap[p], t)
                    if c:
                        charge = prob.capex_charge(t, prob.technologies[k].lifespan)
                        capex_arr[i, j, li] = charge * c
        if capex_arr.any():
            capex_da = xr.DataArray(
                capex_arr,
                coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
                dims=["process", "tech", "period"],
            )
            obj_terms.append((capex_da * ctx.w).sum(["process", "tech", "period"]))

    # ── Renewal capex ─────────────────────────────────────────────────────────
    if tog.renewal and ctx.ren is not None:
        ren_capex_arr = np.zeros((len(ctx.procs), len(ctx.techs), len(ctx.years)))
        for i, p in enumerate(ctx.procs):
            for j, k in enumerate(ctx.techs):
                if k not in ctx.feasible[p]:
                    continue
                for li, t in enumerate(ctx.years):
                    rc = prob.technologies[k].renewal(t) * cap[p]
                    if rc:
                        charge = prob.capex_charge(t, prob.technologies[k].lifespan)
                        ren_capex_arr[i, j, li] = charge * rc
        if ren_capex_arr.any():
            ren_capex_da = xr.DataArray(
                ren_capex_arr,
                coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
                dims=["process", "tech", "period"],
            )
            obj_terms.append((ren_capex_da * ctx.ren).sum(["process", "tech", "period"]))

    # ── Measure capex + opex (small — few slots) ──────────────────────────────
    if ctx.slots:
        for t in ctx.years:
            df = prob.discount_factor(t)
            w = df * dur[t]
            pt = prev[t]
            for s in ctx.slots:
                if tog.measure_capex:
                    inc = ctx.z.sel(slot=s.key, period=t)
                    if pt is not None:
                        inc = inc - ctx.z.sel(slot=s.key, period=pt)
                    if s.capex_at(t):
                        obj_terms.append((df * s.capex_at(t)) * inc)
                if tog.opex and s.opex_at(t):
                    obj_terms.append((w * s.opex_at(t)) * ctx.z.sel(slot=s.key, period=t))

    # ── Profit: product sale revenue ──────────────────────────────────────────
    for comp, q, y in ctx.demand_keys:
        if prob.objective_of(comp) != ObjectiveMode.PROFIT:
            continue
        price = prob.commodities[q].sale_price(y)
        if not price:
            continue
        scope = _scope_processes(ctx, comp)
        delivered = _lin_sum([ctx.deliver.sel(process=p, commodity=q, period=y) for p in scope])
        if delivered is not None:
            obj_terms.append((-(prob.discount_factor(y) * dur[y] * price)) * delivered)

    # ── Storage build capex (one-time at t0) ─────────────────────────────────
    if tog.capex and prob.storages:
        y0 = ctx.years[0]
        df0 = prob.discount_factor(y0)
        for st in prob.storages:
            build_cost = st.capex_per_capacity_at(y0)
            if build_cost:
                obj_terms.append((df0 * build_cost) * ctx.cap_built.sel(store=st.storage_id))

    # ── Slack penalties (always full-weight, never scaled by the objective blend) ─
    penalty_terms: list[Any] = []
    if ctx.demand_keys:
        penalty_terms.append(prob.slack_penalty * ctx.slk_dem.sum())
    if ctx.cap_keys:
        for cap_c, cap_i, cap_y in ctx.cap_keys:
            pen = prob.impact_cap_penalty.get((cap_c, cap_i), prob.slack_penalty)
            penalty_terms.append(pen * ctx.slk_cap.sel(ckey=f"{cap_c}|{cap_i}|{cap_y}"))

    # ── LCIA-aware blend: cost_weight·cost + impact_weight·Σ emit[category] ──────
    # Defaults (cost_weight 1, impact_weight 0) reproduce plain least-cost. The
    # impact term is duration-weighted but NOT discounted (a physical emission
    # total, not a cash flow). Slack penalties are added at full weight on top.
    cost = _lin_sum(obj_terms)
    blend: list[Any] = []
    if cost is not None:
        blend.append(cost if prob.cost_weight == 1.0 else prob.cost_weight * cost)
    if prob.objective_impact and prob.impact_weight and prob.objective_impact in ctx.impacts:
        dur_da = xr.DataArray(
            np.array([dur[t] for t in ctx.years]),
            coords={"period": ctx.years},
            dims=["period"],
        )
        emit_cat = ctx.emit.sel(impact=prob.objective_impact)  # (process, period)
        blend.append((prob.impact_weight * dur_da * emit_cat).sum(["process", "period"]))
    blend.extend(penalty_terms)

    obj = _lin_sum(blend)
    if obj is not None:
        m.add_objective(obj)
