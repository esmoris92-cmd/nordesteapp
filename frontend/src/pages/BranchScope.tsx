// Selector de sucursal para Inicio e Informe mensual (solo administración).
import { Field } from "../components";
import { useSession } from "../session";

/** "" = la sucursal activa; "all" = todas; o el id de otra sucursal. */
export function BranchScopeSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { user, branch, branches } = useSession();
  if (user.role !== "admin") return null;
  return (
    <Field label="Sucursal">
      {(id) => (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{branch.name} (actual)</option>
          {branches.filter((b) => b.id !== branch.id).map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
          <option value="all">Todas las sucursales</option>
        </select>
      )}
    </Field>
  );
}
