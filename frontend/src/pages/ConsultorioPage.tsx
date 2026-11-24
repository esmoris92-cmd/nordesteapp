// "Mi consultorio": lo que en una clínica hace Administración (nombre, contacto y logo),
// para el profesional de un espacio independiente. Sus propios datos van en "Mi cuenta".
import { ClinicCard, LogoCard } from "./UsersPage";

export function ConsultorioPage() {
  return (
    <>
      <div className="page-title">
        <h1>Mi consultorio</h1>
      </div>
      <p className="muted">
        El nombre y el logo del consultorio salen en el encabezado de Lumen y en lo que imprimís (informes y
        fichas). Tus datos personales y tu título se cargan en <a href="#/cuenta">Mi cuenta</a>.
      </p>
      <ClinicCard />
      <LogoCard />
    </>
  );
}
