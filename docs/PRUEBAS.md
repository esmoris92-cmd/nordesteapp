# Pruebas

## Pruebas automáticas (backend)

Requisitos: haber completado los pasos 1 y 2 de `INSTALACION.md`, incluida la base
`medflow_test` y `TEST_DATABASE_URL` en `backend/.env`.

```bash
cd medflow/backend
source .venv/bin/activate
pytest
```

**Qué deberías ver:** puntos (`.`) que avanzan y, al final, algo como `170 passed in 30s` (en una computadora sin la librería
`openpyxl` verás `169 passed, 1 skipped`: esa prueba extra se omite y es normal).
Una `F` indica una prueba fallida, con el detalle debajo.

Las pruebas **borran el contenido de `medflow_test`** en cada ejecución. Por seguridad, se
niegan a correr si el nombre de la base de pruebas no termina en `_test`. Antes de empezar,
también revierten y vuelven a aplicar la migración, lo que comprueba que es reversible.

| Archivo | Qué comprueba |
|---|---|
| `test_auth.py` | Inicio y cierre de sesión, cookie segura, bloqueo por intentos, CSRF, hash de contraseñas, cuenta desactivada |
| `test_isolation.py` | Que ninguna operación cruce datos entre clínicas, ni por la API ni directamente en la base |
| `test_access.py` | Permisos por rol, acceso compartido concedido y revocado, trazabilidad, validaciones en español |
| `test_clinical.py` | Notas de solo-agregar, correcciones con motivo, informes borrador/final, que la auditoría no copie contenido clínico |
| `test_reception_reports.py` | Recepción lee solo informes finalizados, no escribe, no ve notas, queda auditada |
| `test_logo_clinica.py` | Logo de la clínica: solo Administración lo sube o quita, solo PNG/JPG de hasta 1 MB, lo ve toda la clínica (y ninguna otra), queda auditado |
| `test_admin_reports.py` | Administración lee solo informes finalizados (de todas las sucursales), no escribe, no ve notas ni secciones, queda auditada |
| `test_users.py` | Edición de cuentas: correo único, sesiones cerradas al cambiar correo o rol, auditoría sin valores |
| `test_specialties.py` | Especialidades por clínica: alta, nombre único, desactivar sin quitar, aislamiento |
| `test_archive.py` | “Eliminar” archiva: oculta y bloquea la cuenta, conserva su historial, se puede restaurar |
| `test_dashboard.py` | Inicio: cada profesional ve solo sus números; recepción su sucursal; nada de otra clínica |
| `test_group_sessions.py` | Hasta N pacientes a la vez por profesional; el mismo paciente no se superpone |
| `test_patient_profile.py` | Ficha: documento único por clínica y en mayúsculas, segundo nombre/apellido, sexo, tipo de afiliación obligatorio y filtro por afiliación, búsqueda por documento |
| `test_guardians.py` | Responsables: quién puede verlos y editarlos, un solo contacto principal, auditoría |
| `test_note_kinds.py` | Anamnesis, entrevista y evaluación: se guardan como registros clínicos inalterables |
| `test_files.py` | Archivos: solo PDF/PNG/JPG reales, límite de tamaño, sin acceso para administración/recepción, descarga segura, visor dentro de Lumen (auditado y que no se puede incrustar en otros sitios), retiro con motivo |
| `test_branches.py` | Sucursales: entra directo si tiene una, elige si tiene varias, el servidor rechaza sucursales no permitidas, cambio de permisos en el momento, administración de sucursales, cuentas sin sucursal |
| `test_patient_branches.py` | Pacientes por sucursal: recepción ve su sucursal y los privados de todas, no puede crear en una sucursal ajena, el filtro por sucursal, el listado de a páginas con el total y la sucursal en la importación |
| `test_agenda_branches.py` | Agenda por sucursal: horarios solo donde trabaja el profesional y nunca a la misma hora en dos sucursales, turnos en la sucursal activa, AYEX, Tutela Militar y Tutela Policial solo en su sucursal, recepción solo gestiona su sucursal, no se puede quitar una sucursal con turnos pendientes, vista diaria con los horarios de todos los profesionales de la sucursal |
| `test_collaborators.py` | Varios profesionales con un paciente: el colaborador recibe turnos, recepción ve responsable y colaboradores (listado y ficha) pero no puede agregarlos, y el error al dar turno explica qué hacer |
| `test_afiliaciones.py` | Tipos de afiliación Privado, AYEX, Tutela Militar y Tutela Policial: alta, importación (con variantes como "policial"), filtro, y que los no privados se atienden solo en su sucursal |
| `test_compression.py` | Compresión gzip de la interfaz y los datos (carga más rápida por internet), salvo el inicio de sesión, que lleva el token CSRF |
| `test_demo_check.py` | Antes de abrir Lumen por internet: detecta las cuentas que todavía usan la contraseña de demostración |
| `test_reports_branches.py` | Inicio e informe mensual por sucursal: administración ve la activa, otra o todas; recepción solo la suya; cada profesional lo suyo en todas sus sucursales; Excel con columna y totales por sucursal |
| `test_goals.py` | Plan de tratamiento: solo profesionales con acceso (responsable y colaboradores), avances y estados, reabrir, validaciones, la base impide reescribir o borrar, auditoría sin textos |
| `test_password_reset.py` | Restablecer contraseña: temporal mostrada una vez, sesiones cerradas, obligación de cambiarla antes de usar Lumen, desbloqueo, solo administración, nunca en la auditoría |
| `test_monthly_summary.py` | Informe mensual: conteos por estado y afiliación, pacientes atendidos, límites del mes en hora de la clínica, profesional ve solo lo suyo, exportación sin nombres de pacientes |
| `test_patient_export.py` | Exportación a Excel: solo administración y recepción, respeta filtros, nunca muestra otra clínica, el texto nunca se ejecuta como fórmula, queda auditada |
| `test_patient_import.py` | Importación CSV: la vista previa no guarda, errores por fila (fecha, sexo, documento repetido, responsable inexistente), el mismo documento escrito con o sin puntos, descarga de las filas con errores, solo administración y recepción, codificación de Excel |
| `test_backup.py` | Copias de seguridad: crear y restaurar de verdad, conservar solo las N más recientes, permisos solo para tu usuario, detectar copias dañadas o con rutas peligrosas, restaurar guardando antes el estado actual, nunca dentro del proyecto |
| `test_orphan_appointments.py` | Turnos sueltos: un paciente que deja de estar activo pierde sus turnos futuros; al eliminar una cuenta hay que decidir cada turno futuro (cancelar o pasar); revocar un acceso cancela sus turnos; cambiar el responsable los pasa o cancela; un pase que no entra se rechaza sin cambiar nada |
| `test_responsible.py` | Recepción solo asigna responsable si falta; administración lo cambia con motivo; al eliminar una cuenta, reasignación obligatoria de sus pacientes; rol bloqueado mientras sea responsable |
| `test_agenda.py` | Disponibilidad, superposición, cancelación, reprogramación, agenda propia del profesional (y la de todos en lectura con «Día (todos)») |

