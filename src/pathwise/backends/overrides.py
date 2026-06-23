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
"""

from __future__ import annotations

import copy
from typing import Any

from pathwise.data import sheets
from pathwise.data.workbook import Workbook
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
    impact, price = str(ov.get("impact") or "CO2"), ov.get("price")
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


_OPS = {
    "set_machine_tech": _set_machine_tech,
    "set_price": _set_price,
    "set_carbon_price": _set_carbon_price,
    "toggle_measure": _toggle_measure,
}
