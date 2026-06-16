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

# ── Time horizon ──────────────────────────────────────────────────────────────

#: One row per modelled year (``year``, ``duration_years``).
PERIODS = "periods"

# ── Streams (commodities) ─────────────────────────────────────────────────────

#: Static commodity/stream definitions.
COMMODITIES = "commodities"

#: Long-format per-year price trajectory (commodity_id, year, price?, sale_price?).
COMMODITY_PRICES = "commodity_prices"

#: Free-form physical stream properties (commodity_id, property, value) — e.g.
#: temperature, voltage, pressure, calorific value. Carried as metadata.
COMMODITY_PROPERTIES = "commodity_properties"

# ── Environmental impacts ─────────────────────────────────────────────────────

#: Static impact definitions (impact_id, unit).
IMPACTS = "impacts"

#: Long-format per-year impact price (impact_id, year, price).
IMPACT_PRICES = "impact_prices"

# ── Technologies (process recipes) ───────────────────────────────────────────

#: Static technology definitions (capex, opex, lifespan, …).
TECHNOLOGIES = "technologies"

#: Unified I/O table: one row per (technology, target, role).
IO = "io"

#: Long-format per-year I/O coefficients (technology_id, target, role, year,
#: coefficient) — year-varying intensities / yields / emission factors.
IO_T = "io_t"

#: Legacy technology inputs table (technology_id, commodity_id, intensity).
PROCESS_INPUTS = "process_inputs"

#: Legacy technology outputs table (technology_id, commodity_id, yield).
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

# ── Commodity impact factors ──────────────────────────────────────────────────

#: Static per-unit stream emission/impact factors (commodity_id, impact_id, factor).
COMMODITY_IMPACTS = "commodity_impacts"

#: Year-varying stream emission/impact factors (commodity_id, impact_id, year, factor).
COMMODITY_IMPACTS_T = "commodity_impacts_t"

# ── Facilities (process instances) ───────────────────────────────────────────

#: Flat facility/process instances (process_id, company, baseline_technology, …).
PROCESSES = "processes"

#: Technology compatibility + transition routes (from_technology, to_technology, …).
TRANSITIONS = "transitions"

#: Fleet-wide adoption caps (technology_id, max_count) — at most N processes may
#: run a technology in any one year.
TECHNOLOGY_CAPS = "technology_caps"

#: Long-format per-year transition capex (from_technology, to_technology, year,
#: capex_per_capacity).
TRANSITIONS_T = "transitions_t"

#: Company-level objective configuration (cost vs. profit).
COMPANY_CONFIG = "company_config"

# ── Node hierarchy (optional — replaces flat processes/edges) ─────────────────

#: Recursive node tree rows (node_id, parent_id, kind, level, label, order).
NODES = "nodes"

#: Leaf-machine detail rows (machine_id, baseline_technology, capacity, …).
MACHINES = "machines"

#: Directed commodity flows between sibling nodes (from_node, to_node, commodity_id, …).
CONNECTIONS = "connections"

#: Boundary ports exposed by group nodes (node_id, commodity_id, direction, …).
PORTS = "ports"

#: 2-D layout of process/node cards for the canvas UI (id, x, y).
NODE_LAYOUT = "node_layout"

# ── Edges (flat-model wiring) ─────────────────────────────────────────────────

#: Directed commodity flows between flat processes (from_process, to_process, …).
EDGES = "edges"

#: Long-format per-year edge capacity (from_process, to_process, commodity_id,
#: year, max_flow).
EDGES_T = "edges_t"

# ── Measures and MACCs ───────────────────────────────────────────────────────

#: Individual retrofit measure definitions (measure_id, type, target, …).
MEASURES = "measures"

#: Piecewise cost-curve blocks for each measure (measure_id, block, reduction, …).
MEASURE_BLOCKS = "measure_blocks"

#: Long-format per-year block-cost trajectory (measure_id, block, year, capex?, opex?).
MEASURE_BLOCKS_T = "measure_blocks_t"

#: MACC bundle membership: which measures belong to which named MACC
#: (macc, measure_id).
MACCS = "maccs"

#: MACC deployment links: which facilities/technologies a MACC applies to
#: (macc, facility?, technology?, commodity?, storage?).
MACC_LINKS = "macc_links"

#: Legacy named-set membership for measures (set, applies_to).
MEASURE_LINKS = "measure_links"

# ── Storage ───────────────────────────────────────────────────────────────────

#: Inter-year commodity stores (storage_id, commodity_id, company, …).
STORAGE = "storage"

#: Wide temporal store build cost / O&M / efficiencies (keyed by storage_id).
STORAGE_T_CAPEX = "storage_t__capex_per_capacity"
STORAGE_T_FIXED_OPEX = "storage_t__fixed_opex_per_capacity"
STORAGE_T_CHARGE_EFFICIENCY = "storage_t__charge_efficiency"
STORAGE_T_DISCHARGE_EFFICIENCY = "storage_t__discharge_efficiency"
STORAGE_T_STANDING_LOSS = "storage_t__standing_loss"

# ── Markets ───────────────────────────────────────────────────────────────────

#: Market definitions — commodity supply or ETS (market_id, target, …).
MARKETS = "markets"

#: Long-format per-year market price trajectory (market_id, year, price?, sell_price?, …).
MARKET_PRICES = "market_prices"

# ── Constraints ───────────────────────────────────────────────────────────────

#: Per-year product demand requirements (company, commodity_id, year, amount).
DEMAND = "demand"

#: Per-year investment budget limits (company, year?, limit?).
INVESTMENT_BUDGET = "investment_budget"

#: Per-year minimum production floors (company, commodity_id, year?, amount?).
MIN_PRODUCTION = "min_production"

#: Per-year environmental impact caps (company, impact_id, year?, limit?, soft?, …).
IMPACT_CAPS = "impact_caps"

# ── Component library (round-trip sheets for ComponentLibrary) ────────────────

#: Legacy composite-machine components (name, label, technology, capacity, …).
GROUPS = "groups"

# ── PyPSA-style wide temporal sheets (entity × year matrix) ───────────────────
# Sheet names follow the convention ``<entity>_t__<attribute>`` (double
# underscore separates entity base name from the varying attribute).

#: Wide temporal commodity purchase prices (year column + one column per commodity).
COMMODITIES_T_PRICE = "commodities_t__price"

#: Wide temporal commodity sale prices.
COMMODITIES_T_SALE_PRICE = "commodities_t__sale_price"

#: Wide temporal commodity maximum-purchase caps.
COMMODITIES_T_MAX_PURCHASE = "commodities_t__max_purchase"

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

#: Wide temporal market buy-volume caps.
MARKETS_T_MAX_BUY = "markets_t__max_buy"

#: Wide temporal market sell-volume caps.
MARKETS_T_MAX_SELL = "markets_t__max_sell"

#: Wide temporal investment-budget limits.
INVESTMENT_BUDGET_T_LIMIT = "investment_budget_t__limit"

#: Wide temporal minimum-production amounts.
MIN_PRODUCTION_T_AMOUNT = "min_production_t__amount"

#: Wide temporal demand amounts.
DEMAND_T_AMOUNT = "demand_t__amount"

#: Wide temporal impact-cap limits.
IMPACT_CAPS_T_LIMIT = "impact_caps_t__limit"
