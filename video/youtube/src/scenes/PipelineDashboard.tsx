import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

export const STAGES = [
  {
    n: "01",
    label: "Workload Intelligence",
    desc: "Pull the scenario from the question.",
  },
  {
    n: "02",
    label: "Grid Intelligence",
    desc: "Load the city's distribution network.",
  },
  {
    n: "03",
    label: "Cold-Event Simulation",
    desc: "Model what the cold weather does to demand.",
  },
  {
    n: "04",
    label: "Risk Scoring",
    desc: "Rank every feeder and substation on overload risk.",
  },
  {
    n: "05",
    label: "Plan Synthesis",
    desc: "Bring it together as a resilience report.",
  },
];

type State = "queued" | "active" | "done";

export const stateForIndex = (
  i: number,
  activeIndex: number | null,
  previewMode = false,
): State => {
  if (activeIndex === null) return "queued";
  if (i < activeIndex) return previewMode ? "queued" : "done";
  if (i === activeIndex) return "active";
  return "queued";
};

export const DashboardFrame: React.FC<{
  activeIndex: number | null;
  body?: React.ReactNode;
  pipelineLabel?: string;
  // When true, prior stages stay "queued" instead of going "done" —
  // used by the dashboard scene to preview the sequence without
  // claiming work has actually completed.
  previewMode?: boolean;
}> = ({
  activeIndex,
  body,
  pipelineLabel = "Winter Peak Stress Tester",
  previewMode = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headerIn = interpolate(frame, [0, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const stagesIn = interpolate(frame, [fps * 0.2, fps * 0.9], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });

  return (
    <div
      style={{
        padding: 80,
        display: "flex",
        flexDirection: "column",
        gap: 36,
        height: "100%",
      }}
    >
      <div
        style={{
          opacity: headerIn,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingBottom: 24,
          borderBottom: "1px solid var(--rule-1)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 999,
              background: "#6fcf8e",
              boxShadow: "0 0 12px #6fcf8e",
            }}
          />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 13,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "var(--fg-3)",
            }}
          >
            Live job
          </span>
          <span style={{ color: "var(--rule-3)" }}>·</span>
          <span
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 18,
              fontWeight: 500,
              color: "var(--fg-1)",
            }}
          >
            {pipelineLabel}
          </span>
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--fg-4)",
          }}
        >
          jobId · 57b8f39f
        </div>
      </div>

      <div
        style={{
          opacity: stagesIn,
          display: "grid",
          gridTemplateColumns: "repeat(5, 1fr)",
          gap: 16,
        }}
      >
        {STAGES.map((s, i) => {
          const state = stateForIndex(i, activeIndex, previewMode);
          return <StageCard key={s.n} stage={s} state={state} />;
        })}
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>{body}</div>
    </div>
  );
};

const StageCard: React.FC<{
  stage: (typeof STAGES)[number];
  state: State;
}> = ({ stage, state }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pulse =
    state === "active"
      ? 0.5 +
        0.5 *
          Math.sin((frame / fps) * Math.PI * 1.4) ** 2
      : 0;
  const accent =
    state === "active"
      ? "var(--accent)"
      : state === "done"
        ? "#6fcf8e"
        : "var(--fg-4)";
  return (
    <div
      style={{
        backgroundColor:
          state === "active" ? "var(--accent-soft)" : "var(--bg-1)",
        border: `1px solid ${
          state === "active"
            ? `rgba(243,135,100,${0.4 + pulse * 0.4})`
            : "var(--rule-1)"
        }`,
        borderRadius: 16,
        padding: "20px 22px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        boxShadow:
          state === "active"
            ? `0 0 ${20 + pulse * 30}px rgba(243,135,100,${0.18 + pulse * 0.18})`
            : undefined,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: "0.16em",
            color: accent,
            fontWeight: 600,
          }}
        >
          {stage.n}
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: accent,
          }}
        >
          {state === "active" ? "● running" : state === "done" ? "✓ done" : "queued"}
        </span>
      </div>
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 17,
          fontWeight: 500,
          lineHeight: 1.25,
          color:
            state === "queued" ? "var(--fg-3)" : "var(--fg-1)",
        }}
      >
        {stage.label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 12,
          lineHeight: 1.4,
          color: "var(--fg-3)",
        }}
      >
        {stage.desc}
      </div>
    </div>
  );
};
