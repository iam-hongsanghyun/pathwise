// Run client: submit by sessionId (the model never travels from the browser),
// then poll until the result is ready. Pure logic layer: no React.

import type { ConfigBundle, JobState, RunMeta, RunResult } from "../../types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return (await resp.json()) as T;
}

/** The persisted run history (all sessions, newest first). Stays visible across a
 *  cache clear so the user's exported runs remain reachable. */
export async function listRuns(): Promise<RunMeta[]> {
  const { runs } = await json<{ runs: RunMeta[] }>(await fetch("/api/runs"));
  return runs;
}

/** Load one stored run's full result (for the history → re-open in analytics). */
export async function getRun(runId: string): Promise<RunResult> {
  return json<RunResult>(await fetch(`/api/runs/${encodeURIComponent(runId)}`));
}

/** Human tick label for a polled job: a live "done / total runs (label)" while a
 *  multi-solve backend reports progress, else the bare status. */
function tickLabel(state: JobState): string {
  const p = state.progress;
  if (state.status === "running" && p && p.total > 0) {
    const note = p.label ? ` · ${p.label}` : "";
    return `${p.done} / ${p.total} runs${note}`;
  }
  return state.status;
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
  const sleep = () => new Promise((r) => setTimeout(r, 1500));
  // Runs are tracked in server memory, so a backend restart (e.g. a dev
  // `--reload`) loses the job. Tolerate brief unreachability (the server may be
  // mid-reload), but a clean 404 means the job is gone for good — fail with a
  // plain message instead of a raw "404 Not Found".
  let unreachable = 0;
  for (;;) {
    let resp: Response;
    try {
      resp = await fetch(`/api/run/${jobId}`);
    } catch {
      if (++unreachable > 8) {
        throw new Error("Lost contact with the server during the run. Check the backend is up, then run again.");
      }
      onTick?.("reconnecting");
      await sleep();
      continue;
    }
    if (resp.status === 404) {
      throw new Error("The run was lost — the server restarted while it was in progress. Please run it again.");
    }
    const state = await json<JobState>(resp);
    unreachable = 0;
    onTick?.(tickLabel(state));
    if (state.status === "done" && state.result) return state.result;
    if (state.status === "error") throw new Error(state.error ?? "run failed");
    if (state.status === "cancelled") throw new Error("run cancelled");
    await sleep();
  }
}
