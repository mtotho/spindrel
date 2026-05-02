import { useIsMobile } from "@/src/hooks/useIsMobile";
import {
  EmptyState, FormRow, TextInput, SelectInput, Row, Col,
} from "@/src/components/shared/FormControls";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import type { ChannelSettings } from "@/src/types/api";

export const VERBOSITY_OPTIONS = [
  { label: "Compact", value: "compact" },
  { label: "Standard", value: "standard" },
  { label: "Detailed", value: "detailed" },
];

type NativeContextPolicy = NonNullable<ChannelSettings["effective_native_context_policy"]>;

function policySectionIndexDefaults(policy: NativeContextPolicy): { count: number; verbosity: string } {
  if (policy === "lean") return { count: 8, verbosity: "compact" };
  return { count: 10, verbosity: "standard" };
}

export function SectionIndexSettings({ form, patch, channelId }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
}) {
  const isMobile = useIsMobile();
  const effectivePolicy = (
    form.native_context_policy && form.native_context_policy !== "default"
      ? form.native_context_policy
      : form.effective_native_context_policy
  ) as NativeContextPolicy | undefined;
  const policyDefaults = policySectionIndexDefaults(effectivePolicy ?? "lean");
  const count = form.section_index_count ?? policyDefaults.count;
  const verbosity = form.section_index_verbosity ?? policyDefaults.verbosity;

  const { data: preview } = useQuery({
    queryKey: ["section-index-preview", channelId, count, verbosity, "current"],
    queryFn: () => apiFetch<{ content: string; section_count: number; chars: number }>(
      `/api/v1/admin/channels/${channelId}/section-index-preview?count=${count}&verbosity=${verbosity}&scope=current`,
    ),
    enabled: count > 0,
  });

  return (
    <div>
      <div className="mb-2 text-[11px] leading-relaxed text-text-muted">
        The bot sees the current session archive without spending a tool call and can use{" "}
        <code className="rounded bg-surface-overlay px-1 py-px font-mono text-[10px] text-text-muted">read_conversation_history</code>{" "}
        with a section number to read full transcripts. Leave these blank to use the active context policy default
        ({policyDefaults.count} sections, {policyDefaults.verbosity}).
      </div>
      <Row stack={isMobile}>
        <Col minWidth={isMobile ? 0 : 200}>
          <FormRow label="Index Sections" description="Recent sections injected into context each turn. 0 = disabled.">
            <TextInput
              value={form.section_index_count == null ? "" : count.toString()}
              onChangeText={(v) => { const n = parseInt(v); patch("section_index_count", isNaN(n) ? undefined : n); }}
              placeholder={`${policyDefaults.count} (policy default)`}
              type="number"
            />
          </FormRow>
        </Col>
        <Col minWidth={isMobile ? 0 : 200}>
          <FormRow label="Verbosity" description="How much detail to show per section.">
            <SelectInput
              value={form.section_index_verbosity ?? "__policy__"}
              onChange={(v) => patch("section_index_verbosity", (v === "__policy__" ? undefined : v) as ChannelSettings["section_index_verbosity"])}
              options={[
                { label: `Policy default (${policyDefaults.verbosity})`, value: "__policy__" },
                ...VERBOSITY_OPTIONS,
              ]}
            />
          </FormRow>
        </Col>
      </Row>

      {/* Live preview */}
      {count > 0 && (
        <div className="mt-2">
          {preview && preview.section_count > 0 ? (
            <>
              <div className="max-h-[300px] overflow-auto rounded-md bg-surface-raised/35 px-3.5 py-3 font-mono text-[11px] leading-relaxed text-text-muted whitespace-pre-wrap">
                {preview.content}
              </div>
              <div className="mt-1 text-[10px] text-text-dim">
                ~{preview.chars.toLocaleString()} chars per turn
              </div>
            </>
          ) : (
            <EmptyState message="No sections to preview - run backfill first." />
          )}
        </div>
      )}
    </div>
  );
}
