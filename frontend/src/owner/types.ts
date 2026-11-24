// Tipos de la pantalla del dueño del sistema (/sistema).

export interface ClinicAdmin {
  id: string; full_name: string; email: string; is_active: boolean; locked: boolean;
  must_change_password: boolean;
}

export interface ClinicSummary {
  /** "independent" = espacio de un profesional independiente; sus "admins" son el titular. */
  id: string; name: string; kind?: "clinic" | "independent"; created_at: string; suspended_at: string | null;
  /** Fecha en que se borraron todos sus datos (queda solo el nombre). */
  purged_at?: string | null;
  branches: number;
  users: number; active_patients: number;
  /** En pausa, y de esos, cuántos tuvieron algún turno realizado en el mes corriente. */
  paused_patients?: number; paused_with_sessions?: number;
  last_activity: string | null; admins: ClinicAdmin[];
}

export interface TemporaryAccess { full_name: string; email: string; temporary_password: string }
