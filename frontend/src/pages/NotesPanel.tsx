import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import { hasDraft, useDraft } from "../drafts";
import { fmtDate, fmtDateTime, NOTE_KIND_LABELS, todayLocal } from "../labels";
import { useSession } from "../session";
import { notify } from "../toast";
import type { Note, NoteKind } from "../types";

interface Props {
  patientId: string;
  /** Tipos de registro que muestra y permite crear esta pestaña. */
  kinds: NoteKind[];
  title: string;
  emptyText: string;
  /** Reportes de una institución educativa: muestra y crea solo los de esa institución. */
  institutionId?: string;
  /** Fecha propuesta para el registro nuevo (por ejemplo, la del turno desde el Inicio). */
  defaultDate?: string;
}

export function NotesPanel({ patientId, kinds, title, emptyText, institutionId, defaultDate }: Props) {
  const { user } = useSession();
  const notes = useAsync(() => api.get<Note[]>(`/patients/${patientId}/notes`), [patientId]);
  const [showHistory, setShowHistory] = useState(false);
  const [correcting, setCorrecting] = useState<Note | null>(null);
  // Filtro por tipo (solo en pestañas con varios tipos, como Historia clínica).
  const [onlyKind, setOnlyKind] = useState<NoteKind | "">("");

  const all = (notes.data ?? []).filter((n) => kinds.includes(n.kind)
    && (!institutionId || n.institution_id === institutionId));
  const current = all.filter((n) => !n.superseded_by_id);
  const visible = (showHistory ? all : current).filter((n) => !onlyKind || n.kind === onlyKind);
  const correctedCount = all.length - current.length;
  // Si quedó una corrección a medio escribir (por cambiar de pestaña), se vuelve a abrir.
  useEffect(() => {
    if (correcting || !notes.data) return;
    const pending = all.find((n) => !n.superseded_by_id && hasDraft(`correccion:${n.id}`));
    if (pending) setCorrecting(pending);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes.data]);

  return (
    <>
      <NewNoteForm key={kinds.join()} patientId={patientId} kinds={kinds} institutionId={institutionId}
                   defaultDate={defaultDate} onSaved={notes.reload} />
      <Card
        title={title}
        actions={correctedCount > 0 && (
          <label className="checkbox">
            <input type="checkbox" checked={showHistory} onChange={(e) => setShowHistory(e.target.checked)} />
            Mostrar versiones corregidas ({correctedCount})
          </label>
        )}
      >
        <p className="muted small">
          {institutionId ? "Los reportes" : "Las notas"} no se pueden borrar ni editar. Para corregir
          {institutionId ? " uno" : " una"}, se crea una nueva versión con el motivo, y la anterior queda guardada.
        </p>
        {kinds.length > 1 && current.length > 0 && (
          <div className="kind-filter" role="group" aria-label="Mostrar por tipo">
            <button type="button" className="btn btn-small" aria-pressed={onlyKind === ""}
                    onClick={() => setOnlyKind("")}>Todos ({current.length})</button>
            {kinds.map((k) => (
              <button key={k} type="button" className="btn btn-small" aria-pressed={onlyKind === k}
                      onClick={() => setOnlyKind(k)}>
                {NOTE_KIND_LABELS[k]} ({current.filter((n) => n.kind === k).length})
              </button>
            ))}
          </div>
        )}
        {notes.loading && <Loading />}
        <ErrorBox message={notes.error} />
        {notes.data && visible.length === 0 && (
          <Empty>{onlyKind ? `No hay registros de tipo "${NOTE_KIND_LABELS[onlyKind]}".` : emptyText}</Empty>
        )}
        <ol className="timeline">
          {visible.map((n) => (
            <li key={n.id} className={n.superseded_by_id ? "note superseded" : "note"}>
              <header>
                <Badge tone="info">{NOTE_KIND_LABELS[n.kind]}</Badge>
                {n.session_date && <span>{n.kind === "session" ? "Sesión del " : ""}{fmtDate(n.session_date)}</span>}
                <span className="muted small">
                  {n.author_name} · registrada {fmtDateTime(n.created_at)}
                </span>
                {n.superseded_by_id && <Badge tone="warn">Versión reemplazada</Badge>}
                {n.supersedes_id && <Badge tone="neutral">Corrección</Badge>}
              </header>
              {n.correction_reason && (
                <p className="muted small">Motivo de la corrección: {n.correction_reason}</p>
              )}
              <p className="note-text">{n.content}</p>
              {n.author_id === user.id && !n.superseded_by_id && correcting?.id !== n.id && (
                <button type="button" className="btn btn-small" onClick={() => setCorrecting(n)}>
                  Corregir
                </button>
              )}
              {correcting?.id === n.id && (
                <CorrectionForm note={n} onDone={(saved) => { setCorrecting(null); if (saved) notes.reload(); }} />
              )}
            </li>
          ))}
        </ol>
      </Card>
    </>
  );
}

