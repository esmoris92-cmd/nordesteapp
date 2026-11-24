// Piezas compartidas de la pantalla del dueño del sistema.
import { useId, useRef, useState } from "react";
import { Dialog } from "../components";
import type { TemporaryAccess } from "./types";

export function CopyButton({ text, label = "Copiar" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState<"ok" | "error" | null>(null);
  async function copy() {
    try {
      if (!navigator.clipboard) throw new Error("sin portapapeles");
      await navigator.clipboard.writeText(text);
      setCopied("ok");
    } catch {
      setCopied("error");
    }
  }
  return (
    <>
      <button type="button" className="btn btn-small" onClick={copy}>{copied === "ok" ? "✓ Copiado" : label}</button>
      {copied === "error" && <span className="small"> No se pudo copiar: seleccionalo y copialo a mano.</span>}
    </>
  );
}

/** Muestra UNA sola vez la contraseña temporal de un administrador (o del profesional
 * titular de un espacio independiente: ``who="Profesional"``). */
export function AccessDialog({ title, data, onClose, who = "Administrador" }: {
  title: string; data: TemporaryAccess; onClose: () => void; who?: string;
}) {
  const titleId = useId();
  const done = useRef<HTMLButtonElement>(null);
  return (
    <Dialog labelledBy={titleId} onClose={onClose} closeOnBackdrop={false} initialFocus={done}>
      <h2 id={titleId} className="modal-title">{title}</h2>
      <div className="temp-password">
        <p>{who}: <strong>{data.full_name}</strong></p>
        <p>Correo para entrar: <code>{data.email}</code></p>
        <p>
          Contraseña temporal: <code>{data.temporary_password}</code>{" "}
          <CopyButton text={data.temporary_password} />
        </p>
        <p className="small">
          Pasáselos por un medio seguro (en persona o por teléfono, mejor que por el mismo correo).{" "}
          <strong>No se vuelve a mostrar.</strong> Al entrar en <strong>{window.location.host}</strong> va a tener
          que elegir una contraseña nueva que solo conozca esa persona.
        </p>
      </div>
      <div className="form-actions">
        <button ref={done} type="button" className="btn btn-primary" onClick={onClose}>Listo</button>
      </div>
    </Dialog>
  );
}
