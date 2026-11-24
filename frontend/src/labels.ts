// Textos en español para los valores que guarda el sistema.
import type {
  AccessLevel,
  AffiliationType,
  GoalStatus,
  InstitutionLevel,
  AppointmentStatus,
  NoteKind,
  PatientStatus,
  ReportStatus,
  Sex,
  Role,
} from "./types";

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administración",
  reception: "Recepción",
  professional: "Profesional",
};

export const PATIENT_STATUS_LABELS: Record<PatientStatus, string> = {
  active: "Activo",
  paused: "En pausa",
  discharged: "Alta",
  inactive: "Inactivo",
};

export const PATIENT_STATUS_TONE: Record<PatientStatus, string> = {
  active: "ok",
  paused: "warn",
  discharged: "info",
  inactive: "neutral",
};

export const ACCESS_LABELS: Record<AccessLevel, string> = {
  responsible: "Responsable",
  collaborator: "Colaborador/a",
};

export const APPOINTMENT_STATUS_LABELS: Record<AppointmentStatus, string> = {
  scheduled: "Programado",
  completed: "Realizado",
  no_show: "Ausente",
  cancelled: "Cancelado",
  rescheduled: "Reprogramado",
};

/** Color de la etiqueta de cada estado de turno (los mismos colores que en la grilla). */
export const APPOINTMENT_STATUS_TONE: Record<AppointmentStatus, string> = {
  scheduled: "info",
  completed: "ok",
  no_show: "warn",
  cancelled: "neutral",
  rescheduled: "neutral",
};

export const NOTE_KIND_LABELS: Record<NoteKind, string> = {
  session: "Nota de sesión",
  background: "Antecedentes",
  progress: "Evolución",
  anamnesis: "Anamnesis",
  interview: "Entrevista",
  evaluation: "Evaluación",
  institution: "Reporte de institución",
};

export const INSTITUTION_LEVEL_LABELS: Record<InstitutionLevel, string> = {
  inicial: "Inicial (jardín)",
  primaria: "Primaria",
  secundaria: "Secundaria",
  utu: "UTU / técnica",
  universidad: "Universidad",
  otra: "Otra",
};

export const GOAL_STATUS_LABELS: Record<GoalStatus, string> = {
  active: "En curso",
  achieved: "Logrado",
  discontinued: "Discontinuado",
};

export const GOAL_STATUS_TONE: Record<GoalStatus, string> = { active: "info", achieved: "ok", discontinued: "neutral" };

export const AFFILIATION_LABELS: Record<AffiliationType, string> = {
  private: "Privado",
  ayex: "AYEX",
  military: "Tutela Militar",
  police: "Tutela Policial",
};

export const SEX_LABELS: Record<Sex, string> = {
  male: "Masculino",
  female: "Femenino",
  unspecified: "No especificar",
};

export const REPORT_STATUS_LABELS: Record<ReportStatus, string> = {
  draft: "Borrador",
  final: "Finalizado",
};

