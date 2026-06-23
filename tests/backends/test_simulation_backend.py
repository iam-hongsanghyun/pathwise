"""Simulation backend: evaluate a pinned configuration's lifecycle inventory.

The simulator is a *what-if / LCA* lens over the same value-chain model (not a new
schema): it pins the configuration, evaluates it, and decomposes the emissions by
value-chain stage. The minimal model below has hand-computable emissions; the
green-steel case guards it on a realistic multi-stage chain.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from pathwise.api.workbook_io import parse_sqlite
from pathwise.backends.registry import available_backends, get_backend
from pathwise.backends.simulation_backend import SimulationBackend


def _two_stage_model() -> dict:
    """Steel maker (ore→steel, 2 tCO2/t) → car maker (steel→car, 0.5 tCO2/car).

    100 cars ⇒ 100 steel ⇒ steel stage emits 200, auto stage emits 50, total 250.
    """
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "ore", "kind": "material", "unit": "t", "price": 10},
            {"commodity_id": "steel", "kind": "material", "unit": "t"},
            {"commodity_id": "car", "kind": "product", "unit": "veh"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "technologies": [
            {"technology_id": "SteelMaker", "actions": "continue"},
            {"technology_id": "CarMaker", "actions": "continue"},
        ],
        "nodes": [
            {"node_id": "steelco", "kind": "group", "level": "company", "label": "Steel"},
            {
                "node_id": "steelco/sm",
                "kind": "machine",
                "level": "machine",
                "parent_id": "steelco",
            },
            {"node_id": "autoco", "kind": "group", "level": "company", "label": "Auto"},
            {"node_id": "autoco/cm", "kind": "machine", "level": "machine", "parent_id": "autoco"},
        ],
        "machines": [
            {"machine_id": "steelco/sm", "baseline_technology": "SteelMaker", "capacity": 1000},
            {"machine_id": "autoco/cm", "baseline_technology": "CarMaker", "capacity": 1000},
        ],
        "io": [
            {"technology_id": "SteelMaker", "target": "ore", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "SteelMaker",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "SteelMaker", "target": "CO2", "role": "impact", "coefficient": 2.0},
            {"technology_id": "CarMaker", "target": "steel", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "CarMaker",
                "target": "car",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "CarMaker", "target": "CO2", "role": "impact", "coefficient": 0.5},
        ],
        "connections": [{"from_node": "steelco", "to_node": "autoco", "commodity_id": "steel"}],
        "demand": [{"company": "autoco", "commodity_id": "car", "year": 2025, "amount": 100}],
    }


_SCENARIO = {"economics": {"base_year": 2025, "discount_rate": 0.0}}


def _two_stage_with_green() -> dict:
    """``_two_stage_model`` plus a cleaner steel route the simulator can pin to.

    ``GreenSteelMaker`` makes steel from ore at 0.5 tCO2/t (vs 2.0) but costs an
    extra $5/t in opex — so switching to it abates emissions at a known $/t.
    """
    m = _two_stage_model()
    m["technologies"].append({"technology_id": "GreenSteelMaker", "actions": "continue", "opex": 5})
    m["io"].extend(
        [
            {
                "technology_id": "GreenSteelMaker",
                "target": "ore",
                "role": "input",
                "coefficient": 1.0,
            },
            {
                "technology_id": "GreenSteelMaker",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {
                "technology_id": "GreenSteelMaker",
                "target": "CO2",
                "role": "impact",
                "coefficient": 0.5,
            },
        ]
    )
    return m


def test_simulate_backend_is_registered() -> None:
    names = {b["name"] for b in available_backends()}
    assert "simulate" in names
    assert get_backend("simulate").name == "simulate"


def test_variant_comparison_abatement_and_breakeven() -> None:
    """Switching the steel mill to the green route abates CO2 at a known $/t."""
    model = _two_stage_with_green()
    scenario = {
        **_SCENARIO,
        "simulate": {
            "variants": [
                {
                    "label": "green steel",
                    "overrides": [
                        {
                            "op": "set_machine_tech",
                            "machine": "steelco/sm",
                            "technology": "GreenSteelMaker",
                        }
                    ],
                }
            ]
        },
    }
    res = SimulationBackend().run(model, scenario)
    assert res["status"] == "optimal"

    # Baseline LCA is unchanged from the as-is run (250 tCO2 total).
    base_co2 = next(d for d in res["outputs"]["lca"]["by_impact"] if d["impact"] == "CO2")
    assert base_co2["total"] == pytest.approx(250.0)

    # The variant's own inventory: steel 100×0.5 + auto 100×0.5 = 100 tCO2.
    variant = res["outputs"]["variants"][0]
    assert variant["status"] == "optimal"
    var_co2 = next(d for d in variant["lca"]["by_impact"] if d["impact"] == "CO2")
    assert var_co2["total"] == pytest.approx(100.0)

    comp = res["outputs"]["comparison"][0]
    assert comp["label"] == "green steel"
    assert comp["impact"] == "CO2"
    # 250 - 100 = 150 tCO2 abated; the green route adds 100 t × $5 = $500 of opex.
    assert comp["abatement"] == pytest.approx(150.0)
    assert comp["cost_delta"] == pytest.approx(500.0)
    # $500 / 150 t = $3.33/t — and the same carbon price breaks the choice even.
    assert comp["abatement_cost_per_unit"] == pytest.approx(500.0 / 150.0)
    assert comp["breakeven_carbon_price"] == pytest.approx(500.0 / 150.0)


def test_set_price_override_changes_cost_not_emissions() -> None:
    """A pure price override moves cost (and break-even) but not the inventory."""
    model = _two_stage_with_green()
    scenario = {
        **_SCENARIO,
        "simulate": {
            "variants": [
                {
                    "label": "cheap ore",
                    "overrides": [{"op": "set_price", "commodity": "ore", "price": 2}],
                }
            ]
        },
    }
    res = SimulationBackend().run(model, scenario)
    comp = res["outputs"]["comparison"][0]
    # Same emissions ⇒ no abatement; ore $10→$2 over 100 t saves $800.
    assert comp["abatement"] == pytest.approx(0.0)
    assert comp["cost_delta"] == pytest.approx(-800.0)
    # No abatement ⇒ no carbon price ever flips the choice.
    assert comp["breakeven_carbon_price"] is None


def test_unknown_override_op_is_invalid() -> None:
    scenario = {
        **_SCENARIO,
        "simulate": {"variants": [{"label": "bad", "overrides": [{"op": "nope"}]}]},
    }
    res = SimulationBackend().run(_two_stage_with_green(), scenario)
    assert res["status"] == "invalid"
    assert any("nope" in e for e in res["validation"]["errors"])


def test_policy_sweep_traces_cost_curves() -> None:
    """The carbon-price sweep returns each config's cost(p) and constant emissions."""
    scenario = {
        **_SCENARIO,
        "simulate": {
            "variants": [
                {
                    "label": "green steel",
                    "overrides": [
                        {
                            "op": "set_machine_tech",
                            "machine": "steelco/sm",
                            "technology": "GreenSteelMaker",
                        }
                    ],
                }
            ],
            "policy_sweep": {
                "lever": "carbon_price",
                "impact": "CO2",
                "from": 0,
                "to": 10,
                "step": 5,
            },
        },
    }
    sweep = SimulationBackend().run(_two_stage_with_green(), scenario)["outputs"]["policy_sweep"]
    assert [row["carbon_price"] for row in sweep] == [0.0, 5.0, 10.0]

    def at(price: float, label: str) -> dict:
        row = next(r for r in sweep if r["carbon_price"] == price)
        return next(v for v in row["variants"] if v["label"] == label)

    # Baseline: $1000 ore + 250 tCO2 × p.  Green: $1500 + 100 tCO2 × p.
    assert at(0, "baseline")["cost"] == pytest.approx(1000.0)
    assert at(0, "green steel")["cost"] == pytest.approx(1500.0)
    assert at(10, "baseline")["cost"] == pytest.approx(3500.0)
    assert at(10, "green steel")["cost"] == pytest.approx(2500.0)
    # Pinned configs ⇒ emissions independent of the carbon price.
    assert at(10, "baseline")["emissions"] == pytest.approx(250.0)
    assert at(10, "green steel")["emissions"] == pytest.approx(100.0)


