import { useState } from "react";
import { ChevronRight, Copy } from "lucide-react";

import { ActionButton } from "@/src/components/shared/SettingsControls";
import { writeToClipboard } from "@/src/utils/clipboard";
import type { MachineProfileSetupGuide } from "@/src/api/hooks/useMachineTargets";

export function ProfileSetupGuide({ guide }: { guide: MachineProfileSetupGuide }) {
  const [open, setOpen] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  async function handleCopy(key: string, value: string) {
    await writeToClipboard(value);
    setCopiedKey(key);
    window.setTimeout(() => {
      setCopiedKey((current) => (current === key ? null : current));
    }, 1200);
  }

  const stepCount = guide.steps.length;

  return (
    <div className="rounded-md border border-border-subtle bg-surface-base/40">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-[12px] font-semibold text-text hover:bg-surface-overlay/40"
        aria-expanded={open}
      >
        <span className="flex items-center gap-1.5">
          <ChevronRight
            size={13}
            className={`text-text-dim transition-transform ${open ? "rotate-90" : ""}`}
          />
          How to set this up ({stepCount} {stepCount === 1 ? "step" : "steps"})
        </span>
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t border-border-subtle px-3 py-3">
          {guide.summary && (
            <p className="text-[11px] leading-snug text-text-dim">{guide.summary}</p>
          )}
          <ol className="flex flex-col gap-3">
            {guide.steps.map((step, index) => (
              <li key={index} className="flex flex-col gap-1.5">
                <div className="flex items-baseline gap-2">
                  <span className="text-[11px] font-mono text-text-dim">{index + 1}.</span>
                  <span className="text-[12px] font-semibold text-text">{step.title}</span>
                </div>
                {step.description && (
                  <p className="pl-5 text-[11px] leading-snug text-text-dim whitespace-pre-line">
                    {step.description}
                  </p>
                )}
                {step.commands && step.commands.length > 0 && (
                  <div className="flex flex-col gap-1.5 pl-5">
                    {step.commands.map((command, commandIndex) => {
                      const key = `${index}:${commandIndex}`;
                      const copied = copiedKey === key;
                      return (
                        <div
                          key={key}
                          className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-overlay/50 px-2.5 py-1.5"
                        >
                          <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-[11px] text-text">
                            {command.value}
                          </code>
                          <ActionButton
                            label={copied ? "Copied" : "Copy"}
                            onPress={() => void handleCopy(key, command.value)}
                            variant="secondary"
                            size="small"
                            icon={<Copy size={11} />}
                          />
                        </div>
                      );
                    })}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
