"""Emisor LocalSend v2: descubrimiento, aceptación y envío con SHA-256.

Referencia: https://github.com/localsend/protocol (v2.2).
Solo se conecta a direcciones IP locales elegidas desde el dashboard.
"""
import hashlib
import http.client
import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode


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

    def info(self, puerto=53317):
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
    def _leer_json(respuesta):
        datos = respuesta.read(65537)
        if len(datos) > 65536:
            raise ValueError("Respuesta del receptor demasiado grande.")
        if respuesta.status != 200:
            mensajes = {401: "El celular solicita un PIN o el PIN no coincide.",
                        403: "El celular rechazó el envío.", 409: "El celular está ocupado con otro envío.",
                        422: "El receptor rechazó la integridad del archivo."}
            raise ValueError(mensajes.get(respuesta.status, f"El receptor respondió HTTP {respuesta.status}."))
        resultado = json.loads(datos) if datos else {}
        if not isinstance(resultado, dict):
            raise ValueError("Respuesta LocalSend inválida.")
        return resultado

    def probar(self, ip, puerto=53317, protocolo=None):
        validar_destino(ip, puerto)
        errores = []
        for modo in ([protocolo] if protocolo else ["https", "http"]):
            dispositivo = {"ip": ip, "port": puerto, "protocol": modo}
            con = None
            try:
                con, huella = self._conexion(dispositivo, timeout=3, comprobar=False)
                con.request("GET", "/api/localsend/v2/info")
                datos = self._leer_json(con.getresponse())
                if not str(datos.get("version", "")).startswith("2.") or not datos.get("alias"):
                    raise ValueError("El dispositivo no ofrece un receptor LocalSend v2.")
                dispositivo.update(alias=str(datos["alias"])[:100],
                                   fingerprint=huella or str(datos.get("fingerprint", "")))
                return dispositivo
            except (OSError, ValueError, http.client.HTTPException) as error:
                errores.append(str(error))
            finally:
                if con:
                    con.close()
        raise ValueError("No se pudo conectar a LocalSend. Abrilo en el celular, verificá Wi-Fi, IP y puerto. " + "; ".join(errores))

    def descubrir(self, segundos=3):
        encontrados = {}
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
                        encontrados[ip] = (ip, datos.get("port", 53317), datos.get("protocol", "https"))
                    cuerpo = json.dumps(cliente.info(self.server.server_port)).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(cuerpo)))
                    self.end_headers()
                    self.wfile.write(cuerpo)
                except (ValueError, OSError):
                    self.send_error(400)

        servidor = ThreadingHTTPServer(("0.0.0.0", 0), Registro)
        servidor.daemon_threads = True
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            anuncio = {**self.info(servidor.server_port), "announce": True}
            udp.sendto(json.dumps(anuncio).encode(), ("224.0.0.167", 53317))
            time.sleep(min(max(segundos, 0.1), 5))
        finally:
            udp.close()
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=2)
        dispositivos = []
        for ip, puerto, protocolo in list(encontrados.values())[:32]:
            try:
                dispositivos.append(self.probar(ip, puerto, protocolo))
            except ValueError:
                pass
        return dispositivos

    def enviar(self, dispositivo, archivos, recibido, progreso, cancelar, pin=""):
        if cancelar.is_set():
            raise ValueError("Envío cancelado.")
        metadatos = {a["id"]: {"id": a["id"], "fileName": a["nombre"], "size": a["tamano"],
                               "fileType": mimetypes.guess_type(a["nombre"])[0] or "application/octet-stream",
                               "sha256": a["sha256"]} for a in archivos}
        consulta = "?" + urlencode({"pin": pin}) if pin else ""
        con, _ = self._conexion(dispositivo, timeout=90)
        sesion = None
        try:
            if dispositivo["protocol"] == "http":
                con.request("GET", "/api/localsend/v2/info")
                identidad = self._leer_json(con.getresponse())
                if identidad.get("fingerprint") != dispositivo.get("fingerprint"):
                    raise ValueError("Cambió la identidad del celular. Buscalo nuevamente.")
            cuerpo = json.dumps({"info": self.info(), "files": metadatos}).encode()
            progreso(0, "Esperando aceptación en el celular")
            con.request("POST", "/api/localsend/v2/prepare-upload" + consulta, cuerpo,
                        {"Content-Type": "application/json", "Content-Length": str(len(cuerpo))})
            respuesta = self._leer_json(con.getresponse())
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
                progreso(0, "Enviando " + archivo["nombre"])
                parametros = urlencode({"sessionId": sesion, "fileId": archivo["id"], "token": token})
                con.close()
                con, _ = self._conexion(dispositivo, timeout=30)
                con.putrequest("POST", "/api/localsend/v2/upload?" + parametros)
                con.putheader("Content-Type", "application/octet-stream")
                con.putheader("Content-Length", str(archivo["tamano"]))
                con.endheaders()
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
                self._leer_json(con.getresponse())
                recibido(archivo)
            if rechazados:
                raise ValueError("El celular no aceptó estos videos; siguen sin publicar: " + ", ".join(rechazados))
        except Exception:
            con.close()
            if sesion:
                try:
                    cierre, _ = self._conexion(dispositivo, timeout=3)
                    try:
                        cierre.request("POST", "/api/localsend/v2/cancel?" + urlencode({"sessionId": sesion}), b"")
                        cierre.getresponse().read(65536)
                    finally:
                        cierre.close()
                except (OSError, ValueError, http.client.HTTPException):
                    pass
            raise
        finally:
            con.close()
