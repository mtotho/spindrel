interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

/** Translate raw error messages into human-friendly ones. */
function friendlyMessage(raw: string): string {
  if (raw.includes("502") || raw.includes("Failed to fetch") || raw.includes("NetworkError")) {
    return "Can't reach the agent server. Make sure it's running and the AGENT_SERVER_URL is correct.";
  }
  if (raw.includes("401") || raw.includes("403")) {
    return "Authentication failed. Check that AGENT_SERVER_API_KEY is set correctly.";
  }
  if (raw.includes("404")) {
    return "Resource not found. The channel or file may have been deleted.";
  }
  return raw;
}

export default function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
      <p className="text-sm text-red-400">{friendlyMessage(message)}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 text-xs text-red-400 hover:text-red-300 underline underline-offset-2"
        >
          Try again
        </button>
      )}
    </div>
  );
}
