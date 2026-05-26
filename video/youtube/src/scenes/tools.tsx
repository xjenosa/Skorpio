import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";
import type { Scene } from "../Composition";
import { SceneShell, Eyebrow } from "./SceneShell";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

export type ToolId =
  | "winter-peak-stress"
  | "datacenter-siting"
  | "datacenter-expansion"
  | "electrification-readiness"
  | "grid-investment-optimizer";

export type Tool = {
  id: ToolId;
  label: string;
  short: string;
  blurb: string;
  detail: string;
  accent: string;
  examples: string[];
};

export const TOOLS: Tool[] = [
  {
    id: "winter-peak-stress",
    label: "Winter Peak Stress Tester",
    short: "Winter Stress",
    blurb:
      "Simulate extreme cold on a regional grid — heat pumps, EVs, baseboards.",
    detail:
      "What we just demoed: model how the local grid behaves under a deep cold snap, with heat pump COP loss, EV cold draw, and baseboard spikes baked in.",
    accent: "#6fcf8e",
    examples: [
      "Mississauga, -25 °C, 30% heat pump adoption",
      "Ottawa, 5-day cold snap, 2030 horizon",
    ],
  },
  {
    id: "datacenter-siting",
    label: "Datacenter Siting",
    short: "Siting",
    blurb:
      "Place new AI capacity by carbon intensity, latency, and cost.",
    detail:
      "Given a target load and a region, rank candidate sites by clean-energy access, network latency, and total project cost. Picks where to build.",
    accent: "#f38764",
    examples: [
      "50 MW AI training cluster, Quebec, lowest carbon",
      "200 MW HPC build, Ontario, hydro-first",
    ],
  },
  {
    id: "datacenter-expansion",
    label: "Expansion Planner",
    short: "Expansion",
    blurb:
      "Plan next-phase capacity at existing datacenter sites.",
    detail:
      "For sites you already own, find the cheapest path to more megawatts — incremental builds, transmission upgrades, on-site generation, the works.",
    accent: "#7aa2f7",
    examples: [
      "Toronto site: +30 MW in 18 months",
      "Montreal: 20 MW → 80 MW, cheapest path",
    ],
  },
  {
    id: "electrification-readiness",
    label: "Electrification Readiness",
    short: "Electrification",
    blurb:
      "Score neighborhoods on how ready they are for EVs and heat pumps.",
    detail:
      "Per-FSA score combining demographics, housing stock, grid headroom, and policy support. Tells you which neighborhoods are ready and which need help first.",
    accent: "#e0a44a",
    examples: [
      "Liberty Village (M6K), 2030 EV + heat pump",
      "Calgary, ranked by readiness",
    ],
  },
  {
    id: "grid-investment-optimizer",
    label: "Grid Investment Optimizer",
    short: "Investment",
    blurb:
      "Allocate a fixed upgrade budget for the most resilience per dollar.",
    detail:
      "Greedy ROI knapsack across all hardening candidates — substations, lines, feeders, transformers — under your specified climate scenario. Maximizes avoided losses.",
    accent: "#c889e6",
    examples: [
      "Hydro Ottawa, $50M, 2050 climate",
      "BC Hydro rural feeders, $200M plan",
    ],
  },
];

// Scenes 11a-e — spotlight one tool
export const SceneToolSpotlight: React.FC<{
  scene: Scene;
  spotlightId: ToolId;
}> = ({ scene, spotlightId }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tool = TOOLS.find((t) => t.id === spotlightId);
  if (!tool) return null;
  const spotlightIndex = TOOLS.findIndex((t) => t.id === spotlightId);

  const cardIn = interpolate(frame, [0, fps * 0.5], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const cardX = interpolate(frame, [0, fps * 0.5], [40, 0], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const strip = interpolate(frame, [fps * 0.1, fps * 0.6], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });

  return (
    <SceneShell scene={scene}>
      <div
        style={{
          padding: 100,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          gap: 40,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            opacity: strip,
          }}
        >
          <Eyebrow
            prefix={`Tool ${spotlightIndex + 1} of 5`}
            suffix={tool.short}
          />
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "var(--fg-4)",
            }}
          >
            five tools · one agent
          </div>
        </div>

        <div
          style={{
            opacity: cardIn,
            transform: `translateX(${cardX}px)`,
            flex: 1,
            display: "grid",
            gridTemplateColumns: "1.3fr 1fr",
            gap: 32,
            minHeight: 0,
          }}
        >
          <SpotlightCard tool={tool} />
          <ExamplesPane tool={tool} />
        </div>

        <ToolStrip activeId={spotlightId} opacity={strip} />
      </div>
    </SceneShell>
  );
};

