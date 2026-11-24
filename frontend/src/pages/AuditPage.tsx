// Registro de auditoría (solo Administración): filtros por persona, acción, paciente y fechas,
// y "Cargar más" para ir hacia atrás sin límite.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAsync } from "../hooks";
import { AUDIT_ACTION_LABELS, fmtDateTime, FEATURE_LABELS } from "../labels";
import type { AuditEvent, Patient } from "../types";
import { PatientPicker } from "./PatientPicker";

const PAGE = 100;
const ACTIONS = Object.entries(AUDIT_ACTION_LABELS).sort((a, b) => a[1].localeCompare(b[1], "es"));

export function AuditPage({ patientId }: { patientId: string | null }) {
  const people = useAsync(() => api.get<{ id: string; full_name: string }[]>("/audit/people"), []);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [patient, setPatient] = useState<Patient | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastRequest = useRef(0); // si cambian los filtros mientras carga, vale solo la última respuesta

  // Al venir desde una ficha (#/auditoria?paciente=…): ese paciente ya elegido.
  useEffect(() => {
    if (!patientId) { setPatient(null); return; }
    api.get<Patient>(`/patients/${patientId}`).then(setPatient).catch(() => setPatient(null));
  }, [patientId]);
  const patientFilter = patient?.id ?? (patientId && patient === null ? patientId : "");

  const filters = { actor_id: actor, action, patient_id: patientFilter, date_from: from, date_to: to };
  const key = JSON.stringify(filters);
  const badRange = Boolean(from && to && from > to);

  async function load(beforeId?: number) {
    const request = ++lastRequest.current;
    setLoading(true);
    setError(null);
    try {
      const page = await api.get<AuditEvent[]>("/audit", {
        ...filters, limit: String(PAGE), before_id: beforeId ? String(beforeId) : undefined,
      });
      if (request !== lastRequest.current) return;
      setEvents((prev) => (beforeId ? [...prev, ...page] : page));
      setMore(page.length === PAGE);
    } catch (e) {
      if (request !== lastRequest.current) return;
      setError(e instanceof Error ? e.message : "No se pudo cargar la auditoría.");
    } finally {
      if (request === lastRequest.current) setLoading(false);
    }
  }

  useEffect(() => {
    if (badRange) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, badRange]);

  const anyFilter = Boolean(actor || action || patient || from || to);

  function clear() {
    setActor(""); setAction(""); setPatient(null); setFrom(""); setTo("");
    if (patientId) window.location.hash = "#/auditoria";
  }

  return (
    <>
      <div className="page-title"><h1>Registro de auditoría</h1></div>
      <Card>
        <p className="muted small">
          Muestra quién consultó o modificó información y cuándo. Solo guarda metadatos: nunca el
          contenido de notas o informes. Los registros no se pueden editar ni borrar.
        </p>
        <div className="grid-form audit-filters">
          <Field label="Persona">
            {(id) => (
              <select id={id} value={actor} onChange={(e) => setActor(e.target.value)}>
                <option value="">Todas</option>
                {people.data?.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
              </select>
            )}
          </Field>
          <Field label="Acción">
            {(id) => (
              <select id={id} value={action} onChange={(e) => setAction(e.target.value)}>
                <option value="">Todas</option>
                {ACTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            )}
          </Field>
          <Field label="Desde">
            {(id) => <input id={id} type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />}
          </Field>
          <Field label="Hasta">
            {(id) => <input id={id} type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />}
          </Field>
          <div className="span-all">
            <Field label="Paciente">
              {(id) => (
                <PatientPicker id={id} value={patient} status="" branch="all"
                               onChange={(p) => {
                                 setPatient(p);
                                 if (!p && patientId) window.location.hash = "#/auditoria";
                               }} />
              )}
            </Field>
          </div>
          {anyFilter && (
            <div className="form-actions">
              <button type="button" className="btn" onClick={clear}>Quitar filtros</button>
            </div>
          )}
        </div>
        {badRange && <ErrorBox message='La fecha "Desde" no puede ser posterior a "Hasta".' />}
        <ErrorBox message={error ?? people.error} />
        {!loading && !error && events.length === 0 && (
          <Empty>{anyFilter ? "No hay eventos con esos filtros." : "No hay eventos registrados."}</Empty>
        )}
        {events.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Fecha</th><th scope="col">Persona</th>
                  <th scope="col">Acción</th><th scope="col">Paciente</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}>
                    <td>{fmtDateTime(e.created_at)}</td>
                    <td>{e.actor_name ?? "—"}</td>
                    <td>
                      {AUDIT_ACTION_LABELS[e.action] ?? e.action}
                      {e.details?.past === true && <> <Badge tone="warn">con fecha pasada</Badge></>}
                      {typeof e.details?.feature === "string" && <>: {FEATURE_LABELS[e.details.feature] ?? e.details.feature}</>}
                    </td>
                    <td>
                      {e.patient_id
                        ? <a href={`#/pacientes/${e.patient_id}`}>{e.patient_name ?? "Ver ficha"}</a> : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {loading && <Loading />}
        {!loading && events.length > 0 && (
          <div className="audit-more">
            <span className="muted small">
              {events.length === 1 ? "1 evento" : `${events.length} eventos`}{more ? " (hay más)" : ""}
            </span>
            {more && (
              <button type="button" className="btn" onClick={() => load(events[events.length - 1].id)}>
                Cargar más
              </button>
            )}
          </div>
        )}
      </Card>
    </>
  );
}
