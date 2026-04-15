import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Check, Zap } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";

/** Ordered tiers from cheapest to most expensive. */
const TIER_ORDER = ["free", "fast", "standard", "capable", "frontier"] as const;
type TierName = (typeof TIER_ORDER)[number];

const TIER_LABELS: Record<TierName, { label: string; hint: string }> = {
  free: { label: "Free", hint: "Zero-cost / rate-limited" },
  fast: { label: "Fast", hint: "Trivial extraction, scanning" },
  standard: { label: "Standard", hint: "Research, code review" },
  capable: { label: "Capable", hint: "Multi-step reasoning" },
  frontier: { label: "Frontier", hint: "Complex / high-stakes" },
};

interface TierEntry {
  model: string;
  provider_id?: string | null;
}
type TiersMap = Partial<Record<TierName, TierEntry>>;

function useGlobalModelTiers() {
  return useQuery({
    queryKey: ["global-model-tiers"],
    queryFn: () =>
      apiFetch<{ tiers: TiersMap }>("/api/v1/admin/global-model-tiers"),
  });
}

function useUpdateGlobalModelTiers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tiers: TiersMap) =>
      apiFetch("/api/v1/admin/global-model-tiers", {
        method: "PUT",
        body: JSON.stringify({ tiers }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["global-model-tiers"] });
    },
  });
}

export function ModelTiersSection() {
  const t = useThemeTokens();
  const query = useGlobalModelTiers();
  const updateMut = useUpdateGlobalModelTiers();

  const [tiers, setTiers] = useState<TiersMap>({});
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (query.data?.tiers) {
      setTiers(query.data.tiers);
      setDirty(false);
    }
  }, [query.data]);

  const handleChange = useCallback(
    (tier: TierName, model: string, providerId?: string | null) => {
      setTiers((prev) => ({
        ...prev,
        [tier]: { model, provider_id: providerId ?? null },
      }));
      setDirty(true);
      setSaved(false);
    },
    [],
  );

  const handleClear = useCallback(
    (tier: TierName) => {
      setTiers((prev) => {
        const next = { ...prev };
        delete next[tier];
        return next;
      });
      setDirty(true);
      setSaved(false);
    },
    [],
  );

  const handleSave = useCallback(async () => {
    // Strip empty entries
    const clean: TiersMap = {};
    for (const [k, v] of Object.entries(tiers)) {
      if (v && v.model) {
        clean[k as TierName] = v;
      }
    }
    await updateMut.mutateAsync(clean);
    setDirty(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }, [tiers, updateMut]);

  const configuredCount = Object.values(tiers).filter((v) => v?.model).length;

  return (
    <Section title="Model Tiers">
      <span
        style={{
          color: t.textDim,
          fontSize: 12,
          marginBottom: 12,
          display: "block",
        }}
      >
        Map performance tiers to concrete models. Sub-agents and delegation use
        these tiers to select cost-appropriate models automatically.
      </span>

      {query.isLoading ? (
        <div className="chat-spinner" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {TIER_ORDER.map((tier) => {
            const entry = tiers[tier];
            const meta = TIER_LABELS[tier];
            return (
              <div
                key={tier}
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                }}
              >
                {/* Tier label */}
                <div
                  style={{
                    width: 100,
                    flexShrink: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: 1,
                  }}
                >
                  <span
                    style={{
                      color: t.text,
                      fontSize: 13,
                      fontWeight: 600,
                    }}
                  >
                    {meta.label}
                  </span>
                  <span
                    style={{
                      color: t.textDim,
                      fontSize: 10,
                    }}
                  >
                    {meta.hint}
                  </span>
                </div>

                {/* Model selector */}
                <div style={{ flex: 1 }}>
                  <LlmModelDropdown
                    value={entry?.model ?? ""}
                    selectedProviderId={entry?.provider_id}
                    onChange={(m, pid) => {
                      if (!m) {
                        handleClear(tier);
                      } else {
                        handleChange(tier, m, pid);
                      }
                    }}
                    placeholder="Not configured"
                    allowClear
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Save button */}
      <div
        style={{
          marginTop: 16,
          display: "flex",
          flexDirection: "row",
          gap: 12,
          alignItems: "center",
        }}
      >
        <button
          onClick={handleSave}
          disabled={!dirty || updateMut.isPending}
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            backgroundColor: dirty ? t.accent : "rgba(128,128,128,0.3)",
            paddingLeft: 16,
            paddingRight: 16,
            paddingTop: 8,
            paddingBottom: 8,
            borderRadius: 8,
            opacity: dirty ? 1 : 0.5,
            border: "none",
            cursor: dirty && !updateMut.isPending ? "pointer" : "default",
          }}
        >
          {updateMut.isPending ? (
            <div className="chat-spinner" />
          ) : saved ? (
            <Check size={14} color="#fff" />
          ) : (
            <Save size={14} color="#fff" />
          )}
          <span style={{ color: "#fff", fontSize: 13, fontWeight: 600 }}>
            {saved ? "Saved" : "Save"}
          </span>
        </button>
        {updateMut.isError && (
          <span style={{ color: t.danger, fontSize: 12 }}>Failed to save</span>
        )}
        {!dirty && configuredCount > 0 && (
          <span style={{ color: t.textDim, fontSize: 11 }}>
            {configuredCount} of {TIER_ORDER.length} tiers configured
          </span>
        )}
      </div>
    </Section>
  );
}
