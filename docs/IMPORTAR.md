# Importar pacientes desde Excel (CSV)

Esta guía explica cómo pasar la lista de pacientes que ya tienes en Excel a Nordeste,
paso a paso. Se puede hacer con muchos pacientes a la vez (hasta 2000 por archivo).

> **Privacidad:** el archivo con los pacientes reales nunca se pega en un chat, ni se manda
> por correo, ni se guarda dentro de la carpeta del proyecto `medflow`. Guárdalo, por ejemplo,
> en `Documentos/MedFlow-importacion`. Por las dudas, Git ya está configurado para ignorar
> cualquier `.csv` o `.xlsx` dentro del proyecto.

## Antes de empezar

1. **Haz una copia de seguridad** (desde la carpeta del proyecto):
   `bash scripts/copia-seguridad.sh crear`. Si algo sale mal, se puede volver atrás.
2. **Crea las sucursales** (Usuarios → Sucursales) con los nombres que vas a usar en el
   archivo: por ejemplo `Central`, `Pando` y `Anexo`.
3. **Crea las cuentas de los profesionales** si quieres asignar el responsable al importar.
4. Entra a Nordeste como **administración** (puede cargar pacientes en todas las sucursales).
   Recepción solo puede importar pacientes de su propia sucursal.

## 1. Preparar la planilla

Puedes descargar la **planilla modelo** desde Nordeste (Pacientes → Importar desde CSV →
"planilla modelo") o usar tu propia planilla, siempre que la primera fila tenga estos
nombres de columna (no importan las mayúsculas ni las tildes, y el orden puede ser otro).
Hay un ejemplo con datos ficticios en `docs/ejemplo-importacion-pacientes.csv`: ábrelo con
Excel para ver cómo queda (no lo importes).

| Columna | ¿Obligatoria? | Qué poner | Ejemplo |
|---|---|---|---|
| `documento` | No | Cédula. Con o sin puntos y guion: `1.234.567-8` y `12345678` se consideran la **misma**. | `1.234.567-8` |
| `primer_nombre` | **Sí** | | `Ana` |
| `segundo_nombre` | No | | `Laura` |
| `primer_apellido` | **Sí** | | `Ejemplo` |
| `segundo_apellido` | No | | `Ficticia` |
| `sexo` | No | `M`, `F` o `X` (también "masculino", "femenino") | `F` |
| `tipo_afiliacion` | **Sí** | `Privado`, `AYEX`, `Tutela Militar` o `Tutela Policial` (también "militar" o "policial") | `AYEX` |
| `vencimiento_ayex` | No (recomendada para AYEX) | Fecha de vencimiento del AYEX, día/mes/año: `31/12/2026`. Solo se guarda en pacientes AYEX. Si queda vacía, el Inicio avisa cuántos AYEX no tienen fecha para completarla luego en la ficha | `31/12/2026` |
| `fecha_nacimiento` | No | Día/mes/año: `14/03/1990` (también `14-03-1990` o `1990-03-14`) | `14/03/1990` |
| `telefono` | No | | `099 000 001` |
| `correo` | No | | `ana@correo.test` |
| `profesional_responsable` | No | El **correo** del profesional o su **nombre completo** tal como figura en Nordeste | `lucia@clinica.uy` |
| `sucursal` | No | El nombre de la sucursal tal como figura en Nordeste. Si falta, el paciente queda en la sucursal en la que estás. | `Pando` |

Otros nombres de columna que también se reconocen: `cedula` o `ci` (documento), `nombre`,
`apellido`, `afiliacion`, `celular`, `email`, `responsable`. Las columnas que Nordeste no
conoce (por ejemplo "Observaciones") se ignoran y te avisa cuáles son.

**Recuerda:** los pacientes de **AYEX**, **Tutela Militar** y **Tutela Policial** solo se atienden en su sucursal,
así que revisa bien la columna `sucursal` para ellos. Los privados pueden atenderse en
cualquiera.

## 2. Guardarla como CSV

En Excel: **Archivo → Guardar como** → en "Formato de archivo" elige **CSV UTF-8 (delimitado
por comas)** → Guardar. Si Excel avisa que se pueden perder funciones, acepta: el CSV solo
guarda los datos, y es lo que necesita Nordeste.

Si tienes más de 2000 pacientes, divídelos en varios archivos (por ejemplo, uno por sucursal).

## 3. Revisar el archivo (no guarda nada)

1. En Nordeste: **Pacientes → Importar desde CSV**.
2. Elige el archivo y toca **Revisar archivo**.
3. Verás cuántas filas están **correctas** y cuántas **con errores**, y en cada fila con
   error, qué hay que arreglar (fecha que no existe, afiliación no reconocida, sucursal mal
   escrita, documento repetido, etc.).

Todavía no se guardó nada: puedes cerrar, arreglar el Excel y volver a revisar las veces que
quieras.

## 4. Importar

Cuando estés conforme, toca **Importar N pacientes** (N es la cantidad de filas correctas). Se cargan **solo las filas correctas**; las
que tienen errores quedan afuera.

**Importa cada archivo una sola vez.** Si lo vuelves a importar, los pacientes con documento
se detectan como repetidos, pero los que **no tienen documento** se cargarían dos veces.

## 5. Corregir las filas con errores

1. En la revisión, toca **Descargar filas con errores (CSV)**. Baja un archivo solo con esas
   filas, tal como estaban, y una última columna **errores** que dice qué arreglar en cada una.
2. Ábrelo en Excel, corrige cada fila (puedes borrar la columna "errores" o dejarla: se ignora)
   y guárdalo de nuevo como CSV UTF-8.
3. Impórtalo (revisar → importar). Así no se tocan los pacientes que ya entraron.

Cuando termines, borra los archivos CSV de tu computadora si ya no los necesitas: tienen
datos personales de los pacientes.

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| "Faltan columnas obligatorias" | La primera fila debe tener `primer_nombre`, `primer_apellido` y `tipo_afiliacion` (o sus variantes). |
| "Fecha de nacimiento no válida" | Usa día/mes/año con el año completo (`14/03/1990`, no `14/03/90`) y revisa que el día exista. |
| "Sucursal no encontrada o no permitida" | Escribe el nombre como figura en Nordeste. Recepción solo puede usar su sucursal. |
| "Profesional responsable no encontrado" | Usa el correo del profesional, o su nombre completo exactamente como en Usuarios. |
| "Ya existe un paciente con ese documento" | Ese paciente ya está cargado: no hace falta importarlo. |
| Letras raras en los nombres (Ã³ en vez de ó) | Guardaste con otro formato: vuelve a guardar como **CSV UTF-8**. |
