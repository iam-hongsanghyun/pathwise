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
    // Probe with the 200-returning existence check (not /model, which 404s and
    // spams the console) so a stale localStorage id recovers quietly.
    const { exists } = await json<{ exists: boolean }>(await fetch(`/api/session/${stored}`));
    if (exists) {
      const body = await json<{ model: Workbook }>(await fetch(`/api/session/${stored}/model`));
      return { sessionId: stored, model: body.model };
    }
    console.info(`pathwise: stored session ${stored} no longer exists — creating a fresh one.`);
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

/** Upload a model file (.xlsx or .sqlite) — parsed SERVER-side (format sniffed),
 *  replaces the session model; returns the refreshed model. */
export async function uploadWorkbook(sessionId: string, file: File): Promise<Workbook> {
  const form = new FormData();
  form.append("file", file);
  await json(await fetch(`/api/session/${sessionId}/workbook`, { method: "POST", body: form }));
  return getFullModel(sessionId);
}

/** Download URL for the session model as a human-readable .xlsx (one sheet per table). */
export function exportModelUrl(sessionId: string): string {
  return `/api/session/${sessionId}/export`;
}

/** Download URL for the session model as a single-file SQLite database. */
export function exportModelSqliteUrl(sessionId: string): string {
  return `/api/session/${sessionId}/export.sqlite`;
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

// ── Example / importable libraries (served by the backend) ──────────────────

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