def test_cap_compliance_flags_the_over_config() -> None:
    """A CO2 cap of 150 t/yr: the as-is baseline is over, the green variant complies."""
    model = _two_stage_with_green()
    model["impact_caps"] = [{"company": "steelco", "impact_id": "CO2", "year": 2025, "limit": 150}]
    scenario = {
        **_SCENARIO,
        "simulate": {
            "variants": [
                {
                    "label": "green steel",
                    "overrides": [
                        {
                            "op": "set_machine_tech",
                            "machine": "steelco/sm",
                            "technology": "GreenSteelMaker",
                        }
                    ],
                }
            ]
        },
    }
    compliance = SimulationBackend().run(model, scenario)["outputs"]["cap_compliance"]
    by_label = {c["label"]: c for c in compliance}

    base = by_label["baseline"]
    assert base["compliant"] is False
    assert base["by_year"][0] == {
        "impact": "CO2",
        "year": 2025,
        "emissions": pytest.approx(250.0),
        "cap": pytest.approx(150.0),
        "over": pytest.approx(100.0),
    }
    green = by_label["green steel"]
    assert green["compliant"] is True
    assert green["by_year"][0]["over"] == pytest.approx(0.0)


def _three_stage_with_use() -> dict:
    """Cradle-to-grave chain: ore→steel→car→mobility, the use phase a real process.

    Per the design decision, the use phase is just another value-chain stage: a
    ``UsePhase`` machine consuming the car and emitting 20 tCO2 over its life. With
    100 units of mobility demanded: steel 200 + auto 50 + use 2000 = 2250 tCO2.
    """
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "ore", "kind": "material", "unit": "t", "price": 10},
            {"commodity_id": "steel", "kind": "material", "unit": "t"},
            {"commodity_id": "car", "kind": "product", "unit": "veh"},
            {"commodity_id": "mobility", "kind": "product", "unit": "veh-life"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "technologies": [
            {"technology_id": "SteelMaker", "actions": "continue"},
            {"technology_id": "CarMaker", "actions": "continue"},
            {"technology_id": "UsePhase", "actions": "continue"},
        ],
        "nodes": [
            {"node_id": "steelco", "kind": "group", "level": "company", "label": "Steel"},
            {
                "node_id": "steelco/sm",
                "kind": "machine",
                "level": "machine",
                "parent_id": "steelco",
            },
            {"node_id": "autoco", "kind": "group", "level": "company", "label": "Auto"},
            {"node_id": "autoco/cm", "kind": "machine", "level": "machine", "parent_id": "autoco"},
            {"node_id": "useco", "kind": "group", "level": "company", "label": "Use"},
            {"node_id": "useco/up", "kind": "machine", "level": "machine", "parent_id": "useco"},
        ],
        "machines": [
            {"machine_id": "steelco/sm", "baseline_technology": "SteelMaker", "capacity": 1000},
            {"machine_id": "autoco/cm", "baseline_technology": "CarMaker", "capacity": 1000},
            {"machine_id": "useco/up", "baseline_technology": "UsePhase", "capacity": 1000},
        ],
        "io": [
            {"technology_id": "SteelMaker", "target": "ore", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "SteelMaker",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "SteelMaker", "target": "CO2", "role": "impact", "coefficient": 2.0},
            {"technology_id": "CarMaker", "target": "steel", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "CarMaker",
                "target": "car",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "CarMaker", "target": "CO2", "role": "impact", "coefficient": 0.5},
            {"technology_id": "UsePhase", "target": "car", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "UsePhase",
                "target": "mobility",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "UsePhase", "target": "CO2", "role": "impact", "coefficient": 20.0},
        ],
        "connections": [
            {"from_node": "steelco", "to_node": "autoco", "commodity_id": "steel"},
            {"from_node": "autoco", "to_node": "useco", "commodity_id": "car"},
        ],
        "demand": [{"company": "useco", "commodity_id": "mobility", "year": 2025, "amount": 100}],
    }


