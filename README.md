# Lumen

Sistema web de gestión clínica para clínicas y consultorios de **psicología**,
**terapia ocupacional** y otras especialidades que cada clínica configure (p. ej. fonoaudiología).

> ⚠️ **Estado: primera versión de desarrollo (0.1.0).** No está lista para datos reales.
> Úsala solo con datos ficticios. Ver [docs/SEGURIDAD.md](docs/SEGURIDAD.md).

## Qué incluye esta versión

- **Inicio** con un resumen: sesiones y asistencia del mes, pacientes activos, vencimientos de AYEX,
  próxima sesión y los demás turnos de ese día (cada profesional ve lo suyo en todas sus
  sucursales; recepción, su sucursal; administración, la sucursal activa o todas juntas).
- Inicio de sesión con cuentas individuales y roles: **Administración**, **Recepción** y **Profesional**.
- **Pacientes:** alta, consulta, edición, estado (activo, en pausa, alta, inactivo) y búsqueda
  por nombre, apellido o documento. El listado muestra las **inasistencias del mes** de cada
  paciente (turnos marcados como ausente; vuelven a cero cada mes). **Ficha del paciente** con encabezado, pestañas e
  información general (documento, nombres y apellidos, sexo, **tipo de afiliación** obligatorio:
  Privado, AYEX, Tutela Militar o Tutela Policial, edad, fecha de registro).
- **Importar pacientes desde CSV** (por ejemplo, una planilla de Excel guardada como CSV):
  planilla modelo, vista previa con los errores de cada fila, alta solo de las filas correctas y
  descarga de las filas con errores para corregirlas. Guía paso a paso en
  [docs/IMPORTAR.md](docs/IMPORTAR.md).
- **Exportar pacientes a Excel (.xlsx)** con los filtros del listado (administración y
  recepción; solo datos administrativos, nunca historia clínica). Las columnas coinciden con
  las de la importación.
- **Responsables o tutores** del paciente (vínculo, teléfono, correo, contacto principal).
- **Instituciones educativas** del paciente (inicial, primaria, secundaria, UTU, universidad u
  otra) con teléfono y correo de contacto, cuál es la actual, y en cada una **reportes**
  (como la historia clínica: no se borran, se corrigen con motivo) y **archivos**. El contacto
  lo ve quien ve la ficha; los reportes y archivos, solo los profesionales con acceso.
- **Profesionales y asignación:** responsable por paciente, más **acceso compartido**
  autorizado expresamente, revocable y con historial de quién lo concedió o retiró.
  Desde el listado, recepción **asigna** responsable a los pacientes que no tienen y
  administración puede además **cambiarlo** (con motivo) en un solo paso, y al eliminar la cuenta
  de un profesional debe elegir quién queda a cargo de cada uno de sus pacientes y qué pasa
  con cada uno de sus turnos futuros (se cancelan con motivo o pasan a otro profesional).
  Revocar un acceso cancela los turnos futuros de ese profesional con el paciente.
- **Agenda por profesional:** disponibilidad semanal, turnos, cancelaciones con motivo,
  reprogramaciones (queda el turno original) y marca de realizado o ausente. Cada
  profesional puede atender **varios pacientes en el mismo horario** (3 por defecto,
  configurable de 1 a 10); un mismo paciente nunca tiene dos turnos superpuestos.
  Vista en **grilla semanal** (disponibilidad sombreada; clic en un hueco para dar turno), en
  lista o, para recepción y administración, **Día (todos)**: todos los profesionales de la
  sucursal en un mismo día, uno por columna. En las tres vistas, al tocar un turno se abre una
  ventana para marcarlo realizado o ausente, reprogramarlo o cancelarlo. Si un paciente pasa a en pausa, alta o inactivo, sus turnos futuros se cancelan.
- **Historia clínica:** notas de sesión, antecedentes y evolución, más pestañas propias para
  **anamnesis**, **entrevistas** y **evaluaciones**. No se editan ni se borran: las
  correcciones crean una nueva versión con el motivo.
- **Plan de tratamiento:** objetivos por área (lenguaje, motricidad, etc.) con fecha objetivo,
  avance en porcentaje y notas por sesión; estados en curso, logrado o discontinuado. Lo usan
  todos los profesionales que atienden al paciente; nada se reescribe ni se borra.
- **Archivos adjuntos** (PDF, PNG, JPG hasta 10 MB) visibles solo para los profesionales
  autorizados; no se borran, se retiran con motivo.
- **Informes profesionales:** borrador editable que queda fijo al finalizarse; los finalizados
  se pueden **imprimir o guardar en PDF**, igual que la ficha del paciente.
- **Informe mensual** de sesiones por profesional y tipo de afiliación (realizadas, ausentes,
  canceladas, pacientes atendidos), separado por sucursal y exportable a Excel. Recepción ve
  su sucursal; administración, la sucursal activa o todas (con un total por sucursal); cada
  profesional, lo suyo.
- **Administración básica:** nombre de la clínica; alta, edición (nombre, correo, rol), desactivación y eliminación (archivado) de cuentas;
  **especialidades editables** (por ejemplo, agregar Fonoaudiología).
- **Restablecer contraseña** desde administración: contraseña temporal que se muestra una vez
  y obliga a elegir una nueva al entrar.
- **Copias de seguridad** manuales o **automáticas cada día** (se conservan las 30 últimas).
- **Auditoría:** quién consultó o modificó qué, y cuándo, sin copiar contenido clínico.
- **Sucursales** (por ejemplo Central, Pando y Anexo): cada cuenta entra solo a las que tiene
  asignadas (Administración, a todas); al entrar se elige la sucursal y se puede cambiar
  desde el encabezado.
