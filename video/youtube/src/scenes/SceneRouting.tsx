import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";
import type { Scene } from "../Composition";
import { SceneShell, Eyebrow } from "./SceneShell";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

const TOOLS = [
  { id: "datacenter-siting", label: "Datacenter Siting", accent: "#f38764" },
  { id: "datacenter-expansion", label: "Expansion Planner", accent: "#7aa2f7" },
  { id: "winter-peak-stress", label: "Winter Peak Stress Tester", accent: "#6fcf8e" },
  { id: "electrification-readiness", label: "Electrification Readiness", accent: "#e0a44a" },
  { id: "grid-investment-optimizer", label: "Grid Investment Optimizer", accent: "#c889e6" },
];

const TARGET = "winter-peak-stress";

export const SceneRouting: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const eyebrow = interpolate(frame, [0, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const question = interpolate(frame, [fps * 0.2, fps * 0.9], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const tools = interpolate(frame, [fps * 0.8, fps * 2.0], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const routeStart = fps * 2.4;
  const routeProgress = interpolate(
    frame,
    [routeStart, routeStart + fps * 1.2],
    [0, 1],
    {
      extrapolateRight: "clamp",
      extrapolateLeft: "clamp",
      easing: easeOut,
    },
  );

  return (
    <SceneShell scene={scene}>
      <div
        style={{
          padding: 120,
          display: "flex",
          flexDirection: "column",
          gap: 56,
          height: "100%",
        }}
      >
        <Eyebrow prefix="Routing" suffix="AI assistant" opacity={eyebrow} />

        <div
          style={{
            opacity: question,
            backgroundColor: "var(--bg-1)",
            border: "1px solid var(--rule-2)",
            borderRadius: 20,
            padding: "28px 32px",
            display: "flex",
            alignItems: "center",
            gap: 24,
            maxWidth: 1700,
          }}
        >
          <div
            style={{
              width: 12,
              height: 12,
              borderRadius: 999,
              background: "var(--accent)",
              boxShadow: "0 0 14px var(--accent)",
              flexShrink: 0,
            }}
          />
          <div
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 24,
              color: "var(--fg-1)",
              lineHeight: 1.4,
            }}
          >
            Will Mississauga&apos;s grid hold a{" "}
            <Pill color="var(--accent)">-25&deg;C polar vortex</Pill> with{" "}
            <Pill color="var(--accent)">30% heat pump adoption</Pill>?
          </div>
        </div>

        <div
          style={{
            opacity: tools,
            display: "flex",
            justifyContent: "space-between",
            gap: 20,
            flex: 1,
            alignItems: "stretch",
          }}
        >
          {TOOLS.map((t, i) => {
            const isTarget = t.id === TARGET;
            const localActivate = isTarget
              ? interpolate(
                  frame,
                  [routeStart + fps * 0.6, routeStart + fps * 1.2],
                  [0, 1],
                  {
                    extrapolateRight: "clamp",
                    extrapolateLeft: "clamp",
                    easing: easeOut,
                  },
                )
              : 0;
            const dim = isTarget ? 1 : 1 - routeProgress * 0.7;
            return (
              <ToolCard
                key={t.id}
                index={i}
                label={t.label}
                accent={t.accent}
                isTarget={isTarget}
                activate={localActivate}
                opacity={dim}
              />
            );
          })}
        </div>

        <div
          style={{
            opacity: tools,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: 14,
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--fg-3)",
          }}
        >
          <span style={{ color: "var(--accent)" }}>● matched</span>
          <span style={{ color: "var(--rule-3)" }}>·</span>
          <span>winter peak stress tester</span>
          <span style={{ color: "var(--rule-3)" }}>·</span>
          <span>confidence {(routeProgress * 96).toFixed(0)}%</span>
        </div>
      </div>
    </SceneShell>
  );
};

const Pill: React.FC<{ color: string; children: React.ReactNode }> = ({
  color,
  children,
}) => (
  <span
    style={{
      backgroundColor: "var(--accent-soft)",
      border: "1px solid var(--accent-line)",
      color,
      padding: "4px 14px",
      borderRadius: 999,
      fontFamily: "var(--font-mono)",
      fontSize: 18,
      letterSpacing: "0.02em",
    }}
  >
    {children}
  </span>
);

const ToolCard: React.FC<{
  index: number;
  label: string;
  accent: string;
  isTarget: boolean;
  activate: number;
  opacity: number;
}> = ({ label, accent, isTarget, activate, opacity }) => {
  return (
    <div
      style={{
        opacity,
        flex: 1,
        backgroundColor: "var(--bg-1)",
        border: `1px solid ${
          isTarget
            ? `rgba(243,135,100,${0.3 + activate * 0.7})`
            : "var(--rule-1)"
        }`,
        borderRadius: 20,
        padding: "32px 24px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        gap: 28,
        boxShadow: isTarget
          ? `0 0 ${activate * 60}px rgba(243,135,100,${activate * 0.35})`
          : undefined,
        transition: "none",
      }}
    >
      <div
        style={{
          width: 14,
          height: 14,
          borderRadius: 999,
          background: accent,
          boxShadow: isTarget ? `0 0 18px ${accent}` : undefined,
        }}
      />
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 22,
          fontWeight: 500,
          color: isTarget ? "var(--fg-1)" : "var(--fg-2)",
          lineHeight: 1.25,
          letterSpacing: "-0.01em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: isTarget ? "var(--accent)" : "var(--fg-4)",
        }}
      >
        {isTarget && activate > 0.3 ? "→ Selected" : "Candidate"}
      </div>
    </div>
  );
};
