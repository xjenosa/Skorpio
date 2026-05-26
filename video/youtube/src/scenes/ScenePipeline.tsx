import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";
import type { Scene } from "../Composition";
import { SceneShell } from "./SceneShell";
import { DashboardFrame } from "./PipelineDashboard";
import {
  REPORT,
  SUBSTATIONS,
  VERDICT_COLOR,
} from "./winterPeakReport";
// Scenes 07/08/09 (cold-sim, risk scoring, plan synthesis) render the live
// output of job 476a2f1 — the PASS-verdict Mississauga run whose mitigation
// set the scene-11 chat-followup transcript references — so they pull from
// a separate data file. Earlier stages (04 dashboard, 05 workload-intel,
// 06 grid-intel) keep the original REPORT for visual continuity.
import {
  REPORT as REPORT_4B,
  LOAD_CURVE_MW,
  TEMP_CURVE_C,
} from "./winterPeakReportJob4b";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

const useFade = (delay = 0, dur = 0.6) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return interpolate(frame, [delay * fps, (delay + dur) * fps], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
};

// Scene 04 — pipeline overview. The 5 stage cards in DashboardFrame
// glow orange one at a time as a *preview* of the sequence about to run
// (prior cards revert to queued — we haven't actually executed anything
// yet). The body holds a single wide callout that occupies the same
// row position as scene 05's tile grid for spatial consistency.
export const SceneDashboard: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fade = useFade(0.3, 0.8);
  const cardIn = interpolate(frame, [fps * 0.4, fps * 1.1], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const cardY = interpolate(frame, [fps * 0.4, fps * 1.1], [16, 0], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const pulse = 0.55 + 0.45 * Math.sin((frame / fps) * Math.PI * 1.6) ** 2;

  // Sequential preview: each stage glows for ~0.6s, in order.
  const previewIndex = (() => {
    const startDelay = fps * 0.6; // wait for stage cards to fade in
    const stagePeriod = fps * 0.6;
    const since = frame - startDelay;
    if (since < 0) return null;
    const idx = Math.floor(since / stagePeriod);
    if (idx >= 5) return null; // after the sweep, everything settles to queued
    return idx;
  })();

  return (
    <SceneShell scene={scene}>
      <DashboardFrame
        activeIndex={previewIndex}
        previewMode
        body={
          <Body
            label="00 · Pipeline initialized"
            opacity={fade}
            content={
              <div
                style={{
                  // Match the tile-row position used by scene 05: anchored
                  // to the top of the Body content area, not centered.
                  display: "flex",
                  alignItems: "flex-start",
                  width: "100%",
                }}
              >
                <div
                  style={{
                    opacity: cardIn,
                    transform: `translateY(${cardY}px)`,
                    display: "flex",
                    alignItems: "center",
                    gap: 28,
                    padding: "22px 28px",
                    width: "100%",
                    backgroundColor: "var(--bg-2)",
                    border: "1px solid var(--rule-1)",
                    borderRadius: 16,
                  }}
                >
                  <div
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: 999,
                      background: "var(--accent-soft)",
                      border: "1px solid var(--accent-line)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    <span
                      style={{
                        width: 12,
                        height: 12,
                        borderRadius: 999,
                        background: "var(--accent)",
                        boxShadow: `0 0 ${8 + pulse * 16}px rgba(243,135,100,${0.4 + pulse * 0.4})`,
                      }}
                    />
                  </div>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                      flex: 1,
                      minWidth: 0,
                    }}
                  >
                    <div
                      style={{
                        fontFamily: "var(--font-serif)",
                        fontSize: 28,
                        lineHeight: 1.15,
                        letterSpacing: "-0.015em",
                        color: "var(--fg-1)",
                      }}
                    >
                      Five agents queued.
                    </div>
                    <div
                      style={{
                        fontFamily: "var(--font-sans)",
                        fontSize: 14,
                        lineHeight: 1.4,
                        color: "var(--fg-3)",
                      }}
                    >
                      Each stage&apos;s output feeds the next ·{" "}
                      {REPORT.network.substationCount} substations and{" "}
                      {REPORT.network.feederCount} feeders to analyze.
                    </div>
                  </div>
                </div>
              </div>
            }
          />
        }
      />
    </SceneShell>
  );
};

