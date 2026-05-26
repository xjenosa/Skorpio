// Skorpio Console — PipelinePanel (the "dark zone" running view)
const { useState: useStatePipe, useEffect: useEffectPipe } = React;

function CornerBrackets() {
  const c = (pos) => ({
    position: "absolute", width: 10, height: 10, borderColor: "var(--accent-line)",
    borderStyle: "solid", borderWidth: 0,
    ...({
      tl: { top: -1, left: -1,    borderTopWidth: 1, borderLeftWidth: 1 },
      tr: { top: -1, right: -1,   borderTopWidth: 1, borderRightWidth: 1 },
      bl: { bottom: -1, left: -1, borderBottomWidth: 1, borderLeftWidth: 1 },
      br: { bottom: -1, right: -1,borderBottomWidth: 1, borderRightWidth: 1 },
    }[pos]),
  });
  return (
    <>
      <span style={c("tl")}/><span style={c("tr")}/>
      <span style={c("bl")}/><span style={c("br")}/>
    </>
  );
}

function PipelinePanel({ stages, log, runId = "run_2811", workload = "training-cluster · Q3 expansion" }) {
  const [active, setActive] = useStatePipe(0);
  const [logCount, setLogCount] = useStatePipe(1);

  useEffectPipe(() => {
    const id = setInterval(() => {
      setActive(a => Math.min(a + 1, stages.length - 1));
      setLogCount(c => Math.min(c + 1, log.length));
    }, 1100);
    return () => clearInterval(id);
  }, [stages.length, log.length]);

  return (
    <div style={{
      position: "relative",
      background: "#0e0e0d", border: "1px solid var(--rule-2)",
      borderRadius: "var(--radius-xl)", padding: 28,
      display: "flex", flexDirection: "column", gap: 22,
      boxShadow: "var(--shadow-3)",
      overflow: "hidden",
    }}>
      {/* dot grid */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        backgroundImage: "radial-gradient(rgba(243,135,100,0.10) 1px, transparent 1px)",
        backgroundSize: "28px 28px",
        WebkitMaskImage: "radial-gradient(ellipse 100% 80% at 50% 50%, black 20%, transparent 95%)",
        maskImage: "radial-gradient(ellipse 100% 80% at 50% 50%, black 20%, transparent 95%)",
        opacity: 0.5,
      }}/>

      <div style={{ position: "relative", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div className="t-eyebrow" style={{ color: "var(--accent)", marginBottom: 6 }}>
            ● Live · {runId}
          </div>
          <div className="t-h2" style={{ color: "var(--fg-1)" }}>{workload}</div>
        </div>
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4,
          fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.14em", color: "var(--fg-3)", textTransform: "uppercase",
        }}>
          <span>Elapsed · <span style={{ color: "var(--fg-1)" }}>00:04.220</span></span>
          <span>Pipeline · {active + 1}/{stages.length}</span>
        </div>
      </div>

      {/* Stage track */}
      <div style={{ position: "relative", display: "grid", gridTemplateColumns: `repeat(${stages.length}, 1fr)`, gap: 8 }}>
        {stages.map((s, i) => {
          const done = i < active;
          const live = i === active;
          return (
            <div key={s.id} style={{
              position: "relative",
              padding: "12px 14px",
              borderRadius: "var(--radius-md)",
              border: `1px solid ${live ? "var(--accent-line)" : "var(--rule-2)"}`,
              background: live ? "rgba(243,135,100,0.06)" : "rgba(255,255,255,0.02)",
              display: "flex", flexDirection: "column", gap: 6,
              minHeight: 72,
            }}>
              {live && <CornerBrackets/>}
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, letterSpacing: "0.14em", textTransform: "uppercase", color: live ? "var(--accent)" : "var(--fg-3)" }}>
                {String(i + 1).padStart(2, "0")} · {done ? "done" : live ? "running" : "queued"}
              </span>
              <span style={{ fontSize: 13, color: "var(--fg-1)", fontWeight: 500 }}>{s.label}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.04em" }}>{s.detail}</span>
              <div style={{ height: 2, background: "var(--rule-2)", borderRadius: 2, overflow: "hidden", marginTop: 4 }}>
                <div style={{
                  height: "100%",
                  width: done ? "100%" : live ? "62%" : "0%",
                  background: live ? "var(--accent)" : "var(--fg-2)",
                  transition: "width 800ms var(--ease-out)",
                }}/>
              </div>
            </div>
          );
        })}
      </div>

      {/* Log + telemetry */}
      <div style={{ position: "relative", display: "grid", gridTemplateColumns: "2fr 1fr", gap: 14 }}>
        <div style={{
          background: "rgba(0,0,0,0.4)", border: "1px solid var(--rule-2)",
          borderRadius: "var(--radius-md)", padding: 14,
          fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.7,
          maxHeight: 200, overflow: "auto",
        }}>
          {log.slice(0, logCount).map((l, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "100px 60px 1fr", gap: 10, color: "var(--fg-2)" }}>
              <span style={{ color: "var(--fg-3)" }}>{l.t}</span>
              <span style={{
                color: l.level === "ok" ? "var(--energy-clean)" : l.level === "warn" ? "var(--energy-mid)" : "var(--accent)",
                textTransform: "uppercase", fontSize: 10, letterSpacing: "0.14em",
              }}>{l.level}</span>
              <span>{l.msg}</span>
            </div>
          ))}
        </div>

        <div style={{
          background: "rgba(0,0,0,0.4)", border: "1px solid var(--rule-2)",
          borderRadius: "var(--radius-md)", padding: 14,
          display: "flex", flexDirection: "column", gap: 10,
        }}>
          <span className="t-eyebrow" style={{ color: "var(--accent)" }}>HUD telemetry</span>
          {[
            { k: "Streams", v: "5/5" }, { k: "Lag (avg)", v: "188 ms" },
            { k: "Candidates", v: "47" }, { k: "Top-K", v: "12" },
            { k: "Best gCO₂/kWh", v: "138" },
          ].map(t => (
            <div key={t.k} style={{
              display: "flex", alignItems: "baseline", gap: 6,
              fontFamily: "var(--font-mono)", fontSize: 11,
            }}>
              <span style={{ color: "var(--fg-3)", letterSpacing: "0.1em", textTransform: "uppercase", fontSize: 9 }}>{t.k}</span>
              <span style={{ flex: 1, borderBottom: "1px dotted var(--rule-2)", margin: "0 4px", alignSelf: "center", height: 1 }}/>
              <span style={{ color: "var(--fg-1)", fontVariantNumeric: "tabular-nums" }}>{t.v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

window.SkorpioPipeline = { PipelinePanel };
