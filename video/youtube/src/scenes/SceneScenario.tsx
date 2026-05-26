import {
  AbsoluteFill,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";
import { Audio } from "@remotion/media";
import type { Scene } from "../Composition";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

export const SceneScenario: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const eyebrow = interpolate(frame, [0, fps * 0.5], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const card = interpolate(frame, [fps * 0.15, fps * 1.0], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const cardY = interpolate(frame, [fps * 0.15, fps * 1.0], [40, 0], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const stats = interpolate(frame, [fps * 0.8, fps * 1.6], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "var(--bg-0)",
        padding: 120,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        fontFamily: "var(--font-sans)",
        overflow: "hidden",
      }}
    >
      {scene.audioReady ? (
        <Audio src={staticFile(`audio/${scene.id}.mp3`)} />
      ) : null}

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
          marginBottom: 40,
        }}
      >
        <span style={{ color: "var(--accent)" }}>The scenario</span>
        <span style={{ color: "var(--rule-3)" }}>·</span>
        <span>Mississauga, ON</span>
      </div>

      <div
        style={{
          opacity: card,
          transform: `translateY(${cardY}px)`,
          backgroundColor: "var(--bg-1)",
          border: "1px solid var(--rule-2)",
          borderRadius: 28,
          padding: "56px 64px",
          maxWidth: 1500,
          boxShadow:
            "0 1px 0 rgba(255,255,255,0.05) inset, 0 18px 40px rgba(0,0,0,0.45)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            marginBottom: 32,
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--fg-3)",
          }}
        >
          <PlannerAvatar />
          <span style={{ color: "var(--fg-2)" }}>Grid planner</span>
          <span style={{ color: "var(--rule-3)" }}>·</span>
          <span>local utility</span>
        </div>

        <div
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: 64,
            lineHeight: 1.15,
            letterSpacing: "-0.02em",
            color: "var(--fg-1)",
          }}
        >
          “Will our grid hold a{" "}
          <span style={{ color: "var(--accent)" }}>-25&deg;C polar vortex</span>{" "}
          once <span style={{ color: "var(--accent)" }}>30% of homes</span> have
          switched to heat pumps?”
        </div>
      </div>

      <div
        style={{
          opacity: stats,
          marginTop: 56,
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 32,
          maxWidth: 1500,
        }}
      >
        <StatTile label="Region" value="Mississauga" sub="distribution network" />
        <StatTile label="Event" value="-25 °C" sub="5-day cold snap" />
        <StatTile label="Adoption" value="30%" sub="homes on heat pumps" />
      </div>
    </AbsoluteFill>
  );
};

const PlannerAvatar: React.FC = () => (
  <div
    style={{
      width: 40,
      height: 40,
      borderRadius: 999,
      background: "var(--accent-soft)",
      border: "1px solid var(--accent-line)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "var(--font-mono)",
      color: "var(--accent)",
      fontWeight: 600,
      fontSize: 14,
    }}
  >
    GP
  </div>
);

const StatTile: React.FC<{ label: string; value: string; sub: string }> = ({
  label,
  value,
  sub,
}) => (
  <div
    style={{
      backgroundColor: "var(--bg-1)",
      border: "1px solid var(--rule-1)",
      borderRadius: 20,
      padding: "28px 32px",
    }}
  >
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: "var(--fg-3)",
        marginBottom: 16,
      }}
    >
      {label}
    </div>
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 40,
        fontVariantNumeric: "tabular-nums",
        color: "var(--fg-1)",
        letterSpacing: "0.01em",
      }}
    >
      {value}
    </div>
    <div
      style={{
        marginTop: 8,
        fontFamily: "var(--font-sans)",
        fontSize: 14,
        color: "var(--fg-3)",
      }}
    >
      {sub}
    </div>
  </div>
);
