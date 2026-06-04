"""The assembled optimisation instance handed to the core builder.

A :class:`Problem` bundles the entity collections (from the workbook) with the
scenario-derived numeric settings (horizon, demand, caps, economics, toggles).
It contains no solver objects; :func:`pathwise.core.build.build` turns it into a
``linopy`` model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathwise.core.entities import (
    CapexConvention,
    Commodity,
    Edge,
    Impact,
    Measure,
    ObjectiveMode,
    Period,
    Process,
    Storage,
    Technology,
    Transition,
)


@dataclass(slots=True)
class CostToggles:
    """Which additive cost components enter the objective."""

    capex: bool = True
    renewal: bool = True
    opex: bool = True
    commodity_cost: bool = True  # purchases minus sales
    impact_price: bool = True  # carbon price / ETS, per impact
    measure_capex: bool = True


@dataclass(slots=True)
class Problem:
    """A complete process-network optimisation instance.

    Attributes:
        periods: Ordered horizon periods.
        processes: Facilities/machines.
        technologies: Technology configs keyed by id.
        commodities: Commodities keyed by id.
        impacts: Impacts keyed by id.
        measures: MACC/measures.
        edges: Inter-process commodity flows.
        transitions: Permitted technology changes (replace/renew) + compatibility.
        storages: Per-commodity inter-year stores.
        commodity_impacts: Impact factor of consuming a commodity, keyed by
            ``(commodity_id, impact_id)`` [impact unit / commodity unit].
        demand: Required product output, keyed by ``(company, commodity_id, year)``
            [commodity unit / yr].
        impact_caps: Upper limit on an impact, keyed by ``(company, impact_id, year)``
            [impact unit / yr]; company ``"all"`` ⇒ sector-wide.
        investment_budget: Max nominal capex spend, keyed by ``(company, year)``
            [currency / yr]; company ``"all"`` ⇒ sector-wide.
        min_production: Minimum delivered product, keyed by
            ``(company, commodity_id, year)`` [commodity unit / yr].
        company_objective: Per-company goal (``cost`` default, or ``profit``).
        discount_rate: Annual discount rate ``ρ`` [1/yr].
        base_year: Baseline period ``t₀``.
        capex_convention: Annuity (CRF) or NPV lump.
        slack_penalty: Objective penalty per unit demand/impact-cap violation.
        toggles: Which cost components are priced.
    """

    periods: list[Period]
    processes: list[Process]
    technologies: dict[str, Technology]
    commodities: dict[str, Commodity]
    impacts: dict[str, Impact]
    measures: list[Measure] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    storages: list[Storage] = field(default_factory=list)
    commodity_impacts: dict[tuple[str, str], float] = field(default_factory=dict)
    demand: dict[tuple[str, str, int], float] = field(default_factory=dict)
    impact_caps: dict[tuple[str, str, int], float] = field(default_factory=dict)
    investment_budget: dict[tuple[str, int], float] = field(default_factory=dict)
    min_production: dict[tuple[str, str, int], float] = field(default_factory=dict)
    company_objective: dict[str, ObjectiveMode] = field(default_factory=dict)
    discount_rate: float = 0.08
    base_year: int = 0
    capex_convention: CapexConvention = CapexConvention.ANNUITY
    slack_penalty: float = 1.0e9
    toggles: CostToggles = field(default_factory=CostToggles)

    @property
    def years(self) -> list[int]:
        """Ordered horizon years."""
        return [p.year for p in self.periods]

    @property
    def companies(self) -> list[str]:
        """Sorted distinct companies across all processes."""
        return sorted({p.company for p in self.processes})

    def discount_factor(self, year: int) -> float:
        r"""Discount factor ``DF_t = (1+ρ)^-(year - base_year)`` [—]."""
        return (1.0 + self.discount_rate) ** (-(year - self.base_year))

    def objective_of(self, company: str) -> ObjectiveMode:
        """Objective mode for ``company`` (default :attr:`ObjectiveMode.COST`)."""
        return self.company_objective.get(company, ObjectiveMode.COST)
