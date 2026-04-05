import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  X,
  Shield,
  Copy,
  Check,
  Loader2,
  Mail,
  ArrowRight,
  Calendar,
  Folder,
  Paperclip,
  AlertTriangle,
  Info,
  Tag,
} from "lucide-react";
import { fetchQuarantineItem, reprocess } from "../lib/api";

interface Props {
  storeName: string;
  itemId: number;
  onClose: () => void;
  onRelease: () => void;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Well-known metadata keys with dedicated icons and labels. */
const KNOWN_META_KEYS: Record<
  string,
  { icon: React.ComponentType<{ className?: string }>; label: string }
> = {
  from: { icon: Mail, label: "From" },
  to: { icon: ArrowRight, label: "To" },
  date: { icon: Calendar, label: "Date" },
  folder: { icon: Folder, label: "Folder" },
  message_id: { icon: Tag, label: "Message ID" },
};

/** Keys handled separately (attachments) or to skip. */
const SKIP_KEYS = new Set(["attachments", "subject", "title"]);

function formatAttachment(att: unknown): string {
  if (typeof att === "string") return att;
  if (att && typeof att === "object" && "filename" in att) {
    return (att as { filename: string }).filename;
  }
  return String(att);
}

export default function ItemDetailDrawer({
  storeName,
  itemId,
  onClose,
  onRelease,
}: Props) {
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["quarantine-detail", storeName, itemId],
    queryFn: () => fetchQuarantineItem(storeName, itemId),
  });

  const releaseMutation = useMutation({
    mutationFn: () => reprocess(storeName, { quarantine_ids: [itemId] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quarantine", storeName] });
      queryClient.invalidateQueries({
        queryKey: ["quarantine-detail", storeName, itemId],
      });
      onRelease();
      onClose();
    },
  });

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const item = data?.item;
  const meta = item?.metadata as Record<string, unknown> | null;

  // Derive a display title from metadata (subject for email, title for RSS, etc.)
  const displayTitle = meta
    ? String(meta.subject ?? meta.title ?? "")
    : "";

  const copySourceId = () => {
    if (!item) return;
    navigator.clipboard.writeText(item.source_id);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Separate known metadata rows from extra keys
  const knownRows: { key: string; icon: React.ComponentType<{ className?: string }>; label: string; value: string }[] = [];
  const extraRows: { key: string; value: string }[] = [];

  if (meta) {
    for (const [key, value] of Object.entries(meta)) {
      if (!value || SKIP_KEYS.has(key)) continue;
      const known = KNOWN_META_KEYS[key];
      if (known) {
        knownRows.push({ key, icon: known.icon, label: known.label, value: String(value) });
      } else if (typeof value === "string" || typeof value === "number") {
        extraRows.push({ key, value: String(value) });
      }
    }
  }

  const attachments = meta && Array.isArray(meta.attachments) ? meta.attachments : [];
  const hasMetadata = knownRows.length > 0 || extraRows.length > 0 || attachments.length > 0;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 w-full max-w-lg z-50 bg-surface-0 border-l border-surface-3 shadow-2xl flex flex-col animate-slide-in">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-surface-3">
          <div className="flex-1 min-w-0">
            {isLoading ? (
              <div className="h-5 w-48 bg-surface-2 rounded animate-pulse" />
            ) : item ? (
              <>
                <h2 className="text-sm font-semibold truncate">
                  {displayTitle || item.source_id}
                </h2>
                <p className="text-xs text-content-dim mt-0.5 truncate">
                  {item.source} &middot; {item.source_id}
                </p>
              </>
            ) : (
              <h2 className="text-sm font-semibold text-status-red">
                {data?.error || "Item not found"}
              </h2>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {item && (
              <span
                className={`inline-block px-2 py-0.5 rounded text-[10px] font-medium
                  ${
                    item.risk_level === "high"
                      ? "bg-red-500/15 text-red-400"
                      : item.risk_level === "medium"
                        ? "bg-yellow-500/15 text-yellow-400"
                        : "bg-blue-500/15 text-blue-400"
                  }`}
              >
                {item.risk_level}
              </span>
            )}
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-surface-2 text-content-dim hover:text-content transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-5 h-5 animate-spin text-content-dim" />
            </div>
          )}

          {error && (
            <div className="px-5 py-4 text-sm text-status-red">
              Failed to load item details.
            </div>
          )}

          {item && (
            <div className="divide-y divide-surface-3">
              {/* Metadata section */}
              {hasMetadata && (
                <div className="px-5 py-4 space-y-2">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-content-dim mb-3">
                    Details
                  </h3>
                  {knownRows.map((row) => (
                    <MetaRow key={row.key} icon={row.icon} label={row.label} value={row.value} />
                  ))}
                  {attachments.length > 0 ? (
                    <MetaRow
                      icon={Paperclip}
                      label="Attachments"
                      value={attachments.map(formatAttachment).join(", ")}
                    />
                  ) : null}
                  {extraRows.map((row) => (
                    <MetaRow key={row.key} icon={Info} label={row.key} value={row.value} />
                  ))}
                </div>
              )}

              {/* Classification section */}
              <div className="px-5 py-4 space-y-2">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-content-dim mb-3">
                  Classification
                </h3>
                <div className="flex items-center gap-2">
                  <Shield className="w-3.5 h-3.5 text-content-dim shrink-0" />
                  <span className="text-xs text-content-muted">Risk:</span>
                  <span
                    className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium
                      ${
                        item.risk_level === "high"
                          ? "bg-red-500/15 text-red-400"
                          : item.risk_level === "medium"
                            ? "bg-yellow-500/15 text-yellow-400"
                            : "bg-blue-500/15 text-blue-400"
                      }`}
                  >
                    {item.risk_level}
                  </span>
                </div>
                {item.reason && (
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-content-dim shrink-0 mt-0.5" />
                    <div>
                      <span className="text-xs text-content-muted">Reason:</span>
                      <p className="text-xs text-content mt-0.5">{item.reason}</p>
                    </div>
                  </div>
                )}
                {item.flags.length > 0 && (
                  <div className="flex items-start gap-2">
                    <Shield className="w-3.5 h-3.5 text-content-dim shrink-0 mt-0.5" />
                    <div>
                      <span className="text-xs text-content-muted">
                        Layer 2 Flags:
                      </span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {item.flags.map((flag) => (
                          <span
                            key={flag}
                            className="px-1.5 py-0.5 rounded text-[10px] bg-surface-2 text-content-muted"
                          >
                            {flag}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <Calendar className="w-3.5 h-3.5 text-content-dim shrink-0" />
                  <span className="text-xs text-content-muted">Quarantined:</span>
                  <span className="text-xs text-content">
                    {formatDate(item.quarantined_at)}
                  </span>
                </div>
              </div>

              {/* Content preview */}
              <div className="px-5 py-4">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-content-dim mb-3">
                  Content Preview
                </h3>
                <pre className="text-xs text-content-muted bg-surface-1 border border-surface-3 rounded-lg p-3 max-h-80 overflow-y-auto whitespace-pre-wrap break-words font-mono leading-relaxed">
                  {item.raw_content || "(empty)"}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* Footer actions */}
        {item && (
          <div className="px-5 py-3 border-t border-surface-3 space-y-2">
            <div className="flex items-center gap-2">
              <button
                onClick={() => releaseMutation.mutate()}
                disabled={releaseMutation.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs
                           bg-accent hover:bg-accent-hover text-white
                           disabled:opacity-50 transition-colors"
              >
                {releaseMutation.isPending ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Check className="w-3 h-3" />
                )}
                Release This Item
              </button>
              <button
                onClick={copySourceId}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs
                           bg-surface-2 hover:bg-surface-3 text-content-muted
                           transition-colors"
              >
                {copied ? (
                  <Check className="w-3 h-3 text-status-green" />
                ) : (
                  <Copy className="w-3 h-3" />
                )}
                {copied ? "Copied!" : "Copy Source ID"}
              </button>

              {releaseMutation.isError && (
                <span className="text-xs text-status-red ml-2">
                  Release failed: {(releaseMutation.error as Error).message}
                </span>
              )}
            </div>
            <p className="text-[10px] text-content-dim leading-relaxed">
              Releasing removes this item from quarantine and marks it for re-ingestion on the next poll cycle.
            </p>
          </div>
        )}
      </div>
    </>
  );
}

function MetaRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="w-3.5 h-3.5 text-content-dim shrink-0" />
      <span className="text-xs text-content-muted shrink-0">{label}:</span>
      <span className="text-xs text-content truncate">{value}</span>
    </div>
  );
}
