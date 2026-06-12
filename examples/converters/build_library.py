"""Extract facility/chain templates from the example workbooks into the library.

Groups each example's facilities by baseline technology into facility
ARCHETYPES (one template per recipe; alternatives = its transition targets),
derives a per-sector process chain from the flow depth of the archetypes, and
writes ``frontend/pathwise/public/library/<sector>.json``. Rerunnable whenever
the examples change. The hand-authored sectors (aluminium + literature-based
files) are left untouched; this script owns steel / shipping / petrochemical.

Run:  uv run python examples/converters/build_library.py
"""

from __future__ import annotations

import json
import math
import sys
import unicodedata
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from pathwise.data.library import SectorLibrary

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "frontend/pathwise/public/examples"
OUT_DIR = ROOT / "frontend/pathwise/public/library"
REPO = "https://github.com/PLANiT-Institute/pathwise/blob/main/examples/converters"

# (sector, example file, converter, dataset note, baseline-tech filter)
SECTORS: list[dict[str, Any]] = [
    {
        "sector": "steel",
        "label": "Steel",
        "file": "steel.xlsx",
        "converter": "steel.py",
        "dataset": "PLANiT MACC steel dataset (Korea), via the pathwise steel converter",
        "keep": lambda tech: True,
    },
    {
        "sector": "shipping",
        "label": "Shipping",
        "file": "shipping.xlsx",
        "converter": "shipping.py",
        "dataset": "Clarkson fleet data + fuel specs, via the pathwise shipping converter",
        "keep": lambda tech: True,
    },
    {
        "sector": "petrochemical",
        "label": "Petrochemical",
        "file": "petrochemical.xlsx",
        "converter": "petrochemical.py",
        "dataset": "PLANiT MACC petrochemical dataset (Korea), via the pathwise converter",
        # The 40+ per-product utility archetypes would drown the library — keep
        # the cracker and BTX trains (the decarbonisation-relevant recipes).
        "keep": lambda tech: "[Utility]" not in tech,
    },
]


def _slug(name: str) -> str:
    norm = unicodedata.normalize("NFKD", name)
    out = "".join(c.lower() if c.isalnum() else "_" for c in norm)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _rows(xl: pd.ExcelFile, sheet: str) -> list[dict[str, Any]]:
    if sheet not in xl.sheet_names:
        return []
    return xl.parse(sheet).to_dict(orient="records")  # type: ignore[no-any-return]


def _io_of(io_rows: list[dict[str, Any]], tech: str) -> list[dict[str, Any]]:
    out = []
    for r in io_rows:
        if str(r.get("technology_id")) != tech:
            continue
        coef = _num(r.get("coefficient"))
        row: dict[str, Any] = {
            "target": str(r.get("target")),
            "role": str(r.get("role") or "input"),
            "coefficient": coef if coef is not None else 0.0,
        }
        if bool(r.get("is_product")) and str(r.get("is_product")).lower() not in ("nan", "false"):
            row["is_product"] = True
        g = r.get("group")
        if g is not None and str(g) not in ("", "nan"):
            row["group"] = str(g)
            lo, hi = _num(r.get("share_min")), _num(r.get("share_max"))
            row["share_min"] = lo if lo is not None else 0.0
            row["share_max"] = hi if hi is not None else 1.0
        out.append(row)
    return out


