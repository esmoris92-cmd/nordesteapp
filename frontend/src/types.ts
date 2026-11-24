// Tipos que reflejan las respuestas de la API (backend/app/schemas.py).

export type Role = "admin" | "reception" | "professional";
export type PatientStatus = "active" | "paused" | "discharged" | "inactive";
export type AccessLevel = "responsible" | "collaborator";
export type AppointmentStatus = "scheduled" | "completed" | "no_show" | "cancelled" | "rescheduled";
export type NoteKind = "session" | "background" | "progress" | "anamnesis" | "interview" | "evaluation"
  | "institution";
export type InstitutionLevel = "inicial" | "primaria" | "secundaria" | "utu" | "universidad" | "otra";
export type Sex = "male" | "female" | "unspecified";
export type AffiliationType = "private" | "ayex" | "military" | "police";
export type ReportStatus = "draft" | "final";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  specialty_id: string | null;
  specialty_name: string | null;
  is_active: boolean;
  archived_at: string | null;
  max_concurrent_patients: number;
  must_change_password: boolean;
  branch_ids: string[];
  document_number?: string | null; // C.I. (null en cuentas creadas antes de exigirla)
  phone?: string | null;
  // Datos para el Cronograma BPS (los profesionales los completan en "Mi cuenta").
  first_name?: string | null;
  middle_name?: string | null;
  last_name?: string | null;
  second_last_name?: string | null;
  bps_training?: string | null;
  degree_issuer?: string | null;
  // Título universitario (solo profesionales): el actual, o null si todavía no lo subió.
  degree_id?: string | null;
  degree_uploaded_at?: string | null;
}

