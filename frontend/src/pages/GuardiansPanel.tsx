// Pestaña "Responsables": madre, padre o tutor de un paciente (datos de contacto).
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { askConfirm } from "../confirm";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import { telHref } from "../labels";
import { notify } from "../toast";
import type { Guardian } from "../types";

const RELATIONSHIPS = ["Madre", "Padre", "Tutor/a legal", "Abuelo/a", "Hermano/a", "Pareja", "Otro"];

export function GuardiansPanel({ patientId, canEdit }: { patientId: string; canEdit: boolean }) {
  const guardians = useAsync(() => api.get<Guardian[]>(`/patients/${patientId}/guardians`), [patientId]);
  const [editing, setEditing] = useState<Guardian | "new" | null>(null);
  const action = useAction();

  async function remove(g: Guardian) {
    if (!await askConfirm(`¿Quitar a ${g.full_name} de los responsables de este paciente?`,
                          { confirmLabel: "Quitar", danger: true })) return;
    const ok = await action.run(async () => { await api.del(`/patients/${patientId}/guardians/${g.id}`); });
    if (ok) { notify(`${g.full_name} ya no figura como responsable.`); guardians.reload(); }
  }

  return (
    <>
      <Card
        title="Responsables"
        actions={canEdit && editing === null && (
          <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>
            Agregar responsable
          </button>
        )}
      >
        <p className="muted small">
          Personas de contacto del paciente, por ejemplo la madre, el padre o el tutor de un menor.
        </p>
        <ErrorBox message={action.error} />
        {guardians.loading && <Loading />}
        <ErrorBox message={guardians.error} />
        {guardians.data && guardians.data.length === 0 && <Empty>No hay responsables cargados.</Empty>}
        {guardians.data && guardians.data.length > 0 && (
          <div className="guardian-grid">
            {guardians.data.map((g) => (
              <article key={g.id} className="guardian">
                <header>
                  <strong>{g.full_name}</strong>
                  {g.is_primary && <Badge tone="info">Contacto principal</Badge>}
                </header>
                <p className="muted small">{g.relationship}</p>
                {!g.first_name && (
                  <p className="small text-danger">Falta separar primer nombre y primer apellido (editá el responsable).</p>
                )}
                <dl className="details compact">
                  <dt>C.I.</dt>
                  <dd>{g.document_number ?? <span className="text-danger">Falta cargarla (editá el responsable)</span>}</dd>
                  <dt>Teléfono</dt><dd>{g.phone ? <a href={telHref(g.phone)}>{g.phone}</a> : "—"}</dd>
                  <dt>Correo</dt><dd>{g.email ? <a href={`mailto:${g.email}`}>{g.email}</a> : "—"}</dd>
                  {g.notes && (<><dt>Notas</dt><dd>{g.notes}</dd></>)}
                </dl>
                {canEdit && (
                  <div className="row-actions">
                    <button type="button" className="btn btn-small" onClick={() => setEditing(g)}>Editar</button>
                    <button type="button" className="btn btn-small btn-danger" onClick={() => remove(g)}
                            disabled={action.busy}>Quitar</button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </Card>
      {editing !== null && (
        <GuardianForm
          key={editing === "new" ? "new" : editing.id}
          patientId={patientId}
          guardian={editing === "new" ? null : editing}
          onClose={(saved) => { setEditing(null); if (saved) guardians.reload(); }}
        />
      )}
    </>
  );
}

function GuardianForm({ patientId, guardian, onClose }: {
  patientId: string; guardian: Guardian | null; onClose: (saved: boolean) => void;
}) {
  // Responsables cargados antes de separar nombre y apellido: se propone una división del
  // nombre completo para revisar.
  const split = guardian && !guardian.first_name ? splitName(guardian.full_name) : null;
  const [form, setForm] = useState({
    first_name: guardian?.first_name ?? split?.first_name ?? "",
    middle_name: guardian?.middle_name ?? split?.middle_name ?? "",
    last_name: guardian?.last_name ?? split?.last_name ?? "",
    second_last_name: guardian?.second_last_name ?? split?.second_last_name ?? "",
    document_number: guardian?.document_number ?? "",
    relationship: guardian?.relationship ?? "Madre",
    phone: guardian?.phone ?? "",
    email: guardian?.email ?? "",
    is_primary: guardian?.is_primary ?? false,
    notes: guardian?.notes ?? "",
  });
  const { busy, error, run } = useAction();
  const set = (key: "first_name" | "middle_name" | "last_name" | "second_last_name" | "document_number"
    | "relationship" | "phone" | "email" | "notes") =>
    (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      ...form, middle_name: form.middle_name || null, second_last_name: form.second_last_name || null,
      phone: form.phone || null, email: form.email || null, notes: form.notes || null,
    };
    const ok = await run(async () => {
      if (guardian) await api.patch(`/patients/${patientId}/guardians/${guardian.id}`, body);
      else await api.post(`/patients/${patientId}/guardians`, body);
    });
    if (ok) {
      notify(guardian ? "Responsable actualizado." : "Responsable agregado.");
      onClose(true);
    }
  }

  return (
    <Card title={guardian ? `Editar responsable: ${guardian.full_name}` : "Nuevo responsable"}>
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        {split && (
          <p className="alert alert-info span-all small">
            Separamos el nombre "{guardian?.full_name}" automáticamente: revisá que nombre y apellido estén bien.
          </p>
        )}
        <Field label="Primer nombre" required>
          {(id) => <input id={id} required maxLength={100} value={form.first_name} onChange={set("first_name")} />}
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
        <Field label="C.I." required hint="Cédula de identidad del responsable.">
          {(id, hint) => (
            <input id={id} aria-describedby={hint} required minLength={3} maxLength={30}
                   value={form.document_number} onChange={set("document_number")} />
          )}
        </Field>
        <Field label="Vínculo" required>
          {(id) => (
            <input id={id} required minLength={2} maxLength={60} list="relationship-options" value={form.relationship}
                   onChange={set("relationship")} />
          )}
        </Field>
        <datalist id="relationship-options">
          {RELATIONSHIPS.map((r) => <option key={r} value={r} />)}
        </datalist>
        <Field label="Teléfono">
          {(id) => <input id={id} type="tel" maxLength={40} value={form.phone} onChange={set("phone")} />}
        </Field>
        <Field label="Correo electrónico">
          {(id) => <input id={id} type="email" maxLength={254} value={form.email} onChange={set("email")} />}
        </Field>
        <div className="span-all">
          <Field label="Notas" hint="Por ejemplo: horarios en que se lo puede llamar. Sin datos clínicos.">
            {(id, hint) => <input id={id} aria-describedby={hint} maxLength={300} value={form.notes} onChange={set("notes")} />}
          </Field>
          <label className="checkbox">
            <input type="checkbox" checked={form.is_primary}
                   onChange={(e) => setForm({ ...form, is_primary: e.target.checked })} />
            Contacto principal
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

/** Propuesta para separar un nombre completo: 2 palabras = nombre + apellido; 3 = nombre +
 * dos apellidos; 4 o más = dos nombres + dos apellidos. La persona la revisa antes de guardar. */
function splitName(full: string) {
  const w = full.trim().split(/\s+/);
  if (w.length <= 2) return { first_name: w[0] ?? "", middle_name: "", last_name: w[1] ?? "", second_last_name: "" };
  if (w.length === 3) return { first_name: w[0], middle_name: "", last_name: w[1], second_last_name: w[2] };
  return { first_name: w[0], middle_name: w.slice(1, -2).join(" "), last_name: w[w.length - 2],
           second_last_name: w[w.length - 1] };
}
