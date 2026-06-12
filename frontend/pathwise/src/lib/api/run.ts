// Run client: submit by sessionId (the model never travels from the browser),
// then poll until the result is ready. Pure logic layer: no React.

import type { ConfigBundle, JobState, RunResult } from "../../types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return (await resp.json()) as T;
}

export async function getConfig(): Promise<ConfigBundle> {
  return json<ConfigBundle>(await fetch("/api/config"));
}

export async function runToCompletion(
  sessionId: string,
  scenario: Record<string, unknown>,
  options: Record<string, unknown> = { domain: "process" },
  onTick?: (status: string) => void,
): Promise<RunResult> {
  const { jobId } = await json<{ jobId: string }>(
    await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, scenario, options }),
    }),
  );
  for (;;) {
    const state = await json<JobState>(await fetch(`/api/run/${jobId}`));
    onTick?.(state.status);
    if (state.status === "done" && state.result) return state.result;
    if (state.status === "error") throw new Error(state.error ?? "run failed");
    if (state.status === "cancelled") throw new Error("run cancelled");
    await new Promise((r) => setTimeout(r, 1500));
  }
}
