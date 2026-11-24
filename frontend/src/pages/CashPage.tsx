// Caja diaria de la sucursal: abrir con el efectivo inicial, cargar entradas y salidas,
// cerrar contando el efectivo, y ver el balance semanal, mensual o anual.
// Recepción trabaja con la caja de su sucursal; Administración elige la sucursal (y en el
// balance puede ver todas juntas) y es la única que puede reabrir una caja cerrada.
import { useId, useState, type FormEvent } from "react";
import { api } from "../api";
import { askConfirm } from "../confirm";
import { Badge, Card, Dialog, Empty, ErrorBox, Field, Loading, WarnBox } from "../components";
import { useAction, useAsync } from "../hooks";
import { fmtDate, fmtTime, isoDate } from "../labels";
import { useSession } from "../session";
import { notify } from "../toast";
import type { CashBalance, CashRegister, CashToday } from "../types";

const money = new Intl.NumberFormat("es-UY", { style: "currency", currency: "UYU", minimumFractionDigits: 2 });

export function fmtMoney(n: number): string {
  return money.format(n);
}

/** "1.500,50" o "1500.5" → número (o null si no es válido). */
function parseAmount(text: string): number | null {
  let t = text.trim().replace(/\s|\$/g, "");
  if (!t) return null;
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
  const n = Number(t);
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : null;
}

function DifferenceText({ value }: { value: number }) {
  if (Math.abs(value) < 0.005) return <Badge tone="ok">Sin diferencia</Badge>;
  return value > 0
    ? <Badge tone="info">Sobrante {fmtMoney(value)}</Badge>
    : <Badge tone="danger">Faltante {fmtMoney(-value)}</Badge>;
}

export function CashPage() {
  const { user, branch } = useSession();
  const [tab, setTab] = useState<"day" | "balance">("day");
  // Administración elige la sucursal; Recepción siempre usa la suya.
  const [branchId, setBranchId] = useState(branch.id);

  return (
    <>
      <div className="page-title"><h1>Caja</h1></div>
      <div className="tabs" role="tablist" aria-label="Caja">
        <button type="button" role="tab" aria-selected={tab === "day"} className={`tab${tab === "day" ? " active" : ""}`}
                onClick={() => setTab("day")}>Caja del día</button>
        <button type="button" role="tab" aria-selected={tab === "balance"}
                className={`tab${tab === "balance" ? " active" : ""}`} onClick={() => setTab("balance")}>Balance</button>
      </div>
      {tab === "day"
        ? <DayTab branchId={user.role === "admin" ? branchId : branch.id} onBranch={setBranchId} />
        : <BalanceTab />}
    </>
  );
}

/** Selector de sucursal para Administración (solo sucursales sueltas, o también "todas"). */
function BranchSelect({ value, onChange, allowAll }: { value: string; onChange: (v: string) => void; allowAll?: boolean }) {
  const { user, branch, branches } = useSession();
  if (user.role !== "admin") return null;
  return (
    <Field label="Sucursal">
      {(id) => (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
          {branches.map((b) => <option key={b.id} value={b.id}>{b.name}{b.id === branch.id ? " (actual)" : ""}</option>)}
          {allowAll && <option value="all">Todas las sucursales</option>}
        </select>
      )}
    </Field>
  );
}

// ---------- Caja del día ----------

