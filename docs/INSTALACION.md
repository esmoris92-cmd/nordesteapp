# Instalación y ejecución local (Mac M1 y Mac Intel)

Esta guía sirve para las dos computadoras. Donde hay diferencias, se indica.
Cada comando se escribe en la app **Terminal** y se ejecuta con **Enter**.

> **Convención:** el texto `medflow/` se refiere a la carpeta del proyecto, esté
> donde esté en tu Mac. Ningún paso usa rutas fijas de una computadora concreta.

---

## 0. Comprobar las herramientas

```bash
cd medflow           # entra a la carpeta del proyecto (ajusta el camino si hace falta)
bash scripts/verificar-entorno.sh
```

**Qué deberías ver:** una lista con la versión de cada herramienta y un ✅ o ⚠️ al lado.
El script **solo lee** versiones: no instala ni cambia nada.

Necesitas:

| Herramienta | Versión mínima | Para qué |
|---|---|---|
| Python | 3.11 | backend (API) |
| Node.js y npm | Node 20 | compilar la interfaz |
| PostgreSQL | 14 (recomendado 16) | base de datos |
| Git | cualquiera reciente | control de versiones |

### Sobre Homebrew en el M1

En el M1, `brew` responde desde `/usr/local/bin/brew`, pero `~/.zprofile` intenta cargar
`/opt/homebrew/bin/brew`, que no existe. **Nordeste no necesita Homebrew**, así que puedes
dejarlo como está. Si más adelante quieres ordenarlo, conviene revisarlo con calma, en una
sesión aparte, antes de cambiar nada.

---

## 1. Instalar PostgreSQL (una vez por Mac)

Recomendación: **Postgres.app**, que no depende de Homebrew y funciona igual en M1 e Intel.

1. Descárgalo de <https://postgresapp.com/>. Antes de instalarlo, comprueba en esa página
   qué versión de macOS pide; la Mac Intel tiene **macOS Monterey (12)**.
2. Arrástralo a *Aplicaciones*, ábrelo y pulsa **Initialize**. Debería mostrar
   “Running” en el puerto 5432.
3. Para que la Terminal encuentre `psql`, sigue la sección “Configure your $PATH” de la
   página de Postgres.app. Después cierra y vuelve a abrir la Terminal.

**Comprobación:** `psql --version` debe mostrar una versión, por ejemplo `psql (PostgreSQL) 16.x`.

### Crear el usuario y las bases de Nordeste

**Forma rápida (recomendada):** desde la carpeta `medflow`, con Postgres.app en “Running”:

```bash
bash scripts/crear-base-local.sh
```

Crea el usuario `medflow` con una contraseña aleatoria (no se muestra), las bases
`medflow` y `medflow_test`, y el archivo `backend/.env`. Si ya existe `backend/.env`, no
cambia nada. **Qué deberías ver:** tres líneas con ✅ y “Archivo backend/.env creado”.
Si usaste esta forma, en el paso 2 sáltate la parte de copiar y editar `.env`.

**Forma manual** (equivalente):

Elige una contraseña **solo para tu base local** y no reutilices ninguna real.
En los comandos de abajo, reemplaza `TU_CLAVE_LOCAL` por esa contraseña.

```bash
psql -d postgres
```

Se abre el intérprete de PostgreSQL (verás `postgres=#`). Escribe una línea a la vez:

```sql
CREATE ROLE medflow LOGIN PASSWORD 'TU_CLAVE_LOCAL';
CREATE DATABASE medflow OWNER medflow;
CREATE DATABASE medflow_test OWNER medflow;
\q
```

**Qué deberías ver:** `CREATE ROLE`, `CREATE DATABASE` y `CREATE DATABASE`.
`medflow` es la base que usas; `medflow_test` es la de las pruebas automáticas, que la vacían.

---

## 2. Configurar y arrancar el backend (API)

