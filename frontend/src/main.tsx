import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { OwnerApp } from "./owner/OwnerApp";
import { ToastHost } from "./components";
import { ConfirmHost } from "./confirm";
import { ErrorBoundary } from "./ErrorBoundary";
import { applySavedTheme, ThemeToggle } from "./theme";
import "./styles.css";

applySavedTheme();

// lumengestion.uy/sistema: la pantalla del dueño del sistema (sesión aparte de las clínicas).
const isOwnerArea = window.location.pathname.replace(/\/+$/, "") === "/sistema";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <ErrorBoundary>
        {isOwnerArea ? <OwnerApp /> : <App />}
        <ConfirmHost />
        <ToastHost />
        <ThemeToggle />
      </ErrorBoundary>
    </StrictMode>,
  );
}
