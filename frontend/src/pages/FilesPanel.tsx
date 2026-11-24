// Pestaña "Archivos": PDF e imágenes del paciente. Los ven y suben los profesionales con acceso
// al paciente, Administración y Recepción.
import { useId, useRef, useState, type FormEvent } from "react";
import { api, uploadFile } from "../api";
import { Badge, Card, Dialog, Empty, ErrorBox, Field, Loading } from "../components";
import { notify } from "../toast";
import { useAction, useAsync } from "../hooks";
import { fmtDateTime, fmtSize } from "../labels";
import type { PatientFile } from "../types";

const MAX_MB = 10;

/** Con ``institutionId``: solo los archivos de esa institución educativa, y los nuevos se
 * suben a ella. Sin él: todos los archivos del paciente (los de instituciones, marcados). */
export function FilesPanel({ patientId, institutionId, title = "Archivos del paciente" }: {
  patientId: string; institutionId?: string; title?: string;
}) {
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const files = useAsync(
    () => api.get<PatientFile[]>(`/patients/${patientId}/files`,
      { include_withdrawn: showWithdrawn ? "true" : undefined }),
    [patientId, showWithdrawn],
  );
  const list = files.data ? files.data.filter((f) => !institutionId || f.institution_id === institutionId) : null;
  const [withdrawing, setWithdrawing] = useState<PatientFile | null>(null);
  const [viewing, setViewing] = useState<PatientFile | null>(null);

  /** En el celular, un PDF dentro de una ventana muestra solo la primera página (iPhone): se
   * abre en otra pestaña con el visor del teléfono. En la computadora, en la ventana de Nordeste. */
  function view(f: PatientFile) {
    const small = window.matchMedia?.("(max-width: 640px)").matches;
    if (small && f.content_type === "application/pdf") {
      window.open(`/api/files/${f.id}/download?view=true`, "_blank", "noopener");
      return;
    }
    setViewing(f);
  }

  return (
    <>
      <UploadForm patientId={patientId} institutionId={institutionId} onUploaded={files.reload} />
      <Card
        title={title}
        actions={(
          <label className="checkbox">
            <input type="checkbox" checked={showWithdrawn} onChange={(e) => setShowWithdrawn(e.target.checked)} />
            Mostrar retirados
          </label>
        )}
      >
        <p className="muted small">
          Ven estos archivos los profesionales con acceso al paciente, Administración y Recepción.
          Cada vez que se abre o descarga uno queda registrado.
          Los archivos no se borran: se retiran indicando el motivo.
        </p>
        {files.loading && <Loading />}
        <ErrorBox message={files.error} />
        {list && list.length === 0 && <Empty>No hay archivos.</Empty>}
        {list && list.length > 0 && (
          <div className="table-wrap table-cards">
            <table>
              <thead>
                <tr>
                  <th scope="col">Archivo</th><th scope="col">Subido</th><th scope="col">Tamaño</th>
                  <th scope="col"><span className="sr-only">Acciones</span></th>
                </tr>
              </thead>
              <tbody>
                {list.map((f) => (
                  <tr key={f.id} className={f.withdrawn_at ? "row-muted" : undefined}>
                    <td className="card-title">
                      <span className="file-kind" aria-hidden="true">{f.content_type === "application/pdf" ? "PDF" : "IMG"}</span>{" "}
                      {f.withdrawn_at ? f.original_name : (
                        <button type="button" className="link-button" onClick={() => view(f)}
                                title="Ver sin descargar">{f.original_name}</button>
                      )}
                      {f.description && <div className="muted small">{f.description}</div>}
                      {!institutionId && f.institution_name && (
                        <div className="muted small">Institución: {f.institution_name}</div>
                      )}
                      {f.withdrawn_at && (
                        <div className="small">
                          <Badge tone="warn">Retirado</Badge> {fmtDateTime(f.withdrawn_at)} por {f.withdrawn_by_name}
                          {" — "}{f.withdraw_reason}
                        </div>
                      )}
                    </td>
                    <td data-label="Subido">
                      <span>{fmtDateTime(f.created_at)}<span className="muted small block">{f.uploaded_by_name}</span></span>
                    </td>
                    <td data-label="Tamaño">{fmtSize(f.size_bytes)}</td>
                    <td className="row-actions">
                      {!f.withdrawn_at && (
                        <>
                          <button type="button" className="btn btn-small btn-primary" onClick={() => view(f)}
                                  aria-label={`Ver ${f.original_name}`}>Ver</button>
                          <a className="btn btn-small" href={`/api/files/${f.id}/download`}
                             aria-label={`Descargar ${f.original_name}`}>Descargar</a>
                        </>
                      )}
                      {f.can_withdraw && (
                        <button type="button" className="btn btn-small btn-danger" onClick={() => setWithdrawing(f)}>
                          Retirar
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {withdrawing && (
          <WithdrawForm file={withdrawing} onDone={(ok) => { setWithdrawing(null); if (ok) files.reload(); }} />
        )}
      </Card>
      {viewing && <FileViewer file={viewing} onClose={() => setViewing(null)} />}
    </>
  );
}

function UploadForm({ patientId, institutionId, onUploaded }: {
  patientId: string; institutionId?: string; onUploaded: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [description, setDescription] = useState("");
  const { busy, error, setError, run } = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const file = input.current?.files?.[0];
    if (!file) { setError("Elegí un archivo."); return; }
    if (file.size > MAX_MB * 1024 * 1024) { setError(`El archivo supera el máximo de ${MAX_MB} MB.`); return; }
    const ok = await run(async () => {
      await uploadFile(`/patients/${patientId}/files`, file,
        { filename: file.name, ...(description ? { description } : {}),
          ...(institutionId ? { institution_id: institutionId } : {}) });
    });
    if (ok) {
      notify(`Archivo "${file.name}" subido.`);
      setDescription("");
      if (input.current) input.current.value = "";
      onUploaded();
    }
  }

  return (
    <Card title="Subir archivo">
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Archivo" required hint={`PDF, PNG o JPG, hasta ${MAX_MB} MB.`}>
          {(id, hint) => (
            <input id={id} ref={input} type="file" aria-describedby={hint}
                   accept="application/pdf,image/png,image/jpeg" />
          )}
        </Field>
        <Field label="Descripción" hint="Opcional. Por ejemplo: informe escolar 2026.">
          {(id, hint) => (
            <input id={id} aria-describedby={hint} maxLength={300} value={description}
                   onChange={(e) => setDescription(e.target.value)} />
          )}
        </Field>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Subiendo…" : "Subir archivo"}
          </button>
        </div>
      </form>
    </Card>
  );
}

/** Ventana para retirar un archivo (antes el formulario aparecía al pie de la tabla). */
function WithdrawForm({ file, onDone }: { file: PatientFile; onDone: (ok: boolean) => void }) {
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  const titleId = useId();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await run(async () => { await api.post(`/files/${file.id}/withdraw`, { reason }); });
    if (ok) {
      notify(`Archivo "${file.original_name}" retirado.`);
      onDone(true);
    }
  }

  return (
    <Dialog labelledBy={titleId} onClose={() => onDone(false)}>
      <div className="modal-head">
        <h2 id={titleId}>Retirar "{file.original_name}"</h2>
        <button type="button" className="icon-close" onClick={() => onDone(false)} aria-label="Cerrar">✕</button>
      </div>
      <p className="muted small">
        El archivo no se borra: deja de mostrarse y queda en el historial con el motivo.
      </p>
      <form onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Motivo" required>
          {(id) => <input id={id} required minLength={3} maxLength={300} value={reason} data-autofocus
                          onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <div className="form-actions">
          <button type="button" className="btn" onClick={() => onDone(false)}>Cancelar</button>
          <button type="submit" className="btn btn-danger" disabled={busy}>
            {busy ? "Retirando…" : "Retirar archivo"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Visor dentro de Nordeste: el PDF o la imagen se muestra en una ventana, sin descargarlo.
 * El servidor lo envía para verse "en línea" y solo deja mostrarlo dentro de Nordeste. */
function FileViewer({ file, onClose }: { file: PatientFile; onClose: () => void }) {
  return (
    <DocumentViewer name={file.original_name} contentType={file.content_type} alt={file.description ?? undefined}
                    src={`/api/files/${file.id}/download?view=true`} downloadUrl={`/api/files/${file.id}/download`}
                    onClose={onClose} />
  );
}

/** Ventana para ver un PDF o una imagen dentro de Nordeste, sin descargarlo. */
export function DocumentViewer({ name, contentType, src, downloadUrl, alt, onClose }: {
  name: string; contentType: string; src: string; downloadUrl: string; alt?: string; onClose: () => void;
}) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const isPdf = contentType === "application/pdf";
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);

  return (
    <Dialog className="viewer" labelledBy={titleId} onClose={onClose} initialFocus={closeRef}>
      <header className="viewer-head">
        <strong id={titleId} className="viewer-title">{name}</strong>
        <a className="btn btn-small" href={downloadUrl}>Descargar</a>
        <button type="button" ref={closeRef} className="btn btn-small" onClick={onClose}>Cerrar</button>
      </header>
      <div className="viewer-body">
        {!isPdf && !loaded && !failed && <Loading text="Abriendo archivo…" />}
        {failed && <ErrorBox message="No se pudo mostrar el archivo. Prueba con Descargar." />}
        {isPdf ? (
          <iframe src={src} title={name} className="viewer-pdf" onLoad={() => setLoaded(true)} />
        ) : (
          <img src={src} alt={alt ?? name} className="viewer-img"
               hidden={!loaded} onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
        )}
      </div>
    </Dialog>
  );
}
