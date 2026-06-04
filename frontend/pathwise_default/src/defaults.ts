// The frontend is the single source of truth for *user-definable* model config.
// These defaults seed the scenario the user edits and sends with each run; the
// backend never supplies them.

import type { Scenario } from "./types";

export function defaultScenario(domain: string): Scenario {
  return {
    name: "scenario",
    domain,
    selection: { target_set: "Tier1" },
    economics: {
      discount_rate: 0.08,
      base_period: 2025,
      capex_convention: "annuity",
      default_measure_lifetime: 15,
      default_newbuild_lifetime: 25,
      currency: "USD",
    },
    features: {
      include_transitions: true,
      include_measures: true,
      include_new_build: true,
      include_carbon_price: true,
      include_capex: true,
    },
    solver: { name: "highs", threads: 4, time_limit_s: 600, mip_gap: 0.01 },
  };
}
