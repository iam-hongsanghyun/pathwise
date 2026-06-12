"""Library contract: every shipped template is valid, referenced, and buildable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem, validate
from pathwise.data.library import SectorLibrary, instantiate_chain, load_sector

LIB_DIR = Path(__file__).resolve().parents[2] / "frontend/pathwise/public/library"
SECTOR_FILES = sorted(p for p in LIB_DIR.glob("*.json") if p.name != "index.json")


def test_index_lists_existing_files() -> None:
    index = json.loads((LIB_DIR / "index.json").read_text(encoding="utf-8"))
    assert index, "library index is empty"
    for entry in index:
        assert {"sector", "label", "file"} <= set(entry), f"index entry incomplete: {entry}"
        assert (LIB_DIR / entry["file"]).exists(), f"missing library file {entry['file']}"


@pytest.mark.parametrize("path", SECTOR_FILES, ids=lambda p: p.stem)
def test_sector_file_is_valid_and_referenced(path: Path) -> None:
    lib = load_sector(path)  # pydantic enforces mandatory source.url on every entry
    declared = {c.commodity_id for c in lib.commodities}
    for f in lib.facilities:
        for tech in [f.technology, *(a.technology for a in f.alternatives)]:
            for r in tech.io:
                if r.role != "impact":
                    assert r.target in declared, (
                        f"{path.name}: '{f.facility_id}' io target '{r.target}' "
                        "is not a declared commodity"
                    )
    facility_ids = {f.facility_id for f in lib.facilities}
    for c in lib.chains:
        for stage in c.stages:
            assert stage.facility in facility_ids, (
                f"{path.name}: chain '{c.chain_id}' references unknown facility '{stage.facility}'"
            )
            for feed in stage.feeds:
                assert feed in facility_ids
    # MACC measures must target something the baseline system actually uses:
    # an input commodity (energy_efficiency) or an emitted impact (otherwise).
    for f in lib.facilities:
        inputs = {r.target for r in f.technology.io if r.role == "input"}
        impacts = {r.target for r in f.technology.io if r.role == "impact"}
        for m in f.measures:
            pool = inputs if m.type == "energy_efficiency" else impacts
            assert m.target in pool, (
                f"{path.name}: '{f.facility_id}' measure '{m.measure_id}' targets "
                f"'{m.target}' which the baseline technology does not "
                f"{'consume' if m.type == 'energy_efficiency' else 'emit'}"
            )


@pytest.mark.parametrize("path", SECTOR_FILES, ids=lambda p: p.stem)
def test_every_chain_solves_optimal(path: Path) -> None:
    lib = load_sector(path)
    for chain in lib.chains:
        wb = instantiate_chain(lib, chain.chain_id)
        report = validate(wb)
        assert report.ok, f"{path.name}/{chain.chain_id}: {report.errors}"
        sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
        res = extract_results(solve(build(assemble_problem(wb, sc))))
        assert res["status"] == "optimal", f"{path.name}/{chain.chain_id}: {res['status']}"
        assert not res["outputs"]["demand_slack"], (
            f"{path.name}/{chain.chain_id}: unmet demand {res['outputs']['demand_slack']}"
        )


def test_measures_stamped_on_insert() -> None:
    # add_facility writes measures + blocks onto the created instance, with the
    # block capex scaled by the instance capacity.
    from pathwise.data.library import add_facility

    cement = next(p for p in SECTOR_FILES if p.stem == "cement")
    lib = load_sector(cement)
    fac = lib.facility("clinker_kiln")
    assert fac.measures, "cement kiln template should carry a MACC measure"
    wb = add_facility({"periods": [{"year": 2025}]}, lib, "clinker_kiln", company="C")
    pid = str(wb["processes"][-1]["process_id"])
    rows = [m for m in wb["measures"] if m["facility"] == pid]
    assert len(rows) == len(fac.measures)
    blocks = [b for b in wb["measure_blocks"] if b["measure_id"] == rows[0]["measure_id"]]
    assert len(blocks) == len(fac.measures[0].blocks)
    expected = fac.measures[0].blocks[0].capex_per_capacity * fac.default_capacity
    assert blocks[0]["capex"] == pytest.approx(expected)


def test_chain_with_measures_still_solves() -> None:
    cement = next(p for p in SECTOR_FILES if p.stem == "cement")
    lib = load_sector(cement)
    wb = instantiate_chain(lib, "cement_chain")
    assert any(wb.get("measures", [])), "chain instance should inherit kiln measures"
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    res = extract_results(solve(build(assemble_problem(wb, sc))))
    assert res["status"] == "optimal"


def test_missing_reference_is_rejected() -> None:
    lib = json.loads((SECTOR_FILES[0]).read_text(encoding="utf-8"))
    del lib["facilities"][0]["source"]
    with pytest.raises(Exception, match="source"):
        SectorLibrary.model_validate(lib)


def test_non_http_reference_is_rejected() -> None:
    lib = json.loads((SECTOR_FILES[0]).read_text(encoding="utf-8"))
    lib["facilities"][0]["source"]["url"] = "see internal memo"
    with pytest.raises(Exception, match="http"):
        SectorLibrary.model_validate(lib)


def test_broken_chain_feed_raises() -> None:
    lib = load_sector(SECTOR_FILES[0])
    # Reverse a chain so a stage feeds from a facility that shares no commodity.
    chain = lib.chains[0]
    if len(chain.stages) < 3:
        pytest.skip("needs a 3-stage chain")
    bad = chain.model_copy(deep=True)
    bad.stages[1].feeds[:] = [chain.stages[-1].facility]  # downstream as feed
    bad_lib = lib.model_copy(deep=True)
    bad_lib.chains[0] = bad
    with pytest.raises(ValueError, match="share no commodity"):
        instantiate_chain(bad_lib, bad.chain_id)


def test_add_replacement_writes_transition_not_facility() -> None:
    from pathwise.data.library import add_facility, add_replacement

    aluminium = next(p for p in SECTOR_FILES if p.stem == "aluminium")
    lib = load_sector(aluminium)
    wb = add_facility({"periods": [{"year": 2025}]}, lib, "alumina_refinery", company="C")
    pid = str(wb["processes"][-1]["process_id"])
    n_procs = len(wb["processes"])

    out = add_replacement(wb, lib, "smelter", pid)
    assert len(out["processes"]) == n_procs, "replacement must not create a facility"
    techs = {str(r["technology_id"]) for r in out["technologies"]}
    assert "Smelt_Grid" in techs, "template technology merged in"
    trans = [
        t
        for t in out["transitions"]
        if str(t["from_technology"]) == "Refine_Gas" and str(t["to_technology"]) == "Smelt_Grid"
    ]
    assert len(trans) == 1, "transition row from the facility's baseline to the template"
    # idempotent: inserting again adds nothing
    again = add_replacement(out, lib, "smelter", pid)
    assert len(again["transitions"]) == len(out["transitions"])


def test_add_replacement_unknown_process_raises() -> None:
    aluminium = next(p for p in SECTOR_FILES if p.stem == "aluminium")
    lib = load_sector(aluminium)
    from pathwise.data.library import add_replacement

    with pytest.raises(KeyError, match="unknown facility"):
        add_replacement({"processes": []}, lib, "smelter", "nope")
