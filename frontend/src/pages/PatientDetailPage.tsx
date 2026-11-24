// Ficha del paciente: encabezado con nombre y documento, pestañas con íconos.
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import { Badge, Card, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import {
  ACCESS_LABELS, AFFILIATION_LABELS, ageFrom, ayexState, fmtDate, fmtDateTime, fullName, PATIENT_STATUS_LABELS,
  PATIENT_STATUS_TONE as STATUS_TONE, SEX_LABELS, telHref,
} from "../labels";
import { ProfTag, ProfTagList, useSpecialtyLookup } from "../profession";
import { navigate, useRoute } from "../router";
import { hasFeature, isTitular, useSession } from "../session";
import { notify } from "../toast";
import type { AffiliationType, NoteKind, Patient, PatientDetail } from "../types";
import { AnamnesisPanel } from "./AnamnesisPanel";
import { FilesPanel } from "./FilesPanel";
import { GoalsPanel } from "./GoalsPanel";
import { GuardiansPanel } from "./GuardiansPanel";
import { InstitutionsPanel } from "./InstitutionsPanel";
import { NotesPanel } from "./NotesPanel";
import { AddressFields, addressPayload, addressText, emptyAddress } from "./AddressFields";
import { AccessPanel, PatientAppointments } from "./PatientPanels";
import { receptionCanSee } from "./PatientsPage";
import { ReportsPanel } from "./ReportsPanel";
import { AbordajePanel, SharedSectionPanel } from "./ReportSectionsPanel";

type Tab = "info" | "responsables" | "instituciones" | "historia" | "objetivos" | "anamnesis" | "entrevista" | "evaluaciones"
  | "antecedentes" | "diagnostico" | "encuadre" | "abordaje"
  | "informes" | "archivos" | "turnos" | "accesos";

// Íconos simples dibujados en SVG (sin librerías externas).
const ICONS: Record<Tab, ReactNode> = {
  info: <><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-6 8-6s8 2 8 6" /></>,
  responsables: <><circle cx="8" cy="8" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M2 20c0-3 3-5 6-5s6 2 6 5M14 20c0-2 1.5-4 4-4s4 2 4 4" /></>,
  instituciones: <><path d="M3 10l9-5 9 5" /><path d="M5 10v9h14v-9" /><path d="M10 19v-5h4v5" /></>,
  historia: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 8h6M9 12h6M9 16h4" /></>,
  objetivos: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="0.8" /></>,
  anamnesis: <><path d="M4 5h16v12H9l-5 4z" /><path d="M8 10h8" /></>,
  entrevista: <><path d="M3 5h12v8H7l-4 3z" /><path d="M17 9h4v8l-3-2h-5v-2" /></>,
  evaluaciones: <><path d="M9 11l2 2 4-4" /><rect x="4" y="4" width="16" height="16" rx="2" /></>,
  antecedentes: <><circle cx="12" cy="12" r="8" /><path d="M12 7v5l3 2" /></>,
  diagnostico: <><path d="M6 4v6a6 6 0 0012 0V4" /><circle cx="18" cy="16" r="2" /><path d="M12 16v1a4 4 0 004 4h0" /></>,
  encuadre: <><rect x="4" y="4" width="16" height="16" rx="1" /><path d="M4 9h16M9 9v11" /></>,
  abordaje: <><circle cx="9" cy="8" r="3" /><path d="M3 20c0-3 3-5 6-5" /><path d="M14 14l2 2 5-5" /></>,
  informes: <><path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4M9 13h6M9 17h6" /></>,
  archivos: <><path d="M14 4l5 5-8.5 8.5a3.5 3.5 0 01-5-5L14 4.5" /></>,
  turnos: <><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M4 10h16M9 3v4M15 3v4" /></>,
  accesos: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 018 0v3" /></>,
};

function Icon({ tab }: { tab: Tab }) {
  return (
    <svg className="tab-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
         fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {ICONS[tab]}
    </svg>
  );
}

// Pestañas de registros clínicos: qué tipos de nota muestra cada una.
const CLINICAL_TABS: Partial<Record<Tab, { kinds: NoteKind[]; title: string; empty: string }>> = {
  historia: { kinds: ["session", "background", "progress"], title: "Historia clínica",
              empty: "Todavía no hay notas de sesión, antecedentes ni evolución." },
  entrevista: { kinds: ["interview"], title: "Entrevistas", empty: "Todavía no hay entrevistas registradas." },
  evaluaciones: { kinds: ["evaluation"], title: "Evaluaciones", empty: "Todavía no hay evaluaciones registradas." },
};

export function PatientDetailPage({ patientId }: { patientId: string }) {
  const { user, branch, clinic } = useSession();
  const patient = useAsync(() => api.get<PatientDetail>(`/patients/${patientId}`), [patientId]);
  const route = useRoute();
  // Enlaces directos a una pestaña (por ejemplo "Escribir nota" desde el Inicio:
  // #/pacientes/<id>?pestana=historia&fecha=2026-10-23).
  const [tab, setTab] = useState<Tab>(() => (route.params.get("pestana") as Tab | null) ?? "info");
  const noteDate = route.params.get("fecha") ?? undefined;
  const tabsRef = useRef<HTMLElement>(null);
  const [tabsAtEnd, setTabsAtEnd] = useState(false);
  // En el celular las pestañas van en una fila que se desliza: la elegida queda a la vista.
  useEffect(() => {
    tabsRef.current?.querySelector<HTMLElement>(".ptab.active")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab, patient.data?.id]);
  const [editing, setEditing] = useState(false);

  if (patient.loading && !patient.data) return <Loading />;
  if (patient.error || !patient.data) {
    return (
      <>
        <p><a href="#/pacientes">← Volver a pacientes</a></p>
        <ErrorBox message={patient.error ?? "Paciente no encontrado."} />
      </>
    );
  }
  const p = patient.data;
  const age = ageFrom(p.birth_date);

  const tabs: [Tab, string][] = [["info", "Info. general"], ["responsables", "Responsables"], ["instituciones", "Instituciones"]];
  if (p.can_view_clinical) {
    tabs.push(["historia", "H. clínica"]);
    if (hasFeature(clinic, "objetivos")) tabs.push(["objetivos", "Objetivos"]);
    tabs.push(["anamnesis", "Anamnesis"], ["entrevista", "Entrevista"], ["evaluaciones", "Evaluaciones"],
              ["antecedentes", "Antecedentes"], ["diagnostico", "Diagnóstico"], ["encuadre", "Encuadre"],
              ["abordaje", "Abordaje"]);
  }
  if (p.can_view_reports) tabs.push(["informes", "Informes"]);
  // Archivos: los profesionales con acceso, y también Administración y Recepción (los suben y ven).
  const canSeeFiles = p.can_view_clinical || user.role === "admin" || user.role === "reception";
  if (canSeeFiles && hasFeature(clinic, "archivos")) tabs.push(["archivos", "Archivos"]);
  tabs.push(["turnos", "Turnos"]);
  if (user.role !== "reception") tabs.push(["accesos", "Accesos"]);

  function openTab(key: Tab) {
    setTab(key);
    setEditing(false);
  }

  // Si la pestaña pedida no está disponible para este rol, se muestra Info. general.
  const current: Tab = tabs.some(([key]) => key === tab) ? tab : "info";
  const clinical = CLINICAL_TABS[current];

  return (
    <>
      <p><a href="#/pacientes">← Volver a pacientes</a></p>

      <header className="patient-banner">
        <div className="patient-avatar" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
          </svg>
        </div>
        <div className="patient-banner-text">
          <h1>{fullName(p)}</h1>
          <p>
            {p.document_number ? <>Documento: <strong>{p.document_number}</strong></> : "Sin documento cargado"}
            {age !== null && <> · {age} años</>}
          </p>
        </div>
        <div className="patient-banner-badges">
          <Badge tone={STATUS_TONE[p.status]}>{PATIENT_STATUS_LABELS[p.status]}</Badge>
          {p.my_access_level && <Badge tone="info">Tu acceso: {ACCESS_LABELS[p.my_access_level]}</Badge>}
        </div>
      </header>

      <nav ref={tabsRef} className={tabsAtEnd ? "patient-tabs at-end" : "patient-tabs"} role="tablist"
           aria-label="Secciones del paciente"
           onScroll={(e) => {
             const el = e.currentTarget;
             setTabsAtEnd(el.scrollLeft + el.clientWidth >= el.scrollWidth - 4);
           }}>
        {tabs.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={current === key}
                  className={current === key ? "ptab active" : "ptab"} onClick={() => openTab(key)}>
            <Icon tab={key} /> <span>{label}</span>
          </button>
        ))}
      </nav>

      {current === "info" && (user.role === "admin" || user.role === "reception") && (
        <p className="muted small">
          Tu rol ve los datos administrativos y los informes finalizados (solo lectura). La
          historia clínica solo la ven los profesionales autorizados.
        </p>
      )}

      <div role="tabpanel">
        {current === "info" && !editing && (
          <PatientInfo patient={p}
                       onEdit={p.can_edit ? () => setEditing(true) : undefined}
                       onChangeResponsible={user.role === "admin" ? () => openTab("accesos") : undefined} />
        )}
        {current === "info" && editing && (
          <PatientEditForm
            patient={p}
            onClose={(updated) => {
              setEditing(false);
              if (!updated) return;
              if (user.role === "reception" && !receptionCanSee(updated, branch.id)) {
                // Pasó a una sucursal que recepción no ve desde aquí: se vuelve al listado.
                notify(`Ficha actualizada. ${updated.first_name} ${updated.last_name} ahora se atiende en otra ` +
                       "sucursal: para ver su ficha, cambiá a esa sucursal.");
                navigate("/pacientes");
                return;
              }
              notify("Ficha actualizada.");
              patient.reload();
            }}
          />
        )}
        {current === "responsables" && <GuardiansPanel patientId={p.id} canEdit={p.can_edit} />}
        {current === "instituciones" && (
          <InstitutionsPanel patientId={p.id} canEdit={p.can_edit} canViewClinical={p.can_view_clinical} />
        )}
        {clinical && p.can_view_clinical && (
          <NotesPanel key={current} patientId={p.id} kinds={clinical.kinds} title={clinical.title}
                      emptyText={clinical.empty} defaultDate={current === "historia" ? noteDate : undefined} />
        )}
        {current === "informes" && p.can_view_reports && (
          <ReportsPanel patientId={p.id} readOnly={!p.can_view_clinical}
                        isResponsible={p.my_access_level === "responsible"} />
        )}
        {current === "anamnesis" && p.can_view_clinical && <AnamnesisPanel patient={p} />}
        {(current === "antecedentes" || current === "diagnostico" || current === "encuadre") && p.can_view_clinical && (
          <SharedSectionPanel key={current} patientId={p.id} section={current} />
        )}
        {current === "abordaje" && p.can_view_clinical && <AbordajePanel patientId={p.id} />}
        {current === "archivos" && canSeeFiles && <FilesPanel patientId={p.id} />}
        {current === "objetivos" && p.can_view_clinical && <GoalsPanel patientId={p.id} />}
        {current === "turnos" && <PatientAppointments patientId={p.id} active={p.status === "active"} />}
        {current === "accesos" && (
          <AccessPanel patientId={p.id} patient={p} canManage={p.can_manage_access} onChanged={patient.reload} />
        )}
      </div>

      <footer className="patient-footer">
        <a className="btn" href="#/pacientes">Volver al listado</a>
        <a className="btn" href={`#/imprimir/ficha/${p.id}`} target="_blank" rel="noopener">
          Imprimir ficha
        </a>
        {p.affiliation === "ayex" && (user.role !== "professional" || isTitular(user, clinic)) && hasFeature(clinic, "bps")
          && <AyexFormLink patient={p} />}
      </footer>
    </>
  );
}

