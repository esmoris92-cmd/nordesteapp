import { useState, type ReactNode } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Loading } from "../components";
import { useAsync } from "../hooks";
import { APPOINTMENT_STATUS_LABELS, APPOINTMENT_STATUS_TONE, fmtDate, fmtTime, ROLE_LABELS, todayLocal } from "../labels";
import { ProfTag, useSpecialtyLookup } from "../profession";
import { useSession } from "../session";
import type { Appointment } from "../types";
import { BranchScopeSelect } from "./BranchScope";

interface DashboardData {
  scope: "own" | "branch" | "clinic";
  branch_name: string | null;
  today: string;
  month: { completed: number; scheduled: number; no_show: number; cancelled: number; attendance_rate: number | null };
  active_patients: number;
  ayex_due: { patient_id: string; name: string; expires_on: string; expired: boolean; level: "red" | "yellow" }[];
  ayex_due_total: number;
  ayex_missing: number;
  next_appointment: Appointment | null;
  next_day: string | null;
  next_day_others: Appointment[];
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Buenos días";
  if (h < 20) return "Buenas tardes";
  return "Buenas noches";
}

/** "hoy", "mañana" o "del lunes 19" para titular los turnos del día de la próxima sesión. */
function dayLabel(iso: string, todayIso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const [ty, tm, td] = todayIso.split("-").map(Number);
  const diff = Math.round((new Date(y, m - 1, d).getTime() - new Date(ty, tm - 1, td).getTime()) / 86400000);
  if (diff === 0) return "de hoy";
  if (diff === 1) return "de mañana";
  return "del " + new Date(y, m - 1, d).toLocaleDateString("es-UY", { weekday: "long", day: "numeric" });
}

