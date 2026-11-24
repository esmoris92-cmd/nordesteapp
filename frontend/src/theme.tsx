// Modo claro / oscuro. La elección se guarda en este navegador (cada persona elige el suyo).
import { useState } from "react";

type Theme = "light" | "dark";
const KEY = "lumen-tema";

function readSaved(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light"; // sin almacenamiento: modo claro
  }
}

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

/** Se llama al arrancar, antes de dibujar la pantalla, para que no "parpadee" en claro. */
export function applySavedTheme() {
  apply(readSaved());
}

/** Botón redondo fijo en la esquina inferior derecha. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readSaved);
  const dark = theme === "dark";

  function toggle() {
    const next: Theme = dark ? "light" : "dark";
    setTheme(next);
    apply(next);
    try { localStorage.setItem(KEY, next); } catch { /* sin almacenamiento: dura hasta recargar */ }
  }

  const label = dark ? "Pasar a modo claro" : "Pasar a modo oscuro";
  return (
    <button type="button" className="theme-toggle" onClick={toggle} aria-label={label} title={label}>
      {dark ? (
        // Sol: en modo oscuro, el botón ofrece volver al claro
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      ) : (
        // Luna: en modo claro, el botón ofrece pasar al oscuro
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      )}
    </button>
  );
}
