// Página de una clínica en /sistema: resumen (solo cantidades, nunca pacientes), cuánto ocupa,
// qué funciones tiene habilitadas, el acceso (administradores y suspensión) y la exportación
// completa de sus datos (un .zip para entregarle a la clínica al terminar el contrato).
import { useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Field, Loading, SuccessBox } from "../components";
import { askConfirm } from "../confirm";
import { useAction, useAsync } from "../hooks";
import { AFFILIATION_LABELS, fmtDate, fmtDateTime, PATIENT_STATUS_LABELS, ROLE_LABELS } from "../labels";
import { navigate } from "../router";
import { AccessDialog } from "./shared";
import type { ClinicAdmin, ClinicSummary, TemporaryAccess } from "./types";

interface KeyCount { key: string; count: number }
interface PeriodCount { period: string; count: number }
interface TableUsage { table: string; label: string; rows: number; bytes: number }

export interface ClinicStorage {
  clinic_id: string; name: string; suspended: boolean; database_bytes: number; rows: number;
  files_count: number; files_bytes: number; tables: TableUsage[];
}

interface FeatureState { key: string; label: string; description: string; enabled: boolean }

interface ClinicDashboard {
  clinic: ClinicSummary;
  patients_total: number;
  patients_by_status: KeyCount[];
  patients_by_affiliation: KeyCount[];
  patients_by_branch: { name: string; is_active: boolean; active: number; total: number }[];
  new_patients_by_month: PeriodCount[];
  accounts_by_role: KeyCount[];
  accounts: { id: string; full_name: string; role: string; is_active: boolean; created_at: string;
    last_seen_at: string | null }[];
  logins_by_day: PeriodCount[];
  active_accounts_7d: number;
  active_accounts_30d: number;
  files: { patient_files: number; patient_files_withdrawn: number; patient_files_bytes: number;
    degrees: number; degrees_bytes: number };
  storage: ClinicStorage;
  features: FeatureState[];
}

const SECTIONS: [string, string][] = [
  ["resumen", "Resumen"], ["espacio", "Espacio"], ["funciones", "Funciones"], ["acceso", "Acceso"],
  ["exportar", "Exportar"],
];

const NUMBER = new Intl.NumberFormat("es-UY");
const DECIMAL = new Intl.NumberFormat("es-UY", { maximumFractionDigits: 1 });
const MONTHS = ["ene.", "feb.", "mar.", "abr.", "may.", "jun.", "jul.", "ago.", "set.", "oct.", "nov.", "dic."];

/** "12,3 MB" (en base 1024, como lo muestra la Mac en "Obtener información"). */
export function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${NUMBER.format(bytes)} bytes`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${DECIMAL.format(value)} ${units[unit]}`;
}

/** "12.894.208 bytes": el número exacto, para el detalle. */
export function exactBytes(bytes: number): string {
  return `${NUMBER.format(bytes)} bytes`;
}

function label(map: Record<string, string>, key: string): string {
  return map[key] ?? key;
}

function monthLabel(period: string): string {
  const [y, m] = period.split("-");
  return `${MONTHS[Number(m) - 1]} ${y.slice(2)}`;
}

export function ClinicPage({ clinicId, section }: { clinicId: string; section: string }) {
  const data = useAsync(() => api.get<ClinicDashboard>(`/owner/clinics/${clinicId}/dashboard`), [clinicId]);
  const current = SECTIONS.some(([key]) => key === section) ? section : "resumen";
  const d = data.data;

  return (
    <>
      <p className="small no-print"><a href="#/clinicas">← Todas las clínicas</a></p>
      <div className="page-title no-print">
        <h1>{d ? d.clinic.name : "Clínica"}</h1>
        {d && (d.clinic.purged_at ? <Badge tone="neutral">Datos borrados</Badge> : d.clinic.suspended_at
          ? <Badge tone="danger">Suspendida</Badge> : <Badge tone="ok">Activa</Badge>)}
        {d?.clinic.kind === "independent" && <Badge tone="info">Profesional independiente</Badge>}
      </div>
      {d && (
        <p className="muted small">
          Alta: {fmtDate(d.clinic.created_at.slice(0, 10))} · Último uso:{" "}
          {d.clinic.last_activity ? fmtDateTime(d.clinic.last_activity) : "nunca"} · Desde acá no se ven
          pacientes ni historia clínica: solo cantidades.
        </p>
      )}
      <nav className="page-tabs no-print" role="tablist" aria-label="Secciones de la clínica"
           hidden={Boolean(d?.clinic.purged_at)}>
        {SECTIONS.map(([key, text]) => (
          <button key={key} type="button" role="tab" aria-selected={current === key}
                  className={current === key ? "ptab active" : "ptab"}
                  onClick={() => navigate(`/clinicas/${clinicId}/${key}`)}>
            {text}
          </button>
        ))}
      </nav>
      <ErrorBox message={data.error} />
      {d?.clinic.purged_at ? <PurgeCertificate clinicId={clinicId} /> : data.loading && !d ? <Loading /> : d && (
        <div role="tabpanel">
          {current === "resumen" && <SummarySection d={d} />}
          {current === "espacio" && <StorageSection d={d} />}
          {current === "funciones" && <FeaturesSection clinic={d.clinic} features={d.features} onChanged={data.reload} />}
          {current === "acceso" && <AccessSection clinic={d.clinic} onChanged={data.reload} />}
          {current === "exportar" && <ExportSection d={d} />}
        </div>
      )}
    </>
  );
}

