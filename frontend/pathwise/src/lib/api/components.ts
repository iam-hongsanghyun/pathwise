// Component-library API client — the writable catalogue the Component builder
// edits, and the source the Value-Chain builder drops fresh copies from.
// Pure logic layer: no React imports.

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return (await resp.json()) as T;
}

// ── Types mirroring src/pathwise/data/components.py + library.py ───────────────

export type IoRole = "input" | "output" | "impact";
export type LeverType = "energy_efficiency" | "emission_reduction" | "environmental";
export type CommodityKind = "energy" | "material" | "indirect" | "product" | "byproduct";

export interface IoRow {
  target: string;
  role: IoRole;
  coefficient: number;
  /** Authored unit of `coefficient` (e.g. "MWh"). Blank/absent = the target
   *  stream's unit; a differing unit is converted to the stream's unit at assembly. */
  unit?: string | null;
  is_product?: boolean;
  group?: string | null;
  share_min?: number | null;
  share_max?: number | null;
}

/** A per-year override map: calendar year → value. JSON keys arrive as strings. */
export type ByYear = Record<string, number>;

export interface TechnologyTemplate {
  technology_id: string;
  lifespan: number;
  capex: number;
  opex: number;
  /** Per-year overrides of the scalar capex/opex (empty = scalar every year). */
  capex_by_year?: ByYear;
  opex_by_year?: ByYear;
  /** Per-year overrides of an io coefficient, keyed `target -> {year: value}`
   *  (a recipe whose intensity / yield / emission factor varies over the horizon).
   *  Empty = use the scalar io coefficient. Round-trips through the `io_t` sheet. */
  input_intensity_by_year?: Record<string, ByYear>;
  output_yield_by_year?: Record<string, ByYear>;
  direct_impact_by_year?: Record<string, ByYear>;
  /** Years the technology is available to adopt (null = always). */
  introduction_year?: number | null;
  phase_out_year?: number | null;
  io: IoRow[];
  /** Ids of the MACC bundles that apply to this technology. */
  maccs: string[];
  /** Free-text notes / references (optimiser ignores it). */
  notes?: string;
}

export interface LeverBlock {
  reduction: number;
  capex_per_capacity: number;
  opex_per_capacity: number;
  /** Per-year overrides of the scalar per-capacity costs (empty = scalar). */
  capex_per_capacity_by_year?: ByYear;
  opex_per_capacity_by_year?: ByYear;
}

export interface LeverTemplate {
  lever_id: string;
  label: string;
  type: LeverType;
  target: string;
  lifetime: number;
  blocks: LeverBlock[];
  /** Free-text notes / references (optimiser ignores it). */
  notes?: string;
}

/** A MACC — a named, reusable bundle linking individual levers by id. */
export interface MaccGroup {
  macc_id: string;
  label: string;
  measures: string[];
  /** Free-text notes / references (optimiser ignores it). */
  notes?: string;
}

export interface AssetComponent {
  name: string;
  label: string;
  technology: string;
  capacity: number;
  measures: LeverTemplate[];
}

export interface CommodityTemplate {
  commodity_id: string;
  kind: CommodityKind;
  unit: string;
  price?: number | null;
  sale_price?: number | null;
  /** Per-year overrides of the scalar price/sale_price (empty = scalar). */
  price_by_year?: ByYear;
  sale_price_by_year?: ByYear;
  /** Owning sector (the sector that PRODUCES this stream — electricity is "power",
   *  not "steel"). Blank/null = a general, industry-agnostic stream. */
  sector?: string | null;
  /** Free-text notes / references (optimiser ignores it). */
  notes?: string;
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
  /** Free-text notes / references (optimiser ignores it). */
  notes?: string;
}

export interface ComponentLibrary {
  label: string;
  commodities: CommodityTemplate[];
  technologies: TechnologyTemplate[];
  /** Standalone, reusable levers. */
  measures: LeverTemplate[];
  /** MACC bundles grouping levers. */
  maccs: MaccGroup[];
  /** Legacy composite components (no longer authored). */
  assets: AssetComponent[];
  groups: GroupComponent[];
  /** Free-text notes / references keyed by derived sector name. */
  notes_by_sector?: Record<string, string>;
}

/** Which catalogue a library lives in: the shared "base" set, or a project's
 *  own per-"session" set. */
export type LibScope = "base" | "session";

export interface LibrarySummary {
  id: string;
  label: string;
  scope: LibScope;
  /** "starter" = a shipped read-only reference; "user" = the user's own library.
   *  Only set for base-scope libraries (session libraries are always editable). */
  origin?: "starter" | "user";
  commodities: number;
  technologies: number;
  levers: number;
  maccs: number;
  assets: number;
  groups: number;
}

