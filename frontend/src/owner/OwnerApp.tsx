// Pantalla del dueño del sistema (lumengestion.uy/sistema): clínicas (resumen, espacio, funciones y
// acceso), alta, suspensión y auditoría. Sesión aparte de las clínicas y SIN datos de pacientes.
import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { api, ApiError, setCsrfToken, setUnauthorizedHandler } from "../api";
import { Badge, Card, Empty, ErrorBox, Field, Loading, Logo, SuccessBox, WarnBox } from "../components";
import { useAction, useAsync } from "../hooks";
import { FEATURE_LABELS, fmtDate, fmtDateTime, OWNER_ACTION_LABELS } from "../labels";
import { ChangePasswordForm } from "../pages/AccountPage";
import { navigate, useRoute } from "../router";
import { ClinicPage } from "./ClinicPage";
import { AccessDialog, CopyButton } from "./shared";
import { StoragePage } from "./StoragePage";
import type { ClinicSummary, TemporaryAccess } from "./types";

interface OwnerSession {
  owner: { email: string; full_name: string; must_change_password: boolean; totp_enabled: boolean };
  csrf_token: string;
  idle_minutes: number;
}

interface OwnerAuditRow {
  id: number; created_at: string; owner_name: string | null; action: string; clinic_name: string | null;
  target_name: string | null; details: Record<string, unknown>; ip: string | null;
}

type Notice = { text: string; tone: "ok" | "warn" } | null;

export function OwnerApp() {
  const [info, setInfo] = useState<OwnerSession | null>(null);
  const [checking, setChecking] = useState(true);
  const [notice, setNotice] = useState<Notice>(null);

  const apply = useCallback((next: OwnerSession | null) => {
    setCsrfToken(next ? next.csrf_token : null);
    setInfo(next);
  }, []);
  const refresh = useCallback(() => api.get<OwnerSession>("/owner/auth/me").then(apply), [apply]);

  useEffect(() => {
    document.title = "Lumen · Dueño del sistema";
    // Primero se comprueba si ya hay sesión; recién después un 401 significa "expiró".
    refresh()
      .catch((err) => {
        if (!(err instanceof ApiError && err.status === 401)) setNotice({ text: err.message, tone: "warn" });
      })
      .finally(() => {
        setChecking(false);
        setUnauthorizedHandler(() => {
          apply(null);
          setNotice({ text: "Tu sesión expiró. Iniciá sesión nuevamente.", tone: "warn" });
        });
      });
    return () => setUnauthorizedHandler(null);
  }, [apply, refresh]);

  const logout = useCallback(() => {
    api.post("/owner/auth/logout").catch(() => undefined).finally(() => {
      apply(null);
      setNotice({ text: "Cerraste sesión.", tone: "ok" });
    });
  }, [apply]);

  if (checking) return <main className="center"><Loading /></main>;
  if (!info) return <OwnerLogin notice={notice} onLogin={(s) => { setNotice(null); apply(s); }} />;
  if (info.owner.must_change_password) {
    return (
      <SetupCard title="Elegí una contraseña nueva" onLogout={logout}>
        <p className="small">
          Hola, {info.owner.full_name}. Entraste con la contraseña temporal del servidor. Elegí una
          contraseña nueva, larga y que no uses en ningún otro lado.
        </p>
        <ChangePasswordForm currentLabel="Contraseña temporal" endpoint="/owner/auth/change-password"
                            onChanged={() => { refresh().catch(logout); }} />
      </SetupCard>
    );
  }
  if (!info.owner.totp_enabled) {
    return (
      <SetupCard title="Configurá el código del celular" onLogout={logout}>
        <TotpSetup onDone={() => { refresh().catch(logout); }} />
      </SetupCard>
    );
  }
  return <OwnerShell name={info.owner.full_name} onLogout={logout} />;
}

function SetupCard({ title, onLogout, children }: { title: string; onLogout: () => void; children: ReactNode }) {
  return (
    <main className="login">
      <div className="login-card owner-setup">
        <Card title={title}>
          {children}
          <p className="small"><button type="button" className="link-button" onClick={onLogout}>Cerrar sesión</button></p>
        </Card>
      </div>
    </main>
  );
}

