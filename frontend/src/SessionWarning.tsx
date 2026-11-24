// Aviso antes de que la sesión se cierre, para no perder lo que se está escribiendo.
//
// * Por inactividad: el servidor cierra la sesión tras ``idleMinutes`` sin peticiones. Escribir
//   una nota larga no hace peticiones; por eso, si la persona está usando el teclado o el
//   mouse (clics), se renueva sola. Si de verdad no hay nadie, se avisa 5 minutos antes con
//   el botón "Seguir conectado".
// * Por el máximo de horas: no se puede extender; se avisa 10 minutos antes. Lo escrito queda
//   como borrador y se recupera al volver a entrar (ver drafts.ts).
import { useEffect, useState } from "react";
import { api, lastServerActivity } from "./api";
import { usePendingDrafts } from "./drafts";
import { fmtTime } from "./labels";

const WARN_IDLE_MS = 5 * 60_000;
const WARN_END_MS = 10 * 60_000;
const RENEW_AFTER_MS = 5 * 60_000; // con la persona activa, renovar si pasaron 5 min sin peticiones
const ACTIVE_MS = 2 * 60_000; // "activa" = tecleó o hizo clic en los últimos 2 min

export function SessionWarning({ idleMinutes, expiresAt }: { idleMinutes: number; expiresAt: string | null }) {
  const [now, setNow] = useState(Date.now());
  const pending = usePendingDrafts();

  useEffect(() => {
    let lastInput = Date.now();
    const onInput = () => { lastInput = Date.now(); };
    window.addEventListener("keydown", onInput, true);
    window.addEventListener("pointerdown", onInput, true);
    const timer = setInterval(() => {
      const t = Date.now();
      if (t - lastInput < ACTIVE_MS && t - lastServerActivity() > RENEW_AFTER_MS) {
        api.get("/auth/me").catch(() => undefined); // la persona está: se renueva sin avisar
      }
      setNow(t);
    }, 20_000);
    return () => {
      window.removeEventListener("keydown", onInput, true);
      window.removeEventListener("pointerdown", onInput, true);
      clearInterval(timer);
    };
  }, []);

  const idleLeft = idleMinutes * 60_000 - (now - lastServerActivity());
  const end = expiresAt ? new Date(expiresAt).getTime() : null;
  const endLeft = end === null ? Infinity : end - now;

  if (endLeft <= WARN_END_MS && endLeft > 0) {
    return (
      <div className="session-warning" role="alert">
        <span>
          Tu sesión termina a las {fmtTime(expiresAt!)} (máximo de horas por seguridad).
          {pending > 0 ? " Guardá lo que estás escribiendo; si no llegás, se recupera al volver a entrar." : ""}
        </span>
      </div>
    );
  }
  if (idleLeft <= WARN_IDLE_MS && idleLeft > 0) {
    const minutes = Math.max(1, Math.ceil(idleLeft / 60_000));
    return (
      <div className="session-warning" role="alert">
        <span>
          Tu sesión se cierra en {minutes} {minutes === 1 ? "minuto" : "minutos"} por inactividad.
        </span>
        <button type="button" className="btn btn-small btn-primary"
                onClick={() => { api.get("/auth/me").then(() => setNow(Date.now())).catch(() => undefined); }}>
          Seguir conectado
        </button>
      </div>
    );
  }
  return null;
}