```bash
cd medflow/backend
python3 --version                 # debe ser 3.11 o superior
python3 -m venv .venv             # crea un entorno aislado para las librerías
source .venv/bin/activate         # lo activa (verás "(.venv)" al inicio de la línea)
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

> **Si `python3 --version` muestra una versión menor a 3.11** (por ejemplo la 3.9 que trae
> macOS), usa el nombre con la versión, si la tienes instalada: `python3.13 -m venv .venv`
> (o `python3.12`, `python3.11`). Una vez activado el entorno, `python` ya será esa versión.

**Qué deberías ver:** varias líneas de descarga y, al final,
`Successfully installed ...`.

Crea tu archivo de configuración a partir del ejemplo:

```bash
cp .env.example .env
open -e .env
```

En el editor, reemplaza las **dos** apariciones de `cambia-esta-clave-local` por
`TU_CLAVE_LOCAL` y guarda. `.env` está en `.gitignore`, así que **nunca se sube a GitHub**.

Crea las tablas (migraciones) y la clínica con sus sucursales:

```bash
alembic upgrade head
python -m app.instalar_clinica
```

**Qué deberías ver:** primero las líneas `Running upgrade …` y después
`✅ Centro Interdisciplinario Nordeste creada con las sucursales Central, Anexo, Pando.`, con el
correo de Administración y una **contraseña temporal** (anótala: no se vuelve a mostrar). No
se cargan datos de demostración: las demás cuentas se crean desde *Usuarios*.

Arranca la API:

```bash
uvicorn app.main:app --reload --no-access-log
```

Los **archivos adjuntos** de los pacientes se guardan en `backend/storage/files` (se crea
sola; está excluida de Git). Para usar otra carpeta, define `FILES_DIR` en `.env`.

**Qué deberías ver:** `Uvicorn running on http://127.0.0.1:8000`. Deja esta Terminal abierta.
(`--no-access-log` evita que las búsquedas por nombre queden escritas en la Terminal.)

---

## 3. Compilar la interfaz (frontend)

Abre **otra** ventana de Terminal (⌘N):

```bash
cd medflow/frontend
npm install
npm run build
```

**Qué deberías ver:** `added N packages` y luego `Interfaz compilada en frontend/dist.`

> Con npm 11 o superior puede aparecer el aviso *install-scripts ... esbuild*. La compilación
> suele funcionar igual. Si `npm run build` da un error de esbuild, ejecuta
> `npm install-scripts approve esbuild && npm rebuild esbuild` y vuelve a compilar.

Vuelve a la Terminal del backend, detenlo con **Ctrl+C** y arráncalo de nuevo con el mismo
comando `uvicorn ...`, para que tome la interfaz recién compilada.

Abre <http://localhost:8000> en el navegador. Debería aparecer la pantalla de inicio de sesión.

### Mientras programas la interfaz

`npm run dev` recompila automáticamente cada vez que guardas un archivo de `frontend/src`.
Para ver los cambios, recarga el navegador.

---

## 4. Uso diario (después de la primera vez)

Terminal 1:
```bash
bash ~/Developer/medflow/scripts/iniciar.sh   # ajusta la ruta si el proyecto está en otra carpeta
```

El script se ubica solo en `backend`, activa el entorno virtual y arranca el servidor. Si
falta compilar la interfaz o el puerto 8000 está ocupado, lo avisa y explica qué hacer.

> Si arrancas `uvicorn` a mano, hazlo **desde la carpeta `backend`**. Desde otra carpeta
> aparece `No module named 'app'`.

Terminal 2 (solo si cambias la interfaz):
```bash
cd medflow/frontend && npm run dev
```

**Cuando el proyecto trae cambios en la base de datos** (una migración nueva en
`backend/migrations/versions`), o después de un `git pull`, ejecuta en `backend`, con el
entorno virtual activo:

```bash
alembic upgrade head
```

**Qué deberías ver:** una línea `Running upgrade ... -> ...` por cada migración nueva, o nada
nuevo si ya estaba al día (`alembic current` debe mostrar `(head)`). Las migraciones
conservan tus datos.

Y en `frontend`: `npm install && npm run build`.

---