function InfoField({ label, value, wide }: { label: string; value: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? "info-field wide" : "info-field"}>
      <span className="info-label">{label}</span>
      <span className="info-value">{value === null || value === undefined || value === "" ? "—" : value}</span>
    </div>
  );
}

function PatientInfo({ patient: p, onEdit, onChangeResponsible }: {
  patient: PatientDetail; onEdit?: () => void; onChangeResponsible?: () => void;
}) {
  const age = ageFrom(p.birth_date);
  const specialty = useSpecialtyLookup();
  return (
    <Card title="Información general" actions={onEdit && (
      <button type="button" className="btn btn-primary" onClick={onEdit}>Editar ficha</button>
    )}>
      <div className="info-grid">
        <InfoField label="Documento (cédula)" value={p.document_number} />
        <InfoField label="Primer nombre" value={p.first_name} />
        <InfoField label="Segundo nombre" value={p.middle_name} />
        <InfoField label="Primer apellido" value={p.last_name} />
        <InfoField label="Segundo apellido" value={p.second_last_name} />
        <InfoField label="Sexo" value={p.sex ? SEX_LABELS[p.sex] : null} />
        <InfoField label="Tipo de afiliación" value={AFFILIATION_LABELS[p.affiliation]} />
        {p.affiliation === "ayex" && (
          <InfoField label="Vencimiento del AYEX" value={p.ayex_expires_on ? (
            <>
              {fmtDate(p.ayex_expires_on)}{" "}
              {ayexState(p.ayex_expires_on) === "expired" && <span className="badge badge-danger">Vencido</span>}
              {ayexState(p.ayex_expires_on) === "red" && <span className="badge badge-danger">Vence en menos de 2 meses</span>}
              {ayexState(p.ayex_expires_on) === "yellow" && <span className="badge badge-warn">Vence en menos de 3 meses</span>}
            </>
          ) : <span className="text-danger">Falta cargarlo (editá la ficha)</span>} />
        )}
        <InfoField label="Sucursal" value={p.branch_name} />
        <InfoField label="Fecha de nacimiento" value={p.birth_date ? fmtDate(p.birth_date) : null} />
        <InfoField label="Edad" value={age !== null ? `${age} años` : null} />
        <InfoField label="Domicilio" wide value={addressText(p)} />
        <InfoField label="Teléfono" value={p.phone ? <a href={telHref(p.phone)}>{p.phone}</a> : null} />
        <InfoField label="Correo electrónico" value={p.email} />
        <InfoField label="Profesional responsable" value={(
          <>
            {p.responsible_name
              ? <ProfTag name={p.responsible_name} specialty={specialty.byId(p.responsible_id)} />
              : "Sin asignar"}
            {onChangeResponsible && (
              <button type="button" className="link-button" onClick={onChangeResponsible}>Cambiar</button>
            )}
          </>
        )} />
        <InfoField label="Profesionales colaboradores" value={
          p.collaborator_names && p.collaborator_names.length > 0
            ? <ProfTagList names={p.collaborator_names} lookup={specialty} />
            : "Ninguno"
        } />
        <InfoField label="Fecha de registro" value={fmtDateTime(p.created_at)} />
      </div>
    </Card>
  );
}

