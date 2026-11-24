// Distintivo visual de cada profesional según su profesión (especialidad):
// un recuadro de color suave alrededor del nombre, con la profesión abreviada al lado
// ("Ana Pérez · FONO"). La abreviatura hace que se distinga también sin ver colores.
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Professional } from "./types";

/** Colores disponibles (definidos en styles.css como .prof-tone-<nombre>, en modo claro y oscuro). */
const TONES = ["green", "sky", "violet", "orange", "pink", "teal", "indigo", "amber"] as const;
type Tone = (typeof TONES)[number];

/** Profesiones conocidas: siempre el mismo color y la misma abreviatura. */
const KNOWN: Record<string, { abbr: string; tone: Tone }> = {
  "psicologia": { abbr: "PSICO", tone: "green" },
  "fonoaudiologia": { abbr: "FONO", tone: "sky" },
  "psicomotricidad": { abbr: "PSICOMOT", tone: "violet" },
  "terapia ocupacional": { abbr: "T.O.", tone: "orange" },
  "psicopedagogia": { abbr: "PSICOPED", tone: "pink" },
  "psiquiatria": { abbr: "PSIQ", tone: "teal" },
  "psiquiatria infantil": { abbr: "PSIQ", tone: "teal" },
  "neuropediatria": { abbr: "NEURO", tone: "indigo" },
  "neurologia": { abbr: "NEURO", tone: "indigo" },
  "fisioterapia": { abbr: "FISIO", tone: "amber" },
};

/** Minúsculas, sin tildes y sin espacios de más: "Fonoaudiología " → "fonoaudiologia". */
function normalize(name: string): string {
  return name.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
}

/** Abreviatura para una profesión que no está en la lista: una palabra → sus primeras letras
 * ("Musicoterapia" → "MUSIC"); varias → las iniciales ("Acompañamiento terapéutico" → "A.T."). */
function abbreviate(normalized: string): string {
  const words = normalized.split(" ").filter((w) => w && !["de", "del", "la", "y", "en"].includes(w));
  if (words.length === 1) return words[0].slice(0, 5).toUpperCase();
  return words.map((w) => w[0].toUpperCase() + ".").join("");
}

/** Para una profesión que no está en la lista: siempre el mismo color para el mismo nombre. */
function toneFor(normalized: string): Tone {
  let h = 0;
  for (const ch of normalized) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TONES[h % TONES.length];
}

export function professionStyle(specialty: string | null | undefined): { abbr: string; tone: Tone } | null {
  if (!specialty) return null;
  const n = normalize(specialty);
  if (!n) return null;
  return KNOWN[n] ?? { abbr: abbreviate(n), tone: toneFor(n) };
}

/** Clase CSS del color de la profesión (para usarla en un botón u otro recuadro). */
export function professionClass(specialty: string | null | undefined): string {
  const style = professionStyle(specialty);
  return style ? `prof-tone prof-tone-${style.tone}` : "";
}

/** Nombre del profesional dentro del recuadro de color de su profesión.
 * Sin profesión conocida, muestra solo el nombre. */
export function ProfTag({ name, specialty }: { name: string; specialty?: string | null }) {
  const style = professionStyle(specialty);
  if (!style) return <>{name}</>;
  return (
    <span className={`prof-tag prof-tone prof-tone-${style.tone}`} title={specialty ?? undefined}>
      {name}
      <span className="prof-abbr" aria-label={`, ${specialty}`}>· {style.abbr}</span>
    </span>
  );
}

// ---------- Profesión a partir del id del profesional ----------
// Algunas listas (turnos, accesos, responsable) traen solo el nombre y el id del profesional.
// La lista de profesionales se pide una sola vez y se reutiliza durante un minuto.

let cache: { at: number; promise: Promise<Professional[]> } | null = null;

function loadProfessionals(): Promise<Professional[]> {
  if (cache && Date.now() - cache.at < 60_000) return cache.promise;
  const promise = api.get<Professional[]>("/professionals").catch(() => {
    cache = null; // si falla, se muestran los nombres sin distintivo y se reintenta la próxima vez
    return [] as Professional[];
  });
  cache = { at: Date.now(), promise };
  return promise;
}

export interface SpecialtyLookup {
  /** id del profesional → su profesión (o null si no se conoce). */
  byId: (professionalId: string | null | undefined) => string | null;
  /** nombre del profesional → su profesión; null si no se conoce o si hay dos con ese nombre. */
  byName: (name: string | null | undefined) => string | null;
}

/** Profesión de cada profesional, para las listas que traen solo su id o su nombre. */
export function useSpecialtyLookup(): SpecialtyLookup {
  const [list, setList] = useState<Professional[]>([]);
  useEffect(() => {
    let cancelled = false;
    loadProfessionals().then((l) => { if (!cancelled) setList(l); });
    return () => { cancelled = true; };
  }, []);
  return useMemo(() => {
    const ids = new Map(list.map((p) => [p.id, p.specialty_name]));
    const names = new Map<string, string | null>();
    const repeated = new Set<string>();
    for (const p of list) {
      if (names.has(p.full_name)) repeated.add(p.full_name);
      names.set(p.full_name, p.specialty_name);
    }
    return {
      byId: (id) => (id ? ids.get(id) ?? null : null),
      byName: (name) => (name && !repeated.has(name) ? names.get(name) ?? null : null),
    };
  }, [list]);
}

/** Varios profesionales (por ejemplo, los colaboradores de un paciente), cada uno con su distintivo. */
export function ProfTagList({ names, lookup }: { names: string[]; lookup: SpecialtyLookup }) {
  return (
    <span className="prof-tag-list">
      {names.map((name, i) => <ProfTag key={`${i}-${name}`} name={name} specialty={lookup.byName(name)} />)}
    </span>
  );
}
