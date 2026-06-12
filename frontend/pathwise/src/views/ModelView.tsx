import { useEffect, useState } from "react";
import { DetailPanel } from "../features/detail/DetailPanel";
import { LeftRail, type RailLibrarySector } from "../layout/LeftRail";
import { Resizer } from "../layout/Resizer";
import { TopologyCanvas } from "../features/topology/TopologyCanvas";
import { FlowView } from "../features/flow/FlowView";
import { MaccPanel } from "../features/macc/MaccPanel";
import { WorkbookTable, type ColumnMeta } from "../features/tables/WorkbookTable";
import { SearchableSelect } from "../features/controls/SearchableSelect";
import type { SchemaMap } from "../features/controls/CreateComponentModal";
import {
  addFacilityWithTech,
  addMeasure,
  addTransitionOption,
  applyMacc,
  ensureTechnology,
  maccNames,
} from "../lib/graph";
import { insertTemplate } from "../lib/api/session";
import { listLibrary, loadSector, type SectorLibrary } from "../lib/api/library";
import type { Cell, ConfigBundle, Row, Selection, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  config: ConfigBundle | null;
  sessionId: string | null;
  /** Adopt a model the backend already holds (no re-sync needed). */
  adoptServerModel: (wb: Workbook) => void;
  leftW: number;
  setLeftW: (w: number) => void;
}

const ID_COL: Record<string, string> = {
  processes: "process_id",
  commodities: "commodity_id",
  markets: "market_id",
  storage: "storage_id",
  technologies: "technology_id",
  measures: "measure_id",
  impacts: "impact_id",
};

const coerce = (v: string): Cell =>
  v === "" ? null : Number.isNaN(Number(v)) || v.trim() === "" ? v : Number(v);

/** Bottom dock when an item is selected: ALL the time series this item owns
 *  (`<sheet>_t__<attr>` columns named after the item) in ONE table — a `year`
 *  row index with one editable column per temporal attribute. */