## 4 bis. Copias de seguridad

Guardan **la base de datos y los archivos adjuntos** en un solo archivo, en la carpeta
`~/MedFlow-copias` (fuera del proyecto, así nunca se sube a GitHub).

```bash
bash ~/Developer/medflow/scripts/copia-seguridad.sh
```

**Qué deberías ver:** `✅ Copia creada: /Users/…/MedFlow-copias/medflow-copia-FECHA.tar.gz`
con el tamaño y cuántos pacientes contiene. Puedes hacerlo con Nordeste encendido.

Una copia que nunca se probó no es confiable. Para comprobar que se puede restaurar:

```bash
bash ~/Developer/medflow/scripts/copia-seguridad.sh verificar
```

Restaura la última copia en la base de **pruebas** (`medflow_test`), cuenta las filas, las
compara y deja esa base vacía. **No toca tus datos.** Deberías ver
`✅ La copia está completa y se restauró bien…`.

Para **volver** Nordeste al estado de una copia (por ejemplo, después de un error grave):

1. Detén Nordeste (Ctrl + C en su Terminal).
2. Ejecuta, con el nombre real del archivo:
   ```bash
   bash ~/Developer/medflow/scripts/copia-seguridad.sh restaurar ~/MedFlow-copias/medflow-copia-FECHA.tar.gz
   ```
3. Escribe `RESTAURAR` cuando lo pida. Antes de reemplazar nada guarda una copia del estado
   actual (`medflow-antes-de-restaurar-…`) y aparta los adjuntos actuales sin borrarlos.
4. Ejecuta `alembic upgrade head` y vuelve a iniciar Nordeste.

### Copias automáticas cada día

Para que la Mac haga la copia sola todos los días (por defecto a las 22:00):

```bash
bash ~/Developer/medflow/scripts/copias-automaticas.sh instalar
```

**Qué deberías ver:** `✅ Copia automática activada: todos los días a las 22:00.` Para otra
hora, agrégala al final (por ejemplo `instalar 13:30`). Se conservan las 30 copias más
recientes; las de "antes de restaurar" nunca se borran.

* Si a esa hora la Mac está **dormida**, la copia se hace al despertarla; si está **apagada**,
  ese día se saltea. Postgres.app tiene que estar abierto.
* Ver si está activa y el resultado de la última: `bash ~/Developer/medflow/scripts/copias-automaticas.sh estado`
* Probarla en el momento: el comando `launchctl kickstart …` que muestra al instalar.
* Desactivarla (no borra copias): `bash ~/Developer/medflow/scripts/copias-automaticas.sh desinstalar`

**Importante:** las copias contienen datos de pacientes. Guárdalas en un disco cifrado
(FileVault activado o un disco externo cifrado) y ten al menos una copia fuera de la
computadora. Si quieres otra carpeta, define `BACKUP_DIR` en `backend/.env`.

## 4 ter. Sucursales

Al actualizar la base (`alembic upgrade head`), Nordeste crea la sucursal **Central** y le
asigna todas las cuentas existentes. Para agregar otras (por ejemplo Pando y Anexo):

1. Entra como administración → **Usuarios** → tarjeta **Sucursales** → escribe el nombre →
   **Agregar**.
2. En cada cuenta, **Editar** → marca las sucursales donde trabaja → **Guardar cambios**.
   Administración no necesita: entra a todas.

Quien tiene una sola sucursal entra directo; quien tiene varias elige al entrar y puede
cambiar desde el encabezado.

Con la migración `0013_paciente_sucursal`, **todos los pacientes que ya existían quedan en
Central**. Si alguno pertenece a otra sucursal, cámbialo desde su ficha (**Editar datos** →
**Sucursal**), o vuelve a importarlo con la columna `sucursal`.

Con la migración `0014_agenda_sucursal`, los **horarios de disponibilidad que ya existían
quedan en Central**, y los turnos también (salvo los de pacientes de AYEX, Tutela Militar o Tutela Policial,
que quedan en la sucursal del paciente). Para un profesional que atiende en otra sucursal:

