// Pure insert helpers: drop a facility template or a whole chain template into
// the workbook. Mirrors src/pathwise/data/library.py (the Python side proves
// every shipped chain solves; this side does the in-app insertion).

import type { Row, Workbook } from "../types";
import type { ChainTemplate, FacilityTemplate, LibTechnology, SectorLibrary } from "../library";
import { nodeId } from "./model";

const s = (v: unknown) => (v == null ? "" : String(v));

function techRow(t: LibTechnology): Row {
  return {
    technology_id: t.technology_id,
    lifespan: t.lifespan ?? 20,
    actions: "continue,replace,renew",
    capex: t.capex ?? 0,
    opex: t.opex ?? 0,
  };
}

function ioRows(t: LibTechnology): Row[] {
  return t.io.map((r) => {
    const row: Row = {
      technology_id: t.technology_id,
      target: r.target,
      role: r.role,
      coefficient: r.coefficient,
    };
    if (r.is_product) row.is_product = true;
    if (r.group != null) {
      row.group = r.group;
      row.share_min = r.share_min ?? 0;
      row.share_max = r.share_max ?? 1;
    }
    return row;
  });
}

/** Insert one facility template; merges commodities/technologies by id (existing
 *  rows win — the recipe/instance separation lets facilities share archetypes),
 *  uniquifies the process id, and places the node at (x, y) when given. Returns
 *  the new workbook and the created process id. */
export function addFacilityTemplate(
  wb: Workbook,
  lib: SectorLibrary,
  facility: FacilityTemplate,
  pos?: { x: number; y: number },
): { wb: Workbook; processId: string } {
  const out: Workbook = { ...wb };
  const copy = (sheet: string) => (out[sheet] = [...(out[sheet] ?? [])]);
  copy("commodities");
  copy("technologies");
  copy("io");
  copy("processes");
  copy("transitions");
  copy("impacts");

  const techs = [facility.technology, ...(facility.alternatives ?? []).map((a) => a.technology)];

  // Streams referenced by any of the facility's technologies (skip existing).
  const haveComm = new Set(out.commodities.map((r) => s(r.commodity_id)));
  const referenced = new Set(
    techs.flatMap((t) => t.io.filter((r) => r.role !== "impact").map((r) => r.target)),
  );
  for (const c of lib.commodities) {
    if (!referenced.has(c.commodity_id) || haveComm.has(c.commodity_id)) continue;
    const row: Row = { commodity_id: c.commodity_id, kind: c.kind, unit: c.unit ?? "unit" };
    if (c.price != null) row.price = c.price;
    if (c.sale_price != null) row.sale_price = c.sale_price;
    out.commodities.push(row);
    haveComm.add(c.commodity_id);
  }

  // Impacts referenced by io rows (skip existing).
  const haveImp = new Set(out.impacts.map((r) => s(r.impact_id)));
  for (const t of techs)
    for (const r of t.io)
      if (r.role === "impact" && !haveImp.has(r.target)) {
        out.impacts.push({ impact_id: r.target, unit: "t" });
        haveImp.add(r.target);
      }

  const haveTech = new Set(out.technologies.map((r) => s(r.technology_id)));
  for (const t of techs) {
    if (haveTech.has(t.technology_id)) continue;
    out.technologies.push(techRow(t));
    out.io.push(...ioRows(t));
    haveTech.add(t.technology_id);
  }

  const haveTrans = new Set(
    out.transitions.map((r) => `${s(r.from_technology)}→${s(r.to_technology)}`),
  );
  for (const alt of facility.alternatives ?? []) {
    const key = `${facility.technology.technology_id}→${alt.technology.technology_id}`;
    if (haveTrans.has(key)) continue;
    out.transitions.push({
      from_technology: facility.technology.technology_id,
      to_technology: alt.technology.technology_id,
      action: "replace",
      capex_per_capacity: alt.transition_capex_per_capacity ?? 0,
    });
    haveTrans.add(key);
  }

  const haveProc = new Set(out.processes.map((r) => s(r.process_id)));
  let pid = facility.label;
  for (let n = 2; haveProc.has(pid); n += 1) pid = `${facility.label} ${n}`;
  out.processes.push({
    process_id: pid,
    company: "",
    baseline_technology: facility.technology.technology_id,
    capacity: facility.default_capacity ?? 1000,
  });

  if (pos) {
    out.node_layout = [
      ...(out.node_layout ?? []).filter((r) => s(r.id) !== nodeId("process", pid)),
      { id: nodeId("process", pid), x: Math.round(pos.x), y: Math.round(pos.y) },
    ];
  }
  return { wb: out, processId: pid };
}

/** Insert a whole chain: stages in order, edges derived from each stage's
 *  `feeds` (the commodity the upstream produces and the downstream consumes),
 *  facilities placed left→right so the chain reads as a flow. Returns the new
 *  workbook and the created process ids (stage order). */
export function addChainTemplate(
  wb: Workbook,
  lib: SectorLibrary,
  chain: ChainTemplate,
): { wb: Workbook; processIds: string[] } {
  let out = wb;
  const pidOf = new Map<string, string>();
  const baseY = 60 + (wb.processes?.length ?? 0) * 40;
  chain.stages.forEach((stage, i) => {
    const fac = lib.facilities.find((f) => f.facility_id === stage.facility);
    if (!fac) throw new Error(`chain '${chain.chain_id}': unknown facility '${stage.facility}'`);
    const res = addFacilityTemplate(out, lib, fac, { x: 260 + i * 440, y: baseY });
    out = res.wb;
    pidOf.set(stage.facility, res.processId);
  });

  const outputsOf = (fid: string) =>
    new Set(
      lib.facilities
        .find((f) => f.facility_id === fid)
        ?.technology.io.filter((r) => r.role === "output")
        .map((r) => r.target) ?? [],
    );
  const inputsOf = (fid: string) =>
    new Set(
      lib.facilities
        .find((f) => f.facility_id === fid)
        ?.technology.io.filter((r) => r.role === "input")
        .map((r) => r.target) ?? [],
    );

  const edges = [...(out.edges ?? [])];
  for (const stage of chain.stages) {
    for (const feed of stage.feeds ?? []) {
      const shared = [...outputsOf(feed)].filter((c) => inputsOf(stage.facility).has(c));
      for (const commodity of shared) {
        edges.push({
          from_process: pidOf.get(feed) ?? feed,
          to_process: pidOf.get(stage.facility) ?? stage.facility,
          commodity_id: commodity,
        });
      }
    }
  }
  out = { ...out, edges };

  // Seed demand from the hint so the inserted chain runs out of the box; the
  // user still owns company/amount (selecting the last facility prompts them).
  if (chain.demand_hint) {
    const periods = out.periods ?? [];
    const years = periods.length ? periods.map((p) => Number(p.year)) : [2025];
    if (!periods.length) out = { ...out, periods: [{ year: 2025, duration_years: 1 }] };
    const demand = [...(out.demand ?? [])];
    for (const y of years) {
      const exists = demand.some(
        (d) => s(d.commodity_id) === chain.demand_hint!.commodity_id && Number(d.year) === y,
      );
      if (!exists)
        demand.push({
          company: "",
          commodity_id: chain.demand_hint.commodity_id,
          year: y,
          amount: chain.demand_hint.amount,
        });
    }
    out = { ...out, demand };
  }
  return { wb: out, processIds: chain.stages.map((st) => pidOf.get(st.facility) ?? "") };
}
