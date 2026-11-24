# Seguridad y privacidad: decisiones de diseño

Lumen manejará datos de salud. Este documento explica qué protecciones tiene la
versión actual, cómo se comprueban y qué **falta** antes de usarla con datos reales.

> Lumen **no** está evaluado ni certificado frente a ninguna normativa de protección de
> datos o de historia clínica. Antes de usar datos reales hace falta una evaluación
> especializada (legal y de seguridad).

## 1. Separación entre clínicas (multi-clínica)

**Decisión:** una sola base de datos con la columna `clinic_id` en cada tabla, en dos capas.

1. **Aplicación:** la clínica nunca llega desde el navegador. Se toma de la sesión iniciada
   y se agrega a *todas* las consultas (`app/permissions.py`, `app/routers/*`). Si un
   recurso no pertenece a tu clínica, la respuesta es “no encontrado” (404), sin revelar
   si existe.
2. **Base de datos:** las relaciones usan claves foráneas **compuestas** `(clinic_id, id)`.
   Por ejemplo, una nota apunta a `(clinic_id, patient_id)` del paciente. PostgreSQL
   rechaza cualquier fila que mezcle una clínica con un paciente o profesional de otra,
   aunque el código tuviera un error.

**Cómo se comprueba:** `backend/tests/test_isolation.py` intenta, desde la clínica B, leer,
editar, listar, agendar y conceder accesos sobre datos de la clínica A por cada camino de
la API, y además inserta filas cruzadas directamente en la base.

Pendiente para un servicio con muchas clínicas: añadir *Row Level Security* de PostgreSQL
como tercera capa, y ejecutar las tareas de fondo (hoy no hay) siempre filtradas por clínica.

## 2. Roles y acceso mínimo

| Rol | Pacientes (datos de contacto) | Historia clínica e informes | Agenda | Accesos | Usuarios y auditoría |
|---|---|---|---|---|---|
| Administración | Todos los de su clínica | Historia: **No**. Informes: solo **finalizados**, en lectura | Todas (una sucursal a la vez) | Concede y revoca cualquiera | Sí |
| Recepción | Los de su sucursal y los privados de todas | Historia: **No**. Informes: solo **finalizados**, en lectura | La de su sucursal | No | No |
| Profesional | Solo los autorizados | Solo los autorizados | Gestiona solo la propia; ve la de todos en «Día (todos)» y «Horas libres», en lectura | El responsable puede compartir con colaboradores | No |

* Recepción y Administración pueden **leer e imprimir** los informes **finalizados** (por
  ejemplo, para entregarlos al paciente). No ven borradores, notas de sesión ni las secciones
  del informe en preparación, no pueden crear ni editar informes, y cada consulta queda en la
  auditoría (`tests/test_reception_reports.py`, `tests/test_admin_reports.py`).
* En la Agenda, un profesional puede **ver** los turnos y horarios de todos los profesionales de
  su sucursal activa («Día (todos)» y «Horas libres»), con el nombre del paciente, para coordinar.
  Solo da turnos en su propia columna y no puede modificar los turnos de otros
  (`tests/test_agenda.py`).
* El **logo de la clínica** (PNG o JPG de hasta 1 MB, se comprueba por su contenido; no se
  aceptan SVG) lo sube o quita solo Administración y queda en la auditoría. Lo ve cualquier
  usuario de la clínica, para el encabezado de lo que se imprime (`tests/test_logo_clinica.py`).
* Los permisos se validan **en el servidor en cada petición**; ocultar botones en la
  interfaz es solo comodidad.
* **Acceso compartido:** un paciente tiene como máximo un profesional *responsable*,
  asignado por Administración. El responsable puede autorizar *colaboradores* de su
  clínica. Cada acceso guarda quién lo concedió, cuándo y por qué. Revocar no borra:
  completa quién lo retiró, cuándo y el motivo. Un disparador de la base impide borrar
  accesos o modificar uno ya revocado.
* **Asignar responsable:** Recepción solo puede asignarlo a pacientes que no tienen (igual
  que al darlos de alta). **Cambiar** un responsable existente es solo de Administración.
* **Cambio de responsable:** solo Administración. Revoca el acceso anterior con el motivo y
  crea el nuevo en la misma operación. No se puede eliminar la cuenta de un profesional ni
  quitarle el rol mientras sea responsable de pacientes sin elegir antes quién los recibe,
  para que ningún paciente quede a cargo de una cuenta que ya no puede entrar.
* **Turnos sueltos:** un profesional sin acceso a un paciente no puede tener turnos futuros
  con él. Al revocar el acceso se cancelan con el mismo motivo; al cambiar el responsable se
  pasan al nuevo (con las reglas de disponibilidad y cupo) o se cancelan; al eliminar una
  cuenta hay que decidir cada turno. Nada se borra: un turno pasado a otro profesional queda
  como "reprogramado" y apunta al nuevo.
* Un identificador difícil de adivinar (UUID) **no** se considera autorización.

### Sucursales

