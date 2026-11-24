import { useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, Field, SuccessBox, Logo, WarnBox } from "../components";
import { useAction } from "../hooks";
import type { SessionInfo } from "../types";

interface Props {
  notice: { text: string; tone: "ok" | "warn" } | null;
  onLogin: (session: SessionInfo) => void;
}

export function LoginPage({ notice, onLogin }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const session = await api.post<SessionInfo>("/auth/login", { email, password });
      setPassword("");
      onLogin(session);
    });
  }

  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit} noValidate={false}>
        <h1>
          <Logo /> Nordeste
        </h1>
        <p className="muted">Gestión clínica para centros de salud.</p>
        {notice?.tone === "ok" ? <SuccessBox message={notice.text} /> : <WarnBox message={notice?.text} />}
        <ErrorBox message={error} />
        <Field label="Correo electrónico" required>
          {(id) => (
            <input
              id={id}
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          )}
        </Field>
        <Field label="Contraseña" required>
          {(id) => (
            <input
              id={id}
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
          {busy ? "Ingresando…" : "Ingresar"}
        </button>
        <p className="muted small">
          Las cuentas de demostración (ficticias) están en el archivo README del proyecto.
        </p>
      </form>
    </main>
  );
}