function DayTab({ branchId, onBranch }: { branchId: string; onBranch: (id: string) => void }) {
  const { user } = useSession();
  const today = useAsync(() => api.get<CashToday>("/cash/today", { branch: branchId }), [branchId]);
  // Caja de un día anterior que quedó abierta y se eligió para cerrarla.
  const [pendingId, setPendingId] = useState<string | null>(null);
  const data = today.data;

  return (
    <>
      {user.role === "admin" && (
        <div className="toolbar cash-toolbar">
          <BranchSelect value={branchId} onChange={(v) => { setPendingId(null); onBranch(v); }} />
        </div>
      )}
      {today.loading && !data && <Loading />}
      <ErrorBox message={today.error} />
      {data && pendingId && (
        <PendingRegister id={pendingId} onBack={() => { setPendingId(null); today.reload(); }} />
      )}
      {data && !pendingId && (
        <>
          {data.pending.length > 0 && (
            <div className="alert alert-warn cash-pending" role="status">
              <strong>Quedó abierta la caja de {data.pending.map((p) => fmtDate(p.business_date)).join(", ")}.</strong>{" "}
              Hay que cerrarla antes de abrir la de hoy.
              <div className="cash-pending-actions">
                {data.pending.map((p) => (
                  <button key={p.id} type="button" className="btn btn-small" onClick={() => setPendingId(p.id)}>
                    Ir a la caja del {fmtDate(p.business_date)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {data.current
            ? <RegisterView register={data.current} title={`Caja de hoy, ${fmtDate(data.today)} · ${data.branch_name}`}
                            onChange={today.reload} />
            : <OpenForm today={data} disabled={data.pending.length > 0} onOpened={today.reload} />}
        </>
      )}
    </>
  );
}

function PendingRegister({ id, onBack }: { id: string; onBack: () => void }) {
  const reg = useAsync(() => api.get<CashRegister>(`/cash/registers/${id}`), [id]);
  return (
    <>
      <p><button type="button" className="link-button" onClick={onBack}>← Volver a la caja de hoy</button></p>
      {reg.loading && !reg.data && <Loading />}
      <ErrorBox message={reg.error} />
      {reg.data && (
        <RegisterView register={reg.data} title={`Caja del ${fmtDate(reg.data.business_date)} · ${reg.data.branch_name}`}
                      onChange={(r) => { if (r?.status === "closed") onBack(); else reg.reload(); }} />
      )}
    </>
  );
}

function OpenForm({ today, disabled, onOpened }: { today: CashToday; disabled: boolean; onOpened: () => void }) {
  const [amount, setAmount] = useState(today.suggested_opening != null ? String(today.suggested_opening).replace(".", ",") : "");
  const action = useAction();
  const parsed = parseAmount(amount);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post("/cash/registers", { opening_amount: amount, branch_id: today.branch_id });
    });
    if (ok) {
      notify("Caja abierta.");
      onOpened();
    }
  }

  return (
    <Card title={`Abrir la caja de hoy, ${fmtDate(today.today)} · ${today.branch_name}`}>
      <p className="muted small">
        Contá el efectivo que hay en la caja al empezar el día e ingresá el total.
        {today.suggested_opening != null && ` Al cerrar la última caja se contaron ${fmtMoney(today.suggested_opening)}.`}
      </p>
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={action.error} />
        <Field label="Efectivo al abrir" required hint={parsed != null ? fmtMoney(parsed) : "Por ejemplo 2000 o 2000,50"}>
          {(id, hint) => (
            <input id={id} aria-describedby={hint} inputMode="decimal" autoComplete="off" required value={amount}
                   onChange={(e) => setAmount(e.target.value)} disabled={disabled} />
          )}
        </Field>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={disabled || action.busy || parsed == null || parsed < 0}>
            {action.busy ? "Abriendo…" : "Abrir caja"}
          </button>
        </div>
      </form>
    </Card>
  );
}

function CashTiles({ r }: { r: CashRegister }) {
  return (
    <div className="stats cash-tiles">
      <section className="stat card"><div>
        <h3 className="stat-label">Al abrir</h3><p className="stat-value">{fmtMoney(r.opening_amount)}</p>
        <p className="stat-hint">{r.opened_by_name} · {fmtTime(r.opened_at)}</p>
      </div></section>
      <section className="stat card"><div>
        <h3 className="stat-label">Entradas</h3><p className="stat-value cash-in">+ {fmtMoney(r.income)}</p>
      </div></section>
      <section className="stat card"><div>
        <h3 className="stat-label">Salidas</h3><p className="stat-value cash-out">− {fmtMoney(r.expense)}</p>
      </div></section>
      <section className="stat card"><div>
        <h3 className="stat-label">{r.status === "open" ? "Debería haber" : "Esperado al cerrar"}</h3>
        <p className="stat-value">{fmtMoney(r.expected_amount)}</p>
        <p className="stat-hint">al abrir + entradas − salidas</p>
      </div></section>
    </div>
  );
}

/** Caja con sus movimientos. Abierta: cargar, anular y cerrar. Cerrada: el resumen del cierre. */
function RegisterView({ register, title, onChange, readOnly }: {
  register: CashRegister; title: string; onChange: (r?: CashRegister) => void; readOnly?: boolean;
}) {
  const { user } = useSession();
  const r = register;
  const action = useAction();
  const open = r.status === "open";

  async function reopen() {
    if (!await askConfirm(`¿Reabrir la caja del ${fmtDate(r.business_date)} (${r.branch_name})? Se podrán corregir `
      + "sus movimientos y habrá que volver a cerrarla. Queda registrado en la auditoría.",
    { confirmLabel: "Reabrir caja" })) return;
    let updated: CashRegister | undefined;
    const ok = await action.run(async () => { updated = await api.post<CashRegister>(`/cash/registers/${r.id}/reopen`); });
    if (ok) {
      notify("Caja reabierta.");
      onChange(updated);
    }
  }

  return (
    <>
      <Card title={title} actions={open ? <Badge tone="ok">Abierta</Badge> : <Badge>Cerrada</Badge>}>
        <ErrorBox message={action.error} />
        <CashTiles r={r} />
        {!open && (
          <dl className="details cash-close-summary">
            <dt>Contado al cerrar</dt><dd><strong>{fmtMoney(r.counted_amount ?? 0)}</strong></dd>
            <dt>Diferencia</dt><dd><DifferenceText value={r.difference ?? 0} /></dd>
            {r.closing_note && <><dt>Motivo</dt><dd>{r.closing_note}</dd></>}
            <dt>Cerró</dt><dd>{r.closed_by_name} · {r.closed_at ? fmtDate(r.closed_at.slice(0, 10)) : ""} {r.closed_at ? fmtTime(r.closed_at) : ""}</dd>
            {r.reopen_count > 0 && <><dt>Reaperturas</dt><dd>{r.reopen_count}</dd></>}
          </dl>
        )}
        {!open && user.role === "admin" && (
          <div className="form-actions">
            <button type="button" className="btn" disabled={action.busy} onClick={reopen}>Reabrir caja</button>
          </div>
        )}
      </Card>
      {open && !readOnly && <MovementForm register={r} onSaved={onChange} />}
      <Card title="Movimientos">
        <MovementsTable register={r} canVoid={open && !readOnly} onChange={onChange} />
      </Card>
      {open && !readOnly && <CloseForm register={r} onClosed={onChange} />}
    </>
  );
}

function MovementForm({ register, onSaved }: { register: CashRegister; onSaved: (r: CashRegister) => void }) {
  const [kind, setKind] = useState<"income" | "expense">("income");
  const [amount, setAmount] = useState("");
  const [concept, setConcept] = useState("");
  const [sent, setSent] = useState(0);
  const action = useAction();
  const parsed = parseAmount(amount);
  const groupId = useId();

  async function submit(event: FormEvent) {
    event.preventDefault();
    let updated: CashRegister | undefined;
    const ok = await action.run(async () => {
      updated = await api.post<CashRegister>(`/cash/registers/${register.id}/movements`, { kind, amount, concept });
    });
    if (ok && updated) {
      notify(kind === "income" ? "Entrada registrada." : "Salida registrada.");
      setAmount("");
      setConcept("");
      setSent((n) => n + 1);
      onSaved(updated);
    }
  }

  return (
    <Card title="Nueva entrada o salida">
      <form key={sent} className="grid-form" onSubmit={submit}>
        <ErrorBox message={action.error} />
        <fieldset className="span-all cash-kind" aria-labelledby={groupId}>
          <legend id={groupId}>Tipo</legend>
          <button type="button" className="btn" aria-pressed={kind === "income"} onClick={() => setKind("income")}>
            + Entrada
          </button>
          <button type="button" className="btn" aria-pressed={kind === "expense"} onClick={() => setKind("expense")}>
            − Salida
          </button>
        </fieldset>
        <Field label="Monto" required hint={parsed != null && parsed > 0 ? fmtMoney(parsed) : "Por ejemplo 1500 o 1500,50"}>
          {(id, hint) => (
            <input id={id} aria-describedby={hint} inputMode="decimal" autoComplete="off" required value={amount}
                   onChange={(e) => setAmount(e.target.value)} />
          )}
        </Field>
        <Field label="Concepto" required hint={kind === "income" ? "Por ejemplo: sesión particular, venta de material" : "Por ejemplo: artículos de limpieza, taxi"}>
          {(id, hint) => (
            <input id={id} aria-describedby={hint} maxLength={200} required value={concept}
                   onChange={(e) => setConcept(e.target.value)} />
          )}
        </Field>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary"
                  disabled={action.busy || parsed == null || parsed <= 0 || !concept.trim()}>
            {action.busy ? "Guardando…" : kind === "income" ? "Registrar entrada" : "Registrar salida"}
          </button>
        </div>
      </form>
    </Card>
  );
}

function MovementsTable({ register, canVoid, onChange }: {
  register: CashRegister; canVoid: boolean; onChange: (r: CashRegister) => void;
}) {
  const [voiding, setVoiding] = useState<string | null>(null);
  const movements = register.movements ?? [];
  if (movements.length === 0) return <Empty>Todavía no hay entradas ni salidas.</Empty>;
  const target = movements.find((m) => m.id === voiding);
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Hora</th><th scope="col">Concepto</th><th scope="col" className="num">Monto</th>
              <th scope="col" className="cash-who">Cargó</th>{canVoid && <th scope="col"><span className="sr-only">Acciones</span></th>}
            </tr>
          </thead>
          <tbody>
            {movements.map((m) => (
              <tr key={m.id} className={m.voided_at ? "row-muted" : undefined}>
                <td>{fmtTime(m.created_at)}</td>
                <td>
                  <span className={m.voided_at ? "cash-voided" : undefined}>{m.concept}</span>
                  <div className="small muted cash-who-inline">{m.created_by_name}</div>
                  {m.voided_at && (
                    <div className="small">Anulado por {m.voided_by_name}: {m.void_reason}</div>
                  )}
                </td>
                <td className={`num ${m.voided_at ? "cash-voided" : m.kind === "income" ? "cash-in" : "cash-out"}`}>
                  {m.kind === "income" ? "+ " : "− "}{fmtMoney(m.amount)}
                </td>
                <td className="cash-who">{m.created_by_name}</td>
                {canVoid && (
                  <td className="row-actions">
                    {!m.voided_at && (
                      <button type="button" className="btn btn-small" onClick={() => setVoiding(m.id)}>Anular</button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {target && (
        <VoidDialog register={register} movement={target} onClose={() => setVoiding(null)}
                    onDone={(r) => { setVoiding(null); onChange(r); }} />
      )}
    </>
  );
}

function VoidDialog({ register, movement, onClose, onDone }: {
  register: CashRegister; movement: NonNullable<CashRegister["movements"]>[number];
  onClose: () => void; onDone: (r: CashRegister) => void;
}) {
  const [reason, setReason] = useState("");
  const action = useAction();
  const titleId = useId();

  async function submit(event: FormEvent) {
    event.preventDefault();
    let updated: CashRegister | undefined;
    const ok = await action.run(async () => {
      updated = await api.post<CashRegister>(`/cash/registers/${register.id}/movements/${movement.id}/void`, { reason });
    });
    if (ok && updated) {
      notify("Movimiento anulado.");
      onDone(updated);
    }
  }

  return (
    <Dialog onClose={onClose} labelledBy={titleId} closeOnBackdrop={false}>
      <h2 id={titleId}>Anular movimiento</h2>
      <p>
        {movement.kind === "income" ? "Entrada" : "Salida"} de <strong>{fmtMoney(movement.amount)}</strong> ·{" "}
        {movement.concept}
      </p>
      <p className="muted small">No se borra: queda a la vista, tachado, y deja de sumar en la caja.</p>
      <form className="inline-form" onSubmit={submit}>
        <ErrorBox message={action.error} />
        <Field label="Motivo" required hint="Por ejemplo: cargado dos veces, monto equivocado">
          {(id, hint) => (
            <input id={id} aria-describedby={hint} data-autofocus maxLength={200} required value={reason}
                   onChange={(e) => setReason(e.target.value)} />
          )}
        </Field>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button type="submit" className="btn btn-danger" disabled={action.busy || reason.trim().length < 3}>
            {action.busy ? "Anulando…" : "Anular movimiento"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function CloseForm({ register, onClosed }: { register: CashRegister; onClosed: (r: CashRegister) => void }) {
  const [counted, setCounted] = useState("");
  const [note, setNote] = useState("");
  const action = useAction();
  const parsed = parseAmount(counted);
  const diff = parsed != null ? Math.round((parsed - register.expected_amount) * 100) / 100 : null;
  const needsNote = diff != null && Math.abs(diff) >= 0.005;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (parsed == null) return;
    const text = needsNote
      ? `Contaste ${fmtMoney(parsed)} y debería haber ${fmtMoney(register.expected_amount)} `
        + `(${diff! > 0 ? "sobran" : "faltan"} ${fmtMoney(Math.abs(diff!))}). `
      : `Contaste ${fmtMoney(parsed)}, igual a lo esperado. `;
    if (!await askConfirm(`${text}Después de cerrar, la caja no se puede modificar (solo Administración puede reabrirla). ¿Cerrar la caja?`,
      { confirmLabel: "Cerrar caja" })) return;
    let updated: CashRegister | undefined;
    const ok = await action.run(async () => {
      updated = await api.post<CashRegister>(`/cash/registers/${register.id}/close`, { counted_amount: counted, note });
    });
    if (ok && updated) {
      notify("Caja cerrada.");
      onClosed(updated);
    }
  }

  return (
    <Card title="Cierre de caja">
      <p className="muted small">
        Al terminar el día, contá el efectivo e ingresá el total. Lumen lo compara con lo que debería haber
        ({fmtMoney(register.expected_amount)}).
      </p>
      <form className="grid-form" onSubmit={submit}>
        <ErrorBox message={action.error} />
        <Field label="Efectivo contado" required hint={parsed != null ? fmtMoney(parsed) : "Por ejemplo 3200 o 3200,50"}>
          {(id, hint) => (
            <input id={id} aria-describedby={hint} inputMode="decimal" autoComplete="off" required value={counted}
                   onChange={(e) => setCounted(e.target.value)} />
          )}
        </Field>
        <div className="field cash-diff" aria-live="polite">
          <span className="field-label">Diferencia</span>
          {diff == null ? <span className="muted">—</span> : <DifferenceText value={diff} />}
        </div>
        {needsNote && (
          <div className="span-all">
            <Field label="Motivo de la diferencia" required hint={`${note.length} de 300 caracteres.`}>
              {(id, hint) => (
                <textarea id={id} aria-describedby={hint} rows={2} maxLength={300} required value={note}
                          onChange={(e) => setNote(e.target.value)} />
              )}
            </Field>
          </div>
        )}
        <div className="form-actions">
          <button type="submit" className="btn btn-primary"
                  disabled={action.busy || parsed == null || parsed < 0 || (needsNote && !note.trim())}>
            {action.busy ? "Cerrando…" : "Cerrar caja"}
          </button>
        </div>
      </form>
    </Card>
  );
}

// ---------- Balance ----------

type Period = "week" | "month" | "year";
const PERIOD_LABELS: Record<Period, string> = { week: "Semana", month: "Mes", year: "Año" };
const MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
  "Octubre", "Noviembre", "Diciembre"];
const WEEKDAYS_SHORT = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

function shift(ref: string, period: Period, delta: number): string {
  const [y, m, d] = ref.split("-").map(Number);
  if (period === "week") return isoDate(new Date(y, m - 1, d + 7 * delta));
  if (period === "month") return isoDate(new Date(y, m - 1 + delta, 1));
  return isoDate(new Date(y + delta, 0, 1));
}

function periodTitle(b: CashBalance): string {
  if (b.period === "year") return `Año ${b.start.slice(0, 4)}`;
  if (b.period === "month") return `${MONTHS[Number(b.start.slice(5, 7)) - 1]} de ${b.start.slice(0, 4)}`;
  return `Semana del ${fmtDate(b.start)} al ${fmtDate(b.end)}`;
}

function rowLabel(key: string, period: Period): string {
  if (period === "year") return MONTHS[Number(key.slice(5, 7)) - 1];
  const [y, m, d] = key.split("-").map(Number);
  return `${WEEKDAYS_SHORT[new Date(y, m - 1, d).getDay()]} ${fmtDate(key)}`;
}

function StatusBadge({ registers, open }: { registers: number; open: number }) {
  if (registers === 1) return open ? <Badge tone="warn">Abierta</Badge> : <Badge tone="ok">Cerrada</Badge>;
  if (open === 0) return <Badge tone="ok">{registers} cajas cerradas</Badge>;
  return <Badge tone="warn">{registers} cajas · {open} {open === 1 ? "abierta" : "abiertas"}</Badge>;
}

function BalanceTab() {
  const { user, branch } = useSession();
  const [period, setPeriod] = useState<Period>("month");
  const [ref, setRef] = useState(() => isoDate(new Date()));
  const [scope, setScope] = useState(branch.id);
  const [detail, setDetail] = useState<string | null>(null);
  const balance = useAsync(
    () => api.get<CashBalance>("/cash/balance", { period, date: ref, branch: user.role === "admin" ? scope : undefined }),
    [period, ref, scope],
  );
  const b = balance.data;
  // En el mes se muestran solo los días con caja; en la semana y el año, todas las filas.
  const rows = b ? (b.period === "month" ? b.rows.filter((r) => r.registers > 0) : b.rows) : [];

  return (
    <>
      <Card>
        <div className="toolbar cash-toolbar">
          <fieldset className="cash-period">
            <legend>Período</legend>
            {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
              <button key={p} type="button" className="btn btn-small" aria-pressed={period === p} onClick={() => setPeriod(p)}>
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </fieldset>
          <div className="cash-nav">
            <button type="button" className="btn btn-small" onClick={() => setRef(shift(ref, period, -1))}>← Anterior</button>
            <button type="button" className="btn btn-small" onClick={() => setRef(isoDate(new Date()))}>Hoy</button>
            <button type="button" className="btn btn-small" onClick={() => setRef(shift(ref, period, 1))}>Siguiente →</button>
          </div>
          <BranchSelect value={scope} onChange={setScope} allowAll />
        </div>
        {balance.loading && !b && <Loading />}
        <ErrorBox message={balance.error} />
        {b && (
          <>
            <h2 className="cash-period-title">
              {periodTitle(b)} <span className="muted">· {b.scope === "clinic" ? "Todas las sucursales" : b.branch_name}</span>
            </h2>
            <div className="stats cash-tiles">
              <section className="stat card"><div>
                <h3 className="stat-label">Entradas</h3><p className="stat-value cash-in">{fmtMoney(b.totals.income)}</p>
              </div></section>
              <section className="stat card"><div>
                <h3 className="stat-label">Salidas</h3><p className="stat-value cash-out">{fmtMoney(b.totals.expense)}</p>
              </div></section>
              <section className="stat card"><div>
                <h3 className="stat-label">Resultado</h3><p className="stat-value">{fmtMoney(b.totals.net)}</p>
                <p className="stat-hint">entradas − salidas</p>
              </div></section>
              <section className="stat card"><div>
                <h3 className="stat-label">Diferencias de cierre</h3>
                <p className={`stat-value ${b.totals.difference < -0.004 ? "cash-out" : ""}`}>{fmtMoney(b.totals.difference)}</p>
                <p className="stat-hint">{b.totals.registers} {b.totals.registers === 1 ? "caja" : "cajas"}
                  {b.totals.open_registers > 0 && ` · ${b.totals.open_registers} sin cerrar`}</p>
              </div></section>
            </div>
            {b.totals.open_registers > 0 && (
              <WarnBox message="Hay cajas sin cerrar en este período: sus diferencias todavía no se conocen." />
            )}
            {b.totals.registers === 0 ? <Empty>No hay cajas en este período.</Empty> : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">{b.period === "year" ? "Mes" : "Día"}</th>
                      <th scope="col" className="num">Entradas</th><th scope="col" className="num">Salidas</th>
                      <th scope="col" className="num">Resultado</th><th scope="col" className="num">Diferencia</th>
                      <th scope="col">Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.key} className={r.registers === 0 ? "row-muted" : undefined}>
                        <td>{rowLabel(r.key, b.period)}</td>
                        {r.registers === 0 ? (
                          <td colSpan={5} className="muted">Sin caja</td>
                        ) : (
                          <>
                            <td className="num">{fmtMoney(r.income)}</td>
                            <td className="num">{fmtMoney(r.expense)}</td>
                            <td className="num">{fmtMoney(r.net)}</td>
                            <td className="num">{fmtMoney(r.difference)}</td>
                            <td>
                              <StatusBadge registers={r.registers} open={r.open_registers} />
                              {r.register_id && (
                                <> <button type="button" className="link-button" onClick={() => setDetail(r.register_id)}>Ver detalle</button></>
                              )}
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="grand-total">
                      <th scope="row">Total</th>
                      <td className="num">{fmtMoney(b.totals.income)}</td>
                      <td className="num">{fmtMoney(b.totals.expense)}</td>
                      <td className="num">{fmtMoney(b.totals.net)}</td>
                      <td className="num">{fmtMoney(b.totals.difference)}</td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </>
        )}
      </Card>
      {b && b.by_branch.length > 0 && (
        <Card title="Por sucursal">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Sucursal</th>
                  <th scope="col" className="num">Entradas</th><th scope="col" className="num">Salidas</th>
                  <th scope="col" className="num">Resultado</th><th scope="col" className="num">Diferencias</th>
                  <th scope="col" className="num">Cajas</th>
                </tr>
              </thead>
              <tbody>
                {b.by_branch.map((x) => (
                  <tr key={x.branch_id}>
                    <td>{x.branch_name}</td>
                    <td className="num">{fmtMoney(x.income)}</td>
                    <td className="num">{fmtMoney(x.expense)}</td>
                    <td className="num">{fmtMoney(x.net)}</td>
                    <td className="num">{fmtMoney(x.difference)}</td>
                    <td className="num">{x.registers}{x.open_registers > 0 && ` (${x.open_registers} sin cerrar)`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {detail && <DetailDialog id={detail} onClose={() => { setDetail(null); balance.reload(); }} />}
    </>
  );
}

/** Detalle de la caja de un día, desde el balance (solo para ver; Administración puede reabrirla). */
function DetailDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const reg = useAsync(() => api.get<CashRegister>(`/cash/registers/${id}`), [id]);
  const titleId = useId();
  return (
    <Dialog onClose={onClose} labelledBy={titleId} className="modal-wide">
      <div className="modal-head">
        <h2 id={titleId}>{reg.data ? `Caja del ${fmtDate(reg.data.business_date)} · ${reg.data.branch_name}` : "Caja"}</h2>
        <button type="button" className="btn btn-small" onClick={onClose}>Volver al balance</button>
      </div>
      {reg.loading && !reg.data && <Loading />}
      <ErrorBox message={reg.error} />
      {reg.data && (
        <>
          {reg.data.status === "open" && (
            <p className="muted small">Esta caja está abierta: se carga y se cierra desde "Caja del día".</p>
          )}
          <RegisterView register={reg.data} title="Resumen" readOnly onChange={() => reg.reload()} />
        </>
      )}
    </Dialog>
  );
}
