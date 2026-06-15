// Shared, domain-agnostic model for the directory TreeExplorer used by both the
// Component and Value Chain tabs. The host adapts its domain (libraries, or the
// session node hierarchy) into a flat TreeNode[] and handles the callbacks.

export type TreeNodeKind = "library" | "group" | "machine" | "leaf";

export interface TreeNode {
  /** Stable, unique across the whole tree. */
  id: string;
  /** Parent id, or null for a top-level row. */
  parentId: string | null;
  kind: TreeNodeKind;
  label: string;
  /** Optional secondary text shown dimmed (e.g. a group's level). */
  level?: string;
  /** Sibling ordering; falls back to input order then label. */
  order?: number;
  /** Show a twisty even before the subtree is materialised (cheap, from data). */
  hasChildren: boolean;
  /** Render dimmed/secondary (e.g. an alternative technology under a machine). */
  muted?: boolean;
  /** Can be dragged (default true). */
  draggable?: boolean;
  /** Can accept children dropped "inside" (default: groups/libraries yes). */
  droppable?: boolean;
}

export interface TreeAction {
  id: string;
  label: string;
  danger?: boolean;
  separatorBefore?: boolean;
}

export type DropPosition = "inside" | "before" | "after";

export interface TreeMoveEvent {
  dragId: string;
  /** New parent id (null = top level). For before/after this is the sibling's parent. */
  targetId: string | null;
  position: DropPosition;
  /** For before/after: the sibling the drop is relative to. */
  beforeSiblingId?: string;
}
