// Pestaña "Instituciones": escuela, liceo, UTU o universidad del paciente.
// El nombre, el nivel y el contacto los ve quien ve la ficha; los reportes y archivos de cada
// institución son clínicos y solo los ven los profesionales con acceso al paciente.
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { askConfirm } from "../confirm";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import { INSTITUTION_LEVEL_LABELS, telHref } from "../labels";
import { notify } from "../toast";
import type { Institution, InstitutionLevel } from "../types";
import { FilesPanel } from "./FilesPanel";
import { NotesPanel } from "./NotesPanel";

export function InstitutionsPanel({ patientId, canEdit, canViewClinical }: {
  patientId: string; canEdit: boolean; canViewClinical: boolean;
}) {
  const institutions = useAsync(() => api.get<Institution[]>(`/patients/${patientId}/institutions`), [patientId]);
  const [editing, setEditing] = useState<Institution | "new" | null>(null);
  const [open, setOpen] = useState<string | null>(null); // institución con reportes y archivos abiertos
  const action = useAction();
  const selected = institutions.data?.find((i) => i.id === open) ?? null;

  async function remove(inst: Institution) {
    if (!await askConfirm(`¿Quitar "${inst.name}" de las instituciones de este paciente?`,
                          { confirmLabel: "Quitar", danger: true })) return;
    const ok = await action.run(async () => { await api.del(`/patients/${patientId}/institutions/${inst.id}`); });
    if (ok) { notify(`"${inst.name}" quitada de las instituciones.`); if (open === inst.id) setOpen(null); institutions.reload(); }
  }

  return (
    <>
      <Card
        title="Instituciones"
        actions={canEdit && editing === null && (
          <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>
            Agregar institución
          </button>
        )}
      >
        <p className="muted small">
          Escuela, liceo, UTU o universidad a la que va el paciente, con su contacto.
          {canViewClinical
            ? " En cada una se pueden escribir reportes y subir archivos."
            : " Los reportes y archivos de cada institución solo los ven los profesionales con acceso al paciente."}
        </p>
        <ErrorBox message={action.error} />
        {institutions.loading && <Loading />}
        <ErrorBox message={institutions.error} />
        {institutions.data && institutions.data.length === 0 && <Empty>No hay instituciones cargadas.</Empty>}
        {institutions.data && institutions.data.length > 0 && (
          <div className="guardian-grid">
            {institutions.data.map((inst) => (
              <article key={inst.id} className={open === inst.id ? "guardian selected" : "guardian"}>
                <header>
                  <strong>{inst.name}</strong>
                  {inst.is_current ? <Badge tone="ok">Actual</Badge> : <Badge tone="neutral">Anterior</Badge>}
                </header>
                <p className="muted small">{INSTITUTION_LEVEL_LABELS[inst.level]}</p>
                <dl className="details compact">
                  <dt>Teléfono</dt>
                  <dd>{inst.phone ? <a href={telHref(inst.phone)}>{inst.phone}</a> : "—"}</dd>
                  <dt>Correo</dt>
                  <dd>{inst.email ? <a href={`mailto:${inst.email}`}>{inst.email}</a> : "—"}</dd>
                </dl>
                <div className="row-actions">
                  {canViewClinical && (
                    <button type="button" className={open === inst.id ? "btn btn-small btn-primary" : "btn btn-small"}
                            aria-expanded={open === inst.id}
                            onClick={() => setOpen(open === inst.id ? null : inst.id)}>
                      {open === inst.id ? "Ocultar reportes y archivos" : "Reportes y archivos"}
                    </button>
                  )}
                  {canEdit && (
                    <>
                      <button type="button" className="btn btn-small" onClick={() => setEditing(inst)}>Editar</button>
                      <button type="button" className="btn btn-small btn-danger" onClick={() => remove(inst)}
                              disabled={action.busy}>Quitar</button>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </Card>
      {editing !== null && (
        <InstitutionForm
          key={editing === "new" ? "new" : editing.id}
          patientId={patientId}
          institution={editing === "new" ? null : editing}
          onClose={(saved) => { setEditing(null); if (saved) institutions.reload(); }}
        />
      )}
      {selected && canViewClinical && (
        <section className="institution-records" aria-label={`Reportes y archivos de ${selected.name}`}>
          <h2 className="section-title">Reportes y archivos: {selected.name}</h2>
          <NotesPanel key={`notes-${selected.id}`} patientId={patientId} kinds={["institution"]}
                      institutionId={selected.id} title="Reportes"
                      emptyText="Todavía no hay reportes de esta institución." />
          <FilesPanel key={`files-${selected.id}`} patientId={patientId} institutionId={selected.id}
                      title={`Archivos de ${selected.name}`} />
        </section>
      )}
    </>
  );
}

function InstitutionForm({ patientId, institution, onClose }: {
  patientId: string; institution: Institution | null; onClose: (saved: boolean) => void;
}) {
  const [form, setForm] = useState({
    name: institution?.name ?? "",
    level: (institution?.level ?? "primaria") as InstitutionLevel,
    phone: institution?.phone ?? "",
    email: institution?.email ?? "",
    is_current: institution?.is_current ?? true,
  });
  const { busy, error, run } = useAction();
  const set = (key: "name" | "level" | "phone" | "email") =>
    (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = { ...form, phone: form.phone || null, email: form.email || null };
    const ok = await run(async () => {
      if (institution) await api.patch(`/patients/${patientId}/institutions/${institution.id}`, body);
      else await api.post(`/patients/${patientId}/institutions`, body);
    });
    if (ok) {
      notify(institution ? "Institución actualizada." : "Institución agregada.");
      onClose(true);
    }
  }

  return (
    <Card title={institution ? `Editar institución: ${institution.name}` : "Nueva institución"}>
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Nombre de la institución" required hint="Por ejemplo: Escuela N.º 12, Liceo Pando.">
          {(id, hint) => (
            <input id={id} aria-describedby={hint} required minLength={2} maxLength={200}
                   value={form.name} onChange={set("name")} />
          )}
        </Field>
        <Field label="Nivel" required>
          {(id) => (
            <select id={id} required value={form.level} onChange={set("level")}>
              {Object.entries(INSTITUTION_LEVEL_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </Field>
        <Field label="Teléfono de contacto">
          {(id) => <input id={id} type="tel" maxLength={40} value={form.phone} onChange={set("phone")} />}
        </Field>
        <Field label="Correo de contacto">
          {(id) => <input id={id} type="email" maxLength={254} value={form.email} onChange={set("email")} />}
        </Field>
        <div className="span-all">
          <label className="checkbox">
            <input type="checkbox" checked={form.is_current}
                   onChange={(e) => setForm({ ...form, is_current: e.target.checked })} />
            Es la institución actual del paciente (si hay otra marcada, pasa a "Anterior")
          </label>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Guardando…" : "Guardar"}
          </button>
        </div>
      </form>
    </Card>
  );
}
