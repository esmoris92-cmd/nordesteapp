// Importar pacientes desde un CSV o desde la planilla del Cronograma BPS (.xlsx):
// revisar primero (sin guardar) y después confirmar.
import { useRef, useState, type FormEvent } from "react";
import { uploadAndDownload, uploadFile } from "../api";
import { Badge, Card, ErrorBox, Field, SuccessBox } from "../components";
import { useAction } from "../hooks";
import { AFFILIATION_LABELS, fmtDate } from "../labels";
import { isTitular, useSession } from "../session";
import type { ImportResult } from "../types";

const MAX_MB = 2;

export type ImportSource = "csv" | "bps";

export function ImportPatients({ source, onClose }: {
  source: ImportSource;
  onClose: (imported: boolean) => void;
}) {
  const bps = source === "bps";
  // Profesional independiente: queda como responsable de todo lo que importa.
  const { user, clinic } = useSession();
  const titular = isTitular(user, clinic);
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [done, setDone] = useState<ImportResult | null>(null);
  const { busy, error, setError, run } = useAction();

  function choose(f: File | null) {
    setFile(f);
    setPreview(null);
    setDone(null);
    setError(null);
  }

  async function check(event: FormEvent) {
    event.preventDefault();
    if (!file) { setError(bps ? "Elegí la planilla del Cronograma (.xlsx)." : "Elegí un archivo CSV."); return; }
    if (file.size > MAX_MB * 1024 * 1024) { setError(`El archivo supera el máximo de ${MAX_MB} MB.`); return; }
    await run(async () => {
      setPreview(await uploadFile<ImportResult>("/patient-import", file, { dry_run: "true" }));
    });
  }

  async function confirm() {
    if (!file) return;
    const ok = await run(async () => {
      setDone(await uploadFile<ImportResult>("/patient-import", file, { dry_run: "false" }));
    });
    if (ok) {
      setPreview(null);
      setFile(null);
      if (input.current) input.current.value = "";
    }
  }

  async function downloadErrors() {
    if (!file) return;
    await run(async () => {
      await uploadAndDownload("/patient-import/errors", file, "lumen-pacientes-con-errores.csv");
    });
  }

  const rows = (preview?.rows ?? []).filter((r) => !onlyErrors || r.status === "error");

  return (
    <Card title={bps ? "Importar pacientes desde el Cronograma BPS" : "Importar pacientes desde CSV"}>
      {bps ? (
        <ol className="steps small">
          <li>
            Elegí la planilla del <strong>Cronograma de Actividades</strong> del BPS (el Excel <code>.xlsx</code>,
            tal como lo descargás o te lo mandan). Se leen los pacientes de la hoja <strong>USUARIOS</strong>:
            documento, apellidos, nombres, teléfono y dirección.
          </li>
          <li>
            Entran como pacientes <strong>AYEX</strong> activos{titular ? <> y vos quedás como responsable</> : " de la sucursal actual"}. Los que ya están en
            Lumen (mismo documento) se saltean. Los horarios de las hojas LUN a SAB no se importan: los
            turnos se cargan en la Agenda.
          </li>
          <li>
            Revisalo: no se guarda nada hasta que confirmes. Después completá en cada paciente el
            vencimiento del AYEX (el Inicio te avisa cuáles faltan).
          </li>
        </ol>
      ) : (
      <ol className="steps small">
        <li>
          Descargá la <a href="/api/patient-import/template" download>planilla modelo</a> y abrila en Excel,
          o usá tu planilla con las mismas columnas (obligatorias: <strong>primer_nombre</strong>,{" "}
          <strong>primer_apellido</strong> y <strong>tipo_afiliacion</strong>).{" "}
          {titular ? <>Vas a quedar como profesional responsable de todos: las columnas <strong>sucursal</strong> y{" "}
            <strong>profesional_responsable</strong> no hacen falta.</>
            : <>La columna <strong>sucursal</strong> es opcional: si falta, los pacientes quedan en la sucursal actual.</>}
        </li>
        <li>
          En Excel: <em>Archivo → Guardar como → CSV UTF-8</em>. Fechas como <code>14/03/2015</code>;
          sexo <code>M</code>, <code>F</code> o <code>X</code>; tipo de afiliación <code>Privado</code>,{" "}
          <code>AYEX</code>, <code>Tutela Militar</code> o <code>Tutela Policial</code>
          {titular ? "." : "; responsable con su correo o nombre completo tal como figura en Lumen."}
        </li>
        <li>Elegí el archivo y revisalo: no se guarda nada hasta que confirmes.</li>
      </ol>
      )}

      <form className="inline-form" onSubmit={check}>
        <Field label={bps ? "Planilla del Cronograma (.xlsx)" : "Archivo CSV"}
               hint={`Hasta ${MAX_MB} MB y 2000 pacientes.`}>
          {(id, hint) => (
            <input id={id} ref={input} type="file" aria-describedby={hint}
                   accept={bps ? ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                               : ".csv,text/csv"}
                   onChange={(e) => choose(e.target.files?.[0] ?? null)} />
          )}
        </Field>
        <button type="submit" className="btn btn-primary" disabled={busy || !file}>
          {busy && !preview ? "Revisando…" : "Revisar archivo"}
        </button>
        <button type="button" className="btn" onClick={() => onClose(done !== null && done.created > 0)}>
          {done ? "Listo" : "Cancelar"}
        </button>
      </form>
      <ErrorBox message={error} />

      {done && (
        <SuccessBox message={
          `Se importaron ${done.created} ${done.created === 1 ? "paciente" : "pacientes"}.` +
          (done.skipped > 0 ? ` ${done.skipped} ya estaban en Lumen.` : "") +
          (done.invalid > 0 ? ` ${done.invalid} filas con errores no se cargaron.` : "")
        } />
      )}

      {preview && (
        <div className="import-preview">
          <p>
            <strong>{preview.total}</strong> filas: <Badge tone="ok">{preview.valid} correctas</Badge>{" "}
            {preview.skipped > 0 && <Badge tone="neutral">{preview.skipped} ya en Lumen</Badge>}{" "}
            {preview.invalid > 0 && <Badge tone="danger">{preview.invalid} con errores</Badge>}
          </p>
          {preview.ignored_columns.length > 0 && (
            <p className="muted small">
              Columnas que no se usan y se ignorarán: {preview.ignored_columns.join(", ")}.
            </p>
          )}
          {preview.invalid > 0 && (
            <p className="small">
              Las filas con errores no se cargan. Para corregirlas sin tocar las demás:{" "}
              <button type="button" className="btn btn-small" onClick={downloadErrors} disabled={busy}>
                Descargar filas con errores (CSV)
              </button>
              {" "}— trae una columna <strong>errores</strong> con lo que hay que arreglar. Corregilas en
              Excel, borrá esa columna si querés, e importá ese archivo después
              {bps ? <> con <strong>Importar desde CSV</strong> (guardalo como CSV UTF-8).</> : "."}
            </p>
          )}
          {preview.invalid > 0 && (
            <label className="checkbox">
              <input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} />
              Ver solo las filas con errores
            </label>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Línea</th><th scope="col">Paciente</th><th scope="col">Documento</th>
                  <th scope="col">Afiliación</th><th scope="col">Sucursal</th>
                  {!bps && <><th scope="col">Nacimiento</th><th scope="col">Responsable</th></>}
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.line} className={r.status === "error" ? "row-error" : undefined}>
                    <td>{r.line}</td>
                    <td>{r.full_name || <span className="muted">(sin nombre)</span>}</td>
                    <td>{r.document_number ?? "—"}</td>
                    <td>{r.affiliation ? AFFILIATION_LABELS[r.affiliation] : "—"}</td>
                    <td>{r.branch_name ?? "—"}</td>
                    {!bps && <>
                      <td>{r.birth_date ? fmtDate(r.birth_date) : "—"}</td>
                      <td>{r.responsible_name ?? <span className="muted">Sin asignar</span>}</td>
                    </>}
                    <td>
                      {r.status === "error" ? (
                        <ul className="row-errors">{r.errors.map((e) => <li key={e}>{e}</li>)}</ul>
                      ) : r.status === "skipped" ? (
                        <span title={r.note ?? undefined}><Badge tone="neutral">Ya está en Lumen</Badge></span>
                      ) : <Badge tone="ok">Correcta</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="form-actions">
            {preview.valid === 0 && preview.skipped > 0 && preview.invalid === 0 && (
              <span className="muted small">Todos los pacientes de la planilla ya están en Lumen.</span>
            )}
            {preview.invalid > 0 && preview.valid > 0 && (
              <span className="muted small">Las filas con errores no se cargarán. Podés corregirlas
                en Excel y volver a importar solo esas.</span>
            )}
            <button type="button" className="btn btn-primary" onClick={confirm}
                    disabled={busy || preview.valid === 0}>
              {busy ? "Importando…" : `Importar ${preview.valid} ${preview.valid === 1 ? "paciente" : "pacientes"}`}
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
