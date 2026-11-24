# Nordeste en un servidor (prueba en DigitalOcean)

Esta guía instala Nordeste en un servidor en internet, con conexión segura (HTTPS), para
**probarlo con datos ficticios** desde las sucursales. Al terminar, el servidor se elimina
para que no siga cobrando.

> **Solo datos ficticios.** Para usarlo con pacientes reales falta: elegir proveedor y
> región con el asesor de protección de datos, un dominio propio, copias de seguridad fuera
> del servidor y crear las cuentas reales (sin los datos de demostración).

## Qué hace cada script

| Script | Dónde se ejecuta | Qué hace |
|---|---|---|
| `scripts/servidor/desplegar.sh` | En tu Mac | Compila la interfaz, arma un paquete con el código guardado en Git (nunca `.env`, copias ni archivos de pacientes), lo envía al servidor y ejecuta el instalador |
| `scripts/servidor/instalar.sh` | En el servidor (lo ejecuta el anterior) | Instala PostgreSQL, Python y Caddy; crea la base con una contraseña al azar; deja Nordeste como servicio que se reinicia solo; activa HTTPS automático y un cortafuegos (solo puertos 22, 80 y 443) |

## 1. Una llave SSH en tu Mac (una sola vez)

SSH es la forma segura de conectarse al servidor. En lugar de una contraseña, usa una
"llave" guardada en tu Mac. Primero fíjate si ya tienes una:

```bash
ls ~/.ssh/id_ed25519.pub
```

* Si muestra la ruta del archivo, ya la tienes: sigue al paso de copiarla.
* Si dice "No such file or directory", créala:

  ```bash
  ssh-keygen -t ed25519 -C "medflow"
  ```

  Pulsa Enter para aceptar la ubicación. Te pide una **frase de contraseña** (passphrase):
  elige una y no la olvides (al escribirla no se ve nada; es normal).

Copia la parte **pública** de la llave (la que se puede compartir) al portapapeles:

```bash
pbcopy < ~/.ssh/id_ed25519.pub
```

No se ve nada: ya quedó copiada. **Nunca** compartas el archivo sin `.pub`: esa es la parte
privada.

## 2. Crear el servidor (Droplet) en DigitalOcean

1. En el panel: **Create → Droplets**.
2. **Region**: Frankfurt o Amsterdam (Europa: cumple con la lista de países de la URCDP).
3. **Image**: **Ubuntu 24.04 (LTS) x64**. Importante elegir la 24.04.
4. **Size**: *Basic → Regular* → el de **1 GB** de memoria (no el de 512 MB, que se queda corto).
5. **Authentication**: **SSH Key → New SSH Key** → pega (`Cmd + V`) la llave copiada → nombre
   "Mi Mac" → **Add SSH Key**.
6. **Hostname**: `medflow-prueba`.
7. **Create Droplet**. En un minuto aparece con su **IP** (por ejemplo `164.90.123.45`):
   cópiala.

**Recomendado:** *Settings → Billing → Billing alerts* y pon un aviso, por ejemplo, de USD 5.

## 3. Instalar Nordeste (desde tu Mac)

```bash
cd ~/Developer/nordesteapp && bash scripts/servidor/desplegar.sh 164.90.123.45
```

(con la IP de tu servidor; si ya hay dominio apuntando a esa IP, agrégalo al final, por
ejemplo `... 164.90.123.45 app.nordeste.com.uy`). Qué vas a ver:

* "Are you sure you want to continue connecting (yes/no)?" → escribe `yes` (solo la primera vez).
* Te pide la frase de contraseña de tu llave SSH (dos veces: al enviar y al instalar).
* Los pasos `1/8` a `8/8`; la instalación tarda unos minutos.
* La primera vez crea la clínica **Centro Interdisciplinario Nordeste** con las sucursales
  **Central, Anexo y Pando** y la primera cuenta de **Administración**. Al final muestra:

  ```
  ✅ Nordeste está funcionando en:   https://164-90-123-45.sslip.io
     Primera cuenta de Administración (anotala; no se vuelve a mostrar):
     Administración:       administracion@nordeste.example.com
     Contraseña temporal:  …
  ```

`sslip.io` es un servicio gratuito que da un nombre a la IP para poder tener HTTPS.

El correo de Administración es **provisorio**: cámbialo desde *Usuarios* por el real de la
clínica. Nunca se cargan datos de demostración.

## 4. Primeros pasos en la clínica

