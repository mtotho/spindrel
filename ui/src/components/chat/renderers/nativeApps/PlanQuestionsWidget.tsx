import { useMemo, useState } from "react";
import { apiFetch } from "@/src/api/client";
import type { ToolResultEnvelope } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { parsePayload, PreviewCard } from "./shared";

interface PlanQuestionField {
  id: string;
  label: string;
  type: "text" | "textarea" | "select";
  help?: string;
  placeholder?: string;
  required?: boolean;
  choices?: string[];
}

export function PlanQuestionsWidget({
  envelope,
  sessionId,
  t,
}: {
  envelope: ToolResultEnvelope;
  sessionId?: string;
  t: ThemeTokens;
}) {
  const payload = useMemo(() => parsePayload(envelope), [envelope]);
  const state = (payload.state ?? {}) as Record<string, unknown>;
  const title = typeof state.title === "string" && state.title.trim() ? state.title : "Plan questions";
  const intro = typeof state.intro === "string" ? state.intro : "";
  const submitLabel = typeof state.submit_label === "string" && state.submit_label.trim()
    ? state.submit_label
    : "Submit Answers";
  const questions = Array.isArray(state.questions) ? state.questions as PlanQuestionField[] : [];
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!questions.length) {
    return <PreviewCard title={title} description="No questions were provided." t={t} />;
  }

  const updateValue = (id: string, value: string) => {
    setValues((prev) => ({ ...prev, [id]: value }));
    if (error) setError(null);
    if (submitted) setSubmitted(false);
  };

  const buildAnswerText = () => {
    const missing = questions.filter((q) => q.required && !String(values[q.id] ?? "").trim());
    if (missing.length) {
      setError(`Answer ${missing.length === 1 ? "this required question" : "the required questions"} first.`);
      return null;
    }
    const lines: string[] = ["Plan answers:"];
    for (const q of questions) {
      const answer = String(values[q.id] ?? "").trim();
      if (!answer) continue;
      if (q.type === "textarea" || answer.includes("\n")) {
        lines.push(`- ${q.label}:`);
        for (const line of answer.split(/\r?\n/)) {
          lines.push(`  ${line}`);
        }
      } else {
        lines.push(`- ${q.label}: ${answer}`);
      }
    }
    return lines.join("\n");
  };

  const submitAnswers = async () => {
    const text = buildAnswerText();
    if (!text) return;
    if (!sessionId) {
      setError("This session is missing plan context, so the answers could not be saved.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/sessions/${sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({
          content: text,
          source: "plan_questions",
          notify: false,
          run_agent: true,
        }),
      });
      setSubmitted(true);
      setValues({});
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to save your answers.";
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{title}</div>
        {intro ? <div style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.55 }}>{intro}</div> : null}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {questions.map((question) => {
          const value = values[question.id] ?? "";
          return (
            <div
              key={question.id}
              style={{
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 10,
                background: t.surface,
                padding: 12,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                  {question.label}
                  {question.required ? <span style={{ color: t.danger }}> *</span> : null}
                </div>
                {question.help ? <div style={{ fontSize: 12, color: t.textDim }}>{question.help}</div> : null}
              </div>
              {question.type === "select" ? (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {(question.choices ?? []).map((choice) => {
                    const active = value === choice;
                    return (
                      <button
                        key={choice}
                        type="button"
                        onClick={() => updateValue(question.id, choice)}
                        style={{
                          borderRadius: 999,
                          border: `1px solid ${active ? t.accentBorder : t.surfaceBorder}`,
                          background: active ? t.accentSubtle : t.surfaceRaised,
                          color: active ? t.accent : t.textMuted,
                          padding: "6px 10px",
                          fontSize: 12,
                          cursor: "pointer",
                        }}
                      >
                        {choice}
                      </button>
                    );
                  })}
                </div>
              ) : question.type === "textarea" ? (
                <textarea
                  value={value}
                  onChange={(e) => updateValue(question.id, e.target.value)}
                  placeholder={question.placeholder}
                  style={{
                    minHeight: 92,
                    width: "100%",
                    resize: "vertical",
                    borderRadius: 8,
                    border: `1px solid ${t.surfaceBorder}`,
                    background: t.surfaceRaised,
                    color: t.text,
                    padding: 10,
                    fontSize: 13,
                    lineHeight: 1.5,
                    outline: "none",
                  }}
                />
              ) : (
                <input
                  value={value}
                  onChange={(e) => updateValue(question.id, e.target.value)}
                  placeholder={question.placeholder}
                  style={{
                    width: "100%",
                    borderRadius: 8,
                    border: `1px solid ${t.surfaceBorder}`,
                    background: t.surfaceRaised,
                    color: t.text,
                    padding: "10px 12px",
                    fontSize: 13,
                    outline: "none",
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ fontSize: 12, color: error ? t.danger : t.textDim }}>
          {error ?? (submitted ? "Saved to chat history and sent to the agent." : "Submitting saves these answers as a real user message in the chat history.")}
        </div>
        <button
          type="button"
          onClick={() => void submitAnswers()}
          disabled={busy}
          style={{
            borderRadius: 999,
            border: `1px solid ${t.accentBorder}`,
            background: t.accentSubtle,
            color: t.accent,
            padding: "8px 14px",
            fontSize: 12,
            fontWeight: 600,
            cursor: busy ? "wait" : "pointer",
            opacity: busy ? 0.7 : 1,
          }}
        >
          {busy ? "Saving..." : submitLabel}
        </button>
      </div>
    </div>
  );
}
