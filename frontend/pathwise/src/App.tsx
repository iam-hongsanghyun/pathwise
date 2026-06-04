import { useEffect, useState } from "react";

interface Health {
  status: string;
}

/** Skeleton app — confirms the backend handshake is reachable. The facility
 *  designer, MACC designer, and table views land in P4–P6. */
export function App() {
  const [health, setHealth] = useState<string>("…");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json() as Promise<Health>)
      .then((h) => setHealth(h.status))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>pathwise</h1>
        <span className="muted">process-network cost optimiser</span>
      </header>
      <section>
        {error ? (
          <p className="error">backend unreachable: {error}</p>
        ) : (
          <p>
            backend health: <strong>{health}</strong>
          </p>
        )}
        <p className="muted">Designer and tables arrive in later phases (P4–P6).</p>
      </section>
    </div>
  );
}
