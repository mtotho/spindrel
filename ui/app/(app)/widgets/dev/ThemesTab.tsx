import { useEffect, useMemo, useState } from "react";
import {
  useCreateWidgetTheme,
  useDeleteWidgetTheme,
  useForkWidgetTheme,
  useSetWidgetThemeDefault,
  useUpdateWidgetTheme,
  useWidgetThemeDefault,
  useWidgetThemes,
} from "@/src/api/hooks/useWidgetThemes";
import { useUpdateChannelSettings } from "@/src/api/hooks/useChannels";
import type { WidgetTheme } from "@/src/types/api";

function prettyJson(value: Record<string, string>): string {
  return JSON.stringify(value, null, 2);
}

function ThemePreview({ theme }: { theme: WidgetTheme | null }) {
  const tokens = theme?.light_tokens ?? {};
  const cardStyle = {
    background: tokens.surfaceRaised ?? "#fff",
    border: `1px solid ${tokens.surfaceBorder ?? "#e5e7eb"}`,
    color: tokens.text ?? "#171717",
    borderRadius: 16,
    padding: 16,
    display: "flex",
    flexDirection: "column" as const,
    gap: 12,
    boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
  };
  const subStyle = {
    background: tokens.surfaceOverlay ?? "#f3f4f6",
    border: `1px solid ${tokens.surfaceBorder ?? "#e5e7eb"}`,
    borderRadius: 12,
    padding: 12,
    display: "flex",
    flexDirection: "column" as const,
    gap: 8,
  };
  const buttonStyle = {
    background: tokens.accent ?? "#3b82f6",
    color: "#fff",
    border: "none",
    borderRadius: 10,
    padding: "8px 12px",
    fontWeight: 600,
  };

  return (
    <div className="rounded-2xl border border-surface-border bg-surface-raised p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-text-muted">Preview</div>
          <div className="text-sm text-text-muted">{theme?.name ?? "Widget theme"}</div>
        </div>
      </div>
      <div style={cardStyle}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-base font-semibold">Quick Home</div>
            <div className="text-sm" style={{ color: tokens.textMuted ?? "#737373" }}>Live just now</div>
          </div>
          <span
            className="rounded-full px-2 py-1 text-[11px] font-semibold"
            style={{
              background: tokens.accentSubtle ?? "#eff6ff",
              color: tokens.accent ?? "#3b82f6",
              border: `1px solid ${tokens.accentBorder ?? "#93c5fd"}`,
            }}
          >
            {theme?.is_builtin ? "Builtin" : "Custom"}
          </span>
        </div>
        <div style={subStyle}>
          <div className="text-xs font-semibold uppercase tracking-[0.12em]" style={{ color: tokens.textMuted ?? "#737373" }}>
            Kitchen temp
          </div>
          <div className="text-4xl font-semibold">63.1°F</div>
          <div className="text-sm" style={{ color: tokens.textMuted ?? "#737373" }}>Humidity 47%</div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button style={buttonStyle}>Kitchen on</button>
          <button
            style={{
              ...buttonStyle,
              background: tokens.surfaceOverlay ?? "#f3f4f6",
              color: tokens.text ?? "#171717",
              border: `1px solid ${tokens.surfaceBorder ?? "#e5e7eb"}`,
            }}
          >
            Kitchen off
          </button>
        </div>
      </div>
    </div>
  );
}

