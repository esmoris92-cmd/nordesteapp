import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { askConfirm, confirmDiscard } from "../confirm";
import { hasDraft, useDraft } from "../drafts";
import { notify } from "../toast";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import { fmtDateTime, REPORT_STATUS_LABELS } from "../labels";
import { useSession } from "../session";
import type { Report, ReportPerson, ReportReadiness, ReportSummary } from "../types";
import { generateReport, REPORT_MAX_CHARS } from "./reportBuilder";

export function ReportsPanel({ patientId, readOnly = false, isResponsible = false }: {
  patientId: string; readOnly?: boolean; isResponsible?: boolean;
}) {
  const reports = useAsync(() => api.get<ReportSummary[]>(`/patients/${patientId}/reports`), [patientId]);
  const [openId, setOpenId] = useState<string | null>(null);
  // Si quedó un informe nuevo a medio escribir (por cambiar de pestaña), se reabre.
  const [creating, setCreating] = useState(
    () => hasDraft(`informe:${patientId}:nuevo:titulo`) || hasDraft(`informe:${patientId}:nuevo:contenido`));
  const generating = useAction();

  /** Junta Diagnóstico, Antecedentes, Encuadre y cada Abordaje en un borrador nuevo y lo abre. */
  async function generate() {
    let createdId: string | null = null;
    let problem: string | null = null;
    const ok = await generating.run(async () => {
      const built = await generateReport(patientId);
      if (!built) {
        problem = "Todavía no hay nada para el informe: completá Diagnóstico, Antecedentes, " +
                  "Encuadre o algún Abordaje en las pestañas del paciente.";
      } else if (built.content.length > REPORT_MAX_CHARS) {
        problem = `El informe quedaría de ${built.content.length.toLocaleString("es-UY")} caracteres ` +
                  `y el máximo es ${REPORT_MAX_CHARS.toLocaleString("es-UY")}. Acortá alguna sección.`;
      } else {
        createdId = (await api.post<Report>(`/patients/${patientId}/reports`, built)).id;
      }
    });
    if (problem) { generating.setError(problem); return; }
    if (ok && createdId) {
      notify("Se generó el borrador del informe. Revisalo y finalizalo cuando esté listo.");
      setCreating(false);
      reports.reload();
      setOpenId(createdId);
    }
  }

  return (
    <>
      <Card
        title="Informes"
        actions={!creating && !readOnly && (
          <>
            {isResponsible && (
              <button type="button" className="btn btn-primary" onClick={generate} disabled={generating.busy}
                      title="Arma un borrador con Diagnóstico, Antecedentes, Encuadre y el Abordaje de cada profesional">
                {generating.busy ? "Generando…" : "Generar informe"}
              </button>
            )}
            <button type="button" className="btn" onClick={() => { setCreating(true); setOpenId(null); }}>
              Nuevo informe en blanco
            </button>
          </>
        )}
      >
        <p className="muted small">
          {readOnly
            ? "Se muestran solo los informes finalizados, en modo lectura. Cada consulta queda registrada."
            : isResponsible
              ? <>«Generar informe» arma un borrador con lo cargado en Diagnóstico, Antecedentes, Encuadre y
                Abordaje (y los datos de la ficha). Para finalizarlo tienen que estar los abordajes de todos los
                profesionales del paciente. Al finalizarlo queda fijo.</>
              : <>El informe conjunto lo genera y finaliza el profesional responsable del paciente: vos escribí tu parte
                en la pestaña Abordaje (al guardarla, le llega un aviso). Acá podés hacer un informe propio en blanco.</>}
        </p>
        <ErrorBox message={generating.error} />
        {reports.loading && <Loading />}
        <ErrorBox message={reports.error} />
        {reports.data && reports.data.length === 0 && (
          <Empty>{readOnly ? "No hay informes finalizados para este paciente." : "No hay informes para este paciente."}</Empty>
        )}
        {reports.data && reports.data.length > 0 && (
          <ul className="list">
            {reports.data.map((r) => (
              <li key={r.id}>
                <button type="button" className="link" onClick={() => { setOpenId(r.id); setCreating(false); }}>
                  {r.title}
                </button>{" "}
                <Badge tone={r.status === "final" ? "ok" : "warn"}>{REPORT_STATUS_LABELS[r.status]}</Badge>
                <span className="muted small"> · {r.author_name} · {fmtDateTime(r.updated_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {creating && (
        <ReportEditor
          patientId={patientId}
          onClose={(id) => { setCreating(false); reports.reload(); if (id) setOpenId(id); }}
        />
      )}
      {openId && <ReportView key={openId} reportId={openId} onChanged={reports.reload}
                             onClose={() => setOpenId(null)} />}
    </>
  );
}

function ReportEditor({ patientId, report, onClose }: {
  patientId: string; report?: Report; onClose: (id?: string) => void;
}) {
  const base = report ? `informe:${report.id}` : `informe:${patientId}:nuevo`;
  const [title, setTitle, discardTitle] = useDraft(`${base}:titulo`, report?.title ?? "");
  const [content, setContent, discardContent] = useDraft(`${base}:contenido`, report?.content ?? "");
  const { busy, error, run } = useAction();
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => { boxRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, []);
  const discard = () => { discardTitle(); discardContent(); };
  const changed = title !== (report?.title ?? "") || content !== (report?.content ?? "");

  async function submit(event: FormEvent) {
    event.preventDefault();
    let id: string | undefined;
    const ok = await run(async () => {
      if (report) {
        await api.patch(`/reports/${report.id}`, { title, content });
        id = report.id;
      } else {
        const created = await api.post<Report>(`/patients/${patientId}/reports`, { title, content });
        id = created.id;
      }
    });
    if (ok) {
      notify("Borrador del informe guardado.");
      discard();
      onClose(id);
    }
  }

  return (
    <div ref={boxRef}>
    <Card title={report ? "Editar borrador" : "Nuevo informe"}>
      <form onSubmit={submit}>
        <ErrorBox message={error} />
        <Field label="Título" required>
          {(id) => (
            <input id={id} required minLength={3} maxLength={200} value={title}
                   onChange={(e) => setTitle(e.target.value)} />
          )}
        </Field>
        <Field label="Contenido" required hint="Durante las pruebas, solo datos ficticios.">
          {(id, hint) => (
            <textarea id={id} aria-describedby={hint} required rows={report ? 24 : 10} maxLength={60000}
                      value={content} onChange={(e) => setContent(e.target.value)} />
          )}
        </Field>
        <div className="form-actions">
          <button type="button" className="btn" onClick={async () => {
            if (changed && !await confirmDiscard(title + content)) return;
            discard();
            onClose(report?.id);
          }}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Guardando…" : "Guardar borrador"}
          </button>
        </div>
      </form>
    </Card>
    </div>
  );
}

function ReportView({ reportId, onChanged, onClose }: {
  reportId: string; onChanged: () => void; onClose: () => void;
}) {
  const { user } = useSession();
  const report = useAsync(() => api.get<Report>(`/reports/${reportId}`), [reportId]);
  // Si quedó una edición a medio escribir, se reabre el editor.
  const [editing, setEditing] = useState(
    () => hasDraft(`informe:${reportId}:titulo`) || hasDraft(`informe:${reportId}:contenido`));
  const action = useAction();
  const boxRef = useRef<HTMLDivElement>(null);
  // Al abrir un informe, la pantalla baja hasta él (antes quedaba debajo de la lista).
  useEffect(() => {
    if (report.data) boxRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [report.data?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const readiness = useAsync(
    () => (report.data?.generated && report.data.status === "draft"
      ? api.get<ReportReadiness>(`/reports/${reportId}/readiness`) : Promise.resolve(null)),
    [report.data?.updated_at, report.data?.status],
  );

  if (report.loading && !report.data) return <Loading />;
  if (!report.data) return <ErrorBox message={report.error} />;
  const r = report.data;
  const isAuthorDraft = r.author_id === user.id && r.status === "draft";
  const ready = readiness.data;
  // Informe generado: se puede finalizar solo si lo cierra el responsable, está al día y no falta nadie.
  const blocked = r.generated && (!ready || !ready.can_close || ready.stale || ready.missing.length > 0);

  if (editing) {
    return (
      <ReportEditor patientId={r.patient_id} report={r}
                    onClose={() => { setEditing(false); report.reload(); onChanged(); }} />
    );
  }

  /** Rearma el borrador con lo último de las pestañas (reemplaza el texto). */
  async function refresh() {
    if (!await askConfirm("Se va a rearmar el borrador con lo último de Diagnóstico, Antecedentes, Encuadre y " +
                          "los abordajes. Si cambiaste el texto a mano, esos cambios se pierden. ¿Continuar?",
                          { confirmLabel: "Actualizar borrador" })) return;
    const ok = await action.run(async () => {
      const built = await generateReport(r.patient_id);
      if (!built) return;
      await api.patch(`/reports/${reportId}`, built);
    });
    if (ok) {
      notify("Borrador actualizado con lo último.");
      report.reload();
      onChanged();
    }
  }

  async function setParticipation(person: ReportPerson, participates: boolean) {
    if (!participates && !await askConfirm(
      `¿Marcar a ${person.name} como que no participa en este informe? Se podrá finalizar sin su abordaje ` +
      "y queda registrado en la auditoría.", { confirmLabel: "No participa" })) return;
    const ok = await action.run(async () => {
      await api.post(`/reports/${reportId}/participation`, { user_id: person.user_id, participates });
    });
    if (ok) readiness.reload();
  }

  async function finalize() {
    if (!await askConfirm("Al finalizar, el informe ya no podrá modificarse. ¿Continuar?",
                          { confirmLabel: "Finalizar informe" })) return;
    const ok = await action.run(async () => {
      await api.post(`/reports/${reportId}/finalize`);
    });
    if (ok) {
      notify("Informe finalizado.");
      report.reload();
      onChanged();
    }
  }

  return (
    <div ref={boxRef}>
    <Card
      title={r.title}
      actions={(
        <>
          {isAuthorDraft && (
            <>
              <button type="button" className="btn" onClick={() => setEditing(true)}>Editar</button>
              <button type="button" className="btn btn-primary" onClick={finalize} disabled={action.busy || blocked}
                      title={blocked ? "Revisá lo que falta (abajo del título)" : undefined}>
                Finalizar
              </button>
            </>
          )}
          {r.status === "final" && (
            <a className="btn" href={`#/imprimir/informe/${r.id}`} target="_blank" rel="noopener">
              Imprimir / PDF
            </a>
          )}
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cerrar</button>
        </>
      )}
    >
      <ErrorBox message={action.error} />
      {r.generated && r.status === "draft" && ready && (
        <ReadinessBox ready={ready} canAct={isAuthorDraft && ready.can_close} busy={action.busy}
                      onRefresh={refresh} onParticipation={setParticipation} />
      )}
      <ErrorBox message={readiness.error} />
      <p className="muted small">
        <Badge tone={r.status === "final" ? "ok" : "warn"}>{REPORT_STATUS_LABELS[r.status]}</Badge>{" "}
        {r.author_name} · creado {fmtDateTime(r.created_at)}
        {r.finalized_at && <> · finalizado {fmtDateTime(r.finalized_at)}</>}
        {r.signers.length > 0 && (
          <><br />Firman: {r.signers.map((s) => s.specialty ? `${s.name} (${s.specialty})` : s.name).join(" · ")}</>
        )}
      </p>
      <div className="note-text">{r.content}</div>
    </Card>
    </div>
  );
}

const personText = (p: ReportPerson) => (p.specialty ? `${p.name} (${p.specialty})` : p.name);

/** Lo que falta para finalizar un informe generado, con las acciones del responsable. */
function ReadinessBox({ ready, canAct, busy, onRefresh, onParticipation }: {
  ready: ReportReadiness; canAct: boolean; busy: boolean;
  onRefresh: () => void; onParticipation: (p: ReportPerson, participates: boolean) => void;
}) {
  const ok = !ready.stale && ready.missing.length === 0;
  return (
    <div className={`alert ${ok ? "alert-info" : "alert-warn"} readiness`} role="status">
      {!ready.can_close && (
        <p>Este informe lo finaliza {ready.responsible_name ?? "el profesional responsable del paciente"}.</p>
      )}
      {ready.stale && (
        <p>
          Hubo cambios en las pestañas después de generar este borrador.{" "}
          {canAct && <button type="button" className="btn btn-small" disabled={busy} onClick={onRefresh}>
            Actualizar con lo último
          </button>}
        </p>
      )}
      {ready.missing.length > 0 && (
        <>
          <p>Para finalizar falta el abordaje de:</p>
          <ul className="readiness-list">
            {ready.missing.map((p) => (
              <li key={p.user_id}>
                {personText(p)}
                {canAct && <> <button type="button" className="link-button" disabled={busy}
                                      onClick={() => onParticipation(p, false)}>No participa</button></>}
              </li>
            ))}
          </ul>
        </>
      )}
      {ready.excluded.length > 0 && (
        <p className="small">
          No participan: {ready.excluded.map((p) => (
            <span key={p.user_id}>
              {personText(p)}
              {canAct && <> · <button type="button" className="link-button" disabled={busy}
                                      onClick={() => onParticipation(p, true)}>volver a incluir</button></>}{" "}
            </span>
          ))}
        </p>
      )}
      {ok && <p>Están todos los abordajes y el borrador está al día: {canAct ? "ya podés finalizarlo." : "listo para finalizar."}</p>}
    </div>
  );
}

