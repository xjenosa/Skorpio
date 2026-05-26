import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";
import type { Scene } from "../Composition";
import { SceneShell, Eyebrow } from "./SceneShell";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

type Bubble =
  | { from: "user"; text: string }
  | { from: "ai"; text: React.ReactNode };

// Bubbles taken from a live chat-followup transcript on job 4b62134b.
// User questions are verbatim (they're the same chip prompts shown in
// the report's ReportChatBar); Skorpio's answers are tightened from the
// full live responses to fit the on-screen bubble at video readability —
// same numbers, less prose.
const BUBBLES: Bubble[] = [
  { from: "user", text: "What if heat pump adoption hits 50%?" },
  {
    from: "ai",
    text: (
      <>
        Peak climbs to{" "}
        <em style={{ color: "var(--accent)", fontStyle: "normal" }}>
          3,780 MW with 1,425 MW of headroom (27.4%)
        </em>{" "}
        — still a pass, ~133 MW tighter than the 30% case. MIS-01 feeders at
        31–46% utilization absorb most of the new load.
      </>
    ),
  },
  {
    from: "user",
    text: "Which upgrade gives us the most resilience per dollar?",
  },
  {
    from: "ai",
    text: (
      <>
        Demand response —{" "}
        <em style={{ color: "var(--accent)", fontStyle: "normal" }}>
          12% risk reduction for $180K
        </em>
        , roughly 4× the per-dollar lift of the $3.5M transformer upgrade.
        Deploy across MIS-01-F01/F02/F03 in 6 months while the capital
        works are scoped.
      </>
    ),
  },
];

export const SceneChatFollowup: React.FC<{ scene: Scene }> = ({ scene }) => {
  return (
    <SceneShell scene={scene}>
      <div
        style={{
          padding: 100,
          display: "flex",
          flexDirection: "column",
          gap: 36,
          height: "100%",
        }}
      >
        <Eyebrow prefix="Chat panel" suffix="Follow-up · grounded in simulation" />

        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            gap: 18,
            backgroundColor: "var(--bg-1)",
            border: "1px solid var(--rule-1)",
            borderRadius: 24,
            padding: 36,
            overflow: "hidden",
          }}
        >
          {BUBBLES.map((b, i) => (
            <BubbleRow key={i} bubble={b} index={i} />
          ))}
        </div>
      </div>
    </SceneShell>
  );
};

const BubbleRow: React.FC<{ bubble: Bubble; index: number }> = ({
  bubble,
  index,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const start = fps * (0.4 + index * 0.9);
  const fade = interpolate(frame, [start, start + fps * 0.5], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const slide = interpolate(frame, [start, start + fps * 0.5], [16, 0], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const isUser = bubble.from === "user";
  return (
    <div
      style={{
        opacity: fade,
        transform: `translateY(${slide}px)`,
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
      }}
    >
      <div
        style={{
          maxWidth: "78%",
          backgroundColor: isUser ? "var(--accent-soft)" : "var(--bg-2)",
          border: `1px solid ${isUser ? "var(--accent-line)" : "var(--rule-1)"}`,
          borderRadius: 20,
          padding: "20px 28px",
          fontFamily: "var(--font-sans)",
          fontSize: 22,
          lineHeight: 1.45,
          color: "var(--fg-1)",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: isUser ? "var(--accent)" : "var(--fg-3)",
          }}
        >
          {isUser ? "Planner" : "Skorpio"}
        </div>
        <div>{bubble.text}</div>
      </div>
    </div>
  );
};
