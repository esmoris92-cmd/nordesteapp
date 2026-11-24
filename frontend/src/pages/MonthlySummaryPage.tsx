// Informe mensual: sesiones por profesional y tipo de afiliación (solo números).
import { useState } from "react";
import { api } from "../api";
import { Card, Empty, ErrorBox, Loading } from "../components";
import { useAsync } from "../hooks";
import { AFFILIATION_LABELS } from "../labels";
import type { AffiliationType } from "../types";
import { BranchScopeSelect } from "./BranchScope";

interface Totals { completed: number; no_show: number; cancelled: number; scheduled: number; patients_seen: number }
interface Row extends Totals {
  branch_id: string; branch_name: string; professional_id: string; professional_name: string; affiliation: AffiliationType;
}
interface BranchTotals extends Totals { branch_id: string; branch_name: string }
interface Summary {
  month: string; rows: Row[]; by_affiliation: Record<AffiliationType, Totals>; by_branch: BranchTotals[];
  total: Totals; only_own: boolean; scope: "own" | "branch" | "clinic"; branch_name: string | null;
}

const AFFILIATIONS: AffiliationType[] = ["private", "ayex", "military", "police"];

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthName(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const name = new Date(y, m - 1, 1).toLocaleDateString("es-UY", { month: "long", year: "numeric" });
  return name.charAt(0).toUpperCase() + name.slice(1);
}

const MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
  "Octubre", "Noviembre", "Diciembre"];
const YEARS_BACK = 5;

function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Elegir mes con dos listas (mes y año) y botones anterior / siguiente. No usa el campo
 * "month" del navegador porque Safari para Mac no lo muestra como selector. */
function MonthPicker({ value, onChange }: { value: string; onChange: (month: string) => void }) {
  const max = currentMonth();
  const [year, month] = value.split("-").map(Number);
  const maxYear = Number(max.slice(0, 4));
  const years = Array.from({ length: YEARS_BACK + 1 }, (_, i) => maxYear - i);
  const set = (y: number, m: number) => {
    const next = `${y}-${String(m).padStart(2, "0")}`;
    onChange(next > max ? max : next); // nunca un mes que todavía no empezó
  };
  const prev = shiftMonth(value, -1);
  const next = shiftMonth(value, 1);
  const firstYear = maxYear - YEARS_BACK;
  return (
    <fieldset className="month-picker">
      <legend>Mes</legend>
      <button type="button" className="btn btn-small" onClick={() => onChange(prev)}
              disabled={Number(prev.slice(0, 4)) < firstYear} aria-label="Mes anterior">← Anterior</button>
      <select aria-label="Mes" value={month} onChange={(e) => set(year, Number(e.target.value))}>
        {MONTHS.map((name, i) => (
          <option key={name} value={i + 1} disabled={`${year}-${String(i + 1).padStart(2, "0")}` > max}>{name}</option>
        ))}
      </select>
      <select aria-label="Año" value={year} onChange={(e) => set(Number(e.target.value), month)}>
        {years.map((y) => <option key={y} value={y}>{y}</option>)}
      </select>
      <button type="button" className="btn btn-small" onClick={() => onChange(next)}
              disabled={next > max} aria-label="Mes siguiente">Siguiente →</button>
    </fieldset>
  );
}

function Numbers({ t }: { t: Totals }) {
  return (
    <>
      <td className="num">{t.completed}</td>
      <td className="num">{t.no_show}</td>
      <td className="num">{t.cancelled}</td>
      <td className="num">{t.scheduled}</td>
      <td className="num">{t.patients_seen}</td>
    </>
  );
}

export function MonthlySummaryPage() {
  const [month, setMonth] = useState(currentMonth);
  const [branch, setBranch] = useState("");
  const summary = useAsync(() => api.get<Summary>("/monthly-summary", { month, ...(branch ? { branch } : {}) }),
                           [month, branch]);
  const data = summary.data;
  // Columna "Sucursal" y subtotales por sucursal cuando el informe abarca más de una.
  const multi = data ? data.scope !== "branch" : false;
  const cols = multi ? 3 : 2;
  const exportUrl = `/api/monthly-summary/export?month=${month}${branch ? `&branch=${encodeURIComponent(branch)}` : ""}`;

  return (
    <>
      <div className="page-title">
        <h1>Informe mensual</h1>
        <div className="title-actions">
          <a className="btn" href={exportUrl} download>Exportar a Excel</a>
        </div>
      </div>
      <Card>
        <div className="toolbar month-field">
          <MonthPicker value={month} onChange={setMonth} />
          <BranchScopeSelect value={branch} onChange={setBranch} />
        </div>
        <p className="muted small">
          Turnos de {monthName(month)} según su estado. Los reprogramados no se cuentan (cuenta el
          turno nuevo). La afiliación es la que tiene hoy cada paciente.
          {data?.only_own && " Ves solo tus propias sesiones, en todas tus sucursales."}
          {data?.scope === "branch" && ` Sucursal: ${data.branch_name} (donde fue cada turno).`}
          {data?.scope === "clinic" && " Todas las sucursales."}
        </p>
        {summary.loading && <Loading />}
        <ErrorBox message={summary.error} />
        {data && (
          <div className="stats summary-tiles">
            {AFFILIATIONS.map((a) => (
              <section key={a} className="stat card">
                <div>
                  <h2 className="stat-label">{AFFILIATION_LABELS[a]}</h2>
                  <p className="stat-value">{data.by_affiliation[a].completed}</p>
                  <p className="stat-hint">
                    sesiones realizadas · {data.by_affiliation[a].patients_seen} pacientes atendidos
                  </p>
                </div>
              </section>
            ))}
          </div>
        )}
        {data && data.rows.length === 0 && <Empty>No hay turnos en {monthName(month)}.</Empty>}
        {data && data.rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {multi && <th scope="col">Sucursal</th>}
                  <th scope="col">Profesional</th><th scope="col">Afiliación</th>
                  <th scope="col" className="num">Realizadas</th><th scope="col" className="num">Ausentes</th>
                  <th scope="col" className="num">Canceladas</th><th scope="col" className="num">Programadas</th>
                  <th scope="col" className="num">Pacientes atendidos</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={`${r.branch_id}-${r.professional_id}-${r.affiliation}`}>
                    {multi && <td>{r.branch_name}</td>}
                    <td>{r.professional_name}</td>
                    <td>{AFFILIATION_LABELS[r.affiliation]}</td>
                    <Numbers t={r} />
                  </tr>
                ))}
              </tbody>
              <tfoot>
                {data.by_branch.length > 1 && data.by_branch.map((b) => (
                  <tr key={b.branch_id} className="subtotal">
                    <th scope="row" colSpan={cols}>Total {b.branch_name}</th>
                    <Numbers t={b} />
                  </tr>
                ))}
                {AFFILIATIONS.map((a) => (
                  <tr key={a} className="subtotal">
                    <th scope="row" colSpan={cols}>Total {AFFILIATION_LABELS[a]}</th>
                    <Numbers t={data.by_affiliation[a]} />
                  </tr>
                ))}
                <tr className="grand-total">
                  <th scope="row" colSpan={cols}>Total del mes</th>
                  <Numbers t={data.total} />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
