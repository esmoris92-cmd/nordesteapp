// Pestañas Antecedentes, Diagnóstico, Encuadre y Abordaje del paciente: lo que después junta
// "Generar informe" (pestaña Informes).
//
// * Antecedentes, Diagnóstico y Encuadre: un texto por paciente que cualquier profesional con
//   acceso clínico actualiza.
// * Abordaje: uno por profesional, titulado por su profesión ("Abordaje de Terapia
//   ocupacional"), con sus cuadros "En suma" y "Sugerencias". Cada uno edita solo el suyo.
//
// Cada guardado es una versión nueva (quién y cuándo) y se puede ver cómo estaba antes.
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import { askConfirm } from "../confirm";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useDraft } from "../drafts";
import { useAction, useAsync } from "../hooks";
import { ProfTag } from "../profession";
import { fmtDateTime } from "../labels";
import { useSession } from "../session";
import { notify } from "../toast";

export type SharedSection = "antecedentes" | "diagnostico" | "encuadre";
type Data = Record<string, string>;

export interface SectionVersion {
  id: string;
  section: string;
  owner_id: string | null;
  author_name: string;
  created_at: string;
  data: Data;
}

export interface SectionState {
  current: SectionVersion | null;
  versions: { id: string; author_name: string; created_at: string }[];
}

export interface AbordajeState extends SectionState {
  owner_id: string;
  owner_name: string;
  specialty_name: string | null;
}

export interface ReportSections {
  antecedentes: SectionState;
  diagnostico: SectionState;
  encuadre: SectionState;
  abordajes: AbordajeState[];
}

export const SHARED_TITLES: Record<SharedSection, string> = {
  antecedentes: "Antecedentes",
  diagnostico: "Diagnóstico",
  encuadre: "Encuadre",
};

const SHARED_HINTS: Record<SharedSection, string> = {
  antecedentes: "Antecedentes del caso: desarrollo, historia familiar, historial educativo, tratamientos anteriores.",
  diagnostico: "Diagnóstico y equipos o instituciones que hacen el seguimiento.",
  encuadre: "Cómo es el tratamiento: frecuencia, modalidad, con quién asiste y su participación.",
};

interface FieldDef { key: string; label: string; rows: number }

const SHARED_FIELDS: FieldDef[] = [{ key: "texto", label: "Texto", rows: 12 }];
export const ABORDAJE_FIELDS: FieldDef[] = [
  { key: "abordaje", label: "Abordaje", rows: 14 },
  { key: "en_suma", label: "En suma", rows: 5 },
  { key: "sugerencias", label: "Sugerencias", rows: 5 },
];

/** "Abordaje de Terapia ocupacional" y, si hay más de un profesional de esa profesión, su nombre. */
export function abordajeTitle(a: AbordajeState, all: AbordajeState[]): string {
  if (!a.specialty_name) return `Abordaje de ${a.owner_name}`;
  const same = all.filter((x) => x.specialty_name === a.specialty_name).length > 1;
  return `Abordaje de ${a.specialty_name}${same ? ` — ${a.owner_name}` : ""}`;
}

function useSections(patientId: string) {
  return useAsync(() => api.get<ReportSections>(`/patients/${patientId}/report-sections`), [patientId]);
}

export function SharedSectionPanel({ patientId, section }: { patientId: string; section: SharedSection }) {
  const sections = useSections(patientId);
  if (sections.loading && !sections.data) return <Loading />;
  if (!sections.data) return <ErrorBox message={sections.error ?? "No se pudo cargar."} />;
  return (
    <>
      <p className="muted small section-intro">
        {SHARED_HINTS[section]} Lo puede actualizar cualquier profesional con acceso; se usa al
        «Generar informe».
      </p>
      <SectionCard patientId={patientId} section={section} title={SHARED_TITLES[section]}
                   fields={SHARED_FIELDS} state={sections.data[section]} canEdit
                   onSaved={sections.reload} />
    </>
  );
}

export function AbordajePanel({ patientId }: { patientId: string }) {
  const { user } = useSession();
  const sections = useSections(patientId);
  const list = useMemo(() => {
    const all = sections.data?.abordajes ?? [];
    // El de quien entra va primero; si todavía no escribió el suyo, aparece vacío para escribirlo.
    const mine: AbordajeState = all.find((a) => a.owner_id === user.id) ?? {
      owner_id: user.id, owner_name: user.full_name, specialty_name: user.specialty_name,
      current: null, versions: [],
    };
    return [mine, ...all.filter((a) => a.owner_id !== user.id)];
  }, [sections.data, user]);

  if (sections.loading && !sections.data) return <Loading />;
  if (!sections.data) return <ErrorBox message={sections.error ?? "No se pudo cargar."} />;
  return (
    <>
      <p className="muted small section-intro">
        Cada profesional escribe su abordaje, su «En suma» y sus «Sugerencias». Se ven los de todos
        y cada uno edita solo el suyo. «Generar informe» los incluye a todos.
      </p>
      {list.map((a) => (
        <SectionCard key={a.owner_id} patientId={patientId} section="abordaje"
                     title={abordajeTitle(a, list)} fields={ABORDAJE_FIELDS} state={a}
                     canEdit={a.owner_id === user.id} mine={a.owner_id === user.id}
                     owner={<ProfTag name={a.owner_name} specialty={a.specialty_name} />}
                     onSaved={sections.reload} />
      ))}
    </>
  );
}

