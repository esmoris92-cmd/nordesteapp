// Vistas para imprimir o guardar como PDF (con el diálogo de impresión del navegador).
import { Fragment, type ReactNode } from "react";
import { api } from "../api";
import { ErrorBox, Loading } from "../components";
import { useAsync } from "../hooks";
import {
  AFFILIATION_LABELS, ageFrom, fmtDate, fmtDateTime, fullName, PATIENT_STATUS_LABELS, SEX_LABELS,
} from "../labels";
import { useSession } from "../session";
import type { Guardian, Institution, PatientDetail, Report } from "../types";
import { ageText, answered, type Anamnesis, type Version } from "./AnamnesisPanel";
import { ANAMNESIS_SECTIONS } from "./anamnesisForm";

/** Dirección del logo de la clínica; cambia cada vez que se sube uno nuevo (así no queda el viejo en caché). */
export function clinicLogoUrl(updatedAt: string): string {
  return `/api/clinic/logo?v=${encodeURIComponent(updatedAt)}`;
}

function PrintLayout({ title, health = false, children }: { title: string; health?: boolean; children: ReactNode }) {
  const { clinic, user } = useSession();
  return (
    <div className="print-page">
      <div className="print-toolbar no-print">
        <button type="button" className="btn btn-primary" onClick={() => window.print()}>
          Imprimir o guardar como PDF
        </button>
        <button type="button" className="btn" onClick={() => window.close()}>Cerrar</button>
        <span className="muted small">
          En el diálogo de impresión, elegí "Guardar como PDF" para obtener el archivo.
        </span>
      </div>
      <header className="print-header">
        <div>
          <span className="print-clinic">
            {clinic.logo_updated_at && (
              <img className="print-logo" src={clinicLogoUrl(clinic.logo_updated_at)} alt={`Logo de ${clinic.name}`} />
            )}
            <strong>{clinic.name}</strong>
          </span>
          <span className="muted small">Nordeste</span>
        </div>
        <h1>{title}</h1>
      </header>
      {children}
      <footer className="print-footer small">
        Impreso el {fmtDateTime(new Date().toISOString())} por {user.full_name}. Documento
        confidencial: contiene datos personales{health || title.startsWith("Informe") ? " y de salud" : ""}.
      </footer>
    </div>
  );
}

function PatientLine({ patient }: { patient: PatientDetail }) {
  const age = ageFrom(patient.birth_date);
  return (
    <dl className="print-facts">
      <dt>Paciente</dt><dd>{fullName(patient)}</dd>
      <dt>Documento</dt><dd>{patient.document_number ?? "—"}</dd>
      <dt>Fecha de nacimiento</dt>
      <dd>{patient.birth_date ? `${fmtDate(patient.birth_date)}${age !== null ? ` (${age} años)` : ""}` : "—"}</dd>
      <dt>Tipo de afiliación</dt><dd>{AFFILIATION_LABELS[patient.affiliation]}</dd>
    </dl>
  );
}

/** Una línea es un título si está escrita en mayúsculas ("DIAGNÓSTICO", "EN SUMA",
 * "ABORDAJE DE FONOAUDIOLOGÍA — Lic. Ana": lo que va después de " — " puede tener minúsculas). */
export function isHeadingLine(line: string): boolean {
  const head = line.trim().split(" — ")[0];
  if (!head || head.length > 120) return false;
  const letters = head.replace(/[^\p{L}]/gu, "");
  return letters.length >= 3 && head === head.toLocaleUpperCase("es");
}

/** Texto del informe tal cual, con los títulos en mayúsculas también en negrita. */
function ReportText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <Fragment key={i}>
          {isHeadingLine(line) ? <strong className="print-heading">{line}</strong> : line}
          {i < lines.length - 1 && "\n"}
        </Fragment>
      ))}
    </>
  );
}

export function PrintReport({ reportId }: { reportId: string }) {
  const report = useAsync(() => api.get<Report>(`/reports/${reportId}`), [reportId]);
  const patient = useAsync(
    () => (report.data ? api.get<PatientDetail>(`/patients/${report.data.patient_id}`) : Promise.resolve(null)),
    [report.data?.patient_id],
  );
  if (report.loading || patient.loading) return <Loading />;
  if (!report.data) return <ErrorBox message={report.error ?? "Informe no encontrado."} />;
  const r = report.data;
  if (r.status !== "final") {
    return <ErrorBox message="Solo se pueden imprimir informes finalizados." />;
  }
  // Informes generados: firman todos los que intervienen; los demás, solo el autor.
  const signers = r.signers.length > 0 ? r.signers : [{ name: r.author_name, specialty: null }];
  return (
    <PrintLayout title={`Informe: ${r.title}`}>
      {patient.data && <PatientLine patient={patient.data} />}
      <dl className="print-facts">
        <dt>{signers.length > 1 ? "Profesionales" : "Profesional"}</dt>
        <dd>{signers.map((s) => s.name).join(", ")}</dd>
        <dt>Finalizado</dt><dd>{r.finalized_at ? fmtDateTime(r.finalized_at) : "—"}</dd>
      </dl>
      <div className="print-body"><ReportText text={r.content} /></div>
      {/* Un espacio de firma por cada profesional que interviene. */}
      <div className="print-signatures">
        {signers.map((s) => (
          <div key={s.name} className="print-signature">
            <span>{s.name}</span>
            {s.specialty && <span className="small">{s.specialty}</span>}
            <span className="muted small">Firma</span>
          </div>
        ))}
      </div>
    </PrintLayout>
  );
}

