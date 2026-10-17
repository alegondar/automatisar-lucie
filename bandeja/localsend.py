"""Emisor LocalSend v2: descubrimiento, aceptación y envío con SHA-256.

Referencia: https://github.com/localsend/protocol (v2.2).
Solo se conecta a direcciones IP locales elegidas desde el dashboard.
"""
import hashlib
import http.client
import functools
import io
import ipaddress
import json
import mimetypes
import logging
import uuid
import os
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode
from bandeja.red_local import interfaces_locales, buscar_puerto_lucie


logger = logging.getLogger(__name__)
PUERTO_LUCIE = 53318
PUERTO_DESCUBRIMIENTO_LUCIE = 53319
PUERTO_LOCALSEND = 53317
GRUPO_DESCUBRIMIENTO = "224.0.0.167"


def tipo_receptor(dispositivo):
    """Identifica la app anunciada; la identidad criptográfica se verifica aparte."""
    if dispositivo.get("receptor") in ("lucie", "localsend"):
        return dispositivo["receptor"]
    return "lucie" if (dispositivo.get("port") == PUERTO_LUCIE and
                        str(dispositivo.get("alias", "")).startswith("Lucie Recibir")) else "localsend"


def validar_receptor(receptor):
    if receptor not in (None, "lucie", "localsend"):
        raise ValueError("Elegí Lucie Recibir o LocalSend.")


class _LecturaCancelable(io.RawIOBase):
    """Sondea la cancelación sin depender de shutdown entre hilos de Windows."""
    def __init__(self, sock, propietario, cancelar):
        super().__init__()
        self.sock = sock
        self.propietario = propietario
        self.cancelar = cancelar
        self.timeout_original = sock.gettimeout()
        self.vence = time.monotonic() + (self.timeout_original or 90)

    def readable(self):
        return True

    def readinto(self, buffer):
        while True:
            if self.cancelar.is_set():
                raise OSError("Envío cancelado.")
            restante = self.vence - time.monotonic()
            if restante <= 0:
                raise TimeoutError("El receptor no respondió a tiempo.")
            self.sock.settimeout(min(0.1, restante))
            try:
                return self.sock.recv_into(buffer)
            except socket.timeout:
                continue

    def close(self):
        try:
            if not self.closed:
                try:
                    self.sock.settimeout(self.timeout_original)
                except OSError:
                    pass
            self.propietario.close()
        finally:
            super().close()


class _RespuestaCancelable(http.client.HTTPResponse):
    def __init__(self, sock, *args, cancelar, **kwargs):
        super().__init__(sock, *args, **kwargs)
        # Conservar el makefile original como propietario del descriptor: los
        # servidores HTTP/1.0 pueden cerrar HTTPConnection antes de leer el cuerpo.
        self.fp = io.BufferedReader(_LecturaCancelable(sock, self.fp, cancelar))


class ErrorLocalSend(ValueError):
    """Diagnóstico sin PIN, tokens, nombres personales ni contenido."""
    def __init__(self, mensaje, etapa, codigo_http=None):
        super().__init__(mensaje)
        self.etapa = etapa
        self.codigo_http = codigo_http
        self.cancelacion_confirmada = None


def validar_destino(ip, puerto):
    direccion = ipaddress.ip_address(str(ip))
    if direccion.version != 4 or not direccion.is_private or direccion.is_unspecified or direccion.is_multicast:
        raise ValueError("Usá la dirección IPv4 local del celular conectado a tu Wi-Fi.")
    if type(puerto) is not int or not 1 <= puerto <= 65535:
        raise ValueError("Puerto del receptor inválido.")
    return str(direccion)


