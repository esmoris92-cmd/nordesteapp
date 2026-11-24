import { useRef, useState, type FormEvent } from "react";
import { api, uploadFile } from "../api";
import { Badge, Card, ErrorBox, Field, Loading, PasswordInput } from "../components";
import { useAction, useAsync } from "../hooks";
import { fmtDateTime, fmtSize, ROLE_LABELS } from "../labels";
import { hasFeature, useSession } from "../session";
import { notify } from "../toast";
import type { Degree } from "../types";
import { BpsFields, bpsForm, bpsMissing, bpsPayload, type BpsForm } from "./BpsFields";
import { DocumentViewer } from "./FilesPanel";

export function AccountPage() {
  const { user, clinic } = useSession();

  return (
    <>
      <div className="page-title"><h1>Mi cuenta</h1></div>
      <PersonalDataCard />
      <Card title="Datos de la cuenta">
        <dl className="details">
          <dt>Correo (para entrar)</dt><dd>{user.email}</dd>
          <dt>Rol</dt><dd>{ROLE_LABELS[user.role]}</dd>
          {user.specialty_name && (<><dt>Especialidad</dt><dd>{user.specialty_name}</dd></>)}
          <dt>Clínica</dt><dd>{clinic.name}</dd>
        </dl>
        <p className="muted small">El correo, el rol, la especialidad y las sucursales los cambia Administración.</p>
      </Card>
      {user.role === "professional" && hasFeature(clinic, "bps") && <BpsDataCard />}
      {user.role === "professional" && <DegreeCard />}
      <Card title="Cambiar contraseña">
        <ChangePasswordForm
          currentLabel="Contraseña actual"
          onChanged={() => notify("Contraseña actualizada. Se cerraron tus otras sesiones abiertas.")}
        />
      </Card>
    </>
  );
}

/** Formulario para cambiar la contraseña (en "Mi cuenta" y al entrar con una temporal). */
export function ChangePasswordForm({ currentLabel, onChanged, endpoint = "/auth/change-password" }: {
  currentLabel: string; onChanged: () => void;
  endpoint?: string; // el dueño del sistema usa su propia ruta
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [show, setShow] = useState(false); // un solo botón muestra u oculta los tres campos
  const { busy, error, setError, run } = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== repeat) {
      setError("Las contraseñas nuevas no coinciden.");
      return;
    }
    const ok = await run(async () => {
      await api.post(endpoint, { current_password: current, new_password: next });
    });
    if (ok) {
      setCurrent("");
      setNext("");
      setRepeat("");
      onChanged();
    }
  }

  return (
    <form className="narrow-form" onSubmit={submit}>
      <ErrorBox message={error} />
      <Field label={currentLabel} required>
        {(id) => <PasswordInput id={id} required autoComplete="current-password" show={show}
                                onToggle={() => setShow(!show)}
                                value={current} onChange={(e) => setCurrent(e.target.value)} />}
      </Field>
      <Field label="Contraseña nueva" required hint="Mínimo 12 caracteres.">
        {(id, hint) => <PasswordInput id={id} aria-describedby={hint} required minLength={12}
                                      maxLength={128} autoComplete="new-password" show={show}
                                      onToggle={() => setShow(!show)}
                                      value={next} onChange={(e) => setNext(e.target.value)} />}
      </Field>
      <Field label="Repetir contraseña nueva" required>
        {(id) => <PasswordInput id={id} required minLength={12} maxLength={128} show={show}
                                onToggle={() => setShow(!show)}
                                autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />}
      </Field>
      <button type="submit" className="btn btn-primary" disabled={busy}>Cambiar contraseña</button>
    </form>
  );
}

const MAX_MB = 10;

/** Título universitario del profesional: obligatorio (foto JPG/PNG o PDF). Lo ven solo la
 * persona y Administración. Si se sube otro, el anterior queda guardado como reemplazado. */
