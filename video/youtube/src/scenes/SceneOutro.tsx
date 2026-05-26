import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";
import type { Scene } from "../Composition";
import { SceneShell } from "./SceneShell";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

export const SceneOutro: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const eyebrow = interpolate(frame, [0, fps * 0.5], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const title = interpolate(frame, [fps * 0.3, fps * 1.2], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const titleY = interpolate(frame, [fps * 0.3, fps * 1.2], [30, 0], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const pills = interpolate(frame, [fps * 0.8, fps * 1.6], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const footer = interpolate(frame, [fps * 1.3, fps * 2.0], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });

  return (
    <SceneShell scene={scene}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "radial-gradient(ellipse 70% 60% at 70% 60%, rgba(243,135,100,0.10), transparent 65%)",
        }}
      />
      <div
        style={{
          padding: 120,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          height: "100%",
          gap: 40,
          position: "relative",
        }}
      >
        <div
          style={{
            opacity: eyebrow,
            display: "flex",
            alignItems: "center",
            gap: 14,
            fontFamily: "var(--font-mono)",
            fontSize: 14,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--fg-3)",
          }}
        >
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 999,
              background: "var(--accent)",
              boxShadow: "0 0 18px var(--accent)",
            }}
          />
          <span style={{ color: "var(--accent)" }}>That's Skorpio</span>
          <span style={{ color: "var(--rule-3)" }}>·</span>
          <span>built on Claude AI</span>
        </div>

        <div
          style={{
            opacity: title,
            transform: `translateY(${titleY}px)`,
            fontFamily: "var(--font-serif)",
            fontSize: 144,
            lineHeight: 0.95,
            letterSpacing: "-0.035em",
            color: "var(--fg-1)",
            maxWidth: 1600,
          }}
        >
          A co-pilot for{" "}
          <em style={{ fontStyle: "italic", color: "var(--accent)" }}>
            Canadian utilities.
          </em>
        </div>

        <div
          style={{
            opacity: pills,
            display: "flex",
            gap: 18,
            flexWrap: "wrap",
          }}
        >
          <CtaCard
            label="DEMO"
            url="pre-skorpio.vercel.app"
            subtitle="try it live"
          />
          <CtaCard
            label="REPORTS"
            url="bit.ly/skorpio-gdrive"
            subtitle="printed dossiers"
          />
          <CtaCard
            label="CODE"
            url="github.com/xjenosa/Skorpio"
            subtitle="source code"
          />
        </div>

        {/* Outro footer — kept tag-line only. The URL row that used to live
            here was redundant with the CTA card row above (same github
            link displayed twice). Single source of truth for each URL. */}
        <div
          style={{
            opacity: footer,
            position: "absolute",
            bottom: 80,
            left: 120,
            right: 120,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-start",
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            letterSpacing: "0.10em",
            color: "var(--fg-3)",
          }}
        >
          <span>seneca hackathon · 2026</span>
        </div>
      </div>
    </SceneShell>
  );
};

// CTA card — labeled link tile used in the outro to point viewers at the
// demo, the printed report dossiers, and the source code. Replaces the
// row of decorative pills that used to live here.
const CtaCard: React.FC<{
  label: string;
  url: string;
  subtitle: string;
}> = ({ label, url, subtitle }) => (
  <div
    style={{
      padding: "20px 28px",
      borderRadius: 16,
      border: "1px solid var(--rule-2)",
      backgroundColor: "var(--bg-1)",
      display: "flex",
      flexDirection: "column",
      gap: 8,
      minWidth: 280,
    }}
  >
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.20em",
        textTransform: "uppercase",
        color: "var(--accent)",
      }}
    >
      {label}
    </span>
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 18,
        color: "var(--fg-1)",
        letterSpacing: "0.01em",
      }}
    >
      {url}
    </span>
    <span
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 12,
        color: "var(--fg-3)",
        letterSpacing: "0.02em",
      }}
    >
      {subtitle}
    </span>
  </div>
);
