import { AbsoluteFill, Sequence } from "remotion";
import { SceneIntro } from "./scenes/SceneIntro";
import { SceneScenario } from "./scenes/SceneScenario";
import { SceneChatInput } from "./scenes/SceneChatInput";
import { SceneRouting } from "./scenes/SceneRouting";
import {
  SceneDashboard,
  SceneStage1,
  SceneStage2,
  SceneStage3,
  SceneStage4,
  SceneStage5,
} from "./scenes/ScenePipeline";
import { SceneChatFollowup } from "./scenes/SceneChatFollowup";
import { SceneToolSpotlight } from "./scenes/tools";
import { SceneOutro } from "./scenes/SceneOutro";

export type Scene = {
  id: string;
  text: string;
  durationInFrames: number;
  audioReady: boolean;
};

export type NarrationProps = {
  scenes: Scene[];
};

const SCENE_MAP: Record<string, React.FC<{ scene: Scene }>> = {
  "01a-intro": SceneIntro,
  "01b-scenario": SceneScenario,
  "02-question": SceneChatInput,
  "03-routing": SceneRouting,
  "04-dashboard": SceneDashboard,
  "05-workload-intel": SceneStage1,
  "06-grid-intel": SceneStage2,
  "07-cold-sim": SceneStage3,
  "08-risk-scoring": SceneStage4,
  "09-plan-synthesis": SceneStage5,
  "10-chat-followup": SceneChatFollowup,
  "11a-tools-intro": (props) => (
    <SceneToolSpotlight {...props} spotlightId="winter-peak-stress" />
  ),
  "11b-siting": (props) => (
    <SceneToolSpotlight {...props} spotlightId="datacenter-siting" />
  ),
  "11c-expansion": (props) => (
    <SceneToolSpotlight {...props} spotlightId="datacenter-expansion" />
  ),
  "11d-electrification": (props) => (
    <SceneToolSpotlight {...props} spotlightId="electrification-readiness" />
  ),
  "11e-investment": (props) => (
    <SceneToolSpotlight {...props} spotlightId="grid-investment-optimizer" />
  ),
  "12-outro": SceneOutro,
};

export const MyComposition: React.FC<NarrationProps> = ({ scenes }) => {
  let cursor = 0;
  return (
    <AbsoluteFill style={{ backgroundColor: "var(--bg-0)" }}>
      {scenes.map((scene) => {
        const from = cursor;
        cursor += scene.durationInFrames;
        const Body = SCENE_MAP[scene.id];
        return (
          <Sequence
            key={scene.id}
            from={from}
            durationInFrames={scene.durationInFrames}
          >
            {Body ? <Body scene={scene} /> : null}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