function NewNoteForm({ patientId, kinds, institutionId, defaultDate, onSaved }: {
  patientId: string; kinds: NoteKind[]; institutionId?: string; defaultDate?: string; onSaved: () => void;
}) {
  const [kind, setKind] = useState<string>(kinds[0]);
  const [sessionDate, setSessionDate] = useState(() => defaultDate ?? todayLocal());
  // Borrador: si se cambia de pestaña sin guardar, el texto vuelve al regresar.
  const [content, setContent, discardDraft, restored] = useDraft(
    `nota:${patientId}:${institutionId ?? kinds.join(",")}`);
  const [formKey, setFormKey] = useState(0); // al cambiar, el formulario se vuelve a crear limpio
  const { busy, error, run } = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/patients/${patientId}/notes`, {
        kind, session_date: sessionDate || null, content,
        ...(institutionId ? { institution_id: institutionId } : {}),
      });
    });
    if (ok) {
      notify(institutionId ? "Reporte guardado." : "Registro guardado.");
      discardDraft();
      setFormKey((k) => k + 1);
      onSaved();
    }
  }

  return (
    <Card title={institutionId ? "Nuevo reporte" : kinds.length === 1 ? `Nuevo registro: ${NOTE_KIND_LABELS[kinds[0]]}` : "Nueva nota"}>
      <form key={formKey} className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        {kinds.length > 1 && (
          <Field label="Tipo" required>
            {(id) => (
              <select id={id} value={kind} onChange={(e) => setKind(e.target.value)}>
                {kinds.map((k) => <option key={k} value={k}>{NOTE_KIND_LABELS[k]}</option>)}
              </select>
            )}
          </Field>
        )}
        <Field label={kinds.length > 1 ? "Fecha de la sesión" : "Fecha"}>
          {(id) => <input id={id} type="date" max={todayLocal()} value={sessionDate}
                          onChange={(e) => setSessionDate(e.target.value)} />}
        </Field>
        <div className="span-all">
          {restored && content && (
            <p className="alert alert-info small">Recuperamos lo que estabas escribiendo: todavía no está guardado.</p>
          )}
          <Field label="Contenido" required hint="Máximo 20.000 caracteres. Durante las pruebas, solo datos ficticios.">
            {(id, hint) => (
              <textarea id={id} aria-describedby={hint} required rows={5} maxLength={20000}
                        value={content} onChange={(e) => setContent(e.target.value)} />
            )}
          </Field>
        </div>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy || !content.trim()}>
            {busy ? "Guardando…" : institutionId ? "Guardar reporte" : "Guardar registro"}
          </button>
        </div>
      </form>
    </Card>
  );
}

function CorrectionForm({ note, onDone }: { note: Note; onDone: (saved: boolean) => void }) {
  const [content, setContent, discardDraft] = useDraft(`correccion:${note.id}`, note.content);
  const [sessionDate, setSessionDate] = useState(note.session_date ?? "");
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  const dateChanged = sessionDate !== (note.session_date ?? "");
  const unchanged = content.trim() === note.content.trim() && !dateChanged;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/notes/${note.id}/corrections`, {
        content, reason, ...(dateChanged ? { session_date: sessionDate || null } : {}),
      });
    });
    if (ok) {
      notify("Corrección guardada. La versión anterior queda en el historial.");
      discardDraft();
      onDone(true);
    }
  }

  return (
    <form className="correction" onSubmit={submit}>
      <ErrorBox message={error} />
      <Field label="Texto corregido" required>
        {(id) => (
          <textarea id={id} required rows={4} maxLength={20000} value={content} autoFocus
                    onChange={(e) => setContent(e.target.value)} />
        )}
      </Field>
      <Field label="Fecha" hint="Cambiala solo si la fecha estaba mal.">
        {(id, hint) => (
          <input id={id} type="date" aria-describedby={hint} max={todayLocal()} value={sessionDate}
                 onChange={(e) => setSessionDate(e.target.value)} />
        )}
      </Field>
      <Field label="Motivo de la corrección" required>
        {(id) => (
          <input id={id} required minLength={3} maxLength={300} value={reason}
                 onChange={(e) => setReason(e.target.value)} />
        )}
      </Field>
      {unchanged && <p className="muted small">Cambiá el texto o la fecha para poder guardar la corrección.</p>}
      <div className="form-actions">
        <button type="button" className="btn" onClick={() => { discardDraft(); onDone(false); }}>Cancelar</button>
        <button type="submit" className="btn btn-primary" disabled={busy || unchanged}>
          {busy ? "Guardando…" : "Guardar corrección"}
        </button>
      </div>
    </form>
  );
}
