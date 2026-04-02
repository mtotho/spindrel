import { CheckCircle, AlertTriangle, RefreshCw } from "lucide-react";
import { useReadiness, useSetupGuide } from "../hooks/useMC";
import MarkdownViewer from "../components/MarkdownViewer";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import type { FeatureReadiness } from "../lib/types";

function ReadinessIcon({ ready }: { ready: boolean }) {
  return ready ? (
    <CheckCircle size={16} className="text-green-400 flex-shrink-0" />
  ) : (
    <AlertTriangle size={16} className="text-yellow-400 flex-shrink-0" />
  );
}

function ReadinessRow({ name, feature }: { name: string; feature: FeatureReadiness }) {
  return (
    <div className="flex items-start gap-3 py-2.5 px-3 rounded-lg hover:bg-surface-3 transition-colors">
      <ReadinessIcon ready={feature.ready} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-200 capitalize">{name}</span>
          <span className="text-xs text-gray-500">{feature.count}/{feature.total}</span>
        </div>
        <p className="text-xs text-gray-400 mt-0.5">{feature.detail}</p>
        {feature.issues.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {feature.issues.map((issue, idx) => (
              <li key={idx} className="text-xs text-yellow-400/80">&bull; {issue}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function Setup() {
  const { data: readiness, isLoading: loadingReadiness, error: readinessError, refetch: refetchReadiness, isFetching: fetchingReadiness } = useReadiness();
  const { data: guide, isLoading: loadingGuide } = useSetupGuide();

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100">Setup</h1>
        <p className="text-sm text-gray-500 mt-1">Feature readiness and configuration guide</p>
      </div>

      <div className="bg-surface-2 rounded-xl border border-surface-3 p-4 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-200">Feature Readiness</h2>
          <button
            onClick={() => refetchReadiness()}
            disabled={fetchingReadiness}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md border border-surface-3 text-gray-400 hover:text-gray-200 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={fetchingReadiness ? "animate-spin" : ""} />
            Re-check
          </button>
        </div>
        {loadingReadiness ? (
          <LoadingSpinner />
        ) : readinessError ? (
          <ErrorBanner message={readinessError.message} />
        ) : readiness ? (
          <div className="divide-y divide-surface-3">
            {(Object.entries(readiness) as [string, FeatureReadiness][]).map(([name, feat]) => (
              <ReadinessRow key={name} name={name} feature={feat} />
            ))}
          </div>
        ) : null}
      </div>

      <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
        <h2 className="text-sm font-semibold text-gray-200 mb-3">Setup Guide</h2>
        {loadingGuide ? (
          <LoadingSpinner />
        ) : guide ? (
          <MarkdownViewer content={guide} />
        ) : (
          <p className="text-xs text-gray-500 italic">No setup guide available.</p>
        )}
      </div>
    </div>
  );
}