1. Entra a **Central** → **Agenda** → elige al profesional → en **Disponibilidad semanal**,
   **Quitar** los horarios que en realidad son de la otra sucursal.
2. Cambia a la otra sucursal desde el encabezado → **Agenda** → agrega esos horarios allí.

El profesional tiene que tener esa sucursal marcada en **Usuarios**.

## 4 quater. Mostrarlo en otros equipos de la misma red (demostración)

Para probar Nordeste desde otra computadora, tablet o celular **conectado al mismo Wi-Fi** que
tu Mac (por ejemplo, recepción en un equipo y un profesional en otro):

1. Detén Nordeste si está encendido (`Control + C` en su Terminal).
2. Arráncalo en modo red:

   ```bash
   bash scripts/iniciar-red.sh
   ```

   Verás una dirección como `http://192.168.1.20:8000`. Si macOS pregunta si permitir
   conexiones entrantes, elige **Permitir**.
3. En el otro equipo, abre esa dirección en el navegador y entra con una cuenta.
4. Al terminar, `Control + C`: los demás equipos dejan de poder entrar. Para el uso normal
   vuelve a `bash scripts/iniciar.sh` (solo esta Mac).

**Cuidados:** úsalo solo con **datos ficticios**. Dentro de la red la conexión no va cifrada
(`http`, sin "s"), y cualquiera conectado a ese Wi-Fi puede llegar a la pantalla de ingreso: no
lo uses en un Wi-Fi público ni en el de pacientes. Si la dirección no abre, revisa que los dos
equipos estén en el mismo Wi-Fi y que el firewall de la Mac (Ajustes del Sistema → Red →
Firewall) permita conexiones a Python. La dirección puede cambiar de un día a otro: el script
siempre muestra la actual.

## 5. Pasar de una Mac a la otra

Lo que viaja por Git: el código, las migraciones, `.env.example` y la documentación.
Lo que **no** viaja y se crea en cada Mac: `backend/.venv`, `backend/.env`,
`frontend/node_modules`, `frontend/dist` y la base de datos local.

En la segunda Mac, repite los pasos 1 a 3. Cada base local tiene sus propios datos ficticios.

---

## 6. Solución de problemas

| Síntoma | Causa probable | Paso sugerido |
|---|---|---|
| `command not found: psql` | La Terminal no encuentra Postgres.app | Configura el `$PATH` (paso 1.3) y abre una Terminal nueva |
| `connection refused` o `could not connect to server` | PostgreSQL no está iniciado | Abre Postgres.app y verifica “Running” |
| `password authentication failed for user "medflow"` | La clave de `.env` no coincide con la de `CREATE ROLE` | Corrige `DATABASE_URL` y `TEST_DATABASE_URL` en `.env` |
| `Field required ... database_url` | Falta `backend/.env` | `cp .env.example .env` y completa la clave |
| `No module named 'fastapi'` (u otro) | El entorno virtual no está activo | `source .venv/bin/activate` dentro de `backend` |
| `python3: command not found`, o una versión menor a 3.11 | Falta Python 3.11 o superior | Instálalo desde python.org y repite el paso 2 |
| `address already in use` en el puerto 8000 | Ya hay un backend abierto | Ciérralo con Ctrl+C en la otra Terminal |
| `No module named 'app'` al arrancar | `uvicorn` se ejecutó fuera de `backend` | Usa `bash scripts/iniciar.sh`, o entra a `backend` antes |
| La página dice “falta compilar la interfaz” | No existe `frontend/dist` | `npm run build` y reinicia el backend |
| `npm: command not found` | Falta Node.js | Instala la versión LTS desde nodejs.org |
| No puedes iniciar sesión tras varios intentos | Bloqueo de 15 minutos tras 5 fallos | Espera 15 minutos, o pide a Administración que restablezca la contraseña |
| Un turno da “fuera de la disponibilidad” | La hora no cae en un bloque de disponibilidad | Revisa la disponibilidad del profesional en Agenda |