* Cada cuenta tiene una lista de sucursales permitidas; Administración entra a todas.
* La sucursal activa se guarda en la sesión del servidor. En **cada pedido** se comprueba que
  siga siendo una sucursal permitida y activa; si se la quitaron, se pide elegir otra.
* Las sucursales no se borran: se desactivan, y debe quedar al menos una activa.
* Cada paciente pertenece a una sucursal. Recepción ve los pacientes de **su sucursal
  activa** y los **privados** de todas (pueden atenderse en cualquiera); los de AYEX,
  Tutela Militar y Tutela Policial solo desde su sucursal. Esto se aplica en el servidor, en el listado,
  la ficha, la exportación y la búsqueda de la agenda.
* Al crear, editar o importar un paciente solo se puede elegir una sucursal permitida para
  la cuenta.
* Cada horario de disponibilidad y cada turno pertenecen a una sucursal. Los turnos nuevos se
  dan en la sucursal activa y el servidor comprueba que el profesional trabaje allí, que el
  horario esté dentro de su disponibilidad **en esa sucursal** y que no tenga otro turno a la
  misma hora en otra sucursal. Recepción solo ve y gestiona los turnos de su sucursal.
* **Inicio** e **Informe mensual**: recepción ve solo su sucursal; administración, la
  sucursal activa o, si lo elige, todas juntas; cada profesional, lo suyo en todas sus
  sucursales. El servidor rechaza que recepción pida otra sucursal o todas.
* A un profesional no se le puede quitar una sucursal, ni se puede desactivar una sucursal,
  mientras haya turnos futuros allí.
* La sucursal no cambia el acceso a la historia clínica: sigue dependiendo de ser responsable
  o colaborador del paciente.

## 3. Historia clínica y auditoría inalterables

* `clinical_notes` y `audit_log` son de **solo-agregar**: un disparador de PostgreSQL
  rechaza cualquier `UPDATE` o `DELETE`.
* Corregir una nota crea una **nueva versión** que apunta a la anterior e indica el motivo.
  Solo la autora o el autor puede corregir, y ambas versiones quedan visibles.
* Un informe es editable mientras es borrador. Al finalizarlo queda fijo (también lo
  impone la base). Los informes no se borran.
* La auditoría registra inicios de sesión, consultas de fichas, historias e informes, y
  altas o cambios de pacientes, accesos, turnos, notas, informes y usuarios. Solo guarda
  **metadatos** (quién, qué, cuándo, sobre qué entidad). Una lista blanca de campos impide
  copiar contenido clínico (`app/audit.py`), y una prueba lo verifica.

### Plan de tratamiento

* Los objetivos y sus avances son información clínica: solo los ven y escriben los
  profesionales con acceso activo al paciente; Administración y Recepción no.
* El texto de un objetivo no se edita; cada avance o cambio de estado es un registro nuevo
  con autor y fecha. Dos disparadores de la base impiden modificar o borrar objetivos (salvo
  su estado y avance) y registros de avance.

## 4. Autenticación y sesiones

* **Eliminar una cuenta la archiva**, no la borra: queda desactivada, oculta de la lista y
  sin sesiones, pero se conservan su historial (notas, informes, turnos, accesos, auditoría)
  y su correo sigue reservado. Se puede restaurar. La base impide que una cuenta archivada
  esté activa.
* Las especialidades pertenecen a cada clínica (clave foránea compuesta `(clinic_id, id)`):
  una cuenta no puede quedar vinculada a la especialidad de otra clínica. Solo Administración
  las crea, renombra o desactiva; no se borran.

* Administración puede editar nombre, correo y rol de las cuentas de su clínica. Al cambiar
  el correo o el rol se cierran las sesiones abiertas de esa persona; la auditoría registra
  qué campos cambiaron, no sus valores. Nadie puede quitarse a sí mismo el rol de
  administración ni desactivar su propia cuenta.

* Contraseñas con **Argon2id** (biblioteca `argon2-cffi`) y mínimo de 12 caracteres.
* Bloqueo temporal de 15 minutos tras 5 intentos fallidos. El mensaje de error es el mismo
  para “correo inexistente” y “contraseña incorrecta”, y el tiempo de respuesta se iguala.
* Sesión en una cookie `HttpOnly` y `SameSite=Strict`, que además es `Secure` en
  producción. En la base solo se guarda el **hash** del token.
* Vencimiento a las 8 horas, o tras 60 minutos sin actividad. Cerrar sesión, cambiar la
  contraseña o desactivar a la persona invalida las sesiones en el servidor.
* **CSRF:** toda petición que modifica datos exige la cabecera `X-CSRF-Token`, ligada a la
  sesión.
* **XSS:** React escapa el texto por defecto y no se usa `dangerouslySetInnerHTML`. La
  interfaz se sirve con una *Content-Security-Policy* que solo permite scripts del propio
  servidor.

## 4 bis. Restablecer contraseña

