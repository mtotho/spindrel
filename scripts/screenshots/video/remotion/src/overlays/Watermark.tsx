import React from "react";
import type { Watermark as WatermarkSpec } from "../types";

type Props = {
  watermark: WatermarkSpec;
};

export const Watermark: React.FC<Props> = ({ watermark }) => {
  return (
    <div
      style={{
        position: "absolute",
        bottom: 24,
        right: 32,
        color: "rgba(244, 244, 245, 1)",
        opacity: watermark.opacity,
        fontSize: 24,
        fontFamily: "Inter, system-ui, -apple-system, sans-serif",
        fontWeight: 500,
        letterSpacing: 0.5,
        textShadow: "0 2px 8px rgba(0,0,0,0.4)",
        pointerEvents: "none",
      }}
    >
      {watermark.text}
    </div>
  );
};
