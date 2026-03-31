import { useThemeTokens } from "@/src/theme/tokens";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import {
  FormRow, TextInput, SelectInput, Row, Col,
} from "@/src/components/shared/FormControls";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import type { ChannelSettings } from "@/src/types/api";

export const VERBOSITY_OPTIONS = [
  { label: "Compact", value: "compact" },
  { label: "Standard", value: "standard" },
  { label: "Detailed", value: "detailed" },
];

export function SectionIndexSettings({ form, patch, channelId }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
}) {
  const t = useThemeTokens();
  const isMobile = useIsMobile();
  const count = form.section_index_count ?? 10;
  const verbosity = form.section_index_verbosity ?? "standard";

  const { data: preview } = useQuery({
    queryKey: ["section-index-preview", channelId, count, verbosity],
    queryFn: () => apiFetch<{ content: string; section_count: number; chars: number }>(
      `/api/v1/admin/channels/${channelId}/section-index-preview?count=${count}&verbosity=${verbosity}`,
    ),
    enabled: count > 0,
  });

  return (
    <div>
      <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 8, lineHeight: "1.5" }}>
        The bot sees what's in the archive without spending a tool call and can use <code style={{ color: t.codeText }}>read_conversation_history</code> with a section number to read full transcripts.
      </div>
      <Row stack={isMobile}>
        <Col minWidth={isMobile ? 0 : 200}>
          <FormRow label="Index Sections" description="Recent sections injected into context each turn. 0 = disabled.">
            <TextInput
              value={count === 10 && form.section_index_count == null ? "" : count.toString()}
              onChangeText={(v) => patch("section_index_count", v ? parseInt(v) || 0 : undefined)}
              placeholder="10"
              type="number"
            />
          </FormRow>
        </Col>
        <Col minWidth={isMobile ? 0 : 200}>
          <FormRow label="Verbosity" description="How much detail to show per section.">
            <SelectInput
              value={verbosity}
              onChange={(v) => patch("section_index_verbosity", v || undefined)}
              options={VERBOSITY_OPTIONS}
            />
          </FormRow>
        </Col>
      </Row>

      {/* Live preview */}
      {count > 0 && (
        <div style={{ marginTop: 8 }}>
          {preview && preview.section_count > 0 ? (
            <>
              <div style={{
                background: t.codeBg, border: `1px solid ${t.codeBorder}`, borderRadius: 8,
                padding: "12px 14px", fontFamily: "monospace", fontSize: 11,
                color: t.contentText, whiteSpace: "pre-wrap", lineHeight: "1.5",
                maxHeight: 300, overflow: "auto",
              }}>
                {preview.content}
              </div>
              <div style={{ fontSize: 10, color: t.textDim, marginTop: 4 }}>
                ~{preview.chars.toLocaleString()} chars per turn
              </div>
            </>
          ) : (
            <div style={{
              padding: "12px 14px", background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 8, fontSize: 11, color: t.textDim, fontStyle: "italic",
            }}>
              No sections to preview — run backfill first.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
