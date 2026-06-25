"""Workbook sheet-name vocabulary — the single source of truth.

Every ``{sheet: rows[]}`` workbook key used anywhere in ``pathwise`` is
declared here as a module-level ``str`` constant. Consumers import these
constants instead of repeating raw string literals, so renaming a sheet
requires one edit here (plus the corresponding migration of any persisted
files) rather than a grep-and-replace across the whole codebase.

Naming convention
-----------------
Constants are ``UPPER_SNAKE_CASE`` and their values are the *exact*
lowercase strings the engine uses.  Wide temporal sheets follow the
PyPSA-style ``<entity>_t__<attribute>`` convention (double underscore
before the attribute) that is already established throughout the codebase.

This module is deliberately **import-free** (no relative imports, no
third-party dependencies) so it can be imported at the top of any file
without risk of circular imports.
"""

from __future__ import annotations

# ── Metadata ──────────────────────────────────────────────────────────────────

#: Key-value pairs stored at the workbook level (label, sector notes, …).
META = "meta"

# ── Unit registry (per-project conversion factors) ────────────────────────────

#: The project's conversion-factor registry — one base-anchored row per unit:
#: ``(unit, dimension, factor_to_base)`` meaning ``1 unit = factor_to_base ×
#: <dimension base>``. Assembled into pint ``unit_overrides`` so a project can
#: set its own rates (e.g. ``KRW = 1/1300 USD``); the dimension bases come from
#: the global ``units.yaml``. Also the closed vocabulary the UI's unit pickers
#: draw from.
UNITS = "units"

# ── Time horizon ──────────────────────────────────────────────────────────────

#: One row per modelled year (``year``, ``duration_years``).
PERIODS = "periods"

# ── Streams (flows) ─────────────────────────────────────────────────────

#: Static flow/stream definitions.
FLOWS = "flows"

#: Long-format per-year price trajectory (flow_id, year, price?, sale_price?).
FLOW_PRICES = "flow_prices"

#: Free-form physical stream properties (flow_id, property, value) — e.g.
#: temperature, voltage, pressure, calorific value. Carried as metadata.
FLOW_PROPERTIES = "flow_properties"

# ── Environmental impacts ─────────────────────────────────────────────────────

#: Static impact definitions (impact_id, unit).
IMPACTS = "impacts"

#: Long-format per-year impact price (impact_id, year, price).
IMPACT_PRICES = "impact_prices"

#: LCIA characterisation: map a base elementary-flow impact to an impact CATEGORY
#: with a factor (flow_impact_id, category_id, factor). The engine derives the
#: category's emission as Σ_flow factor · flow — e.g. (CO2, GWP, 1), (CH4, GWP, 27),
#: (N2O, GWP, 273). A category is any impact_id appearing as a category_id here; it
#: must also be declared in ``impacts`` (with its unit, e.g. kg CO2e).
CHARACTERISATION = "characterisation"

# ── Technologies (process recipes) ───────────────────────────────────────────

#: Static technology definitions (capex, opex, lifespan, …).
TECHNOLOGIES = "technologies"

#: Unified I/O table: one row per (technology, target, role).
IO = "io"

#: Long-format per-year I/O coefficients (technology_id, target, role, year,
#: coefficient) — year-varying intensities / yields / emission factors.
IO_T = "io_t"

#: Legacy technology inputs table (technology_id, flow_id, intensity).
PROCESS_INPUTS = "process_inputs"

#: Legacy technology outputs table (technology_id, flow_id, yield).
PROCESS_OUTPUTS = "process_outputs"

#: Direct process-level impact factors (technology_id, impact_id, factor).
TECH_IMPACTS = "tech_impacts"

#: Per-FACILITY direct impact factors (process_id, impact_id, factor) — added on
#: top of the baseline technology's own direct impact, so two facilities on the
#: same technology can carry different real emission intensities.
PROCESS_IMPACTS = "process_impacts"

#: Year-varying per-facility direct impact (process_id, impact_id, year, factor).
PROCESS_IMPACTS_T = "process_impacts_t"

#: Long-format per-year technology cost trajectory (technology_id, year, capex?, opex?).
TECHNOLOGIES_PRICES = "technologies_prices"

