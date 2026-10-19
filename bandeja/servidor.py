#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/servidor.py

Servidor HTTP multihilo y manejador de peticiones para el panel web de la
bandeja de descargas. Gestiona endpoints REST de la API y sirve activos
estáticos exclusivamente mediante lista blanca estricta con inyección segura de CSRF.
"""

import datetime
import os
import json
import html
import secrets
import hmac
import shutil
import subprocess
import logging
import mimetypes
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("bandeja_descargas")

from bandeja.plataforma import esta_confinado_en_raiz, validar_longitud_ruta, abrir_carpeta_windows, normalizar_ruta_relativa_posix
from bandeja.config import (
    ConfiguracionBandeja,
    ErrorSeguridadBandeja,
    ErrorValidacionEscena,
    ErrorDeshacer,
)
from bandeja.db import GestorBaseDatosBandeja
from bandeja.clasificacion import ValidadorEscenas
from bandeja.movimientos import (
    GestorMovimientosBandeja,
    generar_html_simulacion,
)
from bandeja.pendrive import (
    obtener_estado_pendrive,
    simular_envio_capitulos,
    ejecutar_envio_pendrive,
    detectar_unidad_candidata_sin_vincular,
    simular_vinculacion_pendrive,
    vincular_pendrive,
    escanear_sala_espera_carpetas,
    detectar_pendrive,
    leer_manifiesto_pendrive,
    montar_unidad_pendrive,
    desmontar_unidad_pendrive,
)
from bandeja.vigilante import VigilanteBandeja
from bandeja.eliminacion import GestorEliminacionPendrive
from bandeja.publicacion import GestorPublicacion
from bandeja.organizacion_mensual import resolver_relativa
from bandeja.edicion import (
    obtener_secciones_edicion,
    obtener_sesiones_con_crudos_pendientes,
    crear_sesion,
    verificar_version_export,
    obtener_carpeta_edicion,
    sumar_videos_sesion,
    cancelar_sesion,
    finalizar_edicion_crudos,
    revisar_export_terminado,
    registrar_exports_revision_ambigua,
    deshacer_finalizar_edicion,
    copiar_export_a_videos_completos,
    deshacer_copia_completo,
    vincular_nuevo_export,
    procesar_exports_pendientes_copia,
    obtener_videos_completados,
    obtener_sesiones_para_export,
)

RUTA_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

class GeneradorMiniaturas:
    """Genera miniaturas seguras vía ffmpeg usando IDs de base de datos y subprocess sin shell."""

    def __init__(self, db: GestorBaseDatosBandeja, ruta_cache_miniaturas: str = ".cache/miniaturas_bandeja"):
        self.db = db
        self.ruta_cache = ruta_cache_miniaturas
        os.makedirs(self.ruta_cache, exist_ok=True)

    def obtener_o_generar(self, archivo_id: int) -> Optional[Tuple[bytes, str]]:
        """
        Recibe exclusivamente el ID de archivo en la base SQLite.
        Invoca ffmpeg de manera segura con subprocess y lista de argumentos, sin shell=True y con '--'.
        Retorna (contenido_bytes, mime_type).
        """
        registro = self.db.obtener_por_id(archivo_id)
        if not registro:
            return None

        ruta_archivo = registro["ruta_actual"]
        if not os.path.exists(ruta_archivo):
            return None

        hash_archivo = registro["hash"]
        ruta_miniatura = os.path.join(self.ruta_cache, f"{hash_archivo}.jpg")

        # Si ya existe en caché, servirla directamente
        if os.path.exists(ruta_miniatura):
            with open(ruta_miniatura, "rb") as f:
                return f.read(), "image/jpeg"

        _, ext = os.path.splitext(ruta_archivo.lower())

        # Si es imagen estática, podemos generar un thumbnail o leer los datos directamente
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")
            with open(ruta_archivo, "rb") as f:
                return f.read(), mime

        # Si es video, extraer un fotograma en el segundo 1 con ffmpeg
        if ext in (".mp4", ".mov", ".webm"):
            if not shutil.which("ffmpeg"):
                # Fallback sin ffmpeg: devolver None (la UI renderizará icono por defecto)
                return None

            # Invocación segura: lista de argumentos, sin shell=True, y '--' antes de la ruta
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", "00:00:01",
                "-i", "--", ruta_archivo,
                "-vframes", "1",
                "-q:v", "2",
                ruta_miniatura
            ]
            try:
                subprocess.run(
                    cmd,
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8.0,
                    check=False
                )
                if os.path.exists(ruta_miniatura):
                    with open(ruta_miniatura, "rb") as f:
                        return f.read(), "image/jpeg"
            except Exception:
                pass

        return None



class HandlerServidorBandeja(BaseHTTPRequestHandler):
    """Manejador HTTP para el panel web de la bandeja de descargas."""

    # Inyectados por el servidor
    config: ConfiguracionBandeja = None
    db: GestorBaseDatosBandeja = None
    vigilante: VigilanteBandeja = None
    vigilante_capcut: Optional[Any] = None
    movimientos: GestorMovimientosBandeja = None
    miniaturas: GeneradorMiniaturas = None
    token_csrf: str = ""

    def _enviar_json(self, datos: Any, codigo: int = 200, solo_cabeceras: bool = False):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        if not solo_cabeceras:
            self.wfile.write(cuerpo)

    def _enviar_error(self, codigo: int, mensaje: str, solo_cabeceras: bool = False):
        self._enviar_json({"error": mensaje, "codigo": codigo}, codigo=codigo, solo_cabeceras=solo_cabeceras)

    def _validar_host(self, solo_cabeceras: bool = False) -> bool:
        host_header = self.headers.get("Host", "").strip()
        puerto_esperado = str(self.config.puerto_servidor)
        puerto_real = str(self.server.server_address[1]) if hasattr(self, "server") and hasattr(self.server, "server_address") else puerto_esperado
        hosts_validos = {
            f"127.0.0.1:{puerto_esperado}",
            f"localhost:{puerto_esperado}",
            f"127.0.0.1:{puerto_real}",
            f"localhost:{puerto_real}",
            "127.0.0.1",
            "localhost"
        }
        if host_header not in hosts_validos:
            self._enviar_error(HTTPStatus.FORBIDDEN, f"Cabecera Host no permitida: '{host_header}'", solo_cabeceras=solo_cabeceras)
            return False
        return True

    def _validar_seguridad_post(self) -> bool:
        """
        Valida que la petición POST cumpla:
        1. Host coincidente con 127.0.0.1:<puerto> o localhost:<puerto>.
        2. Content-Type 'application/json'.
        3. Token anti-CSRF en cabecera 'X-CSRF-Token'.
        Responde 403 Forbidden si no se cumplen.
        """
        # 1. Validar Host
        if not self._validar_host():
            return False

        # 2. Validar Content-Type
        content_type = self.headers.get("Content-Type", "").strip().lower()
        if not content_type.startswith("application/json"):
            self._enviar_error(HTTPStatus.FORBIDDEN, "Se requiere Content-Type: application/json.")
            return False

        # 3. Validar Token anti-CSRF
        token_recibido = self.headers.get("X-CSRF-Token", "").strip()
        if not token_recibido or not hmac.compare_digest(token_recibido, self.token_csrf):
            self._enviar_error(HTTPStatus.FORBIDDEN, "Acceso denegado: token anti-CSRF ausente o inválido.")
            return False

        return True

    def _leer_json_body(self) -> Optional[Dict[str, Any]]:
        try:
            longitud = int(self.headers.get("Content-Length", 0))
            if longitud <= 0:
                return {}
            cuerpo_raw = self.rfile.read(longitud).decode("utf-8")
            return json.loads(cuerpo_raw)
        except Exception:
            return None

    def do_HEAD(self):
        parsed = urlparse(self.path)
        ruta = parsed.path

        if ruta.startswith("/api/"):
            if not self._validar_host(solo_cabeceras=True):
                return

        if ruta == "/api/media":
            self._servir_media(parsed.query, solo_cabeceras=True)
        elif ruta in ("/", "/index.html", "/panel.html"):
            self._servir_html_spa(solo_cabeceras=True)
        elif ruta == "/panel.js":
            self._servir_estatico("panel.js", "application/javascript; charset=utf-8", solo_cabeceras=True)
        elif ruta == "/wifi.js":
            self._servir_estatico("wifi.js", "application/javascript; charset=utf-8", solo_cabeceras=True)
        elif ruta == "/panel.css":
            self._servir_estatico("panel.css", "text/css; charset=utf-8", solo_cabeceras=True)
        elif ruta == "/api/estado-version":
            token = self.vigilante.obtener_token_version()
            estado_pen = getattr(self.vigilante, "_estado_pendrive", {})
            self._enviar_json({
                "version": token,
                "refresco_panel_segundos": getattr(self.config, "refresco_panel_segundos", 4),
                "banner_pendrive": estado_pen.get("banner_reactivo"),
                "horas_material_reciente": getattr(self.config, "horas_material_reciente", 168)
            }, solo_cabeceras=True)
        elif ruta == "/api/pendrive/carpetas":
            self._handle_pendrive_carpetas(solo_cabeceras=True)
        elif ruta == "/api/pendrive/estado":
            self._handle_pendrive_estado(solo_cabeceras=True)
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada.", solo_cabeceras=True)

    def do_GET(self):
        parsed = urlparse(self.path)
        ruta = parsed.path

        if ruta.startswith("/api/"):
            if not self._validar_host():
                return

        if ruta in ("/", "/index.html", "/panel.html"):
            self._servir_html_spa()
        elif ruta == "/panel.js":
            self._servir_estatico("panel.js", "application/javascript; charset=utf-8")
        elif ruta == "/wifi.js":
            self._servir_estatico("wifi.js", "application/javascript; charset=utf-8")
        elif ruta == "/panel.css":
            self._servir_estatico("panel.css", "text/css; charset=utf-8")
        elif ruta == "/api/media":
            self._servir_media(parsed.query, solo_cabeceras=False)
        elif ruta == "/api/estado-version":
            token = self.vigilante.obtener_token_version()
            estado_pen = getattr(self.vigilante, "_estado_pendrive", {})
            self._enviar_json({
                "version": token,
                "refresco_panel_segundos": getattr(self.config, "refresco_panel_segundos", 4),
                "banner_pendrive": estado_pen.get("banner_reactivo"),
                "horas_material_reciente": getattr(self.config, "horas_material_reciente", 168)
            })
        elif ruta == "/api/lotes":
            estado = self.vigilante.obtener_estado()
            self._enviar_json({
                "lotes": estado["lotes"],
                "lotes_anteriores": estado.get("lotes_anteriores", []),
                "horas_material_reciente": getattr(self.config, "horas_material_reciente", 168)
            })
        elif ruta == "/api/sin-identificar":
            estado = self.vigilante.obtener_estado()
            self._enviar_json({"sin_identificar": estado["sin_identificar"]})
        elif ruta == "/api/escenas":
            estado = self.vigilante.obtener_estado()
            self._enviar_json({"escenas": estado["escenas"]})
        elif ruta == "/api/personajes":
            ultimo = self.db.obtener_ultimo_personaje() or "lucie"
            self._enviar_json({
                "personajes": [
                    {"id": "lucie", "nombre": "Lucie"},
                    {"id": "roli", "nombre": "Roli"},
                    {"id": "mailen", "nombre": "Mailen"}
                ],
                "ultimo_personaje": ultimo
            })
        elif ruta == "/api/miniatura":
            self._servir_miniatura(parsed.query)
        elif ruta == "/api/historial":
            historial = self.movimientos.obtener_historial(50)
            self._enviar_json({"historial": historial})
        elif ruta == "/api/capitulos/estado":
            self._handle_capitulos_estado()
        elif ruta == "/api/capitulos/abiertos":
            self._handle_capitulos_abiertos()
        elif ruta == "/api/capitulos/cerrados":
            self._handle_capitulos_cerrados()
        elif ruta == "/api/capitulos/descartados":
            self._handle_capitulos_descartados()
        elif ruta == "/api/capitulo-activo":
            cap_activo = self.db.obtener_capitulo_activo()
            self._enviar_json({"capitulo_activo": cap_activo})
        elif ruta == "/api/pendrive/estado":
            self._handle_pendrive_estado()
        elif ruta == "/api/pendrive/eliminacion":
            self._handle_eliminacion()
        elif ruta == "/api/pendrive/carpetas":
            self._handle_pendrive_carpetas()
        elif ruta == "/api/edicion/secciones":
            self._handle_edicion_secciones()
        elif ruta == "/api/capcut/exports":
            self._handle_capcut_exports()
        elif ruta == "/api/publicacion/lista":
            self._enviar_json(self.publicacion.listar())
        elif ruta == "/api/publicacion/estado":
            try:
                self._enviar_json(self.publicacion.estado(parse_qs(parsed.query).get("id", [""])[0]))
            except ValueError as e:
                self._enviar_error(HTTPStatus.NOT_FOUND, str(e))
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada.")

    def _handle_pendrive_estado(self, solo_cabeceras: bool = False):
        try:
            res = obtener_estado_pendrive(self.config, self.db, timeout_segundos=3.0)
            self._enviar_json(res, solo_cabeceras=solo_cabeceras)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al consultar estado de pendrive: {e}", solo_cabeceras=solo_cabeceras)

    def _handle_pendrive_carpetas(self, solo_cabeceras: bool = False):
        try:
            envios_manifiesto = set()
            try:
                info_pen = detectar_pendrive(self.config)
                if info_pen and info_pen.get("conectado"):
                    punto = info_pen.get("punto_montaje") or info_pen.get("ruta_montaje")
                    entradas_m = leer_manifiesto_pendrive(punto, getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas"))
                    for ent in entradas_m:
                        h = ent.get("sha256")
                        ruta = ent.get("ruta_relativa")
                        if h and ruta and ent.get("estado") != "revertido":
                            raiz = os.path.join(punto, getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas"))
                            envios_manifiesto.add((h.lower(), resolver_relativa(raiz, normalizar_ruta_relativa_posix(ruta)).lower()))
            except Exception:
                pass

            carpetas = escanear_sala_espera_carpetas(
                self.config.ruta_destino_base,
                db=self.db,
                envios_manifiesto=envios_manifiesto,
                vigilante=self.vigilante
            )
            self._enviar_json({"carpetas": carpetas, "total_carpetas": len(carpetas)}, solo_cabeceras=solo_cabeceras)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al listar carpetas de sala de espera: {e}", solo_cabeceras=solo_cabeceras)

    def _handle_capitulos_estado(self):
        cap_foco = self.db.obtener_capitulo_en_foco()
        es_activo = cap_foco.get("habilitado", False)
        limite = float(self.config.horas_alerta_capitulo_olvidado)
        alerta = self.db.es_capitulo_olvidado(horas_limite=limite)

        balance = {"pendientes": 0, "movidos": 0}
        if es_activo and cap_foco.get("personaje") and cap_foco.get("nombre"):
            balance = self.db.calcular_balance_capitulo(
                cap_foco["personaje"], cap_foco["nombre"], verificar_disco=True
            )
            carpeta_cap = os.path.join(self.config.ruta_destino_base, cap_foco["personaje"], cap_foco["nombre"])
            if os.path.isdir(carpeta_cap):
                tot_arch = sum(len(f) for _, _, f in os.walk(carpeta_cap))
                if tot_arch > 0:
                    cap_foco["carpeta_info"] = {
                        "ya_existia": True,
                        "total_archivos": tot_arch,
                        "mensaje": f"La carpeta ya existía y tiene {tot_arch} archivos"
                    }

        abiertos = self.db.listar_capitulos_abiertos()
        for c in abiertos:
            c["balance"] = self.db.calcular_balance_capitulo(c["personaje"], c["nombre"], verificar_disco=True)
            c["en_foco"] = bool(c.get("en_foco"))

        self._enviar_json({
            "activo": es_activo,
            "capitulo": cap_foco,
            "capitulo_foco": cap_foco if es_activo else None,
            "capitulos_abiertos": abiertos,
            "cantidad_abiertos": len(abiertos),
            "alerta_olvidado": alerta,
            "horas_limite": self.config.horas_alerta_capitulo_olvidado,
            "balance": balance
        })

    def _handle_capitulos_abiertos(self):
        abiertos = self.db.listar_capitulos_abiertos()
        for c in abiertos:
            c["balance"] = self.db.calcular_balance_capitulo(c["personaje"], c["nombre"], verificar_disco=True)
            c["en_foco"] = bool(c.get("en_foco"))
        self._enviar_json({"abiertos": abiertos, "total": len(abiertos)})

    def _handle_capitulos_cerrados(self):
        cerrados = self.db.listar_capitulos_cerrados()
        self._enviar_json({"cerrados": cerrados})

    def _handle_capitulos_descartados(self):
        descartados = self.db.listar_capitulos_descartados()
        self._enviar_json({"descartados": descartados})

    def _servir_miniatura(self, query_string: str):
        params = parse_qs(query_string)
        archivo_id_str = params.get("id", [None])[0]
        if not archivo_id_str or not archivo_id_str.isdigit():
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Parámetro 'id' numérico requerido.")
            return

        resultado = self.miniaturas.obtener_o_generar(int(archivo_id_str))
        if not resultado:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Miniatura no disponible.")
            return

        datos, mime = resultado
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(datos)

    def _servir_media(self, query_string: str, solo_cabeceras: bool = False):
        params = parse_qs(query_string)
        media_id = params.get("id", [None])[0]
        if not media_id:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Identificador multimedia no especificado.", solo_cabeceras=solo_cabeceras)
            return

        ruta = None
        raiz_publicacion = None
        if str(media_id).startswith("publicacion:"):
            try:
                ruta, raiz_publicacion = self.publicacion.resolver_media(str(media_id)[12:])
            except (OSError, ValueError) as e:
                self._enviar_error(HTTPStatus.NOT_FOUND, str(e), solo_cabeceras=solo_cabeceras)
                return
        if str(media_id).startswith("capcut:") and self.db:
            export_id = str(media_id)[7:]
            export = next((e for e in self.db.obtener_exports_pendientes()
                           if str(e["id"]) == export_id and e["estado"] != "descartado"), None)
            if export:
                if not esta_confinado_en_raiz(export["ruta_origen"], self.config.obtener_carpeta_exportacion_capcut()):
                    self._enviar_error(HTTPStatus.FORBIDDEN, "Export fuera de la carpeta de CapCut.", solo_cabeceras=solo_cabeceras)
                    return
                try:
                    verificar_version_export(export)
                except (ValueError, OSError) as e:
                    self._enviar_error(HTTPStatus.CONFLICT, str(e), solo_cabeceras=solo_cabeceras)
                    return
                ruta = export["ruta_origen"]
        if self.vigilante:
            ruta = ruta or self.vigilante.resolver_ruta_media(str(media_id))

        # Si no se encuentra en vigilante, intentar resolver en el pendrive vinculado
        raiz_pen_detectada = raiz_publicacion
        punto_pen_detectado = None
        try:
            info_pen = detectar_pendrive(self.config)
            if info_pen and info_pen.get("conectado"):
                punto_pen = info_pen.get("punto_montaje") or info_pen.get("ruta_montaje")
                if punto_pen:
                    punto_pen_detectado = punto_pen
                    carpeta_raiz = getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas")
                    raiz_pen_detectada = os.path.join(punto_pen, carpeta_raiz)
                    if not ruta:
                        raw_id = str(media_id)
                        if raw_id.startswith("pendrive:"):
                            raw_id = raw_id[9:]
                        norm_rel = raw_id.replace("/", os.sep).replace("\\", os.sep).lstrip(os.sep)
                        candidatos = [
                            os.path.join(raiz_pen_detectada, norm_rel),
                            os.path.join(raiz_pen_detectada, "videos sin editar", norm_rel),
                            os.path.join(raiz_pen_detectada, "videos ya editados", norm_rel),
                            os.path.join(raiz_pen_detectada, "videos completos", norm_rel),
                            os.path.join(raiz_pen_detectada, "videos1", norm_rel),
                        ]
                        if punto_pen:
                            candidatos.extend([
                                os.path.join(punto_pen, norm_rel),
                                os.path.join(punto_pen, "videos sin editar", norm_rel),
                                os.path.join(punto_pen, "videos ya editados", norm_rel),
                                os.path.join(punto_pen, "videos completos", norm_rel),
                                os.path.join(punto_pen, "videos1", norm_rel),
                            ])
                        for cand in candidatos:
                            confinado = (esta_confinado_en_raiz(cand, raiz_pen_detectada) or 
                                         (punto_pen and esta_confinado_en_raiz(cand, punto_pen)))
                            if confinado and os.path.isfile(cand):
                                ruta = cand
                                break
        except Exception:
            pass

        if not ruta:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Archivo multimedia no encontrado.", solo_cabeceras=solo_cabeceras)
            return

        # Resolver con realpath para mitigar enlaces simbólicos y evasión de directorio
        real_ruta = os.path.realpath(ruta)
        validar_longitud_ruta(real_ruta)

        raices_permitidas = [
            self.config.ruta_descargas,
            self.config.ruta_destino_base
        ]
        if raiz_pen_detectada:
            raices_permitidas.append(raiz_pen_detectada)
        if punto_pen_detectado:
            raices_permitidas.append(punto_pen_detectado)
        try:
            dir_capcut = self.config.obtener_carpeta_exportacion_capcut()
            if dir_capcut and os.path.isdir(dir_capcut):
                raices_permitidas.append(dir_capcut)
        except Exception:
            pass

        dentro_de_raices = any(esta_confinado_en_raiz(real_ruta, raiz) for raiz in raices_permitidas)

        if not dentro_de_raices:
            self._enviar_error(HTTPStatus.FORBIDDEN, "Acceso no permitido: el archivo está fuera de las raíces autorizadas.", solo_cabeceras=solo_cabeceras)
            return

        if not os.path.isfile(real_ruta):
            self._enviar_error(HTTPStatus.NOT_FOUND, "El archivo solicitado no existe en disco.", solo_cabeceras=solo_cabeceras)
            return

        try:
            st = os.stat(real_ruta)
            total_bytes = st.st_size
            mtime = st.st_mtime
        except OSError:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Error al acceder a los metadatos del archivo.", solo_cabeceras=solo_cabeceras)
            return

        mime_type, _ = mimetypes.guess_type(real_ruta)
        if not mime_type:
            _, ext = os.path.splitext(real_ruta.lower())
            if ext in (".mp4", ".m4v"):
                mime_type = "video/mp4"
            elif ext == ".webm":
                mime_type = "video/webm"
            elif ext == ".mov":
                mime_type = "video/quicktime"
            elif ext in (".jpg", ".jpeg"):
                mime_type = "image/jpeg"
            elif ext == ".png":
                mime_type = "image/png"
            elif ext == ".webp":
                mime_type = "image/webp"
            else:
                mime_type = "application/octet-stream"

        etag = f'"{total_bytes}-{int(mtime)}"'
        range_header = self.headers.get("Range", "").strip()

        es_rango = False
        start = 0
        end = total_bytes - 1

        if range_header.startswith("bytes="):
            rango_val = range_header[6:].strip()
            if "," in rango_val:
                rango_val = rango_val.split(",")[0].strip()

            partes = rango_val.split("-")
            if len(partes) == 2:
                str_start, str_end = partes[0].strip(), partes[1].strip()
                try:
                    if str_start and str_end:
                        start = int(str_start)
                        end = int(str_end)
                    elif str_start and not str_end:
                        start = int(str_start)
                        end = total_bytes - 1
                    elif not str_start and str_end:
                        sufijo = int(str_end)
                        start = max(0, total_bytes - sufijo)
                        end = total_bytes - 1
                    else:
                        start = 0
                        end = total_bytes - 1

                    if start < 0 or start >= total_bytes or end < start:
                        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                        self.send_header("Content-Range", f"bytes */{total_bytes}")
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Length", "0")
                        self.send_header("Cache-Control", "private")
                        self.end_headers()
                        return

                    end = min(end, total_bytes - 1)
                    es_rango = True
                except ValueError:
                    es_rango = False
                    start = 0
                    end = total_bytes - 1

        longitud = end - start + 1 if es_rango else total_bytes

        codigo_respuesta = HTTPStatus.PARTIAL_CONTENT if es_rango else HTTPStatus.OK
        self.send_response(codigo_respuesta)
        self.send_header("Content-Type", mime_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(longitud))
        if es_rango:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total_bytes}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", "inline")
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "private")
        self.end_headers()

        if solo_cabeceras:
            return

        chunk_size = 65536
        restante = longitud
        try:
            with open(real_ruta, "rb") as f:
                if start > 0:
                    f.seek(start)
                while restante > 0:
                    a_leer = min(chunk_size, restante)
                    bloque = f.read(a_leer)
                    if not bloque:
                        break
                    self.wfile.write(bloque)
                    restante -= len(bloque)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.error):
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        ruta = parsed.path

        if ruta == "/api/estado-version":
            self._enviar_error(HTTPStatus.METHOD_NOT_ALLOWED, "El endpoint /api/estado-version solo admite peticiones GET.")
            return

        if not self._validar_seguridad_post():
            return

        body = self._leer_json_body()

        if body is None:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Cuerpo JSON inválido o malformado.")
            return

        if ruta in ("/api/publicacion/buscar", "/api/publicacion/conectar", "/api/publicacion/simular",
                    "/api/publicacion/enviar", "/api/publicacion/cancelar", "/api/publicacion/deshacer",
                    "/api/publicacion/resguardar", "/api/publicacion/organizar-simular",
                    "/api/publicacion/organizar", "/api/publicacion/deshacer-organizacion"):
            self._handle_publicacion(ruta, body)
        elif ruta == "/api/pendrive/eliminacion-simular":
            self._handle_eliminacion(body, simular=True)
        elif ruta == "/api/pendrive/eliminar":
            self._handle_eliminacion(body)
        elif ruta == "/api/clasificar-sin-identificar":
            self._handle_clasificar_sin_identificar(body)
        elif ruta == "/api/deshacer-clasificar-sin-identificar":
            self._handle_deshacer_clasificar_sin_identificar(body)
        elif ruta == "/api/capitulos/empezar":
            self._handle_capitulos_empezar(body)
        elif ruta == "/api/capitulos/en-foco":
            self._handle_capitulos_en_foco(body)
        elif ruta == "/api/capitulos/terminar":
            self._handle_capitulos_terminar(body)
        elif ruta == "/api/capitulos/reabrir":
            self._handle_capitulos_reabrir(body)
        elif ruta == "/api/capitulos/descartar-simular":
            self._handle_capitulos_descartar_simular(body)
        elif ruta == "/api/capitulos/descartar":
            self._handle_capitulos_descartar(body)
        elif ruta == "/api/capitulos/posponer_alerta":
            self._handle_capitulos_posponer_alerta(body)
        elif ruta == "/api/capitulo-activo":
            self._handle_guardar_capitulo_activo(body)
        elif ruta == "/api/simular-mover":
            self._handle_simular_mover(body)
        elif ruta == "/api/mover-lote":
            self._handle_mover_lote(body)
        elif ruta == "/api/deshacer":
            self._handle_deshacer(body)
        elif ruta == "/api/pendrive/vincular-simular":
            self._handle_pendrive_vincular_simular(body)
        elif ruta == "/api/pendrive/vincular":
            self._handle_pendrive_vincular(body)
        elif ruta == "/api/pendrive/envio-simular":
            self._handle_pendrive_envio_simular(body)
        elif ruta == "/api/pendrive/envio":
            self._handle_pendrive_envio(body)
        elif ruta == "/api/pendrive/montar":
            self._handle_pendrive_montar(body)
        elif ruta == "/api/pendrive/desmontar":
            self._handle_pendrive_desmontar(body, expulsar=False)
        elif ruta == "/api/pendrive/expulsar":
            self._handle_pendrive_desmontar(body, expulsar=True)
        elif ruta == "/api/edicion/crear-sesion":
            self._handle_edicion_crear_sesion(body)
        elif ruta == "/api/edicion/sumar-videos":
            self._handle_edicion_sumar_videos(body)
        elif ruta == "/api/edicion/cancelar-sesion":
            self._handle_edicion_cancelar_sesion(body)
        elif ruta == "/api/edicion/terminar":
            self._handle_edicion_terminar(body)
        elif ruta == "/api/edicion/revisar-export":
            self._handle_edicion_revisar_export(body)
        elif ruta == "/api/edicion/deshacer-terminar":
            self._handle_edicion_deshacer_terminar(body)
        elif ruta == "/api/capcut/asignar-export":
            self._handle_capcut_asignar_export(body)
        elif ruta == "/api/capcut/enviar-export":
            self._handle_capcut_asignar_export(body)
        elif ruta == "/api/capcut/descartar-export":
            self._handle_capcut_descartar_export(body)
        elif ruta == "/api/capcut/deshacer-completo":
            self._handle_capcut_deshacer_completo(body)
        elif ruta == "/api/capcut/escanear":
            self._handle_capcut_escanear(body)
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Endpoint POST no encontrado.")

    def _handle_publicacion(self, ruta, body):
        try:
            if not isinstance(body, dict):
                raise ValueError("El cuerpo debe ser un objeto JSON.")
            if ruta.endswith("/buscar"):
                resultado = {"dispositivos": self.publicacion.buscar_dispositivos(body.get("receptor"))}
            elif ruta.endswith("/conectar"):
                resultado = {"dispositivo": self.publicacion.agregar_dispositivo(body.get("ip"), body.get("puerto", 53318), body.get("receptor"))}
            elif ruta.endswith("/simular"):
                resultado = self.publicacion.simular(body.get("seleccion"), body.get("dispositivo_id"), body.get("personajes"), body.get("receptor"))
            elif ruta.endswith("/organizar-simular"):
                resultado = self.publicacion.organizacion.simular(body.get("seleccion"))
            elif ruta.endswith("/organizar"):
                resultado = self.publicacion.organizacion.ejecutar(body.get("token"), body.get("confirmacion"))
            elif ruta.endswith("/deshacer-organizacion"):
                resultado = self.publicacion.organizacion.deshacer(body.get("id_organizacion"))
            elif ruta.endswith("/enviar"):
                resultado = self.publicacion.iniciar_envio(body.get("token"), body.get("confirmacion"), body.get("pin", ""))
            elif ruta.endswith("/cancelar"):
                resultado = self.publicacion.cancelar(body.get("id"))
            elif ruta.endswith("/deshacer"):
                resultado = self.publicacion.deshacer(body.get("id_operacion"))
            else:
                from bandeja.edicion import copiar_export_sin_sesion_a_sin_publicar
                export = next((e for e in self.db.obtener_exports_pendientes() if e["id"] == body.get("export_id")), None)
                if not export or export.get("sesion_id") or export["estado"] not in ("sin_asignar", "copiado"):
                    raise ValueError("Export sin sesión no encontrado.")
                pen = detectar_pendrive(self.config)
                if not pen or not pen.get("conectado"):
                    raise ValueError("No hay pendrive vinculado conectado.")
                destino = copiar_export_sin_sesion_a_sin_publicar(export, pen.get("punto_montaje") or pen.get("ruta_montaje"),
                    self.db, self.config.carpeta_raiz_pendrive, self.movimientos.ruta_bitacora)
                resultado = {"exito": True, "destino": destino}
            self._enviar_json(resultado)
        except (OSError, ValueError) as e:
            self._enviar_error(HTTPStatus.CONFLICT, str(e))

    def _handle_eliminacion(self, body=None, simular=False):
        try:
            if body is not None and not isinstance(body, dict):
                raise ValueError('El cuerpo debe ser un objeto JSON.')
            if body is None:
                resultado = self.eliminacion.listar()
                for entrada in resultado['entradas']:
                    if entrada['tipo'] == 'archivo':
                        ruta = os.path.join(resultado['ruta_proyecto'], *entrada['ruta'].split('/'))
                        entrada['id_media'] = self.vigilante.registrar_ruta_media(ruta)
            elif simular:
                resultado = self.eliminacion.simular(body.get('seleccion'))
            else:
                resultado = self.eliminacion.ejecutar(body.get('token'), body.get('confirmacion'))
                self.vigilante.forzar_actualizacion_version()
            self._enviar_json(resultado)
        except (ValueError, OSError) as e:
            self._enviar_error(HTTPStatus.CONFLICT, str(e))

    def _handle_pendrive_envio_simular(self, body: Dict[str, Any]):
        capitulos = body.get("capitulos")
        carpetas = body.get("carpetas")
        seleccion = carpetas if carpetas is not None else capitulos
        if isinstance(seleccion, str):
            seleccion = [seleccion]
        elif not isinstance(seleccion, list):
            seleccion = None
        try:
            res = simular_envio_capitulos(seleccion, self.config, self.db, carpetas=carpetas,
                                          resoluciones_colisiones=body.get("resoluciones_colisiones"))
            self._enviar_json(res)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al simular envío: {e}")

    def _handle_pendrive_envio(self, body: Dict[str, Any]):
        capitulos = body.get("capitulos")
        carpetas = body.get("carpetas")
        simulacion = body.get("simulacion")
        seleccion = carpetas if carpetas is not None else capitulos
        if isinstance(seleccion, str):
            seleccion = [seleccion]
        elif not isinstance(seleccion, list):
            seleccion = None

        arg = simulacion if simulacion else seleccion
        try:
            res = ejecutar_envio_pendrive(arg, self.config, self.db, self.movimientos)
            if self.vigilante:
                try:
                    self.vigilante.escanear()
                except Exception:
                    pass
            self._enviar_json(res)
        except ValueError as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST, str(e))
        except ErrorSeguridadBandeja as e:
            self._enviar_error(HTTPStatus.FORBIDDEN, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al ejecutar envío: {e}")

    def _handle_pendrive_montar(self, body: Dict[str, Any]):
        dispositivo = str(body.get("dispositivo", "")).strip()
        if not dispositivo:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Debe especificar el campo 'dispositivo'.")
            return
        try:
            res = montar_unidad_pendrive(dispositivo, config=self.config, db=self.db)
            if res.get("exito"):
                self._enviar_json(res)
            else:
                self._enviar_json(res, codigo=HTTPStatus.UNPROCESSABLE_ENTITY)
        except ValueError as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al montar unidad: {e}")

    def _handle_pendrive_desmontar(self, body: Dict[str, Any], expulsar: bool = False):
        dispositivo = str(body.get("dispositivo", "")).strip()
        if not dispositivo:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Debe especificar el campo 'dispositivo'.")
            return
        try:
            res = desmontar_unidad_pendrive(dispositivo, expulsar=expulsar, config=self.config, db=self.db)
            if res.get("exito"):
                self._enviar_json(res)
            else:
                status = HTTPStatus.CONFLICT if res.get("ocupado") or res.get("bloqueado") else HTTPStatus.UNPROCESSABLE_ENTITY
                self._enviar_json(res, codigo=status)
        except ValueError as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al desmontar unidad: {e}")

    def _handle_pendrive_vincular_simular(self, body: Dict[str, Any]):
        punto = str(body.get("punto_montaje", "")).strip()
        if not punto:
            cand = detectar_unidad_candidata_sin_vincular(self.config)
            if cand:
                punto = cand["punto_montaje"]
            else:
                self._enviar_error(HTTPStatus.BAD_REQUEST, "No se especificó 'punto_montaje' y no se detectaron unidades candidatas sin vincular.")
                return
        try:
            res = simular_vinculacion_pendrive(punto, self.config)
            self._enviar_json(res)
        except (ValueError, FileNotFoundError) as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST if isinstance(e, FileNotFoundError) else HTTPStatus.CONFLICT, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al simular vinculación: {e}")

    def _handle_pendrive_vincular(self, body: Dict[str, Any]):
        punto = str(body.get("punto_montaje", "")).strip()
        if not punto:
            cand = detectar_unidad_candidata_sin_vincular(self.config)
            if cand:
                punto = cand["punto_montaje"]
            else:
                self._enviar_error(HTTPStatus.BAD_REQUEST, "No se especificó 'punto_montaje' y no se detectaron unidades candidatas sin vincular.")
                return
        try:
            res = vincular_pendrive(punto, self.config)
            if hasattr(self, "vigilante") and self.vigilante:
                self.vigilante.escanear()
            self._enviar_json(res)
        except ValueError as e:
            self._enviar_error(HTTPStatus.CONFLICT, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al vincular pendrive: {e}")

    def _handle_capitulos_empezar(self, body: Dict[str, Any]):
        personaje = str(body.get("personaje", "lucie")).strip().lower()
        nombre = str(body.get("nombre", "")).strip()

        if personaje not in ("lucie", "roli", "mailen"):
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Personaje inválido. Debe ser 'lucie', 'roli' o 'mailen'.")
            return

        if not nombre:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "El nombre del capítulo no puede estar vacío.")
            return

        valido, motivo = ValidadorEscenas.validar_nombre_escena(
            nombre, self.config.ruta_destino_base, self.config.ruta_descargas,
            es_existente_descargas=False, personaje=personaje
        )
        if not valido:
            self._enviar_error(HTTPStatus.BAD_REQUEST, f"Nombre de capítulo inválido: {motivo}")
            return

        try:
            from bandeja.clasificacion import nombre_carpeta_documentado
            existente = os.path.join(self.config.ruta_destino_base, personaje, nombre)
            if not os.path.isdir(existente):
                nombre = nombre_carpeta_documentado(nombre)
            info_carpeta = self.movimientos.asegurar_carpeta_capitulo(personaje, nombre)
            cap = self.db.empezar_capitulo(
                personaje, nombre,
                ruta_destino_base=self.config.ruta_destino_base,
                ruta_descargas=self.config.ruta_descargas
            )
            cap["carpeta_info"] = info_carpeta
            self.vigilante.escanear()
            mensaje = f"Capítulo '{personaje}/{nombre}' iniciado con éxito."
            if info_carpeta.get("ya_existia") and info_carpeta.get("total_archivos", 0) > 0:
                mensaje = f"{mensaje} {info_carpeta['mensaje']}."
            self._enviar_json({
                "exito": True,
                "mensaje": mensaje,
                "carpeta_info": info_carpeta,
                "capitulo": cap
            })
        except ValueError as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST if "inválido" in str(e).lower() or "límite" in str(e).lower() else HTTPStatus.CONFLICT, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al empezar capítulo: {str(e)}")

    def _handle_capitulos_en_foco(self, body: Dict[str, Any]):
        id_cap = body.get("id")
        if id_cap is None:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'id' de capítulo requerido.")
            return

        try:
            id_cap_num = int(id_cap)
        except (ValueError, TypeError):
            self._enviar_error(HTTPStatus.BAD_REQUEST, "El ID del capítulo debe ser numérico.")
            return

        try:
            cap = self.db.poner_capitulo_en_foco(id_cap_num)
            self.vigilante.escanear()
            self._enviar_json({
                "exito": True,
                "mensaje": f"Capítulo '{cap['personaje']}/{cap['nombre']}' puesto en foco.",
                "capitulo": cap
            })
        except ValueError as e:
            self._enviar_error(HTTPStatus.NOT_FOUND, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al poner capítulo en foco: {str(e)}")

    def _handle_capitulos_terminar(self, body: Dict[str, Any]):
        id_cap = body.get("id")
        accion = body.get("accion", "sin_mover")

        id_cap_num = int(id_cap) if id_cap is not None else None
        cerrado = self.db.terminar_capitulo(id_capitulo=id_cap_num)
        if not cerrado:
            self._enviar_error(HTTPStatus.NOT_FOUND, "No hay ningún capítulo activo o especificado para terminar.")
            return

        self.vigilante.escanear()
        self._enviar_json({
            "exito": True,
            "mensaje": "Capítulo terminado y cerrado correctamente.",
            "accion": accion
        })

    def _handle_capitulos_reabrir(self, body: Dict[str, Any]):
        id_cap = body.get("id")
        if not id_cap:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'id' de capítulo requerido.")
            return

        try:
            cap = self.db.reabrir_capitulo(
                int(id_cap),
                ruta_destino_base=self.config.ruta_destino_base,
                ruta_descargas=self.config.ruta_descargas
            )
            info_carpeta = self.movimientos.asegurar_carpeta_capitulo(cap["personaje"], cap["nombre"])
            cap["carpeta_info"] = info_carpeta
            self.vigilante.escanear()
            mensaje = f"Capítulo '{cap['personaje']}/{cap['nombre']}' reabierto como activo."
            if info_carpeta.get("ya_existia") and info_carpeta.get("total_archivos", 0) > 0:
                mensaje = f"{mensaje} {info_carpeta['mensaje']}."
            self._enviar_json({
                "exito": True,
                "mensaje": mensaje,
                "carpeta_info": info_carpeta,
                "capitulo": cap
            })
        except ValueError as e:
            self._enviar_error(HTTPStatus.CONFLICT, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al reabrir capítulo: {str(e)}")

    def _handle_capitulos_descartar_simular(self, body: Dict[str, Any]):
        capitulo_id = body.get("id")
        if capitulo_id is None:
            cap_foco = self.db.obtener_capitulo_en_foco()
            if cap_foco and cap_foco.get("habilitado") and cap_foco.get("id"):
                capitulo_id = cap_foco["id"]
            else:
                self._enviar_error(HTTPStatus.BAD_REQUEST, "Se requiere el ID del capítulo a descartar.")
                return

        try:
            capitulo_id = int(capitulo_id)
        except (ValueError, TypeError):
            self._enviar_error(HTTPStatus.BAD_REQUEST, "El ID del capítulo debe ser numérico.")
            return

        try:
            sim = self.movimientos.simular_descartar_capitulo(capitulo_id)
            self._enviar_json(sim)
        except ErrorValidacionEscena as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST, str(e))
        except ErrorSeguridadBandeja as e:
            self._enviar_error(HTTPStatus.FORBIDDEN, str(e))
        except ValueError as e:
            self._enviar_error(HTTPStatus.NOT_FOUND, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al simular descarte: {str(e)}")

    def _handle_capitulos_descartar(self, body: Dict[str, Any]):
        capitulo_id = body.get("id") or (body.get("simulacion") or {}).get("capitulo_id")
        nombre_confirmacion = str(body.get("nombre_confirmacion", "")).strip()

        if capitulo_id is None:
            cap_foco = self.db.obtener_capitulo_en_foco()
            if cap_foco and cap_foco.get("habilitado") and cap_foco.get("id"):
                capitulo_id = cap_foco["id"]
            else:
                self._enviar_error(HTTPStatus.BAD_REQUEST, "Se requiere el ID del capítulo a descartar.")
                return

        try:
            capitulo_id = int(capitulo_id)
        except (ValueError, TypeError):
            self._enviar_error(HTTPStatus.BAD_REQUEST, "El ID del capítulo debe ser numérico.")
            return

        if not nombre_confirmacion:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Debe ingresar el nombre del capítulo para confirmar el descarte.")
            return

        try:
            sim = self.movimientos.simular_descartar_capitulo(capitulo_id)
            resultado = self.movimientos.ejecutar_descartar_capitulo(sim, nombre_confirmacion)
            self.vigilante.escanear()
            self._enviar_json(resultado)
        except ErrorValidacionEscena as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST, str(e))
        except ErrorSeguridadBandeja as e:
            self._enviar_error(HTTPStatus.FORBIDDEN, str(e))
        except ValueError as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al descartar capítulo: {str(e)}")

    def _handle_capitulos_posponer_alerta(self, body: Dict[str, Any]):
        id_cap = body.get("id")
        self.db.posponer_alerta_capitulo(id_capitulo=int(id_cap) if id_cap else None)
        self._enviar_json({
            "exito": True,
            "mensaje": "Alerta de capítulo pospuesta exitosamente."
        })

    def _handle_guardar_capitulo_activo(self, body: Dict[str, Any]):
        habilitado = bool(body.get("habilitado", False))
        personaje = str(body.get("personaje", "lucie")).strip().lower()
        nombre = str(body.get("nombre", "")).strip()

        if habilitado:
            if not nombre:
                self._enviar_error(HTTPStatus.BAD_REQUEST, "El nombre del capítulo actual no puede estar vacío.")
                return
            valido, motivo = ValidadorEscenas.validar_nombre_escena(
                nombre, self.config.ruta_destino_base, self.config.ruta_descargas,
                es_existente_descargas=False, personaje=personaje
            )
            if not valido:
                self._enviar_error(HTTPStatus.BAD_REQUEST, f"Nombre de capítulo inválido: {motivo}")
                return

        if habilitado and nombre:
            try:
                self.movimientos.asegurar_carpeta_capitulo(personaje, nombre)
            except Exception:
                pass

        self.db.guardar_capitulo_activo(personaje, nombre, habilitado)
        self.vigilante.escanear()
        self._enviar_json({
            "exito": True,
            "capitulo_activo": {
                "habilitado": habilitado,
                "personaje": personaje,
                "nombre": nombre
            }
        })

    def _handle_clasificar_sin_identificar(self, body: Dict[str, Any]):
        hash_val = body.get("hash")
        ruta_archivo = body.get("ruta")
        es_proyecto = bool(body.get("es_proyecto", False))

        if not hash_val or not ruta_archivo:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Faltan campos obligatorios 'hash' y 'ruta'.")
            return

        self.db.guardar_decision_sin_identificar(hash_val, ruta_archivo, es_proyecto)
        # Forzar reescaneo y actualización inmediata del token de versión
        if hasattr(self.vigilante, "forzar_actualizacion_version"):
            self.vigilante.forzar_actualizacion_version()
        else:
            self.vigilante.escanear()
        self._enviar_json({"exito": True, "hash": hash_val, "es_proyecto": es_proyecto})

    def _handle_deshacer_clasificar_sin_identificar(self, body: Dict[str, Any]):
        hash_val = body.get("hash")
        ruta_archivo = body.get("ruta")

        if not hash_val and not ruta_archivo:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Se requiere al menos 'hash' o 'ruta'.")
            return

        revertido = self.db.revertir_decision_sin_identificar(hash_val, ruta_archivo)
        if hasattr(self.vigilante, "forzar_actualizacion_version"):
            self.vigilante.forzar_actualizacion_version()
        else:
            self.vigilante.escanear()
        self._enviar_json({"exito": True, "revertido": revertido, "hash": hash_val, "ruta": ruta_archivo})

    def _generar_html_simulacion_multilote(self, simulaciones_lotes: List[Dict[str, Any]]) -> str:
        total_archivos = sum(len(item["simulacion"].get("movimientos", [])) for item in simulaciones_lotes)
        bloques = [
            f'<div style="margin-bottom:16px; padding:12px; background:rgba(187,134,252,0.1); border:1px solid var(--accent); border-radius:6px;">'
            f'<strong>Simulación previa consolidada:</strong> Se moverán <strong>{total_archivos}</strong> archivos en <strong>{len(simulaciones_lotes)}</strong> lote(s).'
            f'</div>'
        ]
        for item in simulaciones_lotes:
            lote_id = html.escape(str(item.get("lote_id", "")))
            sim = item.get("simulacion", {})
            personaje = html.escape(str(item.get("personaje", "")))
            escena = html.escape(str(item.get("escena", "")))
            es_descargas = item.get("es_existente_descargas", False)
            desc_tag = " (En Descargas)" if es_descargas else ""
            bloques.append(
                f'<div style="margin-top:20px; margin-bottom:10px; padding:8px 12px; background:var(--card-alt); border-radius:6px;">'
                f'<strong>Lote {lote_id}</strong> &mdash; Destino: <code>{personaje} / {escena}{desc_tag}</code>'
                f'</div>'
            )
            bloques.append(sim.get("html") or generar_html_simulacion(sim))
        return "\n".join(bloques)

    def _handle_simular_mover(self, body: Dict[str, Any]):
        # Modo multi-lote
        if "lotes" in body and isinstance(body["lotes"], list):
            lotes_req = body["lotes"]
            if not lotes_req:
                self._enviar_error(HTTPStatus.BAD_REQUEST, "Lista de lotes vacía para simulación.")
                return

            simulaciones_lotes = []
            todos_movimientos = []
            destinos_reservados: Set[str] = set()

            try:
                for item in lotes_req:
                    lote_id = item.get("lote_id", "lote_desconocido")
                    archivos = item.get("archivos", [])
                    personaje = item.get("personaje", "lucie")
                    nombre_escena = str(item.get("escena", "")).strip()
                    es_descargas = bool(item.get("es_existente_descargas", False))

                    if not archivos or not nombre_escena:
                        self._enviar_error(HTTPStatus.BAD_REQUEST, f"El lote '{lote_id}' debe contener archivos y escena.")
                        return

                    sim_individual = self.movimientos.simular_movimiento_lote(
                        archivos=archivos,
                        personaje=personaje,
                        nombre_escena=nombre_escena,
                        es_existente_descargas=es_descargas,
                        destinos_reservados=destinos_reservados,
                        documentar_fecha=True
                    )
                    for mov in sim_individual.get("movimientos", []):
                        destinos_reservados.add(mov["destino"])

                    simulaciones_lotes.append({
                        "lote_id": lote_id,
                        "personaje": personaje,
                        "escena": sim_individual["escena"],
                        "es_existente_descargas": es_descargas,
                        "simulacion": sim_individual
                    })
                    todos_movimientos.extend(sim_individual.get("movimientos", []))

                html_consolidado = self._generar_html_simulacion_multilote(simulaciones_lotes)

                self._enviar_json({
                    "valido": True,
                    "es_multilote": True,
                    "total_lotes": len(simulaciones_lotes),
                    "total_archivos": len(todos_movimientos),
                    "movimientos": todos_movimientos,
                    "simulaciones_lotes": simulaciones_lotes,
                    "html": html_consolidado
                })
            except ErrorValidacionEscena as e:
                self._enviar_error(HTTPStatus.BAD_REQUEST, str(e))
            except ErrorSeguridadBandeja as e:
                self._enviar_error(HTTPStatus.FORBIDDEN, str(e))
            except Exception as e:
                self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error en simulación multi-lote: {str(e)}")
            return

        # Modo individual (un solo lote)
        archivos = body.get("archivos", [])
        personaje = body.get("personaje", "lucie")
        nombre_escena = str(body.get("escena", "")).strip()
        es_existente_descargas = bool(body.get("es_existente_descargas", False))

        if not archivos or not nombre_escena:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Faltan campos obligatorios 'archivos' y 'escena'.")
            return

        try:
            simulacion = self.movimientos.simular_movimiento_lote(
                archivos=archivos,
                personaje=personaje,
                nombre_escena=nombre_escena,
                es_existente_descargas=es_existente_descargas,
                documentar_fecha=True
            )
            self._enviar_json(simulacion)
        except ErrorValidacionEscena as e:
            self._enviar_error(HTTPStatus.BAD_REQUEST, str(e))
        except ErrorSeguridadBandeja as e:
            self._enviar_error(HTTPStatus.FORBIDDEN, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error en simulación: {str(e)}")

    def _handle_mover_lote(self, body: Dict[str, Any]):
        simulacion = body.get("simulacion")
        lote_id = body.get("lote_id", "lote_desconocido")

        if not simulacion:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Se requiere el objeto 'simulacion' previamente validado.")
            return

        # Si es simulación multi-lote
        if simulacion.get("es_multilote"):
            simulaciones_lotes = simulacion.get("simulaciones_lotes", [])
            if not simulaciones_lotes:
                self._enviar_error(HTTPStatus.BAD_REQUEST, "No hay lotes en la simulación multi-lote.")
                return

            resultados = []
            total_movidos = 0
            ultimo_id_operacion = ""
            try:
                for item in simulaciones_lotes:
                    sub_sim = item.get("simulacion")
                    sub_lote_id = item.get("lote_id", "lote_desconocido")
                    if sub_sim and "movimientos" in sub_sim:
                        res = self.movimientos.ejecutar_movimiento_lote(sub_sim, sub_lote_id)
                        total_movidos += res.get("total_movidos", 0)
                        ultimo_id_operacion = res.get("id_operacion", "")
                        resultados.append({
                            "lote_id": sub_lote_id,
                            "id_operacion": ultimo_id_operacion,
                            "total_movidos": res.get("total_movidos", 0),
                            "personaje": item.get("personaje"),
                            "escena": item.get("escena")
                        })
                self.vigilante.escanear()
                self._enviar_json({
                    "exito": True,
                    "es_multilote": True,
                    "total_movidos": total_movidos,
                    "resultados": resultados,
                    "id_operacion": ultimo_id_operacion,
                    "ultimo_id_operacion": ultimo_id_operacion
                })
            except ErrorSeguridadBandeja as e:
                self._enviar_error(HTTPStatus.FORBIDDEN, str(e))
            except Exception as e:
                self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al mover lotes listos: {str(e)}")
            return

        # Si es un lote individual
        if "movimientos" not in simulacion:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Se requiere el objeto 'simulacion' previamente validado con 'movimientos'.")
            return

        try:
            resultado = self.movimientos.ejecutar_movimiento_lote(simulacion, lote_id)
            self.vigilante.escanear()
            self._enviar_json(resultado)
        except ErrorSeguridadBandeja as e:
            self._enviar_error(HTTPStatus.FORBIDDEN, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al mover lote: {str(e)}")


    def _handle_deshacer(self, body: Dict[str, Any]):
        id_operacion = body.get("id_operacion")
        if not id_operacion:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'id_operacion' requerido.")
            return

        try:
            resultado = self.movimientos.deshacer_operacion(id_operacion)
            self.vigilante.escanear()
            self._enviar_json(resultado)
        except ErrorDeshacer as e:
            self._enviar_error(HTTPStatus.CONFLICT, str(e))
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al deshacer: {str(e)}")

    # =========================================================================
    # Handlers para Modo Edición con CapCut (Tramo 3)
    # =========================================================================

    def _handle_edicion_secciones(self, solo_cabeceras: bool = False):
        try:
            info_pen = detectar_pendrive(self.config)
            if not info_pen or not info_pen.get("conectado"):
                self._enviar_json({
                    "conectado": False,
                    "mensaje": "No hay pendrive vinculado conectado.",
                    "para_editar": [],
                    "en_edicion": obtener_sesiones_con_crudos_pendientes(self.db) if self.db else [],
                    "conteos_capitulo": {},
                    "exports_sin_asignar": self.db.obtener_exports_pendientes(estado="sin_asignar") if self.db else [],
                    "videos_completados": obtener_videos_completados(self.db) if self.db else [],
                    "sesiones_para_export": obtener_sesiones_para_export(self.db) if self.db else [],
                }, solo_cabeceras=solo_cabeceras)
                return

            punto_pen = info_pen.get("punto_montaje") or info_pen.get("ruta_montaje")
            carpeta_raiz = getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas")
            datos = obtener_secciones_edicion(punto_pen, self.db, carpeta_raiz=carpeta_raiz, vigilante=self.vigilante)
            datos["conectado"] = True
            datos["pendrive_info"] = info_pen
            self._enviar_json(datos, solo_cabeceras=solo_cabeceras)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al obtener secciones de edición: {e}", solo_cabeceras=solo_cabeceras)

    def _handle_capcut_exports(self, solo_cabeceras: bool = False):
        try:
            exports = obtener_videos_completados(self.db) if self.db else []
            self._enviar_json({"exports": exports}, solo_cabeceras=solo_cabeceras)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al obtener exports de CapCut: {e}", solo_cabeceras=solo_cabeceras)

    def _handle_edicion_crear_sesion(self, body: Dict[str, Any]):
        clips = body.get("clips")
        personaje = body.get("personaje")
        capitulo = body.get("capitulo")
        nombre_sesion = body.get("nombre_sesion")

        if not clips or not personaje or not capitulo:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campos 'clips', 'personaje' y 'capitulo' requeridos.")
            return

        try:
            sesion = crear_sesion(self.db, clips, personaje, capitulo, nombre_sesion)
            apertura = {}
            if body.get("abrir_carpeta") is True:
                try:
                    info = detectar_pendrive(self.config)
                    if not info or not info.get("conectado"):
                        raise ValueError("No hay pendrive vinculado conectado.")
                    ruta = obtener_carpeta_edicion(sesion, info.get("punto_montaje") or info.get("ruta_montaje"), self.config.carpeta_raiz_pendrive)
                    apertura = {"carpeta_edicion": ruta, "carpeta_abierta": abrir_carpeta_windows(ruta)}
                except (OSError, ValueError) as e:
                    apertura = {"carpeta_abierta": False, "error_abrir_carpeta": str(e)}
            self._enviar_json({"exito": True, "sesion": sesion, **apertura})
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al crear sesión: {e}")

    def _handle_edicion_sumar_videos(self, body):
        try:
            if not isinstance(body, dict) or type(body.get("sesion_id")) is not int:
                raise ValueError("Sesión inválida.")
            info = detectar_pendrive(self.config)
            if not info or not info.get("conectado"):
                raise ValueError("No hay pendrive vinculado conectado.")
            resultado = sumar_videos_sesion(self.db, body["sesion_id"], body.get("clips"),
                                           info.get("punto_montaje") or info.get("ruta_montaje"),
                                           self.config.carpeta_raiz_pendrive)
            self.vigilante.forzar_actualizacion_version()
            self._enviar_json({"exito": True, **resultado})
        except (ValueError, OSError) as e:
            self._enviar_error(HTTPStatus.CONFLICT, str(e))

    def _handle_edicion_cancelar_sesion(self, body: Dict[str, Any]):
        sesion_id = body.get("sesion_id")
        if not sesion_id:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'sesion_id' requerido.")
            return
        try:
            ok = cancelar_sesion(self.db, int(sesion_id))
            self._enviar_json({"exito": ok})
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al cancelar sesión: {e}")

    def _handle_edicion_terminar(self, body: Dict[str, Any]):
        sesion_id = body.get("sesion_id")
        if not sesion_id:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'sesion_id' requerido.")
            return

        info_pen = detectar_pendrive(self.config)
        if not info_pen or not info_pen.get("conectado"):
            self._enviar_error(HTTPStatus.BAD_REQUEST, "El pendrive debe estar conectado para finalizar la edición.")
            return

        punto_pen = info_pen.get("punto_montaje") or info_pen.get("ruta_montaje")
        carpeta_raiz = getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas")
        ruta_bit = getattr(self.movimientos, "ruta_bitacora", "bitacora_bandeja.jsonl") if self.movimientos else "bitacora_bandeja.jsonl"

        try:
            res = finalizar_edicion_crudos(self.db, int(sesion_id), punto_pen, carpeta_raiz, ruta_bit)
            if res["exito"]:
                res["export_final"] = self._revisar_export_sesion(int(sesion_id), punto_pen, carpeta_raiz, ruta_bit)
            self._enviar_json(res)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al finalizar edición: {e}")

    def _revisar_export_sesion(self, sesion_id, punto_pen, carpeta_raiz, ruta_bit):
        try:
            automatico = self.config.envio_exports_capcut == "automatico"
            estado = revisar_export_terminado(self.db, sesion_id, punto_pen, carpeta_raiz, ruta_bit, automatico,
                                             self.config.obtener_carpeta_exportacion_capcut())
            sesion = self.db.obtener_sesion_por_id(sesion_id)
            if automatico and estado["modo"] == "esperando_export" and not sesion.get("export_asociado"):
                if self.vigilante_capcut:
                    revision = self.vigilante_capcut.revisar_export_sesion(sesion, self.db.obtener_sesiones_edicion())
                    if revision["modo"] == "ambiguo":
                        registrar_exports_revision_ambigua(self.db, revision)
                        estado = {"modo": "ambiguo", "mensaje": "Hay varios exports o sesiones posibles. Elegí el video en Videos completados."}
                    elif revision["modo"] == "esperando_estabilidad":
                        estado = {"modo": "esperando_estabilidad", "mensaje": "Export encontrado. Se copiará automáticamente al estabilizarse y quedar libre de escritura."}
                    elif revision["modo"] == "error":
                        estado = revision
                else:
                    estado = {"modo": "error", "mensaje": "El vigilante de CapCut no está disponible. Reiniciá la bandeja para detectar el export."}
            return estado
        except (OSError, ValueError) as error:
            return {"modo": "error", "mensaje": str(error)}

    def _handle_edicion_revisar_export(self, body):
        try:
            if type(body.get("sesion_id")) is not int:
                raise ValueError("Sesión inválida.")
            pen = detectar_pendrive(self.config)
            if not pen or not pen.get("conectado"):
                raise ValueError("Conectá el pendrive para revisar el video final.")
            sesion = self.db.obtener_sesion_por_id(body["sesion_id"])
            if not sesion or not sesion.get("fecha_cierre"):
                raise ValueError("Primero confirmá Terminé de editar en esta sesión.")
            self.db.actualizar_sesion_edicion(sesion["id"], revision_export_solicitada=1)
            punto = pen.get("punto_montaje") or pen.get("ruta_montaje")
            ruta_bit = getattr(self.movimientos, "ruta_bitacora", "bitacora_bandeja.jsonl")
            estado = self._revisar_export_sesion(body["sesion_id"], punto, self.config.carpeta_raiz_pendrive, ruta_bit)
            self._enviar_json({"exito": estado["modo"] != "error", "export_final": estado})
        except (OSError, ValueError) as error:
            self._enviar_error(HTTPStatus.CONFLICT, str(error))

    def _handle_edicion_deshacer_terminar(self, body: Dict[str, Any]):
        sesion_id = body.get("sesion_id")
        if not sesion_id:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'sesion_id' requerido.")
            return

        info_pen = detectar_pendrive(self.config)
        if not info_pen or not info_pen.get("conectado"):
            self._enviar_error(HTTPStatus.BAD_REQUEST, "El pendrive debe estar conectado para deshacer.")
            return

        punto_pen = info_pen.get("punto_montaje") or info_pen.get("ruta_montaje")
        carpeta_raiz = getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas")
        ruta_bit = getattr(self.movimientos, "ruta_bitacora", "bitacora_bandeja.jsonl") if self.movimientos else "bitacora_bandeja.jsonl"

        try:
            res = deshacer_finalizar_edicion(self.db, int(sesion_id), punto_pen, carpeta_raiz, ruta_bit)
            self._enviar_json(res)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al deshacer finalización: {e}")

    def _handle_capcut_asignar_export(self, body: Dict[str, Any]):
        export_id = body.get("export_id")
        sesion_id = body.get("sesion_id")
        if not export_id:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'export_id' requerido.")
            return

        exp_list = self.db.obtener_exports_pendientes() if self.db else []
        target_exp = next((e for e in exp_list if e["id"] == int(export_id)), None)
        if not target_exp:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Export no encontrado.")
            return

        if target_exp["estado"] in ("copiado", "descartado"):
            self._enviar_error(HTTPStatus.CONFLICT, "El export ya fue enviado o descartado.")
            return
        if not esta_confinado_en_raiz(target_exp["ruta_origen"], self.config.obtener_carpeta_exportacion_capcut()):
            self._enviar_error(HTTPStatus.FORBIDDEN, "Export fuera de la carpeta de CapCut.")
            return
        sesion_id = sesion_id or target_exp.get("sesion_id")
        if not sesion_id:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Selecciona la edicion correspondiente al export.")
            return

        sesion = self.db.obtener_sesion_por_id(int(sesion_id))
        if not sesion:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Sesión no encontrada.")
            return

        try:
            verificar_version_export(target_exp)
        except (ValueError, OSError) as e:
            self._enviar_error(HTTPStatus.CONFLICT, str(e))
            return
        self.db.actualizar_export_pendiente(int(export_id), sesion_id=int(sesion_id), estado="pendiente_copia", error=None, envio_automatico_bloqueado=0)
        self.db.actualizar_sesion_edicion(int(sesion_id), export_asociado=target_exp["ruta_origen"])

        info_pen = detectar_pendrive(self.config)
        if info_pen and info_pen.get("conectado"):
            punto_pen = info_pen.get("punto_montaje") or info_pen.get("ruta_montaje")
            carpeta_raiz = getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas")
            ruta_bit = getattr(self.movimientos, "ruta_bitacora", "bitacora_bandeja.jsonl") if self.movimientos else "bitacora_bandeja.jsonl"
            try:
                res_copia = copiar_export_a_videos_completos(
                    target_exp["ruta_origen"], sesion, punto_pen, self.db, carpeta_raiz, ruta_bit
                )
                self.db.actualizar_export_pendiente(
                    int(export_id),
                    estado="copiado",
                    fecha_copia=datetime.datetime.now().isoformat(),
                    sha256=res_copia.get("sha256"),
                    error=None,
                )
                self._enviar_json({"exito": True, "resultado_copia": res_copia})
            except Exception as e:
                self.db.actualizar_export_pendiente(int(export_id), error=str(e))
                self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al copiar export: {e}")
        else:
            self.db.actualizar_export_pendiente(int(export_id), estado="pendiente_copia")
            self._enviar_json({"exito": True, "modo": "encolado_offline"})

    def _handle_capcut_descartar_export(self, body: Dict[str, Any]):
        export_id = body.get("export_id")
        if not export_id:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'export_id' requerido.")
            return
        self.db.actualizar_export_pendiente(int(export_id), estado="descartado")
        self._enviar_json({"exito": True})

    def _handle_capcut_deshacer_completo(self, body: Dict[str, Any]):
        video_completo_ruta = body.get("video_completo_ruta")
        if not video_completo_ruta:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Campo 'video_completo_ruta' requerido.")
            return

        info_pen = detectar_pendrive(self.config)
        if not info_pen or not info_pen.get("conectado"):
            self._enviar_error(HTTPStatus.BAD_REQUEST, "El pendrive debe estar conectado para deshacer.")
            return

        punto_pen = info_pen.get("punto_montaje") or info_pen.get("ruta_montaje")
        carpeta_raiz = getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas")
        ruta_bit = getattr(self.movimientos, "ruta_bitacora", "bitacora_bandeja.jsonl") if self.movimientos else "bitacora_bandeja.jsonl"

        try:
            res = deshacer_copia_completo(video_completo_ruta, punto_pen, self.db, carpeta_raiz, ruta_bit)
            self._enviar_json(res)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al deshacer copia de completo: {e}")

    def _handle_capcut_escanear(self, body: Dict[str, Any]):
        if self.vigilante_capcut:
            try:
                nuevos = self.vigilante_capcut.escanear()
                self._enviar_json({"exito": True, "nuevos": nuevos})
            except Exception as e:
                self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al escanear CapCut: {e}")
        else:
            self._enviar_json({"exito": True, "nuevos": []})

    def do_PUT(self):
        self._enviar_error(HTTPStatus.METHOD_NOT_ALLOWED, "Método PUT no permitido.")

    def do_DELETE(self):
        self._enviar_error(HTTPStatus.METHOD_NOT_ALLOWED, "Método DELETE no permitido.")

    def do_PATCH(self):
        self._enviar_error(HTTPStatus.METHOD_NOT_ALLOWED, "Método PATCH no permitido.")


    def _servir_estatico(self, nombre_archivo: str, content_type: str, solo_cabeceras: bool = False):
        # Lista blanca fija e inmutable
        if nombre_archivo not in ("panel.js", "panel.css", "wifi.js"):
            self._enviar_error(HTTPStatus.NOT_FOUND, "Archivo estático no permitido.", solo_cabeceras=solo_cabeceras)
            return

        ruta_archivo = os.path.join(RUTA_WEB, nombre_archivo)
        if not esta_confinado_en_raiz(ruta_archivo, RUTA_WEB):
            self._enviar_error(HTTPStatus.FORBIDDEN, "Acceso no permitido.", solo_cabeceras=solo_cabeceras)
            return

        if not os.path.isfile(ruta_archivo):
            self._enviar_error(HTTPStatus.NOT_FOUND, "Recurso no encontrado.", solo_cabeceras=solo_cabeceras)
            return

        try:
            with open(ruta_archivo, "rb") as f:
                cuerpo = f.read()
        except Exception:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error al leer recurso estático.", solo_cabeceras=solo_cabeceras)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        if not solo_cabeceras:
            self.wfile.write(cuerpo)

    def _servir_html_spa(self, solo_cabeceras: bool = False):
        ruta_archivo = os.path.join(RUTA_WEB, "panel.html")
        try:
            with open(ruta_archivo, "r", encoding="utf-8", newline="\n") as f:
                plantilla = f.read()
        except Exception:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error al cargar la plantilla web.", solo_cabeceras=solo_cabeceras)
            return

        refresco = str(getattr(self.config, "refresco_panel_segundos", 4))
        puerto = str(self.config.puerto_servidor)

        # Inyecciones dinámicas seguras
        html_salida = (
            plantilla
            .replace("__TOKEN_CSRF__", self.token_csrf)
            .replace("__REFRESCO__", refresco)
            .replace("__PUERTO__", puerto)
        )
        cuerpo = html_salida.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        if not solo_cabeceras:
            self.wfile.write(cuerpo)


class ServidorBandejaHTTPServer(ThreadingHTTPServer):
    """Servidor HTTP multihilo adaptado para instancia única y exclusividad de socket."""

    def server_bind(self):
        if os.name == "nt":
            self.allow_reuse_address = False
            so_exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", -5)
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, so_exclusive, 1)
            except OSError:
                pass
        super().server_bind()


def crear_servidor(config: ConfiguracionBandeja, db: GestorBaseDatosBandeja,
                   vigilante: VigilanteBandeja, movimientos: GestorMovimientosBandeja,
                   miniaturas: GeneradorMiniaturas, token_csrf: Optional[str] = None,
                   vigilante_capcut: Optional[Any] = None) -> ServidorBandejaHTTPServer:
    """Crea y configura la instancia de ThreadingHTTPServer con política de socket por plataforma."""
    token = token_csrf or secrets.token_urlsafe(32)

    class CustomHandler(HandlerServidorBandeja):
        pass

    CustomHandler.config = config
    CustomHandler.db = db
    CustomHandler.vigilante = vigilante
    CustomHandler.vigilante_capcut = vigilante_capcut
    CustomHandler.movimientos = movimientos
    CustomHandler.miniaturas = miniaturas
    CustomHandler.token_csrf = token
    CustomHandler.eliminacion = GestorEliminacionPendrive(config)
    CustomHandler.publicacion = GestorPublicacion(config, db)

    servidor = ServidorBandejaHTTPServer((config.host_servidor, config.puerto_servidor), CustomHandler)
    servidor.daemon_threads = True
    if config.puerto_servidor == 0:
        config.puerto_servidor = servidor.server_address[1]
    return servidor