function DegreeCard() {
  const { refresh } = useSession();
  const degree = useAsync(() => api.get<Degree | null>("/account/degree"), []);
  const input = useRef<HTMLInputElement>(null);
  const [viewing, setViewing] = useState(false);
  const { busy, error, setError, run } = useAction();
  const current = degree.data;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const file = input.current?.files?.[0];
    if (!file) { setError("Elegí la foto o el PDF de tu título."); return; }
    if (file.size > MAX_MB * 1024 * 1024) { setError(`El archivo supera el máximo de ${MAX_MB} MB.`); return; }
    const ok = await run(async () => {
      await uploadFile("/account/degree", file, { filename: file.name });
    });
    if (ok) {
      notify(current ? "Título reemplazado." : "Título subido. ¡Gracias!");
      if (input.current) input.current.value = "";
      degree.reload();
      await refresh(); // quita el aviso de "falta tu título"
    }
  }

  return (
    <Card title="Título universitario" actions={current
      ? <Badge tone="ok">Cargado</Badge> : <Badge tone="warn">Obligatorio: falta cargarlo</Badge>}>
      <p className="muted small">
        Subí una foto clara de tu título (JPG o PNG) o un PDF, de hasta {MAX_MB} MB. Solo lo ven
        Administración y vos.
      </p>
      {degree.loading && <Loading />}
      <ErrorBox message={degree.error} />
      {current && (
        <p>
          <button type="button" className="link-button" style={{ marginLeft: 0 }} onClick={() => setViewing(true)}>
            {current.original_name}
          </button>{" "}
          <span className="muted small">· {fmtSize(current.size_bytes)} · subido {fmtDateTime(current.created_at)}</span>
        </p>
      )}
      <form className="inline-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label={current ? "Reemplazar por otro archivo" : "Foto o PDF del título"} required={!current}>
          {(id) => <input id={id} ref={input} type="file" accept="image/jpeg,image/png,application/pdf" />}
        </Field>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Subiendo…" : current ? "Reemplazar título" : "Subir título"}
        </button>
      </form>
      {viewing && current && (
        <DocumentViewer name={current.original_name} contentType={current.content_type}
                        src={`/api/degrees/${current.id}/download?view=true`}
                        downloadUrl={`/api/degrees/${current.id}/download`} onClose={() => setViewing(false)} />
      )}
    </Card>
  );
}

/** Datos personales que cada persona cambia por sí misma: nombre, C.I. (obligatoria) y teléfono. */
function PersonalDataCard() {
  const { user, refresh } = useSession();
  const [form, setForm] = useState({
    full_name: user.full_name, document_number: user.document_number ?? "", phone: user.phone ?? "",
  });
  const { busy, error, run } = useAction();
  const changed = form.full_name !== user.full_name || form.document_number !== (user.document_number ?? "")
    || form.phone !== (user.phone ?? "");
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => {
      await api.patch("/account", {
        full_name: form.full_name, document_number: form.document_number, phone: form.phone || null,
      });
    });
    if (ok) {
      notify("Tus datos se guardaron.");
      await refresh(); // actualiza el nombre del encabezado y quita el aviso de la C.I.
    }
  }

  return (
    <Card title="Mis datos personales" actions={!user.document_number && <Badge tone="warn">Falta la C.I.</Badge>}>
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Nombre completo" required>
          {(id) => <input id={id} required minLength={2} maxLength={200} value={form.full_name}
                          onChange={set("full_name")} />}
        </Field>
        <Field label="C.I." required hint="Cédula de identidad. No puede repetirse con otra cuenta.">
          {(id, hint) => <input id={id} aria-describedby={hint} required minLength={3} maxLength={30}
                                value={form.document_number} onChange={set("document_number")} />}
        </Field>
        <Field label="Teléfono">
          {(id) => <input id={id} type="tel" maxLength={40} value={form.phone} onChange={set("phone")} />}
        </Field>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? "Guardando…" : "Guardar mis datos"}
          </button>
        </div>
      </form>
    </Card>
  );
}

/** Datos que pide el Cronograma del BPS (obligatorios para profesionales). */
function BpsDataCard() {
  const { user, clinic, refresh } = useSession();
  const [form, setForm] = useState<BpsForm>(() => bpsForm(user));
  const { busy, error, run } = useAction();
  const original = bpsForm(user);
  const changed = (Object.keys(form) as (keyof BpsForm)[]).some((k) => form[k] !== original[k]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => { await api.patch("/account", bpsPayload(form)); });
    if (ok) {
      notify("Tus datos para el BPS se guardaron.");
      await refresh(); // quita el aviso de "faltan tus datos para el BPS"
    }
  }

  return (
    <Card title="Datos para el BPS" actions={bpsMissing(user, clinic)
      ? <Badge tone="warn">Obligatorio: faltan datos</Badge> : <Badge tone="ok">Completos</Badge>}>
      <p className="muted small">
        Se usan en el Cronograma de Ayudas Extraordinarias (AYEX) que la clínica presenta al BPS.
        Escribí tu nombre como figura en tu C.I.
      </p>
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <BpsFields form={form} onChange={setForm} required />
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy || !changed}>
            {busy ? "Guardando…" : "Guardar datos para el BPS"}
          </button>
        </div>
      </form>
    </Card>
  );
}
