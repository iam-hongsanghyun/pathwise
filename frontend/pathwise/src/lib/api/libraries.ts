// Importable-library API client — the tiered, auto-discovered catalogue.
//
// A *library* is one JSON workbook bundling components (streams / technologies /
// levers) and optionally a network (a node hierarchy). They live under
// <tier>/<id>.json on the backend: `base` (reference building blocks),
// `example` (illustrative models), `project` (specific real projects). There is
// no index — dropping a JSON file into a tier folder is enough.
// Pure logic layer: no React imports.

import type { Workbook } from "../../types";
import { getFullModel } from "./session";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return (await resp.json()) as T;
}

export type LibraryTier = "base" | "example" | "project";

export interface LibraryEntry {
  id: string;
  tier: LibraryTier;
  label: string;
  /** The workbook carries a node hierarchy → importing rebuilds the network. */
  has_value_chain: boolean;
  /** The workbook carries streams / technologies / levers → stocks the library. */
  has_components: boolean;
}

/** Every importable library, discovered by globbing the tier folders. */
export async function listLibraries(): Promise<LibraryEntry[]> {
  return json<LibraryEntry[]>(await fetch("/api/libraries"));
}

export interface ImportResult {
  library_id: string;
  /** Whether the import replaced the session model with the library's chain. */
  imported_value_chain: boolean;
  /** The refreshed session model (blank if the library was components-only). */
  model: Workbook;
}

/** Import a library into the session: components → the session component
 *  library, and (when it carries a node hierarchy) the network → the
 *  session model. Returns the refreshed model. */
export async function importLibrary(
  sessionId: string,
  tier: LibraryTier,
  id: string,
): Promise<ImportResult> {
  const res = await json<{ library_id: string; imported_value_chain: boolean }>(
    await fetch(
      `/api/session/${sessionId}/library/${encodeURIComponent(tier)}/${encodeURIComponent(id)}/import`,
      { method: "POST" },
    ),
  );
  return {
    library_id: res.library_id,
    imported_value_chain: res.imported_value_chain,
    model: await getFullModel(sessionId),
  };
}
