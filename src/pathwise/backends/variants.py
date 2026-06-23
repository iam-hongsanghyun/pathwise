"""Compile model-resident **variants** into engine inputs — shared by both backends.

A variant (authored in the value chain, stored in the ``variants`` +
``variant_interventions`` sheets) is a named bundle of timed interventions. Both
the optimiser (``linopy``) and the simulator consume the *same* variant: a ``tech``
intervention becomes a **forced timed switch** (``Problem.forced_switches``), and
``stream`` / ``measure`` interventions become workbook **overrides** (see
:mod:`pathwise.backends.overrides`). The optimiser forces a *selected* variant and
optimises the rest; the simulator evaluates every variant against the baseline.
"""

from __future__ import annotations

from typing import Any

from pathwise.backends.overrides import apply_overrides
from pathwise.data.workbook import Workbook


def read_model_variants(model: Workbook) -> list[dict[str, Any]]:
    """Compile the ``variants`` + ``variant_interventions`` sheets into variant
    dicts ``{variant_id, label, overrides, forced}``.

    A ``tech`` intervention becomes a forced timed switch ``forced[machine] =
    (to_tech, year)`` (default year = the first modelled year — a whole-horizon
    swap — when ``forced_year`` is blank); a ``stream`` intervention a ``set_price``
    override; a ``measure`` intervention a ``toggle_measure`` override. Returns
    ``[]`` when the model defines no variant interventions.
    """
    interventions = model.get("variant_interventions", [])
    if not interventions:
        return []
    years = sorted(int(p["year"]) for p in model.get("periods", []) if p.get("year") is not None)
    first_year = years[0] if years else 0
    labels = {
        str(v.get("variant_id")): str(v.get("label") or v.get("variant_id"))
        for v in model.get("variants", [])
    }

    compiled: dict[str, dict[str, Any]] = {}
    for r in interventions:
        vid = str(r.get("variant_id") or "")
        if not vid:
            continue
        slot = compiled.setdefault(vid, {"overrides": [], "forced": {}})
        kind, target, value = str(r.get("kind") or ""), str(r.get("target") or ""), r.get("value")
        year = int(r["forced_year"]) if r.get("forced_year") not in (None, "") else first_year
        if kind == "tech" and target and value not in (None, ""):
            slot["forced"][target] = (str(value), year)
        elif kind == "stream" and target and value not in (None, ""):
            ov: dict[str, Any] = {
                "op": "set_price",
                "commodity": target,
                "price": float(value or 0.0),
            }
            if r.get("forced_year") not in (None, ""):
                ov["year"] = year
            slot["overrides"].append(ov)
        elif kind == "measure" and target:
            on = str(value).strip().lower() not in ("0", "false", "off", "no", "")
            slot["overrides"].append({"op": "toggle_measure", "measure": target, "on": on})
    return [
        {
            "variant_id": vid,
            "label": labels.get(vid, vid),
            "overrides": s["overrides"],
            "forced": s["forced"],
        }
        for vid, s in compiled.items()
    ]


def find_variant(model: Workbook, variant_id: str) -> dict[str, Any] | None:
    """The compiled variant with ``variant_id``, or ``None`` if absent."""
    vid = str(variant_id)
    return next((v for v in read_model_variants(model) if v["variant_id"] == vid), None)


def compile_variant(
    base: Workbook,
    variant: dict[str, Any],
    *,
    source: Workbook | None = None,
) -> tuple[Workbook, dict[str, tuple[str, int]]]:
    """Apply a variant's overrides to ``base`` and return ``(edited, forced)``.

    ``source`` (default ``base``) is where ``toggle_measure on`` pulls a stripped
    measure back from — the simulator passes the full model while evaluating its
    *as-is* (stripped) view.

    Returns:
        The edited workbook and the forced-switch map ``{machine: (to_tech, year)}``.
    """
    edited = apply_overrides(base, variant.get("overrides") or [], source=source)
    forced: dict[str, tuple[str, int]] = dict(variant.get("forced") or {})
    return edited, forced
