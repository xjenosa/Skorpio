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
import { Globe } from "./Globe";

const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

export const SceneIntro: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleIn = interpolate(frame, [0, fps * 0.9], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const titleY = interpolate(frame, [0, fps * 0.9], [40, 0], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const tagIn = interpolate(frame, [fps * 0.5, fps * 1.4], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const eyebrowIn = interpolate(frame, [fps * 0.2, fps * 0.9], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const lineGrow = interpolate(frame, [fps * 0.9, fps * 1.8], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const globeIn = interpolate(frame, [fps * 0.2, fps * 1.4], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });
  const globeScale = interpolate(frame, [fps * 0.2, fps * 1.4], [0.94, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
    easing: easeOut,
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "var(--bg-0)",
        backgroundImage:
          "radial-gradient(ellipse 60% 50% at 30% 30%, rgba(243,135,100,0.10), transparent 60%)",
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

      <GridBackdrop />

      <GlobePanel opacity={globeIn} scale={globeScale} />

      <div
        style={{
          opacity: eyebrowIn,
          display: "flex",
          alignItems: "center",
          gap: 14,
          fontFamily: "var(--font-mono)",
          fontSize: 14,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--fg-3)",
          marginBottom: 32,
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
        <span style={{ color: "var(--accent)" }}>Skorpio</span>
        <span style={{ color: "var(--rule-3)" }}>·</span>
        <span>An AI co-pilot for the Canadian grid</span>
      </div>

      <div
        style={{
          opacity: titleIn,
          transform: `translateY(${titleY}px)`,
          fontFamily: "var(--font-serif)",
          fontSize: 144,
          lineHeight: 0.95,
          letterSpacing: "-0.035em",
          color: "var(--fg-1)",
          maxWidth: 980,
        }}
      >
        Smarter grid<br />
        decisions, <em style={{ fontStyle: "italic", color: "var(--accent)" }}>faster.</em>
      </div>

      <div
        style={{
          height: 1,
          background: "var(--rule-2)",
          margin: "56px 0 32px",
          width: `${lineGrow * 100}%`,
          maxWidth: 720,
        }}
      />

      <div
        style={{
          opacity: tagIn,
          maxWidth: 820,
          fontFamily: "var(--font-sans)",
          fontSize: 24,
          lineHeight: 1.45,
          color: "var(--fg-2)",
          fontWeight: 400,
        }}
      >
        Skorpio helps the people who plan Canada&apos;s electricity grid run
        scenarios, stress-test feeders, and synthesize a plan — using agentic AI
        on real utility data.
      </div>

      <div
        style={{
          opacity: tagIn,
          position: "absolute",
          bottom: 64,
          left: 120,
          right: 120,
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "var(--font-mono)",
          fontSize: 13,
          letterSpacing: "0.08em",
          color: "var(--fg-4)",
        }}
      >
        <span>built at the seneca hackathon · 2026</span>
        <span>github.com/xjenosa/Skorpio</span>
      </div>
    </AbsoluteFill>
  );
};

// Right-side panel that frames the Globe, styled to match the login
// page's `.right` column (rounded card, faint ember radial wash,
// dot-pattern overlay, subtle border + shadow).
function GlobePanel({
  opacity,
  scale,
}: {
  opacity: number;
  scale: number;
}) {
  const panelW = 820;
  const panelH = 820;
  return (
    <div
      aria-hidden
      style={{
        position: "absolute",
        top: "50%",
        right: 80,
        width: panelW,
        height: panelH,
        opacity,
        transform: `translateY(-50%) scale(${scale})`,
        transformOrigin: "center",
        borderRadius: 28,
        border: "1px solid var(--rule-2)",
        backgroundImage:
          "radial-gradient(120% 80% at 50% 50%, rgba(243,135,100,0.06) 0%, transparent 60%)",
        backgroundColor: "var(--bg-1)",
        boxShadow: "0 30px 80px rgba(0,0,0,0.45)",
        overflow: "hidden",
      }}
    >
      {/* dot pattern overlay (matches login .right::before) */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "radial-gradient(rgba(250,249,245,0.07) 1px, transparent 1px)",
          backgroundSize: "22px 22px",
          WebkitMaskImage:
            "radial-gradient(120% 90% at 50% 50%, black 30%, transparent 75%)",
          maskImage:
            "radial-gradient(120% 90% at 50% 50%, black 30%, transparent 75%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Globe size={panelW} />
      </div>

      {/* corner brackets — small HUD detail to echo login chrome */}
      <Corner top={14} left={14} sides="tl" />
      <Corner top={14} right={14} sides="tr" />
      <Corner bottom={14} left={14} sides="bl" />
      <Corner bottom={14} right={14} sides="br" />
    </div>
  );
}

function Corner({
  top,
  bottom,
  left,
  right,
  sides,
}: {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
  sides: "tl" | "tr" | "bl" | "br";
}) {
  const showTop = sides[0] === "t";
  const showLeft = sides[1] === "l";
  return (
    <div
      style={{
        position: "absolute",
        top,
        bottom,
        left,
        right,
        width: 18,
        height: 18,
        borderColor: "var(--accent-line)",
        borderStyle: "solid",
        borderWidth: 0,
        borderTopWidth: showTop ? 1 : 0,
        borderBottomWidth: showTop ? 0 : 1,
        borderLeftWidth: showLeft ? 1 : 0,
        borderRightWidth: showLeft ? 0 : 1,
      }}
    />
  );
}

function GridBackdrop() {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const drift = interpolate(frame, [0, fps * 18], [0, 80], {
    extrapolateRight: "extend",
    extrapolateLeft: "clamp",
  });
  return (
    <div
      aria-hidden
      style={{
        position: "absolute",
        inset: 0,
        backgroundImage:
          "linear-gradient(rgba(250,249,245,0.035) 1px, transparent 1px)," +
          "linear-gradient(90deg, rgba(250,249,245,0.035) 1px, transparent 1px)",
        backgroundSize: "80px 80px",
        backgroundPosition: `${drift}px ${height - drift}px`,
        maskImage:
          "radial-gradient(ellipse 70% 60% at 60% 50%, black 30%, transparent 90%)",
        WebkitMaskImage:
          "radial-gradient(ellipse 70% 60% at 60% 50%, black 30%, transparent 90%)",
      }}
    />
  );
}
