// Borradores de lo que se está escribiendo (notas, correcciones, objetivos, informes).
//
// Si se cambia de pestaña o de pantalla sin guardar, el texto queda aquí y vuelve al regresar.
// También sobrevive a un vencimiento de sesión: al volver a entrar la MISMA persona, lo
// recupera. Solo vive en la memoria de esta pestaña del navegador (nunca en el disco), se borra
// al cerrar sesión y no se muestra a otra persona que entre después.
import { useCallback, useEffect, useState } from "react";

const store = new Map<string, string>();
const listeners = new Set<() => void>();
let owner: string | null = null;

function changed() {
  for (const l of listeners) l();
}

/** Al entrar alguien: si no es la misma persona dueña de los borradores, se descartan. */
export function setDraftOwner(userId: string) {
  if (owner !== userId) {
    store.clear();
    owner = userId;
    changed();
  }
}

/** Al cerrar sesión. */
export function clearAllDrafts() {
  store.clear();
  changed();
}

export function hasDraft(key: string): boolean {
  return store.has(key);
}

export function hasPendingDrafts(): boolean {
  return store.size > 0;
}

/** Cantidad de borradores sin guardar (se actualiza sola). */
export function usePendingDrafts(): number {
  const [count, setCount] = useState(store.size);
  useEffect(() => {
    const l = () => setCount(store.size);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  return count;
}

/** Texto con borrador. Devuelve [valor, cambiar, descartar, recuperado]. El borrador se guarda
 * solo si el texto difiere del inicial y no está vacío. ``recuperado`` indica que al abrir
 * el formulario había un borrador pendiente. */
export function useDraft(key: string, initial = ""): [string, (v: string) => void, () => void, boolean] {
  const [restored] = useState(() => store.has(key));
  const [value, setValue] = useState(() => store.get(key) ?? initial);
  const set = useCallback((next: string) => {
    setValue(next);
    if (next.trim() === "" || next === initial) store.delete(key);
    else store.set(key, next);
    changed();
  }, [key, initial]);
  const discard = useCallback(() => {
    store.delete(key);
    setValue(initial);
    changed();
  }, [key, initial]);
  return [value, set, discard, restored];
}
