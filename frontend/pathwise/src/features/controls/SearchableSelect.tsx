import { useEffect, useRef, useState } from "react";

interface Props {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  /** Offered when the typed text matches nothing — opens the create flow.
   *  Omit for closed lists (enums, booleans). */
  onCreate?: (name: string) => void;
  /** Display label per option (e.g. "BF (11 facilities)"); value stays the id. */
  labelOf?: (v: string) => string;
  placeholder?: string;
  /** Guidance when there is nothing to pick yet ("add a facility first"). */
  hint?: string;
  /** Current value doesn't resolve to an existing component → shown red. */
  broken?: boolean;
  disabled?: boolean;
}

/** Searchable dropdown for component references: type to filter, click to
 *  pick, and — where a missing component can be created — an "add …" row that
 *  opens the create flow instead of silently accepting a broken id. */
export function SearchableSelect({
  value,
  options,
  onChange,
  onCreate,
  labelOf,
  placeholder,
  hint,
  broken,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  // null = idle (input shows the value); string = the user is typing a filter.
  const [query, setQuery] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) {
        setOpen(false);
        setQuery(null);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  if (disabled || (!options.length && !onCreate)) {
    return (
      <div className="combo is-disabled">
        <input disabled readOnly value="" placeholder={hint ?? placeholder ?? "—"} title={hint} />
      </div>
    );
  }

  const q = (query ?? "").toLowerCase();
  const matches = options.filter((o) => o.toLowerCase().includes(q)).slice(0, 60);
  const typed = query ?? "";
  const exact = options.includes(typed);
  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    setQuery(null);
  };
  const create = (name: string) => {
    onCreate?.(name);
    setOpen(false);
    setQuery(null);
  };

  return (
    <div className={`combo${broken ? " ref-broken" : ""}`} ref={wrap}>
      <input
        value={query ?? value}
        placeholder={value || placeholder || "search…"}
        title={broken ? `'${value}' does not match any existing component` : undefined}
        onFocus={() => {
          setOpen(true);
          setQuery("");
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
            setQuery(null);
          } else if (e.key === "Enter") {
            e.preventDefault();
            if (matches.length) pick(matches[0]);
            else if (onCreate && typed) create(typed);
          }
        }}
      />
      {open && (
        <div className="combo-list">
          {value && (
            <button type="button" className="combo-opt combo-clear" onMouseDown={() => pick("")}>
              — clear —
            </button>
          )}
          {matches.map((o) => (
            <button
              type="button"
              key={o}
              className={`combo-opt${o === value ? " is-current" : ""}`}
              onMouseDown={() => pick(o)}
            >
              {labelOf ? labelOf(o) : o}
            </button>
          ))}
          {!matches.length && !onCreate && <div className="combo-empty">{hint ?? "no matches"}</div>}
          {onCreate && typed !== "" && !exact && (
            <button type="button" className="combo-opt combo-new" onMouseDown={() => create(typed)}>
              ＋ add “{typed}”…
            </button>
          )}
          {onCreate && !matches.length && typed === "" && (
            <div className="combo-empty">
              {hint ? `${hint} — or type a new name` : "type a name to add a new one"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
