"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

/** Isolates a feature panel: if a member's panel throws, only that panel shows an error. */
export class ErrorBoundary extends Component<{ name: string; children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Feature panel "${this.props.name}" crashed`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="border-l-2 border-danger bg-danger-soft p-4 text-sm text-fg">
          <p className="font-semibold">The “{this.props.name}” panel crashed.</p>
          <p className="mt-1 break-words">{this.state.error.message}</p>
          <button
            type="button"
            className="mt-2 rounded border border-line-strong px-2 py-1 text-xs hover:bg-hover"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