def test_use_phase_process_is_a_lifecycle_stage() -> None:
    """A use-phase process needs no engine change — it is just another stage."""
    lca = SimulationBackend().run(_three_stage_with_use(), _SCENARIO)["outputs"]["lca"]
    co2 = next(d for d in lca["by_impact"] if d["impact"] == "CO2")
    assert co2["total"] == pytest.approx(2250.0)

    stages = {d["stage"]: d["total"] for d in lca["by_stage"] if d["impact"] == "CO2"}
    assert stages["steelco"] == pytest.approx(200.0)
    assert stages["autoco"] == pytest.approx(50.0)
    assert stages["useco"] == pytest.approx(2000.0)  # the use phase dominates
    assert sum(stages.values()) == pytest.approx(co2["total"])


def test_lifecycle_inventory_decomposes_by_stage() -> None:
    res = SimulationBackend().run(_two_stage_model(), _SCENARIO)
    assert res["status"] == "optimal"
    lca = res["outputs"]["lca"]

    assert lca["functional_unit"] == {"commodity": "car", "amount": 100.0}

    co2 = next(d for d in lca["by_impact"] if d["impact"] == "CO2")
    assert co2["total"] == pytest.approx(250.0)
    assert co2["per_unit"] == pytest.approx(2.5)

    stages = {(d["stage"], d["impact"]): d["total"] for d in lca["by_stage"]}
    assert stages[("steelco", "CO2")] == pytest.approx(200.0)
    assert stages[("autoco", "CO2")] == pytest.approx(50.0)
    # The per-stage decomposition reconstructs the engine's per-impact total.
    assert sum(v for (_s, i), v in stages.items() if i == "CO2") == pytest.approx(co2["total"])