# ── Flow impact factors ──────────────────────────────────────────────────

#: Static per-unit stream emission/impact factors (flow_id, impact_id, factor).
FLOW_IMPACTS = "flow_impacts"

#: Year-varying stream emission/impact factors (flow_id, impact_id, year, factor).
FLOW_IMPACTS_T = "flow_impacts_t"

# ── Facilities (process instances) ───────────────────────────────────────────

#: Flat facility/process instances (process_id, company, baseline_technology, …).
PROCESSES = "processes"

#: Technology compatibility + transition routes (from_technology, to_technology, …).
TRANSITIONS = "transitions"

#: Fleet-wide adoption caps (technology_id, max_count) — at most N processes may
#: run a technology in any one year.
TECHNOLOGY_CAPS = "technology_caps"

#: Fleet asset class (Layer 1b): a pool of interchangeable carriers —
#: (fleet_id, company, mode, fuel, cargo, efficiency, capacity, count, build_year,
#: close_year, lifespan). Legacy per-year availability rows (archetype/year/
#: available) are still accepted.
FLEET = "fleet"

#: Fleet→route assignment (Layer 1b): makes a transport process fleet-managed —
#: (process, fleet_id, share?, min_units, max_units). Its throughput is bounded by
#: units·capacity (route ``share`` overrides the fleet's capacity) and its units
#: draw on the fleet's shared lifecycle pool.
FLEET_ROUTES = "fleet_routes"

#: Fleet ownership hierarchy (the transport layer's OWN tree, separate from the
#: facility `nodes`): (group_id, parent_id, label, level). A fleet's ``group`` points
#: here. UI/serialization only — the engine reads fleets from `fleet` by id.
FLEET_GROUPS = "fleet_groups"

#: Physical route geography (Layer 1c): (process, from_node, to_node, mode,
#: distance). Distance drives per-carrier capacity; blank distance is derived from
#: the endpoints' lon/lat via :mod:`pathwise.routing` (sea = searoute, land =
#: great-circle × mode factor).
ROUTES = "routes"

#: Maritime chokepoint risk (Layer 1c+): (corridor, disruption_prob[, toll][, blocked]).
#: Each maritime chokepoint (suez / ormuz=Hormuz / panama / malacca / …) carries an
#: annual closure probability in [0, 1]. ``disruption_prob >= 1`` (100% = "assume shut")
#: — or the legacy boolean ``blocked`` — closes the passage in the BASE solve, so every
#: sea route through it reroutes (longer, costlier, more fuel/emissions) or becomes
#: infeasible. A sub-100% probability is a sensitivity input only (the chokepoint-risk
#: panel weights each corridor's detour exposure by it); it never alters the base solve.
#: ``toll`` is a per-voyage transit fee [currency/voyage] charged on every route that
#: traverses the corridor (priced as toll·legflow/ship_size); independent of probability.
CORRIDORS = "corridors"

#: Long-format per-year transition capex (from_technology, to_technology, year,
#: capex_per_capacity).
TRANSITIONS_T = "transitions_t"

#: Company-level objective configuration (cost vs. profit).
COMPANY_CONFIG = "company_config"

# ── Node hierarchy (optional — replaces flat processes/edges) ─────────────────

#: Recursive node tree rows (node_id, parent_id, kind, level, label, order,
#: phase?). The optional ``phase`` tag (materials | manufacturing | use |
#: end-of-life) rolls a node's emissions up by lifecycle phase in the simulate
#: LCA (inherited by descendants); used by the LCA interpretation view.
NODES = "nodes"

#: Leaf-asset detail rows (asset_id, baseline_technology, capacity, …).
ASSETS = "assets"

#: Directed flow flows between sibling nodes (from_node, to_node, flow_id,
#: lag_years, min_flow, max_flow). Optional spatial-transport physics per stream
#: (opt-in; untagged links stay free): ``freight_cost`` [currency/unit] and
#: ``freight_energy`` [energy/unit] columns on the flow; per-impact freight emissions
#: live in ``link_impacts`` (impact-agnostic — any/all impacts, no hardcoded CO₂).
LINKS = "links"

