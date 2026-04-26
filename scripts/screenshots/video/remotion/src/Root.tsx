import React from "react";
import { Composition } from "remotion";
import { Quickstart } from "./Quickstart";
import type { StoryboardProps } from "./types";

const TITLE_CARD_DURATION_S = 1.4;

const FALLBACK_PROPS: StoryboardProps = {
  meta: {
    title: "Spindrel quickstart",
    slug: "quickstart",
    resolution: [1920, 1080],
    fps: 30,
    transition: "crossfade",
    transition_duration: 0.5,
    watermark: { text: "spindrel.dev", opacity: 0.45 },
    caption_style: {
      position: "bottom",
      font_size: 38,
      padding: 56,
      bg_opacity: 0.6,
    },
  },
  scenes: [],
};

const calcDurationInFrames = (props: StoryboardProps): number => {
  const fps = props.meta.fps;
  // Crossfades overlap with the prior scene by transitionFrames (mirrors
  // the cursor logic in Quickstart.tsx). Without subtracting the overlap
  // the Composition runs past the last scene's end and trails on black.
  const transitionFrames = Math.round(
    (props.meta.transition === "crossfade"
      ? props.meta.transition_duration
      : 0) * fps,
  );
  const sumFrames = props.scenes.reduce(
    (sum, s) => sum + Math.max(1, Math.round(s.duration * fps)),
    0,
  );
  const overlapCount = Math.max(0, props.scenes.length - 1);
  const total = sumFrames - overlapCount * transitionFrames;
  // At least 1 frame so Composition stays valid when an empty inputProps is rendered in studio.
  return Math.max(1, total);
};

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="Quickstart"
        component={Quickstart}
        durationInFrames={calcDurationInFrames(FALLBACK_PROPS)}
        fps={FALLBACK_PROPS.meta.fps}
        width={FALLBACK_PROPS.meta.resolution[0]}
        height={FALLBACK_PROPS.meta.resolution[1]}
        defaultProps={FALLBACK_PROPS}
        calculateMetadata={({ props }) => {
          const fps = props.meta?.fps ?? 30;
          const [w, h] = props.meta?.resolution ?? [1920, 1080];
          return {
            durationInFrames: calcDurationInFrames(props),
            fps,
            width: w,
            height: h,
          };
        }}
      />
    </>
  );
};

export { TITLE_CARD_DURATION_S };