def test_carbon_cost_uses_the_impact_price() -> None:
    model = _two_stage_model()
    model["impact_prices"] = [{"impact_id": "CO2", "year": 2025, "price": 30}]
    lca = SimulationBackend().run(model, _SCENARIO)["outputs"]["lca"]
    # 250 tCO2 × $30 = $7,500.
    assert lca["cost"]["carbon"] == pytest.approx(7500.0)


@pytest.mark.slow
def test_green_steel_as_is_lifecycle_inventory() -> None:
    """The shipped green-steel example yields a steel-dominated cradle-to-gate LCA."""
    wb = parse_sqlite((files("pathwise.assets.examples") / "green_steel_chain.sqlite").read_bytes())
    res = SimulationBackend().run(
        wb, {"economics": {"base_year": 2025}, "solver": {"mip_gap": 0.05}}
    )
    assert res["status"] == "optimal"
    lca = res["outputs"]["lca"]

    assert lca["functional_unit"]["commodity"] == "car"
    co2 = next(d for d in lca["by_impact"] if d["impact"] == "CO2")
    assert co2["total"] > 0 and co2["per_unit"] > 0

    co2_stages = {d["stage"]: d["total"] for d in lca["by_stage"] if d["impact"] == "CO2"}
    # The integrated steel mill dominates the car's cradle-to-gate footprint.
    assert max(co2_stages, key=lambda s: co2_stages[s]).endswith("kr_steel")
    # The stage decomposition reconstructs the engine's CO2 total.
    assert sum(co2_stages.values()) == pytest.approx(co2["total"], rel=1e-6)


# ── Model-resident variants: forced timed switch + sunk cost (Stage A) ─────────


