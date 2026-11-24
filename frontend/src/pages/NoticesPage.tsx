// Avisos a los profesionales: Recepción y Administración los dejan; cada profesional los ve en
// la barra amarilla de arriba hasta que toca "Entendido".
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { askConfirm } from "../confirm";
import { Badge, Card, Empty, ErrorBox, Field, Loading } from "../components";
import { useAction, useAsync } from "../hooks";
import { fmtDateTime } from "../labels";
import { useSession } from "../session";
import { notify } from "../toast";
import type { Notice } from "../types";

const MAX = 500;

export function NoticesPage() {
  const { user, branch } = useSession();
  const notices = useAsync(() => api.get<Notice[]>("/notices"), []);
  const recipients = useAsync(() => api.get<{ id: string; full_name: string }[]>("/notices/recipients"), []);
  const [to, setTo] = useState("");
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(0); // al enviar, el formulario vuelve a empezar (sin marcas rojas)
  const action = useAction();
  const allLabel = user.role === "admin"
    ? "Todos los profesionales de la clínica" : `Todos los profesionales de la sucursal ${branch.name}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post("/notices", { message, professional_id: to || null });
    });
    if (ok) {
      notify("Aviso enviado.");
      setMessage("");
      setTo("");
      setSent((n) => n + 1);
      notices.reload();
    }
  }

  async function withdraw(n: Notice) {
    if (!await askConfirm("El aviso dejará de mostrarse a quienes todavía no lo leyeron. ¿Retirarlo?",
      { confirmLabel: "Retirar aviso", danger: true })) return;
    const ok = await action.run(async () => { await api.post(`/notices/${n.id}/withdraw`, {}); });
    if (ok) {
      notify("Aviso retirado.");
      notices.reload();
    }
  }

  return (
    <>
      <div className="page-title"><h1>Avisos</h1></div>
      <Card title="Nuevo aviso">
        <p className="muted small">
          Aparece arriba de todo, en la barra amarilla, hasta que el profesional toca "Entendido".
          No escribas datos clínicos.
        </p>
        <form key={sent} className="grid-form" onSubmit={submit}>
          <ErrorBox message={action.error} />
          <div className="span-all">
            <Field label="Para" required>
              {(id) => (
                <select id={id} value={to} onChange={(e) => setTo(e.target.value)}>
                  <option value="">{allLabel}</option>
                  {recipients.data?.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
                </select>
              )}
            </Field>
          </div>
          <div className="span-all">
            <Field label="Mensaje" required hint={`${message.length} de ${MAX} caracteres.`}>
              {(id, hint) => (
                <textarea id={id} aria-describedby={hint} required maxLength={MAX} rows={3} value={message}
                          onChange={(e) => setMessage(e.target.value)} />
              )}
            </Field>
          </div>
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={action.busy || !message.trim()}>
              {action.busy ? "Enviando…" : "Enviar aviso"}
            </button>
          </div>
        </form>
      </Card>
      <Card title={user.role === "admin" ? "Avisos enviados" : `Avisos enviados desde ${branch.name}`}>
        {notices.loading && !notices.data && <Loading />}
        <ErrorBox message={notices.error} />
        {notices.data?.length === 0 && <Empty>Todavía no se dejaron avisos.</Empty>}
        {notices.data && notices.data.length > 0 && (
          <ul className="notice-list">
            {notices.data.map((n) => {
              const read = n.recipients.filter((r) => r.read_at).length;
              return (
                <li key={n.id} className={n.withdrawn_at ? "row-muted" : undefined}>
                  <div className="notice-head">
                    <span className="muted small">
                      {fmtDateTime(n.created_at)} · {n.author_name}
                      {user.role === "admin" && n.branch_name ? ` · ${n.branch_name}` : ""}
                      {" · "}Para: {n.to_all ? "todos" : n.recipients[0]?.full_name}
                    </span>
                    {n.withdrawn_at ? <Badge>Retirado</Badge>
                      : read === n.recipients.length ? <Badge tone="ok">Leído</Badge>
                        : n.recipients.length === 1 ? <Badge tone="warn">Sin leer</Badge>
                          : <Badge tone="warn">Leído por {read} de {n.recipients.length}</Badge>}
                  </div>
                  <p className="notice-message">{n.message}</p>
                  {n.recipients.length > 1 && (
                    <p className="muted small">
                      {n.recipients.map((r) => `${r.full_name}${r.read_at ? " ✓" : ""}`).join(" · ")}
                    </p>
                  )}
                  {!n.withdrawn_at && read < n.recipients.length && (
                    <button type="button" className="btn btn-small" disabled={action.busy} onClick={() => withdraw(n)}>
                      Retirar aviso
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </>
  );
}
