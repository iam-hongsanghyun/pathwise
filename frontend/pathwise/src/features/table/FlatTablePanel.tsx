// A collapsible, searchable, filterable Excel-like grid at the bottom of a view's
// main panel. Each row is one leaf component of a triggered group (located by its
// sub-group path + name + type); the value columns form a real spreadsheet grid:
// rectangular multi-cell selection (drag / shift-click / arrow keys), copy + cut +
// paste of TSV (so it round-trips with Excel/Sheets), delete-to-clear, and inline
// editing. Static cells show a plain value (double-click or Enter to edit, like a
// spreadsheet); temporal cells keep the green click-to-edit TemporalValue. Built on
// headless @tanstack/react-table for search/filter/sort over a plain <table>.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type ColumnFiltersState,
  type SortingState,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { TemporalValue, type TemporalVal } from "../controls/TemporalValue";
import { InfoTooltip } from "../controls/InfoTooltip";
import { fieldMeta } from "../component/fieldMeta";
import { Resizer } from "../../layout/Resizer";
import type { CellVal, FlatColumn, FlatResult, FlatRow } from "./flatten";
import type { Workbook } from "../../types";

interface Props {
  result: FlatResult;
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  baseYear: number;
  periods: number[];
  height: number;
  setHeight: (h: number) => void;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
}

type Cell = { r: number; c: number };
type Range = { a: Cell; f: Cell };

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const isFormEl = (el: Element | null) => !!el && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName);

/** The selected rectangle in row/col index space (inclusive). */
function rect(s: Range) {
  return {
    r0: Math.min(s.a.r, s.f.r),
    r1: Math.max(s.a.r, s.f.r),
    c0: Math.min(s.a.c, s.f.c),
    c1: Math.max(s.a.c, s.f.c),
  };
}

/** A cell's value as plain text (for display + copy). Temporal "varies" and recipe
 *  cells have no single scalar, so they copy as empty. */
function cellText(col: FlatColumn, wb: Workbook, id: string): string {
  if (col.kind === "streams") return "";
  const v = col.get(wb, id);
  if (v == null) return "";
  if (typeof v === "object") return "";
  return String(v);
}

/** Write a raw string into a cell, coercing to the column's kind. Returns the
 *  (possibly unchanged) workbook so writes chain across a paste rectangle. */
function writeCell(col: FlatColumn, wb: Workbook, id: string, raw: string): Workbook {
  if (col.kind === "streams") return wb; // recipe cells aren't paste targets
  const t = raw.trim();
  if (col.kind === "number" || col.kind === "temporal") {
    if (t === "") return col.set(wb, id, null);
    const n = Number(t);
    return Number.isFinite(n) ? col.set(wb, id, n) : wb; // ignore non-numeric
  }
  if (col.kind === "enum") {
    if (t === "") return col.set(wb, id, null);
    return (col.options ?? []).includes(t) ? col.set(wb, id, t) : wb;
  }
  return col.set(wb, id, t === "" ? null : t); // text
}

