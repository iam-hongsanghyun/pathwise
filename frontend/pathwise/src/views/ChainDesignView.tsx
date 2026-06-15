// Chain Design view — shows the recursive group/component hierarchy as a
// drill-able SVG canvas with breadcrumb navigation.
//
// Intentionally stubbed for a later slice:
//   - Editing nodes/connections (add group, rename, delete)
//   - Right-click context menu ("add group", "add alternative", etc.)
//   - Optimisation-level selector (which level drives the solver objective)
//   - Machine detail panel (right-rail inspector for leaf nodes)

import { useMemo, useState } from "react";
import { GroupCanvas } from "../features/topology/GroupCanvas";
import { parseNodes } from "../lib/groupGraph";
import { Breadcrumb } from "../layout/Breadcrumb";
import type { Workbook } from "../types";

interface Props {
  wb: Workbook;
}

/** Chain Design view: a drill-able hierarchy canvas with breadcrumb nav.
 *
 *  `path` holds node ids from the top level down to the currently displayed
 *  group. An empty path shows the roots. Clicking a group child pushes its id;
 *  a breadcrumb crumb truncates the path back to that level. */
export function ChainDesignView({ wb }: Props) {
  // Stack of node ids: [] = top (showing roots), ["A", "B"] = inside B (child of A).
  const [path, setPath] = useState<string[]>([]);

  const allNodes = useMemo(() => parseNodes(wb), [wb]);

  // Resolve the path of ids into GroupNode objects for the breadcrumb.
  const nodeById = useMemo(() => {
    const m = new Map(allNodes.map((nd) => [nd.id, nd]));
    return m;
  }, [allNodes]);

  const pathNodes = useMemo(
    () => path.flatMap((id) => (nodeById.has(id) ? [nodeById.get(id)!] : [])),
    [path, nodeById],
  );

  // The group currently being shown (last id in path, or null = roots).
  const currentGroupId: string | null = path.length > 0 ? path[path.length - 1] : null;

  const handleDrill = (childId: string) => {
    setPath((prev) => [...prev, childId]);
  };

  const handleJump = (index: number) => {
    if (index === -1) {
      // Jump to top.
      setPath([]);
    } else {
      // Truncate to depth index+1 (keep crumbs 0..index inclusive).
      setPath((prev) => prev.slice(0, index + 1));
    }
  };

  // Guard: no hierarchy in this model.
  if ((wb.nodes ?? []).length === 0) {
    return (
      <div
        className="view"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
        }}
      >
        <p className="muted" style={{ maxWidth: 420, textAlign: "center" }}>
          No hierarchy in this model — switch to a model with a group/component
          structure.
        </p>
      </div>
    );
  }

  return (
    <div
      className="view-full"
      style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}
    >
      <Breadcrumb path={pathNodes} onJump={handleJump} />
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <GroupCanvas
          wb={wb}
          groupId={currentGroupId}
          onDrill={handleDrill}
        />
      </div>
    </div>
  );
}
