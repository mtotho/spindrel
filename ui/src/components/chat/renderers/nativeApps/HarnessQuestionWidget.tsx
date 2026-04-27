import { useEffect, useMemo, useState } from "react";
import { ApiError, apiFetch } from "@/src/api/client";
import { parsePayload, PreviewCard, type NativeAppRendererProps } from "./shared";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

interface HarnessQuestion {
  id: string;
  question: string;
  header?: string;
  options?: Array<string | { label?: string; value?: string; description?: string }>;
  allows_multiple?: boolean;
  allows_other?: boolean;
  required?: boolean;
}

interface HarnessQuestionState {
  interaction_id?: string;
  runtime?: string | null;
  title?: string;
  status?: string;
  questions?: HarnessQuestion[];
  answers?: Array<{
    question_id: string;
    answer?: string;
    selected_options?: string[];
  }>;
  notes?: string;
  submit_label?: string;
}

function statusCopy(status: string) {
  if (status === "submitted") return "Answered";
  if (status === "expired") return "Expired";
  if (status === "cancelled") return "Cancelled";
  return "Waiting for your answer";
}

function optionParts(option: string | { label?: string; value?: string; description?: string }) {
  if (typeof option === "string") return { label: option, description: "" };
  return {
    label: String(option.label || option.value || "").trim(),
    description: String(option.description || "").trim(),
  };
}

function errorMessage(err: unknown) {
  if (err instanceof ApiError) return err.detail ?? err.message;
  return err instanceof Error ? err.message : "Unable to submit your answer.";
}

