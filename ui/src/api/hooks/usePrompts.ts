import { useMutation } from "@tanstack/react-query";
import { apiFetch } from "../client";

export function useGeneratePrompt() {
  return useMutation({
    mutationFn: (body: { context: string; user_input: string }) =>
      apiFetch<{ prompt: string }>("/api/v1/admin/generate-prompt", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  });
}
