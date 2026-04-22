/** Extract name and arguments from a ToolCall regardless of format */
export function normalizeToolCall(tc) {
    if (tc.function) {
        return { name: tc.function.name, arguments: tc.function.arguments };
    }
    return { name: tc.name ?? tc.tool_name ?? "unknown", arguments: tc.arguments ?? tc.args ?? "{}" };
}
