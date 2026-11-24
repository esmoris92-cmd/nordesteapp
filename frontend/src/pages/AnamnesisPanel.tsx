// Pestaña Anamnesis: Ficha de Anamnesis Multidisciplinaria con campos para completar.
//
// Hay UNA anamnesis por paciente que se va completando entre todos los profesionales con
// acceso clínico. Cada "Guardar" crea una versión nueva (quién y cuándo) y las anteriores se
// pueden consultar en el historial. Los datos del encabezado (nombre, nacimiento, edad,
// escuela) salen de la ficha del paciente: se corrigen allí.
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import { askConfirm } from "../confirm";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useDraft } from "../drafts";
import { useAction, useAsync } from "../hooks";
import { fmtDate, fmtDateTime, fullName, todayLocal } from "../labels";
import { useSession } from "../session";
import { notify } from "../toast";
import type { Institution, Note, PatientDetail } from "../types";
import {
  ANAMNESIS_SECTIONS, MAX_SIBLINGS, sameArea, siblingKeys, type FieldDef, type Group, type Section,
} from "./anamnesisForm";

type Data = Record<string, string>;

export interface Version {
  id: string;
  author_id: string;
  author_name: string;
  created_at: string;
  data: Data;
}

export interface Anamnesis {
  current: Version | null;
  versions: { id: string; author_name: string; created_at: string; fields: number }[];
}

/** "6 años y 3 meses" (para niños, los meses importan). */
export function ageText(birth: string | null): string {
  if (!birth) return "—";
  const [y, m, d] = birth.split("-").map(Number);
  const now = new Date();
  let months = (now.getFullYear() - y) * 12 + (now.getMonth() + 1 - m);
  if (now.getDate() < d) months -= 1;
  if (months < 0) return "—";
  const years = Math.floor(months / 12);
  const rest = months % 12;
  const yText = years === 1 ? "1 año" : `${years} años`;
  if (years >= 18 || rest === 0) return yText;
  return `${yText} y ${rest === 1 ? "1 mes" : `${rest} meses`}`;
}

/** Cantidad de filas de hermanos a mostrar: las que tienen algo y, al editar, al menos una. */
function siblingCount(data: Data, editing: boolean): number {
  let last = 0;
  for (let n = 1; n <= MAX_SIBLINGS; n++) {
    const k = siblingKeys(n);
    if (data[k.name] || data[k.age]) last = n;
  }
  return editing ? Math.max(last, 1) : last;
}

/** Secciones en orden; en "Evaluación por áreas", primero la profesión de quien la completa. */
function useSections(): { sections: Section[]; myArea: string | null } {
  const { user } = useSession();
  return useMemo(() => {
    const mine = user.specialty_name;
    const sections = ANAMNESIS_SECTIONS.map((s) => {
      if (!s.areas || !mine) return s;
      const own = s.groups.filter((g) => g.title && sameArea(g.title, mine));
      return { ...s, groups: [...own, ...s.groups.filter((g) => !own.includes(g))] };
    });
    const myArea = mine && ANAMNESIS_SECTIONS.some((s) => s.areas && s.groups.some((g) => g.title && sameArea(g.title, mine)))
      ? mine : null;
    return { sections, myArea };
  }, [user.specialty_name]);
}