- **Pacientes por sucursal:** cada paciente tiene su sucursal (obligatoria). Recepción ve los
  de su sucursal y los privados de todas; AYEX, Tutela Militar y Tutela Policial solo en su
  sucursal. El
  listado se muestra de a 50, con filtro por sucursal, y en la agenda el paciente se busca
  escribiendo su nombre.
- **Agenda por sucursal:** los horarios y turnos de cada profesional son por sucursal; la
  agenda muestra la sucursal activa. Un profesional nunca está en dos sucursales a la misma
  hora, y los pacientes de AYEX, Tutela Militar y Tutela Policial solo reciben turnos en su
  sucursal.
- **Separación por clínica** desde el diseño, impuesta también por la base de datos.

## Tecnologías

| Parte | Tecnología |
|---|---|
| Interfaz | React 19 + TypeScript, compilado con esbuild |
| API | Python 3.11+ con FastAPI, SQLAlchemy 2 y Alembic |
| Base de datos | PostgreSQL |

La API y la interfaz se sirven juntas en **http://localhost:8000**.

## Cómo empezar

La guía completa, paso a paso y para las dos Macs, está en
**[docs/INSTALACION.md](docs/INSTALACION.md)**. Resumen:

```bash
# 1) Base de datos: instala y abre Postgres.app, luego:
bash scripts/crear-base-local.sh   # crea usuario, bases y backend/.env

# 2) Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements-dev.txt
alembic upgrade head          # crea las tablas
python -m app.seed            # carga datos ficticios
uvicorn app.main:app --reload --no-access-log

# 3) Interfaz (en otra Terminal)
cd frontend
npm install
npm run build
# reinicia el backend y abre http://localhost:8000
```

**Copias de seguridad:** `bash scripts/copia-seguridad.sh` guarda la base y los adjuntos en
`~/MedFlow-copias`; con `verificar` comprueba que se pueden restaurar
([docs/INSTALACION.md](docs/INSTALACION.md), sección 4 bis).

**Dejar la base sin pacientes (para una demostración):** `bash scripts/vaciar-pacientes.sh`
borra todos los pacientes y lo que depende de ellos (turnos, historia clínica, informes,
archivos, auditoría) y conserva la clínica, las sucursales, los usuarios y sus horarios.
Hace antes una copia de seguridad y pide escribir `BORRAR PACIENTES`. Solo en la base local.

**Uso diario:** `bash scripts/iniciar.sh` arranca Lumen desde cualquier carpeta
(comprueba antes el entorno virtual, la interfaz compilada y que el puerto esté libre).

## Cuentas de demostración (datos ficticios)

Todas usan la contraseña definida en `DEMO_PASSWORD` de `backend/.env`. El valor de
ejemplo es `MedFlow-Demo-2026`; es solo para tu base local y no debe reutilizarse en
ningún otro lugar.

| Correo | Rol | Qué ve |
|---|---|---|
| `admin@aurora.demo` | Administración | Todo lo administrativo de Clínica Aurora, los informes finalizados y la auditoría; sin historia clínica |
| `recepcion@aurora.demo` | Recepción (Central) | Pacientes, agenda e informes finalizados de Aurora; sin historia clínica |
| `recepcion.pando@aurora.demo` / `recepcion.anexo@aurora.demo` | Recepción (Pando / Anexo) | Solo en bases nuevas: las sucursales Pando y Anexo las crea el seed |
| `lucia@aurora.demo` | Psicología | Sus 3 pacientes (responsable) |
| `mateo@aurora.demo` | Terapia ocupacional | Su paciente, más Valentina como colaborador |
| `sofia@aurora.demo` | Psicología | Solo a Elena |
| `admin@boreal.demo` | Administración | Solo la clínica Boreal (para comprobar el aislamiento) |
| `bruno@boreal.demo` | Psicología | Solo a su paciente de Boreal |

Qué probar y qué resultado esperar: **[docs/PRUEBAS.md](docs/PRUEBAS.md)**.

Probarlo en un servidor en internet (DigitalOcean), con HTTPS y datos ficticios:
**[docs/SERVIDOR.md](docs/SERVIDOR.md)**.

## Pruebas

```bash
cd backend && source .venv/bin/activate && pytest
```

Hay 140 pruebas sobre los flujos críticos: aislamiento entre clínicas, acceso compartido
autorizado y no autorizado, inalterabilidad de la historia clínica, sesiones y agenda.

## Estructura

```
backend/
  app/            API: modelos, permisos, rutas y auditoría
  migrations/     migraciones de base de datos (Alembic)
  tests/          pruebas automáticas
frontend/
  src/            interfaz React (páginas, componentes y cliente de la API)
  public/         index.html
docs/             instalación, seguridad y pruebas
scripts/          utilidades (verificar-entorno.sh)
```

## Pendiente y problemas conocidos

- Pruebas automáticas ejecutadas en la Mac M1 (macOS, Python 3.13, PostgreSQL 18):
  **140 aprobadas**. Falta ejecutarlas en la Mac Intel (Monterey).
- **Zona horaria:** la agenda usa la hora de la computadora, que debe coincidir con la de
  la clínica (`America/Montevideo` en la demo).
- No hay recuperación de contraseña por correo ni segundo factor (2FA).
- No hay paginación: los listados muestran hasta 500 pacientes y 300 eventos de auditoría.
- Falta todo lo listado en “Qué falta antes de producción”
  ([docs/SEGURIDAD.md](docs/SEGURIDAD.md#6-qué-falta-antes-de-producción-no-configurado-todavía)).
- Fuera de alcance por decisión: facturación, pagos, CRM, app móvil nativa y funciones
  hospitalarias.