function OwnerLogin({ notice, onLogin }: { notice: Notice; onLogin: (s: OwnerSession) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const { busy, error, run } = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const session = await api.post<OwnerSession>("/owner/auth/login", { email, password, code });
      setPassword("");
      setCode("");
      onLogin(session);
    });
  }

  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit}>
        <h1><Logo /> Lumen</h1>
        <p className="muted">Dueño del sistema</p>
        {notice?.tone === "ok" ? <SuccessBox message={notice.text} /> : <WarnBox message={notice?.text} />}
        <ErrorBox message={error} />
        <Field label="Correo electrónico" required>
          {(id) => <input id={id} type="email" autoComplete="username" required value={email}
                          onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Contraseña" required>
          {(id) => <input id={id} type="password" autoComplete="current-password" required value={password}
                          onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        <Field label="Código del celular"
               hint="Los 6 dígitos de la app del celular. Solo la primera vez, antes de configurarla, se deja vacío.">
          {(id, hint) => <input id={id} aria-describedby={hint} inputMode="numeric" autoComplete="one-time-code"
                                maxLength={7} value={code} onChange={(e) => setCode(e.target.value)} />}
        </Field>
        <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
          {busy ? "Ingresando…" : "Ingresar"}
        </button>
        <p className="muted small">¿Sos de una clínica? Entrá desde <a href="/">la página principal</a>.</p>
      </form>
    </main>
  );
}

function TotpSetup({ onDone }: { onDone: () => void }) {
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const { busy, error, run } = useAction();

  async function start() {
    await run(async () => {
      const r = await api.post<{ secret: string; uri: string }>("/owner/auth/totp/start");
      setSecret(r.secret);
    });
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => { await api.post("/owner/auth/totp/confirm", { code }); });
    if (ok) onDone();
  }

  return (
    <>
      <p className="small">
        Para entrar como dueño vas a necesitar, además de la contraseña, un código de 6 dígitos que
        cambia cada 30 segundos. Lo da una app gratuita del celular: <strong>Google Authenticator</strong>{" "}
        o <strong>Microsoft Authenticator</strong>.
      </p>
      <ErrorBox message={error} />
      {!secret ? (
        <button type="button" className="btn btn-primary" onClick={start} disabled={busy}>
          {busy ? "Generando…" : "Generar la clave para la app"}
        </button>
      ) : (
        <form onSubmit={confirm}>
          <ol className="steps small">
            <li>Instalá la app en el celular y abrila.</li>
            <li>
              Tocá <strong>+</strong> y elegí <em>Ingresar una clave de configuración</em> (o <em>Introducir
              clave</em>). Cuenta: <strong>Lumen</strong>. Clave:
              <div className="totp-secret"><code>{secret}</code> <CopyButton text={secret.replace(/ /g, "")} /></div>
              Tipo: <em>Basada en el tiempo</em>.
            </li>
            <li>Escribí abajo el código de 6 dígitos que muestra la app.</li>
          </ol>
          <Field label="Código de la app" required>
            {(id) => <input id={id} inputMode="numeric" autoComplete="one-time-code" maxLength={7} required
                            value={code} onChange={(e) => setCode(e.target.value)} />}
          </Field>
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "Verificando…" : "Activar el código"}
            </button>
          </div>
          <p className="muted small">
            No compartas esta clave ni le saques captura de pantalla: quien la tenga puede generar tus códigos.
          </p>
        </form>
      )}
    </>
  );
}

const TABS: [string, string][] = [["clinicas", "Clínicas"], ["espacio", "Espacio"], ["auditoria", "Auditoría"]];

function OwnerShell({ name, onLogout }: { name: string; onLogout: () => void }) {
  // La sección va en la dirección (#/clinicas/<id>/funciones): así anda el botón Atrás del navegador.
  const route = useRoute();
  const tab = TABS.some(([key]) => key === route.parts[0]) ? route.parts[0] : "clinicas";
  const clinicId = tab === "clinicas" ? route.parts[1] : undefined;
  let page;
  if (tab === "auditoria") page = <AuditTab />;
  else if (tab === "espacio") page = <StoragePage />;
  else if (clinicId) page = <ClinicPage key={clinicId} clinicId={clinicId} section={route.parts[2] ?? "resumen"} />;
  else page = <ClinicsPage />;
  return (
    <div className="app">
      <header className="topbar no-print">
        <div className="brand">
          <Logo />
          <div>
            <strong>Lumen</strong>
            <small>Dueño del sistema</small>
          </div>
        </div>
        <div className="whoami owner-whoami">
          <span>{name}<small>Dueño del sistema</small></span>
          <button type="button" className="btn btn-ghost" onClick={onLogout}>Cerrar sesión</button>
        </div>
      </header>
      <main className="content">
        {/* Pestañas dentro del contenido: así se ven igual en la computadora y en el celular. */}
        <nav className="page-tabs no-print" role="tablist" aria-label="Secciones">
          {TABS.map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key}
                    className={tab === key ? "ptab active" : "ptab"} onClick={() => navigate(`/${key}`)}>
              {label}
            </button>
          ))}
        </nav>
        <div role="tabpanel">{page}</div>
      </main>
    </div>
  );
}