* Solo Administración, y no para su propia cuenta (esa se cambia en "Mi cuenta").
* Lumen genera una contraseña temporal aleatoria que se muestra **una sola vez**; solo se
  guarda su hash. Se cierran las sesiones abiertas de esa persona y se quita el bloqueo por
  intentos fallidos.
* Con la temporal, la cuenta solo puede cambiar su contraseña (o salir): el servidor rechaza
  cualquier otra acción hasta que elija una nueva, distinta de la temporal.
* La auditoría registra que hubo un restablecimiento, nunca la contraseña.

## 5. Datos expuestos al mínimo

* Los errores de validación responden en español **sin repetir lo enviado**, que podría
  ser texto clínico.
* El registro técnico de la Terminal muestra método, ruta y código, pero no los parámetros
  de búsqueda ni los cuerpos. En producción, los errores inesperados registran solo el tipo
  de error.
* Las respuestas de la API llevan `Cache-Control: no-store`, para que el navegador no
  guarde copias.
* El listado de informes no incluye su contenido; solo se envía al abrir uno.
* La documentación interactiva de la API (`/api/docs`) se desactiva en producción.
* El **documento (cédula)** del paciente es un dato personal identificatorio: se muestra
  solo dentro de la clínica y la auditoría registra que cambió, nunca su valor.

## 5 bis. Archivos adjuntos

* Son información clínica: solo los profesionales con acceso activo al paciente los ven,
  suben o descargan. Administración y recepción reciben "sin permiso".
* El tipo se verifica por el **contenido real** del archivo (firma de PDF, PNG o JPG), no
  por la extensión. Cualquier otro tipo se rechaza.
* Se guardan con un **nombre aleatorio** en `FILES_DIR` (por defecto `backend/storage/files`,
  excluida de Git), fuera de la carpeta pública de la web.
* La descarga se entrega siempre como adjunto, con `nosniff`, para que el navegador no la
  ejecute como página. Cada descarga queda auditada, sin copiar el nombre del archivo.
* **Ver** (visor dentro de Lumen): el mismo archivo se entrega "en línea" para mostrarlo en
  una ventana, sin guardarlo en Descargas. Solo esa respuesta permite mostrarse dentro de
  Lumen (`frame-ancestors 'self'`, `X-Frame-Options: SAMEORIGIN`) y no lleva otras reglas
  de contenido, porque el visor de PDF del navegador las necesita; ninguna otra página puede
  incrustarla. Cada vez que se abre queda auditado como "file.view".
* No se borran: se **retiran** con motivo (lo impide también un *trigger* de la base).
* Pendiente para producción: cifrar los archivos en reposo e incluir `FILES_DIR` en las
  copias de seguridad.

## 5 ter. Importación de pacientes (CSV)

* Solo Administración y Recepción. El archivo va directo del navegador a Lumen: **no se
  guarda** en disco ni en la base, solo se crean los pacientes válidos.
* La vista previa no escribe nada; al confirmar, el servidor vuelve a revisar todo.
* Cada alta queda auditada como "patient.import", sin copiar nombres ni documentos.
* Límites: 2 MB y 2000 filas por archivo.
* Con datos reales, cargar el archivo solo en la instalación de la clínica, nunca enviarlo
  por chat ni subirlo al repositorio.

## 5 cuater. Exportación de pacientes (Excel)

* Solo Administración y Recepción. Exporta datos **administrativos** (documento, nombres,
  sexo, afiliación, nacimiento, contacto, responsable, estado); nunca historia clínica,
  informes ni archivos.
* Respeta los filtros del listado y nunca incluye pacientes de otra clínica.
* Cada exportación queda en la auditoría con la cantidad de pacientes, sin copiar datos.
* Todo el texto se guarda como texto: un valor como `=…` no se ejecuta como fórmula al abrir
  el archivo en Excel.
* El archivo descargado contiene datos personales: guardarlo en un lugar seguro y borrarlo
  cuando ya no se necesite.

## 6. Qué falta antes de producción (no configurado todavía)

* **HTTPS** obligatorio (proxy inverso con certificado) y `ENVIRONMENT=production`.
* Copias de seguridad: ya existen el comando para crearlas (base + adjuntos, con huellas
  SHA-256), verificarlas restaurando de verdad y restaurarlas
  (`scripts/copia-seguridad.sh`). Falta: **cifrarlas** (hoy dependen de guardarse en un disco
  cifrado) y guardar una copia fuera del equipo. Ya pueden programarse a diario
  (`scripts/copias-automaticas.sh`).
* Cifrado del disco o volumen de la base y de la carpeta de archivos, y gestión de secretos
  (no `.env` en servidores).
* Límite de peticiones (*rate limiting*) a nivel de red, además del bloqueo por cuenta.
* Segundo factor de autenticación (2FA) y política de recuperación de contraseña.
* *Row Level Security* en PostgreSQL (ver sección 1).
* Política de retención, exportación y derecho de acceso a los datos, que requiere
  asesoramiento legal.
* Monitoreo, alertas y revisión periódica de la auditoría.
* Revisión de seguridad independiente (pentest).