/** Ficha de anamnesis multidisciplinaria para imprimir: la vigente o, con ``versionId``, una
 * versión anterior. Muestra solo las secciones y preguntas que tienen respuesta. */
export function PrintAnamnesis({ patientId, versionId }: { patientId: string; versionId: string | null }) {
  const patient = useAsync(() => api.get<PatientDetail>(`/patients/${patientId}`), [patientId]);
  const version = useAsync<Version | null>(
    () => (versionId
      ? api.get<Version>(`/patients/${patientId}/anamnesis/${versionId}`)
      : api.get<Anamnesis>(`/patients/${patientId}/anamnesis`).then((a) => a.current)),
    [patientId, versionId],
  );
  const institutions = useAsync(() => api.get<Institution[]>(`/patients/${patientId}/institutions`), [patientId]);
  if (patient.loading || version.loading) return <Loading />;
  if (!patient.data) return <ErrorBox message={patient.error ?? "Paciente no encontrado."} />;
  if (version.error) return <ErrorBox message={version.error} />;
  if (!version.data) return <ErrorBox message="Este paciente todavía no tiene la anamnesis completada." />;
  const p = patient.data;
  const v = version.data;
  const schools = (institutions.data ?? []).filter((i) => i.is_current).map((i) => i.name).join(" · ");
  const interviewee = [v.data.entrevistado_nombre, v.data.entrevistado_parentesco].filter(Boolean).join(" · ");
  return (
    <PrintLayout title="Ficha de anamnesis multidisciplinaria" health>
      <dl className="print-facts">
        <dt>Nombre y apellidos</dt><dd>{fullName(p)}</dd>
        <dt>Documento</dt><dd>{p.document_number ?? "—"}</dd>
        <dt>Fecha de nacimiento</dt><dd>{fmtDate(p.birth_date)}</dd>
        <dt>Edad</dt><dd>{ageText(p.birth_date)}</dd>
        <dt>Escuela</dt><dd>{schools || "—"}</dd>
        <dt>Última actualización</dt><dd>{fmtDateTime(v.created_at)} por {v.author_name}{versionId ? " (versión anterior)" : ""}</dd>
      </dl>
      {ANAMNESIS_SECTIONS.filter((s) => s.id !== "entrevistado").map((s) => {
        const groups = s.groups.map((g) => ({ g, items: answered(g, v.data) })).filter((x) => x.items.length > 0);
        if (groups.length === 0) return null; // secciones sin completar: no ocupan lugar en la hoja
        return (
          <section key={s.id} className="print-section">
            <h2>{s.title}</h2>
            {groups.map(({ g, items }, i) => (
              <div key={g.title ?? i} className="print-group">
                {g.title && <h3>{g.title}</h3>}
                <dl className="print-qa">
                  {items.map(([label, value]) => (
                    <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
                  ))}
                </dl>
              </div>
            ))}
          </section>
        );
      })}
      <div className="print-signatures">
        <div className="print-signature">
          <span>{interviewee || "Persona entrevistada"}</span>
          {interviewee && <span className="small">Persona entrevistada</span>}
          <span className="muted small">Firma</span>
        </div>
        <div className="print-signature">
          <span>Profesional</span>
          <span className="muted small">Firma y aclaración</span>
        </div>
      </div>
    </PrintLayout>
  );
}

export function PrintPatient({ patientId }: { patientId: string }) {
  const patient = useAsync(() => api.get<PatientDetail>(`/patients/${patientId}`), [patientId]);
  const guardians = useAsync(() => api.get<Guardian[]>(`/patients/${patientId}/guardians`), [patientId]);
  if (patient.loading) return <Loading />;
  if (!patient.data) return <ErrorBox message={patient.error ?? "Paciente no encontrado."} />;
  const p = patient.data;
  return (
    <PrintLayout title="Ficha del paciente">
      <dl className="print-facts">
        <dt>Nombre completo</dt><dd>{fullName(p)}</dd>
        <dt>Documento</dt><dd>{p.document_number ?? "—"}</dd>
        <dt>Sexo</dt><dd>{p.sex ? SEX_LABELS[p.sex] : "—"}</dd>
        <dt>Fecha de nacimiento</dt><dd>{fmtDate(p.birth_date)}</dd>
        <dt>Edad</dt><dd>{ageFrom(p.birth_date) ?? "—"}</dd>
        <dt>Tipo de afiliación</dt><dd>{AFFILIATION_LABELS[p.affiliation]}</dd>
        <dt>Teléfono</dt><dd>{p.phone ?? "—"}</dd>
        <dt>Correo</dt><dd>{p.email ?? "—"}</dd>
        <dt>Profesional responsable</dt><dd>{p.responsible_name ?? "Sin asignar"}</dd>
        <dt>Estado</dt><dd>{PATIENT_STATUS_LABELS[p.status]}</dd>
        <dt>Fecha de registro</dt><dd>{fmtDateTime(p.created_at)}</dd>
      </dl>
      <h2>Responsables</h2>
      {guardians.data && guardians.data.length === 0 && <p className="muted">Sin responsables cargados.</p>}
      {guardians.data && guardians.data.length > 0 && (
        <table className="print-table">
          <thead><tr><th>Nombre</th><th>Vínculo</th><th>Teléfono</th><th>Correo</th></tr></thead>
          <tbody>
            {guardians.data.map((g) => (
              <tr key={g.id}>
                <td>{g.full_name}{g.is_primary ? " (contacto principal)" : ""}</td>
                <td>{g.relationship}</td><td>{g.phone ?? "—"}</td><td>{g.email ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </PrintLayout>
  );
}