export function ThemesTab({ originChannelId }: { originChannelId?: string | null }) {
  const { data: themes } = useWidgetThemes();
  const { data: defaultTheme } = useWidgetThemeDefault();
  const [selectedRef, setSelectedRef] = useState<string>("builtin/default");
  const createMut = useCreateWidgetTheme();
  const deleteMut = useDeleteWidgetTheme();
  const setGlobalMut = useSetWidgetThemeDefault();
  const updateMut = useUpdateWidgetTheme(selectedRef);
  const updateChannelMut = useUpdateChannelSettings(originChannelId ?? "");
  const selectedTheme = useMemo(
    () => themes?.find((theme) => theme.ref === selectedRef) ?? null,
    [themes, selectedRef],
  );

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [lightJson, setLightJson] = useState("{}");
  const [darkJson, setDarkJson] = useState("{}");
  const [customCss, setCustomCss] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!themes?.length) return;
    if (!themes.some((theme) => theme.ref === selectedRef)) {
      setSelectedRef(themes[0].ref);
    }
  }, [themes, selectedRef]);

  useEffect(() => {
    setName(selectedTheme?.name ?? "");
    setSlug(selectedTheme?.is_builtin ? "" : (selectedTheme?.slug ?? ""));
    setLightJson(prettyJson(selectedTheme?.light_tokens ?? {}));
    setDarkJson(prettyJson(selectedTheme?.dark_tokens ?? {}));
    setCustomCss(selectedTheme?.custom_css ?? "");
    setError(null);
  }, [selectedTheme]);

  const parseDraft = () => {
    try {
      return {
        name: name.trim(),
        slug: slug.trim() || undefined,
        light_tokens: JSON.parse(lightJson || "{}"),
        dark_tokens: JSON.parse(darkJson || "{}"),
        custom_css: customCss,
      };
    } catch (err: any) {
      throw new Error(err?.message || "Invalid JSON");
    }
  };

  const handleCreate = async () => {
    try {
      const draft = parseDraft();
      if (!draft.name) throw new Error("Theme name is required");
      const created = await createMut.mutateAsync(draft);
      setSelectedRef(created.ref);
    } catch (err: any) {
      setError(err?.message || "Failed to create theme");
    }
  };

  const handleSave = async () => {
    if (!selectedTheme || selectedTheme.is_builtin) return;
    try {
      const draft = parseDraft();
      await updateMut.mutateAsync(draft);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Failed to save theme");
    }
  };

  const canApplyToChannel = !!originChannelId;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="min-h-0 overflow-auto rounded-2xl border border-surface-border bg-surface-raised p-3">
          <div className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-text-muted">Theme library</div>
          <div className="space-y-2">
            {(themes ?? []).map((theme) => {
              const isGlobal = defaultTheme?.ref === theme.ref;
              return (
                <button
                  key={theme.ref}
                  type="button"
                  onClick={() => setSelectedRef(theme.ref)}
                  className={`w-full rounded-xl border px-3 py-3 text-left transition-colors ${
                    selectedRef === theme.ref
                      ? "border-accent bg-accent/10"
                      : "border-surface-border bg-surface hover:bg-surface-overlay"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-text">{theme.name}</div>
                    <span className="text-[11px] text-text-muted">{theme.is_builtin ? "builtin" : "custom"}</span>
                  </div>
                  <div className="mt-1 text-xs text-text-muted">{theme.ref}</div>
                  {isGlobal && <div className="mt-2 text-[11px] font-semibold text-accent">Global default</div>}
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-h-0 overflow-auto rounded-2xl border border-surface-border bg-surface-raised p-4">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-lg font-semibold text-text">Theme editor</div>
              <div className="text-sm text-text-muted">
                Builtin themes are immutable. Fork them before editing, or create one from scratch.
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  setSelectedRef("builtin/default");
                  setName("New theme");
                  setSlug("");
                  setLightJson("{}");
                  setDarkJson("{}");
                  setCustomCss("");
                  setError(null);
                }}
                className="rounded-lg border border-surface-border px-3 py-2 text-sm font-medium text-text hover:bg-surface-overlay"
              >
                New scratch theme
              </button>
              {selectedTheme && (
                <ForkButton
                  theme={selectedTheme}
                  onForked={(ref) => setSelectedRef(ref)}
                />
              )}
            </div>
          </div>

          {error && <div className="mb-3 rounded-lg border border-danger/20 bg-danger/5 px-3 py-2 text-sm text-danger">{error}</div>}

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2">
                <label className="block">
                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-text-muted">Name</div>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full rounded-xl border border-surface-border bg-surface px-3 py-2 text-sm text-text"
                  />
                </label>
                <label className="block">
                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-text-muted">Slug</div>
                  <input
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    disabled={selectedTheme?.is_builtin}
                    className="w-full rounded-xl border border-surface-border bg-surface px-3 py-2 text-sm text-text disabled:opacity-50"
                  />
                </label>
              </div>

              <label className="block">
                <div className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-text-muted">Light tokens JSON</div>
                <textarea
                  value={lightJson}
                  onChange={(e) => setLightJson(e.target.value)}
                  rows={12}
                  className="w-full rounded-xl border border-surface-border bg-surface px-3 py-2 font-mono text-xs text-text"
                />
              </label>

              <label className="block">
                <div className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-text-muted">Dark tokens JSON</div>
                <textarea
                  value={darkJson}
                  onChange={(e) => setDarkJson(e.target.value)}
                  rows={12}
                  className="w-full rounded-xl border border-surface-border bg-surface px-3 py-2 font-mono text-xs text-text"
                />
              </label>

              <label className="block">
                <div className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-text-muted">Custom CSS</div>
                <textarea
                  value={customCss}
                  onChange={(e) => setCustomCss(e.target.value)}
                  rows={10}
                  className="w-full rounded-xl border border-surface-border bg-surface px-3 py-2 font-mono text-xs text-text"
                />
              </label>

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleCreate}
                  className="rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white"
                >
                  Create theme
                </button>
                {selectedTheme && !selectedTheme.is_builtin && (
                  <button
                    type="button"
                    onClick={handleSave}
                    className="rounded-lg bg-surface-overlay px-3 py-2 text-sm font-semibold text-text"
                  >
                    Save changes
                  </button>
                )}
                {selectedTheme && !selectedTheme.is_builtin && (
                  <button
                    type="button"
                    onClick={async () => {
                      await deleteMut.mutateAsync(selectedTheme.ref);
                      setSelectedRef("builtin/default");
                    }}
                    className="rounded-lg border border-danger/30 px-3 py-2 text-sm font-medium text-danger"
                  >
                    Delete theme
                  </button>
                )}
                {selectedTheme && (
                  <button
                    type="button"
                    onClick={() => setGlobalMut.mutate(selectedTheme.ref)}
                    className="rounded-lg border border-surface-border px-3 py-2 text-sm font-medium text-text"
                  >
                    Apply globally
                  </button>
                )}
                {selectedTheme && canApplyToChannel && (
                  <button
                    type="button"
                    onClick={() => updateChannelMut.mutate({ widget_theme_ref: selectedTheme.ref === "builtin/default" ? null : selectedTheme.ref })}
                    className="rounded-lg border border-surface-border px-3 py-2 text-sm font-medium text-text"
                  >
                    Apply to current channel
                  </button>
                )}
              </div>
            </div>

            <ThemePreview theme={selectedTheme} />
          </div>
        </div>
      </div>
    </div>
  );
}

function ForkButton({
  theme,
  onForked,
}: {
  theme: WidgetTheme;
  onForked: (ref: string) => void;
}) {
  const forkMut = useForkWidgetTheme(theme.ref);

  return (
    <button
      type="button"
      onClick={async () => {
        const forked = await forkMut.mutateAsync({ name: `${theme.name} Copy` });
        onForked(forked.ref);
      }}
      className="rounded-lg border border-surface-border px-3 py-2 text-sm font-medium text-text hover:bg-surface-overlay"
    >
      Fork theme
    </button>
  );
}
