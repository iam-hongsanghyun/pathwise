// A collapsible, searchable, filterable Excel-like grid at the bottom of a view's
// main panel. Each row is one leaf component of a triggered group (located by its
// sub-group path + name + type); each value column edits in place — static cells via
// a token-styled input, temporal cells via the existing TemporalValue editor. Built
// on the headless @tanstack/react-table (search/filter/sort) so it renders a plain
// <table className="grid"> that inherits the app's CSS.

import { useMemo, useState } from "react";
import {
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
  flexRender,
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

const cellStyle: React.CSSProperties = {
  padding: "2px 5px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
  fontSize: "0.74rem",
  width: "100%",
  boxSizing: "border-box",
};

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

export function FlatTablePanel({ result, workbook, setWorkbook, baseYear, periods, height, setHeight, open, onToggle, onClose }: Props) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [sorting, setSorting] = useState<SortingState>([]);

  // A static (text/number/enum) editable cell — display-styled input, not a form box.
  const StaticCell = ({ col, id }: { col: FlatColumn; id: string }) => {
    const v = col.get(workbook, id);
    const str = v == null ? "" : typeof v === "object" ? "·varies·" : String(v);
    if (col.kind === "enum") {
      return (
        <select style={cellStyle} value={str} onChange={(e) => setWorkbook(col.set(workbook, id, e.target.value || null))}>
          <option value="">—</option>
          {(col.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    }
    return (
      <input
        style={cellStyle}
        type={col.kind === "number" ? "number" : "text"}
        value={str}
        onChange={(e) => {
          const raw = e.target.value;
          const next: CellVal = raw === "" ? null : col.kind === "number" ? Number(raw) : raw;
          setWorkbook(col.set(workbook, id, next));
        }}
      />
    );
  };

  // A recipe side (inputs/outputs): each stream name + its coefficient as a click-to-
  // edit value (static or temporal), so the whole recipe lives in one cell.
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

  // Fixed location columns (read-only) + one editable column per FlatColumn.
  const columns = useMemo<ColumnDef<FlatRow>[]>(() => {
    const fixed: ColumnDef<FlatRow>[] = [
      { id: "path", header: "Group", accessorFn: (r) => r.path.join(" / ") || "—", cell: (c) => <span className="muted">{c.getValue<string>()}</span> },
      { id: "name", header: "Name", accessorFn: (r) => r.name, cell: (c) => <strong style={{ fontWeight: 600 }}>{c.getValue<string>()}</strong> },
      { id: "type", header: "Type", accessorFn: (r) => r.type, cell: (c) => <span className="muted">{c.getValue<string>()}</span> },
    ];
    const value: ColumnDef<FlatRow>[] = result.columns.map((col) => ({
      id: col.key,
      header: col.label,
      // accessor = a filterable/sortable representation of the current value.
      accessorFn: (r) => {
        const v = col.get(workbook, r.id);
        return v == null ? "" : typeof v === "object" ? "varies" : v;
      },
      cell: (c) =>
        col.kind === "streams" ? (
          <StreamsCell col={col} id={c.row.original.id} name={c.row.original.name} />
        ) : col.kind === "temporal" ? (
          <TemporalValue
            value={(col.get(workbook, c.row.original.id) as TemporalVal | null) ?? null}
            onChange={(v) => setWorkbook(col.set(workbook, c.row.original.id, v))}
            label={`${c.row.original.name} · ${col.label}`}
            unit={col.unit}
            perYear={col.perYear ?? false}
            baseYear={baseYear}
            periods={periods}
            variant="text"
          />
        ) : (
          <StaticCell col={col} id={c.row.original.id} />
        ),
    }));
    return [...fixed, ...value];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, workbook, baseYear, periods]);

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
        <span style={{ flex: 1 }} />
        <button className="rail-collapse" title="close" onClick={onClose}>✕</button>
      </div>
      {open && (
        <div className="flat-table-body">
          {result.rows.length === 0 ? (
            <p className="muted" style={{ padding: 12, fontSize: "0.8rem" }}>No components under this group.</p>
          ) : (
            <table className="grid" style={{ fontSize: "0.74rem" }}>
              <thead>
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => {
                      const meta = fieldMeta(h.column.id);
                      const sorted = h.column.getIsSorted();
                      return (
                        <th key={h.id} style={{ textAlign: "left", whiteSpace: "nowrap" }}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 3, cursor: "pointer" }} onClick={h.column.getToggleSortingHandler()}>
                            {flexRender(h.column.columnDef.header, h.getContext())}
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
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} style={{ padding: "1px 4px" }}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    ))}
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
