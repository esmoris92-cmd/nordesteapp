"""Editor de textos de la página promocional (sitio/index.html).

Abre un servidor solo en esta Mac (http://localhost:8765) que muestra la página y deja
cambiar sus textos con un clic, sin tocar el código. Al guardar, cambia únicamente los
textos editados dentro de sitio/index.html: las etiquetas, estilos y scripts quedan igual.

Se abre con:  bash scripts/editar-pagina.sh
Usa solo Python (sin instalar nada).
"""
import hashlib
import html
import json
import os
import re
import sys
import webbrowser
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
PAGINA = os.path.join(RAIZ, "sitio", "index.html")
EDITOR = os.path.join(AQUI, "editor.html")
PUERTO = int(os.environ.get("LUMEN_EDITOR_PUERTO", "8765"))

# Partes de la página que no son texto para leer.
SIN_TEXTO = {"script", "style", "svg", "head", "title", "textarea", "noscript"}
VACIAS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
          "source", "track", "wbr"}

# Textos de la cabecera (no se ven en la página) que se editan en el panel lateral.
# clave: (expresión regular con un grupo para el valor, cómo se guarda)
META = {
    "titulo": (r"<title>(.*?)</title>", "html"),
    "descripcion": (r'<meta name="description" content="(.*?)">', "attr"),
    "og_titulo": (r'<meta property="og:title" content="(.*?)">', "attr"),
    "og_descripcion": (r'<meta property="og:description" content="(.*?)">', "attr"),
    "og_imagen_alt": (r'<meta property="og:image:alt" content="(.*?)">', "attr"),
    "whatsapp_numero": (r'const WHATSAPP_NUMERO = "(\d*)";', "numero"),
    "whatsapp_mensaje": (r'const WHATSAPP_MENSAJE = "((?:[^"\\]|\\.)*)";', "js"),
}


def leer():
    with open(PAGINA, encoding="utf-8") as f:
        return f.read()


