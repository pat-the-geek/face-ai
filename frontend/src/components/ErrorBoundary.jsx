import { Component } from "react";

/**
 * Capture les erreurs JS dans l'arbre React et affiche un fallback visible,
 * au lieu de laisser l'écran complètement blanc (comportement par défaut
 * quand un composant throw sans qu'un parent ne le gère).
 *
 * En dev, on imprime aussi la pile dans la console pour faciliter le debug.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, errorInfo) {
    // eslint-disable-next-line no-console
    console.error("FACE.ai ErrorBoundary capture :", error, errorInfo);
    this.setState({ errorInfo });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="h-screen flex items-center justify-center p-8 bg-[var(--bg-primary)] text-[var(--text-primary)]">
          <div className="max-w-2xl border border-[var(--accent)] p-6 font-mono text-sm">
            <div className="text-[var(--accent)] uppercase tracking-wider text-xs mb-3">
              ⚠ Crash React capturé
            </div>
            <div className="mb-2">
              <strong>{this.state.error.name || "Error"}:</strong>{" "}
              {this.state.error.message || "(pas de message)"}
            </div>
            {this.state.errorInfo?.componentStack && (
              <details className="mt-3 text-xs text-[var(--text-secondary)]">
                <summary className="cursor-pointer hover:text-[var(--text-primary)]">
                  componentStack
                </summary>
                <pre className="mt-2 whitespace-pre-wrap break-words text-[10px]">
                  {this.state.errorInfo.componentStack}
                </pre>
              </details>
            )}
            <div className="mt-4 text-xs text-[var(--text-secondary)]">
              Cmd+Shift+R pour réessayer après correctif.
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
