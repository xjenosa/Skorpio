// Skorpio Console — SitingComposer
const { useState: useStateComp } = React;

function Chip({ children, on, onClick, color }) {
  const c = color || "var(--fg-2)";
  return (
    <button onClick={onClick} style={{
      fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.06em",
      padding: "5px 10px", borderRadius: 999,
      border: `1px solid ${on ? "var(--accent)" : "var(--rule-2)"}`,
      background: on ? "var(--accent-soft)" : "var(--bg-1)",
      color: on ? "var(--accent)" : c,
      cursor: "pointer",
      display: "inline-flex", alignItems: "center", gap: 6,
      transition: "all 140ms var(--ease-out)",
    }}>{children}</button>
  );
}

function SitingComposer({ regions, onLaunch }) {
  const [workload, setWorkload] = useStateComp("training-cluster · Q3 expansion");
  const [target, setTarget] = useStateComp(42);
  const [picked, setPicked] = useStateComp(["PJM-W", "ERCOT", "CAISO"]);
  const [carbonCap, setCarbonCap] = useStateComp(300);
  const [latency, setLatency] = useStateComp(35);

  const togglePick = (id) => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);

  return (
    <div style={{
      background: "var(--bg-1)", border: "1px solid var(--rule-2)",
      borderRadius: "var(--radius-xl)", padding: 28,
      display: "flex", flexDirection: "column", gap: 22,
      boxShadow: "var(--shadow-2)",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div className="t-eyebrow" style={{ marginBottom: 6 }}>New siting · run 2811</div>
          <div className="t-h2">Place capacity, then prove it</div>
        </div>
        <span className="t-mono" style={{ color: "var(--fg-3)" }}>draft · autosaved 14:04</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="t-label">Workload</span>
          <input value={workload} onChange={e => setWorkload(e.target.value)} style={{
            background: "var(--bg-0)", border: "1px solid var(--rule-2)",
            borderRadius: "var(--radius-sm)", padding: "10px 12px",
            color: "var(--fg-1)", fontFamily: "var(--font-sans)", fontSize: 14, outline: "none",
          }}/>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="t-label">Target capacity</span>
          <div style={{
            background: "var(--bg-0)", border: "1px solid var(--rule-2)",
            borderRadius: "var(--radius-sm)", padding: "10px 12px",
            color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontSize: 14,
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <input type="number" value={target} onChange={e => setTarget(+e.target.value)} style={{
              background: "transparent", border: 0, color: "var(--fg-1)", outline: "none",
              fontFamily: "var(--font-mono)", fontSize: 14, width: 60,
            }}/>
            <span style={{ color: "var(--fg-3)" }}>MW</span>
          </div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span className="t-label">Regions ({picked.length} of {regions.length})</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {regions.map(r => (
            <Chip key={r.id} on={picked.includes(r.id)} onClick={() => togglePick(r.id)}>
              <span style={{ width: 6, height: 6, borderRadius: 999, background: `var(--energy-${r.state})` }}/>
              {r.label}
            </Chip>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span className="t-label">Carbon cap · {carbonCap} gCO₂/kWh</span>
          <input type="range" min="50" max="800" value={carbonCap} onChange={e => setCarbonCap(+e.target.value)} style={{ accentColor: "var(--accent)" }}/>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span className="t-label">Max latency · {latency} ms</span>
          <input type="range" min="5" max="120" value={latency} onChange={e => setLatency(+e.target.value)} style={{ accentColor: "var(--accent)" }}/>
        </div>
      </div>

      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        paddingTop: 16, borderTop: "1px dotted var(--rule-2)",
      }}>
        <span className="t-small" style={{ color: "var(--fg-3)" }}>
          Pipeline est. <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg-2)" }}>~6.4s</span> · {picked.length} regions · {target} MW target
        </span>
        <div style={{ display: "flex", gap: 10 }}>
          <button style={{
            fontFamily: "var(--font-sans)", fontWeight: 500, fontSize: 14,
            padding: "10px 16px", borderRadius: "var(--radius-md)",
            background: "transparent", border: "1px solid var(--rule-2)", color: "var(--fg-2)", cursor: "pointer",
          }}>Save draft</button>
          <button onClick={onLaunch} style={{
            fontFamily: "var(--font-sans)", fontWeight: 500, fontSize: 14,
            padding: "10px 18px", borderRadius: "var(--radius-md)",
            background: "var(--accent)", border: 0, color: "var(--fg-on-accent)", cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 8,
            boxShadow: "var(--glow-accent)",
          }}>
            <i data-lucide="play" style={{ width: 14, height: 14 }}/>
            Run siting
          </button>
        </div>
      </div>
    </div>
  );
}

window.SkorpioComposer = { SitingComposer, Chip };
