// Cuánto ocupa cada clínica (pestaña "Espacio" de /sistema).
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Loading } from "../components";
import { useAsync } from "../hooks";
import { exactBytes, fmtBytes, Tile, type ClinicStorage } from "./ClinicPage";

interface StorageOverview {
  database_bytes: number; clinics_bytes: number; shared_bytes: number; files_bytes: number;
  clinics: ClinicStorage[];
}

export function StoragePage() {
  const data = useAsync(() => api.get<StorageOverview>("/owner/storage"), []);
  const s = data.data;
  const biggest = s ? Math.max(0, ...s.clinics.map((c) => c.database_bytes + c.files_bytes)) : 0;
  return (
    <>
      <div className="page-title">
        <h1>Espacio</h1>
        <button type="button" className="btn" onClick={data.reload} disabled={data.loading}>
          {data.loading ? "Midiendo…" : "Volver a medir"}
        </button>
      </div>
      <p className="muted small">
        Todas las clínicas comparten la misma base de datos, así que lo de cada una es una estimación
        (el tamaño real de cada tabla se reparte según cuánto ocupan sus filas). Los archivos adjuntos
        (PDF e imágenes) están aparte, en el disco del servidor.
      </p>
      <ErrorBox message={data.error} />
      {data.loading && !s ? <Loading /> : s && (
        <>
          <div className="stats owner-stats">
            <Tile title="Base de datos" value={fmtBytes(s.database_bytes)} hint={exactBytes(s.database_bytes)} />
            <Tile title="De las clínicas" value={fmtBytes(s.clinics_bytes)} hint={<>{exactBytes(s.clinics_bytes)} · estimado</>} />
            <Tile title="Compartido" value={fmtBytes(s.shared_bytes)}
                  hint="lo que no es de ninguna clínica: tu cuenta, tu auditoría y el propio PostgreSQL" />
            <Tile title="Archivos adjuntos" value={fmtBytes(s.files_bytes)} hint={exactBytes(s.files_bytes)} />
          </div>
          <Card title="Por clínica">
            {s.clinics.length === 0 ? <Empty>Todavía no hay clínicas.</Empty> : (
              <div className="table-wrap">
                <table className="storage-table">
                  <thead>
                    <tr>
                      <th scope="col">Clínica</th><th scope="col">En la base</th><th scope="col">Archivos</th>
                      <th scope="col">Total</th><th scope="col">Bytes</th>
                      <th scope="col"><span className="sr-only">Proporción</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.clinics.map((c) => {
                      const total = c.database_bytes + c.files_bytes;
                      return (
                        <tr key={c.clinic_id}>
                          <td>
                            <a href={`#/clinicas/${c.clinic_id}/espacio`}><strong>{c.name}</strong></a>
                            {c.suspended && <> <Badge tone="danger">Suspendida</Badge></>}
                          </td>
                          <td>{fmtBytes(c.database_bytes)}</td>
                          <td>{fmtBytes(c.files_bytes)} <span className="muted small">({c.files_count})</span></td>
                          <td><strong>{fmtBytes(total)}</strong></td>
                          <td className="muted small">{exactBytes(total)}</td>
                          <td className="bar-cell" aria-hidden="true">
                            <span className="bar-track">
                              <span className="bar-fill" style={{ width: `${biggest ? (total / biggest) * 100 : 0}%` }} />
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
