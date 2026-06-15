// Component-library API client — the writable catalogue the Component builder
// edits, and the source the Value-Chain builder drops fresh copies from.
// Pure logic layer: no React imports.

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return (await resp.json()) as T;
}

// ── Types mirroring src/pathwise/data/components.py + library.py ───────────────

export type IoRole = "input" | "output" | "impact";
export type MeasureType = "energy_efficiency" | "emission_reduction" | "environmental";
export type CommodityKind = "energy" | "material" | "indirect" | "product" | "byproduct";

export interface IoRow {
  target: string;
  role: IoRole;
  coefficient: number;
  is_product?: boolean;
  group?: string | null;
  share_min?: number | null;
  share_max?: number | null;
}

export interface TechnologyTemplate {
  technology_id: string;
  lifespan: number;
  capex: number;
  opex: number;
  io: IoRow[];
}

export interface MeasureBlock {
  reduction: number;
  capex_per_capacity: number;
  opex_per_capacity: number;
}

export interface MeasureTemplate {
  measure_id: string;
  label: string;
  type: MeasureType;
  target: string;
  lifetime: number;
  blocks: MeasureBlock[];
}

export interface MachineComponent {
  name: string;
  label: string;
  technology: string;
  capacity: number;
  measures: MeasureTemplate[];
}

export interface CommodityTemplate {
  commodity_id: string;
  kind: CommodityKind;
  unit: string;
  price?: number | null;
  sale_price?: number | null;
}

export interface ChildRef {
  component: string;
  alias: string;
}

export interface ConnectionTemplate {
  source: string;
  target: string;
  commodity: string;
  lag_years: number;
}

export interface GroupComponent {
  name: string;
  label: string;
  level: string;
  children: ChildRef[];
  connections: ConnectionTemplate[];
}

export interface ComponentLibrary {
  label: string;
  commodities: CommodityTemplate[];
  technologies: TechnologyTemplate[];
  machines: MachineComponent[];
  groups: GroupComponent[];
}

export interface LibrarySummary {
  id: string;
  label: string;
  commodities: number;
  technologies: number;
  machines: number;
  groups: number;
}

/** A blank library — every list defaults to empty. */
export function emptyLibrary(label = ""): ComponentLibrary {
  return { label, commodities: [], technologies: [], machines: [], groups: [] };
}

// ── Endpoints ─────────────────────────────────────────────────────────────────

export async function listComponentLibraries(): Promise<LibrarySummary[]> {
  return json<LibrarySummary[]>(await fetch("/api/component-libraries"));
}

export async function getComponentLibrary(id: string): Promise<ComponentLibrary> {
  return json<ComponentLibrary>(await fetch(`/api/component-library/${encodeURIComponent(id)}`));
}

export async function saveComponentLibrary(
  id: string,
  library: ComponentLibrary,
): Promise<LibrarySummary> {
  return json<LibrarySummary>(
    await fetch(`/api/component-library/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(library),
    }),
  );
}

export async function deleteComponentLibrary(id: string): Promise<void> {
  await json(
    await fetch(`/api/component-library/${encodeURIComponent(id)}`, { method: "DELETE" }),
  );
}

/** Drop a fresh copy of a component under a group node of the session model. */
export async function instantiateComponent(
  sessionId: string,
  body: { library: string; component: string; parent_id: string; instance_id?: string },
): Promise<{ created: string[]; root: string | null }> {
  return json<{ created: string[]; root: string | null }>(
    await fetch(`/api/session/${sessionId}/instantiate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}
