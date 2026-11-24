import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { askConfirm } from "../confirm";
import { Badge, Card, Dialog, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import { APPOINTMENT_STATUS_LABELS, APPOINTMENT_STATUS_TONE, fmtTime, fullName, isoDate, WEEKDAYS } from "../labels";
import { navigate, useRoute } from "../router";
import { canSchedule, isTitular, useSession } from "../session";
import { notify } from "../toast";
import type { Appointment, AvailabilityBlock, Patient, PatientDetail, Professional } from "../types";
import { professionClass, professionStyle, ProfTag, useSpecialtyLookup } from "../profession";
import { PatientPicker } from "./PatientPicker";
import { GridLegend, showWeekday, TimeGrid, WeekGrid, type GridColumn } from "./WeekGrid";

// Nota: las horas se interpretan en la zona horaria de esta computadora, que debe
// coincidir con la de la clínica (ver "Problemas conocidos" en el README).

function startOfWeek(d: Date): Date {
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const offset = (day.getDay() + 6) % 7; // lunes = 0
  day.setDate(day.getDate() - offset);
  return day;
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

const toInputDate = isoDate;

/** "2026-10-20" + "10:30" (hora local) -> ISO con zona horaria. */
function localToIso(date: string, time: string, plusMinutes = 0): string {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  return new Date(y, m - 1, d, hh, mm + plusMinutes).toISOString();
}

const DURATIONS = [30, 45, 50, 60, 90];
const SUNDAY_CLOSED = "La clínica no atiende los domingos.";

/** Antes de dar o mover un turno: el domingo no se atiende y, si la fecha ya pasó, se pide
 * confirmación (solo se aceptan fechas pasadas del mes en curso; lo controla el servidor).
 * Devuelve null si no hay que seguir, o el valor de ``confirm_past`` para enviar. */
async function checkSlot(date: string, time: string, fail: (message: string) => void): Promise<boolean | null> {
  const [y, m, d] = date.split("-").map(Number);
  if (new Date(y, m - 1, d).getDay() === 0) { fail(SUNDAY_CLOSED); return null; }
  if (new Date(localToIso(date, time)).getTime() >= Date.now()) return false;
  const ok = await askConfirm(
    `Ese turno es el ${date.split("-").reverse().join("/")} a las ${time}, una fecha u hora que ya pasó.\n\n` +
    "Se puede cargar solo dentro del mes en curso (por ejemplo, una sesión que se olvidó agendar) y " +
    "queda registrado en la auditoría. ¿Cargarlo igual?",
    { confirmLabel: "Cargar con fecha pasada" },
  );
  return ok ? true : null;
}

type View = "grid" | "list" | "day" | "free";
const VIEW_KEY = "medflow.agendaView";

/** Vista con la que abre la Agenda: la última que eligió esta persona en este navegador; si
 * nunca eligió, Lista en el celular (la grilla no entra), "Día (todos)" para recepción y
 * Grilla para el resto. */
function initialView(role: string): View {
  let saved: string | null = null;
  try { saved = localStorage.getItem(VIEW_KEY); } catch { /* sin almacenamiento */ }
  if (saved === "list" || saved === "grid") return saved;
  // La vista diaria y la de horas libres (todos los profesionales) las usan todos los roles.
  if (saved === "day" || saved === "free") return saved;
  if (window.matchMedia?.("(max-width: 640px)").matches) return "list";
  return role === "reception" ? "day" : "grid";
}

/** "lunes 20 de octubre" con mayúscula inicial. */
function longDay(d: Date): string {
  const text = d.toLocaleDateString("es-UY", { weekday: "long", day: "numeric", month: "long" });
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** El turno ya empezó (desde ese momento se puede marcar como realizado o ausente). */
function hasStarted(appt: Appointment): boolean {
  return new Date(appt.starts_at).getTime() <= Date.now();
}

export function AgendaPage() {
  const { user, branch, clinic } = useSession();
  const route = useRoute();
  const isProfessional = user.role === "professional";
  // Profesional independiente: es la única agenda del consultorio (sin sucursales ni profesiones).
  const titular = isTitular(user, clinic);
  // Dar, reprogramar y cancelar turnos y cambiar horarios: Recepción, Administración o el titular.
  const canBook = canSchedule(user, clinic);
  const professionals = useAsync(() => api.get<Professional[]>("/professionals"), []);
  // Solo quienes trabajan en la sucursal activa.
  const profList = useMemo(
    () => professionals.data?.filter((p) => p.branch_ids.includes(branch.id)),
    [professionals.data, branch.id],
  );
  // Profesiones (especialidades) de quienes trabajan en la sucursal, para filtrar "Día (todos)"
  // y "Horas libres". "" = todas.
  const specialties = useMemo(() => {
    const seen = new Map<string, string>();
    for (const p of profList ?? []) if (p.specialty_id && p.specialty_name) seen.set(p.specialty_id, p.specialty_name);
    return [...seen].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name, "es"));
  }, [profList]);
  const [specialtyId, setSpecialtyId] = useState("");
  const specialtyName = specialties.find((s) => s.id === specialtyId)?.name;
  const filteredProfs = useMemo(
    () => (specialtyId ? profList?.filter((p) => p.specialty_id === specialtyId) : profList),
    [profList, specialtyId],
  );
  // Si se cambia de sucursal y esa profesión no está, se vuelve a "Todas".
  useEffect(() => {
    if (specialtyId && profList && !specialties.some((s) => s.id === specialtyId)) setSpecialtyId("");
  }, [specialtyId, specialties, profList]);
  const [profId, setProfId] = useState(isProfessional ? user.id : "");
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [view, setView] = useState<View>(() => initialView(user.role));
  // Cambia cuando se da o modifica un turno u horario, para refrescar la vista diaria.
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = () => setRefreshKey((k) => k + 1);
  const [selected, setSelected] = useState<Appointment | null>(null);
  // Hueco elegido en la grilla: abre la ventana para dar el turno.
  const [slot, setSlot] = useState<{ date: string; time: string; professionalId: string } | null>(null);

  // Paciente que llega desde su ficha ("Dar turno"): queda elegido en el formulario.
  const presetId = route.params.get("paciente");
  const preset = useAsync(
    () => (presetId ? api.get<PatientDetail>(`/patients/${presetId}`) : Promise.resolve(null)),
    [presetId],
  );
  const presetPatient = presetId && preset.data?.id === presetId ? preset.data : null;
  // Con el paciente elegido, se propone su profesional responsable (si atiende en esta sucursal).
  useEffect(() => {
    if (isProfessional || !presetPatient?.responsible_id || !profList) return;
    if (profList.some((p) => p.id === presetPatient.responsible_id)) setProfId(presetPatient.responsible_id);
  }, [isProfessional, presetPatient, profList]);
  const clearPreset = () => navigate("/agenda");

  const availability = useAsync(
    () => (profId ? api.get<AvailabilityBlock[]>("/availability", { professional_id: profId })
                  : Promise.resolve([] as AvailabilityBlock[])),
    [profId],
  );

  function changeView(next: View) {
    setView(next);
    try { localStorage.setItem(VIEW_KEY, next); } catch { /* sin almacenamiento: no pasa nada */ }
  }

  function pickSlot(day: Date, time: string, professionalId?: string) {
    setSelected(null);
    setSlot({ date: toInputDate(day), time, professionalId: professionalId ?? profId });
  }

  useEffect(() => {
    if (!profId && profList && profList.length > 0) {
      setProfId(profList[0].id);
    }
  }, [profId, profList]);

  // La grilla sombrea solo los horarios de esta sucursal.
  const branchBlocks = (availability.data ?? []).filter((b) => b.branch_id === branch.id);

  const weekEnd = addDays(weekStart, 7);
  const appts = useAsync(
    () => (profId
      ? api.get<Appointment[]>("/appointments", {
          from: weekStart.toISOString(), to: weekEnd.toISOString(), professional_id: profId,
        })
      : Promise.resolve([] as Appointment[])),
    [profId, weekStart.getTime()],
  );

  const byDay = useMemo(() => {
    const groups: Appointment[][] = Array.from({ length: 7 }, () => []);
    for (const a of appts.data ?? []) {
      const idx = Math.floor((new Date(a.starts_at).getTime() - weekStart.getTime()) / 86400000);
      if (idx >= 0 && idx < 7) groups[idx].push(a);
    }
    return groups;
  }, [appts.data, weekStart]);

  const weekLabel = `${weekStart.toLocaleDateString("es-UY")} – ${addDays(weekStart, 6).toLocaleDateString("es-UY")}`;
  const isDay = view === "day";
  const isFree = view === "free";
  // Vistas con todos los profesionales de la sucursal (no se elige uno).
  const allProfs = isDay || isFree;
  const profName = (id: string) => profList?.find((p) => p.id === id)?.full_name;
  const afterChange = () => { appts.reload(); refresh(); };

  return (
    <>
      <div className="page-title">
        <h1>Agenda</h1>
      </div>
      {presetPatient && (
        <p className="alert alert-info" role="status">
          Dando turno a <strong>{fullName(presetPatient)}</strong>.{" "}
          {isDay ? "Hacé clic en un hueco libre del profesional que corresponda."
            : isFree ? "Tocá el nombre del profesional en la hora libre que corresponda."
            : "Hacé clic en un hueco libre de la grilla o completá el formulario de abajo."}
          <button type="button" className="link-button" onClick={clearPreset}>Quitar</button>
        </p>
      )}
      <ErrorBox message={presetId ? preset.error : null} />
      <Card>
        <div className="toolbar">
          {allProfs && !titular && (
            <Field label="Profesión">
              {(id) => (
                <select id={id} value={specialtyId} onChange={(e) => setSpecialtyId(e.target.value)}>
                  <option value="">Todas</option>
                  {specialties.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              )}
            </Field>
          )}
          {!isProfessional && !allProfs && (
            <Field label="Profesional">
              {(id) => (
                <select id={id} value={profId} onChange={(e) => setProfId(e.target.value)}>
                  {(profList ?? []).map((p) => (
                    <option key={p.id} value={p.id}>{p.full_name}</option>
                  ))}
                </select>
              )}
            </Field>
          )}
          {!isDay && (<>
          <div className="week-nav" role="group" aria-label="Cambiar de semana">
            <button type="button" className="btn" onClick={() => setWeekStart(addDays(weekStart, -7))}>
              ← Anterior
            </button>
            <button type="button" className="btn" onClick={() => setWeekStart(startOfWeek(new Date()))}>
              Hoy
            </button>
            <button type="button" className="btn" onClick={() => setWeekStart(addDays(weekStart, 7))}>
              Siguiente →
            </button>
          </div>
          <Field label="Ir a la fecha">
            {(id) => (
              <input id={id} type="date" value={toInputDate(weekStart)}
                     onChange={(e) => {
                       if (!e.target.value) return;
                       const [y, m, d] = e.target.value.split("-").map(Number);
                       setWeekStart(startOfWeek(new Date(y, m - 1, d)));
                     }} />
            )}
          </Field>
          <strong aria-live="polite">Semana {weekLabel}</strong>
          </>)}
          <div className="view-toggle" role="group" aria-label="Forma de ver la agenda">
            <button type="button" className={view === "grid" ? "btn btn-primary" : "btn"}
                    aria-pressed={view === "grid"} onClick={() => changeView("grid")}>Grilla</button>
            <button type="button" className={view === "list" ? "btn btn-primary" : "btn"}
                    aria-pressed={view === "list"} onClick={() => changeView("list")}>Lista</button>
            <button type="button" className={isDay ? "btn btn-primary" : "btn"}
                    aria-pressed={isDay} onClick={() => changeView("day")}
                    title={titular ? "Tu agenda de un día" : "Todos los profesionales de la sucursal en un día"}>
              {titular ? "Día" : "Día (todos)"}
            </button>
            <button type="button" className={isFree ? "btn btn-primary" : "btn"}
                    aria-pressed={isFree} onClick={() => changeView("free")}
                    title={titular ? "Tus horas libres de la semana"
                      : "Las horas libres de la semana de todos los profesionales (o de una profesión)"}>
              Horas libres
            </button>
          </div>
        </div>
        {!titular && (
        <p className="muted small">
          Agenda de la sucursal <strong>{branch.name}</strong>: los turnos y horarios que ves y los que
          agregues son de esta sucursal. Para otra, cambiala desde el encabezado.
        </p>
        )}
        {profList && profList.length === 0 && (
          <Empty>
            Ningún profesional trabaja en {branch.name}. Administración puede asignarles la sucursal en Usuarios.
          </Empty>
        )}
        {allProfs && profList && profList.length > 0 && filteredProfs?.length === 0 && (
          <Empty>Ningún profesional de {specialtyName ?? "esa profesión"} trabaja en {branch.name}.</Empty>
        )}
        {isDay && filteredProfs && filteredProfs.length > 0 && (
          <BranchDayView professionals={filteredProfs} refreshKey={refreshKey} specialtyName={specialtyName}
                         onPick={(professionalId, day, time) => pickSlot(day, time, professionalId)}
                         onChanged={afterChange} />
        )}
        {isFree && filteredProfs && filteredProfs.length > 0 && (
          <FreeSlotsView professionals={filteredProfs} weekStart={weekStart} refreshKey={refreshKey}
                         specialtyName={specialtyName}
                         onPick={(professionalId, day, time) => pickSlot(day, time, professionalId)} />
        )}
        {!allProfs && appts.loading && <Loading />}
        {!allProfs && <ErrorBox message={appts.error} />}
        {profId && view === "grid" && (
          <>
            <p className="muted small">
              {canBook ? "Hacé clic en un hueco libre para dar un turno, o en un turno para ver sus opciones."
                : "Hacé clic en un turno para ver sus opciones. Los turnos los dan Recepción y Administración."}
            </p>
            <div className="table-wrap">
              <WeekGrid weekStart={weekStart} byDay={byDay} availability={branchBlocks}
                        selectedId={selected?.id ?? null}
                        onSelect={(a) => { setSlot(null); setSelected(a); }}
                        onPickSlot={canBook ? pickSlot : undefined} />
            </div>
            <GridLegend />
            {selected && (
              <AppointmentDialog appt={selected} onClose={() => setSelected(null)}
                                 onChanged={() => { setSelected(null); afterChange(); }} />
            )}
          </>
        )}
        {profId && view === "list" && (
          <div className="week">
            {byDay.map((list, i) => !showWeekday(i, branchBlocks, list) ? null : (
              <section key={i} className="day" aria-label={WEEKDAYS[i]}>
                <h3>
                  {WEEKDAYS[i]} <small>{addDays(weekStart, i).toLocaleDateString("es-UY", { day: "2-digit", month: "2-digit" })}</small>
                </h3>
                {list.length === 0 && <p className="muted small">Sin turnos</p>}
                {list.map((a) => (
                  <AppointmentItem key={a.id} appt={a} onChanged={afterChange} />
                ))}
              </section>
            ))}
          </div>
        )}
      </Card>
      {slot && canBook && (
        <NewAppointmentDialog slot={slot} professionalName={isProfessional ? undefined : profName(slot.professionalId)}
                              presetPatient={presetPatient}
                              onClose={() => setSlot(null)}
                              onSaved={() => { setSlot(null); afterChange(); if (presetPatient) clearPreset(); }} />
      )}
      {/* En "Día (todos)" y "Horas libres" se da el turno tocando un hueco: no hace falta el formulario de abajo. */}
      {profId && !allProfs && canBook && (
        <Card title={isProfessional ? "Dar un turno" : `Dar un turno con ${profName(profId) ?? ""}`}>
          <NewAppointmentForm key={`${profId}-${presetPatient?.id ?? ""}`} professionalId={profId}
                              presetPatient={presetPatient}
                              onSaved={() => { afterChange(); if (presetPatient) clearPreset(); }} />
        </Card>
      )}
      {profId && !allProfs && <AvailabilityCard professionalId={profId}
                                            onChanged={() => { availability.reload(); refresh(); }} />}
    </>
  );
}

/** Un día de la sucursal: una columna por profesional que atiende ese día. */
function BranchDayView({ professionals, refreshKey, specialtyName, onPick, onChanged }: {
  professionals: Professional[];
  refreshKey: number;
  specialtyName?: string;
  onPick: (professionalId: string, day: Date, time: string) => void;
  onChanged: () => void;
}) {
  const { branch, user, clinic } = useSession();
  const isProfessional = user.role === "professional";
  const canBook = canSchedule(user, clinic);
  const [day, setDay] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()); });
  const [selected, setSelected] = useState<Appointment | null>(null);
  const [showAll, setShowAll] = useState(false);
  const appts = useAsync(
    () => api.get<Appointment[]>("/appointments", {
      from: day.toISOString(), to: addDays(day, 1).toISOString(), all_professionals: "true",
    }),
    [day.getTime(), refreshKey],
  );
  // Horarios de todos los profesionales en esta sucursal.
  const blocks = useAsync(() => api.get<AvailabilityBlock[]>("/availability"), [refreshKey]);
  const weekday = (day.getDay() + 6) % 7;

  const columns: GridColumn[] = professionals
    .map((p) => ({
      p,
      appointments: (appts.data ?? []).filter((a) => a.professional_id === p.id),
      blocks: (blocks.data ?? []).filter((b) => b.professional_id === p.id && b.weekday === weekday),
    }))
    // Por defecto, solo quienes atienden ese día (tienen horario o algún turno).
    .filter((c) => showAll || c.blocks.length > 0 || c.appointments.some((a) => a.status !== "cancelled"))
    .map(({ p, appointments, blocks: profBlocks }) => ({
      key: p.id,
      title: <ProfTag name={p.full_name} specialty={p.specialty_name} />,
      appointments,
      blocks: profBlocks,
      slotLabel: (time) => `Dar turno con ${p.full_name} a las ${time}`,
      // Solo Recepción, Administración y el titular dan turnos (el titular tiene una sola columna).
      onPick: canBook ? (time: string) => onPick(p.id, day, time) : undefined,
    }));

  const label = day.toLocaleDateString("es-UY", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const isToday = day.toDateString() === new Date().toDateString();

  return (
    <>
      <div className="toolbar">
        <div className="week-nav" role="group" aria-label="Cambiar de día">
          <button type="button" className="btn" onClick={() => setDay(addDays(day, -1))}>← Día anterior</button>
          <button type="button" className="btn" disabled={isToday}
                  onClick={() => { const d = new Date(); setDay(new Date(d.getFullYear(), d.getMonth(), d.getDate())); }}>
            Hoy
          </button>
          <button type="button" className="btn" onClick={() => setDay(addDays(day, 1))}>Día siguiente →</button>
        </div>
        <Field label="Ir a la fecha">
          {(id) => (
            <input id={id} type="date" value={toInputDate(day)} onChange={(e) => {
              if (!e.target.value) return;
              const [y, m, d] = e.target.value.split("-").map(Number);
              setDay(new Date(y, m - 1, d));
            }} />
          )}
        </Field>
        <strong aria-live="polite" className="day-label">{label.charAt(0).toUpperCase() + label.slice(1)}</strong>
      </div>
      <p className="muted small">
        {specialtyName ? <>Los profesionales de <strong>{specialtyName}</strong></> : "Todos los profesionales"} que
        atienden en <strong>{branch.name}</strong> ese día. Lo sombreado es su
        horario: {!canBook
          ? "hacé clic en un turno para verlo. Los turnos los dan Recepción y Administración; los de tus compañeros son solo para consultar."
          : "hacé clic en un hueco libre para darle un turno, o en un turno para ver sus opciones."}{" "}
        <label className="checkbox inline-check">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          Mostrar también a quienes no atienden ese día
        </label>
      </p>
      {(appts.loading || blocks.loading) && <Loading />}
      <ErrorBox message={appts.error ?? blocks.error} />
      {appts.data && blocks.data && columns.length === 0 && (
        <Empty>{weekday === 6 ? SUNDAY_CLOSED
          : <>Ningún profesional{specialtyName ? ` de ${specialtyName}` : ""} atiende en {branch.name} este día.</>}</Empty>
      )}
      {columns.length > 0 && (
        <div className="table-wrap">
          <TimeGrid columns={columns} selectedId={selected?.id ?? null} minColumnWidth={150}
                    label={`Agenda de ${branch.name} del día, por profesional`}
                    onSelect={(a) => setSelected(a)} />
        </div>
      )}
      {columns.length > 0 && <GridLegend />}
      {selected && (
        <AppointmentDialog appt={selected} showProfessional
                           readOnly={isProfessional && selected.professional_id !== user.id}
                           onClose={() => setSelected(null)}
                           onChanged={() => { setSelected(null); onChanged(); }} />
      )}
    </>
  );
}

