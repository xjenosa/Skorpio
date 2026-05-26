// Skorpio Console — Shell, Topbar, Sidebar
const { useState } = React;

// ─── Logo ───────────────────────────────────────────────
function SkorpioMark({ size = 28 }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      <span style={{
        width: size, height: size, borderRadius: 8,
        background: "var(--bg-inverse)",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
      }}>
        <img src="../../assets/skorpio-logo.png" alt="" style={{ width: size * 0.78, height: size * 0.78, objectFit: "contain" }}/>
      </span>
      <span style={{
        fontFamily: "var(--font-sans)", fontWeight: 600, letterSpacing: "-0.02em",
        fontSize: 16, color: "var(--fg-1)",
      }}>SK<span style={{ color: "var(--accent)" }}>O</span>RPIO</span>
    </span>
  );
}

// ─── Topbar ─────────────────────────────────────────────
function Topbar({ workspace, user, page }) {
  return (
    <div style={{
      height: 56, padding: "0 20px",
      display: "flex", alignItems: "center", gap: 16,
      borderBottom: "1px solid var(--rule-2)",
      background: "var(--bg-0)",
      flexShrink: 0,
    }}>
      <SkorpioMark/>
      <span style={{ width: 1, height: 18, background: "var(--rule-2)" }}/>
      <button style={{
        background: "transparent", border: "1px solid var(--rule-2)", color: "var(--fg-2)",
        fontFamily: "var(--font-sans)", fontSize: 12, padding: "6px 12px",
        borderRadius: "var(--radius-sm)", display: "inline-flex", alignItems: "center", gap: 8, cursor: "pointer",
      }}>
        <span style={{
          width: 16, height: 16, borderRadius: 4, background: "var(--accent)",
          color: "var(--fg-on-accent)", fontSize: 9, fontWeight: 600,
          display: "inline-flex", alignItems: "center", justifyContent: "center"
        }}>NS</span>
        {workspace.name}
        <span style={{ color: "var(--fg-3)" }}>▾</span>
      </button>

      <div style={{
        flex: 1, maxWidth: 460,
        display: "flex", alignItems: "center", gap: 8,
        background: "var(--bg-1)", border: "1px solid var(--rule-2)",
        borderRadius: "var(--radius-sm)", padding: "7px 12px",
        color: "var(--fg-3)", fontSize: 13, marginLeft: "auto",
      }}>
        <i data-lucide="search" style={{ width: 14, height: 14 }}/>
        <span>Search runs, sites, plans…</span>
        <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--fg-3)" }}>⌘K</span>
      </div>

      <span style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--energy-clean)",
        padding: "4px 10px", borderRadius: 999, border: "1px solid rgba(111,207,142,0.28)",
        background: "rgba(111,207,142,0.08)",
      }}>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--energy-clean)" }}/>
        Grid sources nominal
      </span>

      <button style={{
        background: "var(--bg-2)", border: "1px solid var(--rule-2)", color: "var(--fg-2)",
        width: 32, height: 32, borderRadius: "var(--radius-sm)", cursor: "pointer",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
      }}>
        <i data-lucide="bell" style={{ width: 14, height: 14 }}/>
      </button>

      <span style={{
        width: 32, height: 32, borderRadius: 999, background: "var(--accent-soft)",
        color: "var(--accent)", fontFamily: "var(--font-mono)", fontWeight: 500, fontSize: 12,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        border: "1px solid var(--accent-line)",
      }}>{user.avatar}</span>
    </div>
  );
}

// ─── Sidebar ────────────────────────────────────────────
function Sidebar({ page, onNav, regions, recentRuns }) {
  const navItems = [
    { id: "dashboard",  label: "Dashboard",  icon: "layout-dashboard" },
    { id: "composer",   label: "New siting", icon: "play" },
    { id: "pipeline",   label: "Pipeline",   icon: "activity" },
    { id: "report",     label: "Reports",    icon: "file-text" },
    { id: "regions",    label: "Regions",    icon: "map" },
    { id: "settings",   label: "Settings",   icon: "settings" },
  ];

  return (
    <aside style={{
      width: 240, padding: "16px 12px",
      borderRight: "1px solid var(--rule-2)",
      background: "var(--bg-0)",
      display: "flex", flexDirection: "column", gap: 20,
      overflow: "auto",
    }}>
      <div>
        {navItems.map(it => {
          const active = it.id === page;
          return (
            <button key={it.id} onClick={() => onNav(it.id)} style={{
              width: "100%", textAlign: "left",
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 10px", borderRadius: "var(--radius-sm)",
              background: active ? "var(--bg-2)" : "transparent",
              border: 0, color: active ? "var(--fg-1)" : "var(--fg-2)",
              fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 500, cursor: "pointer",
              marginBottom: 2,
            }}>
              <i data-lucide={it.icon} style={{ width: 15, height: 15 }}/>
              {it.label}
            </button>
          );
        })}
      </div>

      <div>
        <div className="t-eyebrow" style={{ padding: "0 10px 8px" }}>Regions</div>
        {regions.map(r => (
          <div key={r.id} style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "6px 10px", borderRadius: "var(--radius-sm)",
            color: "var(--fg-2)", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.06em",
          }}>
            <span style={{ width: 7, height: 7, borderRadius: 999, background: `var(--energy-${r.state})`, flexShrink: 0 }}/>
            <span style={{ flex: 1 }}>{r.label}</span>
            <span style={{ color: "var(--fg-3)" }}>{r.available} MW</span>
          </div>
        ))}
      </div>

      <div>
        <div className="t-eyebrow" style={{ padding: "0 10px 8px" }}>Recent runs</div>
        {recentRuns.slice(0,3).map(r => (
          <div key={r.id} style={{
            padding: "8px 10px", borderRadius: "var(--radius-sm)",
            color: "var(--fg-2)", fontSize: 12, lineHeight: 1.35,
            display: "flex", flexDirection: "column", gap: 2,
            cursor: "pointer",
          }}>
            <span style={{ color: "var(--fg-1)" }}>{r.label}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.06em" }}>
              {r.id} · {r.at} · best {r.best}
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}

window.SkorpioShell = { SkorpioMark, Topbar, Sidebar };