def build_sector(spec: dict[str, Any]) -> dict[str, Any]:
    """Extract one sector's archetypes + chain from its example workbook."""
    xl = pd.ExcelFile(EXAMPLES / spec["file"])
    techs = {str(r.get("technology_id")): r for r in _rows(xl, "technologies")}
    io_rows = _rows(xl, "io")
    procs = _rows(xl, "processes")
    comms = {str(r.get("commodity_id")): r for r in _rows(xl, "commodities")}
    transitions = _rows(xl, "transitions")

    source = {
        "name": spec["dataset"],
        "url": f"{REPO}/{spec['converter']}",
        "year": 2026,
        "region": "KR" if "PLANiT" in spec["dataset"] else "global",
        "basis": "sector-model extraction",
        "notes": "Extracted from the pathwise example workbook; see the converter for provenance.",
    }

    def tech_template(tech_id: str) -> dict[str, Any] | None:
        t = techs.get(tech_id)
        io = _io_of(io_rows, tech_id)
        if t is None or not io:
            return None
        lifespan = _num(t.get("lifespan"))
        return {
            "technology_id": tech_id,
            "lifespan": int(lifespan) if lifespan else 20,
            "capex": _num(t.get("capex")) or 0.0,
            "opex": _num(t.get("opex")) or 0.0,
            "io": io,
        }

    baselines = sorted(
        {str(p.get("baseline_technology")) for p in procs} & {k for k in techs if spec["keep"](k)}
    )
    facilities: list[dict[str, Any]] = []
    referenced: set[str] = set()
    for base in baselines:
        base_t = tech_template(base)
        if base_t is None:
            continue
        alts = []
        for tr in transitions:
            if str(tr.get("from_technology")) != base:
                continue
            alt_t = tech_template(str(tr.get("to_technology")))
            if alt_t is None:
                continue
            alts.append(
                {
                    "technology": alt_t,
                    "transition_capex_per_capacity": _num(tr.get("capex_per_capacity")) or 0.0,
                }
            )
        caps = [
            c
            for p in procs
            if str(p.get("baseline_technology")) == base
            for c in [_num(p.get("capacity"))]
            if c
        ]
        for t in [base_t, *(a["technology"] for a in alts)]:
            referenced |= {r["target"] for r in t["io"] if r["role"] != "impact"}
        facilities.append(
            {
                "facility_id": _slug(base),
                "label": base,
                "description": f"{spec['label']} archetype extracted from the example model "
                f"(baseline of {len(caps)} facilit{'y' if len(caps) == 1 else 'ies'}).",
                "technology": base_t,
                "alternatives": alts,
                "default_capacity": round(median(caps), 3) if caps else 1000.0,
                "source": source,
            }
        )

    commodities = []
    for cid in sorted(referenced):
        c = comms.get(cid, {})
        row: dict[str, Any] = {
            "commodity_id": cid,
            "kind": str(c.get("kind") or "material"),
            "unit": str(c.get("unit") or "unit"),
        }
        if (p := _num(c.get("price"))) is not None:
            row["price"] = p
        if (sp := _num(c.get("sale_price"))) is not None:
            row["sale_price"] = sp
        commodities.append(row)

    chains = _derive_chain(spec, facilities)
    return {
        "sector": spec["sector"],
        "label": spec["label"],
        "commodities": commodities,
        "facilities": facilities,
        "chains": chains,
    }


def _derive_chain(spec: dict[str, Any], facilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order archetypes by flow depth into a single representative chain."""
    outs = {
        f["facility_id"]: {r["target"] for r in f["technology"]["io"] if r["role"] == "output"}
        for f in facilities
    }
    ins = {
        f["facility_id"]: {r["target"] for r in f["technology"]["io"] if r["role"] == "input"}
        for f in facilities
    }

    def depth(fid: str, seen: frozenset[str] = frozenset()) -> int:
        if fid in seen:
            return 0
        ups = [u for u in outs if u != fid and (outs[u] & ins[fid])]
        return max((depth(u, seen | {fid}) + 1 for u in ups), default=0)

    by_depth: dict[int, list[str]] = {}
    for f in facilities:
        by_depth.setdefault(depth(f["facility_id"]), []).append(f["facility_id"])
    if len(by_depth) < 2:
        return []  # single-stage sector — no chain to predefine

    stages: list[dict[str, Any]] = []
    for d in sorted(by_depth):
        for fid in sorted(by_depth[d]):
            feeds = sorted(
                u for prev_d in range(d) for u in by_depth.get(prev_d, []) if outs[u] & ins[fid]
            )
            stages.append({"facility": fid, "feeds": feeds})

    last = next(f for f in facilities if f["facility_id"] == stages[-1]["facility"])
    products = [
        r["target"]
        for r in last["technology"]["io"]
        if r["role"] == "output" and (r.get("is_product") or True)
    ]
    chain = {
        "chain_id": f"{spec['sector']}_chain",
        "label": f"{spec['label']} route ({len(stages)} stages)",
        "description": "Representative end-to-end route extracted from the example model.",
        "stages": stages,
        "source": {
            "name": spec["dataset"],
            "url": f"{REPO}/{spec['converter']}",
            "year": 2026,
            "region": "KR" if "PLANiT" in spec["dataset"] else "global",
            "basis": "sector-model extraction",
        },
    }
    if products:
        cap = float(last["default_capacity"])
        chain["demand_hint"] = {"commodity_id": products[0], "amount": round(cap * 0.5, 3)}
    return [chain]


def main() -> None:
    for spec in SECTORS:
        data = build_sector(spec)
        SectorLibrary.model_validate(data)  # enforce the contract (incl. references)
        out = OUT_DIR / f"{spec['sector']}.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(
            f"[{spec['sector']}] {len(data['facilities'])} facilities, "
            f"{len(data['chains'])} chain(s) → {out.name}"
        )

    # Refresh the index: extracted sectors + any hand-authored files present.
    entries = []
    for path in sorted(OUT_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        lib = json.loads(path.read_text(encoding="utf-8"))
        entries.append(
            {
                "sector": lib["sector"],
                "label": lib["label"],
                "file": path.name,
                "description": f"{len(lib['facilities'])} facility template(s)"
                + (f", {len(lib.get('chains', []))} chain(s)" if lib.get("chains") else ""),
            }
        )
    (OUT_DIR / "index.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[index] {len(entries)} sectors")


if __name__ == "__main__":
    main()
