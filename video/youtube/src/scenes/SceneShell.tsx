import { AbsoluteFill, staticFile } from "remotion";
import { Audio } from "@remotion/media";
import type { Scene } from "../Composition";

type Props = {
  scene: Scene;
  children: React.ReactNode;
};

export const SceneShell: React.FC<Props> = ({ scene, children }) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: "var(--bg-0)",
        fontFamily: "var(--font-sans)",
        overflow: "hidden",
      }}
    >
      {scene.audioReady ? (
        <Audio src={staticFile(`audio/${scene.id}.mp3`)} />
      ) : null}
      {children}
    </AbsoluteFill>
  );
};

export const Eyebrow: React.FC<{
  prefix: string;
  suffix?: string;
  opacity?: number;
}> = ({ prefix, suffix, opacity = 1 }) => (
  <div
    style={{
      opacity,
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
    <span style={{ color: "var(--accent)" }}>{prefix}</span>
    {suffix ? (
      <>
        <span style={{ color: "var(--rule-3)" }}>·</span>
        <span>{suffix}</span>
      </>
    ) : null}
  </div>
);