#: Per-impact freight emissions on a connection (from_node, to_node, flow_id,
#: impact_id, factor [impact unit / flow unit]). Mirrors ``flow_impacts``;
#: priced at each impact's own price in the objective. No privileged impact.
LINK_IMPACTS = "link_impacts"

#: Long-format per-year connection flow bounds (from_node, to_node, flow_id,
#: year, min_flow, max_flow) — the node-space counterpart of ``edges_t``.
LINKS_T = "links_t"

#: Boundary ports exposed by group nodes (node_id, flow_id, direction, …).
PORTS = "ports"

#: 2-D layout of process/node cards for the canvas UI (id, x, y).
NODE_LAYOUT = "node_layout"

# ── Edges (flat-model wiring) ─────────────────────────────────────────────────

#: Directed flow flows between flat processes (from_process, to_process,
#: flow_id, min_flow, max_flow, lag_years). Optional spatial-transport physics
#: per edge: ``freight_cost`` / ``freight_energy`` columns; per-impact freight
#: emissions live in ``edge_impacts`` (see LINKS / LINK_IMPACTS).
EDGES = "edges"

#: Per-impact freight emissions on a flat edge (from_process, to_process,
#: flow_id, impact_id, factor) — the flat-model counterpart of LINK_IMPACTS.
EDGE_IMPACTS = "edge_impacts"

#: Long-format per-year edge capacity (from_process, to_process, flow_id,
#: year, max_flow).
EDGES_T = "edges_t"

# ── Levers and MACCs ─────────────────────────────────────────────────────────

#: Individual retrofit lever definitions (lever_id, type, target, …).
LEVERS = "levers"

#: Piecewise cost-curve blocks for each lever (lever_id, block, reduction, …).
LEVER_BLOCKS = "lever_blocks"

#: Long-format per-year block-cost trajectory (lever_id, block, year, capex?, opex?).
LEVER_BLOCKS_T = "lever_blocks_t"

#: MACC bundle membership: which levers belong to which named MACC
#: (macc, lever_id).
MACCS = "maccs"

#: MACC deployment links: which facilities/technologies a MACC applies to
#: (macc, facility?, technology?, flow?, storage?).
MACC_LINKS = "macc_links"

#: Legacy named-set membership for levers (set, applies_to).
LEVER_LINKS = "lever_links"


# ── Storage ───────────────────────────────────────────────────────────────────

#: Inter-year flow stores (storage_id, flow_id, company, …).
STORAGE = "storage"

#: Wide temporal store build cost / O&M / efficiencies (keyed by storage_id).
STORAGE_T_CAPEX = "storage_t__capex_per_capacity"
STORAGE_T_FIXED_OPEX = "storage_t__fixed_opex_per_capacity"
STORAGE_T_CHARGE_EFFICIENCY = "storage_t__charge_efficiency"
STORAGE_T_DISCHARGE_EFFICIENCY = "storage_t__discharge_efficiency"
STORAGE_T_STANDING_LOSS = "storage_t__standing_loss"

# ── Markets ───────────────────────────────────────────────────────────────────

#: Market definitions — flow supply or ETS (market_id, target, …).
MARKETS = "markets"

#: Long-format per-year market price trajectory (market_id, year, price?, sell_price?, …).
MARKET_PRICES = "market_prices"

# ── Constraints ───────────────────────────────────────────────────────────────

#: Per-year product demand requirements (company, flow_id, year, amount).
DEMAND = "demand"

#: Per-year investment budget limits (company, year?, limit?).
INVESTMENT_BUDGET = "investment_budget"

#: Per-year minimum production floors (company, flow_id, year?, amount?).
MIN_PRODUCTION = "min_production"

#: Per-year maximum production ceilings (company, flow_id, year?, amount?).
MAX_PRODUCTION = "max_production"

#: Per-asset minimum consumption / required offtake (company, flow_id, year?, amount?).
MIN_CONSUMPTION = "min_consumption"

#: Per-asset maximum consumption / max purchase (company, flow_id, year?, amount?).
MAX_CONSUMPTION = "max_consumption"

#: Per-year environmental impact caps (company, impact_id, year?, limit?, soft?, …).
IMPACT_CAPS = "impact_caps"

# ── Component library (round-trip sheets for ComponentLibrary) ────────────────

#: Legacy composite-asset components (name, label, technology, capacity, …).
GROUPS = "groups"

