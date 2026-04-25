export type KenBurns = {
  start: [number, number, number];
  end: [number, number, number];
};

export type CaptionStyle = {
  position: "top" | "bottom";
  font_size: number;
  padding: number;
  bg_opacity: number;
};

export type Watermark = {
  text: string;
  opacity: number;
};

export type Meta = {
  title: string;
  slug: string;
  resolution: [number, number];
  fps: number;
  transition: "crossfade" | "cut";
  transition_duration: number;
  watermark: Watermark | null;
  caption_style: CaptionStyle;
};

export type ResolvedScene = {
  id: string;
  kind: "still" | "doc_hero" | "doc_callout" | "title_card" | "video";
  duration: number;
  asset_url: string | null;
  caption: string | null;
  ken_burns: KenBurns;
  fit: "cover" | "width";
  title?: string;
};

export type StoryboardProps = {
  meta: Meta;
  scenes: ResolvedScene[];
};