function PatientEditForm({ patient, onClose }: {
  patient: PatientDetail; onClose: (updated: Patient | null) => void;
}) {
  const { branches } = useSession();
  const [form, setForm] = useState({
    document_number: patient.document_number ?? "",
    first_name: patient.first_name, middle_name: patient.middle_name ?? "",
    last_name: patient.last_name, second_last_name: patient.second_last_name ?? "",
    sex: (patient.sex ?? "") as string,
    affiliation: patient.affiliation as string,
    ayex_expires_on: patient.ayex_expires_on ?? "",
    branch_id: patient.branch_id,
    birth_date: patient.birth_date ?? "", phone: patient.phone ?? "", email: patient.email ?? "",
    status: patient.status as string,
  });
  const [address, setAddress] = useState(() => emptyAddress(patient));
  const { busy, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    let updated: Patient | null = null;
    const ok = await run(async () => {
      updated = await api.patch<Patient>(`/patients/${patient.id}`, {
        document_number: form.document_number || null,
        first_name: form.first_name, middle_name: form.middle_name || null,
        last_name: form.last_name, second_last_name: form.second_last_name || null,
        sex: form.sex || null,
        affiliation: form.affiliation,
        ayex_expires_on: form.affiliation === "ayex" ? form.ayex_expires_on || null : null,
        ...(form.branch_id !== patient.branch_id ? { branch_id: form.branch_id } : {}),
        birth_date: form.birth_date || null, phone: form.phone || null,
        email: form.email || null, status: form.status,
        ...addressPayload(address),
      });
    });
    if (ok) onClose(updated);
  }

  return (
    <Card title="Editar ficha">
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Primer nombre" required>
          {(id) => <input id={id} required maxLength={100} autoFocus value={form.first_name}
                          onChange={set("first_name")} />}
        </Field>
        <Field label="Segundo nombre">
          {(id) => <input id={id} maxLength={100} value={form.middle_name} onChange={set("middle_name")} />}
        </Field>
        <Field label="Primer apellido" required>
          {(id) => <input id={id} required maxLength={100} value={form.last_name} onChange={set("last_name")} />}
        </Field>
        <Field label="Segundo apellido">
          {(id) => <input id={id} maxLength={100} value={form.second_last_name} onChange={set("second_last_name")} />}
        </Field>
        <Field label="Documento (cédula)" hint="Números y letras; se guarda en mayúsculas.">
          {(id, hint) => <input id={id} aria-describedby={hint} maxLength={30} value={form.document_number}
                                onChange={set("document_number")} />}
        </Field>
        <Field label="Fecha de nacimiento">
          {(id) => <input id={id} type="date" value={form.birth_date} onChange={set("birth_date")} />}
        </Field>
        <Field label="Sexo">
          {(id) => (
            <select id={id} value={form.sex} onChange={set("sex")}>
              <option value="">Sin indicar</option>
              {Object.entries(SEX_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </Field>
        <Field label="Estado" required>
          {(id) => (
            <select id={id} value={form.status} onChange={set("status")}>
              {Object.entries(PATIENT_STATUS_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </Field>
        <Field label="Teléfono">
          {(id) => <input id={id} type="tel" maxLength={40} value={form.phone} onChange={set("phone")} />}
        </Field>
        <Field label="Correo electrónico">
          {(id) => <input id={id} type="email" maxLength={254} value={form.email} onChange={set("email")} />}
        </Field>
        <AddressFields value={address} onChange={setAddress} />
        <Field label="Tipo de afiliación" required>
          {(id) => (
            <select id={id} required value={form.affiliation} onChange={set("affiliation")}>
              {Object.entries(AFFILIATION_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </Field>
        {form.affiliation === "ayex" && (
          <Field label="Vencimiento del AYEX" required hint="Obligatorio para pacientes de AYEX. Se avisa en el Inicio el mes en que vence.">
            {(id, hint) => <input id={id} type="date" required aria-describedby={hint} min="2000-01-01" max="2100-12-31"
                                  value={form.ayex_expires_on} onChange={set("ayex_expires_on")} />}
          </Field>
        )}
        <Field label="Sucursal" required hint="Solo podés elegir entre tus sucursales.">
          {(id, hint) => (
            <select id={id} required aria-describedby={hint} value={form.branch_id} onChange={set("branch_id")}>
              {!branches.some((b) => b.id === patient.branch_id) && (
                <option value={patient.branch_id}>{patient.branch_name ?? "Sucursal actual"}</option>
              )}
              {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
        </Field>
        {patient.status === "active" && form.status !== "active" && patient.future_appointments > 0 && (
          <p className="alert alert-warn span-all">
            Al cambiar el estado a "{PATIENT_STATUS_LABELS[form.status as keyof typeof PATIENT_STATUS_LABELS]}"{" "}
            {patient.future_appointments === 1
              ? "se cancelará su turno futuro."
              : `se cancelarán sus ${patient.future_appointments} turnos futuros.`}
          </p>
        )}
        {form.status === "active" && form.affiliation !== "private" && patient.future_appointments > 0
          && (form.branch_id !== patient.branch_id || form.affiliation !== patient.affiliation) && (
          <p className="alert alert-warn span-all">
            Los pacientes de {AFFILIATION_LABELS[form.affiliation as AffiliationType]} se atienden solo en su
            sucursal: si tiene turnos futuros en otra sucursal, se cancelarán al guardar.
          </p>
        )}
        <div className="form-actions">
          <button type="button" className="btn" onClick={() => onClose(null)}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Guardando…" : "Guardar cambios"}
          </button>
        </div>
      </form>
    </Card>
  );
}

/** Descarga del formulario de AYEX del BPS, completado con los datos que Lumen tiene. Avisa
 * qué falta en la ficha para que salga completo (lo demás se completa a mano en el PDF). */
function AyexFormLink({ patient: p }: { patient: PatientDetail }) {
  const missing = [
    !p.document_number && "C.I.",
    !(p.address_street || p.address_locality || p.address_department) && "domicilio",
    !p.phone && "teléfono",
  ].filter(Boolean) as string[];
  return (
    <span className="ayex-form-link">
      <a className="btn" href={`/api/patients/${p.id}/ayex-form`} download
         title="Solicitud de liquidación de Ayuda Extraordinaria del BPS, con los datos del paciente">
        Formulario AYEX (PDF)
      </a>
      {missing.length > 0 && (
        <small className="muted block">Para que salga más completo, falta en la ficha: {missing.join(", ")}.</small>
      )}
    </span>
  );
}
