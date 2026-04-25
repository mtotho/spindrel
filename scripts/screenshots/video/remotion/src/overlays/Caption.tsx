import React from "react";
import type { Meta } from "../types";

type Props = {
  text: string;
  meta: Meta;
};

export const Caption: React.FC<Props> = ({ text, meta }) => {
  const cs = meta.caption_style;
  const isTop = cs.position === "top";

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        [isTop ? "top" : "bottom"]: cs.padding,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          maxWidth: `${meta.resolution[0] - cs.padding * 2}px`,
          padding: `${Math.round(cs.font_size * 0.6)}px ${Math.round(cs.font_size * 1.0)}px`,
          backgroundColor: `rgba(8, 9, 14, ${cs.bg_opacity})`,
          color: "#f4f4f5",
          fontSize: cs.font_size,
          fontFamily: "Inter, system-ui, -apple-system, sans-serif",
          fontWeight: 500,
          lineHeight: 1.3,
          letterSpacing: -0.2,
          borderRadius: 12,
          textAlign: "center",
          backdropFilter: "blur(6px)",
        }}
      >
        {text}
      </div>
    </div>
  );
};
