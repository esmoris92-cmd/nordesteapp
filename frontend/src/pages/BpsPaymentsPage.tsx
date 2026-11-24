// Pagos BPS: Administración o Recepción sube el PDF "Detalle de Item Facturable" que manda el BPS cada
// mes y Nordeste muestra solo lo que hay que revisar (pagos distintos al arancel AYEX,
// pacientes que no figuran, documentos que no son pacientes y repetidos). El PDF no se guarda.
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, uploadAndDownload, uploadFile } from "../api";
import { Badge, Card, ErrorBox, Field, Loading, SuccessBox, WarnBox } from "../components";
import { useAction, useAsync } from "../hooks";
import { isIndependent, useSession } from "../session";
import type { BpsCheck, BpsIssue, BpsIssueKind, ClinicDetail } from "../types";
import { fmtMoney } from "./CashPage";

const MAX_MB = 5;

const KIND_LABELS: Record<BpsIssueKind, string> = {
  underpaid: "Pago menor",
  overpaid: "Pago mayor",
  not_in_bps: "No figura en el PDF",
  not_patient: "No es paciente",
  not_ayex: "No es AYEX activo",
  duplicate: "Repetido",
};

const KIND_TONE: Record<BpsIssueKind, string> = {
  underpaid: "danger",
  overpaid: "info",
  not_in_bps: "warn",
  not_patient: "neutral",
  not_ayex: "neutral",
  duplicate: "warn",
};

const KIND_ORDER: BpsIssueKind[] = ["underpaid", "not_in_bps", "duplicate", "overpaid", "not_patient", "not_ayex"];

export function BpsPaymentsPage() {
  const clinic = useAsync(() => api.get<ClinicDetail>("/clinic"), []);
  const { user, clinic: session } = useSession();
  const independent = isIndependent(session);  // el arancel se carga en "Mi consultorio"
  const reception = user.role === "reception";  // Recepción usa Pagos BPS, pero el arancel lo carga Administración
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<BpsCheck | null>(null);
  const [filter, setFilter] = useState<BpsIssueKind | "all">("all");
  const { busy, error, setError, run } = useAction();
  const fee = clinic.data?.ayex_fee ?? null;

  function choose(f: File | null) {
    setFile(f);
    setResult(null);
    setFilter("all");
    setError(null);
  }

  async function check(event: FormEvent) {
    event.preventDefault();
    if (!file) { setError("Elegí el PDF que mandó el BPS."); return; }
    if (file.size > MAX_MB * 1024 * 1024) { setError(`El archivo supera el máximo de ${MAX_MB} MB.`); return; }
    await run(async () => {
      setResult(await uploadFile<BpsCheck>("/bps-payments/check", file, {}, { quiet: true }));
    });
  }

  async function download() {
    if (!file || !result) return;
    const month = result.months.length ? result.months[result.months.length - 1].replace("/", "-") : "mes";
    await run(async () => {
      await uploadAndDownload("/bps-payments/check/xlsx", file, `lumen-control-pagos-bps-${month}.xlsx`);
    });
  }

  return (
    <>
      <div className="page-title"><h1>Pagos BPS (AYEX)</h1></div>
      <Card title="Controlar el pago del mes">
        <ol className="steps small">
          <li>
            Elegí el PDF <strong>Detalle de Item Facturable</strong> que manda el BPS, tal como llega (no una foto
            ni un escaneo).
          </li>
          <li>
            Nordeste compara cada fila con el arancel AYEX de la clínica y con los pacientes AYEX activos de todas las
            sucursales, y muestra <strong>solo lo que hay que revisar</strong>.
          </li>
          <li>Descargá el Excel para reclamar al BPS. El PDF no se guarda en Nordeste.</li>
        </ol>

        {clinic.loading && !clinic.data && <Loading />}
        <ErrorBox message={clinic.error} />
        {clinic.data && (fee === null ? (
          <WarnBox message={independent
            ? "Falta el arancel AYEX (lo que paga el BPS por paciente). Cargalo en Mi consultorio → Pagos del BPS."
            : reception
              ? "Falta el arancel AYEX de la clínica (lo que paga el BPS por paciente). Pedile a Administración que lo cargue en Usuarios → Clínica → Pagos del BPS."
              : "Falta el arancel AYEX de la clínica (lo que paga el BPS por paciente). Cargalo en Usuarios → Clínica → Pagos del BPS."} />
        ) : (
          <p className="small">
            Arancel AYEX: <strong>{fmtMoney(fee)}</strong> por paciente y por mes{" "}
            <span className="muted">({independent
              ? <>se cambia en <a href="#/consultorio">Mi consultorio</a></>
              : reception ? "lo cambia Administración"
                : <>se cambia en <a href="#/usuarios">Usuarios → Clínica</a></>}).</span>
          </p>
        ))}

        <form className="inline-form" onSubmit={check}>
          <Field label="PDF del BPS" hint={`Hasta ${MAX_MB} MB.`}>
            {(id, hint) => (
              <input id={id} ref={input} type="file" aria-describedby={hint} accept=".pdf,application/pdf"
                     onChange={(e) => choose(e.target.files?.[0] ?? null)} />
            )}
          </Field>
          <button type="submit" className="btn btn-primary" disabled={busy || !file || fee === null}>
            {busy && !result ? "Revisando…" : "Revisar PDF"}
          </button>
          {result && (
            <button type="button" className="btn" onClick={download} disabled={busy}>
              Descargar Excel
            </button>
          )}
        </form>
        <ErrorBox message={error} />
      </Card>

      {result && <Result result={result} filter={filter} onFilter={setFilter} />}
    </>
  );
}

