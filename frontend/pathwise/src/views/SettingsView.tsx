import { useState } from "react";
import { RailList, type RailItem } from "../layout/RailList";
import { Resizer } from "../layout/Resizer";

type Section = "economics" | "snapshots" | "solver" | "policy";

interface Props {
  discount: number;
  onDiscount: (v: number) => void;
  leftW: number;
  setLeftW: (w: number) => void;
}

/** Settings — its own section rail; scenario/run parameters only (model data is
 *  edited in Data). */
export function SettingsView({ discount, onDiscount, leftW, setLeftW }: Props) {
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
              <p className="muted">Per-company objective (cost / profit), budgets, and minimum
                production are edited in Data.</p>
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
