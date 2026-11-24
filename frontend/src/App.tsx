import { useCallback, useEffect, useState } from "react";
import { api, ApiError, setBranchMissingHandler, setCsrfToken, setUnauthorizedHandler } from "./api";
import { Card, Loading, Logo } from "./components";
import { askConfirm } from "./confirm";
import { clearAllDrafts, hasPendingDrafts, setDraftOwner } from "./drafts";
import { SessionWarning } from "./SessionWarning";
import { fmtDateTime, ROLE_LABELS } from "./labels";
import { AccountPage, ChangePasswordForm } from "./pages/AccountPage";
import { AgendaPage } from "./pages/AgendaPage";
import { AuditPage } from "./pages/AuditPage";
import { ConsultorioPage } from "./pages/ConsultorioPage";
import { BpsPaymentsPage } from "./pages/BpsPaymentsPage";
import { CashPage } from "./pages/CashPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { MonthlySummaryPage } from "./pages/MonthlySummaryPage";
import { NoticesPage } from "./pages/NoticesPage";
import { PatientDetailPage } from "./pages/PatientDetailPage";
import { PatientsPage } from "./pages/PatientsPage";
import { bpsMissing } from "./pages/BpsFields";
import { PrintAnamnesis, PrintPatient, PrintReport } from "./pages/PrintPage";
import { UsersPage } from "./pages/UsersPage";
import { navigate, useRoute } from "./router";
import { hasFeature, isTitular, SessionContext, useSession, type Session } from "./session";
import type { MyNotice, SessionInfo } from "./types";

export function App() {
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [checking, setChecking] = useState(true);
  // Aviso en la pantalla de ingreso: verde si es una confirmación, amarillo si hay que
  // volver a entrar (la sesión expiró) o si no se pudo verificar la sesión.
  const [notice, setNotice] = useState<{ text: string; tone: "ok" | "warn" } | null>(null);

  const applySession = useCallback((next: SessionInfo | null) => {
    setCsrfToken(next ? next.csrf_token : null);
    // Los borradores son de quien los escribió: si entra otra persona, se descartan.
    if (next) setDraftOwner(next.user.id);
    setInfo(next);
  }, []);

  // Si hay algo escrito sin guardar, el navegador pregunta antes de cerrar o recargar la página.
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasPendingDrafts()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  useEffect(() => {
    // Primero se comprueba si ya hay una sesión abierta. Recién después se avisa "Tu sesión
    // expiró" ante un 401: al abrir la página sin haber entrado no expiró nada.
    api
      .get<SessionInfo>("/auth/me")
      .then(applySession)
      .catch((err) => {
        if (!(err instanceof ApiError && err.status === 401)) setNotice({ text: err.message, tone: "warn" });
      })
      .finally(() => {
        setChecking(false);
        setUnauthorizedHandler(() => {
          applySession(null);
          setNotice({ text: "Tu sesión expiró. Iniciá sesión nuevamente.", tone: "warn" });
        });
      });
    setBranchMissingHandler(() => {
      api.get<SessionInfo>("/auth/me").then(applySession).catch(() => undefined);
    });
    return () => { setUnauthorizedHandler(null); setBranchMissingHandler(null); };
  }, [applySession]);

  const switchBranch = useCallback(async (branchId: string) => {
    const next = await api.post<SessionInfo>("/auth/branch", { branch_id: branchId });
    applySession(next);
    navigate("/");
  }, [applySession]);

  const logout = useCallback(async () => {
    if (hasPendingDrafts() && !await askConfirm(
      "Tenés texto escrito sin guardar (una nota, un objetivo o un informe). Si cerrás sesión, se pierde.",
      { confirmLabel: "Cerrar sesión igual", danger: true })) return;
    clearAllDrafts();
    api
      .post("/auth/logout")
      .catch(() => undefined)
      .finally(() => {
        applySession(null);
        setNotice({ text: "Cerraste sesión.", tone: "ok" });
        navigate("/");
      });
  }, [applySession]);

  if (checking) return <main className="center"><Loading /></main>;
  if (!info) {
    return (
      <LoginPage
        notice={notice}
        onLogin={(s) => {
          setNotice(null);
          applySession(s);
        }}
      />
    );
  }
  if (info.user.must_change_password) {
    // Entró con una contraseña temporal: primero debe elegir una nueva.
    return (
      <main className="login">
        <div className="login-card">
          <Card title="Elegí una contraseña nueva">
            <p className="small">
              Hola, {info.user.full_name}. Entraste con una contraseña temporal que te dio
              administración. Para seguir, elegí una contraseña nueva que solo vos conozcas.
            </p>
            <ChangePasswordForm
              currentLabel="Contraseña temporal"
              onChanged={() => { api.get<SessionInfo>("/auth/me").then(applySession).catch(logout); }}
            />
            <p className="small"><button type="button" className="link-button" onClick={logout}>Cerrar sesión</button></p>
          </Card>
        </div>
      </main>
    );
  }
  if (!info.active_branch) {
    return <BranchPicker info={info} onChoose={switchBranch} onLogout={logout} />;
  }
  const session: Session = {
    user: info.user, clinic: info.clinic, branch: info.active_branch, branches: info.branches,
    switchBranch, logout,
    refresh: () => api.get<SessionInfo>("/auth/me").then(applySession),
  };
  return (
    <SessionContext.Provider value={session}>
      {/* Al cambiar de sucursal, todas las pantallas se vuelven a cargar con sus datos. */}
      <Shell key={info.active_branch.id} />
      <SessionWarning idleMinutes={info.idle_minutes ?? 60} expiresAt={info.expires_at ?? null} />
    </SessionContext.Provider>
  );
}

