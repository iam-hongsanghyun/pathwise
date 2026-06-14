"""Composite components — reusable, recursively-nested building blocks.

The authoring model: every reusable thing has a unique name and lives in a
*component library*. A **machine** component is a leaf (a technology recipe + a
capacity). A **group** component is a composite: it lists its children (each a
reference to another component, by name, with an instance *alias*) and the
**connections between those children** — so a group carries its own internal
wiring and reusing the group reuses the wiring.

Placing a component **instantiates** it: :func:`instantiate` walks the chosen
component top-down and stamps a fresh INSTANCE of every descendant into the
recursive ``nodes`` / ``machines`` / ``connections`` hierarchy (path-qualified
ids keep instances unique), so one definition can be reused in many groups. This
is the recursive generalization of :func:`pathwise.data.library.instantiate_chain`
and produces a workbook the engine (and :func:`pathwise.core.run.run_model`)
consumes directly.

This is the "vertical" (composition) and "horizontal" (connections) design,
together, as data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from pathwise.data.library import CommodityTemplate, TechnologyTemplate, _io_rows, _tech_row
from pathwise.data.workbook import Workbook


class MachineComponent(BaseModel):
    """A leaf component: a unit running one technology, with its own capacity."""

    name: str
    label: str = ""
    technology: str  # a technology_id defined in the library's technologies
    capacity: float = Field(default=0.0, ge=0.0)


class ChildRef(BaseModel):
    """A child slot in a group: which component, under what instance alias."""

    component: str
    alias: str = ""  # instance name within the parent (defaults to the component name)

    def instance_alias(self) -> str:
        return self.alias or self.component


class ConnectionTemplate(BaseModel):
    """A connection between two sibling children of a group (by their aliases)."""

    source: str  # producer child alias
    target: str  # consumer child alias
    commodity: str
    lag_years: int = Field(default=0, ge=0)


class GroupComponent(BaseModel):
    """A composite component: named children + the connections that wire them."""

    name: str
    label: str = ""
    level: str = ""  # the designed level this group sits at (free text)
    children: list[ChildRef] = Field(min_length=1)
    connections: list[ConnectionTemplate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _aliases_unique_and_wired(self) -> GroupComponent:
        aliases = [c.instance_alias() for c in self.children]
        if len(aliases) != len(set(aliases)):
            raise ValueError(f"group '{self.name}' has duplicate child aliases")
        known = set(aliases)
        for conn in self.connections:
            for end in (conn.source, conn.target):
                if end not in known:
                    raise ValueError(
                        f"group '{self.name}' connection references unknown child '{end}'"
                    )
        return self


class ComponentLibrary(BaseModel):
    """A catalogue of reusable components plus the recipes they reference."""

    label: str = ""
    commodities: list[CommodityTemplate] = Field(default_factory=list)
    technologies: list[TechnologyTemplate] = Field(default_factory=list)
    machines: list[MachineComponent] = Field(default_factory=list)
    groups: list[GroupComponent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _names_unique(self) -> ComponentLibrary:
        names = [m.name for m in self.machines] + [g.name for g in self.groups]
        if len(names) != len(set(names)):
            raise ValueError("duplicate component name across machines/groups")
        return self

    def machine(self, name: str) -> MachineComponent | None:
        return next((m for m in self.machines if m.name == name), None)

    def group(self, name: str) -> GroupComponent | None:
        return next((g for g in self.groups if g.name == name), None)


def load_component_library(path: str | Path) -> ComponentLibrary:
    """Load and validate a component library JSON file."""
    with open(path, encoding="utf-8") as fh:
        return ComponentLibrary.model_validate(json.load(fh))


def instantiate(
    library: ComponentLibrary, component: str, *, instance_id: str | None = None
) -> Workbook:
    """Stamp a component into a recursive hierarchy workbook (one fresh instance).

    Recursively places ``component`` and all its descendants as instance nodes
    (path-qualified ids), emitting the ``nodes`` / ``machines`` / ``connections``
    sheets plus the referenced ``technologies`` / ``io`` / ``commodities``. The
    result is a runnable workbook (add ``periods`` + ``demand`` to solve).

    Raises:
        KeyError: If ``component`` or any referenced child is not in the library.
    """
    nodes: list[dict[str, Any]] = []
    machines: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []

    def place(name: str, node_id: str, parent_id: str | None) -> None:
        machine = library.machine(name)
        if machine is not None:
            nodes.append(
                {
                    "node_id": node_id,
                    "parent_id": parent_id,
                    "kind": "machine",
                    "level": "machine",
                    "label": machine.label or machine.name,
                }
            )
            machines.append(
                {
                    "machine_id": node_id,
                    "baseline_technology": machine.technology,
                    "capacity": machine.capacity,
                }
            )
            return
        group = library.group(name)
        if group is None:
            raise KeyError(f"unknown component '{name}'")
        nodes.append(
            {
                "node_id": node_id,
                "parent_id": parent_id,
                "kind": "group",
                "level": group.level,
                "label": group.label or group.name,
            }
        )
        alias_to_id: dict[str, str] = {}
        for child in group.children:
            alias = child.instance_alias()
            child_id = f"{node_id}/{alias}"
            alias_to_id[alias] = child_id
            place(child.component, child_id, node_id)
        for conn in group.connections:
            connections.append(
                {
                    "from_node": alias_to_id[conn.source],
                    "to_node": alias_to_id[conn.target],
                    "commodity_id": conn.commodity,
                    "lag_years": conn.lag_years,
                }
            )

    root_id = instance_id or component
    place(component, root_id, None)

    technologies = [_tech_row(t) for t in library.technologies]
    io: list[dict[str, Any]] = []
    for t in library.technologies:
        io.extend(_io_rows(t))
    commodities: list[dict[str, Any]] = []
    for c in library.commodities:
        row: dict[str, Any] = {"commodity_id": c.commodity_id, "kind": c.kind, "unit": c.unit}
        if c.price is not None:
            row["price"] = c.price
        if c.sale_price is not None:
            row["sale_price"] = c.sale_price
        commodities.append(row)

    return {
        "nodes": nodes,
        "machines": machines,
        "connections": connections,
        "technologies": technologies,
        "io": io,
        "commodities": commodities,
    }
