// Typed client for the minimal pathwise contract: config handshake + run.
// The only data the frontend sends is the model+scenario; the only data it
// receives is the entire result. (Parsing/exporting xlsx is client-side — see
// workbook.ts.)

import type { ConfigBundle, JobState, RunResult, Scenario, Workbook } from "./types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  }
  return (await resp.json()) as T;
}

/** Handshake: the backend's one true source of server-side config + capabilities. */
export async function getConfig(): Promise<ConfigBundle> {
  return json<ConfigBundle>(await fetch("/api/config"));
}

async function startRun(
  model: Workbook,
  scenario: Scenario,
  options: Record<string, unknown>,
): Promise<{ jobId: string }> {
  return json<{ jobId: string }>(
    await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, scenario, options }),
    }),
  );
}

async function pollRun(jobId: string): Promise<JobState> {
  return json<JobState>(await fetch(`/api/run/${jobId}`));
}

/** Send the model once, then poll until the whole result is ready. */
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
    await new Promise((r) => setTimeout(r, 500));
  }
}
