"""Enumerate the portfolio *assets* of a :class:`~pathwise.core.problem.Problem`.

An **asset** is a candidate way to spend transition capital. The atomic unit is
a :class:`Candidate` — one permitted switch of a single facility from its
baseline technology to a target technology. Candidates are grouped into assets
at a user-chosen :class:`AssetLevel` (per facility / per technology / per
company); the portfolio optimiser then allocates a weight to each asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pathwise.core.problem import Problem


class AssetLevel(StrEnum):
    """The granularity at which candidate transitions are grouped into assets."""

    FACILITY = "facility"  # one asset per (process, target technology)
    TECHNOLOGY = "technology"  # one asset per target technology (economy-wide)
    COMPANY = "company"  # one asset per company (its whole transition budget)
    ECONOMY = "economy"  # one asset per target technology, pooled (≡ technology)


@dataclass(slots=True, frozen=True)
class Candidate:
    """One permitted facility transition — the atomic investment option.

    Attributes:
        process_id: Facility that would switch.
        company: Owning company (demand/economic scope).
        from_technology: The facility's baseline technology.
        to_technology: The technology it would switch to.
        capacity: Facility nameplate throughput [throughput / yr].
        transition_capex: One-off switch cost [currency] =
            ``capex_per_capacity × capacity``.
    """

    process_id: str
    company: str
    from_technology: str
    to_technology: str
    capacity: float
    transition_capex: float


@dataclass(slots=True, frozen=True)
class Asset:
    """A weighted line in the portfolio — one or more grouped candidates.

    Attributes:
        asset_id: Stable key (depends on the :class:`AssetLevel`).
        label: Human-readable label for the UI.
        company: Owning company, or ``"(mixed)"`` when the group spans companies.
        from_technology: Baseline technology, or ``"(mixed)"`` when it varies.
        to_technology: Target technology, or ``"(mixed)"`` when it varies.
        members: The candidates aggregated into this asset.
    """

    asset_id: str
    label: str
    company: str
    from_technology: str
    to_technology: str
    members: tuple[Candidate, ...]

    @property
    def transition_capex(self) -> float:
        """Total switch cost of all members [currency]."""
        return sum(c.transition_capex for c in self.members)


def enumerate_candidates(problem: Problem) -> list[Candidate]:
    """All permitted (facility → target technology) switches.

    A candidate exists for every ``replaceable`` facility and every
    :class:`~pathwise.core.entities.Transition` whose ``from_technology`` is that
    facility's baseline and whose ``to_technology`` is a different, known, and
    (by ``introduction_year``) available technology.

    Args:
        problem: The assembled optimisation instance.

    Returns:
        Candidate switches, ordered by ``(process_id, to_technology)``.
    """
    first_year = min(problem.years) if problem.years else 0
    by_from: dict[str, list[str]] = {}
    for tr in problem.transitions:
        if tr.to_technology != tr.from_technology:
            by_from.setdefault(tr.from_technology, []).append(tr.to_technology)
    capex_of = {
        (tr.from_technology, tr.to_technology): tr.capex_at(first_year)
        for tr in problem.transitions
    }

    out: list[Candidate] = []
    for proc in problem.processes:
        if not proc.replaceable:
            continue
        base = proc.baseline_technology
        for to_tech in by_from.get(base, []):
            tech = problem.technologies.get(to_tech)
            if tech is None:
                continue
            if tech.introduction_year is not None and tech.introduction_year > first_year:
                # Still allowed — it becomes available mid-horizon; the switch
                # cost is discounted to the first horizon year regardless.
                pass
            out.append(
                Candidate(
                    process_id=proc.process_id,
                    company=proc.company,
                    from_technology=base,
                    to_technology=to_tech,
                    capacity=proc.capacity,
                    transition_capex=capex_of.get((base, to_tech), 0.0) * proc.capacity,
                )
            )
    out.sort(key=lambda c: (c.process_id, c.to_technology))
    return out


def enumerate_assets(problem: Problem, level: AssetLevel) -> list[Asset]:
    """Group candidate switches into portfolio assets at ``level``.

    Args:
        problem: The assembled optimisation instance.
        level: Grouping granularity (see :class:`AssetLevel`). ``ECONOMY`` is an
            alias of ``TECHNOLOGY`` (both pool across companies).

    Returns:
        Assets ordered by ``asset_id``. May be empty (fewer than two assets is a
        degenerate portfolio the caller should reject).
    """
    candidates = enumerate_candidates(problem)
    groups: dict[str, list[Candidate]] = {}
    for c in candidates:
        key = _group_key(level, c)
        groups.setdefault(key, []).append(c)

    assets: list[Asset] = []
    for key in sorted(groups):
        members = tuple(groups[key])
        companies = {m.company for m in members}
        froms = {m.from_technology for m in members}
        tos = {m.to_technology for m in members}
        company = next(iter(companies)) if len(companies) == 1 else "(mixed)"
        from_tech = next(iter(froms)) if len(froms) == 1 else "(mixed)"
        to_tech = next(iter(tos)) if len(tos) == 1 else "(mixed)"
        assets.append(
            Asset(
                asset_id=key,
                label=_label(level, key, members),
                company=company,
                from_technology=from_tech,
                to_technology=to_tech,
                members=members,
            )
        )
    return assets


def _group_key(level: AssetLevel, c: Candidate) -> str:
    """Stable grouping key for a candidate at ``level``."""
    if level == AssetLevel.FACILITY:
        return f"{c.process_id}->{c.to_technology}"
    if level == AssetLevel.COMPANY:
        return c.company
    # TECHNOLOGY and ECONOMY both group by the target technology, economy-wide.
    return c.to_technology


def _label(level: AssetLevel, key: str, members: tuple[Candidate, ...]) -> str:
    """Human-readable label for an asset group."""
    if level == AssetLevel.FACILITY:
        c = members[0]
        return f"{c.process_id} → {c.to_technology}"
    if level == AssetLevel.COMPANY:
        return key
    return f"→ {key}"
