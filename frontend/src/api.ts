// Cliente de la API. La sesión viaja en una cookie HttpOnly (JavaScript no la ve);
// el token CSRF se guarda solo en memoria y se envía en cada petición que modifica datos.
import { notify } from "./toast";

export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  status: number;
  fieldErrors: FieldError[];

  constructor(status: number, message: string, fieldErrors: FieldError[] = []) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }

  /** Mensaje completo para mostrar, con los errores por campo si los hay. */
  get fullMessage(): string {
    if (this.fieldErrors.length === 0) return this.message;
    return `${this.message} ${this.fieldErrors.map((e) => e.message).join(" ")}`;
  }
}

let csrfToken: string | null = null;
// Última respuesta del servidor con la sesión válida: cada petición renueva la sesión
// (ver el aviso de sesión por vencer en SessionWarning.tsx).
let lastActivity = Date.now();

export function lastServerActivity(): number {
  return lastActivity;
}
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export const BRANCH_MISSING = "Elegí una sucursal para continuar.";
let onBranchMissing: (() => void) | null = null;

/** Si la sucursal de la sesión deja de ser válida, la aplicación vuelve a pedir que se elija. */
export function setBranchMissingHandler(handler: (() => void) | null) {
  onBranchMissing = handler;
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

type Query = Record<string, string | undefined>;

// Peticiones que modifican algo pero no son "cambios" para avisar (entrar, salir, elegir sucursal).
const QUIET_PATHS = new Set(["/auth/login", "/auth/logout", "/auth/branch",
  "/owner/auth/login", "/owner/auth/logout", "/owner/auth/totp/start"]);

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  return (await requestFull<T>(method, path, body, query)).data;
}

async function requestFull<T>(method: string, path: string, body?: unknown,
                              query?: Query): Promise<{ data: T; headers: Headers }> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let url = `/api${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== "") params.set(k, v);
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servidor. ¿Está iniciado el backend?");
  }

  if (response.ok) lastActivity = Date.now();
  if (response.status === 204) {
    if (method !== "GET" && !QUIET_PATHS.has(path)) notify();
    return { data: undefined as T, headers: response.headers };
  }
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const payload = (data ?? {}) as { detail?: unknown; errors?: FieldError[] };
    const message =
      typeof payload.detail === "string" ? payload.detail : "Ocurrió un error. Intentá nuevamente.";
    if (response.status === 401 && !path.endsWith("/auth/login") && onUnauthorized) onUnauthorized();
    if (response.status === 409 && message === BRANCH_MISSING && onBranchMissing) onBranchMissing();
    throw new ApiError(response.status, message, payload.errors ?? []);
  }
  if (method !== "GET" && !QUIET_PATHS.has(path)) notify();
  return { data: data as T, headers: response.headers };
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query),
  /** Listados paginados: devuelve la página y el total (cabecera X-Total-Count). */
  getPage: async <T>(path: string, query?: Query): Promise<{ items: T[]; total: number }> => {
    const { data, headers } = await requestFull<T[]>("GET", path, undefined, query);
    return { items: data, total: Number(headers.get("X-Total-Count") ?? data.length) };
  },
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

/** Sube un archivo tal cual (sin convertirlo) y devuelve la respuesta de la API. */
export async function uploadFile<T>(path: string, file: File, query: Record<string, string>,
                                   { quiet = query.dry_run === "true" }: { quiet?: boolean } = {}): Promise<T> {
  const params = new URLSearchParams(query).toString();
  const headers: Record<string, string> = { "Content-Type": "application/octet-stream" };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let response: Response;
  try {
    response = await fetch(`/api${path}?${params}`, {
      method: "POST", headers, body: file, credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servidor. ¿Está iniciado el backend?");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : "No se pudo subir el archivo.";
    throw new ApiError(response.status, detail);
  }
  if (!quiet) notify();  // una revisión (como la vista previa de la importación) no cambia nada
  return data as T;
}

/** Envía un archivo y descarga lo que devuelve el servidor (por ejemplo, un CSV). */
export async function uploadAndDownload(path: string, file: File, filename: string): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/octet-stream" };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { method: "POST", headers, body: file, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servidor. ¿Está iniciado el backend?");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data && typeof data.detail === "string" ? data.detail : "No se pudo descargar el archivo.";
    throw new ApiError(response.status, detail);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.fullMessage;
  return "Ocurrió un error inesperado.";
}