function Result({ result, filter, onFilter }: {
  result: BpsCheck; filter: BpsIssueKind | "all"; onFilter: (k: BpsIssueKind | "all") => void;
}) {
  const counts = new Map<BpsIssueKind, number>();
  for (const i of result.issues) counts.set(i.kind, (counts.get(i.kind) ?? 0) + 1);
  const shown = result.issues
    .filter((i) => filter === "all" || i.kind === filter)
    .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
  const months = result.months.join(", ");

  return (
    <Card title={`Resultado${months ? ` · mes de cargo ${months}` : ""}`}>
      <div className="stats cash-tiles">
        <Tile label="Filas del PDF" value={String(result.row_count)}
              hint={`${result.ok_count} ${result.ok_count === 1 ? "correcta" : "correctas"}`} />
        <Tile label="Faltante por pagos menores" value={fmtMoney(result.missing_amount)}
              hint={counts.get("underpaid") ? `${counts.get("underpaid")} con pago menor` : "Ningún pago menor"} />
        <Tile label="Suma de las filas" value={fmtMoney(result.rows_total)}
              hint={result.invoice_total === null ? "El PDF no trae el importe de la factura"
                : result.totals_match ? "Coincide con el importe de la factura"
                : `La factura dice ${fmtMoney(result.invoice_total)}`} />
        <Tile label="Para revisar" value={String(result.issues.length)}
              hint={result.issues.length === 0 ? "Todo en orden" : "Ver la lista abajo"} />
      </div>

      {result.totals_match === false && (
        <WarnBox message="La suma de las filas no coincide con el importe de la factura del encabezado. Puede faltar una página o una fila: revisá que el PDF esté completo." />
      )}
      {result.issues.length === 0 && (
        <SuccessBox message={`Todo en orden: los ${result.row_count} pagos son del arancel y figuran todos los pacientes AYEX activos.`} />
      )}

      {result.issues.length > 0 && (
        <>
          <div className="tabs" role="tablist" aria-label="Filtrar por situación">
            <FilterTab active={filter === "all"} onClick={() => onFilter("all")}>
              Todo ({result.issues.length})
            </FilterTab>
            {KIND_ORDER.filter((k) => counts.get(k)).map((k) => (
              <FilterTab key={k} active={filter === k} onClick={() => onFilter(k)}>
                {KIND_LABELS[k]} ({counts.get(k)})
              </FilterTab>
            ))}
          </div>
          <div className="table-wrap table-cards">
            <table>
              <thead>
                <tr>
                  <th scope="col">Situación</th><th scope="col">Paciente</th><th scope="col">Documento</th>
                  <th scope="col">Sucursal</th><th scope="col">Mes</th>
                  <th scope="col" className="num">Pagado</th><th scope="col" className="num">Esperado</th>
                  <th scope="col" className="num">Diferencia</th><th scope="col">Observación</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((i, n) => <IssueRow key={`${i.kind}-${i.document ?? i.patient_id}-${n}`} issue={i} />)}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}

function IssueRow({ issue: i }: { issue: BpsIssue }) {
  const money = (n: number | null) => (n === null ? "—" : fmtMoney(n));
  return (
    <tr className={i.kind === "underpaid" ? "row-error" : undefined}>
      <td data-label="Situación"><Badge tone={KIND_TONE[i.kind]}>{KIND_LABELS[i.kind]}</Badge></td>
      <td data-label="Paciente">{i.patient_id ? <a href={`#/pacientes/${i.patient_id}`}>{i.name}</a> : i.name || "—"}</td>
      <td data-label="Documento">{i.document ?? "—"}</td>
      <td data-label="Sucursal">{i.branch_name ?? "—"}</td>
      <td data-label="Mes">{i.month ?? "—"}</td>
      <td data-label="Pagado" className="num">{money(i.amount)}</td>
      <td data-label="Esperado" className="num">{money(i.expected)}</td>
      <td data-label="Diferencia" className="num">{i.difference === null ? "—" : fmtMoney(i.difference)}</td>
      <td data-label="Observación" className="small">{i.note ?? ""}</td>
    </tr>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <section className="stat card"><div>
      <h3 className="stat-label">{label}</h3>
      <p className="stat-value">{value}</p>
      <p className="stat-hint">{hint}</p>
    </div></section>
  );
}

function FilterTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" role="tab" aria-selected={active} className={`tab${active ? " active" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}