// Scene 05 — Workload Intelligence: parsed scenario tiles
export const SceneStage1: React.FC<{ scene: Scene }> = ({ scene }) => {
  const fade = useFade(0.3, 0.8);
  return (
    <SceneShell scene={scene}>
      <DashboardFrame
        activeIndex={0}
        body={
          <Body
            label="01 · Workload Intelligence"
            opacity={fade}
            content={
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 20,
                }}
              >
                <Tile
                  label="Region"
                  value={REPORT.city}
                  sub={`${REPORT.utility} · ${REPORT.isoZone}`}
                />
                <Tile
                  label="Cold event"
                  value={`${REPORT.coldEvent.minTempC} °C`}
                  sub={REPORT.coldEvent.name}
                />
                <Tile
                  label="Adoption"
                  value={`${REPORT.scenario.heatPumpPct}% HP`}
                  sub={`+ ${REPORT.scenario.evPct}% EV penetration`}
                />
                <Tile
                  label="Horizon"
                  value={`${REPORT.horizonYear}`}
                  sub={`${REPORT.coldEvent.durationHours} h modeled (5 days)`}
                />
              </div>
            }
          />
        }
      />
    </SceneShell>
  );
};

// Scene 06 — Grid Intelligence: 22 substations / 176 feeders
export const SceneStage2: React.FC<{ scene: Scene }> = ({ scene }) => {
  const fade = useFade(0.3, 0.8);
  return (
    <SceneShell scene={scene}>
      <DashboardFrame
        activeIndex={1}
        body={
          <Body
            label="02 · Grid Intelligence"
            opacity={fade}
            content={<GridDiagram />}
          />
        }
      />
    </SceneShell>
  );
};

// Scene 07 — Cold-Event Simulation: load curve from report
export const SceneStage3: React.FC<{ scene: Scene }> = ({ scene }) => {
  const fade = useFade(0.3, 0.8);
  return (
    <SceneShell scene={scene}>
      <DashboardFrame
        activeIndex={2}
        body={
          <Body
            label="03 · Cold-Event Simulation"
            opacity={fade}
            content={<LoadCurve />}
          />
        }
      />
    </SceneShell>
  );
};

// Scene 08 — Risk Scoring: top-ranked feeders from report
export const SceneStage4: React.FC<{ scene: Scene }> = ({ scene }) => {
  const fade = useFade(0.3, 0.8);
  return (
    <SceneShell scene={scene}>
      <DashboardFrame
        activeIndex={3}
        body={
          <Body
            label="04 · Risk Scoring"
            opacity={fade}
            content={<FeederList />}
          />
        }
      />
    </SceneShell>
  );
};

// Scene 09 — Plan Synthesis: verdict + mitigations
export const SceneStage5: React.FC<{ scene: Scene }> = ({ scene }) => {
  const fade = useFade(0.3, 0.8);
  return (
    <SceneShell scene={scene}>
      <DashboardFrame
        activeIndex={4}
        body={
          <Body
            label="05 · Plan Synthesis"
            opacity={fade}
            content={<ResilienceReport />}
          />
        }
      />
    </SceneShell>
  );
};

// ── shared body chrome ─────────────────────────────────────────────────────

const Body: React.FC<{
  label: string;
  opacity: number;
  content: React.ReactNode;
}> = ({ label, opacity, content }) => (
  <div
    style={{
      opacity,
      height: "100%",
      backgroundColor: "var(--bg-1)",
      border: "1px solid var(--rule-1)",
      borderRadius: 20,
      padding: "28px 32px",
      display: "flex",
      flexDirection: "column",
      gap: 20,
    }}
  >
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: "var(--accent)",
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: 999,
          background: "var(--accent)",
          boxShadow: "0 0 12px var(--accent)",
        }}
      />
      {label}
    </div>
    <div style={{ flex: 1, minHeight: 0 }}>{content}</div>
  </div>
);