export function FlatTablePanel({ result, workbook, setWorkbook, baseYear, periods, height, setHeight, open, onToggle, onClose }: Props) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [sel, setSel] = useState<Range | null>(null);
  const [editing, setEditing] = useState<Cell | null>(null);
  const dragging = useRef(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const activeTd = useRef<HTMLTableCellElement>(null);

  // Headless table only for header sort/filter + the filtered+sorted row order; the
  // body is rendered by hand so each value cell knows its (row, col) grid position.
  const columns = useMemo(
    () =>
      result.columns.map((col) => ({
        id: col.key,
        header: col.label,
        accessorFn: (r: FlatRow): CellVal | string => {
          const v = col.get(workbook, r.id);
          return v == null ? "" : typeof v === "object" ? "varies" : v;
        },
      })),
    [result, workbook],
  );

  const table = useReactTable({
    data: result.rows,
    columns,
    state: { globalFilter, columnFilters, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onColumnFiltersChange: setColumnFilters,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const vcols = result.columns;
  const rows = table.getRowModel().rows;
  const nRows = rows.length;
  const nCols = vcols.length;

  const inSel = (r: number, c: number): boolean => {
    if (!sel) return false;
    const q = rect(sel);
    return r >= q.r0 && r <= q.r1 && c >= q.c0 && c <= q.c1;
  };
  const isActive = (r: number, c: number) => !!sel && sel.f.r === r && sel.f.c === c;

  // ── Selection: drag, shift-extend ───────────────────────────────────────────
  const focusBody = () => bodyRef.current?.focus({ preventScroll: true });
  const startSel = (r: number, c: number, e: React.MouseEvent) => {
    if (editing && (editing.r !== r || editing.c !== c)) setEditing(null);
    if (e.shiftKey && sel) setSel({ a: sel.a, f: { r, c } });
    else setSel({ a: { r, c }, f: { r, c } });
    dragging.current = true;
    focusBody();
  };
  const extendSel = (r: number, c: number) => {
    if (dragging.current && sel) setSel((s) => (s ? { a: s.a, f: { r, c } } : s));
  };
  useEffect(() => {
    const up = () => (dragging.current = false);
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  // Keep the active cell scrolled into view on keyboard navigation.
  useEffect(() => {
    activeTd.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [sel?.f.r, sel?.f.c]);

  // Drop a selection that no longer fits after filtering / column changes.
  useEffect(() => {
    if (sel && (sel.f.r >= nRows || sel.f.c >= nCols)) setSel(null);
  }, [nRows, nCols, sel]);

  // ── Clipboard (native events so we read clipboardData synchronously) ─────────
  const copyToClipboard = useCallback(
    (e: React.ClipboardEvent) => {
      if (!sel || editing || isFormEl(document.activeElement)) return;
      const q = rect(sel);
      const lines: string[] = [];
      for (let r = q.r0; r <= q.r1; r++) {
        const cells: string[] = [];
        for (let c = q.c0; c <= q.c1; c++) cells.push(cellText(vcols[c], workbook, rows[r].original.id));
        lines.push(cells.join("\t"));
      }
      e.preventDefault();
      e.clipboardData.setData("text/plain", lines.join("\n"));
    },
    [sel, editing, vcols, workbook, rows],
  );

  const clearRange = useCallback(() => {
    if (!sel) return;
    const q = rect(sel);
    let wb = workbook;
    for (let r = q.r0; r <= q.r1; r++) for (let c = q.c0; c <= q.c1; c++) wb = writeCell(vcols[c], wb, rows[r].original.id, "");
    setWorkbook(wb);
  }, [sel, workbook, vcols, rows, setWorkbook]);

  const onPaste = (e: React.ClipboardEvent) => {
    if (!sel || editing || isFormEl(document.activeElement)) return;
    const text = e.clipboardData.getData("text/plain");
    if (!text) return;
    e.preventDefault();
    const grid = text.replace(/\r/g, "").split("\n").map((l) => l.split("\t"));
    if (grid.length && grid[grid.length - 1].length === 1 && grid[grid.length - 1][0] === "") grid.pop();
    if (!grid.length) return;
    const q = rect(sel);
    let wb = workbook;
    for (let i = 0; i < grid.length; i++) {
      const r = q.r0 + i;
      if (r >= nRows) break;
      for (let j = 0; j < grid[i].length; j++) {
        const c = q.c0 + j;
        if (c >= nCols) break;
        wb = writeCell(vcols[c], wb, rows[r].original.id, grid[i][j]);
      }
    }
    setWorkbook(wb);
    // Reselect the block that landed, so the user sees the result.
    setSel({
      a: { r: q.r0, c: q.c0 },
      f: { r: Math.min(q.r0 + grid.length - 1, nRows - 1), c: Math.min(q.c0 + (grid[0]?.length ?? 1) - 1, nCols - 1) },
    });
  };

  const onCut = (e: React.ClipboardEvent) => {
    if (!sel || editing || isFormEl(document.activeElement)) return;
    copyToClipboard(e);
    clearRange();
  };

  // ── Keyboard: navigate, extend, edit, clear ─────────────────────────────────
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (editing || isFormEl(document.activeElement)) return;
    if (!sel) return;
    if (e.metaKey || e.ctrlKey) return; // let copy/cut/paste events fire
    const move = (dr: number, dc: number) => {
      e.preventDefault();
      const f = { r: clamp(sel.f.r + dr, 0, nRows - 1), c: clamp(sel.f.c + dc, 0, nCols - 1) };
      setSel(e.shiftKey ? { a: sel.a, f } : { a: f, f });
    };
    switch (e.key) {
      case "ArrowUp": return move(-1, 0);
      case "ArrowDown": return move(1, 0);
      case "ArrowLeft": return move(0, -1);
      case "ArrowRight": return move(0, 1);
      case "Tab": return move(0, e.shiftKey ? -1 : 1);
      case "Enter":
      case "F2": {
        const col = vcols[sel.f.c];
        if (col.kind !== "temporal" && col.kind !== "streams") {
          e.preventDefault();
          setEditing({ ...sel.f });
        }
        return;
      }
      case "Delete":
      case "Backspace":
        e.preventDefault();
        return clearRange();
    }
  };

  // ── Cell renderers ──────────────────────────────────────────────────────────
  const StaticEditor = ({ col, id, r, c }: { col: FlatColumn; id: string; r: number; c: number }) => {
    const [draft, setDraft] = useState(cellText(col, workbook, id));
    const moveTo = (rr: number, cc: number) => setSel({ a: { r: rr, c: cc }, f: { r: rr, c: cc } });
    const commit = (dr: number) => {
      setWorkbook(writeCell(col, workbook, id, draft));
      setEditing(null);
      moveTo(clamp(r + dr, 0, nRows - 1), c);
      focusBody();
    };
    const onKey = (e: React.KeyboardEvent) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); commit(1); }
      else if (e.key === "Escape") { e.preventDefault(); setEditing(null); focusBody(); }
      else if (e.key === "Tab") {
        e.preventDefault();
        setWorkbook(writeCell(col, workbook, id, draft));
        setEditing(null);
        moveTo(r, clamp(c + (e.shiftKey ? -1 : 1), 0, nCols - 1));
        focusBody();
      }
    };
    if (col.kind === "enum") {
      return (
        <select className="flat-cell-input" autoFocus value={draft} onChange={(ev) => setDraft(ev.target.value)} onBlur={() => commit(0)} onKeyDown={onKey}>
          <option value="">—</option>
          {(col.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    }
    return (
      <input
        className="flat-cell-input"
        autoFocus
        type={col.kind === "number" ? "number" : "text"}
        value={draft}
        onChange={(ev) => setDraft(ev.target.value)}
        onBlur={() => commit(0)}
        onKeyDown={onKey}
        onFocus={(ev) => ev.currentTarget.select()}
      />
    );
  };

  const StreamsCell = ({ col, id, name }: { col: FlatColumn; id: string; name: string }) => {
    const targets = col.streams?.(workbook, id) ?? [];
    if (targets.length === 0) return <span className="muted">—</span>;
    return (
      <div className="flat-streams">
        {targets.map((target) => (
          <span key={target} className="flat-stream">
            <span className="flat-stream-name">{target}</span>
            <TemporalValue
              value={(col.streamGet?.(workbook, id, target) as TemporalVal | null) ?? null}
              onChange={(v) => col.streamSet && setWorkbook(col.streamSet(workbook, id, target, v))}
              label={`${name} · ${col.label} · ${target}`}
              baseYear={baseYear}
              periods={periods}
              variant="text"
              placeholder="0"
            />
          </span>
        ))}
      </div>
    );
  };

  const renderCell = (col: FlatColumn, r: number, c: number, id: string, name: string) => {
    if (col.kind === "streams") return <StreamsCell col={col} id={id} name={name} />;
    if (col.kind === "temporal")
      return (
        <TemporalValue
          value={(col.get(workbook, id) as TemporalVal | null) ?? null}
          onChange={(v) => setWorkbook(col.set(workbook, id, v))}
          label={`${name} · ${col.label}`}
          unit={col.unit}
          perYear={col.perYear ?? false}
          baseYear={baseYear}
          periods={periods}
          variant="text"
        />
      );
    if (editing && editing.r === r && editing.c === c) return <StaticEditor col={col} id={id} r={r} c={c} />;
    const txt = cellText(col, workbook, id);
    return <span className="flat-cell-text">{txt === "" ? "—" : txt}</span>;
  };

  const selCount = sel ? (() => { const q = rect(sel); return (q.r1 - q.r0 + 1) * (q.c1 - q.c0 + 1); })() : 0;

  return (
    <div className="flat-table" style={{ height: open ? height : undefined }}>
      {open && <Resizer side="top" width={height} setWidth={setHeight} min={120} max={760} />}
      <div className="flat-table-bar">
        <button className="rail-collapse" title={open ? "collapse" : "expand"} onClick={onToggle}>{open ? "▾" : "▸"}</button>
        <strong style={{ fontSize: "0.8rem" }}>{result.title}</strong>
        <span className="muted" style={{ fontSize: "0.72rem" }}>{result.rows.length} component{result.rows.length === 1 ? "" : "s"}</span>
        {open && (
          <input
            className="flat-table-search"
            placeholder="Search…"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
          />
        )}
        {open && selCount > 0 && (
          <span className="muted" style={{ fontSize: "0.7rem", marginLeft: 8 }} title="Drag / Shift-click / arrows to select · ⌘/Ctrl-C, X, V to copy, cut & paste · Del to clear">
            {selCount > 1 ? `${selCount} cells` : "1 cell"}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <button className="rail-collapse" title="close" onClick={onClose}>✕</button>
      </div>
      {open && (
        <div
          className="flat-table-body"
          ref={bodyRef}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onCopy={copyToClipboard}
          onCut={onCut}
          onPaste={onPaste}
        >
          {result.rows.length === 0 ? (
            <p className="muted" style={{ padding: 12, fontSize: "0.8rem" }}>No components under this group.</p>
          ) : (
            <table className="grid flat-grid" style={{ fontSize: "0.74rem" }}>
              <thead>
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    <th style={{ textAlign: "left" }}>Group</th>
                    <th style={{ textAlign: "left" }}>Name</th>
                    <th style={{ textAlign: "left" }}>Type</th>
                    {hg.headers.map((h) => {
                      const meta = fieldMeta(h.column.id);
                      const sorted = h.column.getIsSorted();
                      return (
                        <th key={h.id} style={{ textAlign: "left", whiteSpace: "nowrap" }}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 3, cursor: "pointer" }} onClick={h.column.getToggleSortingHandler()}>
                            {h.column.columnDef.header as string}
                            {meta?.info && <InfoTooltip text={meta.info} unit={meta.unit} />}
                            {sorted === "asc" ? " ▲" : sorted === "desc" ? " ▼" : ""}
                          </span>
                          <input
                            className="flat-col-filter"
                            placeholder="filter"
                            value={(h.column.getFilterValue() as string) ?? ""}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => h.column.setFilterValue(e.target.value)}
                          />
                        </th>
                      );
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {rows.map((row, r) => (
                  <tr key={row.id}>
                    <td className="muted" style={{ padding: "1px 6px" }}>{row.original.path.join(" / ") || "—"}</td>
                    <td style={{ padding: "1px 6px", fontWeight: 600 }}>{row.original.name}</td>
                    <td className="muted" style={{ padding: "1px 6px" }}>{row.original.type}</td>
                    {vcols.map((col, c) => {
                      const active = isActive(r, c);
                      return (
                        <td
                          key={col.key}
                          ref={active ? activeTd : undefined}
                          className={`cell${inSel(r, c) ? " is-sel" : ""}${active ? " is-active" : ""}`}
                          onMouseDown={(e) => startSel(r, c, e)}
                          onMouseEnter={() => extendSel(r, c)}
                          onDoubleClick={() => col.kind !== "temporal" && col.kind !== "streams" && setEditing({ r, c })}
                        >
                          {renderCell(col, r, c, row.original.id, row.original.name)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
