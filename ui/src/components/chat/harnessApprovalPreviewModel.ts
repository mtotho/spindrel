export type HarnessApprovalPreviewModel =
  | { kind: "bash"; toolName: string; command: string; description: string | null }
  | { kind: "diff"; toolName: string; target: string | null; body: string }
  | { kind: "code"; toolName: string; target: string | null; body: string }
  | { kind: "plan"; toolName: string; body: string }
  | { kind: "json"; toolName: string; body: string };

function stringArg(args: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}

function diffLineCount(value: string): number {
  const lines = value.split(/\r?\n/);
  return lines.length > 1 && lines[lines.length - 1] === "" ? lines.length - 1 : lines.length;
}

export function unifiedDiffPreviewFromStrings({
  path,
  oldString,
  newString,
}: {
  path: string;
  oldString: string;
  newString: string;
}): string {
  const oldLines = oldString.split(/\r?\n/);
  const newLines = newString.split(/\r?\n/);
  if (oldLines.length > 1 && oldLines[oldLines.length - 1] === "") oldLines.pop();
  if (newLines.length > 1 && newLines[newLines.length - 1] === "") newLines.pop();
  return [
    `--- a/${path}`,
    `+++ b/${path}`,
    `@@ -1,${diffLineCount(oldString)} +1,${diffLineCount(newString)} @@`,
    ...oldLines.map((line) => `-${line}`),
    ...newLines.map((line) => `+${line}`),
  ].join("\n");
}

export function buildHarnessApprovalPreview(
  toolName: string,
  args: Record<string, unknown>,
): HarnessApprovalPreviewModel {
  if (toolName === "Bash") {
    return {
      kind: "bash",
      toolName,
      command: stringArg(args, "command") ?? "",
      description: stringArg(args, "description"),
    };
  }

  if (toolName === "Edit") {
    const target = stringArg(args, "file_path", "path");
    const oldString = stringArg(args, "old_string") ?? "";
    const newString = stringArg(args, "new_string") ?? "";
    if (target && (oldString || newString)) {
      return {
        kind: "diff",
        toolName,
        target,
        body: unifiedDiffPreviewFromStrings({ path: target, oldString, newString }),
      };
    }
  }

  if (toolName === "Write") {
    return {
      kind: "code",
      toolName,
      target: stringArg(args, "file_path", "path"),
      body: stringArg(args, "content") ?? "",
    };
  }

  if (toolName === "ExitPlanMode") {
    return {
      kind: "plan",
      toolName,
      body: stringArg(args, "plan") ?? "",
    };
  }

  return {
    kind: "json",
    toolName,
    body: JSON.stringify(args, null, 2),
  };
}