const Tile: React.FC<{ label: string; value: string; sub: string }> = ({
  label,
  value,
  sub,
}) => (
  <div
    style={{
      backgroundColor: "var(--bg-2)",
      border: "1px solid var(--rule-1)",
      borderRadius: 16,
      padding: "22px 24px",
    }}
  >
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: "0.18em",
        textTransform: "uppercase",
        color: "var(--fg-3)",
        marginBottom: 12,
      }}
    >
      {label}
    </div>
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 28,
        color: "var(--fg-1)",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {value}
    </div>
    <div
      style={{
        marginTop: 6,
        fontFamily: "var(--font-sans)",
        fontSize: 12,
        color: "var(--fg-3)",
      }}
    >
      {sub}
    </div>
  </div>
);

// Substation map — real lat/lon projected, colored by aggregate risk band.
// Mirrors Section 02 "At-risk substations" from WinterPeakReport.tsx.
const GridDiagram: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Each substation fades in over its own smooth window, staggered across
  // a longer total reveal. Avoids the snap/step look of a single linear
  // sweep + binary opacity threshold.
  const REVEAL_SECONDS = 9;
  const FADE_SECONDS = 0.55;
  const fadeFor = (i: number) => {
    const startSec =
      (i / Math.max(1, SUBSTATIONS.length - 1)) *
      (REVEAL_SECONDS - FADE_SECONDS);
    return interpolate(
      frame,
      [startSec * fps, (startSec + FADE_SECONDS) * fps],
      [0, 1],
      {
        extrapolateRight: "clamp",
        extrapolateLeft: "clamp",
        easing: easeOut,
      },
    );
  };

  // Project lat/lon into a 0–100 canvas with margin, auto-fit to the
  // substation bbox.
  const pad = 10;
  const lats = SUBSTATIONS.map((s) => s.lat);
  const lons = SUBSTATIONS.map((s) => s.lon);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const project = (lat: number, lon: number) => ({
    x: pad + ((lon - minLon) / (maxLon - minLon)) * (100 - 2 * pad),
    y: pad + (1 - (lat - minLat) / (maxLat - minLat)) * (60 - 2 * pad),
  });

  const colorFor = (risk: number) =>
    risk >= 0.75
      ? VERDICT_COLOR.critical
      : risk >= 0.5
        ? VERDICT_COLOR.warning
        : VERDICT_COLOR.good;
  const sizeFor = (risk: number) =>
    risk >= 0.75 ? 1.6 : risk >= 0.5 ? 1.25 : 0.9;

  const buckets = {
    critical: SUBSTATIONS.filter((s) => s.risk >= 0.75).length,
    warning: SUBSTATIONS.filter((s) => s.risk >= 0.5 && s.risk < 0.75).length,
    good: SUBSTATIONS.filter((s) => s.risk < 0.5).length,
  };

  return (
    <div
      style={{
        position: "relative",
        height: "100%",
        backgroundColor: "var(--bg-0)",
        borderRadius: 14,
        border: "1px solid var(--rule-1)",
        overflow: "hidden",
      }}
    >
      <svg
        viewBox="0 0 100 60"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* faint lat/lon graticule */}
        {[0.25, 0.5, 0.75].map((g) => (
          <line
            key={`v${g}`}
            x1={g * 100}
            x2={g * 100}
            y1={0}
            y2={60}
            stroke="rgba(250,249,245,0.04)"
            strokeWidth={0.08}
          />
        ))}
        {[0.25, 0.5, 0.75].map((g) => (
          <line
            key={`h${g}`}
            x1={0}
            x2={100}
            y1={g * 60}
            y2={g * 60}
            stroke="rgba(250,249,245,0.04)"
            strokeWidth={0.08}
          />
        ))}
        {/* substation markers */}
        {SUBSTATIONS.map((s, i) => {
          const { x, y } = project(s.lat, s.lon);
          const color = colorFor(s.risk);
          const r = sizeFor(s.risk);
          const fade = fadeFor(i);
          return (
            <g key={s.id} opacity={fade}>
              <circle
                cx={x}
                cy={y}
                r={r * 2.4}
                fill={color}
                opacity={0.16}
              />
              <circle cx={x} cy={y} r={r} fill={color} />
            </g>
          );
        })}
      </svg>

      <div
        style={{
          position: "absolute",
          top: 18,
          left: 22,
          display: "flex",
          flexDirection: "column",
          gap: 6,
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "var(--fg-3)",
        }}
      >
        <span>{REPORT.city} · {REPORT.utility}</span>
        <span style={{ color: "var(--fg-4)" }}>
          {REPORT.network.substationCount} substations · {REPORT.network.feederCount} feeders ·{" "}
          {REPORT.network.customers.toLocaleString()} customers
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          top: 18,
          right: 22,
          display: "flex",
          gap: 14,
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "var(--fg-3)",
        }}
      >
        <LegendDot color={VERDICT_COLOR.critical} label={`Critical ≥ 75% · ${buckets.critical}`} />
        <LegendDot color={VERDICT_COLOR.warning} label={`At risk 50–74% · ${buckets.warning}`} />
        <LegendDot color={VERDICT_COLOR.good} label={`Stable < 50% · ${buckets.good}`} />
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 16,
          left: 22,
          right: 22,
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: "0.14em",
          color: "var(--fg-4)",
        }}
      >
        <span>source · IESO-Toronto + Alectra Utilities</span>
        <span>scenario · {REPORT.scenario.label}</span>
      </div>
    </div>
  );
};

