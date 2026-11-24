// Pestaña "Objetivos": plan de tratamiento del paciente (información clínica).
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { confirmDiscard } from "../confirm";
import { hasDraft, useDraft } from "../drafts";
import { notify } from "../toast";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import { fmtDate, fmtDateTime, GOAL_STATUS_LABELS, GOAL_STATUS_TONE as STATUS_TONE, todayLocal } from "../labels";
import type { Goal, GoalStatus } from "../types";

const AREAS = [
  "Lenguaje", "Comunicación", "Habla", "Motricidad fina", "Motricidad gruesa", "Autonomía",
  "Actividades de la vida diaria", "Integración sensorial", "Emocional", "Conducta",
  "Vínculos y socialización", "Aprendizaje", "Atención", "Juego",
];

export function GoalsPanel({ patientId }: { patientId: string }) {
  const goals = useAsync(() => api.get<Goal[]>(`/patients/${patientId}/goals`), [patientId]);
  // Si quedó un objetivo a medio escribir (por cambiar de pestaña), el formulario se reabre.
  const [creating, setCreating] = useState(() => hasDraft(`objetivo:${patientId}`));
  const [showClosed, setShowClosed] = useState(false);

  const list = goals.data ?? [];
  const active = list.filter((g) => g.status === "active");
  const closed = list.filter((g) => g.status !== "active");

  return (
    <>
      <Card
        title="Plan de tratamiento"
        actions={!creating && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>Nuevo objetivo</button>
        )}
      >
        <p className="muted small">
          Cada profesional que atiende al paciente puede proponer objetivos y registrar avances. El texto
          de un objetivo no se edita: si cambia, se discontinúa con su motivo y se crea otro. Todo avance
          queda con su autor y fecha.
        </p>
        {creating && (
          <NewGoalForm patientId={patientId}
                       onClose={(saved) => { setCreating(false); if (saved) goals.reload(); }} />
        )}
        {goals.loading && <Loading />}
        <ErrorBox message={goals.error} />
        {goals.data && list.length === 0 && !creating && <Empty>Todavía no hay objetivos.</Empty>}
        {active.length > 0 && <h3 className="goals-heading">En curso ({active.length})</h3>}
        {active.map((g) => <GoalCard key={g.id} goal={g} onChanged={goals.reload} />)}
        {closed.length > 0 && (
          <label className="checkbox goals-heading">
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
            Mostrar logrados y discontinuados ({closed.length})
          </label>
        )}
        {showClosed && closed.map((g) => <GoalCard key={g.id} goal={g} onChanged={goals.reload} />)}
      </Card>
    </>
  );
}