export interface Degree {
  id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface Branch {
  id: string;
  name: string;
  is_active: boolean;
}

export interface Specialty {
  id: string;
  name: string;
  is_active: boolean;
  professional_count: number;
  bps_activity: string | null; // actividad del BPS elegida por Administración
  bps_activity_auto: string | null; // la que se usa si no se eligió (por el nombre)
}

/** Listas del BPS para el Cronograma. */
export interface BpsLists {
  trainings: string[];
  degree_issuers: string[];
  activities: string[];
}

export interface Clinic {
  id: string;
  name: string;
  timezone: string;
  /** "independent" = espacio de un profesional independiente (una sola cuenta, el titular). */
  kind?: ClinicKind;
  /** Funciones habilitadas para la clínica (las decide el dueño del sistema en /sistema). */
  features: Feature[];
  /** Cuándo se subió el logo; null = la clínica no tiene logo. */
  logo_updated_at?: string | null;
}

export type ClinicKind = "clinic" | "independent";

/** Funciones que el dueño del sistema puede habilitar o deshabilitar por clínica. */
export type Feature = "caja" | "bps" | "avisos" | "informe_mensual" | "objetivos" | "archivos";

/** Datos de la clínica como proveedor del BPS (formulario de AYEX). */
export interface ClinicDetail extends Clinic {
  bps_provider_number: string | null;
  bps_company_number: string | null;
  phone: string | null;
  email: string | null;
  address_street: string | null;
  address_number: string | null;
  address_locality: string | null;
  address_department: string | null;
  address_annex: string | null;
  transport_included: boolean | null;
  monthly_budget: string | null;
  /** Arancel AYEX: lo que paga el BPS por paciente y por mes. */
  ayex_fee: number | null;
}

/** Domicilio del paciente (opcional). */
export interface PatientAddress {
  address_department?: string | null;
  address_locality?: string | null;
  address_street?: string | null;
  address_number?: string | null;
  address_apartment?: string | null;
  address_solar?: string | null;
  address_block?: string | null;
}

export interface SessionInfo {
  user: User;
  clinic: Clinic;
  csrf_token: string;
  branches: Branch[];
  active_branch: Branch | null;
  idle_minutes: number; // minutos sin actividad hasta que la sesión se cierra
  expires_at: string | null; // cierre máximo de la sesión
}

export interface Professional {
  id: string;
  full_name: string;
  specialty_id: string | null;
  specialty_name: string | null;
  branch_ids: string[];
}

export interface Patient extends PatientAddress {
  id: string;
  first_name: string;
  middle_name: string | null;
  last_name: string;
  second_last_name: string | null;
  document_number: string | null;
  sex: Sex | null;
  affiliation: AffiliationType;
  ayex_expires_on: string | null;
  birth_date: string | null;
  phone: string | null;
  email: string | null;
  status: PatientStatus;
  created_at: string;
  responsible_name?: string | null;
  responsible_id?: string | null;
  collaborator_names?: string[];
  no_shows_month?: number; // inasistencias del mes en curso (solo en el listado)
  branch_id: string;
  branch_name?: string | null;
}

export interface PatientDetail extends Patient {
  my_access_level: AccessLevel | null;
  can_view_clinical: boolean;
  can_view_reports: boolean;
  can_edit: boolean;
  can_manage_access: boolean;
  future_appointments: number;
}

export interface Access {
  id: string;
  user_id: string;
  user_name: string;
  level: AccessLevel;
  reason: string | null;
  granted_by_name: string;
  granted_at: string;
  revoked_by_name: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
  future_appointments: number;
}

export interface AvailabilityBlock {
  id: string;
  professional_id: string;
  branch_id: string;
  branch_name: string | null;
  weekday: number;
  start_time: string;
  end_time: string;
}

export interface Appointment {
  id: string;
  patient_id: string;
  patient_name: string;
  professional_id: string;
  professional_name: string;
  branch_id: string;
  branch_name: string | null;
  starts_at: string;
  ends_at: string;
  status: AppointmentStatus;
  cancel_reason: string | null;
  rescheduled_to_id: string | null;
  reschedule_reason: string | null;
  rescheduled_to_starts_at: string | null; // nueva fecha y hora, si se reprogramó
  no_show_reason: string | null; // por qué no vino, si se marcó ausente
}

/** Un turno marcado como ausente, en el historial del paciente (pestaña Turnos). */
export interface Absence {
  id: string;
  starts_at: string;
  professional_name: string;
  branch_name: string | null;
  reason: string | null;
  marked_by: string | null;
  marked_at: string | null;
}

/** Una reprogramación en el historial del paciente (pestaña Turnos). */
export interface Reschedule {
  id: string;
  from_starts_at: string;
  to_starts_at: string | null;
  to_status: AppointmentStatus | null;
  professional_name: string;
  to_professional_name: string | null;
  reason: string | null;
  rescheduled_by: string | null;
  rescheduled_at: string | null;
}

export interface Note {
  id: string;
  patient_id: string;
  author_id: string;
  author_name: string;
  kind: NoteKind;
  session_date: string | null;
  content: string;
  supersedes_id: string | null;
  correction_reason: string | null;
  superseded_by_id: string | null;
  created_at: string;
  institution_id?: string | null; // reportes de institución
}

export interface Institution {
  id: string;
  name: string;
  level: InstitutionLevel;
  phone: string | null;
  email: string | null;
  is_current: boolean;
}

export interface ReportSummary {
  id: string;
  patient_id: string;
  author_id: string;
  author_name: string;
  title: string;
  status: ReportStatus;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
  /** Armado con "Generar informe": lo finaliza solo el responsable, con todos los abordajes. */
  generated: boolean;
}

export interface ReportSigner {
  user_id: string;
  name: string;
  specialty: string | null;
}

export interface ReportPerson {
  user_id: string;
  name: string;
  specialty: string | null;
}

/** Qué falta para finalizar un informe generado. */
export interface ReportReadiness {
  stale: boolean;
  missing: ReportPerson[];
  excluded: ReportPerson[];
  can_close: boolean;
  responsible_name: string | null;
}

export interface Report extends ReportSummary {
  content: string;
  /** Quienes firman (informe generado). Vacío = firma solo el autor. */
  signers: ReportSigner[];
}

export interface AuditEvent {
  id: number;
  created_at: string;
  actor_name: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  patient_id: string | null;
  details: Record<string, unknown>;
  patient_name: string | null;
}

export interface Guardian {
  id: string;
  full_name: string;
  document_number: string | null; // null solo en responsables cargados antes de exigir la C.I.
  // Primer nombre y primer apellido por separado (null en los cargados antes de separarlos).
  first_name: string | null;
  middle_name: string | null;
  last_name: string | null;
  second_last_name: string | null;
  relationship: string;
  phone: string | null;
  email: string | null;
  is_primary: boolean;
  notes: string | null;
}

export interface PatientFile {
  id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  description: string | null;
  uploaded_by_name: string;
  created_at: string;
  withdrawn_at: string | null;
  withdrawn_by_name: string | null;
  withdraw_reason: string | null;
  can_withdraw: boolean;
  institution_id?: string | null;
  institution_name?: string | null;
}

export interface ResponsiblePatient {
  id: string;
  full_name: string;
  document_number: string | null;
  status: PatientStatus;
}

export interface ImportRow {
  line: number;
  status: "ok" | "error" | "created" | "skipped";  // skipped: ya está en Nordeste (Cronograma BPS)
  document_number: string | null;
  full_name: string;
  affiliation: AffiliationType | null;
  branch_name: string | null;
  birth_date: string | null;
  responsible_name: string | null;
  errors: string[];
  note: string | null;
}

export interface ImportResult {
  total: number;
  valid: number;
  invalid: number;
  created: number;
  skipped: number;
  ignored_columns: string[];
  rows: ImportRow[];
}

export type GoalStatus = "active" | "achieved" | "discontinued";

export interface GoalUpdate {
  id: string;
  author_name: string;
  session_date: string | null;
  progress: number;
  new_status: GoalStatus | null;
  note: string;
  created_at: string;
}

export interface Goal {
  id: string;
  area: string;
  description: string;
  target_date: string | null;
  status: GoalStatus;
  progress: number;
  created_by_name: string;
  created_at: string;
  updates: GoalUpdate[];
}

/** Aviso de Recepción o Administración a profesionales (lo que ve quien lo dejó). */
export interface Notice {
  id: string;
  message: string;
  author_name: string;
  branch_name: string | null;
  to_all: boolean;
  created_at: string;
  withdrawn_at: string | null;
  recipients: { user_id: string; full_name: string; read_at: string | null }[];
}

/** Aviso sin leer del profesional (barra amarilla). */
export interface MyNotice {
  id: string;
  message: string;
  author_name: string;
  author_role: Role;
  created_at: string;
}

// ---------- Caja ----------

export interface CashMovement {
  id: string;
  kind: "income" | "expense";
  amount: number;
  concept: string;
  created_by_name: string;
  created_at: string;
  voided_at: string | null;
  voided_by_name: string | null;
  void_reason: string | null;
}

export interface CashRegister {
  id: string;
  branch_id: string;
  branch_name: string;
  business_date: string;
  status: "open" | "closed";
  opening_amount: number;
  income: number;
  expense: number;
  expected_amount: number;
  counted_amount: number | null;
  difference: number | null; // positivo = sobrante, negativo = faltante
  closing_note: string | null;
  opened_by_name: string;
  opened_at: string;
  closed_by_name: string | null;
  closed_at: string | null;
  reopen_count: number;
  movements: CashMovement[] | null;
}

export interface CashToday {
  today: string;
  branch_id: string;
  branch_name: string;
  current: CashRegister | null;
  pending: CashRegister[];
  suggested_opening: number | null;
}

export interface CashTotals {
  income: number;
  expense: number;
  net: number;
  difference: number;
  registers: number;
  open_registers: number;
}

export interface CashBalance {
  period: "week" | "month" | "year";
  start: string;
  end: string;
  scope: "branch" | "clinic";
  branch_name: string | null;
  totals: CashTotals;
  rows: (CashTotals & { key: string; register_id: string | null })[];
  by_branch: (CashTotals & { branch_id: string; branch_name: string })[];
}

/** Control de los pagos AYEX del BPS (PDF "Detalle de Item Facturable"). */
export type BpsIssueKind = "underpaid" | "overpaid" | "not_in_bps" | "not_patient" | "not_ayex" | "duplicate";

export interface BpsIssue {
  kind: BpsIssueKind;
  document: string | null;
  name: string;
  patient_id: string | null;
  branch_name: string | null;
  month: string | null;
  amount: number | null;
  expected: number | null;
  difference: number | null;
  note: string | null;
}

export interface BpsCheck {
  fee: number;
  months: string[];
  row_count: number;
  ok_count: number;
  rows_total: number;
  invoice_total: number | null;
  totals_match: boolean | null;
  missing_amount: number;
  issues: BpsIssue[];
}