// ── shared bits ────────────────────────────────────────────────────────────

const SpotlightCard: React.FC<{ tool: Tool }> = ({ tool }) => (
  <div
    style={{
      backgroundColor: "var(--bg-1)",
      border: "1px solid var(--rule-2)",
      borderRadius: 28,
      padding: "48px 56px",
      display: "flex",
      flexDirection: "column",
      gap: 32,
      position: "relative",
      overflow: "hidden",
      boxShadow:
        "0 1px 0 rgba(255,255,255,0.05) inset, 0 18px 40px rgba(0,0,0,0.45)",
    }}
  >
    <div
      style={{
        position: "absolute",
        top: -120,
        right: -120,
        width: 360,
        height: 360,
        borderRadius: 999,
        background: tool.accent,
        opacity: 0.10,
        filter: "blur(60px)",
      }}
    />
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        position: "relative",
      }}
    >
      <div
        style={{
          width: 22,
          height: 22,
          borderRadius: 999,
          background: tool.accent,
          boxShadow: `0 0 18px ${tool.accent}`,
        }}
      />
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: tool.accent,
        }}
      >
        Pipeline
      </span>
    </div>

    <div
      style={{
        fontFamily: "var(--font-serif)",
        fontSize: 64,
        lineHeight: 1.05,
        letterSpacing: "-0.025em",
        color: "var(--fg-1)",
        position: "relative",
      }}
    >
      {tool.label}
    </div>

    <div
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 22,
        lineHeight: 1.45,
        color: "var(--fg-2)",
        position: "relative",
      }}
    >
      {tool.detail}
    </div>
  </div>
);

const ExamplesPane: React.FC<{ tool: Tool }> = ({ tool }) => (
  <div
    style={{
      backgroundColor: "var(--bg-1)",
      border: "1px solid var(--rule-1)",
      borderRadius: 28,
      padding: "40px 36px",
      display: "flex",
      flexDirection: "column",
      gap: 22,
    }}
  >
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.18em",
        textTransform: "uppercase",
        color: "var(--fg-3)",
      }}
    >
      Example prompts
    </div>
    {tool.examples.map((ex, i) => (
      <div
        key={i}
        style={{
          display: "flex",
          gap: 14,
          alignItems: "flex-start",
        }}
      >
        <span
          style={{
            marginTop: 8,
            width: 6,
            height: 6,
            borderRadius: 999,
            background: tool.accent,
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 18,
            lineHeight: 1.4,
            color: "var(--fg-1)",
            fontStyle: "italic",
          }}
        >
          “{ex}”
        </span>
      </div>
    ))}
    <div
      style={{
        marginTop: "auto",
        paddingTop: 20,
        borderTop: "1px solid var(--rule-1)",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        color: "var(--fg-3)",
      }}
    >
      Routed automatically · grounded in real data
    </div>
  </div>
);

const ToolStrip: React.FC<{ activeId: ToolId; opacity: number }> = ({
  activeId,
  opacity,
}) => (
  <div
    style={{
      opacity,
      display: "grid",
      gridTemplateColumns: "repeat(5, 1fr)",
      gap: 12,
    }}
  >
    {TOOLS.map((t) => {
      const isActive = t.id === activeId;
      return (
        <div
          key={t.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "14px 16px",
            backgroundColor: isActive ? "var(--bg-2)" : "var(--bg-1)",
            border: `1px solid ${
              isActive ? "var(--accent-line)" : "var(--rule-1)"
            }`,
            borderRadius: 14,
          }}
        >
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 999,
              background: t.accent,
              boxShadow: isActive ? `0 0 12px ${t.accent}` : undefined,
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: "0.10em",
              textTransform: "uppercase",
              color: isActive ? "var(--fg-1)" : "var(--fg-3)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {t.short}
          </span>
        </div>
      );
    })}
  </div>
);
