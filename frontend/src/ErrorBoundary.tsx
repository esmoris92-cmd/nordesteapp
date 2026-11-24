// Si una pantalla falla al dibujarse, muestra un mensaje en lugar de dejar todo en blanco.
import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Solo en la consola del navegador (para diagnosticar); no se envía a ningún lado.
    console.error("Nordeste: error al mostrar la pantalla", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="center">
        <div className="card login-card" role="alert">
          <h1>Algo no se pudo mostrar</h1>
          <p>
            Puede que el navegador esté usando una versión vieja de Nordeste. Recargá la página
            ignorando la caché con <strong>⌘ + Shift + R</strong> (en Windows, Ctrl + Shift + R).
          </p>
          <p className="muted small">Si el problema sigue, revisá la Terminal donde corre Nordeste.</p>
          <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
            Recargar
          </button>
        </div>
      </main>
    );
  }
}