1. Entra con la cuenta de Administración y la contraseña temporal; elige una nueva.
2. *Usuarios*: crea las cuentas de Recepción (una por sucursal) y de cada profesional, y
   asígnales sus sucursales.
3. *Clínica*: carga el logo, teléfono, dirección y los datos del BPS.

Para actualizar el servidor con cambios nuevos (después de guardarlos en Git), repite el
mismo comando o usa `scripts/servidor/actualizar.sh` (pide `NORDESTE_SSH` y `NORDESTE_SITIO`):
conserva la base, los archivos y la configuración.

## Dueño del sistema (pantalla /sistema)

Es la pantalla para manejar las clínicas desde afuera: dar de alta una clínica nueva con su
primer administrador, suspender o reactivar el acceso de una clínica y darle una contraseña
temporal a un administrador que perdió la suya. **No muestra pacientes ni historia clínica**:
de cada clínica solo cantidades y sus cuentas de Administración.

- Dirección: `https://<dominio>/sistema` (en la Mac: `http://localhost:8000/sistema`).
- Pide correo, contraseña y un **código de 6 dígitos** de una app del celular (Google
  Authenticator o Microsoft Authenticator).
- La cuenta no se crea desde la pantalla: se crea con un comando, desde la Mac.

Crear la cuenta en el servidor (después de actualizar con `actualizar.sh`):

```
bash scripts/servidor/dueno-sistema.sh crear --correo tu@correo.com --nombre "Tu Nombre"
```

Muestra una **contraseña temporal** (una sola vez). Con ella entrás a `/sistema`, elegís una
contraseña nueva y configurás la app del celular.

Si perdés el celular o la contraseña:

```
bash scripts/servidor/dueno-sistema.sh restablecer --correo tu@correo.com
```

Da otra contraseña temporal y borra el código del celular para configurarlo de nuevo.
`listar` muestra las cuentas de dueño. Para probar en la Mac, los mismos comandos con
`bash scripts/dueno-sistema.sh ...`.

## Copias de seguridad del servidor

Si la VPS se borra o se rompe, la base y los archivos adjuntos se pierden con ella. Por eso:

1. **Todas las noches (03:00)** el servidor hace una copia (base + adjuntos) y conserva las
   últimas 14 en `/opt/medflow/copias`. Lo deja configurado `actualizar.sh`.
   Revisarla en el servidor: `systemctl list-timers lumen-copia.timer` y
   `journalctl -u lumen-copia -n 30`.
2. **Una Mac baja la copia cada día** y conserva las últimas 30 en `~/Nordeste-copias-servidor`.
   Esa es la copia que sirve si se pierde la VPS. La Mac tiene que tener **FileVault** activado
   (las copias tienen datos de pacientes).

Para eso existe en el servidor la cuenta `lumencopia`: no tiene contraseña y su llave solo
puede listar y bajar copias (no abre una terminal ni puede cambiar nada).

En la Mac que guarda las copias (una sola vez):

```
bash scripts/servidor/copias-del-servidor.sh preparar     # crea la llave y la autoriza (pide la contraseña del servidor)
bash scripts/servidor/copias-del-servidor.sh bajar        # baja la copia más reciente ahora
bash scripts/servidor/copias-del-servidor.sh instalar     # la baja sola todos los días a las 21:00
bash scripts/servidor/copias-del-servidor.sh verificar    # prueba restaurar la última en la base de pruebas
```

`estado` muestra si está activa y la última copia; `desinstalar` la apaga (no borra copias).
Si la Mac está dormida a esa hora, la baja al despertarse; si está apagada, ese día se saltea.
Si la copia más nueva del servidor tiene 2 días o más, el registro lo avisa.

## Si algo falla

| Mensaje | Qué hacer |
|---|---|
| `Permission denied (publickey)` | La llave no se agregó al Droplet. Revisa el paso 2.5, o crea el Droplet de nuevo con la llave. |
| `Connection refused` / `timed out` | El Droplet todavía está arrancando: espera un minuto y repite. Revisa la IP. |
| "el HTTPS todavía no respondió" | Espera 2 minutos y abre la dirección. Si sigue sin abrir, conéctate con `ssh root@LA-IP` y revisa `journalctl -u caddy -n 30` y `journalctl -u medflow -n 30`. |
| "Este script está pensado para Ubuntu 24.04" | Elegiste otra versión: elimina el Droplet y créalo con Ubuntu 24.04. |