function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const text = new Date(y, m - 1, d).toLocaleDateString("es-UY", { weekday: "long", day: "numeric", month: "long" });
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function HomePage() {
  const { user, clinic } = useSession();
  const [branch, setBranch] = useState("");
  const data = useAsync(() => api.get<DashboardData>("/dashboard", branch ? { branch } : undefined), [branch]);
  const own = user.role === "professional";
  const specialty = useSpecialtyLookup();
  // Dónde: "en Central", "en toda la clínica".
  const where = data.data?.scope === "branch" ? `en ${data.data.branch_name}` : "en toda la clínica";
  // Mostrar la sucursal de cada turno cuando se mezclan varias.
  const showBranch = data.data?.scope !== "branch";

  return (
    <div className="home">
      <p className="eyebrow">
        <span className="dot" aria-hidden="true" />{" "}
        {own ? "Mi panel (todas mis sucursales)"
          : data.data?.scope === "branch" ? `Panel de la sucursal ${data.data.branch_name}` : "Panel de toda la clínica"}
        {" "}· {clinic.name}
      </p>
      <h1 className="home-title">{greeting()}, {user.full_name}</h1>
      <p className="muted">
        {data.data ? longDate(data.data.today) : ""} — resumen del mes y lo que viene
        {!own && <> · {ROLE_LABELS[user.role]}</>}
      </p>

      {user.role === "admin" && (
        <div className="toolbar home-scope">
          <BranchScopeSelect value={branch} onChange={setBranch} />
        </div>
      )}
      {data.loading && !data.data && <Loading />}
      <ErrorBox message={data.error} />

      {data.data && (
        <>
          <div className="stats">
            <Stat icon={<IconCheck />} tone="blue" label={own ? "Sesiones del mes" : "Sesiones realizadas del mes"}
                  value={String(data.data.month.completed)} hint="turnos marcados como realizados" />
            <Stat icon={<IconPerson />} tone="green" label="Pacientes activos"
                  value={String(data.data.active_patients)}
                  hint={own ? "que estás atendiendo" : where} />
            <Stat icon={<IconChart />} tone="purple" label="Asistencia del mes"
                  value={data.data.month.attendance_rate === null ? "—" : `${data.data.month.attendance_rate}%`}
                  hint={data.data.month.attendance_rate === null
                    ? "todavía no hay turnos marcados"
                    : "de los turnos ya marcados, cuántos vinieron"} />
            <Stat icon={<IconCard />} tone="pink" label="Vencimientos de AYEX"
                  value={String(data.data.ayex_due_total)}
                  hint={`vencidos o que vencen en los próximos 3 meses${own ? " (tus pacientes)" : ` ${where}`}`} />
          </div>

          {own && <TodaySessions />}

          <div className="home-grid">
            <Card title={own ? "Mi mes" : data.data.scope === "branch" ? `El mes en ${data.data.branch_name}` : "El mes en la clínica"}>
              <p className="muted small card-sub">Turnos de este mes según su estado</p>
              <MonthDonut month={data.data.month} />
            </Card>
            <Card title="Lo que viene">
              <p className="muted small card-sub">{own ? "Tu próxima sesión y los demás turnos de ese día" : "Próximo turno y los demás turnos de ese día"}</p>
              <h3 className="section-label">Próxima sesión</h3>
              {data.data.next_appointment
                ? <NextSession appt={data.data.next_appointment} showProfessional={!own} showBranch={showBranch} />
                : <Empty>No hay sesiones programadas.</Empty>}
              {data.data.next_day && (
                <>
                  <h3 className="section-label">Más turnos {dayLabel(data.data.next_day, data.data.today)}</h3>
                  {data.data.next_day_others.length === 0
                    ? <p className="muted">No hay más turnos ese día.</p>
                    : (
                  <ul className="list">
                    {data.data.next_day_others.map((a) => (
                      <li key={a.id}>
                        <strong>{fmtTime(a.starts_at)}</strong>{" "}
                        <a href={`#/pacientes/${a.patient_id}`}>{a.patient_name}</a>
                        {!own && <> · <ProfTag name={a.professional_name} specialty={specialty.byId(a.professional_id)} /></>}
                        {showBranch && a.branch_name && <span className="muted small"> · {a.branch_name}</span>}
                      </li>
                    ))}
                  </ul>
                    )}
                </>
              )}
              <AyexList data={data.data} branch={branch} />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

/** "15/10" a partir de "2026-10-15". */
function dayMonth(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

/** Enlace al listado de Pacientes con los mismos pacientes que cuenta el aviso. */
function ayexLink(kind: "due" | "missing", branch: string): string {
  const params = new URLSearchParams({ estado: "active", afiliacion: "ayex", vencimiento: kind });
  if (branch) params.set("sucursal", branch);
  return `#/pacientes?${params.toString()}`;
}

/** Días entre dos fechas "AAAA-MM-DD" (to - from). */
function daysBetween(from: string, to: string): number {
  const [y1, m1, d1] = from.split("-").map(Number);
  const [y2, m2, d2] = to.split("-").map(Number);
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000);
}

/** Vencimientos de AYEX de los próximos 3 meses: rojo si faltan 2 meses o menos (o ya venció),
 *  amarillo si faltan entre 2 y 3 meses. Vienen ordenados del más cercano al más lejano. */
function AyexList({ data, branch }: { data: DashboardData; branch: string }) {
  const { ayex_due: due, ayex_due_total: total, ayex_missing: missing } = data;
  if (due.length === 0 && missing === 0) return null;
  return (
    <>
      <h3 className="section-label">Vencimientos de AYEX</h3>
      {due.length === 0
        ? <p className="muted">Ningún AYEX vence en los próximos 3 meses.</p>
        : (
          <ul className="list ayex-list">
            {due.map((a) => {
              const link = <a href={`#/pacientes/${a.patient_id}`}>{a.name}</a>;
              const badge = a.level === "red" ? "badge badge-danger" : "badge badge-warn";
              const days = daysBetween(data.today, a.expires_on);
              return (
                <li key={a.patient_id} className={`ayex-${a.level}`}>
                  {a.expired
                    ? <><span className={badge}>Vencido</span> Venció el AYEX de {link} el {fmtDate(a.expires_on)}</>
                    : days === 0
                      ? <><span className={badge}>Hoy</span> Hoy vence el AYEX de {link}</>
                      : <>
                          <span className={badge}>{dayMonth(a.expires_on)}</span> Vence el AYEX de {link}{" "}
                          <span className="muted small">({days === 1 ? "mañana" : `en ${days} días`})</span>
                        </>}
                </li>
              );
            })}
          </ul>
        )}
      {total > due.length && (
        <p className="muted small">
          Se muestran {due.length} de {total}. <a href={ayexLink("due", branch)}>Ver los {total} en Pacientes</a>
        </p>
      )}
      {missing > 0 && (
        <p className="muted small">
          <a href={ayexLink("missing", branch)}>
            {missing === 1 ? "1 paciente con AYEX no tiene" : `${missing} pacientes con AYEX no tienen`} cargada la
            fecha de vencimiento
          </a>: se completa al editar su ficha.
        </p>
      )}
    </>
  );
}

function Stat({ icon, tone, label, value, hint }: {
  icon: ReactNode; tone: string; label: string; value: string; hint: string;
}) {
  return (
    <section className="stat card">
      <div className={`stat-icon tone-${tone}`} aria-hidden="true">{icon}</div>
      <div>
        <h2 className="stat-label">{label}</h2>
        <p className="stat-value">{value}</p>
        <p className="stat-hint">{hint}</p>
      </div>
    </section>
  );
}

function NextSession({ appt, showProfessional, showBranch }: {
  appt: Appointment; showProfessional: boolean; showBranch: boolean;
}) {
  const start = new Date(appt.starts_at);
  const isToday = start.toDateString() === new Date().toDateString();
  const specialty = useSpecialtyLookup();
  return (
    <a className="next-session" href={`#/pacientes/${appt.patient_id}`}>
      <span className="next-time">
        {fmtTime(appt.starts_at)}
        {!isToday && <small>{start.toLocaleDateString("es-UY", { weekday: "short", day: "numeric", month: "short" })}</small>}
      </span>
      <span>
        <strong>{appt.patient_name}</strong>
        {(showProfessional || (showBranch && appt.branch_name)) && (
          <span className="small next-who">
            {showProfessional && (
              <ProfTag name={appt.professional_name} specialty={specialty.byId(appt.professional_id)} />
            )}
            {showBranch && appt.branch_name && <span className="muted">Sucursal {appt.branch_name}</span>}
          </span>
        )}
      </span>
    </a>
  );
}

// Colores validados (diferenciables con daltonismo); siempre acompañados de leyenda con números.
const SEGMENTS = [
  { key: "completed", label: "Realizados", color: "#2e8b57" },
  { key: "scheduled", label: "Programados", color: "#3b6fb6" },
  { key: "no_show", label: "Ausentes", color: "#c98a1a" },
] as const;

function MonthDonut({ month }: { month: DashboardData["month"] }) {
  const total = month.completed + month.scheduled + month.no_show;
  const r = 60;
  const circumference = 2 * Math.PI * r;
  const gap = total > 1 ? 3 : 0; // separación entre segmentos
  let offset = 0;

  return (
    <div className="donut-wrap">
      <svg className="donut" viewBox="0 0 160 160" role="img"
           aria-label={`${total} turnos este mes: ${SEGMENTS.map((s) => `${month[s.key]} ${s.label.toLowerCase()}`).join(", ")}`}>
        <circle cx="80" cy="80" r={r} fill="none" stroke="var(--line)" strokeWidth="16" />
        {total > 0 && SEGMENTS.map((s) => {
          const value = month[s.key];
          if (value === 0) return null;
          const length = (value / total) * circumference;
          const dash = Math.max(length - gap, 1);
          const el = (
            <circle key={s.key} cx="80" cy="80" r={r} fill="none" stroke={s.color} strokeWidth="16"
                    strokeDasharray={`${dash} ${circumference - dash}`} strokeDashoffset={-offset}
                    transform="rotate(-90 80 80)" strokeLinecap="butt">
              <title>{`${s.label}: ${value}`}</title>
            </circle>
          );
          offset += length;
          return el;
        })}
        <text x="80" y="80" textAnchor="middle" className="donut-number">{total}</text>
        <text x="80" y="102" textAnchor="middle" className="donut-caption">TURNOS</text>
      </svg>
      <ul className="donut-legend">
        {SEGMENTS.map((s) => (
          <li key={s.key}>
            <span className="swatch" style={{ background: s.color }} aria-hidden="true" />
            <span>{s.label}</span>
            <strong>{month[s.key]}</strong>
          </li>
        ))}
        <li className="muted">
          <span className="swatch swatch-empty" aria-hidden="true" />
          <span>Cancelados (no se grafican)</span>
          <strong>{month.cancelled}</strong>
        </li>
      </ul>
    </div>
  );
}

// ---- Íconos simples (trazo) ----
function Svg({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round">{children}</svg>
  );
}
const IconCheck = () => <Svg><rect x="4" y="4" width="16" height="16" rx="3" /><path d="m8.5 12 2.5 2.5 4.5-5" /></Svg>;
const IconPerson = () => <Svg><circle cx="12" cy="8" r="3.5" /><path d="M5 20c1.2-3.5 4-5 7-5s5.8 1.5 7 5" /></Svg>;
const IconChart = () => <Svg><circle cx="12" cy="12" r="8" /><path d="m8.5 12 2.5 2.5 4.5-5" /></Svg>;
const IconCard = () => <Svg><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18M7 15h4" /></Svg>;

/** Profesional: sus turnos de hoy, con acceso directo a escribir la nota de la sesión. */
function TodaySessions() {
  const today = todayLocal();
  const appts = useAsync(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    return api.get<Appointment[]>("/appointments", { from: start.toISOString(), to: end.toISOString() });
  }, []);
  const list = (appts.data ?? []).filter((a) => a.status !== "cancelled" && a.status !== "rescheduled");
  if (!appts.data || list.length === 0) return null;
  return (
    <Card title="Mis turnos de hoy">
      <p className="muted small card-sub">Después de cada sesión, escribí la nota desde acá.</p>
      <ul className="list today-list">
        {list.map((a) => (
          <li key={a.id}>
            <strong>{fmtTime(a.starts_at)}</strong>
            <a href={`#/pacientes/${a.patient_id}`}>{a.patient_name}</a>
            <Badge tone={APPOINTMENT_STATUS_TONE[a.status]}>{APPOINTMENT_STATUS_LABELS[a.status]}</Badge>
            <span className="spacer" />
            <a className="btn btn-small" href={`#/pacientes/${a.patient_id}?pestana=historia&fecha=${today}`}>
              Escribir nota
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}
