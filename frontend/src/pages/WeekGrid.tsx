// Agenda en grilla: horas en filas y una columna por día (vista semanal de un profesional)
// o por profesional (vista diaria de la sucursal).
// Muestra la disponibilidad sombreada y los turnos a su hora; un clic en un hueco libre
// propone esa hora para un turno nuevo.
import type { ReactNode } from "react";
import { APPOINTMENT_STATUS_LABELS, WEEKDAYS } from "../labels";
import type { Appointment, AvailabilityBlock } from "../types";

const PX_PER_MIN = 1; // 60 px por hora
const SLOT_MIN = 30;

function minutesOf(time: string): number {
  const [h, m] = time.split(":").map(Number);
  return h * 60 + m;
}

function localMinutes(iso: string): number {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

function hhmm(min: number): string {
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
}

/** Reparte turnos que se superponen en columnas (para sesiones con varios pacientes). */
function lanes(list: Appointment[]): Map<string, { lane: number; of: number }> {
  const sorted = [...list].sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  const result = new Map<string, { lane: number; of: number }>();
  let group: Appointment[] = [];
  let groupEnd = "";
  const flush = () => {
    const ends: string[] = [];
    for (const a of group) {
      let lane = ends.findIndex((e) => e <= a.starts_at);
      if (lane === -1) { lane = ends.length; ends.push(a.ends_at); } else { ends[lane] = a.ends_at; }
      result.set(a.id, { lane, of: 1 });
    }
    for (const a of group) result.get(a.id)!.of = ends.length;
    group = [];
    groupEnd = "";
  };
  for (const a of sorted) {
    if (group.length && a.starts_at >= groupEnd) flush();
    group.push(a);
    if (a.ends_at > groupEnd) groupEnd = a.ends_at;
  }
  if (group.length) flush();
  return result;
}

// En la grilla no se dibujan los cancelados ni los reprogramados (siguen en la vista de lista).
const HIDDEN = new Set(["cancelled", "rescheduled"]);

export interface GridColumn {
  key: string;
  title: ReactNode;
  highlight?: boolean;
  appointments: Appointment[];
  blocks: AvailabilityBlock[]; // horarios disponibles de esa columna
  slotLabel: (time: string) => string; // texto para lectores de pantalla
  /** Al tocar un hueco libre. Sin esto, los huecos se ven pero no se pueden tocar
   * (por ejemplo, la columna de un compañero para un profesional). */
  onPick?: (time: string) => void;
}

export function TimeGrid({ columns, selectedId, onSelect, label, minColumnWidth = 110 }: {
  columns: GridColumn[];
  selectedId: string | null;
  onSelect: (appt: Appointment) => void;
  label: string;
  minColumnWidth?: number;
}) {
  const visible = columns.map((c) => c.appointments.filter((a) => !HIDDEN.has(a.status)));
  // Rango de horas: lo que cubre la disponibilidad y los turnos, como mínimo 08:00–20:00.
  let from = 8 * 60;
  let to = 20 * 60;
  for (const c of columns) {
    for (const b of c.blocks) {
      from = Math.min(from, minutesOf(b.start_time));
      to = Math.max(to, minutesOf(b.end_time));
    }
  }
  for (const list of visible) {
    for (const a of list) {
      from = Math.min(from, localMinutes(a.starts_at));
      to = Math.max(to, localMinutes(a.ends_at) || 24 * 60);
    }
  }
  from = Math.floor(from / 60) * 60;
  to = Math.ceil(to / 60) * 60;
  const height = (to - from) * PX_PER_MIN;
  const hours: number[] = [];
  for (let m = from; m < to; m += 60) hours.push(m);

  return (
    <div className="week-grid" role="grid" aria-label={label}
         style={{
           gridTemplateColumns: `3.2rem repeat(${columns.length}, minmax(${minColumnWidth}px, 1fr))`,
           minWidth: `calc(3.2rem + ${columns.length * minColumnWidth}px)`,
         }}>
      <div className="wg-head wg-corner" />
      {columns.map((c) => (
        <div key={c.key} className={c.highlight ? "wg-head today" : "wg-head"}>{c.title}</div>
      ))}
      <div className="wg-hours" style={{ height }}>
        {hours.map((m) => (
          <span key={m} style={{ top: (m - from) * PX_PER_MIN }}>{hhmm(m)}</span>
        ))}
      </div>
      {columns.map((c, i) => {
        const list = visible[i];
        const placed = lanes(list);
        const slots: number[] = [];
        for (const b of c.blocks) {
          for (let m = minutesOf(b.start_time); m + SLOT_MIN <= minutesOf(b.end_time); m += SLOT_MIN) slots.push(m);
        }
        return (
          <div key={c.key} className="wg-day" style={{ height }}>
            {hours.map((m) => <div key={m} className="wg-line" style={{ top: (m - from) * PX_PER_MIN }} />)}
            {c.blocks.map((b) => (
              <div key={b.id} className="wg-available" aria-hidden="true"
                   style={{ top: (minutesOf(b.start_time) - from) * PX_PER_MIN,
                            height: (minutesOf(b.end_time) - minutesOf(b.start_time)) * PX_PER_MIN }} />
            ))}
            {c.onPick && slots.map((m) => (
              <button key={m} type="button" className="wg-slot"
                      style={{ top: (m - from) * PX_PER_MIN, height: SLOT_MIN * PX_PER_MIN }}
                      aria-label={c.slotLabel(hhmm(m))}
                      onClick={() => c.onPick?.(hhmm(m))} />
            ))}
            {list.map((a) => {
              const start = localMinutes(a.starts_at);
              const end = localMinutes(a.ends_at) || 24 * 60;
              const pos = placed.get(a.id) ?? { lane: 0, of: 1 };
              return (
                <button key={a.id} type="button"
                        className={`wg-appt st-${a.status}${selectedId === a.id ? " selected" : ""}`}
                        style={{
                          top: (start - from) * PX_PER_MIN,
                          height: Math.max((end - start) * PX_PER_MIN, 20),
                          left: `calc(${(pos.lane / pos.of) * 100}% + 2px)`,
                          width: `calc(${100 / pos.of}% - 4px)`,
                        }}
                        title={`${hhmm(start)}–${hhmm(end)} · ${a.patient_name} · ${APPOINTMENT_STATUS_LABELS[a.status]}`}
                        onClick={() => onSelect(a)}>
                  <strong>{hhmm(start)}</strong> <span className="wg-name">{a.patient_name}</span>
                </button>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

interface WeekProps {
  weekStart: Date;
  byDay: Appointment[][];
  availability: AvailabilityBlock[];
  selectedId: string | null;
  onSelect: (appt: Appointment) => void;
  /** Sin esto, los huecos libres no se pueden tocar (quien no da turnos). */
  onPickSlot?: (day: Date, time: string) => void;
}

/** ¿Se muestra ese día? Sábado y domingo solo si hay horario o algún turno (la clínica
 * suele cerrar): así las columnas de lunes a viernes son más anchas. */
export function showWeekday(i: number, blocks: AvailabilityBlock[], appointments: Appointment[]): boolean {
  if (i < 5) return true;
  return blocks.some((b) => b.weekday === i) || appointments.some((a) => !HIDDEN.has(a.status));
}

/** Semana de un profesional: una columna por día. */
export function WeekGrid({ weekStart, byDay, availability, selectedId, onSelect, onPickSlot }: WeekProps) {
  const today = new Date().toDateString();
  const columns: GridColumn[] = WEEKDAYS.flatMap((name, i) => {
    if (!showWeekday(i, availability, byDay[i] ?? [])) return [];
    const day = new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate() + i);
    return [{
      key: name,
      title: <>{name.slice(0, 3)} <small>{day.toLocaleDateString("es-UY", { day: "2-digit", month: "2-digit" })}</small></>,
      highlight: day.toDateString() === today,
      appointments: byDay[i] ?? [],
      blocks: availability.filter((b) => b.weekday === i),
      slotLabel: (time) => `Dar turno el ${name} a las ${time}`,
      onPick: onPickSlot ? (time) => onPickSlot(day, time) : undefined,
    }];
  });
  return <TimeGrid columns={columns} selectedId={selectedId} onSelect={onSelect} label="Agenda semanal en grilla" />;
}

/** Qué significa cada color de la grilla. */
export function GridLegend() {
  return (
    <ul className="grid-legend" aria-label="Colores de la grilla">
      <li><span className="key free" aria-hidden="true" />Horario disponible</li>
      <li><span className="key st-scheduled" aria-hidden="true" />{APPOINTMENT_STATUS_LABELS.scheduled}</li>
      <li><span className="key st-completed" aria-hidden="true" />{APPOINTMENT_STATUS_LABELS.completed}</li>
      <li><span className="key st-no_show" aria-hidden="true" />{APPOINTMENT_STATUS_LABELS.no_show}</li>
    </ul>
  );
}