const FREE_SLOT_MIN = 30; // igual que los huecos de la grilla
// Estos turnos no ocupan el horario (igual que en la grilla).
const NOT_BUSY = new Set(["cancelled", "rescheduled"]);

function minutesOf(time: string): number {
  const [h, m] = time.split(":").map(Number);
  return h * 60 + m;
}

function hhmm(min: number): string {
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
}

/** Horas libres de la semana en la sucursal: por día y por hora, qué profesionales (de la
 * profesión elegida, o todos) tienen ese hueco de 30 minutos dentro de su horario y sin turnos.
 * No muestra horas que ya pasaron ni el domingo. */
function FreeSlotsView({ professionals, weekStart, refreshKey, specialtyName, onPick }: {
  professionals: Professional[];
  weekStart: Date;
  refreshKey: number;
  specialtyName?: string;
  onPick: (professionalId: string, day: Date, time: string) => void;
}) {
  const { branch, clinic, user } = useSession();
  const canBook = canSchedule(user, clinic);
  const weekEnd = addDays(weekStart, 7);
  const appts = useAsync(
    () => api.get<Appointment[]>("/appointments", {
      from: weekStart.toISOString(), to: weekEnd.toISOString(), all_professionals: "true",
    }),
    [weekStart.getTime(), refreshKey],
  );
  // Horarios de todos los profesionales en esta sucursal.
  const blocks = useAsync(() => api.get<AvailabilityBlock[]>("/availability"), [refreshKey]);

  const days = useMemo(() => {
    if (!appts.data || !blocks.data) return null;
    const now = Date.now();
    const busy = appts.data.filter((a) => !NOT_BUSY.has(a.status));
    // Lunes a sábado (el domingo la clínica no atiende).
    return Array.from({ length: 6 }, (_, i) => {
      const day = addDays(weekStart, i);
      const byTime = new Map<number, Professional[]>();
      for (const p of professionals) {
        const mine = busy.filter((a) => a.professional_id === p.id);
        for (const b of blocks.data!.filter((x) => x.professional_id === p.id && x.weekday === i)) {
          for (let m = minutesOf(b.start_time); m + FREE_SLOT_MIN <= minutesOf(b.end_time); m += FREE_SLOT_MIN) {
            const start = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, m).getTime();
            const end = start + FREE_SLOT_MIN * 60000;
            if (start < now) continue; // ya pasó
            if (mine.some((a) => new Date(a.starts_at).getTime() < end && new Date(a.ends_at).getTime() > start)) continue;
            const list = byTime.get(m) ?? [];
            if (!list.includes(p)) list.push(p);
            byTime.set(m, list);
          }
        }
      }
      const times = [...byTime.keys()].sort((a, b) => a - b).map((m) => ({
        minutes: m,
        professionals: byTime.get(m)!.sort((a, b) => a.full_name.localeCompare(b.full_name, "es")),
      }));
      return { day, times };
    });
  }, [appts.data, blocks.data, professionals, weekStart]);

  const total = days?.reduce((n, d) => n + d.times.reduce((k, t) => k + t.professionals.length, 0), 0) ?? 0;
  const who = specialtyName ? <>de <strong>{specialtyName}</strong></> : "de todos los profesionales";

  return (
    <>
      <p className="muted small">
        Horas libres {who} en <strong>{branch.name}</strong> esta semana, en tramos de {FREE_SLOT_MIN} minutos
        dentro de su horario. {canBook
          ? "Tocá el nombre de un profesional para darle un turno a esa hora."
          : "Es para consultar: los turnos los dan Recepción y Administración."}
      </p>
      {(appts.loading || blocks.loading) && <Loading />}
      <ErrorBox message={appts.error ?? blocks.error} />
      {days && total === 0 && <Empty>No quedan horas libres {who} esta semana.</Empty>}
      {days && total > 0 && (
        <div className="free-days">
          {days.filter((d) => d.times.length > 0).map(({ day, times }) => (
            <section key={day.getTime()} className="free-day" aria-label={longDay(day)}>
              <h3>{longDay(day)}</h3>
              <ul className="free-times">
                {times.map(({ minutes, professionals: list }) => (
                  <li key={minutes}>
                    <strong className="free-time">{hhmm(minutes)}</strong>
                    <span className="free-profs">
                      {list.map((p) => (!canBook ? (
                        <ProfTag key={p.id} name={p.full_name} specialty={p.specialty_name} />
                      ) : (
                        <button key={p.id} type="button" className={`btn btn-small ${professionClass(p.specialty_name)}`}
                                title={`Dar turno con ${p.full_name}${p.specialty_name ? ` (${p.specialty_name})` : ""} el ${longDay(day).toLowerCase()} a las ${hhmm(minutes)}`}
                                onClick={() => onPick(p.id, day, hhmm(minutes))}>
                          {p.full_name}
                          {professionStyle(p.specialty_name) && (
                            <span className="prof-abbr">· {professionStyle(p.specialty_name)!.abbr}</span>
                          )}
                        </button>
                      )))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

/** Ventana con las opciones de un turno (Realizado, Ausente, Reprogramar, Cancelar) al tocarlo
 * en la grilla o en la vista del día: se abre encima, así no queda fuera de la vista. */
function AppointmentDialog({ appt, showProfessional = false, readOnly = false, onClose, onChanged }: {
  appt: Appointment; showProfessional?: boolean; readOnly?: boolean; onClose: () => void; onChanged: () => void;
}) {
  const titleId = useId();
  const specialty = useSpecialtyLookup();
  return (
    <Dialog className="appt-dialog" labelledBy={titleId} onClose={onClose}>
      <div className="modal-head">
        <h2 id={titleId}>Turno de {appt.patient_name}</h2>
        <button type="button" className="icon-close" onClick={onClose} aria-label="Cerrar">✕</button>
      </div>
      <p className="muted small">
        {longDay(new Date(appt.starts_at))}
        {showProfessional && <> · <ProfTag name={appt.professional_name} specialty={specialty.byId(appt.professional_id)} /></>}
        {appt.branch_name && <> · Sucursal {appt.branch_name}</>}
      </p>
      {readOnly && (
        <p className="muted small">Es un turno de otro profesional: lo podés ver, pero no modificar.</p>
      )}
      <AppointmentItem key={appt.id} appt={appt} onChanged={onChanged} detailed readOnly={readOnly} />
      <div className="form-actions">
        <button type="button" className="btn" onClick={onClose}>Cerrar</button>
      </div>
    </Dialog>
  );
}

function AppointmentItem({ appt, onChanged, detailed = false, readOnly = false }: {
  appt: Appointment; onChanged: () => void; detailed?: boolean; readOnly?: boolean;
}) {
  const { user, clinic } = useSession();
  // Reprogramar y cancelar: Recepción, Administración o el titular. Realizado y Ausente, también
  // el profesional del turno.
  const canBook = canSchedule(user, clinic);
  const [mode, setMode] = useState<"none" | "cancel" | "move" | "absent">("none");
  const [reason, setReason] = useState("");
  const [date, setDate] = useState(toInputDate(new Date(appt.starts_at)));
  const [time, setTime] = useState(fmtTime(appt.starts_at));
  const action = useAction();
  const minutes = Math.round((new Date(appt.ends_at).getTime() - new Date(appt.starts_at).getTime()) / 60000);
  // Solo lectura (turno de un compañero): sin acciones.
  const active = appt.status === "scheduled" && !readOnly;
  const started = hasStarted(appt);

  async function act(fn: () => Promise<unknown>, success?: string) {
    const ok = await action.run(async () => { await fn(); });
    if (ok) {
      if (success) notify(success);
      setMode("none");
      onChanged();
    }
  }

  /** Realizado no se puede deshacer: se confirma antes. (Ausente se confirma en su propio
   * formulario, donde además se puede escribir el motivo.) */
  async function markCompleted() {
    const when = `${longDay(new Date(appt.starts_at))}, ${fmtTime(appt.starts_at)}`;
    const ok = await askConfirm(
      `¿Marcar el turno de ${appt.patient_name} (${when}) como realizado?\nDespués no se puede cambiar.`,
      { confirmLabel: "Marcar realizado" },
    );
    if (!ok) return;
    await act(() => api.post(`/appointments/${appt.id}/status`, { status: "completed" }),
              `Turno de ${appt.patient_name} marcado como realizado.`);
  }

  return (
    <article className={`appt appt-${appt.status}`} aria-busy={action.busy}>
      <div>
        <strong>{fmtTime(appt.starts_at)}–{fmtTime(appt.ends_at)}</strong>{" "}
        {readOnly ? appt.patient_name : <a href={`#/pacientes/${appt.patient_id}`}>{appt.patient_name}</a>}
      </div>
      <Badge tone={APPOINTMENT_STATUS_TONE[appt.status]}>{APPOINTMENT_STATUS_LABELS[appt.status]}</Badge>
      {appt.cancel_reason && <div className="muted small">Motivo: {appt.cancel_reason}</div>}
      {appt.reschedule_reason && <div className="muted small">Motivo de la reprogramación: {appt.reschedule_reason}</div>}
      {appt.no_show_reason && <div className="muted small">Motivo de la ausencia: {appt.no_show_reason}</div>}
      <ErrorBox message={action.error} />
      {active && mode === "none" && (
        <div className="appt-actions">
          {started && (<>
            <button type="button" className="btn btn-small" disabled={action.busy}
                    onClick={markCompleted}>
              Realizado
            </button>
            <button type="button" className="btn btn-small" disabled={action.busy}
                    onClick={() => { setReason(""); setMode("absent"); }}>
              Ausente
            </button>
          </>)}
          {canBook && (<>
          <button type="button" className="btn btn-small" disabled={action.busy}
                  onClick={() => { setReason(""); setMode("move"); }}>Reprogramar</button>
          <button type="button" className="btn btn-small btn-danger" disabled={action.busy}
                  onClick={() => { setReason(""); setMode("cancel"); }}>Cancelar</button>
          </>)}
        </div>
      )}
      {active && mode === "none" && !canBook && detailed && (
        <p className="muted small">Para reprogramar o cancelar este turno, pedíselo a Recepción.</p>
      )}
      {active && mode === "none" && !started && detailed && (
        <p className="muted small">Realizado y Ausente se habilitan desde la hora de inicio del turno.</p>
      )}
      {mode === "absent" && (
        <form className="mini-form" onSubmit={(e: FormEvent) => {
          e.preventDefault();
          act(() => api.post(`/appointments/${appt.id}/status`, { status: "no_show", reason }),
              `Turno de ${appt.patient_name} marcado como ausente.`);
        }}>
          <Field label="Motivo de la ausencia" hint="Opcional. Queda en la ficha del paciente, en la pestaña Turnos.">
            {(id, hint) => <input id={id} aria-describedby={hint} maxLength={300} value={reason} autoFocus
                                  placeholder="Por ejemplo: avisó que estaba enfermo"
                                  onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <p className="muted small">Después de marcarlo como ausente no se puede cambiar.</p>
          <div className="form-actions">
            <button type="button" className="btn btn-small" onClick={() => setMode("none")}>Volver</button>
            <button type="submit" className="btn btn-small btn-primary" disabled={action.busy}>
              {action.busy ? "Guardando…" : "Marcar ausente"}
            </button>
          </div>
        </form>
      )}
      {mode === "cancel" && (
        <form className="mini-form" onSubmit={(e: FormEvent) => {
          e.preventDefault();
          act(() => api.post(`/appointments/${appt.id}/cancel`, { reason }),
              `Turno de ${appt.patient_name} cancelado.`);
        }}>
          <Field label="Motivo de la cancelación" required>
            {(id) => <input id={id} required minLength={3} maxLength={300} value={reason} autoFocus
                            onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <div className="form-actions">
            <button type="button" className="btn btn-small" onClick={() => setMode("none")}>Volver</button>
            <button type="submit" className="btn btn-small btn-danger" disabled={action.busy}>
              {action.busy ? "Cancelando…" : "Cancelar turno"}
            </button>
          </div>
        </form>
      )}
      {mode === "move" && (
        <form className="mini-form" onSubmit={async (e: FormEvent) => {
          e.preventDefault();
          const confirmPast = await checkSlot(date, time, action.setError);
          if (confirmPast === null) return;
          act(() => api.post(`/appointments/${appt.id}/reschedule`, {
            starts_at: localToIso(date, time), ends_at: localToIso(date, time, minutes), confirm_past: confirmPast,
            reason,
          }), `Turno de ${appt.patient_name} reprogramado para el ${date.split("-").reverse().join("/")} a las ${time}.`);
        }}>
          <Field label="Nueva fecha" required>
            {(id) => <input id={id} type="date" required value={date} onChange={(e) => setDate(e.target.value)} />}
          </Field>
          <Field label="Nueva hora" required>
            {(id) => <input id={id} type="time" required step={300} value={time} onChange={(e) => setTime(e.target.value)} />}
          </Field>
          <Field label="Motivo de la reprogramación" required hint="Queda en la ficha del paciente, en la pestaña Turnos.">
            {(id, hint) => <input id={id} aria-describedby={hint} required minLength={3} maxLength={300} value={reason}
                                  onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <div className="form-actions">
            <button type="button" className="btn btn-small" onClick={() => setMode("none")}>Volver</button>
            <button type="submit" className="btn btn-small btn-primary" disabled={action.busy}>
              {action.busy ? "Guardando…" : "Reprogramar"}
            </button>
          </div>
        </form>
      )}
    </article>
  );
}

/** Ventana para dar un turno al tocar un hueco libre de la grilla o de la vista del día. */
function NewAppointmentDialog({ slot, professionalName, presetPatient, onClose, onSaved }: {
  slot: { date: string; time: string; professionalId: string };
  professionalName?: string;
  presetPatient: Patient | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const titleId = useId();
  const [y, m, d] = slot.date.split("-").map(Number);
  return (
    <Dialog className="new-appt" labelledBy={titleId} onClose={onClose}>
      <div className="modal-head">
        <h2 id={titleId}>{professionalName ? `Dar un turno con ${professionalName}` : "Dar un turno"}</h2>
        <button type="button" className="icon-close" onClick={onClose} aria-label="Cerrar">✕</button>
      </div>
      <p className="muted small">{longDay(new Date(y, m - 1, d))}, {slot.time}</p>
      <NewAppointmentForm professionalId={slot.professionalId} initialDate={slot.date} initialTime={slot.time}
                          presetPatient={presetPatient} onSaved={onSaved} onCancel={onClose} inDialog />
    </Dialog>
  );
}

function NewAppointmentForm({ professionalId, presetPatient, onSaved, onCancel, initialDate, initialTime,
  inDialog = false }: {
  professionalId: string; presetPatient?: Patient | null; onSaved: () => void; onCancel?: () => void;
  initialDate?: string; initialTime?: string; inDialog?: boolean;
}) {
  const { user } = useSession();
  const [patient, setPatient] = useState<Patient | null>(presetPatient ?? null);
  const [date, setDate] = useState(initialDate ?? toInputDate(addDays(new Date(), 1)));
  const [time, setTime] = useState(initialTime ?? "10:00");
  const [duration, setDuration] = useState(50);
  const { busy, error, setError, run } = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!patient) return;
    const confirmPast = await checkSlot(date, time, setError);
    if (confirmPast === null) return;
    const ok = await run(async () => {
      await api.post("/appointments", {
        patient_id: patient.id, professional_id: professionalId,
        starts_at: localToIso(date, time), ends_at: localToIso(date, time, duration), confirm_past: confirmPast,
      });
    });
    if (ok) {
      notify(`Turno agendado: ${patient.first_name} ${patient.last_name}, ${date.split("-").reverse().join("/")} a las ${time}.`);
      setPatient(null); // el próximo turno empieza con el buscador vacío
      onSaved();
    }
  }

  return (
    <>
      {user.role !== "professional" && (
        <p className="muted small">
          Solo se pueden dar turnos a pacientes activos con los que trabaja este profesional (como
          responsable o colaborador).{" "}
          {user.role === "reception"
            ? "Si todavía no trabaja con el paciente, pedile a administración o al profesional responsable que lo sume."
            : "Para sumarlo a un paciente: ficha del paciente → Accesos."}
        </p>
      )}
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Paciente" required>
          {(id) => <PatientPicker id={id} value={patient} onChange={setPatient} autoFocus={inDialog && !patient} />}
        </Field>
        <Field label="Fecha" required>
          {(id) => <input id={id} type="date" required value={date} onChange={(e) => setDate(e.target.value)} />}
        </Field>
        <Field label="Hora de inicio" required>
          {(id) => <input id={id} type="time" required step={300} value={time} onChange={(e) => setTime(e.target.value)} />}
        </Field>
        <Field label="Duración">
          {(id) => (
            <select id={id} value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
              {DURATIONS.map((d) => <option key={d} value={d}>{d} minutos</option>)}
            </select>
          )}
        </Field>
        <div className="form-actions">
          {onCancel && <button type="button" className="btn" onClick={onCancel}>Cancelar</button>}
          <button type="submit" className="btn btn-primary" disabled={busy || !patient}>
            {busy ? "Guardando…" : "Agendar turno"}
          </button>
        </div>
      </form>
    </>
  );
}

function AvailabilityCard({ professionalId, onChanged }: { professionalId: string; onChanged?: () => void }) {
  const { branch, user, clinic } = useSession();
  // Los horarios los cargan y quitan Recepción, Administración o el titular; un profesional de
  // una clínica solo los ve.
  const canEdit = canSchedule(user, clinic);
  // Administración y el titular pueden quitar horarios de cualquier sucursal; recepción, solo
  // los de la suya.
  const canRemoveElsewhere = canEdit && user.role !== "reception";
  const blocks = useAsync(
    () => api.get<AvailabilityBlock[]>("/availability", { professional_id: professionalId }),
    [professionalId],
  );
  const [weekday, setWeekday] = useState(0);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("13:00");
  const action = useAction();

  async function add(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post("/availability", {
        professional_id: professionalId, weekday, start_time: start, end_time: end,
      });
    });
    if (ok) { blocks.reload(); onChanged?.(); }
  }

  async function remove(b: AvailabilityBlock) {
    const where = b.branch_name ?? branch.name;
    const ok = await askConfirm(
      `¿Quitar el horario del ${WEEKDAYS[b.weekday].toLowerCase()} de ${b.start_time.slice(0, 5)} a ` +
      `${b.end_time.slice(0, 5)} en ${where}?\nLos turnos ya dados no se cancelan, pero no se podrán dar ` +
      "turnos nuevos en ese horario.",
      { confirmLabel: "Quitar horario", danger: true },
    );
    if (!ok) return;
    const done = await action.run(async () => { await api.del(`/availability/${b.id}`); });
    if (done) { blocks.reload(); onChanged?.(); }
  }

  const here = (blocks.data ?? []).filter((b) => b.branch_id === branch.id);
  const elsewhere = (blocks.data ?? []).filter((b) => b.branch_id !== branch.id);

  return (
    <Card title={`Disponibilidad semanal en ${branch.name}`}>
      <p className="muted small">
        Los turnos en {branch.name} solo pueden darse dentro de estos horarios. Un profesional no puede
        tener horarios a la misma hora en dos sucursales.
        {!canEdit && " Para cambiar tus horarios, pedíselo a Recepción o a Administración."}
      </p>
      <ErrorBox message={action.error} />
      {blocks.loading && <Loading />}
      <ErrorBox message={blocks.error} />
      {blocks.data && here.length === 0 && <Empty>Sin horarios cargados en {branch.name}.</Empty>}
      {here.length > 0 && (
        <ul className="list">
          {here.map((b) => (
            <li key={b.id}>
              {WEEKDAYS[b.weekday]} {b.start_time.slice(0, 5)}–{b.end_time.slice(0, 5)}{" "}
              {canEdit && (
                <button type="button" className="btn btn-small" disabled={action.busy} onClick={() => remove(b)}
                        aria-label={`Quitar ${WEEKDAYS[b.weekday]} ${b.start_time.slice(0, 5)}`}>
                  Quitar
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {elsewhere.length > 0 && (
        <>
          <h3 className="small">En otras sucursales</h3>
          <ul className="list muted">
            {elsewhere.map((b) => (
              <li key={b.id}>
                {WEEKDAYS[b.weekday]} {b.start_time.slice(0, 5)}–{b.end_time.slice(0, 5)} · {b.branch_name}{" "}
                {canRemoveElsewhere && (
                  <button type="button" className="btn btn-small" disabled={action.busy} onClick={() => remove(b)}
                          aria-label={`Quitar ${WEEKDAYS[b.weekday]} ${b.start_time.slice(0, 5)} en ${b.branch_name}`}>
                    Quitar
                  </button>
                )}
              </li>
            ))}
          </ul>
          {canEdit && (
            <p className="muted small">
              {canRemoveElsewhere
                ? "Para pasar un horario a esta sucursal, quitalo de la otra y agregalo acá."
                : "Esos horarios se cambian desde esa sucursal."}
            </p>
          )}
        </>
      )}
      {canEdit && (
      <form className="grid-form" onSubmit={add}>
        <Field label="Día">
          {(id) => (
            <select id={id} value={weekday} onChange={(e) => setWeekday(Number(e.target.value))}>
              {WEEKDAYS.slice(0, 6).map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
          )}
        </Field>
        <Field label="Desde">
          {(id) => <input id={id} type="time" required value={start} onChange={(e) => setStart(e.target.value)} />}
        </Field>
        <Field label="Hasta">
          {(id) => <input id={id} type="time" required value={end} onChange={(e) => setEnd(e.target.value)} />}
        </Field>
        <div className="form-actions">
          <button type="submit" className="btn" disabled={action.busy}>Agregar horario en {branch.name}</button>
        </div>
      </form>
      )}
    </Card>
  );
}