export const WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  "auth.login": "Inicio de sesión",
  "auth.login_failed": "Inicio de sesión fallido",
  "auth.login_blocked": "Intento con cuenta bloqueada",
  "auth.login_suspended": "Intento de ingreso con la clínica suspendida",
  "auth.logout": "Cierre de sesión",
  "auth.password_changed": "Cambio de contraseña",
  "clinic.update": "Edición de la clínica",
  "clinic.logo_update": "Cambio del logo de la clínica",
  "clinic.logo_remove": "Se quitó el logo de la clínica",
  "specialty.create": "Alta de especialidad",
  "specialty.update": "Edición de especialidad",
  "user.create": "Alta de usuario",
  "user.update": "Edición de usuario",
  "user.archive": "Cuenta eliminada (archivada)",
  "user.restore": "Cuenta restaurada",
  "user.password_reset": "Contraseña restablecida por administración",
  "branch.create": "Sucursal creada",
  "branch.update": "Sucursal modificada",
  "auth.branch": "Elección de sucursal",
  "patient.list": "Consulta del listado de pacientes",
  "patient.create": "Alta de paciente",
  "patient.import": "Alta de paciente (importación CSV o Cronograma BPS)",
  "patient.import_errors": "Descarga de filas con errores (importación CSV)",
  "institution.create": "Institución educativa agregada",
  "institution.update": "Institución educativa editada",
  "institution.delete": "Institución educativa quitada",
  "patient.export": "Exportación de pacientes (Excel)",
  "bps_payments.check": "Control de pagos del BPS (AYEX)",
  "bps_payments.export": "Descarga del control de pagos del BPS (Excel)",
  "patient.ayex_form": "Formulario AYEX del BPS descargado",
  "patient.bps_schedule": "Cronograma BPS descargado",
  "notice.create": "Aviso a profesionales",
  "notice.read": "Aviso marcado como leído",
  "notice.withdraw": "Aviso retirado",
  "cash.open": "Caja abierta",
  "cash.movement": "Movimiento de caja (entrada o salida)",
  "cash.void": "Movimiento de caja anulado",
  "cash.close": "Cierre de caja",
  "cash.reopen": "Caja reabierta por administración",
  "goal.list": "Consulta del plan de tratamiento",
  "goal.create": "Objetivo creado",
  "goal.update": "Avance de objetivo registrado",
  "summary.export": "Exportación del informe mensual (Excel)",
  "patient.view": "Consulta de ficha de paciente",
  "patient.update": "Edición de paciente",
  "access.list": "Consulta de accesos",
  "access.grant": "Acceso concedido",
  "access.revoke": "Acceso revocado",
  "access.transfer": "Cambio de responsable",
  "availability.create": "Alta de disponibilidad",
  "availability.delete": "Baja de disponibilidad",
  "appointment.create": "Turno creado",
  "appointment.cancel": "Turno cancelado",
  "appointment.reschedule": "Turno reprogramado",
  "appointment.reassign": "Turno pasado a otro profesional",
  "appointment.status": "Resultado de turno",
  "clinical_record.view": "Consulta de historia clínica",
  "clinical_note.create": "Nota clínica creada",
  "clinical_note.correct": "Nota clínica corregida",
  "anamnesis.view": "Consulta de anamnesis",
  "anamnesis.save": "Anamnesis guardada",
  "report_section.view": "Consulta de antecedentes, diagnóstico, encuadre o abordaje",
  "report_section.save": "Antecedentes, diagnóstico, encuadre o abordaje guardado",
  "report.participation": "Informe: profesional marcado como que participa o no",
  "report.list": "Consulta de informes",
  "report.create": "Informe creado",
  "report.view": "Consulta de informe",
  "report.update": "Informe editado",
  "report.finalize": "Informe finalizado",
  "guardian.create": "Responsable agregado",
  "guardian.update": "Responsable editado",
  "guardian.delete": "Responsable quitado",
  "file.list": "Consulta de archivos",
  "file.view": "Archivo visto en pantalla",
  "file.upload": "Archivo subido",
  "file.download": "Archivo descargado",
  "file.withdraw": "Archivo retirado",
  "degree.upload": "Título universitario subido",
  "account.update": "Datos personales actualizados (Mi cuenta)",
  "degree.view": "Consulta de título universitario",
  "degree.download": "Título universitario descargado",
  "system.clinic_create": "Clínica dada de alta en Nordeste",
  "system.user_create": "Primer administrador creado",
  "system.clinic_suspended": "Acceso a la clínica suspendido",
  "system.clinic_reactivated": "Acceso a la clínica reactivado",
  "system.admin_password_reset": "Contraseña de administración restablecida por soporte",
  "system.feature_enabled": "Función habilitada por soporte",
  "system.feature_disabled": "Función deshabilitada por soporte",
  "system.clinic_export": "Exportación completa de los datos de la clínica (por soporte)",
  "system.clinic_converted": "El consultorio independiente pasó a ser una clínica (por soporte)",
};

