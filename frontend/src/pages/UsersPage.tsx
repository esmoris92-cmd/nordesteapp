import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, uploadFile } from "../api";
import { askConfirm } from "../confirm";
import { Badge, Card, Dialog, Empty, ErrorBox, Field, Loading, WarnBox } from "../components";
import { useAction, useAsync } from "../hooks";
import { fmtDateTime, PATIENT_STATUS_LABELS, ROLE_LABELS } from "../labels";
import { hasFeature, isIndependent, useSession } from "../session";
import { notify } from "../toast";
import { BpsFields, bpsForm, bpsMissing, bpsPayload, useBpsLists, type BpsForm } from "./BpsFields";
import { DocumentViewer } from "./FilesPanel";
import { clinicLogoUrl } from "./PrintPage";
import type {
  Appointment, AvailabilityBlock, Branch, ClinicDetail, Degree, Professional, ResponsiblePatient, Specialty, User,
} from "../types";

type UsersTab = "cuentas" | "clinica" | "sucursales" | "especialidades";
const USERS_TABS: [UsersTab, string][] = [
  ["cuentas", "Cuentas"], ["clinica", "Clínica"], ["sucursales", "Sucursales"], ["especialidades", "Especialidades"],
];

export function UsersPage() {
  const { user: me, clinic } = useSession();
  const [tab, setTab] = useState<UsersTab>("cuentas");
  const [showArchived, setShowArchived] = useState(false);
  const users = useAsync(
    () => api.get<User[]>("/users", { include_archived: showArchived ? "true" : undefined }),
    [showArchived],
  );
  // Todas las especialidades (también las desactivadas: el administrador las gestiona).
  const specialties = useAsync(
    () => api.get<Specialty[]>("/specialties", { include_inactive: "true" }), [],
  );
  const allSpecialties = specialties.data ?? [];
  const branches = useAsync(() => api.get<Branch[]>("/branches"), []);
  const allBranches = branches.data ?? [];
  const action = useAction();
  const [editing, setEditing] = useState<User | null>(null);
  const [creating, setCreating] = useState(false);
  const [archiving, setArchiving] = useState<User | null>(null);
  const [viewingDegree, setViewingDegree] = useState<User | null>(null);
  // Contraseña temporal recién generada (al crear una cuenta o al restablecerla).
  const [tempPassword, setTempPassword] = useState<{ name: string; password: string; isNew: boolean } | null>(null);
  // A9: buscador y filtros de cuentas (en la pantalla: la lista de cuentas de una clínica es corta).
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [branchFilter, setBranchFilter] = useState("");
  const plain = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const terms = plain(search).split(/\s+/).filter(Boolean);
  const shown = (users.data ?? []).filter((u) => {
    if (roleFilter && u.role !== roleFilter) return false;
    if (branchFilter && u.role !== "admin" && !u.branch_ids.includes(branchFilter)) return false;
    const haystack = plain(`${u.full_name} ${u.email} ${u.document_number ?? ""}`);
    return terms.every((t) => haystack.includes(t));
  });
  const anyFilter = Boolean(search.trim() || roleFilter || branchFilter);

  async function toggle(u: User) {
    const verb = u.is_active ? "desactivar" : "reactivar";
    if (!await askConfirm(`¿Seguro que querés ${verb} la cuenta de ${u.full_name}?`,
                          { confirmLabel: u.is_active ? "Desactivar" : "Reactivar", danger: u.is_active })) return;
    const ok = await action.run(async () => {
      await api.patch(`/users/${u.id}`, { is_active: !u.is_active });
    });
    if (ok) users.reload();
  }

  async function resetPassword(u: User) {
    if (!await askConfirm(
      `¿Restablecer la contraseña de ${u.full_name}?\n\n` +
      "Se le dará una contraseña temporal y se cerrarán sus sesiones abiertas. " +
      "Al entrar deberá elegir una nueva.",
      { confirmLabel: "Restablecer" },
    )) return;
    await action.run(async () => {
      const r = await api.post<{ temporary_password: string }>(`/users/${u.id}/reset-password`);
      setTempPassword({ name: u.full_name, password: r.temporary_password, isNew: false });
      notify("Contraseña restablecida.");
    });
  }

  async function restore(u: User) {
    const ok = await action.run(async () => { await api.post(`/users/${u.id}/restore`); });
    if (ok) users.reload();
  }

  return (
    <>
      <div className="page-title"><h1>Usuarios de la clínica</h1></div>
      <nav className="page-tabs" role="tablist" aria-label="Secciones de Usuarios">
        {USERS_TABS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key}
                  className={tab === key ? "ptab active" : "ptab"} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>
      <div role="tabpanel">
        {tab === "clinica" && <><ClinicCard /><LogoCard /></>}
        {tab === "sucursales" && (
          <BranchesCard branches={allBranches} loading={branches.loading} error={branches.error}
                        onChanged={() => { branches.reload(); users.reload(); }} />
        )}
        {tab === "especialidades" && (
          <SpecialtiesCard
            specialties={allSpecialties}
            loading={specialties.loading}
            error={specialties.error}
            onChanged={() => { specialties.reload(); users.reload(); }}
          />
        )}
        {tab === "cuentas" && (
          <Card
            title="Cuentas"
            actions={(
              <div className="title-actions">
                <label className="checkbox">
                  <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
                  Mostrar eliminadas
                </label>
                <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                  Nueva cuenta
                </button>
              </div>
            )}
          >
            <ErrorBox message={action.error} />
            <div className="toolbar users-filters">
              <Field label="Buscar">
                {(id) => <input id={id} type="search" placeholder="Nombre, correo o C.I." value={search}
                                onChange={(e) => setSearch(e.target.value)} />}
              </Field>
              <Field label="Rol">
                {(id) => (
                  <select id={id} value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                    <option value="">Todos</option>
                    {Object.entries(ROLE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                )}
              </Field>
              <Field label="Sucursal">
                {(id) => (
                  <select id={id} value={branchFilter} onChange={(e) => setBranchFilter(e.target.value)}>
                    <option value="">Todas</option>
                    {allBranches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                )}
              </Field>
            </div>
            {users.data && (
              <p className="muted small users-count" role="status">
                {anyFilter ? `${shown.length} de ${users.data.length} cuentas` : `${users.data.length} cuentas`}
                {anyFilter && (
                  <button type="button" className="link-button"
                          onClick={() => { setSearch(""); setRoleFilter(""); setBranchFilter(""); }}>
                    Quitar filtros
                  </button>
                )}
              </p>
            )}
            {users.loading && <Loading />}
            <ErrorBox message={users.error} />
            {users.data && shown.length === 0 && <Empty>No hay cuentas con esos filtros.</Empty>}
            {users.data && shown.length > 0 && (
              <div className="table-wrap table-cards users-table">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Nombre</th><th scope="col">Correo</th><th scope="col">Rol</th>
                      <th scope="col">Estado</th><th scope="col"><span className="sr-only">Acciones</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((u) => (
                      <tr key={u.id} className={u.is_active && !u.archived_at ? undefined : "row-muted"}>
                        <td className="card-title">
                          {u.full_name}
                          <div className="muted small">
                            {u.document_number ? `C.I. ${u.document_number}` : <Badge tone="warn">Falta C.I.</Badge>}
                            {u.phone && <> · {u.phone}</>}
                            {bpsMissing(u, clinic) && <> <Badge tone="warn">Faltan datos BPS</Badge></>}
                          </div>
                        </td>
                        <td data-label="Correo">{u.email}</td>
                        <td className="stack" data-label="Rol">
                          {ROLE_LABELS[u.role]}
                          {u.specialty_name && <div className="muted small">{u.specialty_name}</div>}
                          {u.role === "professional" && (
                            <div className="muted small">Hasta {u.max_concurrent_patients} a la vez</div>
                          )}
                          {u.role === "professional" && (
                            <div className="small">
                              {u.degree_id ? (
                                <button type="button" className="link-button" style={{ marginLeft: 0 }}
                                        onClick={() => setViewingDegree(u)}
                                        aria-label={`Ver el título de ${u.full_name}`}>Ver título</button>
                              ) : <Badge tone="warn">Falta título</Badge>}
                            </div>
                          )}
                          <div className="muted small">
                            {u.role === "admin" ? "Todas las sucursales"
                              : u.branch_ids.length
                                ? allBranches.filter((b) => u.branch_ids.includes(b.id)).map((b) => b.name).join(", ")
                              : "Sin sucursal"}
                          </div>
                        </td>
                        <td className="stack" data-label="Estado">
                          {u.archived_at ? <Badge tone="warn">Eliminada</Badge>
                            : u.is_active ? <Badge tone="ok">Activa</Badge> : <Badge>Desactivada</Badge>}
                          {!u.archived_at && u.must_change_password && (
                            <div className="muted small">Debe cambiar la contraseña al entrar</div>
                          )}
                        </td>
                        <td className="row-actions">
                          {u.archived_at ? (
                            <button type="button" className="btn btn-small" onClick={() => restore(u)}
                                    disabled={action.busy} aria-label={`Restaurar la cuenta de ${u.full_name}`}>
                              Restaurar
                            </button>
                          ) : (
                            <>
                              <button type="button" className="btn btn-small" onClick={() => setEditing(u)}
                                      aria-label={`Editar la cuenta de ${u.full_name}`}>
                                Editar
                              </button>
                              {u.id !== me.id && (
                                <>
                                  <button type="button" className="btn btn-small"
                                          onClick={() => resetPassword(u)} disabled={action.busy}
                                          aria-label={`Restablecer la contraseña de ${u.full_name}`}>
                                    Restablecer contraseña
                                  </button>
                                  <button type="button" className="btn btn-small"
                                          onClick={() => toggle(u)} disabled={action.busy}>
                                    {u.is_active ? "Desactivar" : "Reactivar"}
                                  </button>
                                  <button type="button" className="btn btn-small btn-danger"
                                          onClick={() => setArchiving(u)} disabled={action.busy}
                                          aria-label={`Eliminar la cuenta de ${u.full_name}`}>
                                    Eliminar
                                  </button>
                                </>
                              )}
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}
      </div>
      {viewingDegree?.degree_id && (
        <DegreeViewer user={viewingDegree} onClose={() => setViewingDegree(null)} />
      )}
      {creating && (
        <FormDialog title="Nueva cuenta" onClose={() => setCreating(false)}>
          <NewUserForm specialties={allSpecialties} branches={allBranches} onCancel={() => setCreating(false)}
                       onCreated={(name, password) => {
                         setCreating(false);
                         setTempPassword({ name, password, isNew: true });
                         notify(`Cuenta de ${name} creada.`);
                         users.reload(); specialties.reload();
                       }} />
        </FormDialog>
      )}
      {editing && (
        <FormDialog title={`Editar cuenta: ${editing.full_name}`} onClose={() => setEditing(null)}>
          <EditUserForm
            key={editing.id}
            user={editing}
            isMe={editing.id === me.id}
            specialties={allSpecialties}
            branches={allBranches}
            onClose={(saved) => {
              setEditing(null);
              if (saved) { notify("Cuenta actualizada."); users.reload(); specialties.reload(); }
            }}
          />
        </FormDialog>
      )}
      {archiving && (
        <FormDialog title={`Eliminar la cuenta de ${archiving.full_name}`} onClose={() => setArchiving(null)} wide>
          <ArchiveUserForm
            key={archiving.id}
            target={archiving}
            onClose={(done) => {
              setArchiving(null);
              if (done) { notify("Cuenta eliminada."); users.reload(); specialties.reload(); }
            }}
          />
        </FormDialog>
      )}
      {tempPassword && (
        <TempPasswordDialog {...tempPassword} onClose={() => setTempPassword(null)} />
      )}
    </>
  );
}

/** Ventana para un formulario de Usuarios. Un clic afuera no la cierra (para no perder lo
 * escrito): se cierra con la ✕, con Cancelar o con Escape. */
function FormDialog({ title, onClose, wide = false, children }: {
  title: string; onClose: () => void; wide?: boolean; children: ReactNode;
}) {
  const titleId = useId();
  return (
    <Dialog className={wide ? "form-dialog wide" : "form-dialog"} labelledBy={titleId} onClose={onClose}
            closeOnBackdrop={false}>
      <div className="modal-head">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="icon-close" onClick={onClose} aria-label="Cerrar">✕</button>
      </div>
      {children}
    </Dialog>
  );
}

/** La contraseña temporal se muestra UNA sola vez, en una ventana. */
function TempPasswordDialog({ name, password, isNew, onClose }: {
  name: string; password: string; isNew: boolean; onClose: () => void;
}) {
  const titleId = useId();
  const done = useRef<HTMLButtonElement>(null);
  const [copied, setCopied] = useState<"ok" | "error" | null>(null);

  async function copy() {
    try {
      if (!navigator.clipboard) throw new Error("sin portapapeles");
      await navigator.clipboard.writeText(password);
      setCopied("ok");
    } catch {
      setCopied("error");
    }
  }

  return (
    <Dialog labelledBy={titleId} onClose={onClose} closeOnBackdrop={false} initialFocus={done}>
      <h2 id={titleId} className="modal-title">{isNew ? "Cuenta creada" : "Contraseña restablecida"}</h2>
      <div className="temp-password">
        <p>
          Contraseña temporal de <strong>{name}</strong>:{" "}
          <code>{password}</code>{" "}
          <button type="button" className="btn btn-small" onClick={copy}>
            {copied === "ok" ? "✓ Copiada" : "Copiar"}
          </button>
        </p>
        <p className="small" role="status" aria-live="polite">
          {copied === "ok" && "Contraseña copiada: ya la podés pegar donde la necesites."}
          {copied === "error" && "No se pudo copiar automáticamente: seleccionala y copiala a mano (Cmd+C)."}
        </p>
        <p className="small">
          Dásela en persona o por un medio seguro. <strong>No se vuelve a mostrar.</strong> Al entrar
          deberá elegir una contraseña nueva, que solo conocerá esa persona.
        </p>
      </div>
      <div className="form-actions">
        <button ref={done} type="button" className="btn btn-primary" onClick={onClose}>Listo</button>
      </div>
    </Dialog>
  );
}

const PROVIDER_FIELDS: [keyof ClinicDetail, string, number, string?][] = [
  ["bps_provider_number", "N° de proveedor (BPS)", 30],
  ["bps_company_number", "N° de empresa (BPS)", 30],
  ["phone", "Teléfono", 40, "tel"],
  ["email", "Correo electrónico", 254, "email"],
  ["address_street", "Domicilio (calle)", 120],
  ["address_number", "Número", 20],
  ["address_locality", "Localidad", 80],
  ["address_department", "Departamento", 40],
  ["address_annex", "Anexo", 40],
  ["monthly_budget", "Presupuesto mensual ($)", 40],
];

/** Datos de contacto: en "Mi consultorio" se muestran aparte de los del BPS. */
const CONTACT_FIELDS: (keyof ClinicDetail)[] = [
  "phone", "email", "address_street", "address_number", "address_locality", "address_department",
];

const LOGO_MAX_MB = 1;

/** Logo de la clínica: sale en el encabezado de los informes y la ficha impresos
 * (no en los formularios de AYEX ni del BPS, que tienen su propio formato).
 * También lo usa "Mi consultorio" del profesional independiente. */
export function LogoCard() {
  const { clinic, refresh } = useSession();
  const place = isIndependent(clinic) ? "consultorio" : "clínica";
  const input = useRef<HTMLInputElement>(null);
  const { busy, error, run } = useAction();
  const hasLogo = Boolean(clinic.logo_updated_at);

  async function upload(file: File) {
    const ok = await run(async () => {
      if (!["image/png", "image/jpeg"].includes(file.type)) {
        throw new ApiError(415, "El logo tiene que ser una imagen PNG o JPG.");
      }
      if (file.size > LOGO_MAX_MB * 1024 * 1024) {
        throw new ApiError(413, `El logo supera el máximo de ${LOGO_MAX_MB} MB. Probá con una imagen más chica.`);
      }
      await uploadFile("/clinic/logo", file, {}, { quiet: true });
    });
    if (input.current) input.current.value = "";
    if (ok) {
      notify(hasLogo ? "Logo reemplazado." : "Logo guardado.");
      await refresh().catch(() => undefined);
    }
  }

  async function remove() {
    if (!await askConfirm(`¿Quitar el logo? Lo impreso va a llevar solo el nombre ${place === "clínica" ? "de la clínica" : "del consultorio"}.`,
                          { confirmLabel: "Quitar logo" })) return;
    const ok = await run(async () => { await api.del("/clinic/logo"); });
    if (ok) {
      notify("Logo quitado.");
      await refresh().catch(() => undefined);
    }
  }

  return (
    <Card title={`Logo ${place === "clínica" ? "de la clínica" : "del consultorio"}`}>
      <p className="muted small">
        Sale arriba, junto al nombre {place === "clínica" ? "de la clínica" : "del consultorio"}, en todo lo que se imprime o se guarda como PDF desde
        Nordeste (informes y ficha del paciente). Los formularios de AYEX y del BPS no lo llevan.
        Imagen PNG o JPG de hasta {LOGO_MAX_MB} MB; se ve mejor con fondo blanco o transparente.
      </p>
      <ErrorBox message={error} />
      {hasLogo ? (
        <div className="logo-preview">
          <img src={clinicLogoUrl(clinic.logo_updated_at!)} alt={`Logo actual de ${clinic.name}`} />
          <span className="muted small">Subido el {fmtDateTime(clinic.logo_updated_at!)}</span>
        </div>
      ) : (
        <p><Badge>Sin logo</Badge> Por ahora lo impreso lleva solo el nombre {place === "clínica" ? "de la clínica" : "del consultorio"}.</p>
      )}
      <div className="form-actions">
        <input ref={input} type="file" accept="image/png,image/jpeg" className="sr-only" tabIndex={-1}
               aria-hidden="true" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
        {hasLogo && (
          <button type="button" className="btn btn-danger" disabled={busy} onClick={remove}>Quitar logo</button>
        )}
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => input.current?.click()}>
          {busy ? "Guardando…" : hasLogo ? "Cambiar logo" : "Subir logo"}
        </button>
      </div>
    </Card>
  );
}

/** Datos de la clínica (o del consultorio, en el espacio de un profesional independiente). */
export function ClinicCard() {
  const { refresh, clinic: session } = useSession();
  const independent = isIndependent(session);
  // Los datos para el BPS solo hacen falta si la función BPS y AYEX está habilitada.
  const showBps = !independent || hasFeature(session, "bps");
  const of = independent ? "del consultorio" : "de la clínica";
  const clinic = useAsync(() => api.get<ClinicDetail>("/clinic"), []);
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const { busy, error, run } = useAction();
  const data = clinic.data;
  const values: Record<string, string> = form ?? (data ? Object.fromEntries(
    [["name", data.name], ["transport", data.transport_included === null ? "" : data.transport_included ? "si" : "no"],
     ["ayex_fee", data.ayex_fee === null ? "" : String(data.ayex_fee).replace(".", ",")],
     ...PROVIDER_FIELDS.map(([k]) => [k, (data[k] as string | null) ?? ""])]) : {});
  const set = (key: string, value: string) => setForm({ ...values, [key]: value });

  const feeText = (values.ayex_fee ?? "").trim().replace(/\s|\$/g, "");
  const fee = feeText === "" ? null : Number(feeText.includes(",") ? feeText.replace(/\./g, "").replace(",", ".") : feeText);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      if (fee !== null && (!Number.isFinite(fee) || fee <= 0)) throw new ApiError(422, "El arancel AYEX tiene que ser un importe mayor que cero, por ejemplo 8238.");
      await api.patch("/clinic", {
        name: values.name,
        ayex_fee: fee,
        transport_included: values.transport === "" ? null : values.transport === "si",
        ...Object.fromEntries(PROVIDER_FIELDS.map(([k]) => [k, values[k]?.trim() || null])),
      });
    });
    if (ok) {
      notify(`Datos ${of} guardados.`);
      setForm(null);
      clinic.reload();
      await refresh().catch(() => undefined); // el nombre nuevo se ve enseguida en el encabezado
    }
  }

  return (
    <Card title={independent ? "Consultorio" : "Clínica"}>
      {clinic.loading && !data && <Loading />}
      <ErrorBox message={clinic.error} />
      {data && (
        <form className="grid-form" onSubmit={submit}>
          <ErrorBox message={error} />
          <Field label={`Nombre ${of}`} required
                 hint={independent ? "Sale en el encabezado y en lo que se imprime. Por ejemplo: Consultorio Lic. Ana Pérez." : undefined}>
            {(id, hint) => <input id={id} required minLength={2} maxLength={200} aria-describedby={hint}
                                  value={values.name} onChange={(e) => set("name", e.target.value)} />}
          </Field>
          {independent && (<>
            <p className="span-all section-label">Contacto</p>
            {PROVIDER_FIELDS.filter(([key]) => CONTACT_FIELDS.includes(key)).map(([key, label, max, type]) => (
              <Field key={key} label={label}>
                {(id) => (
                  <input id={id} type={type ?? "text"} maxLength={max}
                         value={values[key] ?? ""} onChange={(e) => set(key, e.target.value)} />
                )}
              </Field>
            ))}
          </>)}
          {showBps && (<>
          <p className="span-all section-label">Datos como proveedor del BPS (para el formulario de AYEX)</p>
          {PROVIDER_FIELDS.filter(([key]) => !independent || !CONTACT_FIELDS.includes(key)).map(([key, label, max, type]) => (
            <Field key={key} label={label} hint={key === "monthly_budget" ? "Solo para instituciones privadas." : undefined}>
              {(id, hint) => (
                <input id={id} type={type ?? "text"} aria-describedby={hint} maxLength={max}
                       value={values[key] ?? ""} onChange={(e) => set(key, e.target.value)} />
              )}
            </Field>
          ))}
          <Field label="¿Incluye el servicio de transporte?">
            {(id) => (
              <select id={id} value={values.transport} onChange={(e) => set("transport", e.target.value)}>
                <option value="">Sin indicar</option>
                <option value="si">Sí</option>
                <option value="no">No</option>
              </select>
            )}
          </Field>
          <p className="span-all section-label">Pagos del BPS</p>
          <Field label="Arancel AYEX por paciente ($)"
                 hint="Lo que paga el BPS por cada paciente AYEX en un mes. Lo usa «Pagos BPS» para encontrar pagos menores.">
            {(id, hint) => (
              <input id={id} inputMode="decimal" aria-describedby={hint} maxLength={14} placeholder="Por ejemplo 8238"
                     value={values.ayex_fee ?? ""} onChange={(e) => set("ayex_fee", e.target.value)} />
            )}
          </Field>
          </>)}
          <div className="form-actions">
            {form && <button type="button" className="btn" onClick={() => setForm(null)}>Descartar cambios</button>}
            <button type="submit" className="btn btn-primary" disabled={busy || !form}>
              {busy ? "Guardando…" : `Guardar datos ${of}`}
            </button>
          </div>
        </form>
      )}
    </Card>
  );
}

/** Opciones del selector de especialidad: las activas, más la actual aunque esté desactivada. */
function specialtyOptions(specialties: Specialty[], currentId?: string | null) {
  return specialties.filter((s) => s.is_active || s.id === currentId);
}

function NewUserForm({ specialties, branches, onCreated, onCancel }: {
  specialties: Specialty[]; branches: Branch[]; onCreated: (name: string, temporaryPassword: string) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({ email: "", full_name: "", document_number: "", phone: "", role: "professional",
    specialty_id: "", max_concurrent_patients: "3" });
  const [branchIds, setBranchIds] = useState<string[]>([]);
  const { busy, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const created = await api.post<User & { temporary_password: string }>("/users", {
        ...form,
        phone: form.phone || null,
        specialty_id: form.role === "professional" ? form.specialty_id || null : null,
        max_concurrent_patients: Number(form.max_concurrent_patients) || 3,
        branch_ids: form.role === "admin" ? [] : branchIds,
      });
      onCreated(created.full_name, created.temporary_password);
    });
  }

  return (
    <form className="grid-form" onSubmit={submit}>
      <ErrorBox message={error} />
      <Field label="Nombre completo" required>
        {(id) => <input id={id} required minLength={2} maxLength={200} value={form.full_name} onChange={set("full_name")}
                        data-autofocus />}
      </Field>
      <Field label="C.I." required>
        {(id) => <input id={id} required minLength={3} maxLength={30} autoComplete="off"
                        value={form.document_number} onChange={set("document_number")} />}
      </Field>
      <Field label="Teléfono">
        {(id) => <input id={id} type="tel" maxLength={40} value={form.phone} onChange={set("phone")} />}
      </Field>
      <Field label="Correo electrónico" required hint="Es el usuario con el que la persona inicia sesión.">
        {(id, hint) => <input id={id} type="email" aria-describedby={hint} required maxLength={254} autoComplete="off"
                              value={form.email} onChange={set("email")} />}
      </Field>
      <Field label="Rol" required>
        {(id) => (
          <select id={id} value={form.role} onChange={set("role")}>
            {Object.entries(ROLE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        )}
      </Field>
      {form.role === "professional" && (
        <Field label="Especialidad" required>
          {(id) => (
            <select id={id} required value={form.specialty_id} onChange={set("specialty_id")}>
              <option value="">Elegir…</option>
              {specialtyOptions(specialties).map((sp) => <option key={sp.id} value={sp.id}>{sp.name}</option>)}
            </select>
          )}
        </Field>
      )}
      {form.role === "professional" && (
        <Field label="Pacientes a la vez" required hint="Cuántos pacientes puede atender en un mismo horario (1 a 10).">
          {(id, hint) => (
            <input id={id} type="number" min={1} max={10} required aria-describedby={hint}
                   value={form.max_concurrent_patients} onChange={set("max_concurrent_patients")} />
          )}
        </Field>
      )}
      <BranchChecklist role={form.role} branches={branches} value={branchIds} onChange={setBranchIds} />
      <p className="span-all muted small" role="note">
        Nordeste genera una contraseña temporal que verás al crear la cuenta. La persona deberá cambiarla
        al entrar por primera vez, así nadie más conoce su contraseña.
      </p>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel}>Cancelar</button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Creando…" : "Crear cuenta"}
        </button>
      </div>
    </form>
  );
}

function EditUserForm({ user, isMe, specialties, branches, onClose }: {
  user: User; isMe: boolean; specialties: Specialty[]; branches: Branch[]; onClose: (saved: boolean) => void;
}) {
  const [branchIds, setBranchIds] = useState<string[]>(user.branch_ids);
  const [bps, setBps] = useState<BpsForm>(() => bpsForm(user));
  const [form, setForm] = useState({
    full_name: user.full_name,
    document_number: user.document_number ?? "",
    phone: user.phone ?? "",
    email: user.email,
    role: user.role as string,
    specialty_id: user.specialty_id ?? "",
    max_concurrent_patients: String(user.max_concurrent_patients),
  });
  const { busy, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });
  const closesSessions = form.email.trim().toLowerCase() !== user.email || form.role !== user.role;
  // A5: si se le quita una sucursal a un profesional, se borran sus horarios de esa sucursal.
  const availability = useAsync(
    () => user.role === "professional"
      ? api.get<AvailabilityBlock[]>("/availability", { professional_id: user.id }) : Promise.resolve([]),
    [user.id],
  );
  const removedBranches = user.role === "professional" && form.role === "professional"
    ? user.branch_ids.filter((id) => !branchIds.includes(id)) : [];
  const lostBlocks = (availability.data ?? []).filter((b) => removedBranches.includes(b.branch_id));
  const lostByBranch = removedBranches
    .map((id) => ({
      name: branches.find((b) => b.id === id)?.name ?? "otra sucursal",
      count: lostBlocks.filter((b) => b.branch_id === id).length,
    }))
    .filter((x) => x.count > 0);
  const lostText = lostByBranch.map((x) => `${x.name} (${x.count} ${x.count === 1 ? "bloque" : "bloques"})`)
    .join(" y ");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (lostByBranch.length > 0 && !await askConfirm(
      `Al quitarle la sucursal se borrarán los horarios de disponibilidad de ${user.full_name} en ${lostText}.\n\n` +
      "No se pueden recuperar: si vuelve a trabajar allí, habrá que cargarlos de nuevo. ¿Guardar igual?",
      { confirmLabel: "Guardar y borrar horarios", danger: true },
    )) return;
    const ok = await run(async () => {
      await api.patch(`/users/${user.id}`, {
        full_name: form.full_name,
        ...(form.document_number.trim() ? { document_number: form.document_number } : {}),
        phone: form.phone || null,
        email: form.email,
        role: form.role,
        specialty_id: form.role === "professional" ? form.specialty_id || null : null,
        ...(form.role === "professional"
          ? { max_concurrent_patients: Number(form.max_concurrent_patients) || 1, ...bpsPayload(bps) } : {}),
        ...(form.role === "admin" ? {} : { branch_ids: branchIds }),
      });
    });
    if (!ok) return;
    if (isMe) {
      window.location.reload(); // actualiza tu nombre y correo en el encabezado
    } else {
      onClose(true);
    }
  }

  return (
    <>
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Nombre completo" required>
          {(id) => <input id={id} required minLength={2} maxLength={200} value={form.full_name} onChange={set("full_name")} />}
        </Field>
        <Field label="C.I." required={Boolean(user.document_number)}
               hint={user.document_number ? undefined : "Falta: la persona también puede cargarla en Mi cuenta."}>
          {(id, hint) => <input id={id} aria-describedby={hint} required={Boolean(user.document_number)} minLength={3}
                                maxLength={30} value={form.document_number} onChange={set("document_number")} />}
        </Field>
        <Field label="Teléfono">
          {(id) => <input id={id} type="tel" maxLength={40} value={form.phone} onChange={set("phone")} />}
        </Field>
        <Field label="Correo electrónico" required hint="Es el usuario con el que la persona inicia sesión.">
          {(id, hint) => (
            <input id={id} type="email" aria-describedby={hint} required maxLength={254} autoComplete="off"
                   value={form.email} onChange={set("email")} />
          )}
        </Field>
        <Field label="Rol" required hint={isMe ? "No podés quitarte el rol de administración." : undefined}>
          {(id, hint) => (
            <select id={id} aria-describedby={hint} value={form.role} onChange={set("role")} disabled={isMe}>
              {Object.entries(ROLE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </Field>
        {form.role === "professional" && (
          <Field label="Especialidad" required>
            {(id) => (
              <select id={id} required value={form.specialty_id} onChange={set("specialty_id")}>
                <option value="">Elegir…</option>
                {specialtyOptions(specialties, user.specialty_id).map((sp) => (
                  <option key={sp.id} value={sp.id}>{sp.name}{sp.is_active ? "" : " (desactivada)"}</option>
                ))}
              </select>
            )}
          </Field>
        )}
        {form.role === "professional" && (
          <Field label="Pacientes a la vez" required hint="Cuántos pacientes puede atender en un mismo horario (1 a 10).">
            {(id, hint) => (
              <input id={id} type="number" min={1} max={10} required aria-describedby={hint}
                     value={form.max_concurrent_patients} onChange={set("max_concurrent_patients")} />
            )}
          </Field>
        )}
        <BranchChecklist role={form.role} branches={branches} value={branchIds} onChange={setBranchIds} />
        {lostByBranch.length > 0 && (
          <div className="span-all">
            <WarnBox message={`Al guardar se borrarán sus horarios de disponibilidad en ${lostText}. ` +
              "Si tiene turnos a futuro en esa sucursal, primero hay que cancelarlos o pasarlos a otro profesional."} />
          </div>
        )}
        {form.role === "professional" && (
          <fieldset className="span-all choice">
            <legend>Datos para el BPS</legend>
            <p className="muted small">
              Para el Cronograma BPS. Los completa cada profesional en Mi cuenta; acá podés corregirlos.
            </p>
            <div className="grid-form">
              <BpsFields form={bps} onChange={setBps} required={false} />
            </div>
          </fieldset>
        )}
        {closesSessions && !isMe && (
          <p className="span-all muted small" role="note">
            Al cambiar el correo o el rol se cerrarán las sesiones abiertas de esta persona; deberá
            volver a iniciar sesión{form.email.trim().toLowerCase() !== user.email ? " con el correo nuevo" : ""}.
          </p>
        )}
        <div className="form-actions">
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Guardando…" : "Guardar cambios"}
          </button>
        </div>
      </form>
    </>
  );
}

function SpecialtiesCard({ specialties, loading, error, onChanged }: {
  specialties: Specialty[]; loading: boolean; error: string | null; onChanged: () => void;
}) {
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<Specialty | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const action = useAction();
  const bps = useBpsLists();

  async function add(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => { await api.post("/specialties", { name: newName }); });
    if (ok) {
      setNewName("");
      onChanged();
    }
  }

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (!renaming) return;
    const ok = await action.run(async () => {
      await api.patch(`/specialties/${renaming.id}`, { name: renameValue });
    });
    if (ok) {
      setRenaming(null);
      onChanged();
    }
  }

  async function setActivity(sp: Specialty, value: string) {
    const ok = await action.run(async () => {
      await api.patch(`/specialties/${sp.id}`, { bps_activity: value || null });
    });
    if (ok) {
      notify(`Actividad BPS de "${sp.name}" guardada.`);
      onChanged();
    }
  }

  async function toggle(sp: Specialty) {
    if (sp.is_active && sp.professional_count > 0 && !await askConfirm(
      `${sp.professional_count} profesional(es) tienen "${sp.name}". La conservarán, pero no podrás ` +
      "asignarla a cuentas nuevas. ¿Desactivarla?", { confirmLabel: "Desactivar", danger: true })) return;
    const ok = await action.run(async () => {
      await api.patch(`/specialties/${sp.id}`, { is_active: !sp.is_active });
    });
    if (ok) onChanged();
  }

  return (
    <Card title="Especialidades">
      <p className="muted small">
        Las especialidades se asignan a los profesionales. No se borran: si una deja de usarse,
        desactivala; quienes ya la tienen la conservan. La "Actividad BPS" es la que figura en el
        Cronograma BPS para los turnos de esa especialidad.
      </p>
      <ErrorBox message={action.error} />
      {loading && specialties.length === 0 && <Loading />}
      <ErrorBox message={error} />
      {specialties.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Especialidad</th><th scope="col">Actividad BPS</th><th scope="col">Profesionales activos</th>
                <th scope="col">Estado</th><th scope="col"><span className="sr-only">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              {specialties.map((sp) => (
                <tr key={sp.id} className={sp.is_active ? undefined : "row-muted"}>
                  <td>{sp.name}</td>
                  <td>
                    <select aria-label={`Actividad BPS de ${sp.name}`} value={sp.bps_activity ?? ""}
                            disabled={action.busy || !bps} onChange={(e) => setActivity(sp, e.target.value)}>
                      <option value="">
                        {sp.bps_activity_auto ? `Automática: ${sp.bps_activity_auto}` : "Sin asociar (queda en blanco)"}
                      </option>
                      {bps?.activities.map((a) => <option key={a} value={a}>{a}</option>)}
                    </select>
                  </td>
                  <td>{sp.professional_count}</td>
                  <td>{sp.is_active ? <Badge tone="ok">Activa</Badge> : <Badge>Desactivada</Badge>}</td>
                  <td className="row-actions">
                    <button type="button" className="btn btn-small"
                            onClick={() => { setRenaming(sp); setRenameValue(sp.name); }}
                            aria-label={`Renombrar ${sp.name}`}>
                      Renombrar
                    </button>
                    <button type="button" className={sp.is_active ? "btn btn-small btn-danger" : "btn btn-small"}
                            onClick={() => toggle(sp)} disabled={action.busy}>
                      {sp.is_active ? "Desactivar" : "Reactivar"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {renaming && (
        <form className="inline-form" onSubmit={rename}>
          <Field label={`Nuevo nombre para "${renaming.name}"`} required>
            {(id) => (
              <input id={id} required minLength={2} maxLength={80} value={renameValue}
                     onChange={(e) => setRenameValue(e.target.value)} />
            )}
          </Field>
          <button type="button" className="btn" onClick={() => setRenaming(null)}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={action.busy}>Guardar</button>
        </form>
      )}
      <form className="inline-form" onSubmit={add}>
        <Field label="Nueva especialidad" hint="Por ejemplo: Fonoaudiología, Psicopedagogía, Psicomotricidad.">
          {(id, hint) => (
            <input id={id} aria-describedby={hint} required minLength={2} maxLength={80} value={newName}
                   onChange={(e) => setNewName(e.target.value)} />
          )}
        </Field>
        <button type="submit" className="btn btn-primary" disabled={action.busy}>Agregar</button>
      </form>
    </Card>
  );
}

/** Confirmar la eliminación de una cuenta: reasignar sus pacientes y resolver sus turnos futuros. */
function ArchiveUserForm({ target, onClose }: { target: User; onClose: (done: boolean) => void }) {
  const patients = useAsync(
    () => api.get<ResponsiblePatient[]>(`/users/${target.id}/responsible-patients`), [target.id],
  );
  const appointments = useAsync(
    () => api.get<Appointment[]>(`/users/${target.id}/future-appointments`), [target.id],
  );
  const professionals = useAsync(() => api.get<Professional[]>("/professionals"), []);
  const [plan, setPlan] = useState<Record<string, string>>({});
  // Por turno: "cancel" o el id del profesional que lo recibe.
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [cancelReason, setCancelReason] = useState("");
  const { busy, error, run } = useAction();

  const list = patients.data ?? [];
  const appts = appointments.data ?? [];
  const options = (professionals.data ?? []).filter((p) => p.id !== target.id);
  const missingPatients = list.filter((p) => !plan[p.id]).length;
  const missingAppts = appts.filter((a) => !decisions[a.id]).length;
  const anyCancel = appts.some((a) => decisions[a.id] === "cancel");
  const loaded = patients.data && appointments.data && professionals.data;

  function assignAll(professionalId: string) {
    if (!professionalId) return;
    setPlan(Object.fromEntries(list.map((p) => [p.id, professionalId])));
  }

  function decideAll(choice: string) {
    if (!choice) return;
    setDecisions(Object.fromEntries(appts.map((a) => {
      // "Al nuevo responsable": solo si ese paciente se está reasignando.
      if (choice === "responsible") return [a.id, plan[a.patient_id] ?? decisions[a.id] ?? ""];
      return [a.id, choice];
    })));
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/users/${target.id}/archive`, {
        reassignments: list.map((p) => ({ patient_id: p.id, professional_id: plan[p.id] })),
        appointments: appts.map((a) => decisions[a.id] === "cancel"
          ? { appointment_id: a.id, action: "cancel" }
          : { appointment_id: a.id, action: "move", professional_id: decisions[a.id] }),
        cancel_reason: cancelReason.trim() || null,
      });
    });
    if (ok) onClose(true);
  }

  const noOneElse = options.length === 0 && (list.length > 0 || appts.length > 0);

  return (
    <>
    <p>
      No podrá volver a entrar y dejará de aparecer en la lista. Sus notas, informes y
      registros se conservan. Podrás restaurarla desde "Mostrar eliminadas".
    </p>
    {!loaded && <Loading />}
    <ErrorBox message={patients.error ?? appointments.error ?? professionals.error} />
    <form onSubmit={confirm}>
      <ErrorBox message={error} />
      {noOneElse && (
        <ErrorBox message="No hay otro profesional activo en la clínica. Creá o reactivá uno antes de eliminar esta cuenta." />
      )}

      {list.length > 0 && options.length > 0 && (
        <section className="archive-section">
          <h3>
            1. Es responsable de {list.length === 1 ? "1 paciente" : `${list.length} pacientes`}.
            Elegí quién queda a cargo de cada uno:
          </h3>
          {list.length > 1 && (
            <div className="reassign-all">
              <Field label="Asignar todos a">
                {(id) => (
                  <select id={id} value="" onChange={(e) => assignAll(e.target.value)}>
                    <option value="">Elegir…</option>
                    {options.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
                  </select>
                )}
              </Field>
            </div>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th scope="col">Paciente</th><th scope="col">Nuevo responsable</th></tr>
              </thead>
              <tbody>
                {list.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.full_name}
                      <div className="muted small">
                        {p.document_number ? `Doc. ${p.document_number} · ` : ""}
                        {PATIENT_STATUS_LABELS[p.status]}
                      </div>
                    </td>
                    <td>
                      <select aria-label={`Nuevo responsable de ${p.full_name}`} required
                              value={plan[p.id] ?? ""}
                              onChange={(e) => setPlan({ ...plan, [p.id]: e.target.value })}>
                        <option value="">Elegir…</option>
                        {options.map((o) => <option key={o.id} value={o.id}>{o.full_name}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {appts.length > 0 && options.length > 0 && (
        <section className="archive-section">
          <h3>
            {list.length > 0 ? "2. " : ""}
            Tiene {appts.length === 1 ? "1 turno" : `${appts.length} turnos`} a futuro.
            Elegí si cada uno se cancela o pasa a otro profesional (mismo día y hora):
          </h3>
          <div className="reassign-all">
            <Field label="Para todos">
              {(id) => (
                <select id={id} value="" onChange={(e) => decideAll(e.target.value)}>
                  <option value="">Elegir…</option>
                  {list.length > 0 && <option value="responsible">Pasar al nuevo responsable de cada paciente</option>}
                  <option value="cancel">Cancelar todos</option>
                  {options.map((p) => <option key={p.id} value={p.id}>Pasar a {p.full_name}</option>)}
                </select>
              )}
            </Field>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th scope="col">Turno</th><th scope="col">Paciente</th><th scope="col">Qué hacer</th></tr>
              </thead>
              <tbody>
                {appts.map((a) => (
                  <tr key={a.id}>
                    <td>{fmtDateTime(a.starts_at)}</td>
                    <td>{a.patient_name}</td>
                    <td>
                      <select aria-label={`Qué hacer con el turno de ${a.patient_name} del ${fmtDateTime(a.starts_at)}`}
                              required value={decisions[a.id] ?? ""}
                              onChange={(e) => setDecisions({ ...decisions, [a.id]: e.target.value })}>
                        <option value="">Elegir…</option>
                        <option value="cancel">Cancelar turno</option>
                        {options.map((o) => <option key={o.id} value={o.id}>Pasar a {o.full_name}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {anyCancel && (
            <div className="reassign-all">
              <Field label="Motivo de la cancelación" hint='Si lo dejás vacío: "Cuenta del profesional eliminada".'>
                {(id, hint) => (
                  <input id={id} aria-describedby={hint} maxLength={300} value={cancelReason}
                         onChange={(e) => setCancelReason(e.target.value)} />
                )}
              </Field>
            </div>
          )}
          <p className="muted small">
            Para pasar un turno, el profesional elegido debe tener acceso al paciente (por ejemplo, ser
            su nuevo responsable) y lugar libre en ese horario.
          </p>
        </section>
      )}

      <div className="form-actions">
        <button type="button" className="btn" onClick={() => onClose(false)}>Cancelar</button>
        <button type="submit" className="btn btn-danger"
                disabled={busy || !loaded || noOneElse || missingPatients > 0 || missingAppts > 0}>
          {busy ? "Eliminando…"
            : list.length > 0 || appts.length > 0 ? "Confirmar y eliminar cuenta" : "Eliminar cuenta"}
        </button>
      </div>
    </form>
    </>
  );
}

/** Sucursales a las que puede entrar una cuenta (Administración entra a todas). */
function BranchChecklist({ role, branches, value, onChange }: {
  role: string; branches: Branch[]; value: string[]; onChange: (ids: string[]) => void;
}) {
  if (role === "admin") {
    return <p className="span-all muted small">Administración entra a todas las sucursales.</p>;
  }
  const active = branches.filter((b) => b.is_active || value.includes(b.id));
  return (
    <fieldset className="span-all choice">
      <legend>Sucursales donde trabaja <span className="required" aria-hidden="true">*</span></legend>
      <div className="branch-checks">
        {active.map((b) => (
          <label key={b.id} className="checkbox">
            <input type="checkbox" checked={value.includes(b.id)} disabled={!b.is_active && !value.includes(b.id)}
                   onChange={(e) => onChange(e.target.checked ? [...value, b.id] : value.filter((x) => x !== b.id))} />
            {b.name}{b.is_active ? "" : " (desactivada)"}
          </label>
        ))}
      </div>
      {value.length === 0 && <p className="muted small">Elegí al menos una.</p>}
    </fieldset>
  );
}

function BranchesCard({ branches, loading, error, onChanged }: {
  branches: Branch[]; loading: boolean; error: string | null; onChanged: () => void;
}) {
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<Branch | null>(null);
  const [renameTo, setRenameTo] = useState("");
  const action = useAction();

  async function add(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => { await api.post("/branches", { name: newName }); });
    if (ok) { setNewName(""); onChanged(); }
  }

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (!renaming) return;
    const ok = await action.run(async () => { await api.patch(`/branches/${renaming.id}`, { name: renameTo }); });
    if (ok) { setRenaming(null); onChanged(); }
  }

  async function toggle(b: Branch) {
    if (b.is_active && !await askConfirm(
      `¿Desactivar la sucursal ${b.name}?\n\nNadie podrá entrar a ella hasta que la reactives. ` +
      "Sus datos se conservan.",
      { confirmLabel: "Desactivar", danger: true },
    )) return;
    const ok = await action.run(async () => { await api.patch(`/branches/${b.id}`, { is_active: !b.is_active }); });
    if (ok) onChanged();
  }

  return (
    <Card title="Sucursales">
      <p className="muted small">
        Cada cuenta entra solo a las sucursales que tiene asignadas (Administración, a todas). Las
        sucursales no se borran: se desactivan.
      </p>
      <ErrorBox message={action.error ?? error} />
      {loading && <Loading />}
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Sucursal</th><th scope="col">Estado</th><th scope="col"><span className="sr-only">Acciones</span></th></tr></thead>
          <tbody>
            {branches.map((b) => (
              <tr key={b.id} className={b.is_active ? undefined : "row-muted"}>
                <td>
                  {renaming?.id === b.id ? (
                    <form className="inline-form" onSubmit={rename}>
                      <Field label="Nuevo nombre" required>
                        {(id) => <input id={id} required minLength={2} maxLength={100} value={renameTo}
                                        onChange={(e) => setRenameTo(e.target.value)} />}
                      </Field>
                      <button type="button" className="btn" onClick={() => setRenaming(null)}>Cancelar</button>
                      <button type="submit" className="btn btn-primary" disabled={action.busy}>Guardar</button>
                    </form>
                  ) : b.name}
                </td>
                <td>{b.is_active ? <Badge tone="ok">Activa</Badge> : <Badge>Desactivada</Badge>}</td>
                <td className="row-actions">
                  {renaming?.id !== b.id && (
                    <button type="button" className="btn btn-small" onClick={() => { setRenaming(b); setRenameTo(b.name); }}>
                      Renombrar
                    </button>
                  )}
                  <button type="button" className={b.is_active ? "btn btn-small btn-danger" : "btn btn-small"}
                          onClick={() => toggle(b)} disabled={action.busy}>
                    {b.is_active ? "Desactivar" : "Reactivar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="inline-form" onSubmit={add}>
        <Field label="Nueva sucursal" hint="Por ejemplo: Pando, Anexo.">
          {(id, hint) => <input id={id} aria-describedby={hint} required minLength={2} maxLength={100}
                                value={newName} onChange={(e) => setNewName(e.target.value)} />}
        </Field>
        <button type="submit" className="btn btn-primary" disabled={action.busy}>Agregar</button>
      </form>
    </Card>
  );
}

/** Título de un profesional (solo Administración). */
function DegreeViewer({ user, onClose }: { user: User; onClose: () => void }) {
  const degree = useAsync(() => api.get<Degree | null>(`/users/${user.id}/degree`), [user.id]);
  if (!degree.data) return null;
  const d = degree.data;
  return (
    <DocumentViewer name={`Título de ${user.full_name} — ${d.original_name}`} contentType={d.content_type}
                    src={`/api/degrees/${d.id}/download?view=true`} downloadUrl={`/api/degrees/${d.id}/download`}
                    onClose={onClose} />
  );
}