def huella(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


class Textos(HTMLParser):
    """Encuentra los textos visibles del cuerpo de la página y dónde están en el archivo."""

    def __init__(self, fuente):
        super().__init__(convert_charrefs=True)
        self.fuente = fuente
        self.inicios = [0]
        for i, c in enumerate(fuente):
            if c == "\n":
                self.inicios.append(i + 1)
        self.pila = []
        self.en_cuerpo = False
        self.tramos = []  # (inicio, fin) del texto sin los espacios de alrededor

    def _pos(self):
        linea, col = self.getpos()
        return self.inicios[linea - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.en_cuerpo = True
        if tag not in VACIAS:
            self.pila.append(tag)

    def handle_endtag(self, tag):
        if tag in VACIAS:
            return
        while self.pila:
            if self.pila.pop() == tag:
                break

    def handle_data(self, data):
        if not self.en_cuerpo or not data.strip() or any(t in SIN_TEXTO for t in self.pila):
            return
        inicio = self._pos()
        fin = self.fuente.find("<", inicio)
        if fin == -1:
            fin = len(self.fuente)
        crudo = self.fuente[inicio:fin]
        izq = len(crudo) - len(crudo.lstrip())
        der = len(crudo.rstrip())
        if der > izq:
            self.tramos.append((inicio + izq, inicio + der))


def tramos_de_texto(fuente):
    p = Textos(fuente)
    p.feed(fuente)
    p.close()
    return p.tramos


def leer_meta(fuente):
    valores = {}
    for clave, (patron, tipo) in META.items():
        m = re.search(patron, fuente, re.S)
        if not m:
            continue
        v = m.group(1)
        if tipo in ("html", "attr"):
            v = html.unescape(v)
        elif tipo == "js":
            v = json.loads('"' + v + '"')
        valores[clave] = v
    return valores


def escribir_meta(fuente, clave, valor):
    patron, tipo = META[clave]
    valor = valor.replace("\r", " ").replace("\n", " ").strip()
    if tipo == "html":
        nuevo = html.escape(valor, quote=False)
    elif tipo == "attr":
        nuevo = html.escape(valor, quote=True)
    elif tipo == "numero":
        if not re.fullmatch(r"\d{8,15}", valor):
            raise ValueError("El número de WhatsApp va solo con números, con el 598 adelante y sin el 0 del celular (por ejemplo 59891090708).")
        nuevo = valor
    else:  # js
        nuevo = json.dumps(valor, ensure_ascii=False)[1:-1].replace("</", "<\\/")
    m = re.search(patron, fuente, re.S)
    if not m:
        raise ValueError("No encontré «%s» en la página." % clave)
    return fuente[:m.start(1)] + nuevo + fuente[m.end(1):]


AYUDANTE = """
<style>
  *, *::before, *::after { animation: none !important; transition: none !important; }
  lumen-t { cursor: text; border-radius: 3px; outline: 1px dashed transparent; outline-offset: 2px; }
  lumen-t:hover { outline-color: rgba(23,103,200,.55); background: rgba(23,103,200,.06); }
  lumen-t:focus { outline: 2px solid #1767c8; background: rgba(23,103,200,.08); }
  lumen-t.cambiado { background: rgba(255, 214, 102, .55); }
  lumen-t:empty { display: inline-block; min-width: 1.2em; outline: 1px dashed #c2413b; }
  .top { position: static !important; }
  .float-wa { display: none !important; }
</style>
"""


def pagina_para_editar(fuente):
    """La página con cada texto envuelto en <lumen-t data-id="N"> y sin sus scripts."""
    partes, ultimo = [], 0
    for n, (a, b) in enumerate(tramos_de_texto(fuente)):
        partes.append(fuente[ultimo:a])
        partes.append('<lumen-t data-id="%d">%s</lumen-t>' % (n, fuente[a:b]))
        ultimo = b
    partes.append(fuente[ultimo:])
    copia = "".join(partes)
    copia = re.sub(r"<script\b(?![^>]*\bsrc=)[^>]*>.*?</script>", "", copia, flags=re.S)
    return copia.replace("</body>", AYUDANTE + "</body>", 1)


def guardar(datos):
    fuente = leer()
    if datos.get("huella") != huella(fuente):
        return 409, {"error": "La página cambió desde que la abriste (quizás la editaste en otro lado). Tocá «Volver a cargar»: se pierden los cambios sin guardar."}
    tramos = tramos_de_texto(fuente)
    cambios = datos.get("textos") or {}
    reemplazos = []
    for clave, texto in cambios.items():
        n = int(clave)
        if not 0 <= n < len(tramos):
            return 400, {"error": "Hay un texto que no reconozco. Volvé a cargar el editor."}
        texto = " ".join(str(texto).split())  # sin saltos de línea ni espacios dobles
        reemplazos.append((tramos[n], html.escape(texto, quote=False)))
    nuevo = fuente
    for (a, b), texto in sorted(reemplazos, key=lambda r: r[0][0], reverse=True):
        nuevo = nuevo[:a] + texto + nuevo[b:]
    try:
        actuales = leer_meta(nuevo)
        for clave, valor in (datos.get("meta") or {}).items():
            if clave in META and valor != actuales.get(clave):
                nuevo = escribir_meta(nuevo, clave, str(valor))
    except ValueError as e:
        return 400, {"error": str(e)}
    if nuevo != fuente:
        temporal = PAGINA + ".guardando"
        with open(temporal, "w", encoding="utf-8") as f:
            f.write(nuevo)
        os.replace(temporal, PAGINA)
    return 200, {"ok": True, "huella": huella(nuevo), "cambios": len(reemplazos)}


class Manejador(BaseHTTPRequestHandler):
    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        if not isinstance(cuerpo, bytes):
            cuerpo = (json.dumps(cuerpo, ensure_ascii=False) if tipo.startswith("application/json") else cuerpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _local(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("localhost", "127.0.0.1")

    def do_GET(self):
        if not self._local():
            return self._responder(403, {"error": "Solo desde esta Mac."})
        ruta = self.path.split("?")[0]
        if ruta == "/":
            with open(EDITOR, encoding="utf-8") as f:
                return self._responder(200, f.read(), "text/html; charset=utf-8")
        if ruta == "/pagina":
            return self._responder(200, pagina_para_editar(leer()), "text/html; charset=utf-8")
        if ruta == "/estado":
            fuente = leer()
            return self._responder(200, {"huella": huella(fuente), "meta": leer_meta(fuente)})
        self._responder(404, {"error": "No existe."})

    def do_POST(self):
        if not self._local() or self.path != "/guardar":
            return self._responder(403, {"error": "No permitido."})
        largo = int(self.headers.get("Content-Length") or 0)
        try:
            datos = json.loads(self.rfile.read(largo).decode("utf-8"))
        except ValueError:
            return self._responder(400, {"error": "No entendí lo que mandó el editor."})
        codigo, respuesta = guardar(datos)
        self._responder(codigo, respuesta)

    def log_message(self, *args):
        pass


def main():
    if not os.path.isfile(PAGINA):
        sys.exit("No encuentro sitio/index.html. Corré el editor desde la carpeta del proyecto.")
    try:
        servidor = HTTPServer(("127.0.0.1", PUERTO), Manejador)
    except OSError:
        sys.exit("El puerto %d está ocupado: quizás el editor ya está abierto en otra ventana de la Terminal." % PUERTO)
    url = "http://localhost:%d" % PUERTO
    print("✏️  Editor de la página abierto en %s" % url)
    print("   Los cambios se guardan en sitio/index.html (todavía no se publican).")
    print("   Para cerrar el editor: volvé a esta ventana y tocá Control + C.")
    if os.environ.get("LUMEN_EDITOR_SIN_NAVEGADOR") != "1":
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n   Editor cerrado.")


if __name__ == "__main__":
    main()
