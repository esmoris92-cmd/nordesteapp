// Buscador de pacientes (escribe nombre, apellido o documento). Pensado para clínicas con
// muchos pacientes: busca en el servidor en vez de cargar una lista con todos.
// Con teclado: flechas para moverse por los resultados, Enter para elegir y Escape para cerrar.
import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { api } from "../api";
import { AFFILIATION_LABELS } from "../labels";
import type { Patient } from "../types";

export function PatientPicker({ id, value, onChange, status = "active", branch = "attend", autoFocus = false }: {
  id: string; value: Patient | null; onChange: (p: Patient | null) => void;
  status?: string; // "" = todos los estados
  branch?: string; // "attend" = los que se atienden en la sucursal activa; "all" = todos los que puedo ver
  autoFocus?: boolean; // dentro de una ventana: el foco empieza en este campo
}) {
  const [text, setText] = useState("");
  const [results, setResults] = useState<Patient[]>([]);
  const [searching, setSearching] = useState(false);
  const [active, setActive] = useState(-1); // opción marcada con las flechas
  const [open, setOpen] = useState(true);
  const listId = useId();

  useEffect(() => {
    if (value || text.trim().length < 2) { setResults([]); return; }
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(() => {
      api.getPage<Patient>("/patients", { q: text.trim(), status, branch, page_size: "15" })
        .then((r) => { if (!cancelled) { setResults(r.items); setActive(r.items.length ? 0 : -1); } })
        .catch(() => { if (!cancelled) setResults([]); })
        .finally(() => { if (!cancelled) setSearching(false); });
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [text, value, status, branch]);

  if (value) {
    return (
      <div className="picker-selected">
        <strong>{value.last_name}, {value.first_name}</strong>
        <span className="muted small">
          {value.document_number ?? "sin documento"} · {AFFILIATION_LABELS[value.affiliation]}
          {value.branch_name ? ` · ${value.branch_name}` : ""}
        </span>
        <button type="button" className="link-button" onClick={() => { onChange(null); setText(""); }}>Cambiar</button>
      </div>
    );
  }

  const showList = open && text.trim().length >= 2;

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" && results.length) {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % results.length);
    } else if (event.key === "ArrowUp" && results.length) {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1));
    } else if (event.key === "Enter" && showList && active >= 0 && results[active]) {
      event.preventDefault(); // elegir, no enviar el formulario
      onChange(results[active]);
    } else if (event.key === "Escape" && showList) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    }
  }

  const optionId = (i: number) => `${listId}-op-${i}`;

  return (
    <div className="picker">
      <input id={id} type="search" autoComplete="off" placeholder="Escribí nombre, apellido o documento"
             role="combobox" aria-autocomplete="list" aria-expanded={showList} aria-controls={listId}
             aria-activedescendant={showList && active >= 0 && results[active] ? optionId(active) : undefined}
             data-autofocus={autoFocus || undefined} value={text} onKeyDown={onKeyDown}
             onChange={(e) => { setText(e.target.value); setOpen(true); }} />
      {showList && (
        <ul className="picker-results" role="listbox" id={listId} aria-label="Pacientes encontrados">
          {searching && <li className="muted small picker-note" role="presentation">Buscando…</li>}
          {!searching && results.length === 0 && (
            <li className="muted small picker-note" role="presentation">Sin resultados.</li>
          )}
          {results.map((p, i) => (
            <li key={p.id} id={optionId(i)} role="option" aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()} // que el campo no pierda el foco
                onClick={() => onChange(p)}>
              {p.last_name}, {p.first_name}
              <span className="muted small"> · {p.document_number ?? "sin documento"} · {AFFILIATION_LABELS[p.affiliation]}
                {p.branch_name ? ` · ${p.branch_name}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
