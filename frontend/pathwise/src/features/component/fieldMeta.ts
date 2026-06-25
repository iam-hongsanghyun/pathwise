// Field-level help: one explanation + unit per data key, shown by the (i) icon
// next to every Component-builder input (and as DataTable column hints). Text is
// taken verbatim from the backend pydantic docstrings (src/pathwise/data/
// library.py, components.py) so the UI never drifts from the model.

export interface FieldMeta {
  info: string;
  unit?: string;
}

/** Keyed by the entity's data key (the field name written to the workbook). */
export const FIELD_META: Record<string, FieldMeta> = {
  // ── Technology ──────────────────────────────────────────────────────────────
  technology_id: { info: "Unique id of the technology recipe." },
  lifespan: { info: "Economic lifetime before the technology must be renewed or replaced.", unit: "years" },
  capex: { info: "Overnight replacement capital cost, per unit of installed capacity.", unit: "currency / unit capacity" },
  opex: { info: "Fixed operating cost, per unit of throughput.", unit: "currency / unit throughput" },
  introduction_year: { info: "First year the technology can be adopted (blank = always available).", unit: "year" },
  phase_out_year: { info: "Last year the technology can be adopted (blank = always available).", unit: "year" },

  // ── Stream / flow ───────────────────────────────────────────────────────
  flow_id: { info: "Unique id of the stream (flow)." },
  kind: { info: "energy · material · indirect · product · byproduct — what the stream represents." },
  unit: { info: "The physical unit the stream's quantities and prices are expressed in." },
  sector: { info: "The sector that PRODUCES this stream (electricity belongs to power, not steel). Blank = a general, industry-agnostic stream. Organisational only — the optimiser ignores it." },
  price: { info: "External purchase price of the stream.", unit: "currency / unit" },
  sale_price: { info: "Revenue when the stream is sold or exported.", unit: "currency / unit" },

  // ── IO row ────────────────────────────────────────────────────────────────────
  target: { info: "The stream consumed/produced (or the impact emitted) by this row." },
  role: { info: "input (consumed) · output (produced) · impact (emitted), per unit of throughput." },
  coefficient: { info: "Amount of the stream per unit of the technology's throughput.", unit: "stream unit / throughput" },
  coefficient_unit: { info: "Unit the coefficient is authored in. Blank = the target stream's own unit; a differing unit is converted to the stream's unit when the model is assembled." },
  is_product: { info: "Marks the primary product output (what demand is placed on)." },
  group: { info: "Blend group (inputs) or output slate (outputs) — members share min/max shares." },
  share_min: { info: "Minimum share of the blend/slate group this stream must take.", unit: "fraction 0–1" },
  share_max: { info: "Maximum share of the blend/slate group this stream may take.", unit: "fraction 0–1" },

  // ── Lever + block ─────────────────────────────────────────────────────────────
  lever_id: { info: "Unique id of the lever (an abatement retrofit applied to a facility)." },
  label: { info: "Human-readable label shown in the UI." },
  lever_type: { info: "energy_efficiency · emission_reduction · environmental — which lever this pulls." },
  lifetime: { info: "Economic lifetime of the retrofit.", unit: "years" },
  reduction: { info: "Fractional reduction of the target at full adoption of this block.", unit: "fraction 0–1" },
  capex_per_capacity: { info: "Block capital cost, per unit of the facility's capacity (scales with the plant it is stamped onto).", unit: "currency / unit capacity" },
  opex_per_capacity: { info: "Block fixed operating cost while adopted, per unit capacity, per year.", unit: "currency / unit capacity / yr" },

  // ── MACC / group ───────────────────────────────────────────────────────────────
  macc_id: { info: "Unique id of the MACC — a named bundle of individual levers." },
  level: { info: "The designed level this group sits at (free text, e.g. facility, company)." },
  notes: { info: "Free-text notes / references for your own use. The optimiser ignores it." },

  // ── Value-chain (placed assets, links, purchasing, demand) ─────────────────
  capacity: { info: "Nameplate throughput this asset can run at full load.", unit: "throughput / yr" },
  lag_years: { info: "Years the flow takes to traverse this link (0 = same year).", unit: "years" },
  amount: { info: "Quantity of the product this node must deliver to demand each year.", unit: "stream unit / yr" },
  max_purchase: { info: "Ceiling on how much of this stream may be bought externally per year (blank = no cap).", unit: "stream unit / yr" },
  available_from: { info: "First year this stream can be bought externally (blank = always).", unit: "year" },
  available_to: { info: "Last year this stream can be bought externally (blank = always).", unit: "year" },
};

export const fieldMeta = (key: string): FieldMeta | undefined => FIELD_META[key];