function BranchPicker({ info, onChoose, onLogout }: {
  info: SessionInfo; onChoose: (branchId: string) => Promise<void>; onLogout: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function choose(id: string) {
    setBusy(true);
    setError(null);
    try {
      await onChoose(id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo elegir la sucursal.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <div className="login-card">
        <Card title="¿A qué sucursal entrás?">
          <p className="small">Hola, {info.user.full_name}. {info.clinic.name}</p>
          {error && <p className="alert alert-error">{error}</p>}
          {info.branches.length === 0 ? (
            <p className="alert alert-warn">
              Tu cuenta no tiene sucursales asignadas. Pedile a administración que te asigne una.
            </p>
          ) : (
            <div className="branch-list">
              {info.branches.map((b) => (
                <button key={b.id} type="button" className="btn branch-choice" disabled={busy}
                        onClick={() => choose(b.id)}>
                  {b.name}
                </button>
              ))}
            </div>
          )}
          <p className="small"><button type="button" className="link-button" onClick={onLogout}>Cerrar sesión</button></p>
        </Card>
      </div>
    </main>
  );
}

function Shell() {
  const route = useRoute();
  const { user, clinic, branch, branches, switchBranch, logout } = useSession();
  const section = route.parts[0] ?? "inicio";
  // En el celular el menú se pliega detrás de un botón; se cierra solo al cambiar de sección.
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => { setMenuOpen(false); }, [section]);
  // Lo que el dueño del sistema deshabilitó para la clínica no aparece (y la API lo rechaza).
  // Profesional independiente: además de atender, administra su propio consultorio.
  const titular = isTitular(user, clinic);
  const can = {
    informe: hasFeature(clinic, "informe_mensual"),
    caja: hasFeature(clinic, "caja") && (user.role === "admin" || user.role === "reception"),
    avisos: hasFeature(clinic, "avisos") && (user.role === "admin" || user.role === "reception"),
    pagosBps: hasFeature(clinic, "bps") && (user.role === "admin" || user.role === "reception" || titular),
    auditoria: user.role === "admin" || titular,
  };
  const links: [string, string][] = [
    ["inicio", "Inicio"],
    ["pacientes", "Pacientes"],
    ["agenda", "Agenda"],
  ];
  if (can.informe) links.push(["informe", "Informe mensual"]);
  if (can.caja) links.push(["caja", "Caja"]);
  if (can.avisos) links.push(["avisos", "Avisos"]);
  if (can.pagosBps) links.push(["pagos-bps", "Pagos BPS"]);
  if (user.role === "admin") links.push(["usuarios", "Usuarios"]);
  if (can.auditoria) links.push(["auditoria", "Auditoría"]);
  if (titular) links.push(["consultorio", "Mi consultorio"]);
  links.push(["cuenta", "Mi cuenta"]);

  // Vistas para imprimir: sin menú ni encabezado de la aplicación.
  if (section === "imprimir" && route.parts[2]) {
    if (route.parts[1] === "informe") return <PrintReport reportId={route.parts[2]} />;
    if (route.parts[1] === "ficha") return <PrintPatient patientId={route.parts[2]} />;
    if (route.parts[1] === "anamnesis") {
      return <PrintAnamnesis patientId={route.parts[2]} versionId={route.params.get("version")} />;
    }
  }

  let page;
  if (section === "pacientes" && route.parts[1]) {
    page = <PatientDetailPage patientId={route.parts[1]} />;
  } else if (section === "agenda") {
    page = <AgendaPage />;
  } else if (section === "usuarios" && user.role === "admin") {
    page = <UsersPage />;
  } else if (section === "consultorio" && titular) {
    page = <ConsultorioPage />;
  } else if (section === "pagos-bps" && can.pagosBps) {
    page = <BpsPaymentsPage />;
  } else if (section === "auditoria" && can.auditoria) {
    page = <AuditPage patientId={route.params.get("paciente")} />;
  } else if (section === "caja" && can.caja) {
    page = <CashPage />;
  } else if (section === "avisos" && can.avisos) {
    page = <NoticesPage />;
  } else if (section === "informe" && can.informe) {
    page = <MonthlySummaryPage />;
  } else if (section === "cuenta") {
    page = <AccountPage />;
  } else if (section === "pacientes") {
    page = <PatientsPage />;
  } else {
    page = <HomePage />;
  }

  return (
    <div className="app">
      <div className="demo-banner" role="note">
        Entorno de desarrollo: usá solo datos ficticios.
      </div>
      <MissingDataBanner />
      {user.role === "professional" && hasFeature(clinic, "avisos") && <NoticesBanner />}
      <header className="topbar">
        <div className="brand">
          <Logo />
          <div>
            <strong>Nordeste</strong>
            <small>{clinic.name}</small>
            {!titular && (
            <div className="branch-badge">
            {branches.length > 1 ? (
              <select aria-label="Sucursal activa" value={branch.id}
                      onChange={(e) => { switchBranch(e.target.value).catch(() => undefined); }}>
                {branches.map((b) => <option key={b.id} value={b.id}>Sucursal: {b.name}</option>)}
              </select>
            ) : (
              <span>Sucursal: {branch.name}</span>
            )}
            </div>
            )}
          </div>
        </div>
        <button type="button" className="btn menu-toggle" aria-expanded={menuOpen} aria-controls="menu-secciones"
                onClick={() => setMenuOpen((open) => !open)}>
          <span aria-hidden="true">☰</span> Menú: {links.find(([key]) => key === section)?.[1] ?? "Inicio"}
          <span aria-hidden="true" className="menu-caret">{menuOpen ? "▴" : "▾"}</span>
        </button>
        <nav id="menu-secciones" aria-label="Secciones" className={menuOpen ? "open" : undefined}>
          {links.map(([key, label]) => (
            <a key={key} href={`#/${key}`} aria-current={section === key ? "page" : undefined}>
              {label}
            </a>
          ))}
        </nav>
        <div className="whoami">
          <span>
            {user.full_name}
            <small>{titular ? "Profesional independiente" : ROLE_LABELS[user.role]}</small>
          </span>
          <button type="button" className="btn btn-ghost" onClick={logout}>
            Cerrar sesión
          </button>
        </div>
      </header>
      <main className="content">{page}</main>
    </div>
  );
}

/** Aviso fijo mientras falten datos obligatorios de la propia cuenta (C.I. y, para
 * profesionales, el título universitario). Se puede seguir trabajando. */
const NOTICES_EVERY_MS = 60_000; // revisar si hay avisos nuevos cada minuto

/** Avisos de Recepción o Administración: en la barra amarilla hasta tocar "Entendido". */
function NoticesBanner() {
  const [notices, setNotices] = useState<MyNotice[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api.get<MyNotice[]>("/notices/mine").then(setNotices).catch(() => undefined);
  }, []);
  useEffect(() => {
    load();
    const timer = setInterval(load, NOTICES_EVERY_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function markRead(id: string) {
    setBusy(id);
    try {
      await api.post(`/notices/${id}/read`, {});
      setNotices((list) => list.filter((n) => n.id !== id));
    } catch {
      load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      {notices.map((n) => (
        <div key={n.id} className="degree-banner notice-banner" role="status">
          <span>
            <strong>{n.author_role === "professional" ? "Aviso automático" : `Aviso de ${n.author_role === "admin" ? "Administración" : "Recepción"}`} · {n.author_name}
              {" · "}{fmtDateTime(n.created_at)}:</strong>{" "}
            <span className="notice-text">{n.message}</span>
          </span>
          <button type="button" className="btn btn-small" disabled={busy === n.id} onClick={() => markRead(n.id)}>
            Entendido
          </button>
        </div>
      ))}
    </>
  );
}

function MissingDataBanner() {
  const { user, clinic } = useSession();
  const missing = [
    !user.document_number && "tu C.I.",
    user.role === "professional" && !user.degree_id && "la foto o el PDF de tu título universitario",
    bpsMissing(user, clinic) && "tus datos para el BPS",
  ].filter(Boolean) as string[];
  if (missing.length === 0) return null;
  return (
    <div className="degree-banner" role="status">
      <strong>Faltan datos obligatorios de tu cuenta:</strong> {missing.length > 1 ? `${missing.slice(0, -1).join(", ")} y ${missing[missing.length - 1]}` : missing[0]} —{" "}
      <a href="#/cuenta">completalos en Mi cuenta</a>.
    </div>
  );
}
