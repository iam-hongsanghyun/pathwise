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

let _inflight: Promise<{ sessionId: string; model: Workbook }> | null = null;

/** Reuse the stored session if the backend still knows it; else create one.
 *
 *  De-duplicated: concurrent calls (React StrictMode runs the boot effect twice
 *  in dev, and a remount could call again) share ONE in-flight request, so a page
 *  load never creates a duplicate orphan session. The cache resets on failure so
 *  a later attempt can retry. */
export function ensureSession(): Promise<{ sessionId: string; model: Workbook }> {
  if (!_inflight) {
    _inflight = _ensureSession();
    _inflight.catch(() => {
      _inflight = null;
    });
  }
  return _inflight;
}

async function _ensureSession(): Promise<{ sessionId: string; model: Workbook }> {
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

/** Reset the session to an empty model; returns the refreshed (blank) model. */
export async function clearModel(sessionId: string): Promise<Workbook> {
  await json(await fetch(`/api/session/${sessionId}/clear`, { method: "POST" }));
  return getFullModel(sessionId);
}

/** Wipe ALL working session data (sessions + session libraries) and adopt the
 *  fresh empty session the server hands back. */
export async function clearCache(): Promise<{ sessionId: string; model: Workbook }> {
  const res = await json<{ sessionId: string }>(
    await fetch("/api/cache/clear", { method: "POST" }),
  );
  localStorage.setItem(SESSION_KEY, res.sessionId);
  return { sessionId: res.sessionId, model: await getFullModel(res.sessionId) };
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
async function _downloadResult(result: unknown, path: string, filename: string): Promise<void> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(result),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  const url = URL.createObjectURL(await resp.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Download the run result as a SQLite workbook (one table per output, by year). */
export const downloadResultSqlite = (result: unknown): Promise<void> =>
  _downloadResult(result, "/api/export/result.sqlite", "pathwise_result.sqlite");

/** Download the run result as a flattened .xlsx. */
export const downloadResultXlsx = (result: unknown): Promise<void> =>
  _downloadResult(result, "/api/export/result", "pathwise_result.xlsx");

// ── Examples + facility-template library (served and inserted by the backend) ─

export interface ExampleModel {
  id: string;
  label: string;
  file: string;
  description?: string;
  /** Component library to surface alongside this example, if any. */
  library?: string;
  /** Optimisation method this example is authored for (default "linopy"). */
  backend?: string;
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
    library: string;
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
