// Datos del profesional para el Cronograma BPS: nombres y apellidos por separado, formación y
// quién expidió el título (las dos últimas, de las listas oficiales del BPS).
import { useEffect, useState } from "react";
import { api } from "../api";
import { Field } from "../components";
import { hasFeature } from "../session";
import type { BpsLists, Clinic, User } from "../types";

let cached: Promise<BpsLists> | null = null;

/** Listas del BPS (se piden una sola vez). */
export function useBpsLists(): BpsLists | null {
  const [lists, setLists] = useState<BpsLists | null>(null);
  useEffect(() => {
    if (!cached) cached = api.get<BpsLists>("/bps-schedule/lists").catch((e) => { cached = null; throw e; });
    let alive = true;
    cached.then((l) => { if (alive) setLists(l); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);
  return lists;
}

export type BpsForm = {
  first_name: string; middle_name: string; last_name: string; second_last_name: string;
  bps_training: string; degree_issuer: string;
};

export function bpsForm(user: User): BpsForm {
  return {
    first_name: user.first_name ?? "", middle_name: user.middle_name ?? "",
    last_name: user.last_name ?? "", second_last_name: user.second_last_name ?? "",
    bps_training: user.bps_training ?? "", degree_issuer: user.degree_issuer ?? "",
  };
}

/** Para enviar al servidor: los vacíos van como null (así se pueden borrar). */
export function bpsPayload(form: BpsForm) {
  return Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]));
}

/** ¿Al profesional le faltan datos obligatorios para el Cronograma BPS? (Solo si la clínica
 * tiene habilitada la función BPS y AYEX.) */
export function bpsMissing(user: User, clinic: Pick<Clinic, "features">): boolean {
  return hasFeature(clinic, "bps") && user.role === "professional"
    && !(user.first_name && user.last_name && user.bps_training && user.degree_issuer);
}

export function BpsFields({ form, onChange, required }: {
  form: BpsForm; onChange: (form: BpsForm) => void; required: boolean;
}) {
  const lists = useBpsLists();
  const set = (key: keyof BpsForm) => (e: { target: { value: string } }) => onChange({ ...form, [key]: e.target.value });
  const options = (values: string[] | undefined, current: string) => [
    ...(values ?? []), ...(current && values && !values.includes(current) ? [current] : []),
  ];
  return (
    <>
      <Field label="Primer nombre" required={required}>
        {(id) => <input id={id} required={required} maxLength={100} value={form.first_name} onChange={set("first_name")} />}
      </Field>
      <Field label="Segundo nombre">
        {(id) => <input id={id} maxLength={100} value={form.middle_name} onChange={set("middle_name")} />}
      </Field>
      <Field label="Primer apellido" required={required}>
        {(id) => <input id={id} required={required} maxLength={100} value={form.last_name} onChange={set("last_name")} />}
      </Field>
      <Field label="Segundo apellido">
        {(id) => <input id={id} maxLength={100} value={form.second_last_name} onChange={set("second_last_name")} />}
      </Field>
      <Field label="Formación académica" required={required}>
        {(id) => (
          <select id={id} required={required} value={form.bps_training} onChange={set("bps_training")}>
            <option value="">{lists ? "Elegir…" : "Cargando…"}</option>
            {options(lists?.trainings, form.bps_training).map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        )}
      </Field>
      <Field label="Título expedido por" required={required}>
        {(id) => (
          <select id={id} required={required} value={form.degree_issuer} onChange={set("degree_issuer")}>
            <option value="">{lists ? "Elegir…" : "Cargando…"}</option>
            {options(lists?.degree_issuers, form.degree_issuer).map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        )}
      </Field>
    </>
  );
}
