import { createContext, useContext } from "react";
import type { Branch, Clinic, Feature, User } from "./types";

export interface Session {
  user: User;
  clinic: Clinic;
  /** Sucursal activa y sucursales a las que puede entrar esta cuenta. */
  branch: Branch;
  branches: Branch[];
  switchBranch: (branchId: string) => Promise<void>;
  logout: () => void;
  /** Vuelve a leer los datos de la sesión (por ejemplo, después de subir el título). */
  refresh: () => Promise<void>;
}

export const SessionContext = createContext<Session | null>(null);

/** ¿La clínica tiene habilitada esta función? (Si no, se oculta: la API también la rechaza.) */
export function hasFeature(clinic: Pick<Clinic, "features">, feature: Feature): boolean {
  return (clinic.features ?? []).includes(feature);
}

/** ¿Es el espacio de un profesional independiente (en vez de una clínica)? */
export function isIndependent(clinic: Pick<Clinic, "kind">): boolean {
  return clinic.kind === "independent";
}

/** El profesional de un espacio independiente: además de atender, carga sus pacientes y los
 * datos del consultorio (no hay Administración ni Recepción). */
export function isTitular(user: Pick<User, "role">, clinic: Pick<Clinic, "kind">): boolean {
  return user.role === "professional" && isIndependent(clinic);
}

/** ¿Puede dar, reprogramar y cancelar turnos y cambiar horarios? Recepción y Administración;
 * en un espacio independiente, el titular (no tiene Recepción). Un profesional de una clínica,
 * no: ve la agenda y marca sus turnos como realizados o ausentes. */
export function canSchedule(user: Pick<User, "role">, clinic: Pick<Clinic, "kind">): boolean {
  return user.role === "admin" || user.role === "reception" || isTitular(user, clinic);
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession debe usarse dentro de una sesión iniciada");
  return session;
}
