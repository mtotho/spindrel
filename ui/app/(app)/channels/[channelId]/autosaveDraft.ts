export function stableAutosaveString(value: unknown): string {
  return JSON.stringify(value);
}

export function shouldApplyServerDraft(options: {
  dirty: boolean;
  pending: boolean;
  hasScheduledSave: boolean;
}): boolean {
  return !options.dirty && !options.pending && !options.hasScheduledSave;
}

export function saveMatchesCurrentDraft(options: {
  savedDraft: unknown;
  currentDraft: unknown;
}): boolean {
  return stableAutosaveString(options.savedDraft) === stableAutosaveString(options.currentDraft);
}
