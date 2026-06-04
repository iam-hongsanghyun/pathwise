// Typed fetch wrappers for the pathwise API.

import type { ConfigBundle, JobState, RunResult, ValidationResult, Workbook, Scenario } from "./types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return (await resp.json()) as T;
}

export async function getConfig(): Promise<ConfigBundle> {
  return json<ConfigBundle>(await fetch("/api/config"));
}

export async function parseWorkbook(file: File): Promise<Workbook> {
  const form = new FormData();
  form.append("file", file);
  const data = await json<{ model: Workbook }>(
    await fetch("/api/workbook/parse", { method: "POST", body: form }),
  );
  return data.model;
}

export async function validate(
  model: Workbook,
  scenario: Scenario,
  options: Record<string, unknown> = {},
): Promise<ValidationResult> {
  return json<ValidationResult>(
    await fetch("/api/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, scenario, options }),
    }),
  );
}

export async function startRun(
  model: Workbook,
  scenario: Scenario,
  options: Record<string, unknown> = {},
): Promise<{ jobId: string }> {
  return json<{ jobId: string }>(
    await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, scenario, options }),
    }),
  );
}

export async function pollRun(jobId: string): Promise<JobState> {
  return json<JobState>(await fetch(`/api/run/${jobId}`));
}

export async function exportXlsx(result: RunResult): Promise<Blob> {
  const resp = await fetch("/api/export/xlsx", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(result),
  });
  if (!resp.ok) throw new Error(`export failed: ${resp.status}`);
  return await resp.blob();
}

/** Submit a run and poll until it finishes (or errors). */
export async function runToCompletion(
  model: Workbook,
  scenario: Scenario,
  options: Record<string, unknown>,
  onTick?: (status: string) => void,
): Promise<RunResult> {
  const { jobId } = await startRun(model, scenario, options);
  for (;;) {
    const state = await pollRun(jobId);
    onTick?.(state.status);
    if (state.status === "done" && state.result) return state.result;
    if (state.status === "error") throw new Error(state.error ?? "run failed");
    if (state.status === "cancelled") throw new Error("run cancelled");
    await new Promise((r) => setTimeout(r, 400));
  }
}
