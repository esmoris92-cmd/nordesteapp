// Domicilio del paciente: campos opcionales (los usa el formulario de AYEX del BPS).
import { Field } from "../components";
import type { PatientAddress } from "../types";

export const ADDRESS_FIELDS: [keyof PatientAddress, string, number][] = [
  ["address_department", "Departamento", 40],
  ["address_locality", "Localidad", 80],
  ["address_street", "Calle", 120],
  ["address_number", "Número", 20],
  ["address_apartment", "Apto.", 20],
  ["address_solar", "Solar", 20],
  ["address_block", "Manzana", 20],
];

export type AddressForm = Record<keyof PatientAddress, string>;

export function emptyAddress(from?: PatientAddress): AddressForm {
  return Object.fromEntries(ADDRESS_FIELDS.map(([k]) => [k, from?.[k] ?? ""])) as AddressForm;
}

/** Para enviar a la API: los vacíos van como null. */
export function addressPayload(form: AddressForm): PatientAddress {
  return Object.fromEntries(ADDRESS_FIELDS.map(([k]) => [k, form[k].trim() || null]));
}

/** "Calle Falsa 123, apto. 2 — Pando, Canelones" (o null si no hay nada cargado). */
export function addressText(p: PatientAddress): string | null {
  const street = [p.address_street, p.address_number].filter(Boolean).join(" ");
  const extra = [
    p.address_apartment && `apto. ${p.address_apartment}`,
    p.address_solar && `solar ${p.address_solar}`,
    p.address_block && `manzana ${p.address_block}`,
  ].filter(Boolean).join(", ");
  const place = [p.address_locality, p.address_department].filter(Boolean).join(", ");
  const first = [street, extra].filter(Boolean).join(", ");
  const text = [first, place].filter(Boolean).join(" — ");
  return text || null;
}

export function AddressFields({ value, onChange }: { value: AddressForm; onChange: (v: AddressForm) => void }) {
  return (
    <fieldset className="span-all choice address-fields">
      <legend>Domicilio (opcional)</legend>
      <div className="grid-form">
        {ADDRESS_FIELDS.map(([key, label, max]) => (
          <Field key={key} label={label}>
            {(id) => (
              <input id={id} maxLength={max} value={value[key]}
                     onChange={(e) => onChange({ ...value, [key]: e.target.value })} />
            )}
          </Field>
        ))}
      </div>
      <p className="muted small">Se usa en el formulario de AYEX del BPS.</p>
    </fieldset>
  );
}
