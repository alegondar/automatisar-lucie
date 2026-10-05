#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/servidor.py

Servidor HTTP multihilo y manejador de peticiones para el panel web de la
bandeja de descargas. Gestiona endpoints REST de la API y sirve activos
estáticos exclusivamente mediante lista blanca estricta con inyección segura de CSRF.
"""

import os
import json
import html
import secrets
import hmac
import shutil
import subprocess
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("bandeja_descargas")

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
)
from bandeja.vigilante import VigilanteBandeja

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
    movimientos: GestorMovimientosBandeja = None
    miniaturas: GeneradorMiniaturas = None
    token_csrf: str = ""

    def _enviar_json(self, datos: Any, codigo: int = 200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _enviar_error(self, codigo: int, mensaje: str):
        self._enviar_json({"error": mensaje, "codigo": codigo}, codigo=codigo)

    def _validar_host(self) -> bool:
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
            self._enviar_error(HTTPStatus.FORBIDDEN, f"Cabecera Host no permitida: '{host_header}'")
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
        elif ruta == "/panel.css":
            self._servir_estatico("panel.css", "text/css; charset=utf-8")
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
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada.")

    def _handle_pendrive_estado(self):
        try:
            res = obtener_estado_pendrive(self.config, self.db, timeout_segundos=3.0)
            self._enviar_json(res)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al consultar estado de pendrive: {e}")

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

        if ruta == "/api/clasificar-sin-identificar":
            self._handle_clasificar_sin_identificar(body)
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
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Endpoint POST no encontrado.")

    def _handle_pendrive_envio_simular(self, body: Dict[str, Any]):
        capitulos = body.get("capitulos")
        if isinstance(capitulos, str):
            capitulos = [capitulos]
        elif not isinstance(capitulos, list):
            capitulos = None
        try:
            res = simular_envio_capitulos(capitulos, self.config, self.db)
            self._enviar_json(res)
        except Exception as e:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error al simular envío: {e}")

    def _handle_pendrive_envio(self, body: Dict[str, Any]):
        capitulos = body.get("capitulos")
        simulacion = body.get("simulacion")
        if isinstance(capitulos, str):
            capitulos = [capitulos]
        elif not isinstance(capitulos, list):
            capitulos = None

        arg = simulacion if simulacion else capitulos
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
        # Forzar reescaneo para reflejar la decisión
        self.vigilante.escanear()
        self._enviar_json({"exito": True, "hash": hash_val, "es_proyecto": es_proyecto})

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
                        destinos_reservados=destinos_reservados
                    )
                    for mov in sim_individual.get("movimientos", []):
                        destinos_reservados.add(mov["destino"])

                    simulaciones_lotes.append({
                        "lote_id": lote_id,
                        "personaje": personaje,
                        "escena": nombre_escena,
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
                es_existente_descargas=es_existente_descargas
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

    def do_PUT(self):
        self._enviar_error(HTTPStatus.METHOD_NOT_ALLOWED, "Método PUT no permitido.")

    def do_DELETE(self):
        self._enviar_error(HTTPStatus.METHOD_NOT_ALLOWED, "Método DELETE no permitido.")

    def do_PATCH(self):
        self._enviar_error(HTTPStatus.METHOD_NOT_ALLOWED, "Método PATCH no permitido.")


    def _servir_estatico(self, nombre_archivo: str, content_type: str):
        # Lista blanca fija e inmutable
        if nombre_archivo not in ("panel.js", "panel.css"):
            self._enviar_error(HTTPStatus.NOT_FOUND, "Archivo estático no permitido.")
            return

        ruta_archivo = os.path.join(RUTA_WEB, nombre_archivo)
        if not os.path.isfile(ruta_archivo):
            self._enviar_error(HTTPStatus.NOT_FOUND, "Recurso no encontrado.")
            return

        try:
            with open(ruta_archivo, "rb") as f:
                cuerpo = f.read()
        except Exception:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error al leer recurso estático.")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _servir_html_spa(self):
        ruta_archivo = os.path.join(RUTA_WEB, "panel.html")
        try:
            with open(ruta_archivo, "r", encoding="utf-8") as f:
                plantilla = f.read()
        except Exception:
            self._enviar_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error al cargar la plantilla web.")
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
        self.wfile.write(cuerpo)


def crear_servidor(config: ConfiguracionBandeja, db: GestorBaseDatosBandeja,
                   vigilante: VigilanteBandeja, movimientos: GestorMovimientosBandeja,
                   miniaturas: GeneradorMiniaturas, token_csrf: Optional[str] = None) -> ThreadingHTTPServer:
    """Crea y configura la instancia de ThreadingHTTPServer."""
    token = token_csrf or secrets.token_urlsafe(32)

    class CustomHandler(HandlerServidorBandeja):
        pass

    CustomHandler.config = config
    CustomHandler.db = db
    CustomHandler.vigilante = vigilante
    CustomHandler.movimientos = movimientos
    CustomHandler.miniaturas = miniaturas
    CustomHandler.token_csrf = token

    servidor = ThreadingHTTPServer((config.host_servidor, config.puerto_servidor), CustomHandler)
    if config.puerto_servidor == 0:
        config.puerto_servidor = servidor.server_address[1]
    return servidor