export function HarnessQuestionWidget({
  envelope,
  sessionId,
  hostSurface,
  t,
}: NativeAppRendererProps) {
  const payload = useMemo(() => parsePayload(envelope), [envelope]);
  const state = (payload.state ?? {}) as HarnessQuestionState;
  const interactionId = state.interaction_id;
  const questions = Array.isArray(state.questions) ? state.questions : [];
  const status = state.status || "pending";
  const title = state.title?.trim() || "Claude has a question";
  const submitLabel = state.submit_label?.trim() || "Submit and continue";
  const [selected, setSelected] = useState<Record<string, string[]>>(() => {
    const initial: Record<string, string[]> = {};
    for (const answer of state.answers ?? []) {
      initial[answer.question_id] = answer.selected_options ?? [];
    }
    return initial;
  });
  const [text, setText] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const answer of state.answers ?? []) {
      initial[answer.question_id] = answer.answer ?? "";
    }
    return initial;
  });
  const [notes, setNotes] = useState(state.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [localStatus, setLocalStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "pending") return;
    const nextSelected: Record<string, string[]> = {};
    const nextText: Record<string, string> = {};
    for (const answer of state.answers ?? []) {
      nextSelected[answer.question_id] = answer.selected_options ?? [];
      nextText[answer.question_id] = answer.answer ?? "";
    }
    setSelected(nextSelected);
    setText(nextText);
    setNotes(state.notes ?? "");
  }, [interactionId, state.answers, state.notes, status]);

  if (!interactionId || !questions.length) {
    return <PreviewCard title={title} description="This harness question is missing its form data." t={t} />;
  }

  const effectiveStatus = localStatus || status;
  const readonly = effectiveStatus !== "pending";
  const isPending = effectiveStatus === "pending";
  const isTerminal = hostSurface === "plain";
  const shellStyle = isTerminal
    ? {
        border: "none",
        borderRadius: 0,
        background: "transparent",
        padding: 0,
        fontFamily: TERMINAL_FONT_STACK,
      }
    : {
        border: "none",
        borderRadius: 0,
        background: "transparent",
        padding: 0,
      };

  const toggleOption = (question: HarnessQuestion, option: string) => {
    if (readonly) return;
    setSelected((prev) => {
      const current = prev[question.id] ?? [];
      if (question.allows_multiple) {
        const next = current.includes(option)
          ? current.filter((item) => item !== option)
          : [...current, option];
        return { ...prev, [question.id]: next };
      }
      return { ...prev, [question.id]: current.includes(option) ? [] : [option] };
    });
    setError(null);
  };

  const updateText = (questionId: string, value: string) => {
    if (readonly) return;
    setText((prev) => ({ ...prev, [questionId]: value }));
    setError(null);
  };

  const submit = async () => {
    if (!sessionId) {
      setError("This question is not attached to a session.");
      return;
    }
    const answers = questions.map((question) => ({
      question_id: question.id,
      selected_options: selected[question.id] ?? [],
      answer: (text[question.id] ?? "").trim() || null,
    }));
    const missing = questions.filter((question, index) => {
      if (question.required === false) return false;
      const answer = answers[index];
      return !answer.answer && !answer.selected_options.length;
    });
    if (missing.length) {
      setError(`Answer ${missing.length === 1 ? "the required question" : "the required questions"} first.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/v1/sessions/${sessionId}/harness-interactions/${interactionId}/answer`, {
        method: "POST",
        body: JSON.stringify({ answers, notes: notes.trim() || null }),
      });
      setLocalStatus("submitted");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        ...shellStyle,
        display: "flex",
        flexDirection: "column",
        gap: isTerminal ? 10 : 12,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
          <div style={{ fontSize: isTerminal ? 12 : 13, fontWeight: 650, color: t.text }}>{title}</div>
          <div style={{ fontSize: isTerminal ? 11 : 12, color: t.textMuted }}>
            {state.runtime || "Harness"} paused for input.
          </div>
        </div>
        <span
          style={{
            flex: "0 0 auto",
            border: `1px solid ${readonly ? t.surfaceBorder : t.accentBorder}`,
            background: readonly ? t.surfaceRaised : t.accentSubtle,
            color: readonly ? t.textMuted : t.accent,
            borderRadius: 999,
            padding: "3px 8px",
            fontSize: isTerminal ? 10.5 : 11,
            fontWeight: 650,
          }}
        >
          {statusCopy(effectiveStatus)}
        </span>
      </div>

      {questions.map((question) => {
        const options = Array.isArray(question.options)
          ? question.options.map(optionParts).filter((option) => option.label)
          : [];
        const chosen = selected[question.id] ?? [];
        return (
          <div key={question.id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: isTerminal ? 2 : 3 }}>
              {question.header ? (
                <div style={{ fontSize: isTerminal ? 10.5 : 11, color: t.textDim, fontWeight: 650, textTransform: "uppercase" }}>
                  {question.header}
                </div>
              ) : null}
              <div style={{ fontSize: isTerminal ? 12 : 13, color: t.text, fontWeight: 600 }}>
                {question.question}
                {question.required === false ? null : <span style={{ color: t.danger }}> *</span>}
              </div>
            </div>
            {options.length ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {options.map((option) => {
                  const active = chosen.includes(option.label);
                  return (
                    <button
                      key={option.label}
                      type="button"
                      disabled={readonly}
                      onClick={() => toggleOption(question, option.label)}
                      style={{
                        border: `1px solid ${active ? t.accentBorder : t.surfaceBorder}`,
                        background: active ? t.accentSubtle : t.surfaceRaised,
                        color: active ? t.accent : t.text,
                        borderRadius: isTerminal ? 5 : 8,
                        padding: isTerminal ? "5px 7px" : "6px 9px",
                        fontSize: isTerminal ? 11.5 : 12,
                        cursor: readonly ? "default" : "pointer",
                        opacity: readonly && !active ? 0.65 : 1,
                        fontFamily: isTerminal ? TERMINAL_FONT_STACK : undefined,
                      }}
                    >
                      <span style={{ display: "flex", flexDirection: "column", gap: 2, textAlign: "left" }}>
                        <span>{option.label}</span>
                        {option.description ? (
                          <span style={{ color: active ? t.accent : t.textDim, fontSize: isTerminal ? 10.5 : 11, fontWeight: 400 }}>
                            {option.description}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : null}
            {question.allows_other !== false ? (
              <textarea
                value={text[question.id] ?? ""}
                disabled={readonly}
                onChange={(event) => updateText(question.id, event.target.value)}
                placeholder={options.length ? "Add details..." : "Type your answer..."}
                rows={options.length ? 2 : 3}
                style={{
                  width: "100%",
                  resize: "vertical",
                  border: `1px solid ${t.inputBorder}`,
                  background: t.inputBg,
                  color: t.text,
                  borderRadius: 8,
                  padding: "8px 10px",
                  fontSize: isTerminal ? 12 : 13,
                  lineHeight: 1.45,
                  outline: "none",
                  fontFamily: isTerminal ? TERMINAL_FONT_STACK : undefined,
                }}
              />
            ) : null}
          </div>
        );
      })}

      {isPending ? (
        <textarea
          value={notes}
          disabled={readonly}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Optional notes..."
          rows={2}
          style={{
            width: "100%",
            resize: "vertical",
            border: `1px solid ${t.inputBorder}`,
            background: t.inputBg,
            color: t.text,
            borderRadius: 8,
            padding: "8px 10px",
            fontSize: isTerminal ? 12 : 13,
            lineHeight: 1.45,
            outline: "none",
            fontFamily: isTerminal ? TERMINAL_FONT_STACK : undefined,
          }}
        />
      ) : null}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span style={{ color: error ? t.danger : t.textDim, fontSize: isTerminal ? 11 : 12 }}>
          {error || (readonly ? "Your response is stored in this session." : "Answering resumes the harness turn.")}
        </span>
        {isPending ? (
          <button
            type="button"
            disabled={busy || readonly}
            onClick={submit}
            style={{
              flex: "0 0 auto",
              border: `1px solid ${t.accentBorder}`,
              background: t.accent,
              color: "#ffffff",
              borderRadius: 8,
              padding: "7px 11px",
              fontSize: isTerminal ? 12 : 13,
              fontWeight: 650,
              cursor: busy || readonly ? "default" : "pointer",
              opacity: busy || readonly ? 0.7 : 1,
              fontFamily: isTerminal ? TERMINAL_FONT_STACK : undefined,
            }}
          >
            {busy ? "Submitting..." : submitLabel}
          </button>
        ) : null}
      </div>
    </div>
  );
}