function SectionCard({ patientId, section, title, fields, state, canEdit, mine = false, owner, onSaved }: {
  patientId: string; section: string; title: string; fields: FieldDef[]; state: SectionState;
  canEdit: boolean; mine?: boolean; owner?: ReactNode; onSaved: () => void;
}) {
  const draftKey = `seccion:${patientId}:${section}${mine ? ":mio" : ""}`;
  const [editing, setEditing] = useState(false);
  const [viewing, setViewing] = useState<SectionVersion | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const old = useAction();
  const { current, versions } = state;
  const shown = viewing ?? current;

  async function openVersion(id: string) {
    if (id === current?.id) { setViewing(null); return; }
    await old.run(async () => {
      setViewing(await api.get<SectionVersion>(`/patients/${patientId}/report-sections/versions/${id}`));
    });
  }

  if (editing) {
    return (
      <SectionEditor patientId={patientId} section={section} title={title} fields={fields}
                     current={current} draftKey={draftKey}
                     onDone={(saved) => { setEditing(false); setViewing(null); if (saved) onSaved(); }} />
    );
  }

  return (
    <Card title={title}
          actions={canEdit && !viewing && (
            <button type="button" className={current ? "btn" : "btn btn-primary"} onClick={() => setEditing(true)}>
              {current ? "Editar" : mine ? "Escribir mi abordaje" : "Escribir"}
            </button>
          )}>
      {owner && <p className="small section-owner">Lo escribe {owner}</p>}
      {viewing && (
        <p className="alert alert-warn" role="status">
          Versión anterior, del {fmtDateTime(viewing.created_at)} ({viewing.author_name}).{" "}
          <button type="button" className="link-button" onClick={() => setViewing(null)}>Volver a la vigente</button>
        </p>
      )}
      {!shown && <Empty>{mine ? "Todavía no escribiste tu abordaje." : "Todavía no se cargó."}</Empty>}
      {shown && fields.map((f) => (
        fields.length === 1
          ? <div key={f.key} className="note-text">{shown.data[f.key] ?? <span className="muted">—</span>}</div>
          : (
            <div key={f.key} className="section-field">
              <h3 className="section-label">{f.label}</h3>
              <div className="note-text">{shown.data[f.key] ?? <span className="muted">Sin completar.</span>}</div>
            </div>
          )
      ))}
      {current && (
        <p className="muted small">
          Última actualización: {fmtDateTime(current.created_at)} por {current.author_name}.{" "}
          {versions.length > 1 && (
            <button type="button" className="link-button" onClick={() => setShowHistory(!showHistory)}>
              {showHistory ? "Ocultar versiones" : `Ver las ${versions.length} versiones`}
            </button>
          )}
        </p>
      )}
      <ErrorBox message={old.error} />
      {showHistory && (
        <ol className="anam-versions">
          {versions.map((v, i) => (
            <li key={v.id}>
              {fmtDateTime(v.created_at)} · {v.author_name}
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
  );
}

function SectionEditor({ patientId, section, title, fields, current, draftKey, onDone }: {
  patientId: string; section: string; title: string; fields: FieldDef[]; current: SectionVersion | null;
  draftKey: string; onDone: (saved: boolean) => void;
}) {
  const initial = useMemo(() => JSON.stringify({ base: current?.id ?? null, data: current?.data ?? {} }), [current]);
  const [draft, setDraft, discardDraft, restored] = useDraft(draftKey, initial);
  const parsed = JSON.parse(draft) as { base: string | null; data: Data };
  const changed = draft !== initial;
  const { busy, error, run } = useAction();

  const set = (key: string, value: string) => {
    const data = { ...parsed.data, [key]: value };
    if (!value) delete data[key];
    setDraft(JSON.stringify({ base: parsed.base, data }));
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/patients/${patientId}/report-sections/${section}`,
                     { data: parsed.data, base_version_id: parsed.base });
    });
    if (ok) {
      notify(`${title}: guardado.`);
      discardDraft();
      onDone(true);
    }
  }

  async function cancel() {
    if (changed && !(await askConfirm("¿Descartar los cambios que no guardaste?",
                                      { confirmLabel: "Descartar cambios" }))) return;
    discardDraft();
    onDone(false);
  }

  return (
    <Card title={title}>
      <form onSubmit={submit}>
        {restored && changed && (
          <p className="alert alert-info small">Recuperamos lo que estabas escribiendo: todavía no está guardado.</p>
        )}
        {fields.map((f) => (
          <Field key={f.key} label={fields.length === 1 ? title : f.label}
                 hint={f === fields[0] ? "Hasta 20.000 caracteres por cuadro. Durante las pruebas, solo datos ficticios." : undefined}>
            {(id, hint) => (
              <textarea id={id} aria-describedby={hint} rows={f.rows} maxLength={20000}
                        value={parsed.data[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)} />
            )}
          </Field>
        ))}
        <ErrorBox message={error} />
        <div className="form-actions">
          <button type="button" className="btn" onClick={cancel}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? "Guardando…" : "Guardar"}
          </button>
        </div>
      </form>
    </Card>
  );
}