def _two_period_green() -> dict:
    """Two-period (2025, 2030) green-steel chain: 100 cars/period.

    Per period the steel mill (SteelMaker, 2 tCO2/t) feeds the car maker (0.5
    tCO2/car). Baseline emits 250/period ⇒ 500 total; switching the mill to
    ``GreenSteelMaker`` (0.5 tCO2/t) makes a switched period emit 100.
    """
    return {
        "periods": [
            {"year": 2025, "duration_years": 1},
            {"year": 2030, "duration_years": 1},
        ],
        "commodities": [
            {"commodity_id": "ore", "kind": "material", "unit": "t", "price": 10},
            {"commodity_id": "steel", "kind": "material", "unit": "t"},
            {"commodity_id": "car", "kind": "product", "unit": "veh"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "technologies": [
            {"technology_id": "SteelMaker", "actions": "continue"},
            {"technology_id": "CarMaker", "actions": "continue"},
            {"technology_id": "GreenSteelMaker", "actions": "continue", "opex": 5},
        ],
        "nodes": [
            {"node_id": "steelco", "kind": "group", "level": "company", "label": "Steel"},
            {
                "node_id": "steelco/sm",
                "kind": "machine",
                "level": "machine",
                "parent_id": "steelco",
            },
            {"node_id": "autoco", "kind": "group", "level": "company", "label": "Auto"},
            {"node_id": "autoco/cm", "kind": "machine", "level": "machine", "parent_id": "autoco"},
        ],
        "machines": [
            {"machine_id": "steelco/sm", "baseline_technology": "SteelMaker", "capacity": 1000},
            {"machine_id": "autoco/cm", "baseline_technology": "CarMaker", "capacity": 1000},
        ],
        "io": [
            {"technology_id": "SteelMaker", "target": "ore", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "SteelMaker",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "SteelMaker", "target": "CO2", "role": "impact", "coefficient": 2.0},
            {
                "technology_id": "GreenSteelMaker",
                "target": "ore",
                "role": "input",
                "coefficient": 1.0,
            },
            {
                "technology_id": "GreenSteelMaker",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {
                "technology_id": "GreenSteelMaker",
                "target": "CO2",
                "role": "impact",
                "coefficient": 0.5,
            },
            {"technology_id": "CarMaker", "target": "steel", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "CarMaker",
                "target": "car",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "CarMaker", "target": "CO2", "role": "impact", "coefficient": 0.5},
        ],
        "connections": [{"from_node": "steelco", "to_node": "autoco", "commodity_id": "steel"}],
        "demand": [
            {"company": "autoco", "commodity_id": "car", "year": 2025, "amount": 100},
            {"company": "autoco", "commodity_id": "car", "year": 2030, "amount": 100},
        ],
    }


def test_model_resident_variant_forces_a_mid_horizon_switch() -> None:
    """A `variants`/`variant_interventions` pair drives a forced 2030 switch."""
    model = _two_period_green()
    model["variants"] = [{"variant_id": "green2030", "label": "Green from 2030"}]
    model["variant_interventions"] = [
        {
            "variant_id": "green2030",
            "kind": "tech",
            "target": "steelco/sm",
            "value": "GreenSteelMaker",
            "forced_year": 2030,
        }
    ]
    res = SimulationBackend().run(model, _SCENARIO)
    assert res["status"] == "optimal"

    # Baseline runs SteelMaker both periods: 250 + 250 = 500 tCO2.
    base = next(d for d in res["outputs"]["lca"]["by_impact"] if d["impact"] == "CO2")
    assert base["total"] == pytest.approx(500.0)

    # Variant: 2025 still SteelMaker (250), 2030 switched to green (100) ⇒ 350.
    variant = res["outputs"]["variants"][0]
    assert variant["label"] == "Green from 2030"
    assert variant["status"] == "optimal"
    vco2 = next(d for d in variant["lca"]["by_impact"] if d["impact"] == "CO2")
    assert vco2["total"] == pytest.approx(350.0)

    comp = res["outputs"]["comparison"][0]
    assert comp["abatement"] == pytest.approx(150.0)  # 500 − 350, only 2030 abated


def test_forced_switch_is_timed_per_period() -> None:
    """The switch happens *in* the forced year (2030), not before — per-period proof.

    A whole-horizon swap would emit 100+100=200; no switch 250+250=500; the timed
    2030 switch emits 250 (2025) + 100 (2030). The cap-compliance table exposes the
    variant's per-year emissions, so we assert the timing directly.
    """
    model = _two_period_green()
    model["impact_caps"] = [
        {"company": "steelco", "impact_id": "CO2", "year": 2025, "limit": 1e9},
        {"company": "steelco", "impact_id": "CO2", "year": 2030, "limit": 1e9},
    ]
    model["variants"] = [{"variant_id": "g", "label": "g"}]
    model["variant_interventions"] = [
        {
            "variant_id": "g",
            "kind": "tech",
            "target": "steelco/sm",
            "value": "GreenSteelMaker",
            "forced_year": 2030,
        }
    ]
    compliance = SimulationBackend().run(model, _SCENARIO)["outputs"]["cap_compliance"]
    variant = next(c for c in compliance if c["label"] == "g")
    by_year = {r["year"]: r["emissions"] for r in variant["by_year"]}
    assert by_year[2025] == pytest.approx(250.0)  # still SteelMaker in 2025
    assert by_year[2030] == pytest.approx(100.0)  # GreenSteelMaker from 2030


def test_sunk_cost_of_an_early_forced_switch() -> None:
    """Forcing a switch before end-of-life strands the incumbent's book value."""
    model = _two_period_green()
    # SteelMaker built 2025, $10/unit capex, 10-yr life, 1000 capacity; forced off in 2030.
    model["technologies"][0].update({"capex": 10, "lifespan": 10})
    model["machines"][0]["introduced_year"] = 2025
    model["variants"] = [{"variant_id": "g", "label": "g"}]
    model["variant_interventions"] = [
        {
            "variant_id": "g",
            "kind": "tech",
            "target": "steelco/sm",
            "value": "GreenSteelMaker",
            "forced_year": 2030,
        }
    ]
    lca = SimulationBackend().run(model, _SCENARIO)["outputs"]["variants"][0]["lca"]
    # age = 2030 − 2025 = 5 of 10 yr ⇒ 50% undepreciated; 10 × 1000 × 0.5 = 5000.
    assert lca["cost"]["sunk"] == pytest.approx(5000.0)


def _green_variant_model() -> dict:
    """``_two_period_green`` + a variant forcing the mill to GreenSteelMaker in 2030."""
    m = _two_period_green()
    m["variants"] = [{"variant_id": "g", "label": "g"}]
    m["variant_interventions"] = [
        {
            "variant_id": "g",
            "kind": "tech",
            "target": "steelco/sm",
            "value": "GreenSteelMaker",
            "forced_year": 2030,
        }
    ]
    return m


def test_optimise_ignores_unselected_variants() -> None:
    """With NO variant selected, linopy is identical whether or not the sheets exist."""
    scenario = {"economics": {"base_year": 2025, "discount_rate": 0.0}}
    obj_plain = get_backend("linopy").run(_two_period_green(), scenario)["objective"]
    obj_tagged = get_backend("linopy").run(_green_variant_model(), scenario)["objective"]
    assert obj_tagged == pytest.approx(obj_plain)


def test_optimise_forces_a_selected_variant() -> None:
    """Selecting a variant forces its transition in the optimise run (and costs more).

    With no carbon price, free optimise keeps the (cheaper) baseline mill both
    periods; forcing the green switch in 2030 must run GreenSteelMaker that year —
    raising cost by its $5/t opex (100 t = $500).
    """
    model = _green_variant_model()
    scenario = {"economics": {"base_year": 2025, "discount_rate": 0.0}}
    free = get_backend("linopy").run(model, scenario)
    forced = get_backend("linopy").run(model, {**scenario, "variant": "g"})
    assert free["status"] == "optimal" and forced["status"] == "optimal"

    # Free optimise never touches the green route; forcing it strictly costs more.
    assert forced["objective"] == pytest.approx(free["objective"] + 500.0)
    # The forced run actually runs GreenSteelMaker at the mill in 2030.
    assert any(
        t["technology"] == "GreenSteelMaker"
        and t["process"] == "steelco/sm"
        and t["period"] == 2030
        for t in forced["outputs"]["technology"]
    )
    # 2025 still runs the baseline (timed switch, not a year-0 swap).
    assert any(
        t["technology"] == "SteelMaker" and t["process"] == "steelco/sm" and t["period"] == 2025
        for t in forced["outputs"]["technology"]
    )


def test_phase_rollup() -> None:
    """An optional `phase` tag on company nodes rolls emissions up by lifecycle phase."""
    m = _three_stage_with_use()
    phases = {"steelco": "materials", "autoco": "manufacturing", "useco": "use"}
    for n in m["nodes"]:
        if n["node_id"] in phases:
            n["phase"] = phases[n["node_id"]]
    lca = SimulationBackend().run(m, _SCENARIO)["outputs"]["lca"]
    by_phase = {
        (d["phase"], d["impact"]): d["total"] for d in lca["by_phase"] if d["impact"] == "CO2"
    }
    assert by_phase[("materials", "CO2")] == pytest.approx(200.0)
    assert by_phase[("manufacturing", "CO2")] == pytest.approx(50.0)
    assert by_phase[("use", "CO2")] == pytest.approx(2000.0)  # use phase dominates
