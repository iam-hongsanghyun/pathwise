// In-app prompt / confirm dialogs — a styled replacement for the browser's
// window.prompt / window.confirm. `useDialogs()` returns Promise-based `prompt`
// and `confirm` plus the `node` to render; call sites `await` them.

import { useCallback, useEffect, useRef, useState } from "react";

interface PromptOpts {
  title: string;
  label?: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
}
interface ConfirmOpts {
  title: string;
  message?: string;
  danger?: boolean;
  confirmLabel?: string;
}

type State =
  | { kind: "prompt"; opts: PromptOpts }
  | { kind: "confirm"; opts: ConfirmOpts }
  | null;

const overlay: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.28)",
  zIndex: 2000,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};
const card: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border-strong)",
  borderRadius: 8,
  boxShadow: "0 12px 40px rgba(0,0,0,0.22)",
  width: 380,
  maxWidth: "92vw",
  padding: 18,
};
const inp: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
  fontSize: "0.9rem",
  boxSizing: "border-box",
};

/** Promise-based prompt/confirm dialogs. Render `node`; `await prompt(...)`
 *  resolves to the entered string (or null on cancel); `await confirm(...)` to a
 *  boolean. */
export function useDialogs() {
  const [state, setState] = useState<State>(null);
  const [value, setValue] = useState("");
  const resolve = useRef<((v: string | null | boolean) => void) | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const finish = useCallback((v: string | null | boolean) => {
    resolve.current?.(v);
    resolve.current = null;
    setState(null);
  }, []);

  const prompt = useCallback((opts: PromptOpts): Promise<string | null> => {
    setValue(opts.defaultValue ?? "");
    setState({ kind: "prompt", opts });
    return new Promise<string | null>((res) => (resolve.current = res as (v: string | null | boolean) => void));
  }, []);

  const confirm = useCallback((opts: ConfirmOpts): Promise<boolean> => {
    setState({ kind: "confirm", opts });
    return new Promise<boolean>((res) => (resolve.current = res as (v: string | null | boolean) => void));
  }, []);

  useEffect(() => {
    if (state?.kind === "prompt") inputRef.current?.focus();
  }, [state]);

  let node: React.ReactNode = null;
  if (state) {
    const onKey = (e: React.KeyboardEvent) => {
      if (e.key === "Escape") finish(state.kind === "confirm" ? false : null);
      if (e.key === "Enter" && state.kind === "prompt") finish(value);
    };
    node = (
      <div style={overlay} onMouseDown={() => finish(state.kind === "confirm" ? false : null)}>
        <div style={card} onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
          <h3 style={{ margin: "0 0 10px", fontSize: "1rem" }}>{state.opts.title}</h3>
          {state.kind === "prompt" ? (
            <label style={{ display: "block", fontSize: "0.78rem" }}>
              {state.opts.label && <span className="muted">{state.opts.label}</span>}
              <input
                ref={inputRef}
                style={{ ...inp, marginTop: state.opts.label ? 4 : 0 }}
                value={value}
                placeholder={state.opts.placeholder}
                onChange={(e) => setValue(e.target.value)}
              />
            </label>
          ) : (
            state.opts.message && <p style={{ fontSize: "0.85rem", margin: "0 0 4px" }}>{state.opts.message}</p>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
            <button className="ghost" onClick={() => finish(state.kind === "confirm" ? false : null)}>
              Cancel
            </button>
            <button
              className="run-button"
              style={state.kind === "confirm" && state.opts.danger ? { background: "var(--danger)" } : undefined}
              disabled={state.kind === "prompt" && value.trim() === ""}
              onClick={() => finish(state.kind === "prompt" ? value : true)}
            >
              {state.opts.confirmLabel ?? (state.kind === "confirm" ? "Confirm" : "OK")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return { prompt, confirm, node };
}
