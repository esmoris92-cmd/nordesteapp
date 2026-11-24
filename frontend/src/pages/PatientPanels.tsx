// Pestañas "Turnos" y "Accesos" de la ficha del paciente.
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import { ACCESS_LABELS, APPOINTMENT_STATUS_LABELS, APPOINTMENT_STATUS_TONE, fmtDateTime } from "../labels";
import { navigate } from "../router";
import { notify } from "../toast";
import { canSchedule, isTitular, useSession } from "../session";
import type { Absence, Access, Appointment, Patient, Professional, Reschedule } from "../types";
import { ProfTag, useSpecialtyLookup } from "../profession";
import { responsibleOptions } from "./PatientsPage";

export function PatientAppointments({ patientId, active }: { patientId: string; active: boolean }) {
  const { user, clinic } = useSession();
  // Los turnos los dan Recepción y Administración (o el titular de un espacio independiente).
  const allowed = canSchedule(user, clinic);
  const canBook = active && allowed;
  const from = new Date(Date.now() - 14 * 86400000).toISOString();
  const to = new Date(Date.now() + 45 * 86400000).toISOString();
  const appts = useAsync(
    () => api.get<Appointment[]>("/appointments", { from, to, patient_id: patientId }),
    [patientId],
  );
  const specialty = useSpecialtyLookup();
  return (
    <>
      <Card title="Turnos (últimas 2 semanas y próximas 6 semanas)" actions={canBook && (
        <button type="button" className="btn btn-primary" onClick={() => navigate(`/agenda?paciente=${patientId}`)}>
          Dar turno
        </button>
      )}>
        {appts.loading && <Loading />}
        <ErrorBox message={appts.error} />
        {appts.data && appts.data.length === 0 && <Empty>No hay turnos en este período.</Empty>}
        {appts.data && appts.data.length > 0 && (
          <ul className="list">
            {appts.data.map((a) => (
              <li key={a.id}>
                <strong>{fmtDateTime(a.starts_at)}</strong> · <ProfTag name={a.professional_name} specialty={specialty.byId(a.professional_id)} />
                {a.branch_name && <span className="muted"> · {a.branch_name}</span>}{" "}
                <Badge tone={APPOINTMENT_STATUS_TONE[a.status]}>
                  {APPOINTMENT_STATUS_LABELS[a.status]}
                </Badge>
                {a.cancel_reason && <span className="muted"> — Motivo: {a.cancel_reason}</span>}
                {a.no_show_reason && <span className="muted"> — Motivo: {a.no_show_reason}</span>}
                {a.status === "rescheduled" && (
                  <span className="muted">
                    {a.rescheduled_to_starts_at && <> → pasó al {fmtDateTime(a.rescheduled_to_starts_at)}</>}
                    {a.reschedule_reason && <> — Motivo: {a.reschedule_reason}</>}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">
          {!allowed ? "Los turnos los dan, reprograman y cancelan Recepción y Administración."
            : canBook ? "\"Dar turno\" abre la Agenda con este paciente ya elegido. Para cancelar o reprogramar, usá también la Agenda."
            : "Solo se dan turnos a pacientes activos. Para cancelar o reprogramar, usá la sección Agenda."}
        </p>
      </Card>
      <AbsenceHistory patientId={patientId} />
      <RescheduleHistory patientId={patientId} />
    </>
  );
}

/** Todas las ausencias del paciente (sin límite de fechas), con su motivo. */
function AbsenceHistory({ patientId }: { patientId: string }) {
  const history = useAsync(() => api.get<Absence[]>(`/patients/${patientId}/absences`), [patientId]);
  const specialty = useSpecialtyLookup();
  const total = history.data?.length ?? 0;
  return (
    <Card title={total > 0 ? `Ausencias (${total})` : "Ausencias"}>
      <p className="muted small card-sub">Todos los turnos marcados como ausente, del más reciente al más viejo.</p>
      {history.loading && <Loading />}
      <ErrorBox message={history.error} />
      {history.data && total === 0 && <Empty>No tiene ausencias.</Empty>}
      {history.data && total > 0 && (
        <ul className="list">
          {history.data.map((h) => (
            <li key={h.id}>
              <strong>{fmtDateTime(h.starts_at)}</strong> · <ProfTag name={h.professional_name} specialty={specialty.byName(h.professional_name)} />
              {h.branch_name && <span className="muted"> · {h.branch_name}</span>}
              <div>Motivo: {h.reason ?? <span className="muted">no se escribió</span>}</div>
              {(h.marked_by || h.marked_at) && (
                <div className="muted small">
                  Lo marcó {h.marked_by ?? "—"}{h.marked_at && <> el {fmtDateTime(h.marked_at)}</>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Todas las reprogramaciones del paciente (sin límite de fechas), con su motivo. */
function RescheduleHistory({ patientId }: { patientId: string }) {
  const history = useAsync(() => api.get<Reschedule[]>(`/patients/${patientId}/reschedules`), [patientId]);
  const specialty = useSpecialtyLookup();
  return (
    <Card title="Reprogramaciones">
      <p className="muted small card-sub">Todas las veces que se cambió la fecha de un turno, de la más reciente a la más vieja.</p>
      {history.loading && <Loading />}
      <ErrorBox message={history.error} />
      {history.data && history.data.length === 0 && <Empty>No se reprogramó ningún turno.</Empty>}
      {history.data && history.data.length > 0 && (
        <ul className="list">
          {history.data.map((h) => (
            <li key={h.id}>
              <strong>{fmtDateTime(h.from_starts_at)}</strong>
              {h.to_starts_at && <> → <strong>{fmtDateTime(h.to_starts_at)}</strong></>}
              {" "}· <ProfTag name={h.professional_name} specialty={specialty.byName(h.professional_name)} />
              {h.to_professional_name && <> → <ProfTag name={h.to_professional_name} specialty={specialty.byName(h.to_professional_name)} /></>}
              {/* Cómo terminó el turno nuevo (si se volvió a reprogramar, se ve en la línea de arriba). */}
              {h.to_status && h.to_status !== "scheduled" && h.to_status !== "rescheduled" && (
                <>{" "}<Badge tone={APPOINTMENT_STATUS_TONE[h.to_status]}>{APPOINTMENT_STATUS_LABELS[h.to_status]}</Badge></>
              )}
              <div>Motivo: {h.reason ?? <span className="muted">no se registró (reprogramado antes de pedir el motivo)</span>}</div>
              {(h.rescheduled_by || h.rescheduled_at) && (
                <div className="muted small">
                  Lo reprogramó {h.rescheduled_by ?? "—"}{h.rescheduled_at && <> el {fmtDateTime(h.rescheduled_at)}</>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function AccessPanel({ patientId, patient, canManage, onChanged }: {
  patientId: string; patient: Pick<Patient, "affiliation" | "branch_id" | "branch_name">;
  canManage: boolean; onChanged: () => void;
}) {
  const { user, clinic } = useSession();
  const history = useAsync(() => api.get<Access[]>(`/patients/${patientId}/access`), [patientId]);
  const professionals = useAsync(() => api.get<Professional[]>("/professionals"), []);
  const [grant, setGrant] = useState({ professional_id: "", level: "collaborator", reason: "" });
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeReason, setRevokeReason] = useState("");
  const action = useAction();

  const activeIds = new Set((history.data ?? []).filter((a) => !a.revoked_at).map((a) => a.user_id));
  // AYEX y Tutelas se atienden solo en su sucursal: se ofrecen quienes atienden allí.
  const eligible = responsibleOptions(professionals.data ?? [], patient.affiliation, patient.branch_id);
  const candidates = eligible.filter((p) => !activeIds.has(p.id));

  async function submitGrant(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post(`/patients/${patientId}/access`, {
        professional_id: grant.professional_id, level: grant.level, reason: grant.reason || null,
      });
    });
    if (ok) {
      const name = candidates.find((p) => p.id === grant.professional_id)?.full_name ?? "";
      notify(`Acceso concedido a ${name}.`);
      setGrant({ professional_id: "", level: "collaborator", reason: "" });
      history.reload();
      onChanged();
    }
  }

  async function submitRevoke(event: FormEvent) {
    event.preventDefault();
    if (!revoking) return;
    const ok = await action.run(async () => {
      await api.post(`/patients/${patientId}/access/${revoking}/revoke`, { reason: revokeReason });
    });
    if (ok) {
      notify("Acceso revocado.");
      setRevoking(null);
      setRevokeReason("");
      history.reload();
      onChanged();
    }
  }

  return (
    <>
      <Card title="Profesionales con acceso">
        <p className="muted small">
          Cada acceso queda registrado con quién lo concedió y quién lo retiró. Los accesos no se
          borran: se revocan.
        </p>
        <ErrorBox message={action.error} />
        {history.loading && <Loading />}
        <ErrorBox message={history.error} />
        {history.data && history.data.length === 0 && <Empty>Nadie tiene acceso todavía.</Empty>}
        {history.data && history.data.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Profesional</th><th scope="col">Nivel</th>
                  <th scope="col">Concedido</th><th scope="col">Estado</th><th scope="col"><span className="sr-only">Acciones</span></th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((a) => {
                  const canRevoke = canManage && !a.revoked_at &&
                    (user.role === "admin" || a.level === "collaborator");
                  return (
                    <tr key={a.id} className={a.revoked_at ? "row-muted" : undefined}>
                      <td>
                        <ProfTag name={a.user_name}
                                 specialty={(professionals.data ?? []).find((p) => p.id === a.user_id)?.specialty_name} />
                      </td>
                      <td>{ACCESS_LABELS[a.level]}</td>
                      <td>
                        {fmtDateTime(a.granted_at)} por {a.granted_by_name}
                        {a.reason && <div className="muted small">Motivo: {a.reason}</div>}
                      </td>
                      <td>
                        {a.revoked_at ? (
                          <>
                            Revocado {fmtDateTime(a.revoked_at)} por {a.revoked_by_name}
                            {a.revoke_reason && <div className="muted small">Motivo: {a.revoke_reason}</div>}
                          </>
                        ) : (
                          <>
                            <Badge tone="ok">Vigente</Badge>
                            {a.future_appointments > 0 && (
                              <div className="muted small">
                                {a.future_appointments === 1 ? "1 turno futuro" : `${a.future_appointments} turnos futuros`}
                              </div>
                            )}
                          </>
                        )}
                      </td>
                      <td>
                        {canRevoke && revoking !== a.id && (
                          <button type="button" className="btn btn-small btn-danger"
                                  onClick={() => { setRevoking(a.id); setRevokeReason(""); }}>
                            Revocar
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {revoking && (
          <form className="inline-form" onSubmit={submitRevoke}>
            {(() => {
              const n = history.data?.find((a) => a.id === revoking)?.future_appointments ?? 0;
              return n > 0 ? (
                <p className="alert alert-warn">
                  Este profesional tiene {n === 1 ? "1 turno futuro" : `${n} turnos futuros`} con el
                  paciente. Al revocar el acceso se cancelarán con este mismo motivo.
                </p>
              ) : null;
            })()}
            <Field label="Motivo de la revocación" required>
              {(id) => (
                <input id={id} required minLength={3} maxLength={300} value={revokeReason}
                       onChange={(e) => setRevokeReason(e.target.value)} />
              )}
            </Field>
            <button type="button" className="btn" onClick={() => setRevoking(null)}>Cancelar</button>
            <button type="submit" className="btn btn-danger" disabled={action.busy}>Confirmar revocación</button>
          </form>
        )}
      </Card>

      {user.role === "admin" && history.data && (
        <ResponsibleCard
          patientId={patientId}
          current={history.data.find((a) => !a.revoked_at && a.level === "responsible") ?? null}
          professionals={eligible}
          onChanged={() => { history.reload(); onChanged(); }}
        />
      )}

      {canManage && (
        <Card title="Compartir acceso">
          <p className="muted small">
            Autoriza expresamente a otro profesional de la clínica a ver y escribir en la historia
            clínica de este paciente. Podés revocarlo en cualquier momento.
            {patient.affiliation !== "private" && ` Se muestran quienes atienden en ${patient.branch_name ?? "su sucursal"}, porque este paciente se atiende solo allí.`}
          </p>
          <form className="grid-form" onSubmit={submitGrant}>
            <Field label="Profesional" required>
              {(id) => (
                <select id={id} required value={grant.professional_id}
                        onChange={(e) => setGrant({ ...grant, professional_id: e.target.value })}>
                  <option value="">Elegir…</option>
                  {candidates.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
                </select>
              )}
            </Field>
            <Field label="Motivo">
              {(id) => (
                <input id={id} maxLength={300} value={grant.reason}
                       onChange={(e) => setGrant({ ...grant, reason: e.target.value })} />
              )}
            </Field>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={action.busy}>Conceder acceso</button>
            </div>
          </form>
        </Card>
      )}
      {(user.role === "admin" || isTitular(user, clinic)) && (
        <p><a href={`#/auditoria?paciente=${patientId}`}>Ver registro de auditoría de este paciente →</a></p>
      )}
    </>
  );
}

/** Cambiar el profesional responsable en un solo paso (solo administración). */
function ResponsibleCard({ patientId, current, professionals, onChanged }: {
  patientId: string; current: Access | null; professionals: Professional[]; onChanged: () => void;
}) {
  const [professionalId, setProfessionalId] = useState("");
  const [reason, setReason] = useState("");
  const [formKey, setFormKey] = useState(0); // al cambiar, el formulario se vuelve a crear limpio
  const [moveAppointments, setMoveAppointments] = useState(true);
  const { busy, error, run } = useAction();
  const pending = current?.future_appointments ?? 0;
  const options = professionals.filter((p) => p.id !== current?.user_id);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/patients/${patientId}/responsible`, {
        professional_id: professionalId, reason, move_appointments: moveAppointments,
      });
    });
    if (ok) {
      const name = options.find((p) => p.id === professionalId)?.full_name ?? "";
      notify(`Ahora ${name} es el profesional responsable.`);
      setProfessionalId("");
      setReason("");
      setFormKey((k) => k + 1);
      onChanged();
    }
  }

  return (
    <Card title="Profesional responsable">
      <p>
        Responsable actual:{" "}
        {current
          ? <ProfTag name={current.user_name} specialty={professionals.find((p) => p.id === current.user_id)?.specialty_name} />
          : <strong>Sin asignar</strong>}
      </p>
      <p className="muted small">
        Al cambiarlo, el acceso del responsable anterior se revoca con el motivo que indiques y queda
        en el historial. Si el nuevo ya era colaborador, pasa a ser responsable.
      </p>
      <form key={formKey} className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Nuevo responsable" required>
          {(id) => (
            <select id={id} required value={professionalId} onChange={(e) => setProfessionalId(e.target.value)}>
              <option value="">Elegir…</option>
              {options.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name}{p.specialty_name ? ` (${p.specialty_name})` : ""}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Motivo" required>
          {(id) => (
            <input id={id} required minLength={3} maxLength={300} value={reason}
                   onChange={(e) => setReason(e.target.value)} />
          )}
        </Field>
        {pending > 0 && (
          <fieldset className="span-all choice">
            <legend>
              {current?.user_name} tiene {pending === 1 ? "1 turno futuro" : `${pending} turnos futuros`} con
              este paciente:
            </legend>
            <label className="checkbox">
              <input type="radio" name="move" checked={moveAppointments} onChange={() => setMoveAppointments(true)} />
              Pasarlos al nuevo responsable (mismo día y hora)
            </label>
            <label className="checkbox">
              <input type="radio" name="move" checked={!moveAppointments} onChange={() => setMoveAppointments(false)} />
              Cancelarlos con este motivo
            </label>
          </fieldset>
        )}
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Guardando…" : current ? "Cambiar responsable" : "Asignar responsable"}
          </button>
        </div>
      </form>
    </Card>
  );
}
