import React from "react";
import {
  AbsoluteFill,
  Img,
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

export const Still: React.FC<Props> = ({
  scene,
  meta,
  durationInFrames,
  transitionFrames,
  isFirst,
}) => {
  const frame = useCurrentFrame();
  const [outW, outH] = meta.resolution;

  // Linear interpolation for Ken Burns — matches the MoviePy renderer.
  const u =
    durationInFrames <= 1
      ? 0
      : Math.min(Math.max(frame / (durationInFrames - 1), 0), 1);
  const [z0, cx0, cy0] = scene.ken_burns.start;
  const [z1, cx1, cy1] = scene.ken_burns.end;
  const zoom = z0 + (z1 - z0) * u;
  const cx = cx0 + (cx1 - cx0) * u;
  const cy = cy0 + (cy1 - cy0) * u;

  // Crossfade in (skip first scene) — fade across `transitionFrames`.
  let opacity = 1;
  if (!isFirst && transitionFrames > 0) {
    opacity = interpolate(frame, [0, transitionFrames], [0, 1], {
      extrapolateRight: "clamp",
    });
  }

  // Image is rendered behind a fixed-aspect crop window. Two fit modes:
  //  - cover: source already sized to output aspect; crop window scales by zoom.
  //  - width: source is taller than output (full-page guide). Translate vertically.
  const fit = scene.fit;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", opacity }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          overflow: "hidden",
        }}
      >
        {scene.asset_url ? (
          <KenBurnsImg
            src={staticFile(scene.asset_url)}
            outW={outW}
            outH={outH}
            zoom={zoom}
            cx={cx}
            cy={cy}
            fit={fit}
          />
        ) : null}
      </div>
      {scene.caption ? (
        <Caption text={scene.caption} meta={meta} />
      ) : null}
    </AbsoluteFill>
  );
};

type KbProps = {
  src: string;
  outW: number;
  outH: number;
  zoom: number;
  cx: number;
  cy: number;
  fit: "cover" | "width";
};

const KenBurnsImg: React.FC<KbProps> = ({
  src,
  outW,
  outH,
  zoom,
  cx,
  cy,
  fit,
}) => {
  // Both fit modes: pre-fit the image, then translate + scale relative to its
  // visible center. CSS `transform-origin` simplifies vs computing crop boxes.
  // For "cover": image sized to outW x outH, then translate+scale.
  // For "width": image scaled to outW (height grows); translate vertically by cy.
  const imageStyle: React.CSSProperties =
    fit === "width"
      ? {
          position: "absolute",
          top: 0,
          left: 0,
          width: outW,
          height: "auto",
          transformOrigin: `${cx * 100}% ${cy * 100}%`,
          transform: `translate(${(0.5 - cx) * outW}px, ${(0.5 - cy) * 100}%) scale(${zoom})`,
        }
      : {
          position: "absolute",
          top: 0,
          left: 0,
          width: outW,
          height: outH,
          objectFit: "cover",
          transformOrigin: `${cx * 100}% ${cy * 100}%`,
          transform: `scale(${zoom})`,
        };

  return <Img src={src} style={imageStyle} />;
};
