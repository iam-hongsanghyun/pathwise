// Facility-template library: types mirroring src/pathwise/data/library.py and
// loaders following the examples-library pattern (static JSON under /library).

export interface SourceRef {
  name: string;
  url: string;
  year: number;
  region?: string;
  basis?: string;
  notes?: string;
}

export interface LibIoRow {
  target: string;
  role: "input" | "output" | "impact";
  coefficient: number;
  is_product?: boolean;
  group?: string;
  share_min?: number;
  share_max?: number;
}

export interface LibTechnology {
  technology_id: string;
  lifespan?: number;
  capex?: number;
  opex?: number;
  io: LibIoRow[];
}

export interface LibAlternative {
  technology: LibTechnology;
  transition_capex_per_capacity?: number;
}

export interface LibCommodity {
  commodity_id: string;
  kind: string;
  unit?: string;
  price?: number;
  sale_price?: number;
}

export interface LibMeasureBlock {
  reduction: number;
  capex_per_capacity: number;
}

/** A measure template: a small retrofit of the same system (no technology switch). */
export interface LibMeasure {
  measure_id: string;
  label?: string;
  type: "energy_efficiency" | "emission_reduction" | "environmental";
  target: string;
  lifetime?: number;
  blocks: LibMeasureBlock[];
}

export interface FacilityTemplate {
  facility_id: string;
  label: string;
  description?: string;
  technology: LibTechnology;
  alternatives?: LibAlternative[];
  measures?: LibMeasure[];
  default_capacity?: number;
  source: SourceRef;
}

export interface ChainStage {
  facility: string;
  feeds?: string[];
}

export interface ChainTemplate {
  chain_id: string;
  label: string;
  description?: string;
  stages: ChainStage[];
  demand_hint?: { commodity_id: string; amount: number };
  source: SourceRef;
}

export interface SectorLibrary {
  sector: string;
  label: string;
  commodities: LibCommodity[];
  facilities: FacilityTemplate[];
  chains?: ChainTemplate[];
}

export interface LibraryIndexEntry {
  sector: string;
  label: string;
  file: string;
  description?: string;
}

/** List the sector libraries (served by the backend). */
export async function listLibrary(): Promise<LibraryIndexEntry[]> {
  const res = await fetch("/api/library");
  if (!res.ok) return [];
  return (await res.json()) as LibraryIndexEntry[];
}

/** Fetch one sector's templates (served by the backend). */
export async function loadSector(sector: string): Promise<SectorLibrary> {
  const res = await fetch(`/api/library/${encodeURIComponent(sector)}`);
  if (!res.ok) throw new Error(`could not load library sector ${sector}`);
  return (await res.json()) as SectorLibrary;
}
