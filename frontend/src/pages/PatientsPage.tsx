import { Fragment, useEffect, useId, useState, type FormEvent } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import {
  AFFILIATION_LABELS, ayexState, fmtDate, PATIENT_STATUS_LABELS, PATIENT_STATUS_TONE as STATUS_TONE, SEX_LABELS, telHref,
} from "../labels";
import { notify } from "../toast";
import { navigate, useRoute } from "../router";
import { hasFeature, isTitular, useSession } from "../session";
import { ProfTag, ProfTagList, useSpecialtyLookup } from "../profession";
import { AddressFields, addressPayload, emptyAddress } from "./AddressFields";
import { ImportPatients, type ImportSource } from "./ImportPatients";
import type { AffiliationType, Patient, Professional } from "../types";


const PAGE_SIZE = 50;

/** Filtros y página del listado. */
interface ListState {
  search: string; status: string; affiliation: string; ayex: string; branch: string; page: number;
}
const EMPTY_STATE: ListState = { search: "", status: "", affiliation: "", ayex: "", branch: "", page: 1 };

// Último estado del listado, para encontrarlo igual al volver de una ficha. Solo en memoria
// (se pierde al recargar la página) y separado por persona y sucursal.
const lastState = new Map<string, ListState>();

/** Filtros que llegan en el enlace (por ejemplo, desde el aviso de AYEX del Inicio). */
function stateFromLink(params: URLSearchParams): ListState | null {
  const keys = ["estado", "afiliacion", "vencimiento", "sucursal", "q"];
  if (!keys.some((k) => params.has(k))) return null;
  return {
    ...EMPTY_STATE,
    search: params.get("q") ?? "",
    status: params.get("estado") ?? "",
    affiliation: params.get("afiliacion") ?? "",
    ayex: params.get("vencimiento") ?? "",
    branch: params.get("sucursal") ?? "",
  };
}

/** ¿Recepción va a poder ver este paciente desde su sucursal activa? (los privados se ven en
 * todas; los demás, solo en la suya). */
export function receptionCanSee(p: { affiliation: AffiliationType | string; branch_id: string }, activeBranchId: string) {
  return p.affiliation === "private" || p.branch_id === activeBranchId;
}

/** Profesionales que pueden ser responsables: para AYEX y Tutelas, solo quienes atienden en la
 * sucursal del paciente (si no, nunca podrían darle turno). */
export function responsibleOptions(list: Professional[], affiliation: string, branchId: string): Professional[] {
  if (!affiliation || affiliation === "private") return list;
  return list.filter((p) => p.branch_ids.includes(branchId));
}

