// Session API client — the backend owns the working model (ragnarok pattern).
// Pure logic layer: no React imports here.

import type { Workbook } from "../../types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return (await resp.json()) as T;
}

const SESSION_KEY = "pathwise.sessionId";

/** The browser's session id, or null before the first ensureSession(). */
export function storedSessionId(): string | null {
  return localStorage.getItem(SESSION_KEY);
}

/** Reuse the stored session if the backend still knows it; else create one. */
export async function ensureSession(): Promise<{ sessionId: string; model: Workbook }> {
  const stored = storedSessionId();
  if (stored) {
    const resp = await fetch(`/api/session/${stored}/model`);
    if (resp.ok) {
      const body = (await resp.json()) as { model: Workbook };
      return { sessionId: stored, model: body.model };
    }
  }
  const created = await json<{ sessionId: string }>(
    await fetch("/api/session", { method: "POST" }),
  );
  localStorage.setItem(SESSION_KEY, created.sessionId);
  const body = await json<{ model: Workbook }>(
    await fetch(`/api/session/${created.sessionId}/model`),
  );
  return { sessionId: created.sessionId, model: body.model };
}

export async function getFullModel(sessionId: string): Promise<Workbook> {
  const body = await json<{ model: Workbook }>(await fetch(`/api/session/${sessionId}/model`));
  return body.model;
}

/** Replace the whole session model (structural changes: sheets added/removed). */
export async function putModel(sessionId: string, model: Workbook): Promise<void> {
  await json(
    await fetch("/api/session/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, model }),
    }),
  );
}

/** Replace one sheet's rows (the debounced per-sheet sync). */
export async function replaceSheet(
  sessionId: string,
  sheet: string,
  rows: Workbook[string],
): Promise<void> {
  await json(
    await fetch(`/api/session/${sessionId}/sheet/${encodeURIComponent(sheet)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ops: [{ op: "replace", rows }] }),
    }),
  );
}

/** Upload an .xlsx — parsed SERVER-side; returns the refreshed model. */
export async function uploadWorkbook(sessionId: string, file: File): Promise<Workbook> {
  const form = new FormData();
  form.append("file", file);
  await json(await fetch(`/api/session/${sessionId}/workbook`, { method: "POST", body: form }));
  return getFullModel(sessionId);
}

/** Download URL for the session model (.xlsx written server-side). */
export function exportModelUrl(sessionId: string): string {
  return `/api/session/${sessionId}/export`;
}

/** Download a run result as .xlsx (flattened server-side). */
export async function downloadResultXlsx(result: unknown): Promise<void> {
  const resp = await fetch("/api/export/result", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(result),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  const url = URL.createObjectURL(await resp.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = "pathwise_result.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}

// ── Examples + facility-template library (served and inserted by the backend) ─

export interface ExampleModel {
  id: string;
  label: string;
  file: string;
  description?: string;
}

export async function listExamples(): Promise<ExampleModel[]> {
  return json<ExampleModel[]>(await fetch("/api/examples"));
}

/** Backend loads the example into the session; returns the refreshed model. */
export async function loadExample(sessionId: string, exampleId: string): Promise<Workbook> {
  await json(
    await fetch(`/api/session/${sessionId}/example/${encodeURIComponent(exampleId)}`, {
      method: "POST",
    }),
  );
  return getFullModel(sessionId);
}

/** Backend inserts a facility/chain template; returns refreshed model + ids. */
export async function insertTemplate(
  sessionId: string,
  body: {
    sector: string;
    kind: "facility" | "chain";
    id: string;
    /** "initial" creates a facility running the template today; "replacement"
     *  registers it as a transition OPTION of `replace_process`'s baseline. */
    mode?: "initial" | "replacement";
    replace_process?: string;
    x?: number;
    y?: number;
  },
): Promise<{ model: Workbook; created: string[] }> {
  const res = await json<{ created: string[] }>(
    await fetch(`/api/session/${sessionId}/library`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return { model: await getFullModel(sessionId), created: res.created };
}
