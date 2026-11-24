// Enrutador mínimo basado en el "hash" de la URL (#/pacientes/123).
// Evita una dependencia extra y no requiere configuración en el servidor.
import { useEffect, useState } from "react";

export interface Route {
  parts: string[];
  params: URLSearchParams;
}

function parse(hash: string): Route {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  return { parts: path.split("/").filter(Boolean), params: new URLSearchParams(query) };
}

export function useRoute(): Route {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return parse(hash);
}

export function navigate(path: string) {
  window.location.hash = path.startsWith("#") ? path : `#${path}`;
}
