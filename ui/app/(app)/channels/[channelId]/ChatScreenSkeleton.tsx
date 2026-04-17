/**
 * Full-page skeleton shown while channel data is loading.
 * Matches the real ChatScreen layout so the transition is seamless.
 */
import { useThemeTokens } from "@/src/theme/tokens";

function ShimmerBar({ width, height = 13 }: { width: string; height?: number }) {
  return (
    <div
      className="rounded bg-skeleton/[0.04] animate-pulse"
      style={{ width, height }}
    />
  );
}

/** Skeleton header matching ChannelHeader geometry */
function HeaderSkeleton({ t }: { t: ReturnType<typeof useThemeTokens> }) {
  return (
    <div
      style={{
        borderBottom: `1px solid ${t.surfaceBorder}`,
        flexShrink: 0,
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        backgroundColor: `${t.surface}e6`,
      }}
    >
      <header
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 12,
          padding: "0 16px",
          minHeight: 52,
        }}
      >
        {/* Hash icon placeholder */}
        <div className="w-[18px] h-[18px] rounded bg-skeleton/[0.04] animate-pulse" style={{ marginLeft: 2 }} />
        {/* Title + subtitle */}
        <div style={{ flex: 1, padding: "8px 0" }}>
          <ShimmerBar width="140px" height={16} />
          <div className="flex items-center gap-2 mt-1.5">
            <ShimmerBar width="80px" height={12} />
            <ShimmerBar width="60px" height={11} />
          </div>
        </div>
        {/* Action button placeholders */}
        <div className="w-9 h-9 rounded-md bg-skeleton/[0.04] animate-pulse" />
        <div className="w-9 h-9 rounded-md bg-skeleton/[0.04] animate-pulse" />
        <div className="w-11 h-11 rounded-md bg-skeleton/[0.04] animate-pulse" />
      </header>

      {/* Badge bar placeholder */}
      <div className="flex items-center gap-3 px-4 py-1" style={{ height: 26 }}>
        <ShimmerBar width="60px" height={10} />
        <ShimmerBar width="80px" height={10} />
      </div>
    </div>
  );
}

/** Message-shaped skeleton bubble */
function MessageSkeleton({
  widths,
  isUser = false,
}: {
  widths: string[];
  isUser?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        gap: 10,
        padding: "6px 20px",
        justifyContent: isUser ? "flex-end" : "flex-start",
      }}
    >
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-skeleton/[0.04] animate-pulse shrink-0" />
      )}
      <div className="flex flex-col gap-1.5" style={{ maxWidth: 480 }}>
        {!isUser && <ShimmerBar width="70px" height={11} />}
        {widths.map((w, i) => (
          <ShimmerBar key={i} width={w} height={14} />
        ))}
      </div>
      {isUser && (
        <div className="w-8 h-8 rounded-full bg-skeleton/[0.04] animate-pulse shrink-0" />
      )}
    </div>
  );
}

/** Input bar skeleton matching MessageInput geometry */
function InputSkeleton({ t }: { t: ReturnType<typeof useThemeTokens> }) {
  return (
    <div
      style={{
        flexShrink: 0,
        boxShadow: "0 -1px 8px rgba(0,0,0,0.06)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        backgroundColor: `${t.surface}e6`,
        padding: "10px 16px",
      }}
    >
      <div
        className="rounded-xl bg-skeleton/[0.02] animate-pulse"
        style={{ height: 44, border: `1px solid ${t.surfaceBorder}` }}
      />
    </div>
  );
}

export function ChatScreenSkeleton() {
  const t = useThemeTokens();

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, backgroundColor: t.surface, overflow: "hidden" }}>
      <HeaderSkeleton t={t} />

      {/* Message area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", padding: "16px 0" }}>
        <MessageSkeleton widths={["220px", "160px"]} />
        <MessageSkeleton widths={["280px", "200px", "120px"]} />
        <MessageSkeleton widths={["180px"]} isUser />
        <MessageSkeleton widths={["300px", "240px"]} />
        <MessageSkeleton widths={["160px", "100px"]} isUser />
      </div>

      <InputSkeleton t={t} />
    </div>
  );
}