class ClienteLocalSend:
    def __init__(self):
        self.huella = secrets.token_hex(32)

    def info(self, puerto=PUERTO_LUCIE):
        return {"alias": "Lucie - Dashboard", "version": "2.0", "deviceModel": "Lucie",
                "deviceType": "desktop", "fingerprint": self.huella, "port": puerto,
                "protocol": "http", "download": False}

    def _conexion(self, dispositivo, timeout=15, comprobar=True):
        ip = validar_destino(dispositivo["ip"], dispositivo["port"])
        protocolo = dispositivo["protocol"]
        if protocolo == "https":
            # LocalSend usa certificados propios. Se fija su huella, no se acepta
            # silenciosamente un certificado distinto después de elegir receptor.
            contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            contexto.check_hostname = False
            contexto.verify_mode = ssl.CERT_NONE
            con = http.client.HTTPSConnection(ip, dispositivo["port"], timeout=timeout, context=contexto)
            con.connect()
            huella = hashlib.sha256(con.sock.getpeercert(binary_form=True)).hexdigest()
            if comprobar and huella != dispositivo.get("fingerprint", "").lower().replace(":", ""):
                con.close()
                raise ValueError("Cambió la identidad del celular. Buscalo nuevamente antes de enviar.")
            return con, huella
        if protocolo != "http":
            raise ValueError("Protocolo del receptor inválido.")
        return http.client.HTTPConnection(ip, dispositivo["port"], timeout=timeout), None

    @staticmethod
    def _leer_json(respuesta, etapa="respuesta", aceptar_sin_cuerpo=False):
        datos = respuesta.read(65537)
        if len(datos) > 65536:
            raise ValueError("Respuesta del receptor demasiado grande.")
        if aceptar_sin_cuerpo and respuesta.status == 204:
            return {}
        if respuesta.status != 200:
            mensajes = {401: "El celular solicita un PIN o el PIN no coincide.",
                        403: "El celular rechazó el envío.", 409: "El celular está ocupado con otro envío.",
                        422: "El receptor rechazó la integridad del archivo."}
            mensaje = mensajes.get(respuesta.status, f"El receptor respondió HTTP {respuesta.status}.")
            if etapa == "preparacion" and respuesta.status == 204:
                mensaje = "El receptor terminó la preparación sin aceptar archivos; no hay recepción confirmada."
            raise ErrorLocalSend(mensaje, etapa, respuesta.status)
        resultado = json.loads(datos) if datos else {}
        if not isinstance(resultado, dict):
            raise ValueError("Respuesta LocalSend inválida.")
        return resultado

    def probar(self, ip, puerto=PUERTO_LUCIE, protocolo=None, timeout=3):
        validar_destino(ip, puerto)
        errores = []
        for modo in ([protocolo] if protocolo else ["https", "http"]):
            dispositivo = {"ip": ip, "port": puerto, "protocol": modo}
            con = None
            try:
                con, huella = self._conexion(dispositivo, timeout=timeout, comprobar=False)
                con.request("GET", "/api/localsend/v2/info")
                datos = self._leer_json(con.getresponse())
                if not str(datos.get("version", "")).startswith("2.") or not datos.get("alias"):
                    raise ValueError("El dispositivo no ofrece un receptor LocalSend v2.")
                dispositivo.update(alias=str(datos["alias"])[:100],
                                   fingerprint=huella or str(datos.get("fingerprint", "")))
                dispositivo["receptor"] = tipo_receptor(dispositivo)
                return dispositivo
            except (OSError, ValueError, http.client.HTTPException) as error:
                errores.append(str(error))
            finally:
                if con:
                    con.close()
        raise ValueError("No se pudo conectar al receptor. Abrí Lucie Recibir en el celular, verificá Wi-Fi, IP y puerto. " + "; ".join(errores))

    def descubrir(self, segundos=3, receptor=None):
        validar_receptor(receptor)
        interfaces = interfaces_locales()
        encontrados = {}
        encontrados_lock = threading.Lock()
        cliente = self

        class Registro(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def setup(self):
                self.request.settimeout(3)
                super().setup()

            def do_POST(self):
                try:
                    if self.path != "/api/localsend/v2/register":
                        self.send_error(404)
                        return
                    largo = int(self.headers.get("Content-Length", "0"))
                    if not 0 < largo <= 8192:
                        self.send_error(400)
                        return
                    datos = json.loads(self.rfile.read(largo))
                    if not isinstance(datos, dict):
                        raise ValueError("Registro inválido.")
                    ip = validar_destino(self.client_address[0], datos.get("port", 53317))
                    if datos.get("fingerprint") != cliente.huella:
                        puerto = datos.get("port", PUERTO_LOCALSEND)
                        with encontrados_lock:
                            if len(encontrados) < 32:
                                encontrados[(ip, puerto)] = (ip, puerto, datos.get("protocol", "https"))
                    cuerpo = json.dumps(cliente.info(self.server.server_port)).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(cuerpo)))
                    self.end_headers()
                    self.wfile.write(cuerpo)
                except (ValueError, OSError):
                    self.send_error(400)

        servidor = None
        hilo = None
        # Lucie contesta al socket UDP emisor; no necesita una escucha HTTP
        # entrante que el firewall pueda bloquear en una red pública de Windows.
        if receptor != "lucie":
            servidor = ThreadingHTTPServer(("0.0.0.0", 0), Registro)
            servidor.daemon_threads = True
            hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
            hilo.start()
        udp = None
        try:
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # Puerto efímero propio: no competir con LocalSend ni depender de
            # compartir UDP 53317. Lucie responde por unicast a este socket.
            udp.bind(("0.0.0.0", 0))
            udp.settimeout(0.1)
            anuncio = {**self.info(servidor.server_port if servidor else PUERTO_LUCIE), "announce": True, "lucie": True}
            cuerpo = json.dumps(anuncio).encode()
            def anunciar():
                puertos = ([PUERTO_DESCUBRIMIENTO_LUCIE] if receptor == "lucie" else
                           [PUERTO_LOCALSEND] if receptor == "localsend" else
                           [PUERTO_DESCUBRIMIENTO_LUCIE, PUERTO_LOCALSEND])
                for interfaz in interfaces or [None]:
                    try:
                        if interfaz:
                            udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(str(interfaz.ip)))
                    except OSError:
                        continue
                    for puerto in puertos:
                        destinos = {GRUPO_DESCUBRIMIENTO, "255.255.255.255"}
                        if interfaz:
                            destinos.add(str(interfaz.network.broadcast_address))
                        for destino in destinos:
                            try:
                                udp.sendto(cuerpo, (destino, puerto))
                            except OSError:
                                # Un adaptador o multicast rechazado no cancela la búsqueda.
                                continue

            anunciar()
            limite = time.monotonic() + min(max(segundos, 0.1), 5)
            siguiente_anuncio = time.monotonic() + 0.8
            while time.monotonic() < limite:
                if time.monotonic() >= siguiente_anuncio:
                    anunciar()
                    siguiente_anuncio = time.monotonic() + 0.8
                try:
                    cuerpo, origen = udp.recvfrom(8192)
                    datos = json.loads(cuerpo)
                    if not isinstance(datos, dict) or datos.get("fingerprint") == self.huella:
                        continue
                    ip = validar_destino(origen[0], datos.get("port", PUERTO_LUCIE))
                    if str(datos.get("version", "")).startswith("2."):
                        puerto = datos.get("port", PUERTO_LUCIE)
                        with encontrados_lock:
                            if len(encontrados) < 32:
                                encontrados[(ip, puerto)] = (ip, puerto, datos.get("protocol", "https"))
                except socket.timeout:
                    continue
                except (ValueError, OSError):
                    continue
        except OSError:
            logger.warning("La búsqueda UDP no respondió; se conserva la comprobación local de Lucie.")
        finally:
            if udp:
                udp.close()
            if servidor:
                servidor.shutdown()
                servidor.server_close()
                hilo.join(timeout=2)
        dispositivos = []
        for ip, puerto, protocolo in list(encontrados.values())[:32]:
            try:
                dispositivo = self.probar(ip, puerto, protocolo)
                if receptor is None or tipo_receptor(dispositivo) == receptor:
                    dispositivos.append(dispositivo)
            except ValueError:
                pass
        if receptor != "localsend" and not any(tipo_receptor(d) == "lucie" for d in dispositivos):
            for ip in buscar_puerto_lucie(interfaces):
                try:
                    dispositivo = self.probar(ip, PUERTO_LUCIE, "https", timeout=1)
                    if tipo_receptor(dispositivo) == "lucie":
                        dispositivos.append(dispositivo)
                except ValueError:
                    continue
        return dispositivos

    def enviar(self, dispositivo, archivos, recibido, progreso, cancelar, pin=""):
        if cancelar.is_set():
            raise ValueError("Envío cancelado.")
        metadatos = {a["id"]: {"id": a["id"], "fileName": a["nombre"], "size": a["tamano"],
                               "fileType": mimetypes.guess_type(a["nombre"])[0] or "application/octet-stream",
                               "sha256": a["sha256"]} for a in archivos}
        consulta = "?" + urlencode({"pin": pin}) if pin else ""
        con, _ = self._conexion(dispositivo, timeout=5)
        con.response_class = functools.partial(_RespuestaCancelable, cancelar=cancelar)
        sesion = None
        etapa = "identidad"
        operacion = uuid.uuid4().hex
        inicio = time.monotonic()
        terminado = threading.Event()
        conexiones = {"actual": con, "socket": con.sock}

        def interrumpir():
            while not terminado.wait(0.1):
                if cancelar.is_set():
                    actual = conexiones["actual"]
                    sockets = {conexiones.get("socket"), actual.sock if actual else None}
                    for sock in sockets:
                        if sock:
                            try:
                                sock.shutdown(socket.SHUT_RDWR)
                            except OSError:
                                pass
                    if actual:
                        actual.close()
                    return

        interrupcion = threading.Thread(target=interrumpir, daemon=True, name="LucieCancelarConexion")
        interrupcion.start()
        try:
            if dispositivo["protocol"] == "http":
                con.request("GET", "/api/localsend/v2/info")
                conexiones["socket"] = con.sock
                identidad = self._leer_json(con.getresponse(), "identidad")
                if identidad.get("fingerprint") != dispositivo.get("fingerprint"):
                    raise ValueError("Cambió la identidad del celular. Buscalo nuevamente.")
            cuerpo = json.dumps({"info": self.info(), "files": metadatos}).encode()
            etapa = "preparacion"
            progreso(0, "Esperando aceptación en el celular")
            con.request("POST", "/api/localsend/v2/prepare-upload" + consulta, cuerpo,
                        {"Content-Type": "application/json", "Content-Length": str(len(cuerpo))})
            conexiones["socket"] = con.sock
            if con.sock:
                con.sock.settimeout(90)
            respuesta = self._leer_json(con.getresponse(), etapa)
            sesion = respuesta.get("sessionId")
            tokens = respuesta.get("files", {})
            if not isinstance(sesion, str) or not sesion or not isinstance(tokens, dict):
                raise ValueError("El receptor no confirmó una sesión de recepción válida.")
            rechazados = []
            for archivo in archivos:
                token = tokens.get(archivo["id"])
                if not isinstance(token, str) or not token:
                    rechazados.append(archivo["nombre"])
                    continue
                if cancelar.is_set():
                    raise ValueError("Envío cancelado.")
                etapa = "upload"
                progreso(0, "Enviando " + archivo["nombre"])
                parametros = urlencode({"sessionId": sesion, "fileId": archivo["id"], "token": token})
                con.close()
                con, _ = self._conexion(dispositivo, timeout=5)
                con.response_class = functools.partial(_RespuestaCancelable, cancelar=cancelar)
                conexiones["actual"] = con
                if cancelar.is_set():
                    raise ValueError("Envío cancelado.")
                con.putrequest("POST", "/api/localsend/v2/upload?" + parametros)
                con.putheader("Content-Type", "application/octet-stream")
                con.putheader("Content-Length", str(archivo["tamano"]))
                con.endheaders()
                conexiones["socket"] = con.sock
                if con.sock:
                    con.sock.settimeout(30)
                hash_enviado = hashlib.sha256()
                enviados = 0
                with open(archivo["origen"], "rb") as entrada:
                    while enviados < archivo["tamano"]:
                        if cancelar.is_set():
                            raise ValueError("Envío cancelado.")
                        bloque = entrada.read(min(1024 * 1024, archivo["tamano"] - enviados))
                        if not bloque:
                            raise ValueError("El video cambió durante el envío.")
                        con.send(bloque)
                        hash_enviado.update(bloque)
                        enviados += len(bloque)
                        progreso(len(bloque), "Enviando " + archivo["nombre"])
                    if entrada.read(1) or hash_enviado.hexdigest() != archivo["sha256"]:
                        raise ValueError("El video cambió durante el envío; no se marcará publicado.")
                etapa = "recepcion"
                conexiones["socket"] = con.sock
                if con.sock:
                    con.sock.settimeout(30)
                self._leer_json(con.getresponse(), etapa)
                recibido(archivo)
            if rechazados:
                raise ValueError("El celular no aceptó estos videos; siguen sin publicar: " + ", ".join(rechazados))
        except Exception as error:
            cancelacion_confirmada = None
            con.close()
            if sesion:
                try:
                    cierre, _ = self._conexion(dispositivo, timeout=3)
                    try:
                        cierre.request("POST", "/api/localsend/v2/cancel?" + urlencode({"sessionId": sesion}), b"")
                        self._leer_json(cierre.getresponse(), "cancelacion", aceptar_sin_cuerpo=True)
                        cancelacion_confirmada = True
                    finally:
                        cierre.close()
                except (OSError, ValueError, http.client.HTTPException):
                    cancelacion_confirmada = False
            diagnostico = error if isinstance(error, ErrorLocalSend) else ErrorLocalSend(
                "Envío cancelado." if cancelar.is_set() else str(error), etapa)
            diagnostico.cancelacion_confirmada = cancelacion_confirmada
            logger.warning("localsend operacion=%s etapa=%s http=%s duracion=%.3f cancelacion_confirmada=%s",
                           operacion, diagnostico.etapa, diagnostico.codigo_http,
                           time.monotonic() - inicio, cancelacion_confirmada)
            if diagnostico is error:
                raise
            raise diagnostico from error
        finally:
            terminado.set()
            con.close()
            interrupcion.join(timeout=1)