const LegendDot: React.FC<{ color: string; label: string }> = ({
  color,
  label,
}) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: 999,
        background: color,
        boxShadow: `0 0 10px ${color}66`,
      }}
    />
    {label}
  </span>
);

// 120-hour load curve drawn from real report data
const LoadCurve: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const reveal = interpolate(frame, [fps * 0.4, fps * 12], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });

  const maxMw = 5500;
  const baseline = REPORT_4B.network.baselineWinterPeakMw;
  const capacity = REPORT_4B.verdict.safeCapacityMw;
  const peakMw = REPORT_4B.verdict.peakLoadMw;
  const headroomMw = Math.abs(REPORT_4B.verdict.shortfallMw);
  const isPass = REPORT_4B.verdict.summary === "PASS";

  // Chart uses a normalized 0..100 × 0..60 viewBox, stretched to fill
  // the container. We compensate with vector-effect:non-scaling-stroke
  // so strokes stay a consistent visual thickness, and render the
  // leading dot as a positioned div (SVG circles would render as
  // ovals under the non-uniform scale).
  const yFor = (mw: number) => 58 - (mw / maxMw) * 50;

  const points = LOAD_CURVE_MW.map((mw, i) => {
    const x = (i / (LOAD_CURVE_MW.length - 1)) * 100;
    return [x, yFor(mw)] as const;
  });

  // Interpolate continuously between sample points so the leading edge
  // moves smoothly even when the reveal is stretched over many seconds.
  // Snapping to integer indices makes the line "step" once every few
  // frames at slow reveal speeds, which reads as laggy.
  const progress = Math.max(0, Math.min(1, reveal)) * (points.length - 1);
  const floorIdx = Math.floor(progress);
  const ceilIdx = Math.min(floorIdx + 1, points.length - 1);
  const segT = progress - floorIdx;
  const tipX =
    points[floorIdx][0] + (points[ceilIdx][0] - points[floorIdx][0]) * segT;
  const tipY =
    points[floorIdx][1] + (points[ceilIdx][1] - points[floorIdx][1]) * segT;

  const fullSegment = points
    .slice(0, floorIdx + 1)
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(" ");
  const path =
    floorIdx + 1 < points.length
      ? `${fullSegment} L ${tipX.toFixed(2)} ${tipY.toFixed(2)}`
      : fullSegment;

  const last: readonly [number, number] = [tipX, tipY];
  const baselineTopPct = (yFor(baseline) / 60) * 100;
  const capacityTopPct = (yFor(capacity) / 60) * 100;
  const dotStillMoving = progress < points.length - 1;

  return (
    <div
      style={{
        position: "relative",
        height: "100%",
        backgroundColor: "var(--bg-0)",
        borderRadius: 14,
        border: "1px solid var(--rule-1)",
        overflow: "hidden",
      }}
    >
      <svg
        viewBox="0 0 100 60"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
        }}
        preserveAspectRatio="none"
      >
        {/* baseline reference */}
        <line
          x1={0}
          x2={100}
          y1={yFor(baseline)}
          y2={yFor(baseline)}
          stroke="rgba(194,192,182,0.28)"
          strokeWidth={1}
          strokeDasharray="4 4"
          vectorEffect="non-scaling-stroke"
        />
        {/* safe-capacity reference */}
        <line
          x1={0}
          x2={100}
          y1={yFor(capacity)}
          y2={yFor(capacity)}
          stroke="rgba(226,107,74,0.45)"
          strokeWidth={1}
          strokeDasharray="4 4"
          vectorEffect="non-scaling-stroke"
        />
        {/* filled area under curve */}
        <path
          d={`${path} L ${last?.[0].toFixed(2) ?? 0} 58 L 0 58 Z`}
          fill="rgba(243,135,100,0.14)"
        />
        {/* curve */}
        <path
          d={path}
          fill="none"
          stroke="#F38764"
          strokeWidth={1.6}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      {/* leading-edge dot — div so it stays a perfect circle */}
      {last && dotStillMoving ? (
        <div
          style={{
            position: "absolute",
            left: `${last[0]}%`,
            top: `${(last[1] / 60) * 100}%`,
            width: 10,
            height: 10,
            marginLeft: -5,
            marginTop: -5,
            borderRadius: 999,
            background: "var(--accent)",
            boxShadow: "0 0 14px rgba(243,135,100,0.7)",
          }}
        />
      ) : null}

      {/* baseline & capacity ref-line tags pinned to the right edge */}
      <RefTag
        topPct={baselineTopPct}
        label={`2024 baseline · ${baseline.toLocaleString()} MW`}
        color="var(--fg-3)"
      />
      <RefTag
        topPct={capacityTopPct}
        label={`safe capacity · ${Math.round(capacity).toLocaleString()} MW`}
        color={isPass ? VERDICT_COLOR.good : "#E26B4A"}
      />

      {/* top header: scenario context */}
      <div
        style={{
          position: "absolute",
          top: 18,
          left: 22,
          right: 22,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "var(--fg-3)",
          pointerEvents: "none",
        }}
      >
        <span>
          {REPORT_4B.city} · cold-event load
          <span style={{ color: "var(--fg-4)" }}> · {REPORT_4B.scenario.label}</span>
        </span>
        <span style={{ color: "var(--fg-4)" }}>
          {REPORT_4B.coldEvent.durationHours} h modeled · 5 days
        </span>
      </div>

      {/* peak summary anchored bottom-right */}
      <div
        style={{
          position: "absolute",
          bottom: 36,
          right: 22,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 4,
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.06em",
          pointerEvents: "none",
        }}
      >
        <span
          style={{
            fontSize: 11,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--fg-3)",
          }}
        >
          modeled peak
        </span>
        <span
          style={{
            fontSize: 30,
            color: "var(--fg-1)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {Math.round(peakMw).toLocaleString()}{" "}
          <span style={{ fontSize: 14, color: "var(--fg-3)" }}>MW</span>
        </span>
        <span
          style={{
            fontSize: 11,
            color: isPass ? VERDICT_COLOR.good : "var(--accent)",
          }}
        >
          + {Math.round(headroomMw).toLocaleString()} MW headroom ·{" "}
          {Math.abs(REPORT_4B.verdict.shortfallPct).toFixed(1)}% under capacity
        </span>
      </div>

      {/* day rail */}
      <div
        style={{
          position: "absolute",
          bottom: 12,
          left: 22,
          right: 22,
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: "0.14em",
          color: "var(--fg-4)",
          pointerEvents: "none",
        }}
      >
        <span>day 1 · {TEMP_CURVE_C[0]}°</span>
        <span>day 2 · {TEMP_CURVE_C[24]}°</span>
        <span>day 3 · {TEMP_CURVE_C[48]}°</span>
        <span>day 4 · {TEMP_CURVE_C[72]}°</span>
        <span>day 5 · {TEMP_CURVE_C[96]}°</span>
      </div>
    </div>
  );
};

