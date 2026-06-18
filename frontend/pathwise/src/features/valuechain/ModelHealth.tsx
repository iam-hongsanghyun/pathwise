// Model-health panel — a live, grouped list of the validation issues for the
// current model. Each row jumps to the offending node (if it has one) and offers
// the issue's one-click fix. Presentational: the host owns jump + fix.

import type { Issue } from "../../lib/validate";

export function ModelHealth({
  issues,
  onJump,
  onFix,
}: {
  issues: Issue[];
  onJump: (nodeId: string) => void;
  onFix: (issue: Issue) => void;
}) {
  if (issues.length === 0) {
    return (
      <div className="rail-section">
        <div className="rail-head">Model health</div>
        <div className="rail-empty" style={{ color: "var(--brand)" }}>✓ No issues found — ready to run.</div>
      </div>
    );
  }
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

  const row = (i: Issue) => (
    <div key={i.id} className="health-row">
      <button
        className="health-msg"
        title={i.scope?.nodeId ? "jump to this item" : i.message}
        onClick={() => i.scope?.nodeId && onJump(i.scope.nodeId)}
        style={{ cursor: i.scope?.nodeId ? "pointer" : "default" }}
      >
        <span className={`health-dot ${i.severity}`} aria-hidden />
        <span className="health-title">{i.title}</span>
        <span className="muted health-detail">{i.message}</span>
      </button>
      {i.fix && (
        <button className="ghost health-fix" onClick={() => onFix(i)} title={i.fix.label}>
          {i.fix.label}
        </button>
      )}
    </div>
  );

  return (
    <div className="rail-section">
      <div className="rail-head">
        Model health{" "}
        <span className="muted" style={{ fontWeight: 400 }}>
          {errors.length} error{errors.length === 1 ? "" : "s"} · {warnings.length} warning
          {warnings.length === 1 ? "" : "s"}
        </span>
      </div>
      {errors.map(row)}
      {warnings.map(row)}
    </div>
  );
}