# ── PyPSA-style wide temporal sheets (entity × year matrix) ───────────────────
# Sheet names follow the convention ``<entity>_t__<attribute>`` (double
# underscore separates entity base name from the varying attribute).

#: Wide temporal flow purchase prices (year column + one column per flow).
FLOWS_T_PRICE = "flows_t__price"

#: Wide temporal flow sale prices.
FLOWS_T_SALE_PRICE = "flows_t__sale_price"

#: Wide temporal flow maximum-purchase caps.
FLOWS_T_MAX_PURCHASE = "flows_t__max_purchase"

#: Wide temporal impact prices.
IMPACTS_T_PRICE = "impacts_t__price"

#: Wide temporal technology replacement capex.
TECHNOLOGIES_T_CAPEX = "technologies_t__capex"

#: Wide temporal technology fixed O&M.
TECHNOLOGIES_T_OPEX = "technologies_t__opex"

#: Wide temporal technology renewal cost.
TECHNOLOGIES_T_RENEWAL = "technologies_t__renewal"

#: Wide temporal technology must-run capacity-factor floor.
TECHNOLOGIES_T_MIN_CF = "technologies_t__min_capacity_factor"

#: Wide temporal market buy prices.
MARKETS_T_PRICE = "markets_t__price"

#: Wide temporal market sell prices.
MARKETS_T_SELL_PRICE = "markets_t__sell_price"

#: Wide temporal ETS allocations.
MARKETS_T_ALLOCATION = "markets_t__allocation"

#: Wide temporal facility/process capacity overrides.
PROCESSES_T_CAPACITY = "processes_t__capacity"

#: Wide temporal facility fixed-O&M overrides.
PROCESSES_T_FIXED_OPEX = "processes_t__fixed_opex"

#: Wide temporal facility forced-outage (failure-rate) overrides.
PROCESSES_T_FAILURE_RATE = "processes_t__failure_rate"

#: Wide temporal per-asset utilisation-ceiling (max capacity factor) overrides.
PROCESSES_T_MAX_CF = "processes_t__max_capacity_factor"

#: Wide temporal market buy-volume caps.
MARKETS_T_MAX_BUY = "markets_t__max_buy"

#: Wide temporal market sell-volume caps.
MARKETS_T_MAX_SELL = "markets_t__max_sell"

#: Wide temporal investment-budget limits.
INVESTMENT_BUDGET_T_LIMIT = "investment_budget_t__limit"

#: Wide temporal minimum-production amounts.
MIN_PRODUCTION_T_AMOUNT = "min_production_t__amount"

#: Wide temporal maximum-production amounts.
MAX_PRODUCTION_T_AMOUNT = "max_production_t__amount"

#: Wide temporal minimum-consumption amounts.
MIN_CONSUMPTION_T_AMOUNT = "min_consumption_t__amount"

#: Wide temporal maximum-consumption amounts.
MAX_CONSUMPTION_T_AMOUNT = "max_consumption_t__amount"

#: Wide temporal demand amounts.
DEMAND_T_AMOUNT = "demand_t__amount"

#: Wide temporal impact-cap limits.
IMPACT_CAPS_T_LIMIT = "impact_caps_t__limit"

# ── Simulate variants (model-resident what-if scenarios) ──────────────────────
# Consumed ONLY by the ``simulate`` backend; the optimiser ignores both sheets.

#: Named what-if variants (variant_id, label, description?).
VARIANTS = "variants"

#: Timed interventions per variant: one row per edit
#: (variant_id, kind, target, value, forced_year, field?).
#: ``tech`` → force ``target`` asset onto technology ``value`` from ``forced_year``;
#: ``stream`` → set flow ``target`` price to ``value`` from ``forced_year``;
#: ``lever`` → toggle lever ``target`` (``value`` truthy = on);
#: ``tech_cost`` → set technology ``target``'s ``field`` (capex|opex) to ``value``;
#: ``io_coef`` → set technology ``target``'s coefficient for flow ``field``;
#: ``stream_cap`` → set flow ``target``'s ``field`` (max_purchase|
#: available_from|available_to) to ``value``.
VARIANT_INTERVENTIONS = "variant_interventions"