function ItemTimeSeries({
  workbook,
  selected,
  onChange,
}: {
  workbook: Workbook;
  selected: Selection;
  onChange: (wb: Workbook) => void;
}) {
  const sheets = Object.keys(workbook).filter(
    (k) => k.startsWith(`${selected.sheet}_t__`) && (workbook[k] ?? []).some((r) => selected.id in r),
  );
  if (!sheets.length) {
    return (
      <div className="muted" style={{ padding: "8px 4px" }}>
        No time series for <strong>{selected.id}</strong>. In the panel on the right, click
        <em> ⟳ temporal</em> on any value to make it vary by year.
      </div>
    );
  }
  const attrOf = (ts: string) => ts.split("_t__")[1];
  const years = [
    ...new Set(sheets.flatMap((ts) => (workbook[ts] ?? []).map((r) => Number(r.year)))),
  ].sort((a, b) => a - b);
  const valueAt = (ts: string, year: number) => {
    const row = (workbook[ts] ?? []).find((r) => Number(r.year) === year);
    return row && row[selected.id] != null ? String(row[selected.id]) : "";
  };
  const editCell = (ts: string, year: number, value: string) =>
    onChange({
      ...workbook,
      [ts]: (workbook[ts] ?? []).map((r) =>
        Number(r.year) === year ? { ...r, [selected.id]: coerce(value) } : r,
      ),
    });
  // Remove this item's temporal series: drop its column from the sheet; if no
  // other item uses the sheet, drop the sheet. The static value (right) remains.
  const removeSeries = (ts: string) => {
    const stripped = (workbook[ts] ?? []).map((r) => {
      const { [selected.id]: _drop, ...rest } = r;
      return rest;
    });
    const stillUsed = stripped.some((r) => Object.keys(r).some((k) => k !== "year"));
    const next = { ...workbook };
    if (stillUsed) next[ts] = stripped;
    else delete next[ts];
    onChange(next);
  };
  return (
    <div className="table-wrap" style={{ maxWidth: 640 }}>
      <table>
        <thead>
          <tr>
            <th>year</th>
            {sheets.map((ts) => (
              <th key={ts}>
                {attrOf(ts)}{" "}
                <button
                  className="ghost ts-del"
                  title={`remove the ${attrOf(ts)} time series (revert to static)`}
                  onClick={() => removeSeries(ts)}
                >
                  ✕
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((y) => (
            <tr key={y}>
              <td>{y}</td>
              {sheets.map((ts) => (
                <td key={ts}>
                  <input value={valueAt(ts, y)} onChange={(e) => editCell(ts, y, e.target.value)} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Model view — the single editing surface. Canvas (top) + the selected item's
 *  STATIC values in the right rail and its TIME SERIES in the bottom dock, shown
 *  together; selecting a group/temporal in the tree shows its table in the dock. */
export function ModelView({
  workbook,
  setWorkbook,
  config,
  sessionId,
  adoptServerModel,
  leftW,
  setLeftW,
}: Props) {
  const [selected, setSelected] = useState<Selection | null>(null);
  const [activeSheet, setActiveSheet] = useState<string | null>(null);
  const [mode, setMode] = useState<"canvas" | "flow">("canvas");
  const [rightW, setRightW] = useState(300);
  const [dockH, setDockH] = useState(260);
  const schema = config?.domains[0]?.schema ?? {};

  // Prebuilt facility/chain templates (sector library) for the rail.
  const [library, setLibrary] = useState<SectorLibrary[]>([]);
  const [libPreview, setLibPreview] = useState<{
    sector: string;
    kind: "facility" | "chain";
    id: string;
  } | null>(null);
  useEffect(() => {
    listLibrary()
      .then((entries) => Promise.all(entries.map((e) => loadSector(e.sector))))
      .then(setLibrary)
      .catch(() => setLibrary([]));
  }, []);
  const railLibrary: RailLibrarySector[] = library.map((lib) => ({
    sector: lib.sector,
    label: lib.label,
    chains: (lib.chains ?? []).map((c) => ({ id: c.chain_id, label: c.label })),
    facilities: lib.facilities.map((f) => ({ id: f.facility_id, label: f.label })),
  }));

  // "Add technology as…" dialog: from a tech drag (tech known, choose mode +
  // facility) or from a facility's context menu (facility known, choose tech).
  const [techAdd, setTechAdd] = useState<{
    tech?: string;
    process?: string;
    x?: number;
    y?: number;
  } | null>(null);
  // "Add MACC measure" dialog, opened from a facility or stream context menu.
  const [measureAdd, setMeasureAdd] = useState<{
    kind: "process" | "commodity";
    entityId: string;
  } | null>(null);
  // "Deploy MACC" picker (right-click a facility; only when MACCs exist).
  const [setApply, setSetApply] = useState<string | null>(null);

  // Template inserts happen SERVER-side (the session owns the model); the
  // frontend adopts the refreshed model and selects what was created.
  const insert = async (body: {
    sector: string;
    kind: "facility" | "chain";
    id: string;
    mode?: "initial" | "replacement";
    replace_process?: string;
    x?: number;
    y?: number;
  }) => {
    if (!sessionId) return;
    const { model, created } = await insertTemplate(sessionId, body);
    adoptServerModel(model);
    const last = created[created.length - 1];
    if (!last) return;
    if (body.mode === "replacement")
      openItem({ sheet: "technologies", idCol: "technology_id", id: last });
    else openItem({ sheet: "processes", idCol: "process_id", id: last });
  };

  const addFromLibrary = (opts: { mode: "initial" | "replacement"; replaceProcess?: string }) => {
    if (!libPreview) return;
    void insert({ ...libPreview, mode: opts.mode, replace_process: opts.replaceProcess });
    setLibPreview(null);
  };

  // A library facility dragged onto the canvas (payload `libfac:<sector>/<id>`).
  const dropLibraryFacility = (key: string, x: number, y: number) => {
    const [sector, fid] = key.split("/", 2);
    if (sector && fid) void insert({ sector, kind: "facility", id: fid, x, y });
  };

  // Table columns = schema columns ∪ keys present in the rows, so optional
  // columns (e.g. impact_caps `intensity` / `soft` / `penalty`) are always
  // editable even when the rows don't yet carry them.
  const columnsFor = (sheet: string): string[] | undefined => {
    const schemaCols = Object.keys(
      (schema as Record<string, { columns?: Record<string, unknown> }>)[sheet]?.columns ?? {},
    );
    if (!schemaCols.length) return undefined;
    const rowCols = new Set((workbook[sheet] ?? []).flatMap((r) => Object.keys(r)));
    return [...new Set([...schemaCols, ...rowCols])];
  };

  const openItem = (s: Selection) => {
    setSelected(s);
    setActiveSheet(null);
  };
  const openGroup = (s: string) => {
    setActiveSheet(s);
    setSelected(null);
  };
  const closeDock = () => {
    setSelected(null);
    setActiveSheet(null);
  };

  const toggle = (sheet: string, idCol: string, id: string, enabled: boolean) =>
    setWorkbook({
      ...workbook,
      [sheet]: (workbook[sheet] ?? []).map((r) =>
        String(r[idCol] ?? "") === id ? { ...r, enabled } : r,
      ),
    });

  const toggleAll = (sheet: string, _idCol: string, enabled: boolean) =>
    setWorkbook({
      ...workbook,
      [sheet]: (workbook[sheet] ?? []).map((r) => ({ ...r, enabled })),
    });

  const toggleIds = (sheet: string, idCol: string, ids: string[], enabled: boolean) => {
    const set = new Set(ids);
    setWorkbook({
      ...workbook,
      [sheet]: (workbook[sheet] ?? []).map((r) =>
        set.has(String(r[idCol] ?? "")) ? { ...r, enabled } : r,
      ),
    });
  };

  const addRow = (sheet: string) => {
    if (sheet === "maccs") {
      const taken = new Set(maccNames(workbook));
      let k = 1;
      let name = "MACC 1";
      while (taken.has(name)) name = `MACC ${++k}`;
      openItem({ sheet: "maccs", idCol: "macc", id: name });
      return;
    }
    const idCol = ID_COL[sheet] ?? "id";
    const rows = workbook[sheet] ?? [];
    const base = `new_${sheet.replace(/s$/, "")}`;
    let k = rows.length + 1;
    let id = `${base}_${k}`;
    const taken = new Set(rows.map((r) => String(r[idCol] ?? "")));
    while (taken.has(id)) id = `${base}_${++k}`;
    const blank: Row = { [idCol]: id };
    setWorkbook({ ...workbook, [sheet]: [...rows, blank] });
    openItem({ sheet, idCol, id });
  };

  const dockOpen = selected != null || activeSheet != null;
  const maccSelected = selected?.sheet === "maccs" ? selected.id : null;

  return (
    <div className="body-row">
      <LeftRail
        workbook={workbook}
        selected={selected}
        activeSheet={activeSheet ?? ""}
        onItem={openItem}
        onGroup={openGroup}
        onToggle={toggle}
        onToggleAll={toggleAll}
        onToggleIds={toggleIds}
        onAdd={addRow}
        library={railLibrary}
        onLibraryItem={(sector, kind, id) => setLibPreview({ sector, kind, id })}
        draggable
        width={leftW}
        schema={schema as SchemaMap}
      />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        <div className="model-banner">
          <div className="view-toggle">
            {(["canvas", "flow"] as const).map((m) => (
              <button key={m} className={`tab${mode === m ? " active" : ""}`} onClick={() => setMode(m)}>
                {m[0].toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
          {mode === "canvas" &&
            "Drag a component onto the canvas to place it; drag a node to move it. Click an item to edit (inputs/outputs in the detail panel)."}
          {mode === "flow" &&
            "Process route by stage (● current · ○ alternative). Toggle aggregated / per-facility; click a technology to edit."}
        </div>
        <div className="canvas-pane">
          {mode === "canvas" && (
            <TopologyCanvas
              workbook={workbook}
              editable
              onChange={setWorkbook}
              onSelect={openItem}
              onDropLibrary={dropLibraryFacility}
              onDropTech={(tech, x, y) => setTechAdd({ tech, x, y })}
              onAddTransition={(pid) => setTechAdd({ process: pid })}
              onAddMeasure={(kind, entityId) => {
                if (kind === "process" || kind === "commodity") setMeasureAdd({ kind, entityId });
              }}
              onApplySet={maccNames(workbook).length ? (pid) => setSetApply(pid) : undefined}
            />
          )}
          {mode === "flow" && <FlowView workbook={workbook} onSelect={openItem} />}
        </div>
        {dockOpen && (
          <div className="editor-dock" style={{ flex: `0 0 ${dockH}px` }}>
            <Resizer width={dockH} setWidth={setDockH} side="top" min={80} max={700} />
            <div className="dock-head">
              <strong>{selected ? selected.id : activeSheet}</strong>
              <span className="rail-count">
                {maccSelected ? "MACC — measures, deployment, curve" : selected ? "time series" : "table"}
              </span>
              <span className="spacer" />
              <button className="ghost" onClick={closeDock} title="close editor">
                ✕
              </button>
            </div>
            <div className="dock-body">
              {maccSelected ? (
                <MaccPanel workbook={workbook} macc={maccSelected} onChange={setWorkbook} />
              ) : selected ? (
                <ItemTimeSeries workbook={workbook} selected={selected} onChange={setWorkbook} />
              ) : (
                activeSheet && (
                  <WorkbookTable
                    rows={workbook[activeSheet] ?? []}
                    columns={columnsFor(activeSheet)}
                    workbook={workbook}
                    sheet={activeSheet}
                    columnMeta={
                      (schema as Record<string, { columns?: Record<string, ColumnMeta> }>)[
                        activeSheet
                      ]?.columns
                    }
                    schema={schema as SchemaMap}
                    onWorkbook={setWorkbook}
                    onChange={(rows) => setWorkbook({ ...workbook, [activeSheet]: rows })}
                  />
                )
              )}
            </div>
          </div>
        )}
      </main>
      {selected && !maccSelected && (
        <>
          <Resizer width={rightW} setWidth={setRightW} side="right" min={200} max={600} />
          <aside
            className="right-rail"
            aria-label="Static values"
            style={{ width: rightW, flex: `0 0 ${rightW}px` }}
          >
            <DetailPanel
              workbook={workbook}
              selected={selected}
              schema={schema}
              onChange={setWorkbook}
              onClose={() => setSelected(null)}
            />
          </aside>
        </>
      )}
      {techAdd && (
        <TechAddModal
          workbook={workbook}
          seed={techAdd}
          onClose={() => setTechAdd(null)}
          onApply={(r) => {
            setTechAdd(null);
            if (r.mode === "initial" && r.tech) {
              setWorkbook(
                addFacilityWithTech(workbook, r.tech, techAdd.x ?? 260, techAdd.y ?? 200),
              );
            } else if (r.mode === "transition" && r.tech && r.fromTech) {
              setWorkbook(
                addTransitionOption(ensureTechnology(workbook, r.tech), r.fromTech, r.tech),
              );
              openItem({ sheet: "technologies", idCol: "technology_id", id: r.tech });
            }
          }}
        />
      )}
      {measureAdd && (
        <MeasureModal
          workbook={workbook}
          seed={measureAdd}
          onClose={() => setMeasureAdd(null)}
          onApply={({ scope, processId, ...opts }) => {
            setMeasureAdd(null);
            const baseline = String(
              (workbook.processes ?? []).find((r) => String(r.process_id) === processId)
                ?.baseline_technology ?? "",
            );
            setWorkbook(
              addMeasure(workbook, {
                ...opts,
                facility: scope === "facility" ? processId : undefined,
                technology: scope === "technology" && baseline ? baseline : undefined,
              }),
            );
            if (opts.macc) openItem({ sheet: "maccs", idCol: "macc", id: opts.macc });
            else openGroup("measures");
          }}
        />
      )}
      {setApply && (
        <ApplySetModal
          workbook={workbook}
          processId={setApply}
          onClose={() => setSetApply(null)}
          onApply={(macc, target) => {
            setSetApply(null);
            setWorkbook(applyMacc(workbook, macc, target));
            openItem({ sheet: "maccs", idCol: "macc", id: macc });
          }}
        />
      )}
      {libPreview && (
        <LibraryPreview
          library={library}
          preview={libPreview}
          workbook={workbook}
          onAdd={addFromLibrary}
          onClose={() => setLibPreview(null)}
        />
      )}
    </div>
  );
}

/** Template preview card: what it consumes/produces, its alternatives, the
 *  reference its coefficients come from — and HOW to add it: as an initial
 *  (current) facility, or as a replacement OPTION the optimiser may switch an
 *  existing facility into (a transitions-table entry, no new facility). */
function LibraryPreview({
  library,
  preview,
  workbook,
  onAdd,
  onClose,
}: {
  library: SectorLibrary[];
  preview: { sector: string; kind: "facility" | "chain"; id: string };
  workbook: Workbook;
  onAdd: (opts: { mode: "initial" | "replacement"; replaceProcess?: string }) => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"initial" | "replacement">("initial");
  // Replacement targets are TECHNOLOGIES (the option covers every facility
  // running that baseline) — shown with their facility counts.
  const counts = new Map<string, number>();
  for (const r of workbook.processes ?? []) {
    const t = String(r.baseline_technology ?? "");
    if (t) counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  const replaceables = [...counts.entries()].sort();
  const [replaceProcess, setReplaceProcess] = useState<string>("");
  const lib = library.find((l) => l.sector === preview.sector);
  if (!lib) return null;
  const fac =
    preview.kind === "facility"
      ? lib.facilities.find((f) => f.facility_id === preview.id)
      : undefined;
  const chain =
    preview.kind === "chain"
      ? (lib.chains ?? []).find((c) => c.chain_id === preview.id)
      : undefined;
  const item = fac ?? chain;
  if (!item) return null;
  const src = item.source;
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal lib-card" onClick={(e) => e.stopPropagation()}>
        <div className="dock-head">
          <strong>{fac ? fac.label : chain!.label}</strong>
          <span className="rail-count">{fac ? "facility template" : "chain template"}</span>
          <span className="spacer" />
          <button className="ghost" onClick={onClose} title="close">
            ✕
          </button>
        </div>
        {item.description && <p className="muted">{item.description}</p>}
        {fac && (
          <>
            <div className="rail-count">consumes → produces</div>
            <ul className="lib-io">
              {fac.technology.io.map((r, i) => (
                <li key={i}>
                  {r.role === "input" ? "▸ in" : r.role === "output" ? "◂ out" : "⚠ impact"}{" "}
                  {r.target} × {r.coefficient}
                  {r.group ? ` (${r.role === "output" ? "slate" : "blend"} ${r.group})` : ""}
                </li>
              ))}
            </ul>
            {(fac.alternatives ?? []).length > 0 && (
              <p className="muted">
                Alternatives (transitions):{" "}
                {(fac.alternatives ?? []).map((a) => a.technology.technology_id).join(", ")}
              </p>
            )}
            {(fac.measures ?? []).length > 0 && (
              <p className="muted">
                MACC measures (same-system retrofits):{" "}
                {(fac.measures ?? [])
                  .map(
                    (m) =>
                      `${m.label || m.measure_id} (−${Math.round(
                        m.blocks.reduce((s, b) => s + b.reduction, 0) * 100,
                      )}% ${m.target})`,
                  )
                  .join("; ")}
              </p>
            )}
          </>
        )}
        {chain && (
          <p className="muted">
            Stages: {chain.stages.map((st) => st.facility).join(" → ")}. Adding the chain inserts
            every stage, wires the intermediates, and seeds demand.
          </p>
        )}
        <p className="lib-source">
          Source:{" "}
          <a href={src.url} target="_blank" rel="noreferrer">
            {src.name}
          </a>{" "}
          ({src.year}, {src.region ?? "global"} — {src.basis ?? "indicative"})
        </p>
        {src.notes && <p className="muted">{src.notes}</p>}
        {fac && replaceables.length > 0 && (
          <div className="lib-mode">
            <div className="view-toggle">
              {(["initial", "replacement"] as const).map((m) => (
                <button
                  key={m}
                  className={`tab${mode === m ? " active" : ""}`}
                  onClick={() => setMode(m)}
                >
                  {m === "initial" ? "Initial" : "Transition"}
                </button>
              ))}
            </div>
            {mode === "initial" && (
              <p className="muted">
                Adds an <strong>initial facility</strong> that runs from the start.
              </p>
            )}
            {mode === "replacement" && (
              <>
                <label className="inspector-field">
                  <span>Replaces technology</span>
                  <SearchableSelect
                    value={replaceProcess}
                    options={replaceables.map(([t]) => t)}
                    labelOf={(t) => {
                      const n = counts.get(t) ?? 0;
                      return `${t} (${n} facilit${n === 1 ? "y" : "ies"})`;
                    }}
                    onChange={setReplaceProcess}
                  />
                </label>
                <p className="muted">
                  Writes a transitions-table row (chosen technology → this template). The option
                  applies to <em>every</em> facility running that technology; for a multi-stage
                  chain, add one replacement per stage.
                </p>
              </>
            )}
          </div>
        )}
        <button
          disabled={mode === "replacement" && !replaceProcess}
          onClick={() =>
            onAdd(
              mode === "replacement"
                ? { mode, replaceProcess }
                : { mode: "initial" },
            )
          }
        >
          {mode === "replacement" ? "Add as replacement option" : "Add to model"}
        </button>
      </div>
    </div>
  );
}

/** "Add technology as…" — from a tech drag (choose Initial vs Transition + the
 *  facility it may replace) or from a facility's menu (choose the technology). */
function TechAddModal({
  workbook,
  seed,
  onApply,
  onClose,
}: {
  workbook: Workbook;
  seed: { tech?: string; process?: string };
  onApply: (r: { mode: "initial" | "transition"; tech?: string; fromTech?: string }) => void;
  onClose: () => void;
}) {
  const facilities = (workbook.processes ?? []).map((r) => ({
    id: String(r.process_id ?? ""),
    baseline: String(r.baseline_technology ?? ""),
  }));
  // Transitions are TECHNOLOGY-level: pick the technology being replaced; the
  // option then applies to every facility running it.
  const baselineCounts = new Map<string, number>();
  for (const f of facilities)
    baselineCounts.set(f.baseline, (baselineCounts.get(f.baseline) ?? 0) + 1);
  const replaceables = [...baselineCounts.entries()].sort();
  const techs = (workbook.technologies ?? []).map((r) => String(r.technology_id ?? ""));
  const [mode, setMode] = useState<"initial" | "transition">(seed.process ? "transition" : "initial");
  const seedBaseline = facilities.find((f) => f.id === seed.process)?.baseline ?? "";
  const [fromTech, setFromTech] = useState(seedBaseline);
  const [tech, setTech] = useState(seed.tech ?? "");
  const chosenTech = (seed.tech ?? tech).trim();
  const ready = mode === "initial" ? Boolean(chosenTech) : Boolean(chosenTech && fromTech);
  const countLabel = (t: string) => {
    const n = baselineCounts.get(t) ?? 0;
    return `${t} (${n} facilit${n === 1 ? "y" : "ies"})`;
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="dock-head">
          <strong>Add technology{seed.tech ? ` · ${seed.tech}` : ""}</strong>
          <span className="spacer" />
          <button className="ghost" onClick={onClose} title="close">
            ✕
          </button>
        </div>
        {!seed.process && (
          <>
            <div className="view-toggle">
              {(["initial", "transition"] as const).map((m) => (
                <button
                  key={m}
                  className={`tab${mode === m ? " active" : ""}`}
                  onClick={() => setMode(m)}
                >
                  {m === "initial" ? "Initial" : "Transition"}
                </button>
              ))}
            </div>
            <p className="muted">
              {mode === "initial"
                ? "Initial — new facility running it from the start (shown on the map)."
                : "Transition — future option a facility may switch into (○ in the tree, not on the map)."}
            </p>
          </>
        )}
        {!seed.tech && (
          <label className="inspector-field">
            <span>Technology (search, or type a new name)</span>
            <SearchableSelect
              value={tech}
              options={techs}
              onChange={setTech}
              onCreate={setTech}
              placeholder="search or type a new technology id…"
            />
          </label>
        )}
        {mode === "transition" && (
          <label className="inspector-field">
            <span>Replaces technology (in the topology)</span>
            <SearchableSelect
              value={fromTech}
              options={replaceables.map(([t]) => t)}
              labelOf={countLabel}
              onChange={setFromTech}
              disabled={Boolean(seed.process)}
              hint="add a facility first"
            />
          </label>
        )}
        {mode === "transition" && fromTech && (
          <p className="muted">
            Writes a transitions row {fromTech} → {chosenTech || "…"}; the option applies to every
            facility running {fromTech}. Set its switch cost and "Available from" year in the
            technology's detail panel.
          </p>
        )}
        <button disabled={!ready} onClick={() => onApply({ mode, tech: chosenTech, fromTech })}>
          {mode === "initial" ? "Add as initial facility" : "Add as transition option"}
        </button>
      </div>
    </div>
  );
}

/** "Add MACC measure" — a small retrofit on a facility's existing technology:
 *  pick the lever (efficiency / abatement), the target, and one starter block. */
function MeasureModal({
  workbook,
  seed,
  onApply,
  onClose,
}: {
  workbook: Workbook;
  seed: { kind: "process" | "commodity"; entityId: string };
  onApply: (opts: {
    processId: string;
    type: "energy_efficiency" | "emission_reduction" | "environmental";
    target: string;
    lifetime?: number;
    reduction: number;
    capex: number;
    macc?: string;
    scope: "facility" | "technology" | "none";
  }) => void;
  onClose: () => void;
}) {
  const baselineOf = (pid: string) =>
    String(
      (workbook.processes ?? []).find((r) => String(r.process_id) === pid)?.baseline_technology ??
        "",
    );
  const inputsOf = (tech: string) =>
    (workbook.io ?? [])
      .filter((r) => String(r.technology_id) === tech && String(r.role ?? "input") === "input")
      .map((r) => String(r.target));
  const impacts = (workbook.impacts ?? []).map((r) => String(r.impact_id ?? ""));
  const consumers = (workbook.processes ?? [])
    .map((r) => String(r.process_id ?? ""))
    .filter((pid) => inputsOf(baselineOf(pid)).includes(seed.entityId));

  const [processId, setProcessId] = useState(
    seed.kind === "process" ? seed.entityId : (consumers[0] ?? ""),
  );
  const [type, setType] = useState<"energy_efficiency" | "emission_reduction" | "environmental">(
    seed.kind === "commodity" ? "energy_efficiency" : "energy_efficiency",
  );
  const [target, setTarget] = useState(seed.kind === "commodity" ? seed.entityId : "");
  const [reduction, setReduction] = useState(0.1);
  const [capex, setCapex] = useState(0);
  const [lifetime, setLifetime] = useState(15);
  const [scope, setScope] = useState<"facility" | "technology" | "none">("facility");
  const [maccName, setMaccName] = useState("");
  const targets = type === "energy_efficiency" ? inputsOf(baselineOf(processId)) : impacts;
  const ready = Boolean(target && reduction > 0 && (scope === "none" || processId));

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="dock-head">
          <strong>Add MACC measure</strong>
          <span className="rail-count">retrofit of the same system</span>
          <span className="spacer" />
          <button className="ghost" onClick={onClose} title="close">
            ✕
          </button>
        </div>
        <label className="inspector-field">
          <span>Applies to (facility)</span>
          <select
            value={processId}
            disabled={seed.kind === "process"}
            onChange={(e) => setProcessId(e.target.value)}
          >
            {(seed.kind === "process"
              ? [seed.entityId]
              : consumers
            ).map((pid) => (
              <option key={pid} value={pid}>
                {pid}
              </option>
            ))}
          </select>
        </label>
        <label className="inspector-field">
          <span>Lever</span>
          <select
            value={type}
            disabled={seed.kind === "commodity"}
            onChange={(e) => {
              setType(e.target.value as typeof type);
              setTarget("");
            }}
          >
            <option value="energy_efficiency">Energy efficiency (cuts an input)</option>
            <option value="emission_reduction">Emission reduction (cuts an impact)</option>
            <option value="environmental">Environmental (non-CO2 impact)</option>
          </select>
        </label>
        <label className="inspector-field">
          <span>{type === "energy_efficiency" ? "Input it cuts" : "Impact it cuts"}</span>
          <select
            value={target}
            disabled={seed.kind === "commodity"}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">— choose —</option>
            {targets.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <div className="modal-two-col">
          <label className="inspector-field">
            <span>Reduction (0–1)</span>
            <input
              type="number"
              min={0.01}
              max={1}
              step={0.01}
              value={reduction}
              onChange={(e) => setReduction(Number(e.target.value))}
            />
          </label>
          <label className="inspector-field">
            <span>Block capex</span>
            <input type="number" value={capex} onChange={(e) => setCapex(Number(e.target.value))} />
          </label>
        </div>
        <label className="inspector-field">
          <span>Lifetime (yr)</span>
          <input type="number" min={1} value={lifetime} onChange={(e) => setLifetime(Number(e.target.value))} />
        </label>
        <div className="lib-mode">
          <label>
            <input
              type="radio"
              checked={scope === "facility"}
              onChange={() => setScope("facility")}
            />{" "}
            This facility only ({processId || "…"})
          </label>
          <label>
            <input
              type="radio"
              checked={scope === "technology"}
              onChange={() => setScope("technology")}
            />{" "}
            Every facility running <strong>{baselineOf(processId) || "…"}</strong> (each adopts
            independently)
          </label>
          <label>
            <input type="radio" checked={scope === "none"} onChange={() => setScope("none")} />{" "}
            Catalogue only — deploy later by bundling it into a MACC
          </label>
        </div>
        <label className="inspector-field">
          <span>Add to MACC (optional bundle — deploy it in macc_links)</span>
          <input
            value={maccName}
            onChange={(e) => setMaccName(e.target.value)}
            placeholder="e.g. EAF retrofits"
          />
        </label>
        <p className="muted">
          Creates one cost-curve block (capex may be negative, e.g. subsidised); add more blocks in
          the measure_blocks table. The MACC tab in the bottom panel shows the curve. Adoption is
          always per facility — a bundle never decides as a group.
        </p>
        <button
          disabled={!ready}
          onClick={() =>
            onApply({
              processId,
              type,
              target,
              lifetime,
              reduction,
              capex,
              macc: maccName.trim() || undefined,
              scope,
            })
          }
        >
          Add measure
        </button>
      </div>
    </div>
  );
}

/** Deploy an existing MACC (bundle of measures) on a facility or on its whole
 *  technology. Each linked facility still adopts independently. */
function ApplySetModal({
  workbook,
  processId,
  onApply,
  onClose,
}: {
  workbook: Workbook;
  processId: string;
  onApply: (macc: string, target: { facility?: string; technology?: string }) => void;
  onClose: () => void;
}) {
  const names = maccNames(workbook);
  const baseline = String(
    (workbook.processes ?? []).find((r) => String(r.process_id) === processId)
      ?.baseline_technology ?? "",
  );
  const [macc, setMacc] = useState(names[0] ?? "");
  const [scope, setScope] = useState<"facility" | "technology">("facility");
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="dock-head">
          <strong>Deploy MACC · {processId}</strong>
          <span className="spacer" />
          <button className="ghost" onClick={onClose} title="close">
            ✕
          </button>
        </div>
        <label className="inspector-field">
          <span>MACC (bundle of measures)</span>
          <SearchableSelect value={macc} options={names} onChange={setMacc} />
        </label>
        <div className="lib-mode">
          <label>
            <input type="radio" checked={scope === "facility"} onChange={() => setScope("facility")} />{" "}
            This facility only
          </label>
          <label>
            <input
              type="radio"
              checked={scope === "technology"}
              onChange={() => setScope("technology")}
            />{" "}
            Every facility running <strong>{baseline}</strong>
          </label>
        </div>
        <p className="muted">
          Writes a macc_links row. Each linked facility receives its own copy of the MACC's
          measures and adopts them independently.
        </p>
        <button
          disabled={!macc}
          onClick={() =>
            onApply(
              macc,
              scope === "technology" && baseline ? { technology: baseline } : { facility: processId },
            )
          }
        >
          Deploy MACC
        </button>
      </div>
    </div>
  );
}