// ---------- Piezas de los gráficos (sin bibliotecas extra) ----------

export function Tile({ title, value, hint }: { title: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <section className="stat card">
      <div>
        <h2 className="stat-label">{title}</h2>
        <p className="stat-value">{value}</p>
        {hint && <p className="stat-hint">{hint}</p>}
      </div>
    </section>
  );
}

/** Barras horizontales: una por fila, con el valor escrito al lado (no depende del color). */
export function BarList({ items, format = (n) => NUMBER.format(n), empty = "Sin datos." }: {
  items: { label: ReactNode; value: number; key: string; title?: string }[];
  format?: (n: number) => string;
  empty?: string;
}) {
  const max = Math.max(0, ...items.map((i) => i.value));
  if (items.length === 0 || max === 0) return <p className="muted small">{empty}</p>;
  return (
    <ul className="bar-list">
      {items.map((i) => (
        <li key={i.key} title={i.title}>
          <span className="bar-label">{i.label}</span>
          <span className="bar-track" aria-hidden="true">
            <span className="bar-fill" style={{ width: `${Math.max((i.value / max) * 100, i.value > 0 ? 2 : 0)}%` }} />
          </span>
          <strong className="bar-value">{format(i.value)}</strong>
        </li>
      ))}
    </ul>
  );
}