function NewGoalForm({ patientId, onClose }: { patientId: string; onClose: (saved: boolean) => void }) {
  const [area, setArea] = useState("");
  const [description, setDescription, discardDraft] = useDraft(`objetivo:${patientId}`);
  const [targetDate, setTargetDate] = useState("");
  const { busy, error, run } = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/patients/${patientId}/goals`, {
        area, description, target_date: targetDate || null,
      });
    });
    if (ok) {
      notify("Objetivo creado.");
      discardDraft();
      onClose(true);
    }
  }

  return (
    <form className="grid-form goal-form" onSubmit={submit}>
      <ErrorBox message={error} />
      <Field label="Área" required hint="Elegí una o escribí otra.">
        {(id, hint) => (
          <input id={id} aria-describedby={hint} required minLength={2} maxLength={80} list="goal-areas"
                 value={area} onChange={(e) => setArea(e.target.value)} />
        )}
      </Field>
      <datalist id="goal-areas">{AREAS.map((a) => <option key={a} value={a} />)}</datalist>
      <Field label="Fecha objetivo" hint="Opcional: para cuándo se espera lograrlo.">
        {(id, hint) => (
          <input id={id} type="date" aria-describedby={hint} value={targetDate}
                 onChange={(e) => setTargetDate(e.target.value)} />
        )}
      </Field>
      <div className="span-all">
        <Field label="Objetivo" required hint="Concreto y observable. Durante las pruebas, solo datos ficticios.">
          {(id, hint) => (
            <textarea id={id} aria-describedby={hint} required minLength={3} maxLength={2000} rows={3}
                      value={description} onChange={(e) => setDescription(e.target.value)} />
          )}
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" className="btn" onClick={async () => {
          if (!await confirmDiscard(description)) return;
          discardDraft();
          onClose(false);
        }}>Cancelar</button>
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Guardando…" : "Crear objetivo"}</button>
      </div>
    </form>
  );
}

function ProgressBar({ value, status }: { value: number; status: GoalStatus }) {
  return (
    <div className="goal-progress-row">
      <div className="goal-progress" role="progressbar" aria-valuenow={value} aria-valuemin={0}
           aria-valuemax={100} aria-label={`Avance ${value} %`}>
        <div className={`goal-progress-fill st-${status}`} style={{ width: `${value}%` }} />
      </div>
      <span className="goal-progress-value">{value} %</span>
    </div>
  );
}

function GoalCard({ goal, onChanged }: { goal: Goal; onChanged: () => void }) {
  // Si quedó un avance a medio escribir (por cambiar de pestaña), el formulario se reabre.
  const [mode, setMode] = useState<"none" | "update" | "history">(
    () => (hasDraft(`avance:${goal.id}`) ? "update" : "none"));
  const overdue = goal.status === "active" && goal.target_date !== null && goal.target_date < todayLocal();
  const last = goal.updates[0];

  return (
    <article className={`goal st-${goal.status}`}>
      <header>
        <Badge tone="info">{goal.area}</Badge>
        <Badge tone={STATUS_TONE[goal.status]}>{GOAL_STATUS_LABELS[goal.status]}</Badge>
        {overdue && <Badge tone="warn">Fecha objetivo vencida</Badge>}
      </header>
      <p className="goal-text">{goal.description}</p>
      <ProgressBar value={goal.progress} status={goal.status} />
      <p className="muted small">
        Propuesto por {goal.created_by_name} el {fmtDate(goal.created_at)}
        {goal.target_date && <> · fecha objetivo {fmtDate(goal.target_date)}</>}
        {last && <> · último registro {fmtDate(last.session_date ?? last.created_at)} ({last.author_name})</>}
      </p>
      <div className="row-actions goal-actions">
        {mode !== "update" && (
          <button type="button" className="btn btn-small btn-primary" onClick={() => setMode("update")}>
            {goal.status === "active" ? "Registrar avance" : "Reabrir"}
          </button>
        )}
        {goal.updates.length > 0 && (
          <button type="button" className="btn btn-small"
                  onClick={() => setMode(mode === "history" ? "none" : "history")}>
            {mode === "history" ? "Ocultar historial" : `Ver historial (${goal.updates.length})`}
          </button>
        )}
      </div>
      {mode === "update" && (
        <UpdateForm goal={goal} onClose={(saved) => { setMode(saved ? "history" : "none"); if (saved) onChanged(); }} />
      )}
      {mode === "history" && (
        <ol className="goal-history">
          {goal.updates.map((u) => (
            <li key={u.id}>
              <div className="small">
                <strong>{fmtDate(u.session_date ?? u.created_at)}</strong> · {u.author_name} · {u.progress} %
                {u.new_status && <> · <Badge tone={STATUS_TONE[u.new_status]}>{GOAL_STATUS_LABELS[u.new_status]}</Badge></>}
                <span className="muted"> · registrado {fmtDateTime(u.created_at)}</span>
              </div>
              <p className="goal-note">{u.note}</p>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

function UpdateForm({ goal, onClose }: { goal: Goal; onClose: (saved: boolean) => void }) {
  const closed = goal.status !== "active";
  const [progress, setProgress] = useState(goal.progress);
  const [sessionDate, setSessionDate] = useState(todayLocal);
  const [newStatus, setNewStatus] = useState<string>(closed ? "active" : "");
  const [note, setNote, discardDraft] = useDraft(`avance:${goal.id}`);
  const { busy, error, run } = useAction();
  const achieved = newStatus === "achieved";

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/goals/${goal.id}/updates`, {
        note, progress: achieved ? 100 : progress, session_date: sessionDate || null, new_status: newStatus || null,
      });
    });
    if (ok) {
      notify(newStatus === "achieved" ? "Objetivo marcado como logrado."
        : newStatus === "discontinued" ? "Objetivo discontinuado."
        : closed ? "Objetivo reabierto." : "Avance registrado.");
      discardDraft();
      onClose(true);
    }
  }

  const noteLabel = newStatus === "discontinued" ? "Motivo" : newStatus === "active" && closed ? "Motivo para reabrir" : "Nota";
  const noteHint = newStatus === "discontinued" ? "Por qué se discontinúa (por ejemplo, se reemplaza por otro objetivo)."
    : newStatus === "active" && closed ? "Por qué se vuelve a trabajar este objetivo."
    : achieved ? "Qué se observó que muestra que se logró."
    : "Breve: qué se observó en la sesión.";

  return (
    <form className="grid-form goal-form" onSubmit={submit}>
      <ErrorBox message={error} />
      <Field label="Fecha de la sesión">
        {(id) => <input id={id} type="date" max={todayLocal()} value={sessionDate}
                        onChange={(e) => setSessionDate(e.target.value)} />}
      </Field>
      <Field label={achieved ? "Avance: 100 % (logrado)" : `Avance: ${progress} %`}>
        {(id) => (
          <input id={id} type="range" min={0} max={100} step={5} value={achieved ? 100 : progress}
                 disabled={achieved} onChange={(e) => setProgress(Number(e.target.value))} />
        )}
      </Field>
      {!closed && (
        <Field label="Estado">
          {(id) => (
            <select id={id} value={newStatus} onChange={(e) => {
              setNewStatus(e.target.value);
              if (e.target.value === "achieved") setProgress(100);
            }}>
              <option value="">Sigue en curso</option>
              <option value="achieved">Logrado</option>
              <option value="discontinued">Discontinuado</option>
            </select>
          )}
        </Field>
      )}
      <div className="span-all">
        <Field label={noteLabel} required hint={noteHint}>
          {(id, hint) => (
            <textarea id={id} aria-describedby={hint} required maxLength={5000} rows={3}
                      value={note} onChange={(e) => setNote(e.target.value)} />
          )}
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" className="btn" onClick={async () => {
          if (!await confirmDiscard(note)) return;
          discardDraft();
          onClose(false);
        }}>Cancelar</button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Guardando…" : closed ? "Reabrir objetivo" : "Guardar avance"}
        </button>
      </div>
    </form>
  );
}
