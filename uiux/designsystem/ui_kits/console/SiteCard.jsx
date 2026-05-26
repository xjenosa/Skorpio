// Skorpio Console — SiteCard, MetricsRail
function EnergyDot({ state, size = 8 }) {
  return <span style={{
    width: size, height: size, borderRadius: 999,
    background: `var(--energy-${state})`,
    display: "inline-block", flexShrink: 0,
  }}/>;
}

function SiteCard({ site, selected, onClick }) {
  return (
    <button onClick={onClick} style={{
      width: "100%", textAlign: "left", cursor: "pointer",
      background: selected ? "var(--bg-2)" : "var(--bg-1)",
      border: `1px solid ${selected ? "var(--accent-line)" : "var(--rule-2)"}`,
      boxShadow: selected ? "var(--glow-accent)" : "var(--shadow-1)",
      borderRadius: "var(--radius-lg)",
      padding: 18,
      display: "flex", flexDirection: "column", gap: 12,
      transition: "all 140ms var(--ease-out)",
      fontFamily: "var(--font-sans)",
      color: "var(--fg-1)",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div className="t-eyebrow" style={{ marginBottom: 4 }}>{site.region} · {site.id}</div>
          <div style={{ fontSize: 17, fontWeight: 500 }}>{site.name}</div>
        </div>
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase",
          padding: "3px 8px", borderRadius: "var(--radius-xs)",
          color: `var(--energy-${site.state})`,
          background: `color-mix(in srgb, var(--energy-${site.state}) 12%, transparent)`,
          border: `1px solid color-mix(in srgb, var(--energy-${site.state}) 35%, transparent)`,
          display: "inline-flex", alignItems: "center", gap: 5,
        }}>
          <EnergyDot state={site.state}/>{site.state}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
        {[
          { k: "Capacity", v: site.capacityMW.toFixed(1), u: "MW" },
          { k: "Carbon",   v: site.carbon, u: "gCO₂" },
          { k: "Spot",     v: `$${site.spot.toFixed(2)}`, u: "" },
        ].map(s => (
          <div key={s.k} style={{
            padding: "8px 10px", border: "1px solid var(--rule-1)",
            borderRadius: "var(--radius-sm)", background: "var(--bg-0)",
            display: "flex", flexDirection: "column", gap: 3,
          }}>
            <span className="t-label" style={{ fontSize: 9 }}>{s.k}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums", fontSize: 16, color: "var(--fg-1)" }}>
              {s.v}<span style={{ color: "var(--fg-3)", fontSize: 11, marginLeft: 3 }}>{s.u}</span>
            </span>
          </div>
        ))}
      </div>

      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        paddingTop: 10, borderTop: "1px dotted var(--rule-2)",
      }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-3)", letterSpacing: "0.08em" }}>
          PUE {site.pue.toFixed(2)} · score {site.score.toFixed(2)}
        </span>
        <span style={{ color: "var(--accent)", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Open →
        </span>
      </div>
    </button>
  );
}

function MetricTile({ label, value, unit, delta, deltaDir }) {
  return (
    <div style={{
      background: "var(--bg-1)", border: "1px solid var(--rule-2)",
      borderRadius: "var(--radius-lg)", padding: 18,
      display: "flex", flexDirection: "column", gap: 6,
      boxShadow: "var(--shadow-1)",
    }}>
      <span className="t-eyebrow">{label}</span>
      <span style={{
        fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums",
        fontSize: 32, fontWeight: 500, color: "var(--fg-1)", letterSpacing: "-0.01em",
      }}>
        {value}<span style={{ color: "var(--fg-3)", fontSize: 14, marginLeft: 4, fontWeight: 400 }}>{unit}</span>
      </span>
      {delta && (
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.06em",
          color: deltaDir === "up" ? "var(--energy-clean)" : "var(--energy-dirty)",
        }}>
          {deltaDir === "up" ? "↗" : "↘"} {delta}
        </span>
      )}
    </div>
  );
}

function MetricsRail() {
  const tiles = [
    { label: "Active capacity", value: "47.2", unit: "MW", delta: "+2.1 MW vs forecast", deltaDir: "up" },
    { label: "Carbon · 7d avg",  value: "187",  unit: "gCO₂", delta: "−12 gCO₂ wow", deltaDir: "up" },
    { label: "Spot · $/MWh",     value: "48.40", unit: "",   delta: "+0.8 today", deltaDir: "down" },
    { label: "PUE · live",       value: "1.18", unit: "",   delta: "−0.02 hour", deltaDir: "up" },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
      {tiles.map(t => <MetricTile key={t.label} {...t}/>)}
    </div>
  );
}

window.SkorpioCards = { SiteCard, MetricsRail, MetricTile, EnergyDot };
