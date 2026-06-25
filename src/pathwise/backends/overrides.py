"""Typed workbook edits — the mechanism a simulator *variant* compiles down to.

A **variant** in the ``simulate`` backend is a small set of edits to the model,
evaluated and diffed against the baseline (see ``docs/proposals/simulation-backend.md``
§5). Each edit is a typed ``override`` op; :func:`apply_overrides` returns a NEW
workbook with the ops applied, never mutating the input (touched sheets are
copied, the rest shared).

Supported ops (P2):

* ``set_asset_tech`` — ``{op, asset, technology}``: pin a asset to a
  different baseline technology (e.g. switch a steel mill ``BOF`` → ``EAF``).
* ``set_price`` — ``{op, flow, price, year?}``: change a flow's
  purchase price; a static ``price`` (all years) unless ``year`` is given, in
  which case the wide temporal price sheet is edited for that year.
* ``set_carbon_price`` — ``{op, impact, price, year?}``: set an impact (carbon)
  price; static across years, or one ``year`` of the long ``impact_prices`` sheet.
* ``toggle_lever`` — ``{op, lever, on}``: with ``on=True`` re-introduce a
  lever (and its blocks) from ``source`` so the fixed-config LP may adopt it
  when economic; ``on=False`` removes it. The simulator's baseline strips all
  levers, so ``toggle_lever`` is how a variant puts one back on the table.

Value edits (change an existing entity's number, static or per-``year``):

* ``set_tech_cost`` — ``{op, technology, field: capex|opex, value, year?}``.
* ``set_io_coef`` — ``{op, technology, flow, value, year?, role?}``: a
  technology's input/output coefficient for ``flow`` (``io`` / ``io_t``).
* ``set_stream_cap`` — ``{op, flow, field: max_purchase|available_from|
  available_to, value, year?}`` (year only for ``max_purchase``).
"""

from __future__ import annotations

import copy
from typing import Any

from pathwise.data import sheets
from pathwise.data.workbook import Workbook, default_impact
from pathwise.logger import get_logger

logger = get_logger(__name__)

#: Lever sheets re-introduced together when a lever is toggled on.
_LEVER_SHEETS = (
    sheets.LEVERS,
    sheets.LEVER_BLOCKS,
    sheets.LEVER_BLOCKS_T,
    sheets.LEVER_LINKS,
)


class OverrideError(ValueError):
    """A malformed or inapplicable override op."""


def apply_overrides(
    base: Workbook,
    overrides: list[dict[str, Any]],
    *,
    source: Workbook | None = None,
) -> Workbook:
    """Return a copy of ``base`` with ``overrides`` applied in order.

    Args:
        base: The workbook to edit (typically the simulator's stripped *as-is*
            view). Not mutated.
        overrides: Ordered list of typed op dicts.
        source: The full, un-stripped workbook to pull rows from (used by
            ``toggle_lever on`` to re-introduce a stripped lever). Defaults
            to ``base``.

    Returns:
        A new workbook with every op applied.

    Raises:
        OverrideError: If an op is unknown or names an entity that does not exist.
    """
    src = source if source is not None else base
    wb: Workbook = dict(base)  # shallow; ops deep-copy the sheet they touch
    for ov in overrides:
        op = str(ov.get("op") or "")
        handler = _OPS.get(op)
        if handler is None:
            raise OverrideError(f"unknown override op: {op!r}")
        handler(wb, ov, src)
        logger.debug("applied override op=%s", op)
    return wb


def _rows(wb: Workbook, sheet: str) -> list[dict[str, Any]]:
    """A fresh, deep-copied row list for ``sheet`` in ``wb`` (so edits are local)."""
    rows = [copy.deepcopy(r) for r in wb.get(sheet, [])]
    wb[sheet] = rows
    return rows


