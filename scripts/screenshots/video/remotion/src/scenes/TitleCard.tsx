import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import type { Meta } from "../types";

type Props = {
  title: string;
  meta: Meta;
  durationInFrames: number;
  transitionFrames: number;
  isFirst: boolean;
};

export const TitleCard: React.FC<Props> = ({
  title,
  meta,
  durationInFrames,
  transitionFrames,
  isFirst,
}) => {
  const frame = useCurrentFrame();
  const [w, h] = meta.resolution;

  let opacity = 1;
  if (!isFirst && transitionFrames > 0) {
    opacity = interpolate(frame, [0, transitionFrames], [0, 1], {
      extrapolateRight: "clamp",
    });
  }

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0a0a12",
        alignItems: "center",
        justifyContent: "center",
        opacity,
      }}
    >
      <div
        style={{
          color: "#f4f4f5",
          fontSize: Math.round(h * 0.06),
          fontFamily: "Inter, system-ui, -apple-system, sans-serif",
          fontWeight: 600,
          letterSpacing: -1,
          padding: `0 ${Math.round(w * 0.08)}px`,
          textAlign: "center",
        }}
      >
        {title}
      </div>
    </AbsoluteFill>
  );
};