function ClinicsPage() {
  const clinics = useAsync(() => api.get<ClinicSummary[]>("/owner/clinics"), []);
  const [creating, setCreating] = useState(false);
  const [access, setAccess] = useState<{ title: string; data: TemporaryAccess; who?: string } | null>(null);
  const list = clinics.data ?? [];
  const active = list.filter((c) => !c.suspended_at);

  return (
    <>
      <div className="page-title">
        <h1>Clínicas</h1>
        {!creating && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>+ Nueva clínica o consultorio</button>
        )}
      </div>
      <p className="muted small">
        Tocá una clínica para ver su resumen, cuánto ocupa, sus funciones y el acceso. Desde acá no se ven
        pacientes ni historia clínica: solo cantidades y las cuentas de la clínica. Todo lo que cambies
        queda en la auditoría, también en la de la clínica.
      </p>
      {creating && (
        <NewClinicForm
          onCancel={() => setCreating(false)}
          onCreated={(data, independent) => {
            setCreating(false);
            clinics.reload();
            setAccess(independent ? { title: "Consultorio creado", data, who: "Profesional" }
              : { title: "Clínica creada", data });
          }}
        />
      )}
      <ErrorBox message={clinics.error} />
      {clinics.loading && !clinics.data ? <Loading /> : list.length === 0 ? (
        <Empty>Todavía no hay clínicas.</Empty>
      ) : (
        <Card>
          <p className="small">
            <strong>{list.length}</strong> {list.length === 1 ? "clínica" : "clínicas"} ·{" "}
            {active.length} {active.length === 1 ? "activa" : "activas"} · {patientsText(active.reduce((n, c) => n + c.active_patients, 0))}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Clínica</th><th scope="col">Estado</th><th scope="col">Sucursales</th>
                  <th scope="col">Cuentas</th><th scope="col">Pacientes activos</th><th scope="col">En pausa</th>
                  <th scope="col">Último uso</th><th scope="col">Alta</th><th scope="col"><span className="sr-only">Acciones</span></th>
                </tr>
              </thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id} className="clickable-row" onClick={() => navigate(`/clinicas/${c.id}`)}>
                    <td>
                      <a href={`#/clinicas/${c.id}`} onClick={(e) => e.stopPropagation()}><strong>{c.name}</strong></a>
                      {c.kind === "independent" && <>{" "}<Badge tone="info">Profesional independiente</Badge></>}
                    </td>
                    <td>
                      {c.purged_at ? <Badge tone="neutral">Datos borrados</Badge>
                        : c.suspended_at ? <Badge tone="danger">Suspendida</Badge> : <Badge tone="ok">Activa</Badge>}
                    </td>
                    <td>{c.branches}</td>
                    <td>{c.users}</td>
                    <td>{c.active_patients}</td>
                    <td>
                      {c.paused_patients ?? 0}
                      {(c.paused_with_sessions ?? 0) > 0 && (
                        <>{" "}<Badge tone="warn">{c.paused_with_sessions} con turnos este mes</Badge></>
                      )}
                    </td>
                    <td>{c.last_activity ? fmtDateTime(c.last_activity) : <span className="muted">Nunca</span>}</td>
                    <td>{fmtDate(c.created_at.slice(0, 10))}</td>
                    <td className="row-actions">
                      <a className="btn btn-small" href={`#/clinicas/${c.id}`} onClick={(e) => e.stopPropagation()}>Ver</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {access && <AccessDialog title={access.title} data={access.data} who={access.who}
                               onClose={() => setAccess(null)} />}
    </>
  );
}

function patientsText(n: number): string {
  return `${n} ${n === 1 ? "paciente activo" : "pacientes activos"} en total`;
}

