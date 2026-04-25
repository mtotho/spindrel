import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import type { Meta, ResolvedScene } from "../types";
import { Caption } from "../overlays/Caption";

type Props = {
  scene: ResolvedScene;
  meta: Meta;
  durationInFrames: number;
  transitionFrames: number;
  isFirst: boolean;
};

export const Video: React.FC<Props> = ({
  scene,
  meta,
  transitionFrames,
  isFirst,
}) => {
  const frame = useCurrentFrame();

  let opacity = 1;
  if (!isFirst && transitionFrames > 0) {
    opacity = interpolate(frame, [0, transitionFrames], [0, 1], {
      extrapolateRight: "clamp",
    });
  }

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", opacity }}>
      {scene.asset_url ? (
        <OffthreadVideo
          src={staticFile(scene.asset_url)}
          style={{
            position: "absolute",
            inset: 0,
            width: meta.resolution[0],
            height: meta.resolution[1],
            objectFit: "cover",
          }}
          muted
        />
      ) : null}
      {scene.caption ? <Caption text={scene.caption} meta={meta} /> : null}
    </AbsoluteFill>
  );
};