function RefTag({
  topPct,
  label,
  color,
}: {
  topPct: number;
  label: string;
  color: string;
}) {
  return (
    <div
      style={{
        position: "absolute",
        top: `${topPct}%`,
        right: 22,
        transform: "translateY(-130%)",
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        color,
        pointerEvents: "none",
      }}
    >
      {label}
    </div>
  );
}

const FeederList: React.FC = () => (
  <div
    style={{
      height: "100%",
      display: "flex",
      flexDirection: "column",
      gap: 10,
    }}
  >
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        paddingBottom: 4,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: "var(--fg-3)",
      }}
    >
      <span>
        {REPORT_4B.verdict.atRiskFeeders} of {REPORT_4B.network.feederCount} feeders at risk
      </span>
      <span style={{ color: "var(--fg-4)" }}>ranked by overload risk</span>
    </div>
    {REPORT_4B.topFeeders.map((f, i) => (
      <FeederRow key={f.id} feeder={f} index={i} />
    ))}
  </div>
);

const FeederRow: React.FC<{
  feeder: (typeof REPORT_4B.topFeeders)[number];
  index: number;
}> = ({ feeder, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const r = interpolate(
    frame,
    [fps * (0.3 + index * 0.15), fps * (0.9 + index * 0.15)],
    [0, 1],
    {
      extrapolateRight: "clamp",
      extrapolateLeft: "clamp",
      easing: easeOut,
    },
  );
  const color =
    feeder.risk > 0.6 ? "#E26B4A" : feeder.risk > 0.4 ? "#E5C46B" : "#6FCF8E";
  // bar normalized so 110% utilization = full
  const barPct = Math.min(100, (feeder.capPct / 110) * 100);
  return (
    <div
      style={{
        opacity: r,
        display: "grid",
        gridTemplateColumns: "200px 1fr 140px 140px 70px",
        gap: 20,
        alignItems: "center",
        padding: "14px 22px",
        backgroundColor: "var(--bg-0)",
        border: "1px solid var(--rule-1)",
        borderRadius: 12,
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 16,
          color: "var(--fg-1)",
          letterSpacing: "0.02em",
        }}
      >
        {feeder.id}
      </div>
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 13,
          color: "var(--fg-3)",
        }}
      >
        {feeder.why}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div
          style={{
            flex: 1,
            height: 6,
            borderRadius: 999,
            backgroundColor: "var(--bg-2)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${barPct * r}%`,
              height: "100%",
              backgroundColor: color,
            }}
          />
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            color,
            width: 50,
            textAlign: "right",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {feeder.capPct.toFixed(1)}%
        </div>
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          color: "var(--fg-3)",
          textAlign: "right",
        }}
      >
        {feeder.ttfHr !== null ? `TTF ${feeder.ttfHr.toFixed(1)} h` : "—"}
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 14,
          color,
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {feeder.risk.toFixed(2)}
      </div>
    </div>
  );
};

