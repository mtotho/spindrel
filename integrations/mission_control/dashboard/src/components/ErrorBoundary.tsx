import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center h-screen bg-surface-0">
          <div className="bg-surface-1 rounded-xl border border-surface-3 p-6 max-w-md mx-4 text-center">
            <p className="text-2xl mb-3">⚠</p>
            <h2 className="text-lg font-semibold text-content mb-2">Something went wrong</h2>
            <p className="text-sm text-content-muted mb-4">
              {this.state.error?.message || "An unexpected error occurred."}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
              className="px-4 py-2 text-sm rounded-lg bg-accent/15 text-accent-hover hover:bg-accent/25 transition-colors"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