def _set_asset_tech(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    asset, tech = str(ov.get("asset") or ""), str(ov.get("technology") or "")
    if not asset or not tech:
        raise OverrideError("set_asset_tech needs 'asset' and 'technology'")
    if not any(str(t.get("technology_id")) == tech for t in wb.get(sheets.TECHNOLOGIES, [])):
        raise OverrideError(f"set_asset_tech: unknown technology {tech!r}")
    rows = _rows(wb, sheets.ASSETS)
    hit = [r for r in rows if str(r.get("asset_id")) == asset]
    if not hit:
        raise OverrideError(f"set_asset_tech: unknown asset {asset!r}")
    for r in hit:
        r["baseline_technology"] = tech


def _set_price(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    flow, price = str(ov.get("flow") or ""), ov.get("price")
    if not flow or price is None:
        raise OverrideError("set_price needs 'flow' and 'price'")
    price = float(price)
    rows = _rows(wb, sheets.FLOWS)
    hit = [r for r in rows if str(r.get("flow_id")) == flow]
    if not hit:
        raise OverrideError(f"set_price: unknown flow {flow!r}")
    year = ov.get("year")
    if year is None:
        for r in hit:
            r["price"] = price
        return
    # Year-specific: edit the wide temporal price sheet (year column + per-flow).
    trows = _rows(wb, sheets.FLOWS_T_PRICE)
    yr = int(year)
    for r in trows:
        if int(r.get("year") or 0) == yr:
            r[flow] = price
            return
    trows.append({"year": yr, flow: price})


def _set_carbon_price(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    impact, price = str(ov.get("impact") or default_impact(wb)), ov.get("price")
    if price is None:
        raise OverrideError("set_carbon_price needs 'price'")
    price = float(price)
    rows = _rows(wb, sheets.IMPACT_PRICES)
    year = ov.get("year")
    if year is not None:
        yr = int(year)
        for r in rows:
            if str(r.get("impact_id")) == impact and int(r.get("year") or 0) == yr:
                r["price"] = price
                return
        rows.append({"impact_id": impact, "year": yr, "price": price})
        return
    # Static: one price for every modelled year — drop existing rows for the
    # impact, then re-add at every year already present for any impact.
    years = sorted({int(r.get("year") or 0) for r in rows} or {0})
    wb[sheets.IMPACT_PRICES] = [r for r in rows if str(r.get("impact_id")) != impact] + [
        {"impact_id": impact, "year": y, "price": price} for y in years
    ]


def _toggle_lever(wb: Workbook, ov: dict[str, Any], src: Workbook) -> None:
    lever, on = str(ov.get("lever") or ""), bool(ov.get("on", True))
    if not lever:
        raise OverrideError("toggle_lever needs 'lever'")
    for sheet in _LEVER_SHEETS:
        kept = [r for r in _rows(wb, sheet) if str(r.get("lever_id")) != lever]
        wb[sheet] = kept
        if on:
            kept.extend(
                copy.deepcopy(r) for r in src.get(sheet, []) if str(r.get("lever_id")) == lever
            )
    if on and not any(str(r.get("lever_id")) == lever for r in wb.get(sheets.LEVERS, [])):
        raise OverrideError(f"toggle_lever: unknown lever {lever!r}")


def _set_wide(wb: Workbook, sheet: str, year: int, column: str, value: float) -> None:
    """Set ``column = value`` at ``year`` in a wide temporal sheet (year row + one
    column per entity), appending the year row if it does not exist yet."""
    rows = _rows(wb, sheet)
    for r in rows:
        if int(r.get("year") or 0) == year:
            r[column] = value
            return
    rows.append({"year": year, column: value})


def _set_tech_cost(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    tech, field = str(ov.get("technology") or ""), str(ov.get("field") or "capex")
    if not tech or field not in ("capex", "opex") or ov.get("value") is None:
        raise OverrideError("set_tech_cost needs 'technology', 'field' (capex|opex), 'value'")
    value, year = float(ov["value"]), ov.get("year")
    if year is not None:
        sheet = sheets.TECHNOLOGIES_T_CAPEX if field == "capex" else sheets.TECHNOLOGIES_T_OPEX
        _set_wide(wb, sheet, int(year), tech, value)
        return
    rows = _rows(wb, sheets.TECHNOLOGIES)
    hit = [r for r in rows if str(r.get("technology_id")) == tech]
    if not hit:
        raise OverrideError(f"set_tech_cost: unknown technology {tech!r}")
    for r in hit:
        r[field] = value


def _set_io_coef(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    tech, flow = str(ov.get("technology") or ""), str(ov.get("flow") or "")
    if not tech or not flow or ov.get("value") is None:
        raise OverrideError("set_io_coef needs 'technology', 'flow', 'value'")
    value, year = float(ov["value"]), ov.get("year")
    # Match the io row(s) for (technology, target); narrow by role when given.
    role = ov.get("role")
    matches = [
        r
        for r in wb.get(sheets.IO, [])
        if str(r.get("technology_id")) == tech
        and str(r.get("target")) == flow
        and (role is None or str(r.get("role")) == str(role))
    ]
    if not matches:
        raise OverrideError(f"set_io_coef: no io row for {tech!r} → {flow!r}")
    roles = {str(r.get("role")) for r in matches}
    if year is None:
        rows = _rows(wb, sheets.IO)
        for r in rows:
            if (
                str(r.get("technology_id")) == tech
                and str(r.get("target")) == flow
                and (role is None or str(r.get("role")) == str(role))
            ):
                r["coefficient"] = value
        return
    # Year-specific: upsert long-format io_t rows (one per matched role).
    trows = _rows(wb, sheets.IO_T)
    yr = int(year)
    for rl in roles:
        existing = next(
            (
                r
                for r in trows
                if str(r.get("technology_id")) == tech
                and str(r.get("target")) == flow
                and str(r.get("role")) == rl
                and int(r.get("year") or 0) == yr
            ),
            None,
        )
        if existing is not None:
            existing["coefficient"] = value
        else:
            trows.append(
                {
                    "technology_id": tech,
                    "target": flow,
                    "role": rl,
                    "year": yr,
                    "coefficient": value,
                }
            )


def _set_stream_cap(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    flow, field = str(ov.get("flow") or ""), str(ov.get("field") or "max_purchase")
    if not flow or field not in ("max_purchase", "available_from", "available_to"):
        raise OverrideError(
            "set_stream_cap needs 'flow' and a 'field' of "
            "max_purchase / available_from / available_to"
        )
    if ov.get("value") is None:
        raise OverrideError("set_stream_cap needs 'value'")
    year = ov.get("year")
    if field == "max_purchase" and year is not None:
        _set_wide(wb, sheets.FLOWS_T_MAX_PURCHASE, int(year), flow, float(ov["value"]))
        return
    rows = _rows(wb, sheets.FLOWS)
    hit = [r for r in rows if str(r.get("flow_id")) == flow]
    if not hit:
        raise OverrideError(f"set_stream_cap: unknown flow {flow!r}")
    # availability years are ints; max_purchase is a float.
    cast = int if field in ("available_from", "available_to") else float
    for r in hit:
        r[field] = cast(ov["value"])


_OPS = {
    "set_asset_tech": _set_asset_tech,
    "set_price": _set_price,
    "set_carbon_price": _set_carbon_price,
    "toggle_lever": _toggle_lever,
    "set_tech_cost": _set_tech_cost,
    "set_io_coef": _set_io_coef,
    "set_stream_cap": _set_stream_cap,
}
