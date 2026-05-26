import "./index.css";
import { Composition, CalculateMetadataFunction, staticFile } from "remotion";
import { MyComposition, NarrationProps, Scene } from "./Composition";
import { getAudioDuration } from "./get-audio-duration";
import narration from "../narration.json";

const FPS = 30;

const calculateMetadata: CalculateMetadataFunction<NarrationProps> = async () => {
  const scenes: Scene[] = await Promise.all(
    narration.lines.map(async (line) => {
      let durationInFrames: number;
      let audioReady: boolean;
      try {
        const seconds = await getAudioDuration(
          staticFile(`audio/${line.id}.mp3`),
        );
        durationInFrames = Math.ceil(seconds * FPS);
        audioReady = true;
      } catch {
        // Audio not generated yet — estimate from word count at ~2.5 wps so
        // visuals can be previewed before running `npm run narrate`.
        const words = line.text.trim().split(/\s+/).length;
        durationInFrames = Math.ceil((words / 2.5) * FPS);
        audioReady = false;
      }
      return {
        id: line.id,
        text: line.text,
        durationInFrames,
        audioReady,
      };
    }),
  );

  const totalFrames = scenes.reduce((sum, s) => sum + s.durationInFrames, 0);

  return {
    durationInFrames: totalFrames,
    props: { scenes },
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="SkorpioVideo"
      component={MyComposition}
      durationInFrames={5400}
      fps={FPS}
      width={1920}
      height={1080}
      defaultProps={{ scenes: [] }}
      calculateMetadata={calculateMetadata}
    />
  );
};