Para ejecutar un solo archivo: `pytest tests/test_isolation.py`.
Para ver el nombre de cada prueba: `pytest -v`.

## Verificación de la interfaz

```bash
cd medflow/frontend
npm run typecheck   # revisa los tipos de TypeScript; no debería mostrar errores
npm run build       # debe terminar con "Interfaz compilada"
```

## Recorrido manual sugerido

Todas las cuentas usan la contraseña definida en `DEMO_PASSWORD` de `backend/.env`.

1. **Recepción** (`recepcion@aurora.demo`)
   - Ves los 5 pacientes ficticios de la Clínica Aurora y ningún paciente de Boreal.
   - Abre “Valentina Ejemplo”: no aparece “Historia clínica”. En “Informes” ves solo los
     informes **finalizados**, sin botón para crear o editar. (El informe de ejemplo es un
     borrador: aparecerá cuando Lucía lo finalice.)
   - En **Agenda**, elige “Lic. Lucía Ficticia” y da un turno a Valentina un día hábil a las
     10:00. Prueba también las 20:00: debería decir que está fuera de la disponibilidad.
   - Agenda a **tres** pacientes de Lucía el mismo día a la misma hora: los tres entran. Un
     cuarto turno en ese horario, o repetir un paciente, muestra un aviso.
   - Crea un paciente ficticio nuevo y asígnale un profesional responsable.

2. **Profesional responsable** (`lucia@aurora.demo`)
   - Ves solo a Valentina, Martín y Carla.
   - En la historia clínica de Valentina, crea una nota y luego **corrígela**. Marca
     “Mostrar versiones corregidas”: las dos versiones siguen visibles, con el motivo.
   - En **Informes**, abre el borrador de ejemplo, edítalo y **finalízalo**. Ya no se puede
     editar.
   - En **Accesos**, verás que Mateo es colaborador. Revócale el acceso indicando un motivo.

3. **Profesional colaborador** (`mateo@aurora.demo`)
   - Después del paso anterior, Valentina ya no aparece en su lista.
   - Si Lucía vuelve a concederle acceso, la recupera.

4. **Otra profesional** (`sofia@aurora.demo`)
   - Solo ve a Elena. Si pegas en la barra de direcciones el enlace de la ficha de
     Valentina, aparece “Paciente no encontrado”.

5. **Administración** (`admin@aurora.demo`)
   - **Auditoría** muestra quién consultó o modificó qué, y cuándo, sin textos clínicos.
   - **Usuarios**: crea una cuenta ficticia y desactívala. Pulsa **Editar** en otra cuenta y
     cámbiale el correo: esa persona tendrá que volver a entrar con el correo nuevo.
   - **Usuarios → Especialidades**: la demo ya trae *Fonoaudiología*. Agrega otra (por ejemplo
     *Psicopedagogía*) y crea una cuenta profesional con esa especialidad: aparecerá en
     Agenda y en Accesos con su especialidad.
   - **Usuarios → Eliminar** en una cuenta: desaparece de la lista y no puede entrar. Marca
     *Mostrar eliminadas* para verla y **Restaurar**la (vuelve desactivada).
   - En la ficha de un paciente no aparece “Historia clínica”. En “Informes” ves solo los
     informes **finalizados**, en modo lectura, con el botón **Imprimir / PDF**.

6. **Otra clínica** (`admin@boreal.demo`)
   - Solo ves a “Pablo Boreal-Demo”. Ningún dato de Aurora es visible.
