import { Link } from "react-router-dom";
import { Save, Check, Server, KeyRound, Eye } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section } from "@/src/components/shared/FormControls";
import {
  FallbackModelList,
  type FallbackModelEntry,
} from "@/src/components/shared/FallbackModelList";

export function GlobalSection({
  fbModels,
  onFbChange,
  onFbSave,
  fbDirty,
  fbSaving,
  fbSaved,
  fbError,
  fbLoading,
}: {
  fbModels: FallbackModelEntry[];
  onFbChange: (v: FallbackModelEntry[]) => void;
  onFbSave: () => void;
  fbDirty: boolean;
  fbSaving: boolean;
  fbSaved: boolean;
  fbError: boolean;
  fbLoading: boolean;
}) {
  const t = useThemeTokens();
  return (
    <div>
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 16,
        }}
      >
        <Link to="/admin/providers">
          <button
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              borderRadius: 6,
              paddingLeft: 12,
              paddingRight: 12,
              paddingTop: 8,
              paddingBottom: 8,
              border: `1px solid ${t.surfaceBorder}`,
              background: "none",
              cursor: "pointer",
            }}
          >
            <Server size={14} color={t.accent} />
            <span style={{ color: t.accent, fontSize: 13 }}>
              Providers
            </span>
          </button>
        </Link>
        <Link to="/admin/api-keys">
          <button
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              borderRadius: 6,
              paddingLeft: 12,
              paddingRight: 12,
              paddingTop: 8,
              paddingBottom: 8,
              border: `1px solid ${t.surfaceBorder}`,
              background: "none",
              cursor: "pointer",
            }}
          >
            <KeyRound size={14} color={t.accent} />
            <span style={{ color: t.accent, fontSize: 13 }}>
              API Keys
            </span>
          </button>
        </Link>
        <Link to="/admin/config-state">
          <button
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              borderRadius: 6,
              paddingLeft: 12,
              paddingRight: 12,
              paddingTop: 8,
              paddingBottom: 8,
              border: `1px solid ${t.surfaceBorder}`,
              background: "none",
              cursor: "pointer",
            }}
          >
            <Eye size={14} color={t.accent} />
            <span style={{ color: t.accent, fontSize: 13 }}>
              Config State
            </span>
          </button>
        </Link>
      </div>

      <Section title="Global Fallback Models">
        <span
          style={{ color: t.textDim, fontSize: 12, marginBottom: 12, display: "block" }}
        >
          Catch-all fallback chain appended after channel/bot fallbacks. When
          all per-channel and per-bot fallbacks are exhausted, these models are
          tried in order.
        </span>

        {fbLoading ? (
          <div className="chat-spinner" />
        ) : (
          <FallbackModelList value={fbModels} onChange={onFbChange} />
        )}
      </Section>

      <div
        style={{
          marginTop: 20,
          display: "flex",
          flexDirection: "row",
          gap: 12,
          alignItems: "center",
        }}
      >
        <button
          onClick={onFbSave}
          disabled={!fbDirty || fbSaving}
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            backgroundColor: fbDirty ? t.accent : "rgba(128,128,128,0.3)",
            paddingLeft: 16,
            paddingRight: 16,
            paddingTop: 8,
            paddingBottom: 8,
            borderRadius: 8,
            opacity: fbDirty ? 1 : 0.5,
            border: "none",
            cursor: fbDirty && !fbSaving ? "pointer" : "default",
          }}
        >
          {fbSaving ? (
            <div className="chat-spinner" />
          ) : fbSaved ? (
            <Check size={14} color="#fff" />
          ) : (
            <Save size={14} color="#fff" />
          )}
          <span style={{ color: "#fff", fontSize: 13, fontWeight: 600 }}>
            {fbSaved ? "Saved" : "Save"}
          </span>
        </button>
        {fbError && (
          <span style={{ color: t.danger, fontSize: 12 }}>
            Failed to save
          </span>
        )}
      </div>
    </div>
  );
}
