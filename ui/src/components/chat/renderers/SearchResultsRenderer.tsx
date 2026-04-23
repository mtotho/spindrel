import { ExternalLink, Search } from "lucide-react";
import type { ThemeTokens } from "../../../theme/tokens";

type SearchResultLike = {
  title?: unknown;
  url?: unknown;
  content?: unknown;
};

type SearchResultsPayload = {
  query?: unknown;
  results?: unknown;
  count?: unknown;
};

export function isSearchResultsPayload(value: unknown): value is {
  query?: string;
  results: SearchResultLike[];
  count?: number;
} {
  if (!value || typeof value !== "object") return false;
  const payload = value as SearchResultsPayload;
  return Array.isArray(payload.results)
    && payload.results.every((result) => result && typeof result === "object");
}

function normalizeUrl(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function resultDomain(url: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.replace(/^https?:\/\//, "").split("/")[0] ?? url;
  }
}

function clamp(text: string, maxLength: number): string {
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

export function DefaultSearchResultsRenderer({
  payload,
  t,
}: {
  payload: { query?: string; results: SearchResultLike[]; count?: number };
  t: ThemeTokens;
}) {
  const query = typeof payload.query === "string" && payload.query.trim()
    ? payload.query.trim()
    : "Search results";
  const results = payload.results.slice(0, 8);
  const count = typeof payload.count === "number" ? payload.count : payload.results.length;

  return (
    <section
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 18,
        overflow: "hidden",
        background: `linear-gradient(135deg, ${t.surfaceRaised} 0%, ${t.surface} 55%, ${t.surfaceOverlay} 100%)`,
        boxShadow: "0 18px 45px rgba(0,0,0,0.16)",
      }}
    >
      <div
        style={{
          padding: "14px 16px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderBottom: `1px solid ${t.overlayBorder}`,
          background: `radial-gradient(circle at 10% 0%, ${t.accentSubtle} 0, transparent 46%), ${t.overlayLight}`,
        }}
      >
        <div
          style={{
            width: 34,
            height: 34,
            borderRadius: 12,
            display: "grid",
            placeItems: "center",
            background: t.accentSubtle,
            color: t.accent,
            border: `1px solid ${t.accentBorder}`,
            flex: "0 0 auto",
          }}
        >
          <Search size={17} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 11, color: t.textMuted, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Search results
          </div>
          <div
            style={{
              color: t.text,
              fontSize: 15,
              fontWeight: 650,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={query}
          >
            {query}
          </div>
        </div>
        <div
          style={{
            color: t.textMuted,
            fontSize: 12,
            border: `1px solid ${t.overlayBorder}`,
            borderRadius: 999,
            padding: "4px 9px",
            background: t.surfaceRaised,
            whiteSpace: "nowrap",
          }}
        >
          {count} {count === 1 ? "result" : "results"}
        </div>
      </div>

      <div style={{ display: "grid" }}>
        {results.length ? results.map((result, index) => {
          const title = typeof result.title === "string" && result.title.trim()
            ? result.title.trim()
            : `Result ${index + 1}`;
          const url = normalizeUrl(result.url);
          const domain = resultDomain(url);
          const content = typeof result.content === "string" ? result.content.trim() : "";

          return (
            <a
              key={`${url || title}:${index}`}
              href={url || undefined}
              target={url ? "_blank" : undefined}
              rel={url ? "noreferrer" : undefined}
              style={{
                color: "inherit",
                textDecoration: "none",
                display: "grid",
                gridTemplateColumns: "34px minmax(0, 1fr) auto",
                gap: 12,
                padding: "13px 16px",
                borderTop: index === 0 ? "none" : `1px solid ${t.overlayBorder}`,
                background: index % 2 === 0 ? "transparent" : t.overlayLight,
              }}
            >
              <div
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 10,
                  display: "grid",
                  placeItems: "center",
                  color: t.accent,
                  background: t.accentSubtle,
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                {index + 1}
              </div>
              <div style={{ minWidth: 0 }}>
                <div
                  style={{
                    color: t.text,
                    fontSize: 14,
                    fontWeight: 650,
                    lineHeight: 1.3,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {title}
                </div>
                {domain && (
                  <div
                    style={{
                      color: t.accent,
                      fontSize: 12,
                      marginTop: 3,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {domain}
                  </div>
                )}
                {content && (
                  <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.45, marginTop: 5 }}>
                    {clamp(content, 230)}
                  </div>
                )}
              </div>
              {url && (
                <ExternalLink size={14} style={{ color: t.textDim, alignSelf: "start", marginTop: 2 }} />
              )}
            </a>
          );
        }) : (
          <div style={{ padding: 16, color: t.textMuted, fontSize: 13 }}>No results returned.</div>
        )}
      </div>
    </section>
  );
}

export function TerminalSearchResultsRenderer({
  payload,
  t,
}: {
  payload: { query?: string; results: SearchResultLike[]; count?: number };
  t: ThemeTokens;
}) {
  const query = typeof payload.query === "string" ? payload.query : "search";
  const results = payload.results.slice(0, 8);
  return (
    <div
      style={{
        fontFamily: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace",
        fontSize: 12,
        lineHeight: 1.55,
        color: t.text,
        whiteSpace: "normal",
      }}
    >
      <div style={{ color: t.textMuted, marginBottom: 8 }}>
        search · {query}
        {typeof payload.count === "number" ? ` · ${payload.count} result${payload.count === 1 ? "" : "s"}` : ""}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {results.map((result, index) => {
          const title = typeof result.title === "string" && result.title.trim()
            ? result.title.trim()
            : `Result ${index + 1}`;
          const url = normalizeUrl(result.url);
          const content = typeof result.content === "string" ? result.content.trim() : "";
          return (
            <div key={`${url || title}:${index}`}>
              <div style={{ color: t.accent }}>
                {index + 1}. {title}
              </div>
              {url && (
                <div style={{ color: t.textMuted, overflowWrap: "anywhere" }}>
                  {url}
                </div>
              )}
              {content && (
                <div style={{ color: t.textMuted }}>
                  {clamp(content, 260)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