const ResilienceReport: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const a = interpolate(frame, [0, fps * 0.6], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const b = interpolate(frame, [fps * 0.5, fps * 1.1], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1.05fr 1fr",
        gap: 20,
        height: "100%",
      }}
    >
      <div
        style={{
          opacity: a,
          backgroundColor: "var(--bg-0)",
          border: "1px solid var(--rule-1)",
          borderRadius: 14,
          padding: 28,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <VerdictPill summary={REPORT_4B.verdict.summary} />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "var(--fg-3)",
            }}
          >
            Peak demand
          </span>
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 64,
            color: "var(--fg-1)",
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "-0.01em",
          }}
        >
          {REPORT_4B.verdict.peakLoadMw.toLocaleString(undefined, {
            maximumFractionDigits: 0,
          })}{" "}
          <span style={{ fontSize: 28, color: "var(--fg-3)" }}>MW</span>
        </div>
        <div
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 14,
            color:
              REPORT_4B.verdict.summary === "PASS"
                ? VERDICT_COLOR.good
                : "#E26B4A",
          }}
        >
          {REPORT_4B.verdict.summary === "PASS"
            ? `+${Math.abs(REPORT_4B.verdict.shortfallMw).toFixed(0)} MW headroom vs safe capacity · ${Math.abs(REPORT_4B.verdict.shortfallPct).toFixed(1)}% under capacity`
            : `${REPORT_4B.verdict.shortfallMw.toFixed(0)} MW shortfall vs safe capacity · ${REPORT_4B.verdict.shortfallPct.toFixed(1)}% over headroom`}
        </div>
        <div
          style={{
            marginTop: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <Row
            k="At-risk feeders"
            v={`${REPORT_4B.verdict.atRiskFeeders} of ${REPORT_4B.network.feederCount}`}
          />
          <Row
            k="Peak hour"
            v={`Hour ${REPORT_4B.verdict.peakHourOffset} · ${REPORT_4B.verdict.peakTempC}°C floor`}
          />
          <Row
            k="Baseline reference"
            v={`${REPORT_4B.network.baselineWinterPeakMw.toLocaleString()} MW · IESO-aligned ${REPORT_4B.network.baselineYear}`}
          />
        </div>
      </div>
      <div
        style={{
          opacity: b,
          backgroundColor: "var(--bg-0)",
          border: "1px solid var(--rule-1)",
          borderRadius: 14,
          padding: 28,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--fg-3)",
          }}
        >
          <span>Recommended mitigations</span>
          <span>relief · cost · months</span>
        </div>
        {REPORT_4B.mitigations.map((m) => (
          <MitigationRow key={m.title} mitigation={m} />
        ))}
      </div>
    </div>
  );
};

