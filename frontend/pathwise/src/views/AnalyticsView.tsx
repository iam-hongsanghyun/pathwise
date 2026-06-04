import { MaccDesigner } from "../components/MaccDesigner";
import { ResultsView } from "../components/ResultsView";
import type { RunResult, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  result: RunResult | null;
}

/** Analytics — the only place results and charts live: the design-time
 *  aggregate MACC, plus the optimisation result once a run completes. */
export function AnalyticsView({ workbook, result }: Props) {
  return (
    <div className="view">
      {result ? (
        <ResultsView result={result} />
      ) : (
        <p className="muted">Run the model (▶ top-left) to see results here.</p>
      )}
      <section>
        <h2>Marginal abatement cost</h2>
        <MaccDesigner workbook={workbook} />
      </section>
    </div>
  );
}