/** Columnas por período (meses o días), con el detalle también como tabla. */
function ColumnChart({ items, caption, periodLabel }: {
  items: { period: string; label: string; value: number }[]; caption: string; periodLabel: string;
}) {
  const max = Math.max(0, ...items.map((i) => i.value));
  const total = items.reduce((n, i) => n + i.value, 0);
  return (
    <figure className="col-figure">
      <div className="col-chart" role="img"
           aria-label={`${caption}: ${NUMBER.format(total)} en total, máximo ${NUMBER.format(max)}.`}>
        {items.map((i) => (
          <div key={i.period} className="col" title={`${i.label}: ${NUMBER.format(i.value)}`}>
            <span className="col-fill" style={{ height: max ? `${Math.max((i.value / max) * 100, i.value > 0 ? 3 : 0)}%` : 0 }} />
          </div>
        ))}
      </div>
      <figcaption className="col-axis small muted">
        <span>{items[0]?.label}</span>
        <span>Máximo: {NUMBER.format(max)} · Total: {NUMBER.format(total)}</span>
        <span>{items[items.length - 1]?.label}</span>
      </figcaption>
      <details className="small">
        <summary>Ver como tabla</summary>
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">{periodLabel}</th><th scope="col">Cantidad</th></tr></thead>
            <tbody>
              {items.map((i) => <tr key={i.period}><td>{i.label}</td><td>{NUMBER.format(i.value)}</td></tr>)}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

// ---------- Resumen ----------

function SummarySection({ d }: { d: ClinicDashboard }) {
  const roles = Object.fromEntries(d.accounts_by_role.map((r) => [r.key, r.count]));
  const activeAccounts = d.accounts_by_role.reduce((n, r) => n + r.count, 0);
  const active = d.patients_by_status.find((s) => s.key === "active")?.count ?? 0;
  const statusLabels = PATIENT_STATUS_LABELS as Record<string, string>;
  const affiliationLabels = AFFILIATION_LABELS as Record<string, string>;
  const roleLabels = ROLE_LABELS as Record<string, string>;
  return (
    <>
      <div className="stats owner-stats">
        <Tile title="Pacientes activos" value={NUMBER.format(active)}
              hint={`de ${NUMBER.format(d.patients_total)} cargados en total`} />
        <Tile title="En pausa" value={NUMBER.format(d.clinic.paused_patients ?? 0)}
              hint={(d.clinic.paused_with_sessions ?? 0) > 0
                ? `${NUMBER.format(d.clinic.paused_with_sessions ?? 0)} tuvieron turnos realizados este mes: conviene revisarlo`
                : "ninguno tuvo turnos realizados este mes"} />
        <Tile title="Cuentas activas" value={NUMBER.format(activeAccounts)}
              hint={`${roles.admin ?? 0} de administración · ${roles.reception ?? 0} de recepción · ${roles.professional ?? 0} profesionales`} />
        <Tile title="Usaron Nordeste esta semana" value={NUMBER.format(d.active_accounts_7d)}
              hint={`cuentas en los últimos 7 días (${NUMBER.format(d.active_accounts_30d)} en 30 días)`} />
        <Tile title="Espacio que ocupa" value={fmtBytes(d.storage.database_bytes + d.storage.files_bytes)}
              hint="base de datos (estimado) + archivos adjuntos" />
      </div>

      <div className="home-grid">
        <Card title="Pacientes">
          <h3 className="section-label">Por estado</h3>
          <BarList items={d.patients_by_status.map((s) => ({ key: s.key, label: label(statusLabels, s.key), value: s.count }))}
                   empty="Todavía no hay pacientes." />
          <h3 className="section-label">Activos por afiliación</h3>
          <BarList items={d.patients_by_affiliation.map((s) => ({ key: s.key, label: label(affiliationLabels, s.key), value: s.count }))}
                   empty="No hay pacientes activos." />
          <h3 className="section-label">Por sucursal</h3>
          {d.patients_by_branch.length === 0 ? <p className="muted small">No tiene sucursales.</p> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th scope="col">Sucursal</th><th scope="col">Activos</th><th scope="col">Total</th></tr></thead>
                <tbody>
                  {d.patients_by_branch.map((b) => (
                    <tr key={b.name} className={b.is_active ? undefined : "row-muted"}>
                      <td>{b.name}{!b.is_active && <> <Badge tone="neutral">Desactivada</Badge></>}</td>
                      <td>{NUMBER.format(b.active)}</td>
                      <td>{NUMBER.format(b.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <div className="owner-column">
          <Card title="Pacientes nuevos por mes">
            <p className="muted small card-sub">Altas de los últimos 12 meses</p>
            <ColumnChart caption="Pacientes nuevos por mes" periodLabel="Mes"
                         items={d.new_patients_by_month.map((m) => ({ period: m.period, label: monthLabel(m.period), value: m.count }))} />
          </Card>
          <Card title="Ingresos a Nordeste">
            <p className="muted small card-sub">Inicios de sesión por día, últimos 30 días</p>
            <ColumnChart caption="Inicios de sesión por día" periodLabel="Día"
                         items={d.logins_by_day.map((x) => ({ period: x.period, label: fmtDate(x.period), value: x.count }))} />
          </Card>
        </div>
      </div>

      <Card title="Cuentas de la clínica">
        <p className="muted small card-sub">Primero las que entraron más recientemente.</p>
        {d.accounts.length === 0 ? <Empty>No tiene cuentas.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Nombre</th><th scope="col">Rol</th><th scope="col">Estado</th>
                  <th scope="col">Último ingreso</th><th scope="col">Alta</th>
                </tr>
              </thead>
              <tbody>
                {d.accounts.map((a) => (
                  <tr key={a.id} className={a.is_active ? undefined : "row-muted"}>
                    <td>{a.full_name}</td>
                    <td>{label(roleLabels, a.role)}</td>
                    <td>{a.is_active ? <Badge tone="ok">Activa</Badge> : <Badge tone="neutral">Desactivada</Badge>}</td>
                    <td>{a.last_seen_at ? fmtDateTime(a.last_seen_at) : <span className="muted">Nunca</span>}</td>
                    <td>{fmtDate(a.created_at.slice(0, 10))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

// ---------- Espacio de la clínica ----------

function StorageSection({ d }: { d: ClinicDashboard }) {
  const s = d.storage;
  const f = d.files;
  return (
    <>
      <div className="stats owner-stats">
        <Tile title="En la base de datos" value={fmtBytes(s.database_bytes)}
              hint={<>{exactBytes(s.database_bytes)} · estimado</>} />
        <Tile title="Archivos adjuntos" value={fmtBytes(s.files_bytes)}
              hint={<>{exactBytes(s.files_bytes)} · {NUMBER.format(s.files_count)} archivos</>} />
        <Tile title="Total" value={fmtBytes(s.database_bytes + s.files_bytes)}
              hint={exactBytes(s.database_bytes + s.files_bytes)} />
        <Tile title="Filas guardadas" value={NUMBER.format(s.rows)} hint="registros de la clínica en todas las tablas" />
      </div>
      <Card title="En la base de datos, por tipo de dato">
        <p className="muted small card-sub">
          Todas las clínicas comparten las mismas tablas, así que el tamaño de cada una es una
          estimación: el tamaño real de cada tabla (con sus índices) se reparte según cuánto ocupan
          las filas de cada clínica.
        </p>
        {s.tables.length === 0 ? <Empty>Todavía no tiene datos.</Empty> : (
          <div className="table-wrap">
            <table className="storage-table">
              <thead>
                <tr>
                  <th scope="col">Dato</th><th scope="col">Filas</th><th scope="col">Tamaño</th>
                  <th scope="col">Bytes</th><th scope="col"><span className="sr-only">Proporción</span></th>
                </tr>
              </thead>
              <tbody>
                {s.tables.map((t) => (
                  <tr key={t.table}>
                    <td>{t.label}</td>
                    <td>{NUMBER.format(t.rows)}</td>
                    <td>{fmtBytes(t.bytes)}</td>
                    <td className="muted small">{NUMBER.format(t.bytes)}</td>
                    <td className="bar-cell" aria-hidden="true">
                      <span className="bar-track">
                        <span className="bar-fill" style={{ width: `${s.database_bytes ? (t.bytes / s.database_bytes) * 100 : 0}%` }} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Archivos adjuntos">
        <p className="muted small card-sub">
          Los PDF e imágenes se guardan en el disco del servidor, fuera de la base. Los retirados no se
          borran: siguen ocupando lugar.
        </p>
        <dl className="details">
          <dt>Archivos de pacientes</dt>
          <dd>{NUMBER.format(f.patient_files)} visibles · {NUMBER.format(f.patient_files_withdrawn)} retirados · {fmtBytes(f.patient_files_bytes)}</dd>
          <dt>Títulos de profesionales</dt>
          <dd>{NUMBER.format(f.degrees)} · {fmtBytes(f.degrees_bytes)}</dd>
        </dl>
      </Card>
    </>
  );
}

// ---------- Funciones ----------

function FeaturesSection({ clinic, features, onChanged }: {
  clinic: ClinicSummary; features: FeatureState[]; onChanged: () => void;
}) {
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const on = features.filter((f) => f.enabled).length;

  async function toggle(f: FeatureState) {
    const enable = !f.enabled;
    const question = enable
      ? `¿Habilitar ${f.label} para ${clinic.name}? Vuelve a aparecer en su menú con todo lo que tenía guardado.`
      : `¿Deshabilitar ${f.label} para ${clinic.name}? Desaparece de su menú y nadie de la clínica la puede usar. ` +
        "No se borra ningún dato: si la volvés a habilitar, todo sigue como estaba.";
    if (!await askConfirm(question, { confirmLabel: enable ? "Habilitar" : "Deshabilitar" })) return;
    setBusyKey(f.key);
    setError(null);
    try {
      await api.put(`/owner/clinics/${clinic.id}/features/${f.key}`, { enabled: enable });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cambiar la función.");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <Card title="Funciones de la clínica">
      <p className="muted small card-sub">
        {on} de {features.length} habilitadas. Pacientes, Agenda, Historia clínica, Informes, Usuarios y
        Auditoría están siempre. Los cambios se aplican al momento (quien esté adentro los ve al
        recargar la página) y quedan en tu auditoría y en la de la clínica.
      </p>
      <ErrorBox message={error} />
      <ul className="feature-list">
        {features.map((f) => (
          <li key={f.key}>
            <div>
              <strong>{f.label}</strong>{" "}
              {f.enabled ? <Badge tone="ok">Habilitada</Badge> : <Badge tone="neutral">Deshabilitada</Badge>}
              <p className="muted small">{f.description}</p>
            </div>
            <button type="button" className={f.enabled ? "btn btn-small" : "btn btn-small btn-primary"}
                    disabled={busyKey !== null} onClick={() => toggle(f)}>
              {busyKey === f.key ? "Guardando…" : f.enabled ? "Deshabilitar" : "Habilitar"}
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ---------- Acceso: administradores y suspensión ----------

function AccessSection({ clinic, onChanged }: { clinic: ClinicSummary; onChanged: () => void }) {
  const [reason, setReason] = useState("");
  const [suspending, setSuspending] = useState(false);
  const [access, setAccess] = useState<TemporaryAccess | null>(null);
  const { busy, error, run } = useAction();
  const independent = clinic.kind === "independent";

  async function suspend(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => { await api.post(`/owner/clinics/${clinic.id}/suspend`, { reason }); });
    if (ok) { setSuspending(false); setReason(""); onChanged(); }
  }

  async function reactivate() {
    if (!await askConfirm(`¿Reactivar el acceso a ${clinic.name}? Sus cuentas van a poder entrar de nuevo.`,
      { confirmLabel: "Reactivar" })) return;
    const ok = await run(async () => { await api.post(`/owner/clinics/${clinic.id}/reactivate`); });
    if (ok) onChanged();
  }

  async function resetAdmin(admin: ClinicAdmin) {
    if (!await askConfirm(
      `¿Dar una contraseña temporal a ${admin.full_name}? Su contraseña actual deja de servir, se cierran sus ` +
      "sesiones y, si estaba desactivada o bloqueada, la cuenta vuelve a funcionar.",
      { confirmLabel: "Restablecer contraseña" })) return;
    await run(async () => {
      const r = await api.post<TemporaryAccess>(`/owner/clinics/${clinic.id}/admins/${admin.id}/reset-password`);
      onChanged();
      setAccess(r);
    });
  }

  return (
    <>
      <ErrorBox message={error} />
      <Card title={independent ? "Profesional del consultorio" : "Administración de la clínica"}>
        {clinic.admins.length === 0 ? (
          <p className="small muted">{independent ? "No tiene la cuenta del profesional." : "No tiene cuentas de Administración."}</p>
        ) : (
          <ul className="owner-admins">
            {clinic.admins.map((a) => (
              <li key={a.id}>
                <span>
                  <strong>{a.full_name}</strong> <span className="muted small">{a.email}</span>{" "}
                  {!a.is_active && <Badge tone="neutral">Desactivada</Badge>}{" "}
                  {a.locked && <Badge tone="warn">Bloqueada por intentos</Badge>}{" "}
                  {a.must_change_password && <Badge tone="info">Con contraseña temporal</Badge>}
                </span>
                <button type="button" className="btn btn-small" disabled={busy} onClick={() => resetAdmin(a)}>
                  Restablecer contraseña
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Acceso a la clínica">
        {clinic.suspended_at ? (
          <p className="small">
            Suspendida desde el {fmtDateTime(clinic.suspended_at)}. Nadie de la clínica puede entrar. No se
            borró nada: al reactivarla todo sigue como estaba.{" "}
            <button type="button" className="btn btn-small" disabled={busy} onClick={reactivate}>Reactivar</button>
          </p>
        ) : suspending ? (
          <form onSubmit={suspend}>
            <p className="small">
              Se cierran todas las sesiones abiertas y nadie de la clínica puede entrar hasta que la reactives.
              No se borra ningún dato.
            </p>
            <Field label="Motivo (opcional)" hint="Queda en tu auditoría. Por ejemplo: falta de pago.">
              {(id, hint) => <input id={id} aria-describedby={hint} maxLength={300} value={reason}
                                    onChange={(e) => setReason(e.target.value)} data-autofocus />}
            </Field>
            <div className="form-actions">
              <button type="button" className="btn" onClick={() => setSuspending(false)} disabled={busy}>Cancelar</button>
              <button type="submit" className="btn btn-danger" disabled={busy}>
                {busy ? "Suspendiendo…" : "Suspender el acceso"}
              </button>
            </div>
          </form>
        ) : (
          <p className="small">
            <button type="button" className="btn btn-danger" onClick={() => setSuspending(true)}>Suspender el acceso…</button>
          </p>
        )}
      </Card>
      {independent && <ConvertCard clinic={clinic} onChanged={onChanged} />}
      <PurgeCard clinic={clinic} />
      {access && <AccessDialog title="Contraseña restablecida" data={access} who={independent ? "Profesional" : undefined}
                               onClose={() => setAccess(null)} />}
    </>
  );
}

// ---------- Exportar: copia completa de los datos de la clínica ----------

/** "Clínica  Aurora" y "clínica aurora" son el mismo nombre (como lo compara el servidor). */
function sameName(a: string, b: string): boolean {
  const norm = (s: string) => s.trim().replace(/\s+/g, " ").toLocaleLowerCase("es");
  return norm(a) === norm(b);
}

interface ExportReady {
  download_url: string; filename: string; size_bytes: number; patients: number; files: number;
  missing_files: number;
}

function ExportSection({ d }: { d: ClinicDashboard }) {
  const clinic = d.clinic;
  const [reason, setReason] = useState("");
  const [confirmName, setConfirmName] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const ready = reason.trim().length >= 3 && sameName(confirmName, clinic.name);
  const files = d.files.patient_files + d.files.patient_files_withdrawn + d.files.degrees;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setDone(null);
    await run(async () => {
      const r = await api.post<ExportReady>(`/owner/clinics/${clinic.id}/export`,
        { reason: reason.trim(), confirm_name: confirmName });
      // El navegador lo baja directo a Descargas (sin pasar por la memoria de la página).
      const link = document.createElement("a");
      link.href = r.download_url;
      link.download = r.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setDone(`Listo: «${r.filename}» (${fmtBytes(r.size_bytes)}) se está bajando a tu carpeta Descargas. ` +
        "El enlace sirve una sola vez: si la descarga se corta, generalo de nuevo. Quedó registrado en tu " +
        "auditoría y en la de la clínica." +
        (r.missing_files > 0 ? ` Atención: ${r.missing_files} archivos no estaban en el servidor (el LEEME dice cuáles).` : ""));
      setReason("");
      setConfirmName("");
    });
  }

  return (
    <Card title="Exportación completa de los datos">
      <p className="small">
        Genera un archivo .zip con <strong>todos</strong> los datos de {clinic.name} y nada de otras clínicas:
        pacientes, responsables, instituciones, turnos, historia clínica (con sus correcciones), anamnesis,
        antecedentes, diagnóstico, encuadre, abordajes, informes, objetivos, caja, usuarios (sin contraseñas),
        sucursales, auditoría y los archivos adjuntos ordenados por paciente. Trae planillas Excel, los mismos
        datos en CSV, documentos para imprimir o guardar como PDF y un LEEME que explica cada carpeta.
      </p>
      <p className="small muted">
        Hoy tiene {NUMBER.format(d.patients_total)} pacientes cargados y {NUMBER.format(files)} archivos
        ({fmtBytes(d.files.patient_files_bytes + d.files.degrees_bytes)}). Con muchos archivos puede tardar
        unos minutos.
      </p>
      <div className="alert alert-warn small" role="note">
        <strong>Contiene datos personales y de salud.</strong> Es la única función de /sistema que entrega
        datos de pacientes. Guardá el archivo en un lugar seguro, entregalo en persona o por un medio cifrado
        (no por correo común) y borrá tu copia después de entregarlo.
      </div>
      <ErrorBox message={error} />
      <SuccessBox message={done} />
      <form onSubmit={submit}>
        <Field label="Motivo" required hint="Queda en tu auditoría. Por ejemplo: fin del contrato, pedido de la clínica.">
          {(id, hint) => <input id={id} aria-describedby={hint} maxLength={300} value={reason} required
                                onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <Field label="Para confirmar, escribí el nombre de la clínica" required hint={`Tal como aparece arriba: ${clinic.name}`}>
          {(id, hint) => <input id={id} aria-describedby={hint} maxLength={200} value={confirmName} required
                                autoComplete="off" onChange={(e) => setConfirmName(e.target.value)} />}
        </Field>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy || !ready}>
            {busy ? "Generando el archivo…" : "Generar y descargar"}
          </button>
        </div>
      </form>
    </Card>
  );
}

// ---------- Convertir un espacio independiente en clínica ----------

function ConvertCard({ clinic, onChanged }: { clinic: ClinicSummary; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ admin_full_name: "", admin_email: "", admin_document: "", confirm_name: "" });
  const [enableFeatures, setEnableFeatures] = useState(true);
  const [access, setAccess] = useState<TemporaryAccess | null>(null);
  const { busy, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!await askConfirm(`¿Convertir ${clinic.name} en una clínica? Se crea la cuenta de Administración y ` +
      "no se puede volver a espacio independiente desde la pantalla.", { confirmLabel: "Convertir en clínica" })) return;
    await run(async () => {
      const r = await api.post<{ admin: TemporaryAccess }>(`/owner/clinics/${clinic.id}/convert-to-clinic`,
        { ...form, enable_features: enableFeatures });
      setAccess(r.admin);
      setOpen(false);
    });
  }

  return (
    <Card title="Convertir en clínica">
      <p className="small">
        Para cuando el profesional suma gente (secretaria, otros profesionales). Se crea la primera cuenta de
        <strong> Administración</strong>, que después crea las demás cuentas. Los pacientes, la historia clínica y la
        cuenta del profesional quedan como están: el profesional sigue siendo profesional y responsable de sus
        pacientes. Administración tiene que usar <strong>otro correo</strong> (una cuenta tiene un solo rol).
      </p>
      <ErrorBox message={error} />
      {!open ? (
        <p className="small"><button type="button" className="btn" onClick={() => setOpen(true)}>Convertir en clínica…</button></p>
      ) : (
        <form onSubmit={submit} className="grid-form">
          <Field label="Nombre de quien administra" required>
            {(id) => <input id={id} value={form.admin_full_name} onChange={set("admin_full_name")} required maxLength={200} data-autofocus />}
          </Field>
          <Field label="Correo" required hint="Distinto del correo del profesional.">
            {(id, hint) => <input id={id} aria-describedby={hint} type="email" value={form.admin_email}
                                  onChange={set("admin_email")} required maxLength={254} />}
          </Field>
          <Field label="C.I." required>
            {(id) => <input id={id} value={form.admin_document} onChange={set("admin_document")} required maxLength={30} />}
          </Field>
          <Field label="Para confirmar, escribí el nombre del consultorio" required hint={clinic.name}>
            {(id, hint) => <input id={id} aria-describedby={hint} value={form.confirm_name} onChange={set("confirm_name")}
                                  required autoComplete="off" maxLength={200} />}
          </Field>
          <label className="checkbox span-all">
            <input type="checkbox" checked={enableFeatures} onChange={(e) => setEnableFeatures(e.target.checked)} />
            Prender todas las funciones (Caja, Avisos, BPS y AYEX), como en cualquier clínica nueva
          </label>
          <div className="form-actions span-all">
            <button type="button" className="btn" onClick={() => setOpen(false)} disabled={busy}>Cancelar</button>
            <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Convirtiendo…" : "Convertir en clínica"}</button>
          </div>
        </form>
      )}
      {access && <AccessDialog title="Ya es una clínica" data={access} onClose={() => { setAccess(null); onChanged(); }} />}
    </Card>
  );
}

// ---------- Borrar todos los datos de la clínica ----------

interface PurgeStatus {
  purged_at: string | null; suspended_at: string | null; min_days: number; can_purge_from: string | null;
  days_left: number | null; export_after_suspension: boolean; patients: number; blockers: string[];
}

interface Certificate {
  clinic_name: string; independent: boolean; purged_at: string; purged_by: string | null; reason: string | null;
  counts: { label: string; count: number }[]; files_deleted: number; backup_name: string | null; backups_gone_by: string;
}

function PurgeCard({ clinic }: { clinic: ClinicSummary }) {
  const status = useAsync(() => api.get<PurgeStatus>(`/owner/clinics/${clinic.id}/purge-status`), [clinic.id, clinic.suspended_at]);
  const [form, setForm] = useState({ confirm_text: "", code: "", reason: "" });
  const { busy, error, run } = useAction();
  const s = status.data;
  const expected = `BORRAR ${clinic.name}`;
  const typed = form.confirm_text.trim().replace(/\s+/g, " ").toLocaleLowerCase("es") ===
    expected.replace(/\s+/g, " ").toLocaleLowerCase("es");
  const needsReason = s ? !s.export_after_suspension : true;
  const ready = typed && /^\d{6}$/.test(form.code.replace(/\s/g, "")) && (!needsReason || form.reason.trim().length >= 3);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !s) return;
    if (!await askConfirm(`Última confirmación: se van a BORRAR todos los datos de ${clinic.name} ` +
      `(${NUMBER.format(s.patients)} pacientes, su historia clínica, cuentas y archivos). Antes se hace una copia de ` +
      "seguridad. Esto no se puede deshacer desde Nordeste.", { confirmLabel: "Borrar todos los datos", danger: true })) return;
    const ok = await run(async () => {
      await api.post(`/owner/clinics/${clinic.id}/purge`, { ...form, code: form.code.replace(/\s/g, "") });
    });
    if (ok) window.location.reload();
  }

  return (
    <Card title="Borrar todos los datos">
      <p className="small">
        Para cuando la clínica dejó Nordeste y ya recibió sus datos. Borra pacientes, historia clínica, informes, turnos,
        caja, cuentas, auditoría y archivos de {clinic.name}; queda solo su nombre en tu lista y en tu auditoría.
        Antes se hace una copia de seguridad completa automática.
      </p>
      <ErrorBox message={status.error ?? error} />
      {!s ? <Loading /> : s.blockers.length > 0 ? (
        <p className="small muted">
          {s.blockers.join(" ")}
          {s.can_purge_from && s.days_left ? ` Se va a poder desde el ${fmtDate(s.can_purge_from.slice(0, 10))} (faltan ${s.days_left} días).` : ""}
        </p>
      ) : (
        <form onSubmit={submit}>
          {s.export_after_suspension ? (
            <SuccessBox message="Se generó una exportación completa después de suspenderla." />
          ) : (
            <div className="alert alert-warn small" role="note">
              No hay una exportación generada después de suspenderla. Si la clínica pidió sus datos, generala primero
              (pestaña Exportar). Si no los quiere, escribí el motivo.
            </div>
          )}
          {needsReason && (
            <Field label="Motivo por el que se borra sin entregar los datos" required>
              {(id) => <input id={id} value={form.reason} maxLength={300} required
                              onChange={(e) => setForm({ ...form, reason: e.target.value })} />}
            </Field>
          )}
          <Field label={`Para confirmar, escribí: ${expected}`} required>
            {(id) => <input id={id} value={form.confirm_text} autoComplete="off" maxLength={220} required
                            onChange={(e) => setForm({ ...form, confirm_text: e.target.value })} />}
          </Field>
          <Field label="Código del celular" required hint="El de 6 dígitos de tu app, como al entrar.">
            {(id, hint) => <input id={id} aria-describedby={hint} inputMode="numeric" autoComplete="one-time-code"
                                  value={form.code} maxLength={7} required
                                  onChange={(e) => setForm({ ...form, code: e.target.value })} />}
          </Field>
          <div className="form-actions">
            <button type="submit" className="btn btn-danger" disabled={busy || !ready}>
              {busy ? "Haciendo la copia y borrando… puede tardar unos minutos" : "Borrar todos los datos"}
            </button>
          </div>
        </form>
      )}
    </Card>
  );
}

function PurgeCertificate({ clinicId }: { clinicId: string }) {
  const cert = useAsync(() => api.get<Certificate>(`/owner/clinics/${clinicId}/purge-certificate`), [clinicId]);
  const c = cert.data;
  return (
    <Card title="Constancia de borrado de datos">
      <ErrorBox message={cert.error} />
      {!c ? <Loading /> : (
        <>
          <p>
            Se borraron de Nordeste todos los datos {c.independent ? "del consultorio" : "de la clínica"}{" "}
            <strong>{c.clinic_name}</strong> el {fmtDateTime(c.purged_at)}
            {c.purged_by ? `, por ${c.purged_by} (responsable de Nordeste)` : ""}.
          </p>
          {c.reason && <p className="small">Motivo: {c.reason}</p>}
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">Dato</th><th scope="col">Cantidad borrada</th></tr></thead>
              <tbody>
                {c.counts.map((row) => <tr key={row.label}><td>{row.label}</td><td>{NUMBER.format(row.count)}</td></tr>)}
                <tr><td>Archivos (adjuntos y títulos) borrados del disco</td><td>{NUMBER.format(c.files_deleted)}</td></tr>
              </tbody>
            </table>
          </div>
          <p className="small">
            Las copias de seguridad anteriores, que todavía contienen estos datos, se renuevan solas: a partir del{" "}
            <strong>{fmtDate(c.backups_gone_by.slice(0, 10))}</strong> ya no queda ninguna copia con ellos.
            {c.backup_name && <> Copia hecha justo antes de borrar: {c.backup_name}.</>}
          </p>
          <p className="small no-print">
            <button type="button" className="btn" onClick={() => window.print()}>Imprimir o guardar como PDF</button>
          </p>
        </>
      )}
    </Card>
  );
}

