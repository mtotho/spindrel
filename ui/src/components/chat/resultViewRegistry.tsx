import type { ReactNode } from "react";
import type { ToolResultEnvelope } from "../../types/api";
import type { ResultRenderMode } from "./chatModes";

export type ResultViewKey = string;
export type ResultViewFallbackReason = "unregistered-view" | "missing-mode-renderer";

export interface ResultViewRendererProps {
  viewKey: ResultViewKey;
  mode: ResultRenderMode;
}

export type ResultViewRenderer<TProps extends ResultViewRendererProps> = (props: TProps) => ReactNode;
export type ResultViewRenderers<TProps extends ResultViewRendererProps> = Partial<
  Record<ResultRenderMode | "any", ResultViewRenderer<TProps>>
>;

export class ResultViewRegistry<TProps extends ResultViewRendererProps> {
  private readonly views = new Map<ResultViewKey, ResultViewRenderers<TProps>>();

  register(viewKey: ResultViewKey, renderers: ResultViewRenderers<TProps>): void {
    const current = this.views.get(viewKey) ?? {};
    this.views.set(viewKey, { ...current, ...renderers });
  }

  resolve(viewKey: ResultViewKey, mode: ResultRenderMode): ResultViewRenderer<TProps> | null {
    const renderers = this.views.get(viewKey);
    if (!renderers) return null;
    return renderers[mode] ?? renderers.any ?? null;
  }

  has(viewKey: ResultViewKey): boolean {
    return this.views.has(viewKey);
  }
}

export function createResultViewRegistry<TProps extends ResultViewRendererProps>(): ResultViewRegistry<TProps> {
  return new ResultViewRegistry<TProps>();
}

export function contentTypeToViewKey(contentType: string | null | undefined): ResultViewKey {
  switch (contentType) {
    case "text/markdown":
      return "core.markdown";
    case "application/json":
      return "core.json";
    case "text/html":
      return "core.html";
    case "application/vnd.spindrel.html+interactive":
      return "core.interactive_html";
    case "application/vnd.spindrel.diff+text":
      return "core.diff";
    case "application/vnd.spindrel.file-listing+json":
      return "core.file_listing";
    case "application/vnd.spindrel.components+json":
      return "core.components";
    case "application/vnd.spindrel.native-app+json":
      return "core.native_app";
    case "application/vnd.spindrel.plan+json":
      return "core.plan";
    case "text/plain":
    default:
      return "core.text";
  }
}

export function envelopeViewKey(envelope: ToolResultEnvelope): ResultViewKey {
  return envelope.view_key || contentTypeToViewKey(envelope.content_type);
}
