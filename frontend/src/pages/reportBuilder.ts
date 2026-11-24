// "Generar informe": arma el texto del informe de evolución con lo cargado en la ficha del
// paciente (Info. general, Instituciones, Anamnesis, Diagnóstico, Antecedentes, Encuadre y el
// Abordaje de cada profesional con su "En suma" y sus "Sugerencias"). El resultado se guarda
// como borrador: se revisa, se completa y se finaliza como cualquier informe.
import { api } from "../api";
import { fmtDate, fullName } from "../labels";
import type { ClinicDetail, Institution, PatientDetail } from "../types";
import { abordajeTitle, type AbordajeState, type ReportSections } from "./ReportSectionsPanel";

export const REPORT_MAX_CHARS = 60000;

const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];

function yearsOld(birth: string | null, today: Date): string | null {
  if (!birth) return null;
  const [y, m, d] = birth.split("-").map(Number);
  let age = today.getFullYear() - y;
  if (today.getMonth() + 1 < m || (today.getMonth() + 1 === m && today.getDate() < d)) age -= 1;
  return age === 1 ? "1 año" : `${age} años`;
}

/** "A, B y C". */
function joinList(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} y ${items[items.length - 1]}`;
}

export interface GeneratedReport {
  title: string;
  content: string;
  signer_ids: string[]; // cada profesional con abordaje (el autor se agrega solo)
  section_version_ids: string[]; // versiones vigentes con que se armó (para saber si quedó viejo)
}

export function buildReport({ patient, clinic, sections, institutions, grade, today = new Date() }: {
  patient: PatientDetail;
  clinic: ClinicDetail | null;
  sections: ReportSections;
  institutions: Institution[];
  grade?: string; // "Grado que cursa" de la anamnesis
  today?: Date;
}): GeneratedReport | null {
  const text = (s: { current: { data: Record<string, string> } | null }, key = "texto") =>
    s.current?.data[key]?.trim() ?? "";
  const abordajes = sections.abordajes.filter((a) => a.current && Object.keys(a.current.data).length > 0);
  const diagnostico = text(sections.diagnostico);
  const antecedentes = text(sections.antecedentes);
  const encuadre = text(sections.encuadre);
  if (!diagnostico && !antecedentes && !encuadre && abordajes.length === 0) return null;

  const blocks: string[] = [];
  const place = clinic?.address_department || clinic?.address_locality;
  const month = MONTHS[today.getMonth()];
  blocks.push(place ? `${place}, ${month} de ${today.getFullYear()}.`
                    : `${month.charAt(0).toUpperCase()}${month.slice(1)} de ${today.getFullYear()}.`);

  const schools = institutions.filter((i) => i.is_current).map((i) => i.name).join(" / ");
  const school = [grade, schools].filter(Boolean).join(" en ");
  const facts = [
    `Nombre: ${fullName(patient)}`,
    patient.document_number && `C.I.: ${patient.document_number}`,
    patient.birth_date && `Fecha de nacimiento: ${fmtDate(patient.birth_date)}`,
    yearsOld(patient.birth_date, today) && `Edad cronológica: ${yearsOld(patient.birth_date, today)}`,
    school && `Institución educativa: ${school}`,
  ].filter(Boolean);
  blocks.push(facts.join("\n"));

  // Títulos en mayúsculas; el nombre del profesional ("— Lic. Ana") queda como está.
  const upper = (h: string) => { const [first, ...rest] = h.split(" — "); return [first.toUpperCase(), ...rest].join(" — "); };
  const section = (heading: string, body: string) => { if (body) blocks.push(`${upper(heading)}\n${body}`); };
  section("Diagnóstico", diagnostico);
  section("Antecedentes", antecedentes);
  section("Encuadre", encuadre);
  for (const a of abordajes) section(abordajeTitle(a, abordajes), a.current!.data.abordaje?.trim() ?? "");

  // "En suma" y "Sugerencias": lo de cada profesional; con más de uno, se indica de quién es.
  const merged = (key: string) => {
    const parts = abordajes
      .map((a) => [a, a.current!.data[key]?.trim() ?? ""] as [AbordajeState, string])
      .filter(([, body]) => body);
    if (parts.length <= 1) return parts.map(([, body]) => body).join("");
    return parts.map(([a, body]) => `${a.specialty_name ?? a.owner_name}:\n${body}`).join("\n\n");
  };
  section("En suma", merged("en_suma"));
  section("Sugerencias", merged("sugerencias"));

  if (abordajes.length > 0) {
    blocks.push(`Profesionales intervinientes:\n${abordajes
      .map((a) => `${a.owner_name}${a.specialty_name ? ` — ${a.specialty_name}` : ""}`).join("\n")}`);
  }

  const specialties = [...new Set(abordajes.map((a) => a.specialty_name).filter((s): s is string => !!s))];
  let title = specialties.length ? `Informe de evolución de ${joinList(specialties)}` : "Informe de evolución";
  if (title.length > 200) title = `${title.slice(0, 197)}…`;
  const versionIds = [sections.antecedentes, sections.diagnostico, sections.encuadre, ...sections.abordajes]
    .flatMap((s) => (s.current ? [s.current.id] : []));
  return { title, content: blocks.join("\n\n"), signer_ids: abordajes.map((a) => a.owner_id),
           section_version_ids: versionIds };
}

/** Junta los datos de la ficha y arma el informe (no lo guarda). */
export async function generateReport(patientId: string): Promise<GeneratedReport | null> {
  const [patient, clinic, sections, institutions, anamnesis] = await Promise.all([
    api.get<PatientDetail>(`/patients/${patientId}`),
    api.get<ClinicDetail>("/clinic").catch(() => null),
    api.get<ReportSections>(`/patients/${patientId}/report-sections`),
    api.get<Institution[]>(`/patients/${patientId}/institutions`).catch(() => [] as Institution[]),
    api.get<{ current: { data: Record<string, string> } | null }>(`/patients/${patientId}/anamnesis`)
      .catch(() => ({ current: null })),
  ]);
  return buildReport({ patient, clinic, sections, institutions, grade: anamnesis.current?.data.grado });
}
