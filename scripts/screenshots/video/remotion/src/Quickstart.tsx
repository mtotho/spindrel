import React from "react";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import type { StoryboardProps } from "./types";
import { Still } from "./scenes/Still";
import { TitleCard } from "./scenes/TitleCard";
import { Watermark } from "./overlays/Watermark";

export const Quickstart: React.FC<StoryboardProps> = ({ meta, scenes }) => {
  const { fps } = useVideoConfig();
  const transitionFrames = Math.round(
    (meta.transition === "crossfade" ? meta.transition_duration : 0) * fps,
  );

  let cursor = 0;
  const segments = scenes.map((scene, idx) => {
    const sceneFrames = Math.max(1, Math.round(scene.duration * fps));
    // Crossfades overlap with the prior scene by `transitionFrames`.
    const from = idx === 0 ? 0 : cursor - transitionFrames;
    cursor = from + sceneFrames;
    return { scene, from, durationInFrames: sceneFrames };
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {segments.map(({ scene, from, durationInFrames }, idx) => (
        <Sequence
          key={`${scene.id}-${idx}`}
          from={from}
          durationInFrames={durationInFrames}
          name={scene.id}
        >
          {scene.kind === "title_card" ? (
            <TitleCard
              title={scene.title ?? scene.caption ?? ""}
              meta={meta}
              durationInFrames={durationInFrames}
              transitionFrames={transitionFrames}
              isFirst={idx === 0}
            />
          ) : (
            <Still
              scene={scene}
              meta={meta}
              durationInFrames={durationInFrames}
              transitionFrames={transitionFrames}
              isFirst={idx === 0}
            />
          )}
        </Sequence>
      ))}
      {meta.watermark ? <Watermark watermark={meta.watermark} /> : null}
    </AbsoluteFill>
  );
};
