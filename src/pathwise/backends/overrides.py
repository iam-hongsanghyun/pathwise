"""Typed workbook edits — the mechanism a simulator *variant* compiles down to.

A **variant** in the ``simulate`` backend is a small set of edits to the model,
evaluated and diffed against the baseline (see ``docs/proposals/simulation-backend.md``
§5). Each edit is a typed ``override`` op; :func:`apply_overrides` returns a NEW
workbook with the ops applied, never mutating the input (touched sheets are
copied, the rest shared).

Supported ops (P2):

* ``set_machine_tech`` — ``{op, machine, technology}``: pin a machine to a
  different baseline technology (e.g. switch a steel mill ``BOF`` → ``EAF``).
* ``set_price`` — ``{op, commodity, price, year?}``: change a commodity's
  purchase price; a static ``price`` (all years) unless ``year`` is given, in
  which case the wide temporal price sheet is edited for that year.
* ``set_carbon_price`` — ``{op, impact, price, year?}``: set an impact (carbon)
  price; static across years, or one ``year`` of the long ``impact_prices`` sheet.
* ``toggle_measure`` — ``{op, measure, on}``: with ``on=True`` re-introduce a
  measure (and its blocks) from ``source`` so the fixed-config LP may adopt it
  when economic; ``on=False`` removes it. The simulator's baseline strips all
  measures, so ``toggle_measure`` is how a variant puts one back on the table.

Value edits (change an existing entity's number, static or per-``year``):

* ``set_tech_cost`` — ``{op, technology, field: capex|opex, value, year?}``.
* ``set_io_coef`` — ``{op, technology, commodity, value, year?, role?}``: a
  technology's input/output coefficient for ``commodity`` (``io`` / ``io_t``).
* ``set_stream_cap`` — ``{op, commodity, field: max_purchase|available_from|
  available_to, value, year?}`` (year only for ``max_purchase``).
"""

from __future__ import annotations

import copy
from typing import Any

from pathwise.data import sheets
from pathwise.data.workbook import Workbook, default_impact
from pathwise.logger import get_logger

logger = get_logger(__name__)

#: Measure sheets re-introduced together when a measure is toggled on.
_MEASURE_SHEETS = (
    sheets.MEASURES,
    sheets.MEASURE_BLOCKS,
    sheets.MEASURE_BLOCKS_T,
    sheets.MEASURE_LINKS,
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
            ``toggle_measure on`` to re-introduce a stripped measure). Defaults
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


def _set_machine_tech(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    machine, tech = str(ov.get("machine") or ""), str(ov.get("technology") or "")
    if not machine or not tech:
        raise OverrideError("set_machine_tech needs 'machine' and 'technology'")
    if not any(str(t.get("technology_id")) == tech for t in wb.get(sheets.TECHNOLOGIES, [])):
        raise OverrideError(f"set_machine_tech: unknown technology {tech!r}")
    rows = _rows(wb, sheets.MACHINES)
    hit = [r for r in rows if str(r.get("machine_id")) == machine]
    if not hit:
        raise OverrideError(f"set_machine_tech: unknown machine {machine!r}")
    for r in hit:
        r["baseline_technology"] = tech


def _set_price(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    commodity, price = str(ov.get("commodity") or ""), ov.get("price")
    if not commodity or price is None:
        raise OverrideError("set_price needs 'commodity' and 'price'")
    price = float(price)
    rows = _rows(wb, sheets.COMMODITIES)
    hit = [r for r in rows if str(r.get("commodity_id")) == commodity]
    if not hit:
        raise OverrideError(f"set_price: unknown commodity {commodity!r}")
    year = ov.get("year")
    if year is None:
        for r in hit:
            r["price"] = price
        return
    # Year-specific: edit the wide temporal price sheet (year column + per-commodity).
    trows = _rows(wb, sheets.COMMODITIES_T_PRICE)
    yr = int(year)
    for r in trows:
        if int(r.get("year") or 0) == yr:
            r[commodity] = price
            return
    trows.append({"year": yr, commodity: price})


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


def _toggle_measure(wb: Workbook, ov: dict[str, Any], src: Workbook) -> None:
    measure, on = str(ov.get("measure") or ""), bool(ov.get("on", True))
    if not measure:
        raise OverrideError("toggle_measure needs 'measure'")
    for sheet in _MEASURE_SHEETS:
        kept = [r for r in _rows(wb, sheet) if str(r.get("measure_id")) != measure]
        wb[sheet] = kept
        if on:
            kept.extend(
                copy.deepcopy(r) for r in src.get(sheet, []) if str(r.get("measure_id")) == measure
            )
    if on and not any(str(r.get("measure_id")) == measure for r in wb.get(sheets.MEASURES, [])):
        raise OverrideError(f"toggle_measure: unknown measure {measure!r}")


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
    tech, commodity = str(ov.get("technology") or ""), str(ov.get("commodity") or "")
    if not tech or not commodity or ov.get("value") is None:
        raise OverrideError("set_io_coef needs 'technology', 'commodity', 'value'")
    value, year = float(ov["value"]), ov.get("year")
    # Match the io row(s) for (technology, target); narrow by role when given.
    role = ov.get("role")
    matches = [
        r
        for r in wb.get(sheets.IO, [])
        if str(r.get("technology_id")) == tech
        and str(r.get("target")) == commodity
        and (role is None or str(r.get("role")) == str(role))
    ]
    if not matches:
        raise OverrideError(f"set_io_coef: no io row for {tech!r} → {commodity!r}")
    roles = {str(r.get("role")) for r in matches}
    if year is None:
        rows = _rows(wb, sheets.IO)
        for r in rows:
            if (
                str(r.get("technology_id")) == tech
                and str(r.get("target")) == commodity
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
                and str(r.get("target")) == commodity
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
                    "target": commodity,
                    "role": rl,
                    "year": yr,
                    "coefficient": value,
                }
            )


def _set_stream_cap(wb: Workbook, ov: dict[str, Any], _src: Workbook) -> None:
    commodity, field = str(ov.get("commodity") or ""), str(ov.get("field") or "max_purchase")
    if not commodity or field not in ("max_purchase", "available_from", "available_to"):
        raise OverrideError(
            "set_stream_cap needs 'commodity' and a 'field' of "
            "max_purchase / available_from / available_to"
        )
    if ov.get("value") is None:
        raise OverrideError("set_stream_cap needs 'value'")
    year = ov.get("year")
    if field == "max_purchase" and year is not None:
        _set_wide(wb, sheets.COMMODITIES_T_MAX_PURCHASE, int(year), commodity, float(ov["value"]))
        return
    rows = _rows(wb, sheets.COMMODITIES)
    hit = [r for r in rows if str(r.get("commodity_id")) == commodity]
    if not hit:
        raise OverrideError(f"set_stream_cap: unknown commodity {commodity!r}")
    # availability years are ints; max_purchase is a float.
    cast = int if field in ("available_from", "available_to") else float
    for r in hit:
        r[field] = cast(ov["value"])


_OPS = {
    "set_machine_tech": _set_machine_tech,
    "set_price": _set_price,
    "set_carbon_price": _set_carbon_price,
    "toggle_measure": _toggle_measure,
    "set_tech_cost": _set_tech_cost,
    "set_io_coef": _set_io_coef,
    "set_stream_cap": _set_stream_cap,
}
