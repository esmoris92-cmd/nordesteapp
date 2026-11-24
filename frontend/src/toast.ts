// Aviso breve de "cambio realizado" que aparece fijo en pantalla (abajo a la derecha) y se
// va solo. Lo dispara automáticamente cualquier guardado exitoso (ver api.ts); una pantalla
// puede reemplazarlo por un texto más preciso con notify("Paciente … agregado con éxito.").
export interface Toast { id: number; message: string }

type Listener = (toast: Toast | null) => void;
const listeners = new Set<Listener>();
let current: Toast | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;

export const DEFAULT_SUCCESS = "Cambio realizado con éxito.";
const VISIBLE_MS = 4500;

function emit() {
  for (const l of listeners) l(current);
}

/** Muestra un aviso de éxito (reemplaza al que esté visible). */
export function notify(message: string = DEFAULT_SUCCESS) {
  current = { id: ++seq, message };
  emit();
  clearTimeout(timer);
  timer = setTimeout(dismiss, VISIBLE_MS);
}

export function dismiss() {
  clearTimeout(timer);
  current = null;
  emit();
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  listener(current);
  return () => { listeners.delete(listener); };
}
