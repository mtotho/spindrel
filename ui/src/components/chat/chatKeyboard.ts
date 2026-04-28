type KeyboardTargetLike = {
  tagName?: string;
  isContentEditable?: boolean;
  closest?: (selector: string) => unknown;
};

export function isEditableKeyboardTarget(target: EventTarget | KeyboardTargetLike | null | undefined): boolean {
  const el = target as KeyboardTargetLike | null | undefined;
  const tag = typeof el?.tagName === "string" ? el.tagName.toUpperCase() : "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el?.isContentEditable) return true;
  return !!el?.closest?.('[contenteditable="true"], [role="textbox"]');
}
