// Confirmación propia de Nordeste (reemplaza a window.confirm).
//
// Las ventanas nativas del navegador pueden estar bloqueadas (por ejemplo, si alguna vez se
// marcó "no permitir más diálogos de esta página"); en ese caso window.confirm responde
// "no" sin mostrar nada y el botón parece no funcionar. Esta ventana no depende de eso.
import { useEffect, useId, useRef, useState } from "react";
import { Dialog } from "./components";

type Request = {
  message: string;
  confirmLabel: string;
  danger: boolean;
  resolve: (ok: boolean) => void;
};

let show: ((request: Request) => void) | null = null;

/** Pregunta y espera la respuesta: true si la persona confirma. */
export function askConfirm(
  message: string,
  options: { confirmLabel?: string; danger?: boolean } = {},
): Promise<boolean> {
  return new Promise((resolve) => {
    const request = {
      message, resolve,
      confirmLabel: options.confirmLabel ?? "Confirmar",
      danger: options.danger ?? false,
    };
    if (show) show(request);
    else resolve(window.confirm(message)); // por si la ventana todavía no está montada
  });
}

/** Se monta una sola vez, junto a la aplicación. */
export function ConfirmHost() {
  const [request, setRequest] = useState<Request | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const textId = useId();

  useEffect(() => {
    show = (next) => setRequest((previous) => {
      previous?.resolve(false);
      return next;
    });
    return () => { show = null; };
  }, []);

  if (!request) return null;

  function close(ok: boolean) {
    request?.resolve(ok);
    setRequest(null);
  }

  return (
    <Dialog key={String(request.message)} role="alertdialog" describedBy={textId} initialFocus={confirmRef}
            onClose={() => close(false)}>
      <p id={textId} className="modal-text">{request.message}</p>
      <div className="form-actions">
        <button type="button" className="btn" onClick={() => close(false)}>Cancelar</button>
        <button type="button" ref={confirmRef} className={request.danger ? "btn btn-danger" : "btn btn-primary"}
                onClick={() => close(true)}>
          {request.confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}

/** Antes de descartar un formulario con texto escrito: true si se puede cerrar. */
export async function confirmDiscard(...texts: string[]): Promise<boolean> {
  if (!texts.some((t) => t.trim() !== "")) return true;
  return askConfirm("¿Descartar lo que escribiste? Todavía no se guardó.",
                    { confirmLabel: "Descartar", danger: true });
}