const Row: React.FC<{ k: string; v: string }> = ({ k, v }) => (
  <div
    style={{
      display: "flex",
      justifyContent: "space-between",
      gap: 16,
      borderTop: "1px solid var(--rule-1)",
      paddingTop: 10,
    }}
  >
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        color: "var(--fg-3)",
      }}
    >
      {k}
    </span>
    <span
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 14,
        color: "var(--fg-1)",
      }}
    >
      {v}
    </span>
  </div>
);

const MitigationRow: React.FC<{
  mitigation: (typeof REPORT_4B.mitigations)[number];
}> = ({ mitigation: m }) => (
  <div
    style={{
      display: "grid",
      gridTemplateColumns: "1fr auto",
      gap: 12,
      alignItems: "center",
      padding: "12px 14px",
      backgroundColor: "var(--bg-1)",
      border: "1px solid var(--rule-1)",
      borderRadius: 10,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 999,
          background: "var(--accent)",
        }}
      />
      <span
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 13,
          color: "var(--fg-1)",
        }}
      >
        {m.title}
      </span>
    </div>
    <div
      style={{
        display: "flex",
        gap: 12,
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        color: "var(--fg-3)",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      <span style={{ color: "var(--accent)" }}>−{m.reliefMw} MW</span>
      <span>${m.costMillionsCad.toFixed(1)}M</span>
      <span>{m.months} mo</span>
    </div>
  </div>
);

// Verdict pill flips orange-red (FAIL) to green (PASS) so the same
// ResilienceReport layout reads correctly for either outcome.
const VerdictPill: React.FC<{ summary: string }> = ({ summary }) => {
  const isPass = summary === "PASS";
  const color = isPass ? VERDICT_COLOR.good : "#E26B4A";
  const bg = isPass ? "rgba(111,207,142,0.16)" : "rgba(226,107,74,0.16)";
  const border = isPass ? "rgba(111,207,142,0.4)" : "rgba(226,107,74,0.4)";
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.18em",
        textTransform: "uppercase",
        padding: "4px 10px",
        borderRadius: 6,
        background: bg,
        color,
        border: `1px solid ${border}`,
      }}
    >
      verdict · {summary}
    </span>
  );
};
