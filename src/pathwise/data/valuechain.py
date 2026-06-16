"""Value-chain spec — a DAG of stage-models coupled by lagged signals.

A *value chain* links several otherwise-independent pathwise models (each a
stage — typically a sector in a region: coal · electricity · steel · auto) into a
directed graph. A **coupling link** says that an upstream stage's solved outcome
for a shared commodity (its price, carbon intensity, or produced volume) feeds
the downstream stage's inputs, optionally **lagged** by a number of years. The
orchestrator in :mod:`pathwise.core.valuechain` consumes this spec.

The format mirrors the facility/chain library (:mod:`pathwise.data.library`):
plain JSON validated by pydantic, kept sector-agnostic (a stage references a
model by an opaque id the caller resolves; nothing here is industry-specific).
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

#: Signals a link may carry from an upstream stage to a downstream stage.
#: ``price`` is the average-cost proxy; ``marginal_price`` is the true marginal
#: cost (finite-difference on demand) and takes precedence when both are present;
#: ``carbon_intensity`` transfers the upstream emissions per unit; ``volume``
#: transfers the upstream produced quantity as a cap on the downstream stage's
#: external purchase of the commodity (available supply).
SIGNALS = ("price", "marginal_price", "carbon_intensity", "volume")


class Stage(BaseModel):
    """One node of the value chain — a model to solve at a point in the chain.

    Attributes:
        id: Unique stage id within the chain.
        label: Human-readable name.
        model: Opaque reference to the stage's workbook (an example id, a library
            chain, or a session model). Resolved to a ``Workbook`` by the caller
            — the orchestrator itself never does I/O.
        region: Optional region label (e.g. ``"KR"``) for grouping in the UI.
        sector: Optional sector label (e.g. ``"electricity"``).
        scenario: Optional per-stage scenario overrides, deep-merged onto the run
            scenario (e.g. a stage-local carbon price / cap = a policy).
    """

    id: str
    label: str = ""
    model: str = ""
    region: str = ""
    sector: str = ""
    scenario: dict[str, Any] = Field(default_factory=dict)


class CouplingLink(BaseModel):
    """A directed coupling from one stage to another for one commodity.

    Attributes:
        from_stage: Upstream stage id (its solved outcome is the source).
        to_stage: Downstream stage id (its inputs receive the signal).
        commodity: The shared commodity id the signal is about (e.g.
            ``"electricity"``).
        signals: Which signals transfer — a subset of :data:`SIGNALS`.
        impact: Which impact the ``carbon_intensity`` signal is about (default
            ``"CO2"``); ignored by the other signals.
        lag_years: Years to shift the signal forward (the time gap between an
            upstream change and its downstream effect).
        feedback: If True, the downstream stage's consumption of ``commodity``
            is fed back as the upstream stage's demand for it (two-way coupling,
            resolved by fixed-point iteration when ``iterations > 1``).
        alternative_of: If set, this link is an *alternative* supply choice for
            the same downstream commodity as the named link (authored via the
            L0 "Link alternative source" action). Alternative links are inert in
            the forward cascade (compared, not auto-selected) until a later phase.
    """

    from_stage: str
    to_stage: str
    commodity: str
    signals: list[str] = Field(default_factory=lambda: ["price"])
    impact: str = "CO2"
    lag_years: int = Field(default=0, ge=0)
    feedback: bool = False
    alternative_of: str | None = None

    @field_validator("signals")
    @classmethod
    def _known_signals(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in SIGNALS]
        if bad:
            raise ValueError(f"unknown signal(s) {bad}; expected a subset of {list(SIGNALS)}")
        return v


class ValueChainSpec(BaseModel):
    """A whole value chain: stages plus the coupling links between them."""

    id: str
    label: str = ""
    stages: list[Stage] = Field(min_length=1)
    links: list[CouplingLink] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> ValueChainSpec:
        ids = [s.id for s in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate stage id in value chain")
        known = set(ids)
        for link in self.links:
            for end in (link.from_stage, link.to_stage):
                if end not in known:
                    raise ValueError(f"link references unknown stage '{end}'")
            if link.from_stage == link.to_stage:
                raise ValueError(f"self-link on stage '{link.from_stage}'")
        # The active (non-alternative) links must form a DAG so the cascade has a
        # solve order; alternative links are excluded (they are choices, not flow).
        self.order()
        return self

    def stage(self, stage_id: str) -> Stage:
        """Look up a stage by id."""
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(f"unknown stage '{stage_id}'")

    def active_links(self) -> list[CouplingLink]:
        """Coupling links that participate in the forward cascade (not alternatives)."""
        return [link for link in self.links if link.alternative_of is None]

    def order(self) -> list[str]:
        """Stage ids in upstream→downstream topological order (Kahn's algorithm).

        Raises:
            ValueError: If the active links contain a cycle.
        """
        deps: dict[str, set[str]] = {s.id: set() for s in self.stages}
        for link in self.active_links():
            deps[link.to_stage].add(link.from_stage)
        ready = deque(sorted(sid for sid, ups in deps.items() if not ups))
        order: list[str] = []
        while ready:
            sid = ready.popleft()
            order.append(sid)
            for other, ups in deps.items():
                if sid in ups:
                    ups.discard(sid)
                    if not ups and other not in order and other not in ready:
                        ready.append(other)
        if len(order) != len(self.stages):
            raise ValueError("value-chain links contain a cycle (no forward solve order)")
        return order


def load_value_chain(path: str | Path) -> ValueChainSpec:
    """Load and validate one value-chain JSON file."""
    with open(path, encoding="utf-8") as fh:
        return ValueChainSpec.model_validate(json.load(fh))
