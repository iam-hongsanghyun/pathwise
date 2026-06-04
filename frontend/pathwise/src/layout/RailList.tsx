export interface RailItem {
  id: string;
  label: string;
  count?: number;
  dragId?: string; // if set, the item is draggable and carries this payload
  marker?: string; // small leading glyph
}

interface Props {
  title?: string;
  items: RailItem[];
  activeId?: string;
  onSelect?: (id: string) => void;
  width?: number;
  dragMime?: string;
}

/** Generic vertical rail list — reused for Model palette, Analytics categories,
 *  and Settings sections, so each view styles its own navigator. */
export function RailList({ title, items, activeId, onSelect, width, dragMime }: Props) {
  return (
    <aside
      className="left-rail"
      aria-label={title ?? "Navigator"}
      style={width ? { width, flex: `0 0 ${width}px` } : undefined}
    >
      {title && (
        <div className="rail-group">
          <div className="rail-head">{title}</div>
        </div>
      )}
      <div className="rail-group">
        {items.map((it) => (
          <button
            key={it.id}
            className={`rail-item${it.id === activeId ? " is-active" : ""}`}
            draggable={Boolean(it.dragId)}
            onDragStart={
              it.dragId && dragMime
                ? (e) => {
                    e.dataTransfer.setData(dragMime, it.dragId as string);
                    e.dataTransfer.effectAllowed = "copy";
                  }
                : undefined
            }
            onClick={() => onSelect?.(it.id)}
            title={it.dragId ? `${it.label} — drag onto the canvas` : it.label}
          >
            {it.marker ? `${it.marker} ` : ""}
            {it.label}
            {it.count != null && <span className="rail-count"> {it.count}</span>}
          </button>
        ))}
      </div>
    </aside>
  );
}