function NewClinicForm({ onCancel, onCreated }: {
  onCancel: () => void; onCreated: (admin: TemporaryAccess, independent: boolean) => void;
}) {
  const [form, setForm] = useState({ kind: "clinic", name: "", branch_name: "Central", admin_full_name: "",
    admin_email: "", admin_document: "", profession: "" });
  const { busy, error, run } = useAction();
  const independent = form.kind === "independent";
  const set = (key: keyof typeof form) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const { branch_name, profession, ...rest } = form;
      const r = await api.post<{ admin: TemporaryAccess }>("/owner/clinics", independent
        ? { ...rest, profession: profession.trim() }  // el consultorio se llama "Consultorio"
        : { ...rest, branch_name });
      onCreated(r.admin, independent);
    });
  }

  return (
    <Card title={independent ? "Nuevo profesional independiente" : "Nueva clínica"}>
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Tipo" required
               hint={independent
                 ? "Una sola cuenta: el profesional atiende, carga sus pacientes y los datos de su consultorio."
                 : "Varias cuentas (Administración, Recepción y profesionales) y sucursales."}>
          {(id, hint) => (
            <select id={id} aria-describedby={hint} value={form.kind} onChange={set("kind")}>
              <option value="clinic">Clínica o centro</option>
              <option value="independent">Profesional independiente</option>
            </select>
          )}
        </Field>
        <Field label={independent ? "Nombre del consultorio" : "Nombre de la clínica"} required
               hint={independent ? "Por ejemplo: Consultorio Lic. Ana Pérez. Lo puede cambiar después." : undefined}>
          {(id, hint) => <input id={id} aria-describedby={hint} required maxLength={200} value={form.name}
                                onChange={set("name")} data-autofocus />}
        </Field>
        {!independent && (
          <Field label="Primera sucursal" required hint="Después se agregan más desde la clínica.">
            {(id, hint) => <input id={id} aria-describedby={hint} required maxLength={100} value={form.branch_name}
                                  onChange={set("branch_name")} />}
          </Field>
        )}
        {independent ? (
          <p className="span-all small muted">
            <strong>Profesional</strong>: va a recibir una contraseña temporal y, al entrar, completa sus datos
            y su título en «Mi cuenta». Caja, BPS y AYEX y Avisos empiezan apagados (se habilitan en Funciones).
          </p>
        ) : (
          <p className="span-all small muted">
            <strong>Primer administrador</strong>: va a recibir una contraseña temporal y, al entrar, carga
            las sucursales, especialidades y cuentas de la clínica.
          </p>
        )}
        <Field label="Nombre y apellido" required>
          {(id) => <input id={id} required maxLength={200} autoComplete="off" value={form.admin_full_name}
                          onChange={set("admin_full_name")} />}
        </Field>
        <Field label="Correo electrónico" required hint="Con este correo inicia sesión.">
          {(id, hint) => <input id={id} aria-describedby={hint} type="email" required maxLength={254}
                                autoComplete="off" value={form.admin_email} onChange={set("admin_email")} />}
        </Field>
        <Field label="C.I." required>
          {(id) => <input id={id} required maxLength={30} autoComplete="off" value={form.admin_document}
                          onChange={set("admin_document")} />}
        </Field>
        {independent && (
          <Field label="Profesión" required hint="Por ejemplo: Psicología, Fonoaudiología, Psicopedagogía.">
            {(id, hint) => <input id={id} aria-describedby={hint} required minLength={2} maxLength={80}
                                  value={form.profession} onChange={set("profession")} />}
          </Field>
        )}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Creando…" : independent ? "Crear consultorio" : "Crear clínica"}
          </button>
        </div>
      </form>
    </Card>
  );
}

function AuditTab() {
  const rows = useAsync(() => api.get<OwnerAuditRow[]>("/owner/audit"), []);
  return (
    <>
      <div className="page-title"><h1>Auditoría del dueño</h1></div>
      <p className="muted small">Las últimas 200 acciones. No se pueden borrar ni modificar.</p>
      <ErrorBox message={rows.error} />
      {rows.loading && !rows.data ? <Loading /> : (
        <Card>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Fecha</th><th scope="col">Acción</th><th scope="col">Clínica</th>
                  <th scope="col">Cuenta</th><th scope="col">Detalle</th><th scope="col">Quién</th><th scope="col">IP</th>
                </tr>
              </thead>
              <tbody>
                {(rows.data ?? []).map((e) => (
                  <tr key={e.id}>
                    <td>{fmtDateTime(e.created_at)}</td>
                    <td>{OWNER_ACTION_LABELS[e.action] ?? e.action}</td>
                    <td>{e.clinic_name ?? "—"}</td>
                    <td>{e.target_name ?? "—"}</td>
                    <td>{auditDetail(e.details)}</td>
                    <td>{e.owner_name ?? "—"}</td>
                    <td className="muted small">{e.ip ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

function auditDetail(details: Record<string, unknown>): string {
  const parts: string[] = [];
  if (typeof details.reason === "string" && details.reason) parts.push(`Motivo: ${details.reason}`);
  if (typeof details.count === "number") parts.push(`${details.count} sesiones cerradas`);
  if (typeof details.patients === "number") parts.push(`${details.patients} pacientes`);
  if (typeof details.files === "number") parts.push(`${details.files} archivos`);
  if (details.is_active === true) parts.push("Cuenta reactivada");
  if (typeof details.feature === "string") parts.push(FEATURE_LABELS[details.feature] ?? details.feature);
  return parts.join(" · ") || "—";
}
