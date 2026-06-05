import { useState } from "react";
import { RailList, type RailItem } from "../layout/RailList";
import { Resizer } from "../layout/Resizer";

type Section = "economics" | "snapshots" | "solver" | "policy";
type Scope = "system" | "company" | "facility";

interface Props {
  discount: number;
  onDiscount: (v: number) => void;
  objScope: Scope;
  onObjScope: (s: Scope) => void;
  leftW: number;
  setLeftW: (w: number) => void;
}

/** Settings — its own section rail; scenario/run parameters only (model data is
 *  edited in Data). */
export function SettingsView({ discount, onDiscount, objScope, onObjScope, leftW, setLeftW }: Props) {
  const [section, setSection] = useState<Section>("economics");
  const items: RailItem[] = [
    { id: "economics", label: "Economics" },
    { id: "snapshots", label: "Snapshots" },
    { id: "solver", label: "Solver" },
    { id: "policy", label: "Policy" },
  ];

  return (
    <div className="body-row">
      <RailList
        title="Settings"
        items={items}
        activeId={section}
        onSelect={(id) => setSection(id as Section)}
        width={leftW}
      />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        <div className="view">
          {section === "economics" && (
            <section className="card">
              <h3>Economics</h3>
              <label className="inspector-field">
                <span>Discount rate</span>
                <input
                  type="number"
                  step="0.01"
                  value={discount}
                  onChange={(e) => onDiscount(Number(e.target.value))}
                />
              </label>
              <label className="inspector-field">
                <span>Optimise cost for</span>
                <select value={objScope} onChange={(e) => onObjScope(e.target.value as Scope)}>
                  <option value="company">Each company (independent targets)</option>
                  <option value="system">The whole economy (one shared target)</option>
                  <option value="facility">Each facility (independent targets)</option>
                </select>
              </label>
              <p className="muted">
                The objective is always to minimise total discounted cost. This sets the level the
                emission targets bind at: <strong>whole economy</strong> pools every target into one
                shared cap (companies trade off to the cheapest system-wide outcome);{" "}
                <strong>each company / facility</strong> keeps targets separate, so the solve
                decomposes into independent per-company (or per-facility) cost minimisations.
                Per-company objective (cost / profit), budgets and minimum production are edited per
                company in the model.
              </p>
            </section>
          )}
          {section === "snapshots" && (
            <section className="card">
              <h3>Snapshots (time resolution)</h3>
              <p className="muted">
                Runs are <strong>annual</strong> — one snapshot per period. Temporal data already
                uses the static + wide-temporal split (rows = years, columns = item names), so
                sub-annual weighted snapshots slot onto the same axis when enabled.
              </p>
              <label className="inspector-field">
                <span>Resolution</span>
                <select disabled value="annual">
                  <option value="annual">Annual (per period)</option>
                </select>
              </label>
            </section>
          )}
          {section === "solver" && (
            <section className="card">
              <h3>Solver</h3>
              <p className="muted">HiGHS via linopy (our engine — not PyPSA). Global scaling on
                for numerical stability; MIP gap / time limit are server-controlled.</p>
            </section>
          )}
          {section === "policy" && (
            <section className="card">
              <h3>Policy</h3>
              <p className="muted">Carbon price / tradable ETS and energy markets (KEPCO / PPA /
                JKM) are modelled as Markets — add them in Data or the Model canvas.</p>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
