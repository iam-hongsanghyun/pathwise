// Project-bundle API client — a self-contained, portable project: the name, the
// Facility/Value-Chain model, the project's own (project-specific) component
// libraries, and every base component the model references. Pure logic, no React.

import type { Workbook } from "../../types";
import type { ComponentLibrary } from "./components";
import { getFullModel } from "./session";

/** Discriminator the backend stamps on an export (import rejects other JSON). */
export const PROJECT_BUNDLE_FORMAT = "pathwise.project";

/** A self-contained project — re-opens and re-edits on any asset. */
export interface ProjectBundle {
  format: string;
  version: number;
  name: string;
  model: Workbook;
  session_libraries: Record<string, ComponentLibrary>;
  base_libraries: Record<string, ComponentLibrary>;
}

async function ok(resp: Response): Promise<Response> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return resp;
}

/** Download the project as one `.pathwise.json` file (assembled server-side). */
export async function downloadProject(sessionId: string, name: string): Promise<void> {
  const resp = await ok(await fetch(`/api/session/${sessionId}/project/export`));
  const url = URL.createObjectURL(await resp.blob());
  const safe = (name || "project").replace(/[^a-zA-Z0-9-_]/g, "") || "project";
  const a = document.createElement("a");
  a.href = url;
  a.download = `${safe}.pathwise.json`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Load a previously-exported bundle into the session; returns the new model. */
export async function importProject(
  sessionId: string,
  bundle: ProjectBundle,
): Promise<{ name: string; model: Workbook }> {
  const res = await ok(
    await fetch(`/api/session/${sessionId}/project/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bundle),
    }),
  );
  const body = (await res.json()) as { name?: string };
  return { name: body.name ?? bundle.name ?? "", model: await getFullModel(sessionId) };
}
