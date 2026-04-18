import { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation, useMatch } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { usePendingApprovalCount } from "../../api/hooks/useApprovals";
import { useThemeTokens } from "../../theme/tokens";

export function ApprovalToast() {
  // On a channel page, approvals for THIS channel render inline via
  // ChannelPendingApprovals — suppress them from the global toast count
  // so we don't double-signal.
  const channelMatch = useMatch("/channels/:channelId");
  const currentChannelId = channelMatch?.params.channelId;
  const { data: count = 0 } = usePendingApprovalCount(currentChannelId);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const t = useThemeTokens();

  const prevCountRef = useRef(count);
  const [showToast, setShowToast] = useState(false);
  const [visible, setVisible] = useState(false);
  const [mounted, setMounted] = useState(false);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Preserve last non-zero count so exit animation doesn't flash "0 pending"
  const displayCountRef = useRef(count);
  if (count > 0) displayCountRef.current = count;
  const displayCount = count > 0 ? count : displayCountRef.current;

  // Show toast only when count increases (new approvals arrived)
  useEffect(() => {
    const prev = prevCountRef.current;
    prevCountRef.current = count;

    // Don't show if on the approvals page or count didn't increase
    if (pathname.startsWith("/admin/approvals")) return;
    if (count > prev && count > 0) {
      setShowToast(true);
    }
    // Auto-dismiss if all approvals were resolved while toast is showing
    if (count === 0 && showToast) {
      setShowToast(false);
    }
  }, [count, pathname, showToast]);

  // Hide when navigating to approvals page
  useEffect(() => {
    if (pathname.startsWith("/admin/approvals")) {
      setShowToast(false);
    }
  }, [pathname]);

  // Mount/unmount with transition
  useEffect(() => {
    if (showToast) {
      setMounted(true);
      requestAnimationFrame(() => setVisible(true));
      // Auto-dismiss after 8 seconds
      dismissTimer.current = setTimeout(() => setShowToast(false), 8000);
      return () => { if (dismissTimer.current) clearTimeout(dismissTimer.current); };
    } else {
      setVisible(false);
      const timer = setTimeout(() => setMounted(false), 200);
      return () => clearTimeout(timer);
    }
  }, [showToast]);

  if (!mounted) return null;

  return (
    <div
      style={{
        position: "absolute",
        bottom: 60,
        right: 16,
        zIndex: 50,
        pointerEvents: "none",
      }}
    >
      <button
        onClick={() => {
          setShowToast(false);
          navigate("/admin/approvals");
        }}
        style={{
          pointerEvents: "auto",
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingLeft: 16,
          paddingRight: 16,
          paddingTop: 10,
          paddingBottom: 10,
          borderRadius: 999,
          backgroundColor: t.surfaceRaised,
          border: `1px solid ${t.accentBorder}`,
          opacity: visible ? 1 : 0,
          transform: `translateY(${visible ? 0 : 8}px)`,
          transition: "opacity 200ms ease-out, transform 200ms ease-out",
          boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
          cursor: "pointer",
          color: "inherit",
          font: "inherit",
        }}
      >
        <ShieldCheck size={14} color="#ef4444" />
        <span style={{ fontSize: 13, color: t.textMuted }}>
          <span style={{ color: "#ef4444", fontWeight: 600 }}>
            {displayCount}
          </span>{" "}
          pending approval{displayCount !== 1 ? "s" : ""}
        </span>
        <span
          style={{
            fontSize: 12,
            color: t.accent,
            fontWeight: 500,
            marginLeft: 4,
          }}
        >
          View
        </span>
      </button>
    </div>
  );
}
