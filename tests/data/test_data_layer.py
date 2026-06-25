"""P1 data layer: workbook round-trip, assembly, validation."""

from __future__ import annotations

import copy

from pathwise.core.entities import CommodityKind, LeverType
from pathwise.data import ScenarioConfig, assemble_problem, validate
from pathwise.data.workbook import frames_to_workbook, workbook_to_frames
from tests.data.example import example_workbook


def _scenario() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025}})


def test_workbook_frames_round_trip() -> None:
    wb = example_workbook()
    again = frames_to_workbook(workbook_to_frames(wb))
    assert set(again) == set(wb)
    assert len(again["processes"]) == len(wb["processes"])
    assert {r["commodity_id"] for r in again["commodities"]} == {
        r["commodity_id"] for r in wb["commodities"]
    }


def test_assemble_builds_problem() -> None:
    prob = assemble_problem(example_workbook(), _scenario())
    assert prob.years == [2025, 2030]
    assert prob.base_year == 2025
    assert prob.companies == ["Acme"]
    assert set(prob.technologies) == {"BF", "EAF"}
    assert prob.commodities["coal"].kind == CommodityKind.ENERGY
    assert prob.commodities["coal"].price(2025) == 30.0
    # Per-tech inputs/outputs land on the technology.
    assert prob.technologies["BF"].input_intensity["coal"] == 4.0
    assert prob.technologies["BF"].output_yield["iron"] == 1.0
    assert prob.technologies["BF"].direct_impact["CO2"] == 1.2
    # Impact price trajectory interpolated onto modelled years.
    assert prob.impacts["CO2"].price(2025) == 50.0
    assert prob.impacts["CO2"].price(2030) == 120.0
    # Lever typed with its block.
    assert len(prob.levers) == 1
    assert prob.levers[0].lever_type == LeverType.ENERGY_EFFICIENCY
    assert prob.levers[0].blocks[0].reduction == 0.1
    # Network + demand.
    assert len(prob.edges) == 1 and prob.edges[0].commodity_id == "iron"
    assert len(prob.transitions) == 1
    assert prob.transitions[0].to_technology == "EAF" and prob.transitions[0].compatible
    assert prob.demand[("Acme", "steel", 2030)] == 900.0
    assert prob.impact_caps[("all", "CO2", 2030)] == 5000.0


def test_assemble_respects_horizon() -> None:
    sc = ScenarioConfig.from_dict({"horizon": {"start": 2030}})
    prob = assemble_problem(example_workbook(), sc)
    assert prob.years == [2030]


def test_validation_passes_on_good_workbook() -> None:
    report = validate(example_workbook())
    assert report.ok, report.errors


def test_validation_flags_missing_sheet() -> None:
    wb = copy.deepcopy(example_workbook())
    del wb["processes"]
    report = validate(wb)
    assert not report.ok
    assert any("processes" in e for e in report.errors)


def test_validation_flags_bad_reference() -> None:
    wb = copy.deepcopy(example_workbook())
    wb["processes"][0]["baseline_technology"] = "NOPE"
    report = validate(wb)
    assert not report.ok
    assert any("NOPE" in e for e in report.errors)
