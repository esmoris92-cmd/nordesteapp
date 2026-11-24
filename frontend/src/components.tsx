// Componentes reutilizables de la interfaz.
import { useEffect, useId, useRef, useState, type InputHTMLAttributes, type ReactNode, type RefObject } from "react";
import { dismiss, subscribe, type Toast } from "./toast";

export function Loading({ text = "Cargando…" }: { text?: string }) {
  return (
    <p className="muted" role="status" aria-live="polite">
      {text}
    </p>
  );
}

export function ErrorBox({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <div className="alert alert-error" role="alert">
      {message}
    </div>
  );
}

export function SuccessBox({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <div className="alert alert-ok" role="status" aria-live="polite">
      {message}
    </div>
  );
}

/** Aviso amarillo (por ejemplo, "Tu sesión expiró"): no es un error ni un éxito. */
export function WarnBox({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <div className="alert alert-warn" role="status" aria-live="polite">
      {message}
    </div>
  );
}

// Ventanas abiertas, de la de abajo a la de arriba: Escape y Tab solo actúan sobre la de
// arriba (por ejemplo, la confirmación que se abre encima de la ventana de un turno).
const openDialogs: symbol[] = [];

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Ventana encima de la pantalla: el foco queda adentro (Tab no se escapa), Escape o un clic
 * afuera la cierran, y al cerrarse el foco vuelve a donde estaba. */
export function Dialog({ onClose, labelledBy, describedBy, role = "dialog", className = "", initialFocus,
  closeOnBackdrop = true, children }: {
  onClose: () => void;
  labelledBy?: string;
  describedBy?: string;
  role?: "dialog" | "alertdialog";
  className?: string;
  initialFocus?: RefObject<HTMLElement | null>;
  closeOnBackdrop?: boolean; // false en formularios largos: un clic afuera no pierde lo escrito
  children: ReactNode;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const id = Symbol("ventana");
    openDialogs.push(id);
    const previous = document.activeElement as HTMLElement | null;
    // Foco inicial: el indicado, o un campo marcado con data-autofocus, o la ventana.
    const box = boxRef.current;
    (initialFocus?.current ?? box?.querySelector<HTMLElement>("[data-autofocus]") ?? box)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (openDialogs[openDialogs.length - 1] !== id) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !boxRef.current) return;
      const items = Array.from(boxRef.current.querySelectorAll<HTMLElement>(FOCUSABLE))
        .filter((el) => el.offsetParent !== null);
      if (items.length === 0) { event.preventDefault(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !boxRef.current.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !boxRef.current.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      const at = openDialogs.indexOf(id);
      if (at >= 0) openDialogs.splice(at, 1);
      if (previous && document.contains(previous)) previous.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="modal-backdrop" onClick={() => { if (closeOnBackdrop) closeRef.current(); }}>
      <div ref={boxRef} className={`modal ${className}`.trim()} role={role} aria-modal="true"
           aria-labelledby={labelledBy} aria-describedby={describedBy} tabIndex={-1}
           onClick={(event) => event.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

/** Aviso flotante de "cambio realizado con éxito" (uno solo en toda la aplicación). */
export function ToastHost() {
  const [toast, setToast] = useState<Toast | null>(null);
  useEffect(() => subscribe(setToast), []);
  return (
    <div className="toast-region" role="status" aria-live="polite">
      {toast && (
        <div key={toast.id} className="toast">
          <span className="toast-icon" aria-hidden="true">✓</span>
          <span>{toast.message}</span>
          <button type="button" className="toast-close" onClick={dismiss} aria-label="Cerrar aviso">×</button>
        </div>
      )}
    </div>
  );
}

/** Logo del Centro Interdisciplinario Nordeste (la figura, sin el nombre).
 * Imagen en public/logo-nordeste.png, recortada del logo original de la clínica. */
export function Logo({ size = 34 }: { size?: number }) {
  return <img className="logo" src="/logo-nordeste.png" width={size} height={size} alt="" aria-hidden="true" />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

interface FieldProps {
  label: string;
  hint?: string;
  required?: boolean;
  children: (id: string, describedBy: string | undefined) => ReactNode;
}

/** Etiqueta + control + ayuda, enlazados para lectores de pantalla. */
export function Field({ label, hint, required, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className="field">
      <label htmlFor={id}>
        {label}
        {required && (
          <span className="required" aria-hidden="true">
            {" "}
            *
          </span>
        )}
      </label>
      {children(id, hintId)}
      {hint && (
        <small id={hintId} className="muted">
          {hint}
        </small>
      )}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/** Campo de contraseña con un botón para verla mientras se escribe. */
export function PasswordInput({ show, onToggle, ...props }: InputHTMLAttributes<HTMLInputElement> & {
  show: boolean; onToggle: () => void;
}) {
  return (
    <div className="password-field">
      <input {...props} type={show ? "text" : "password"} />
      <button type="button" className="btn btn-small" onClick={onToggle} aria-pressed={show}
              aria-label={show ? "Ocultar contraseña" : "Mostrar contraseña"}>
        {show ? "Ocultar" : "Mostrar"}
      </button>
    </div>
  );
}