export function PatientsPage() {
  const { user, branch: activeBranch, branches, clinic } = useSession();
  const route = useRoute();
  // Asignar responsables: Administración y Recepción. Cargar, exportar e importar pacientes,
  // también el profesional independiente (queda como responsable de los que carga).
  const canManage = user.role === "admin" || user.role === "reception";
  const titular = isTitular(user, clinic);
  const canCreate = canManage || titular;
  const stateKey = `${user.id}|${activeBranch.id}`;
  const [initial] = useState<ListState>(
    () => stateFromLink(route.params) ?? lastState.get(stateKey) ?? EMPTY_STATE,
  );
  const [search, setSearch] = useState(initial.search);
  const [query, setQuery] = useState(initial.search.trim());
  const [status, setStatus] = useState(initial.status);
  const [affiliation, setAffiliation] = useState(initial.affiliation);
  const [ayex, setAyex] = useState(initial.ayex);
  // "" = sucursal activa (profesionales: todos sus pacientes); "all" = todas las que puedo ver.
  const [branch, setBranch] = useState(initial.branch);
  const [page, setPage] = useState(initial.page);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState<ImportSource | null>(null);
  const [assigning, setAssigning] = useState<string | null>(null);
  const specialty = useSpecialtyLookup();
  const ayexFilter = affiliation === "ayex" ? ayex : "";
  const professionals = useAsync(
    () => (canCreate ? api.get<Professional[]>("/professionals") : Promise.resolve([] as Professional[])),
    [canCreate],
  );
  // Busca mientras se escribe (con una pausa breve para no consultar en cada letra).
  useEffect(() => {
    const value = search.trim();
    if (value === query) return undefined;
    const timer = setTimeout(() => setQuery(value), 350);
    return () => clearTimeout(timer);
  }, [search, query]);
  const patients = useAsync(
    () => api.getPage<Patient>("/patients", {
      q: query, status, affiliation, ayex: ayexFilter, branch, page: String(page), page_size: String(PAGE_SIZE),
    }),
    [query, status, affiliation, ayexFilter, branch, page],
  );
  const list = patients.data?.items;
  const total = patients.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtersKey = `${query}|${status}|${affiliation}|${ayexFilter}|${branch}`;
  const [lastFilters, setLastFilters] = useState(filtersKey);
  if (filtersKey !== lastFilters) { setLastFilters(filtersKey); setPage(1); }  // filtro nuevo: página 1
  useEffect(() => {
    lastState.set(stateKey, { search: query, status, affiliation, ayex: ayexFilter, branch, page });
  }, [stateKey, query, status, affiliation, ayexFilter, branch, page]);
  const anyFilter = Boolean(query || status || affiliation || branch);

  // La exportación usa los mismos filtros que el listado.
  const exportParams = new URLSearchParams(
    Object.entries({ q: query, status, affiliation, ayex: ayexFilter, branch }).filter(([, v]) => v) as [string, string][],
  ).toString();
  const exportUrl = `/api/patient-export${exportParams ? `?${exportParams}` : ""}`;

  function onSearch(event: FormEvent) {
    event.preventDefault();
    setQuery(search.trim()); // Enter: buscar enseguida, sin esperar la pausa
  }

  function clearFilters() {
    setSearch(""); setQuery(""); setStatus(""); setAffiliation(""); setAyex(""); setBranch("");
  }

  return (
    <>
      <div className="page-title">
        <h1>Pacientes</h1>
        {canCreate && !showForm && !showImport && (
          <div className="title-actions">
            <a className="btn" href={exportUrl} download
               title="Descarga en Excel los pacientes que se ven con los filtros actuales">
              Exportar a Excel
            </a>
            {hasFeature(clinic, "bps") && (<>
              <a className="btn" href="/api/bps-schedule" download
                 title={titular ? "Descarga la planilla del BPS con tus pacientes AYEX activos"
                   : user.role === "admin"
                   ? "Descarga la planilla del BPS con todos los pacientes AYEX activos de la clínica"
                   : "Descarga la planilla del BPS con los pacientes AYEX activos de tu sucursal"}>
                Exportar a Cronograma BPS
              </a>
              <button type="button" className="btn" onClick={() => setShowImport("bps")}
                      title="Carga como pacientes AYEX a los de la hoja USUARIOS de una planilla del Cronograma BPS">
                Importar desde Cronograma BPS
              </button>
            </>)}
            <button type="button" className="btn" onClick={() => setShowImport("csv")}>
              Importar desde CSV
            </button>
            <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
              Nuevo paciente
            </button>
          </div>
        )}
      </div>
      {user.role === "professional" && !titular && (
        <p className="muted">Ves solo los pacientes que tenés asignados o compartidos con vos.</p>
      )}

      {showForm && (
        <NewPatientForm onClose={(created) => { setShowForm(false); if (created) patients.reload(); }} />
      )}
      {showImport && (
        <ImportPatients key={showImport} source={showImport}
                        onClose={(imported) => { setShowImport(null); if (imported) patients.reload(); }} />
      )}

      <Card>
        <form className="toolbar" onSubmit={onSearch} role="search">
          <Field label="Buscar por nombre, apellido o documento">
            {(id) => (
              <input id={id} type="search" value={search} maxLength={100} autoComplete="off"
                     onChange={(e) => setSearch(e.target.value)} />
            )}
          </Field>
          <Field label="Estado">
            {(id) => (
              <select id={id} value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">Todos</option>
                {Object.entries(PATIENT_STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Tipo de afiliación">
            {(id) => (
              <select id={id} value={affiliation} onChange={(e) => setAffiliation(e.target.value)}>
                <option value="">Todos</option>
                {Object.entries(AFFILIATION_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            )}
          </Field>
          {affiliation === "ayex" && (
            <Field label="Vencimiento del AYEX">
              {(id) => (
                <select id={id} value={ayex} onChange={(e) => setAyex(e.target.value)}>
                  <option value="">Todos</option>
                  <option value="due">Vencidos o vencen en los próximos 3 meses</option>
                  <option value="missing">Sin fecha cargada</option>
                </select>
              )}
            </Field>
          )}
          {!titular && (
          <Field label="Sucursal">
            {(id) => (
              <select id={id} value={branch} onChange={(e) => setBranch(e.target.value)}>
                <option value="">
                  {user.role === "professional" ? "Todas (mis pacientes)" : `${activeBranch.name} (actual)`}
                </option>
                <option value="all">
                  {user.role === "reception" ? "Todas las que puedo ver" : "Todas las sucursales"}
                </option>
                {user.role === "admin" && branches.filter((b) => b.id !== activeBranch.id).map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            )}
          </Field>
          )}
          {anyFilter && (
            <button type="button" className="btn" onClick={clearFilters}>Limpiar filtros</button>
          )}
        </form>
        {user.role === "reception" && (
          <p className="muted small">
            Ves los pacientes de {activeBranch.name} y los privados de todas las sucursales (pueden
            atenderse en cualquiera). Los de AYEX, Tutela Militar y Tutela Policial solo se ven en su sucursal.
          </p>
        )}

        {patients.loading && <Loading />}
        <ErrorBox message={patients.error} />
        {list && list.length === 0 && (
          <Empty>
            {anyFilter ? "No hay pacientes que coincidan con la búsqueda." : "Todavía no hay pacientes."}
          </Empty>
        )}
        {list && list.length > 0 && (
          <div className="table-wrap table-cards">
            <table>
              <thead>
                <tr>
                  <th scope="col">Paciente</th>
                  <th scope="col">Documento</th>
                  <th scope="col">Afiliación</th>
                  <th scope="col">Sucursal</th>
                  <th scope="col">Nacimiento</th>
                  <th scope="col">Teléfono</th>
                  <th scope="col">Responsable</th>
                  <th scope="col" className="num" title="Turnos marcados como ausente en este mes. Vuelven a cero cada mes.">
                    Inasistencias <span className="muted small block">este mes</span>
                  </th>
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              <tbody>
                {list.map((p) => (
                  <Fragment key={p.id}>
                  <tr>
                    <td className="card-title">
                      <a href={`#/pacientes/${p.id}`}>
                        {[p.last_name, p.second_last_name].filter(Boolean).join(" ")},{" "}
                        {[p.first_name, p.middle_name].filter(Boolean).join(" ")}
                      </a>
                    </td>
                    <td data-label="Documento">{p.document_number ?? "—"}</td>
                    <td data-label="Afiliación">
                      <span>
                      {AFFILIATION_LABELS[p.affiliation]}
                      {p.affiliation === "ayex" && (
                        <span className={`muted small block${ayexTextClass(ayexState(p.ayex_expires_on))}`}>
                          {p.ayex_expires_on ? `vence ${fmtDate(p.ayex_expires_on)}` : "sin vencimiento"}
                        </span>
                      )}
                      </span>
                    </td>
                    <td data-label="Sucursal">{p.branch_name ?? "—"}</td>
                    <td data-label="Nacimiento">{fmtDate(p.birth_date)}</td>
                    <td data-label="Teléfono">{p.phone ? <a href={telHref(p.phone)}>{p.phone}</a> : "—"}</td>
                    <td data-label="Responsable">
                      <span>
                      {p.responsible_name
                        ? <ProfTag name={p.responsible_name} specialty={specialty.byId(p.responsible_id)} />
                        : <span className="muted">Sin asignar</span>}
                      {assigning !== p.id && (
                        (!p.responsible_id && canManage) || (p.responsible_id && user.role === "admin")
                      ) && (
                        <button type="button" className="link-button" onClick={() => setAssigning(p.id)}
                                aria-label={`${p.responsible_id ? "Cambiar" : "Asignar"} responsable de ${p.first_name} ${p.last_name}`}>
                          {p.responsible_id ? "Cambiar" : "Asignar"}
                        </button>
                      )}
                      {p.collaborator_names && p.collaborator_names.length > 0 && (
                        <div className="small collab-line">
                          <span className="muted">Colaboran:</span>{" "}
                          <ProfTagList names={p.collaborator_names} lookup={specialty} />
                        </div>
                      )}
                      </span>
                    </td>
                    <td className="num" data-label="Inasistencias del mes">
                      {p.no_shows_month
                        ? <Badge tone="warn">{p.no_shows_month}</Badge>
                        : <span className="muted">0</span>}
                    </td>
                    <td data-label="Estado"><Badge tone={STATUS_TONE[p.status]}>{PATIENT_STATUS_LABELS[p.status]}</Badge></td>
                  </tr>
                  {assigning === p.id && (
                    <tr className="inline-row">
                      <td colSpan={9}>
                        <AssignResponsible
                          patient={p}
                          professionals={professionals.data ?? []}
                          onClose={(saved) => { setAssigning(null); if (saved) patients.reload(); }}
                        />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list && total > 0 && (
          <nav className="pager" aria-label="Páginas del listado">
            <span className="muted small">
              Mostrando {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} de {total} pacientes
            </span>
            {pages > 1 && (
              <span className="title-actions">
                <button type="button" className="btn btn-small" disabled={page <= 1}
                        onClick={() => setPage(page - 1)}>← Anterior</button>
                <span className="small">Página {page} de {pages}</span>
                <button type="button" className="btn btn-small" disabled={page >= pages}
                        onClick={() => setPage(page + 1)}>Siguiente →</button>
              </span>
            )}
          </nav>
        )}
      </Card>
    </>
  );
}

function NewPatientForm({ onClose }: { onClose: (created: boolean) => void }) {
  const { user, branch: activeBranch, branches, clinic } = useSession();
  // El profesional independiente siempre queda como responsable, en su único consultorio.
  const titular = isTitular(user, clinic);
  const professionals = useAsync(() => api.get<Professional[]>("/professionals"), []);
  const [form, setForm] = useState({
    document_number: "", first_name: "", middle_name: "", last_name: "", second_last_name: "",
    sex: "", affiliation: "", ayex_expires_on: "", birth_date: "", phone: "", email: "", responsible: "",
    branch_id: activeBranch.id,
  });
  const [address, setAddress] = useState(emptyAddress);
  const { busy, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });
  const options = responsibleOptions(professionals.data ?? [], form.affiliation, form.branch_id);
  const branchName = branches.find((b) => b.id === form.branch_id)?.name ?? "";
  // Si cambia la sucursal o la afiliación y el responsable elegido ya no corresponde, se quita.
  const responsible = options.some((o) => o.id === form.responsible) ? form.responsible : "";

  async function submit(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const created = await api.post<Patient>("/patients", {
        document_number: form.document_number || null,
        first_name: form.first_name,
        middle_name: form.middle_name || null,
        last_name: form.last_name,
        second_last_name: form.second_last_name || null,
        sex: form.sex || null,
        affiliation: form.affiliation,
        ayex_expires_on: form.affiliation === "ayex" ? form.ayex_expires_on || null : null,
        branch_id: form.branch_id,
        birth_date: form.birth_date || null,
        phone: form.phone || null,
        email: form.email || null,
        responsible_professional_id: responsible || null,
        ...addressPayload(address),
      });
      const name = `${created.first_name} ${created.last_name}`;
      if (user.role === "reception" && !receptionCanSee(created, activeBranch.id)) {
        // Recepción no ve desde aquí a los pacientes de AYEX o Tutela de otra sucursal.
        notify(`Paciente ${name} agregado en ${branchName}. Para ver su ficha, cambiá a esa sucursal.`);
        onClose(true);
        return;
      }
      notify(`Paciente ${name} agregado con éxito.`);
      navigate(`/pacientes/${created.id}`);
    });
  }

  return (
    <Card title="Nuevo paciente">
      <p className="muted small">Usá únicamente datos ficticios mientras probás el sistema.</p>
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
        <Field label="Documento (cédula)" hint="Opcional. No puede repetirse en la clínica.">
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
              <option value="">Elegir…</option>
              {Object.entries(AFFILIATION_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </Field>
        {form.affiliation === "ayex" && (
          <Field label="Vencimiento del AYEX" required hint="Obligatorio para pacientes de AYEX. Se avisa en el Inicio 3 meses antes de que venza.">
            {(id, hint) => <input id={id} type="date" required aria-describedby={hint} min="2000-01-01" max="2100-12-31"
                                  value={form.ayex_expires_on} onChange={set("ayex_expires_on")} />}
          </Field>
        )}
        {!titular && (<>
        <Field label="Sucursal" required hint="AYEX, Tutela Militar y Tutela Policial se atienden solo en esta sucursal.">
          {(id, hint) => (
            <select id={id} required aria-describedby={hint} value={form.branch_id} onChange={set("branch_id")}>
              {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
        </Field>
        <Field label="Profesional responsable" hint={form.affiliation && form.affiliation !== "private"
          ? `Podrá ver y escribir la historia clínica. Se muestran quienes atienden en ${branchName}.`
          : "Podrá ver y escribir la historia clínica."}>
          {(id, hint) => (
            <select id={id} aria-describedby={hint} value={responsible} onChange={set("responsible")}>
              <option value="">Asignar más tarde</option>
              {options.map((p) => (
                <option key={p.id} value={p.id}>{p.full_name}{p.specialty_name ? ` (${p.specialty_name})` : ""}</option>
              ))}
            </select>
          )}
        </Field>
        </>)}
        {titular && (
          <p className="span-all muted small">
            Vas a quedar como profesional responsable: podés escribir su historia clínica, darle turnos
            e incluirlo en tus informes.
          </p>
        )}
        <div className="form-actions">
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Guardando…" : "Guardar paciente"}
          </button>
        </div>
      </form>
    </Card>
  );
}

/** Asignar (o, solo administración, cambiar) el responsable desde el listado. */
function AssignResponsible({ patient, professionals, onClose }: {
  patient: Patient; professionals: Professional[]; onClose: (saved: boolean) => void;
}) {
  const changing = Boolean(patient.responsible_id);
  const [professionalId, setProfessionalId] = useState("");
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  // AYEX y Tutelas: solo quienes atienden en la sucursal del paciente.
  const options = responsibleOptions(professionals, patient.affiliation, patient.branch_id)
    .filter((o) => o.id !== patient.responsible_id);
  const noteId = useId();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.post(`/patients/${patient.id}/responsible`, {
        professional_id: professionalId, reason: reason.trim() || null,
      });
    });
    if (ok) onClose(true);
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <ErrorBox message={error} />
      <Field label={`${changing ? "Nuevo responsable" : "Responsable"} de ${patient.first_name} ${patient.last_name}`} required>
        {(id) => (
          <select id={id} required autoFocus value={professionalId} onChange={(e) => setProfessionalId(e.target.value)}>
            <option value="">Elegir…</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>{o.full_name}{o.specialty_name ? ` (${o.specialty_name})` : ""}</option>
            ))}
          </select>
        )}
      </Field>
      {changing && (
        <Field label="Motivo del cambio" required>
          {(id) => (
            <input id={id} aria-describedby={noteId} required minLength={3} maxLength={300} value={reason}
                   onChange={(e) => setReason(e.target.value)} />
          )}
        </Field>
      )}
      <button type="button" className="btn" onClick={() => onClose(false)}>Cancelar</button>
      <button type="submit" className="btn btn-primary" disabled={busy}>
        {busy ? "Guardando…" : changing ? "Cambiar responsable" : "Asignar"}
      </button>
      {options.length === 0 && (
        <p className="muted small inline-note">
          Ningún profesional atiende en la sucursal de este paciente ({patient.branch_name ?? "—"}).
          Administración puede asignarles la sucursal en Usuarios.
        </p>
      )}
      {/* La aclaración va en su propia línea para que los campos queden alineados. */}
      {changing && (
        <p id={noteId} className="muted small inline-note">
          Sus turnos futuros con el paciente pasan al nuevo responsable.
        </p>
      )}
    </form>
  );
}

/** Color del texto "vence …" en el listado: rojo si venció o faltan 2 meses o menos, amarillo hasta 3. */
function ayexTextClass(state: ReturnType<typeof ayexState>): string {
  if (state === "expired" || state === "red") return " text-danger";
  if (state === "yellow") return " text-warn";
  return "";
}