/** Nombres de las funciones que se habilitan o deshabilitan por clínica. */
export const FEATURE_LABELS: Record<string, string> = {
  caja: "Caja",
  bps: "BPS y AYEX",
  avisos: "Avisos",
  informe_mensual: "Informe mensual",
  objetivos: "Objetivos",
  archivos: "Archivos",
};

/** Auditoría del dueño del sistema (pantalla /sistema). */
export const OWNER_ACTION_LABELS: Record<string, string> = {
  "owner.created": "Cuenta de dueño creada (comando del servidor)",
  "owner.reset": "Cuenta de dueño restablecida (comando del servidor)",
  "owner.login": "Inicio de sesión",
  "owner.login_failed": "Inicio de sesión fallido",
  "owner.login_blocked": "Intento con cuenta bloqueada",
  "owner.logout": "Cierre de sesión",
  "owner.password_changed": "Cambio de contraseña",
  "owner.totp_enabled": "Código del celular configurado",
  "owner.clinic_create": "Alta de clínica",
  "owner.clinic_suspend": "Clínica suspendida",
  "owner.clinic_reactivate": "Clínica reactivada",
  "owner.admin_password_reset": "Contraseña de administrador restablecida",
  "owner.feature_enable": "Función habilitada",
  "owner.feature_disable": "Función deshabilitada",
  "owner.clinic_export": "Exportación completa de datos (.zip)",
  "owner.clinic_convert": "Espacio independiente convertido en clínica",
  "owner.clinic_purge": "Datos de la clínica borrados",
};

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  // Las fechas sin hora ("2026-01-31") se muestran tal cual, sin conversión de zona.
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

// Horas siempre en formato de 24 horas ("16:30"): el formato por defecto de es-UY es de
// 12 horas ("04:30 p. m."), que no coincide con la grilla y que el campo de hora no acepta.
export function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("es-UY", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
}

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("es-UY", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

/** Fecha "AAAA-MM-DD" en la hora local (toISOString usaría UTC y de noche daría "mañana"). */
export function isoDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Hoy, como "AAAA-MM-DD" en la hora local. */
export function todayLocal(): string {
  return isoDate(new Date());
}

/** Edad en años a partir de una fecha "AAAA-MM-DD". */
export function ageFrom(iso: string | null): number | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  const now = new Date();
  let age = now.getFullYear() - y;
  if (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d)) age -= 1;
  return age;
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function fullName(p: { first_name: string; middle_name?: string | null; last_name: string; second_last_name?: string | null }): string {
  return [p.first_name, p.middle_name, p.last_name, p.second_last_name].filter(Boolean).join(" ");
}

/** Suma meses de calendario a "AAAA-MM-DD"; si el día no existe (31/04) usa el último del mes. */
export function addMonthsIso(iso: string, months: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const total = y * 12 + (m - 1) + months;
  const year = Math.floor(total / 12), month = total % 12 + 1;
  const lastDay = new Date(year, month, 0).getDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(Math.min(d, lastDay)).padStart(2, "0")}`;
}

/** Estado del vencimiento del AYEX respecto de hoy (igual que el aviso del Inicio):
 *  "expired" ya venció; "red" vence en 2 meses o menos; "yellow" entre 2 y 3 meses; "ok" vigente. */
export function ayexState(iso: string | null | undefined): "expired" | "red" | "yellow" | "ok" | null {
  if (!iso) return null;
  const today = todayLocal();
  if (iso < today) return "expired";
  if (iso <= addMonthsIso(today, 2)) return "red";
  if (iso <= addMonthsIso(today, 3)) return "yellow";
  return "ok";
}

/** Enlace para llamar desde el celular: solo dígitos y "+". */
export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}