export function AnamnesisPanel({ patient }: { patient: PatientDetail }) {
  const anamnesis = useAsync(() => api.get<Anamnesis>(`/patients/${patient.id}/anamnesis`), [patient.id]);
  const institutions = useAsync(() => api.get<Institution[]>(`/patients/${patient.id}/institutions`), [patient.id]);
  // Anamnesis cargadas antes como texto libre: se siguen mostrando (solo lectura).
  const notes = useAsync(() => api.get<Note[]>(`/patients/${patient.id}/notes`), [patient.id]);
  const oldNotes = (notes.data ?? []).filter((n) => n.kind === "anamnesis" && !n.superseded_by_id);
  const [editing, setEditing] = useState(false);
  const [viewing, setViewing] = useState<Version | null>(null); // versión anterior abierta
  const [showHistory, setShowHistory] = useState(false);
  const old = useAction();

  if (anamnesis.loading && !anamnesis.data) return <Loading />;
  if (anamnesis.error || !anamnesis.data) return <ErrorBox message={anamnesis.error ?? "No se pudo cargar la anamnesis."} />;
  const { current, versions } = anamnesis.data;
  const schools = (institutions.data ?? []).filter((i) => i.is_current).map((i) => i.name).join(" · ");
  const shown = viewing ?? current;

  async function openVersion(id: string) {
    if (id === current?.id) { setViewing(null); return; }
    await old.run(async () => {
      setViewing(await api.get<Version>(`/patients/${patient.id}/anamnesis/${id}`));
    });
  }

  const header = (
    <dl className="anam-header">
      <div><dt>Nombre y apellidos</dt><dd>{fullName(patient)}</dd></div>
      <div><dt>Fecha de nacimiento</dt><dd>{fmtDate(patient.birth_date)}</dd></div>
      <div><dt>Edad</dt><dd>{ageText(patient.birth_date)}</dd></div>
      <div><dt>Escuela</dt><dd>{schools || <span className="muted">Sin institución actual (se carga en Instituciones)</span>}</dd></div>
    </dl>
  );

  if (editing) {
    return (
      <AnamnesisForm patientId={patient.id} current={current} header={header}
                     onDone={(saved) => { setEditing(false); setViewing(null); if (saved) anamnesis.reload(); }} />
    );
  }

  return (
    <>
      <Card title="Ficha de anamnesis multidisciplinaria"
            actions={(
              <>
                {shown && (
                  <a className="btn" target="_blank" rel="noopener"
                     href={`#/imprimir/anamnesis/${patient.id}${viewing ? `?version=${viewing.id}` : ""}`}>
                    Imprimir / PDF
                  </a>
                )}
                {!viewing && (
                  <button type="button" className="btn btn-primary" onClick={() => setEditing(true)}>
                    {current ? "Editar anamnesis" : "Completar anamnesis"}
                  </button>
                )}
              </>
            )}>
        {viewing && (
          <p className="alert alert-warn" role="status">
            Estás viendo una versión anterior, del {fmtDateTime(viewing.created_at)} ({viewing.author_name}).{" "}
            <button type="button" className="link-button" onClick={() => setViewing(null)}>Volver a la vigente</button>
          </p>
        )}
        {shown && !viewing && (
          <p className="muted small">
            Última actualización: {fmtDateTime(shown.created_at)} por <strong>{shown.author_name}</strong>.
          </p>
        )}
        {header}
        {!shown && (
          <Empty>
            Todavía no se completó la anamnesis. Cualquier profesional con acceso clínico puede
            completarla; se puede guardar a medias y seguir otro día.
          </Empty>
        )}
        {shown && <AnamnesisView data={shown.data} />}
      </Card>

      {versions.length > 0 && (
        <Card title="Historial de cambios">
          <p className="muted small">
            Cada vez que alguien guarda queda una versión: nunca se borra ni se pisa lo anterior.{" "}
            {versions.length > 1 && (
              <button type="button" className="link-button" onClick={() => setShowHistory(!showHistory)}>
                {showHistory ? "Ocultar" : `Ver las ${versions.length} versiones`}
              </button>
            )}
          </p>
          <ErrorBox message={old.error} />
          {(showHistory || versions.length === 1) && (
            <ol className="anam-versions">
              {versions.map((v, i) => (
                <li key={v.id}>
                  {fmtDateTime(v.created_at)} · {v.author_name}
                  <span className="muted small"> · {v.fields} {v.fields === 1 ? "campo" : "campos"}</span>
                  {i === 0 && <> <Badge tone="info">Vigente</Badge></>}
                  {(viewing?.id ?? current?.id) === v.id
                    ? <span className="muted small"> · (abierta)</span>
                    : <> · <button type="button" className="link-button" disabled={old.busy}
                                   onClick={() => openVersion(v.id)}>Ver</button></>}
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}

      {oldNotes.length > 0 && (
        <Card title="Anamnesis anteriores (texto libre)">
          <p className="muted small">Registradas antes de la ficha estructurada. Se conservan tal cual.</p>
          <ol className="anam-versions">
            {oldNotes.map((n) => (
              <li key={n.id}>
                <div className="small muted">{fmtDate(n.session_date ?? n.created_at)} · {n.author_name}</div>
                <p className="anam-answer">{n.content}</p>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </>
  );
}

/** Lectura: por sección, solo las preguntas respondidas. */
function AnamnesisView({ data }: { data: Data }) {
  const { sections, myArea } = useSections();
  return (
    <div className="anam-view">
      {sections.map((s) => {
        const groups = s.groups.map((g) => ({ g, items: answered(g, data) })).filter((x) => x.items.length > 0);
        return (
          <section key={s.id} className="anam-section">
            <h3>{s.title}</h3>
            {groups.length === 0 && <p className="muted small">Sin completar.</p>}
            {groups.map(({ g, items }, i) => (
              <div key={g.title ?? i} className="anam-group">
                {g.title && <h4>{g.title}{s.areas && myArea && sameArea(g.title, myArea) && <> <Badge tone="info">Tu área</Badge></>}</h4>}
                <dl className="anam-answers">
                  {items.map(([label, value]) => (
                    <div key={label}><dt>{label}</dt><dd className="anam-answer">{value}</dd></div>
                  ))}
                </dl>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}

export function answered(g: Group, data: Data): [string, string][] {
  if (g.siblings) {
    const rows: [string, string][] = [];
    for (let n = 1; n <= siblingCount(data, false); n++) {
      const k = siblingKeys(n);
      if (!data[k.name] && !data[k.age]) continue;
      rows.push([`Hermano/a ${n}`, [data[k.name], data[k.age] && `${data[k.age]}${/^\d+$/.test(data[k.age]) ? " años" : ""}`]
        .filter(Boolean).join(" · ")]);
    }
    return rows;
  }
  return g.fields.filter((f) => data[f.key]).map((f) => [f.label, f.type === "date" ? fmtDate(data[f.key]) : data[f.key]]);
}

/** Formulario completo. Lo escrito queda como borrador si se cambia de pestaña sin guardar. */
function AnamnesisForm({ patientId, current, header, onDone }: {
  patientId: string; current: Version | null; header: ReactNode; onDone: (saved: boolean) => void;
}) {
  const { sections, myArea } = useSections();
  const initial = useMemo(() => JSON.stringify({ base: current?.id ?? null, data: current?.data ?? {} }), [current]);
  const [draft, setDraft, discardDraft, restored] = useDraft(`anamnesis:${patientId}`, initial);
  const parsed = JSON.parse(draft) as { base: string | null; data: Data };
  const data = parsed.data;
  const [siblings, setSiblings] = useState(() => siblingCount(data, true));
  const { busy, error, run } = useAction();

  const set = (key: string, value: string) => {
    const next = { ...data, [key]: value };
    if (!value) delete next[key];
    setDraft(JSON.stringify({ base: parsed.base, data: next }));
  };
  const changed = draft !== initial;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/patients/${patientId}/anamnesis`, { data, base_version_id: parsed.base });
    });
    if (ok) {
      notify("Anamnesis guardada.");
      discardDraft();
      onDone(true);
    }
  }

  async function cancel() {
    if (changed && !(await askConfirm("¿Descartar los cambios que no guardaste en la anamnesis?",
                                      { confirmLabel: "Descartar cambios" }))) return;
    discardDraft();
    onDone(false);
  }

  return (
    <Card title={current ? "Editar anamnesis" : "Completar anamnesis"}>
      <form onSubmit={submit} className="anam-form">
        {restored && changed && (
          <p className="alert alert-info small">Recuperamos lo que estabas escribiendo: todavía no está guardado.</p>
        )}
        <p className="muted small">
          Completá lo que sepas: se puede guardar a medias y seguir otro día. Durante las pruebas, solo datos ficticios.
        </p>
        {header}
        {sections.map((s) => (
          <fieldset key={s.id} className="anam-section">
            <legend>{s.title}</legend>
            {s.groups.map((g, i) => (
              <div key={g.title ?? i} className="anam-group">
                {g.title && (
                  <h4>{g.title}{s.areas && myArea && sameArea(g.title, myArea) && <> <Badge tone="info">Tu área</Badge></>}</h4>
                )}
                {g.siblings ? (
                  <>
                    {Array.from({ length: siblings }, (_, j) => {
                      const k = siblingKeys(j + 1);
                      return (
                        <div key={j} className="grid-form">
                          <Field label={`Hermano/a ${j + 1}: nombre`}>
                            {(id) => <input id={id} maxLength={5000} value={data[k.name] ?? ""}
                                            onChange={(e) => set(k.name, e.target.value)} />}
                          </Field>
                          <Field label="Edad">
                            {(id) => <input id={id} maxLength={5000} value={data[k.age] ?? ""}
                                            onChange={(e) => set(k.age, e.target.value)} />}
                          </Field>
                        </div>
                      );
                    })}
                    {siblings < MAX_SIBLINGS && (
                      <button type="button" className="btn btn-small" onClick={() => setSiblings(siblings + 1)}>
                        Agregar hermano/a
                      </button>
                    )}
                  </>
                ) : (
                  <div className="grid-form">
                    {g.fields.map((f) => <AnamnesisField key={f.key} field={f} value={data[f.key] ?? ""}
                                                         onChange={(v) => set(f.key, v)} />)}
                  </div>
                )}
              </div>
            ))}
          </fieldset>
        ))}
        <ErrorBox message={error} />
        <div className="form-actions anam-actions">
          <button type="button" className="btn" onClick={cancel}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? "Guardando…" : "Guardar anamnesis"}
          </button>
        </div>
      </form>
    </Card>
  );
}

function AnamnesisField({ field, value, onChange }: { field: FieldDef; value: string; onChange: (v: string) => void }) {
  const type = field.type ?? "text";
  const wide = type === "long";
  return (
    <div className={wide ? "span-all" : undefined}>
      <Field label={field.label}>
        {(id) => {
          if (type === "long") {
            return <textarea id={id} rows={2} maxLength={5000} value={value} onChange={(e) => onChange(e.target.value)} />;
          }
          if (type === "date") {
            return <input id={id} type="date" max={todayLocal()} value={value} onChange={(e) => onChange(e.target.value)} />;
          }
          if (type === "yesno" || typeof type === "object") {
            const options = type === "yesno" ? ["Sí", "No"] : type.options;
            return (
              <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
                <option value="">—</option>
                {options.map((o) => <option key={o} value={o}>{o}</option>)}
                {value && !options.includes(value) && <option value={value}>{value}</option>}
              </select>
            );
          }
          return <input id={id} maxLength={5000} value={value} onChange={(e) => onChange(e.target.value)} />;
        }}
      </Field>
    </div>
  );
}
