import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";
import type { Scene } from "../Composition";
import { SceneShell, Eyebrow } from "./SceneShell";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

const QUESTION =
  "Will Mississauga's grid hold a -25°C polar vortex with 30% heat pump adoption?";

export const SceneChatInput: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const eyebrow = interpolate(frame, [0, fps * 0.5], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const composer = interpolate(frame, [fps * 0.2, fps * 0.9], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const composerY = interpolate(frame, [fps * 0.2, fps * 0.9], [20, 0], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });

  const typeStart = fps * 0.8;
  const typeEnd = fps * 4.0;
  const charCount = Math.floor(
    interpolate(frame, [typeStart, typeEnd], [0, QUESTION.length], {
      extrapolateRight: "clamp",
      extrapolateLeft: "clamp",
    }),
  );
  const shownText = QUESTION.slice(0, charCount);
  const cursorBlink = Math.floor(frame / (fps / 2)) % 2 === 0;

  return (
    <SceneShell scene={scene}>
      <div
        style={{
          padding: 120,
          display: "flex",
          flexDirection: "column",
          gap: 56,
        }}
      >
        <Eyebrow prefix="New session" suffix="Skorpio" opacity={eyebrow} />

        <div
          style={{
            opacity: eyebrow,
            fontFamily: "var(--font-serif)",
            fontSize: 72,
            lineHeight: 1.1,
            letterSpacing: "-0.025em",
            color: "var(--fg-1)",
            maxWidth: 1400,
          }}
        >
          What would you like to investigate today?
        </div>

        <div
          style={{
            opacity: composer,
            transform: `translateY(${composerY}px)`,
            backgroundColor: "var(--bg-1)",
            border: "1px solid var(--rule-2)",
            borderRadius: 24,
            padding: "32px 36px",
            boxShadow:
              "0 1px 0 rgba(255,255,255,0.05) inset, 0 18px 40px rgba(0,0,0,0.45)",
            display: "flex",
            flexDirection: "column",
            gap: 24,
            maxWidth: 1500,
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 28,
              lineHeight: 1.4,
              color: "var(--fg-1)",
              minHeight: 80,
            }}
          >
            {shownText}
            <span
              style={{
                display: "inline-block",
                width: 3,
                height: 28,
                marginLeft: 4,
                verticalAlign: "middle",
                background: cursorBlink ? "var(--accent)" : "transparent",
              }}
            />
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              borderTop: "1px solid var(--rule-1)",
              paddingTop: 20,
            }}
          >
            <div
              style={{
                display: "flex",
                gap: 12,
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--fg-3)",
              }}
            >
              <Chip>Sonnet 4.6</Chip>
              <Chip>Canada</Chip>
            </div>

            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: 999,
                background: "var(--accent)",
                color: "var(--fg-on-accent)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "var(--font-mono)",
                fontWeight: 600,
                boxShadow: "0 8px 24px rgba(243,135,100,0.30)",
              }}
            >
              ↵
            </div>
          </div>
        </div>

        <div
          style={{
            opacity: composer,
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            maxWidth: 1500,
          }}
        >
          <Suggestion label="Winter Peak Stress" highlighted />
          <Suggestion label="Datacenter Siting" />
          <Suggestion label="Electrification Readiness" />
          <Suggestion label="Grid Investment Optimizer" />
          <Suggestion label="Expansion Planner" />
        </div>
      </div>
    </SceneShell>
  );
};

const Chip: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      padding: "8px 14px",
      borderRadius: 999,
      border: "1px solid var(--rule-2)",
      color: "var(--fg-2)",
    }}
  >
    {children}
  </div>
);

const Suggestion: React.FC<{ label: string; highlighted?: boolean }> = ({
  label,
  highlighted,
}) => (
  <div
    style={{
      padding: "12px 20px",
      borderRadius: 999,
      border: `1px solid ${highlighted ? "var(--accent-line)" : "var(--rule-2)"}`,
      backgroundColor: highlighted ? "var(--accent-soft)" : "transparent",
      color: highlighted ? "var(--accent)" : "var(--fg-3)",
      fontFamily: "var(--font-mono)",
      fontSize: 13,
      letterSpacing: "0.05em",
    }}
  >
    {label}
  </div>
);
