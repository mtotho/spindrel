import { useMutation } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { SecretCheckResult } from "@/src/types/api";

export type { SecretCheckResult };

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