/** A blank library — every list defaults to empty. */
export function emptyLibrary(label = ""): ComponentLibrary {
  return { label, commodities: [], technologies: [], measures: [], maccs: [], assets: [], groups: [] }; // `measures` = lever list (field name unchanged)
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

// ── Per-session libraries (a project's own set) ───────────────────────────────

export async function listSessionComponentLibraries(sessionId: string): Promise<LibrarySummary[]> {
  return json<LibrarySummary[]>(await fetch(`/api/session/${sessionId}/component-libraries`));
}

export async function getSessionComponentLibrary(
  sessionId: string,
  id: string,
): Promise<ComponentLibrary> {
  return json<ComponentLibrary>(
    await fetch(`/api/session/${sessionId}/component-library/${encodeURIComponent(id)}`),
  );
}

export async function saveSessionComponentLibrary(
  sessionId: string,
  id: string,
  library: ComponentLibrary,
): Promise<LibrarySummary> {
  return json<LibrarySummary>(
    await fetch(`/api/session/${sessionId}/component-library/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(library),
    }),
  );
}

export async function deleteSessionComponentLibrary(sessionId: string, id: string): Promise<void> {
  await json(
    await fetch(`/api/session/${sessionId}/component-library/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  );
}

/** Download URL for a blank component-library template (.xlsx, one sheet per kind). */
export function libraryTemplateUrl(): string {
  return "/api/component-library/template.xlsx";
}

/** Import a component library from an .xlsx/.sqlite file (format sniffed server-side)
 *  into "My" libraries under `id`. */
export async function importComponentLibraryFile(id: string, file: File): Promise<LibrarySummary> {
  const form = new FormData();
  form.append("file", file);
  return json<LibrarySummary>(
    await fetch(`/api/component-library/${encodeURIComponent(id)}/import`, { method: "POST", body: form }),
  );
}

/** Import a component library from a file into this project's (session) set under `id`. */
export async function importSessionComponentLibraryFile(
  sessionId: string,
  id: string,
  file: File,
): Promise<LibrarySummary> {
  const form = new FormData();
  form.append("file", file);
  return json<LibrarySummary>(
    await fetch(`/api/session/${sessionId}/component-library/${encodeURIComponent(id)}/import`, {
      method: "POST",
      body: form,
    }),
  );
}

/** Base (shared) + this session's own libraries, session set first. Each summary
 *  carries its `scope`, so callers can route get/save/delete to the right store. */
export async function listAllComponentLibraries(
  sessionId: string | null,
): Promise<LibrarySummary[]> {
  const base = await listComponentLibraries();
  if (!sessionId) return base;
  const session = await listSessionComponentLibraries(sessionId).catch(() => []);
  return [...session, ...base];
}

/** Drop a fresh copy of a (legacy) composite component under a group node. */
export async function instantiateComponent(
  sessionId: string,
  body: { library: string; component: string; parent_id: string; instance_id?: string; scope?: LibScope },
): Promise<{ created: string[]; root: string | null }> {
  return json<{ created: string[]; root: string | null }>(
    await fetch(`/api/session/${sessionId}/instantiate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

// ── Project workbench: copy-in (drag a component/group from a library) ─────────

/** The component kinds a project can copy in — the dispatch keys of the backend
 *  `copy_component_into` (a "stream" is a commodity). */
export type ComponentCatalogKind = "technology" | "stream" | "lever" | "macc";

/** Hard-copy a component (+ its dependency closure) into the session project
 *  `dstId`. Returns the project's new summary. */
export async function copyComponentIntoProject(
  sessionId: string,
  dstId: string,
  body: { src_scope: LibScope; src_id: string; kind: ComponentCatalogKind; component_id: string },
): Promise<LibrarySummary> {
  return json<LibrarySummary>(
    await fetch(`/api/session/${sessionId}/component-library/${encodeURIComponent(dstId)}/copy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

/** A technology offered by some library (the pool an alternative is drawn from). */
export interface AvailableTechnology {
  library: string;
  scope: LibScope;
  technology: string;
}

/** Every technology across the base + this session's libraries. */
export async function listAvailableTechnologies(sessionId: string): Promise<AvailableTechnology[]> {
  return json<AvailableTechnology[]>(await fetch(`/api/session/${sessionId}/technologies`));
}

/** Offer a technology as an alternative the optimiser may switch a asset to. */
export async function addAlternative(
  sessionId: string,
  body: { library: string; technology: string; asset_id: string; scope: LibScope },
): Promise<{ from_technology: string; to_technology: string }> {
  return json<{ from_technology: string; to_technology: string }>(
    await fetch(`/api/session/${sessionId}/alternative`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

/** Place a technology as a fresh asset under a group node of the session. */
export async function placeTechnology(
  sessionId: string,
  body: {
    library: string;
    technology: string;
    parent_id: string;
    capacity?: number;
    instance_id?: string;
    scope?: LibScope;
  },
): Promise<{ created: string[]; root: string | null }> {
  return json<{ created: string[]; root: string | null }>(
    await fetch(`/api/session/${sessionId}/place-technology`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}
