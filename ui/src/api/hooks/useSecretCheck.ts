import { useMutation } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SecretCheckResult {
  has_secrets: boolean;
  exact_matches: number;
  pattern_matches: Array<{
    type: string;
    match: string;
    start: number;
    end: number;
  }>;
}

export function useSecretCheck() {
  return useMutation({
    mutationFn: (message: string) =>
      apiFetch<SecretCheckResult>("/chat/check-secrets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      }),
  });
}
