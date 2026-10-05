#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja_descargas.py

Módulo de detección, agrupación en lotes y organización segura de contenido nuevo
del proyecto Lucie que cae en ~/Descargas hacia la jerarquía de personaje y escena.

Cumple estrictamente con las 7 Reglas de Oro del proyecto:
- PROHIBICIÓN ABSOLUTA DE BORRADO Y SOBRESCRITURA DESTRUCTIVA.
- Simulación previa obligatoria (dry-run).
- Verificación de destino (nunca sobrescribir).
- Registro auditable .jsonl y función de deshacer con os.rename (sin borrar).
- Confinamiento estricto a ~/Descargas.
- Análisis estático AST anti-borrado: 0 violaciones.
"""

import argparse
import concurrent.futures
import datetime
import fnmatch
import glob
import hashlib
import hmac
import html
import json
import contextlib
import logging
import os
import platform
import re
import secrets
import shutil
import sqlite3
import string
import subprocess
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("bandeja_descargas")
if not logger.handlers:
    _handler_log = logging.StreamHandler()
    _handler_log.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_handler_log)
    logger.setLevel(logging.INFO)

from bandeja.config import (
    RUTA_DESCARGAS_DEFECTO,
    RUTA_DESTINO_DEFECTO,
    CARPETA_RAIZ_PENDRIVE_DEFECTO,
    EXTENSIONES_MEDIA_DEFECTO,
    EXTENSIONES_IMAGENES_DEFECTO,
    EXTENSIONES_VIDEOS_DEFECTO,
    EXTENSIONES_TEMP_DEFECTO,
    NOMBRES_RESERVADOS_WINDOWS,
    CARACTERES_INVALIDOS_ESCENA,
    ErrorSeguridadBandeja,
    ErrorValidacionEscena,
    ErrorDeshacer,
    calcular_sha256,
    formatear_bytes,
    ConfiguracionBandeja,
)


from bandeja.db import GestorBaseDatosBandeja
from bandeja.clasificacion import (
    clasificar_familia_medio,
    FiltroListaBlanca,
    ValidadorEscenas,
    asegurar_carpeta_capitulo,
)
from bandeja.lotes import (
    obtener_fecha_llegada,
    DetectorDescargasActivas,
    AgrupadorLotes,
)
from bandeja.capitulos import (
    calcular_balance_capitulo,
    es_capitulo_olvidado,
    simular_descartar_capitulo,
    ejecutar_descartar_capitulo,
    revertir_descarte_capitulo,
)



from bandeja.movimientos import (
    generar_html_simulacion,
    GestorMovimientosBandeja,
)



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


# ==============================================================================
# MÓDULO DE ENVÍO A PENDRIVE (LucieSinReglas) - DETECCIÓN, MARCADOR Y SEGURIDAD
# ==============================================================================

NOMBRE_MARCADOR_PENDRIVE = ".lucie_pendrive.json"
CARPETA_RAIZ_PENDRIVE_DEFECTO = "LucieSinReglas"
NOMBRE_MANIFIESTO_PENDRIVE = "manifiesto.jsonl"


def validar_marcador_pendrive(datos: Any) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Valida la estructura y contenido del marcador de identidad .lucie_pendrive.json.
    Esquema obligatorio:
    - id: UUIDv4 canónico en minúsculas.
    - creado: timestamp en formato ISO 8601.
    - version: entero igual a 1.
    Retorna (es_valido, datos_validados, mensaje_error).
    """
    if not isinstance(datos, dict):
        return False, None, "El contenido del marcador debe ser un objeto JSON."

    if "id" not in datos or "creado" not in datos or "version" not in datos:
        return False, None, "El marcador no contiene los campos obligatorios ('id', 'creado', 'version')."

    # Validar UUIDv4
    id_str = str(datos["id"]).strip()
    try:
        val_uuid = uuid.UUID(id_str, version=4)
        if str(val_uuid).lower() != id_str.lower():
            return False, None, f"El identificador '{id_str}' no es un UUIDv4 válido."
    except (ValueError, AttributeError, TypeError):
        return False, None, f"El identificador '{id_str}' no es un UUIDv4 válido."

    # Validar fecha ISO
    creado_str = str(datos["creado"]).strip()
    if not creado_str:
        return False, None, "El campo 'creado' no puede estar vacío."
    try:
        datetime.datetime.fromisoformat(creado_str)
    except Exception:
        # Permitir ISO con sufijo 'Z' si python < 3.11
        if creado_str.endswith("Z"):
            try:
                datetime.datetime.fromisoformat(creado_str[:-1] + "+00:00")
            except Exception:
                return False, None, f"El campo 'creado' ('{creado_str}') no tiene formato ISO 8601 válido."
        else:
            return False, None, f"El campo 'creado' ('{creado_str}') no tiene formato ISO 8601 válido."

    # Validar versión
    try:
        ver = int(datos["version"])
        if ver != 1:
            return False, None, f"Versión de marcador no soportada: {ver} (se requiere versión 1)."
    except (ValueError, TypeError):
        return False, None, "El campo 'version' debe ser un número entero."

    marcador_limpio = {
        "id": str(val_uuid).lower(),
        "creado": creado_str,
        "version": 1
    }
    return True, marcador_limpio, None


def leer_marcador_pendrive(ruta_raiz: str) -> Optional[Dict[str, Any]]:
    """
    Lee e interpreta el marcador .lucie_pendrive.json desde la raíz de una unidad.
    Retorna los datos validados o None si no existe o es inválido.
    """
    if not ruta_raiz or not os.path.isdir(ruta_raiz):
        return None

    ruta_marcador = os.path.join(ruta_raiz, NOMBRE_MARCADOR_PENDRIVE)
    if not os.path.isfile(ruta_marcador):
        return None

    try:
        with open(ruta_marcador, "r", encoding="utf-8") as f:
            datos = json.load(f)
        valido, marcador, err = validar_marcador_pendrive(datos)
        if valido:
            return marcador
        logger.warning(f"Marcador inválido en '{ruta_marcador}': {err}")
        return None
    except Exception as e:
        logger.warning(f"Error al leer marcador en '{ruta_marcador}': {e}")
        return None


from bandeja.plataforma import (
    obtener_sistema_archivos,
    obtener_espacio_disco,
    buscar_puntos_montaje_candidatos,
    ejecutar_con_timeout as ejecutar_lectura_pendrive_con_timeout,
    notificar_escritorio,
)


def detectar_pendrive(config: Optional[ConfiguracionBandeja] = None) -> Optional[Dict[str, Any]]:
    """
    Busca unidades montadas que posean el marcador de identidad .lucie_pendrive.json válido.
    Retorna la información del pendrive detectado o None si no hay ninguno.
    """
    carpeta_raiz = config.carpeta_raiz_pendrive if config else CARPETA_RAIZ_PENDRIVE_DEFECTO
    candidatos = buscar_puntos_montaje_candidatos(config)

    for cand in candidatos:
        marcador = leer_marcador_pendrive(cand)
        if marcador:
            fs = obtener_sistema_archivos(cand)
            espacio = obtener_espacio_disco(cand)
            return {
                "conectado": True,
                "sin_respuesta": False,
                "ruta_montaje": cand,
                "punto_montaje": cand,
                "id": marcador["id"],
                "creado": marcador["creado"],
                "version": marcador["version"],
                "sistema_archivos": fs,
                "espacio_total_bytes": espacio["total"],
                "espacio_libre_bytes": espacio["libre"],
                "espacio_usado_bytes": espacio["usado"],
                "carpeta_raiz_confinada": os.path.join(cand, carpeta_raiz)
            }

    return None


def detectar_pendrive_seguro(config: Optional[ConfiguracionBandeja] = None, timeout_segundos: float = 3.0) -> Dict[str, Any]:
    """
    Ejecuta detectar_pendrive fuera del hilo principal con límite de tiempo de 3 s.
    Garantiza que el servidor HTTP nunca se congele si un pendrive defectuoso cuelga las llamadas I/O.
    """
    res = ejecutar_lectura_pendrive_con_timeout(detectar_pendrive, config, timeout_segundos=timeout_segundos)
    if res is None:
        return {"conectado": False, "sin_respuesta": False}
    return res


def detectar_unidad_candidata_sin_vincular(config: Optional[ConfiguracionBandeja] = None) -> Optional[Dict[str, Any]]:
    """
    Busca unidades montadas candidatas que NO posean el marcador .lucie_pendrive.json,
    para permitir la acción de 'Vincular pendrive'.
    """
    candidatos = buscar_puntos_montaje_candidatos(config)
    for cand in candidatos:
        marcador = leer_marcador_pendrive(cand)
        if not marcador:
            fs = obtener_sistema_archivos(cand)
            espacio = obtener_espacio_disco(cand)
            return {
                "punto_montaje": cand,
                "sistema_archivos": fs,
                "espacio_total_bytes": espacio["total"],
                "espacio_libre_bytes": espacio["libre"],
                "espacio_usado_bytes": espacio["usado"]
            }
    return None


def simular_vinculacion_pendrive(punto_montaje: str, config: Optional[ConfiguracionBandeja] = None) -> Dict[str, Any]:
    """
    Simulación previa obligatoria para vincular un pendrive.
    Muestra la unidad candidata (punto de montaje, sistema de archivos, espacio)
    y detalla la estructura base que se creará sin escribir nada en disco.
    """
    if not punto_montaje:
        raise ValueError("El punto de montaje no puede estar vacío.")

    punto_real = os.path.realpath(punto_montaje)
    if not os.path.isdir(punto_real):
        raise FileNotFoundError(f"La ruta especificada no existe o no es un directorio: '{punto_montaje}' (resuelta como '{punto_real}')")

    ruta_marcador = os.path.join(punto_real, NOMBRE_MARCADOR_PENDRIVE)
    if os.path.exists(ruta_marcador):
        marcador_existente = leer_marcador_pendrive(punto_real)
        id_existente = marcador_existente.get("id") if marcador_existente else "desconocido"
        raise ValueError(f"La unidad ya posee un marcador '{NOMBRE_MARCADOR_PENDRIVE}' con ID '{id_existente}'. Prohibida la sobrescritura.")

    carpeta_raiz = config.carpeta_raiz_pendrive if config else CARPETA_RAIZ_PENDRIVE_DEFECTO
    fs = obtener_sistema_archivos(punto_real)
    espacio = obtener_espacio_disco(punto_real)

    subcarpetas_base = [
        os.path.join(carpeta_raiz, ".lucie"),
        os.path.join(carpeta_raiz, "videos sin editar"),
        os.path.join(carpeta_raiz, "videos ya editados"),
        os.path.join(carpeta_raiz, "videos completos"),
        os.path.join(carpeta_raiz, "imagenes"),
    ]

    return {
        "puede_vincular": True,
        "punto_montaje": punto_real,
        "sistema_archivos": fs,
        "espacio_total_bytes": espacio["total"],
        "espacio_libre_bytes": espacio["libre"],
        "espacio_usado_bytes": espacio["usado"],
        "carpeta_raiz_pendrive": carpeta_raiz,
        "marcador_archivo": NOMBRE_MARCADOR_PENDRIVE,
        "subcarpetas_base": subcarpetas_base
    }


def vincular_pendrive(punto_montaje: str, config: Optional[ConfiguracionBandeja] = None) -> Dict[str, Any]:
    """
    Crea el marcador de identidad .lucie_pendrive.json con modo exclusivo ('xb')
    y la estructura base LucieSinReglas/ con mkdir (exist_ok=True).
    Nunca sobrescribe un marcador existente.
    """
    simulacion = simular_vinculacion_pendrive(punto_montaje, config)
    punto_real = simulacion["punto_montaje"]
    carpeta_raiz = simulacion["carpeta_raiz_pendrive"]

    ruta_marcador = os.path.join(punto_real, NOMBRE_MARCADOR_PENDRIVE)
    if os.path.exists(ruta_marcador):
        raise ValueError(f"Conflicto de seguridad: el marcador '{NOMBRE_MARCADOR_PENDRIVE}' ya existe. Nunca se sobrescribe.")

    id_nuevo = str(uuid.uuid4()).lower()
    creado = datetime.datetime.now().isoformat()
    datos_marcador = {
        "id": id_nuevo,
        "creado": creado,
        "version": 1
    }

    # Creación exclusiva obligatoria ('xb')
    contenido_bytes = json.dumps(datos_marcador, indent=2).encode("utf-8")
    with open(ruta_marcador, "xb") as f:
        f.write(contenido_bytes)
        f.flush()
        os.fsync(f.fileno())

    # Crear estructura base en el pendrive (videos ya editados y videos completos vacíos)
    raiz_confinada = os.path.join(punto_real, carpeta_raiz)
    directorios_a_crear = [
        os.path.join(raiz_confinada, ".lucie"),
        os.path.join(raiz_confinada, "videos sin editar"),
        os.path.join(raiz_confinada, "videos ya editados"),
        os.path.join(raiz_confinada, "videos completos"),
        os.path.join(raiz_confinada, "imagenes"),
    ]
    for d in directorios_a_crear:
        os.makedirs(d, exist_ok=True)

    return {
        "exito": True,
        "mensaje": f"Pendrive vinculado exitosamente con ID '{id_nuevo}'. Estructura '{carpeta_raiz}' creada.",
        "id": id_nuevo,
        "creado": creado,
        "punto_montaje": punto_real,
        "carpeta_raiz_confinada": raiz_confinada,
        "directorios_creados": directorios_a_crear
    }


def leer_manifiesto_pendrive(ruta_montaje: str, carpeta_raiz: str = "LucieSinReglas") -> List[Dict[str, Any]]:
    """
    Lee las entradas históricas de <pendrive>/<carpeta_raiz>/.lucie/manifiesto.jsonl.
    Retorna la lista de diccionarios registrados.
    """
    ruta_manifiesto = os.path.join(ruta_montaje, carpeta_raiz, ".lucie", "manifiesto.jsonl")
    if not os.path.isfile(ruta_manifiesto):
        return []

    entradas = []
    try:
        with open(ruta_manifiesto, "r", encoding="utf-8", errors="replace") as f:
            for linea in f:
                linea_str = linea.strip()
                if linea_str:
                    try:
                        entradas.append(json.loads(linea_str))
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        logger.warning(f"Error al leer manifiesto en '{ruta_manifiesto}': {e}")
    return entradas


def _es_extension_video(ext: str) -> bool:
    return ext.lower() in (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")


def _es_extension_foto(ext: str) -> bool:
    return ext.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff")


def _es_extension_multimedia(ext: str) -> bool:
    return _es_extension_video(ext) or _es_extension_foto(ext)


def escanear_capitulos_para_envio(ruta_destino_base: str) -> List[Dict[str, Any]]:
    """
    Escanea la sala de espera ~/Descargas/_lucie/<personaje>/<capítulo>/
    omitiendo carpetas del sistema (_enviados, _revertidos, _descartados, _a_revisar).
    Retorna lista de capítulos disponibles con sus archivos.
    """
    ruta_real_base = os.path.realpath(ruta_destino_base)
    if not os.path.isdir(ruta_real_base):
        return []

    carpetas_ignoradas = {"_enviados", "_revertidos", "_descartados", "_a_revisar"}
    resultado = []

    for pers in sorted(os.listdir(ruta_real_base)):
        if pers.startswith("_") or pers in carpetas_ignoradas:
            continue
        ruta_pers = os.path.join(ruta_real_base, pers)
        if not os.path.isdir(ruta_pers):
            continue

        for cap in sorted(os.listdir(ruta_pers)):
            if cap.startswith("_") or cap in carpetas_ignoradas or cap in ("fotos", "videos"):
                continue
            ruta_cap = os.path.join(ruta_pers, cap)
            if not os.path.isdir(ruta_cap):
                continue

            resultado.append({
                "personaje": pers,
                "capitulo": cap,
                "ruta_absoluta": ruta_cap
            })

    return resultado


def listar_archivos_part_huerfanos(punto_montaje: str, carpeta_raiz: str = "LucieSinReglas") -> List[Dict[str, Any]]:
    """
    Busca de manera no destructiva archivos incompletos con extensión .part
    dentro de <punto_montaje>/<carpeta_raiz>/.
    NUNCA borra ni renombra estos archivos: solo los lista para visualización y diagnóstico.
    """
    if not punto_montaje or not os.path.isdir(punto_montaje):
        return []
    raiz_completa = os.path.join(punto_montaje, carpeta_raiz)
    if not os.path.isdir(raiz_completa):
        return []

    huerfanos = []
    try:
        for root, dirs, files in os.walk(raiz_completa):
            for f in files:
                if f.endswith(".part"):
                    p = os.path.join(root, f)
                    try:
                        st = os.stat(p)
                        sz = st.st_size
                        mtime = datetime.datetime.fromtimestamp(st.st_mtime).isoformat()
                    except OSError:
                        sz = 0
                        mtime = ""
                    huerfanos.append({
                        "nombre": f,
                        "ruta_relativa": os.path.relpath(p, raiz_completa),
                        "ruta_absoluta": p,
                        "tamanio_bytes": sz,
                        "tamanio_fmt": formatear_bytes(sz),
                        "fecha_modificacion": mtime
                    })
    except Exception as e:
        logger.warning(f"Error al listar archivos .part en pendrive: {e}")
    return sorted(huerfanos, key=lambda x: x["nombre"])


def _leer_estado_pendrive_raw(config: Optional[ConfiguracionBandeja] = None,
                              db: Optional[GestorBaseDatosBandeja] = None) -> Dict[str, Any]:
    """Rutina interna de lectura del estado físico del pendrive."""
    cfg = config or ConfiguracionBandeja()
    info = detectar_pendrive(cfg)
    if not info:
        cand = detectar_unidad_candidata_sin_vincular(cfg)
        return {
            "conectado": False,
            "sin_respuesta": False,
            "id": None,
            "punto_montaje": cand.get("punto_montaje") if cand else None,
            "sistema_archivos": cand.get("sistema_archivos") if cand else None,
            "espacio_libre_bytes": cand.get("espacio_libre_bytes", 0) if cand else 0,
            "espacio_libre_fmt": formatear_bytes(cand.get("espacio_libre_bytes", 0)) if cand else "0 B",
            "espacio_total_bytes": cand.get("espacio_total_bytes", 0) if cand else 0,
            "espacio_total_fmt": formatear_bytes(cand.get("espacio_total_bytes", 0)) if cand else "0 B",
            "espacio_usado_bytes": cand.get("espacio_usado_bytes", 0) if cand else 0,
            "unidad_candidata": cand,
            "archivos_part_huerfanos": [],
            "archivos_pendientes_conteo": 0,
            "capitulos_pendientes_conteo": 0,
            "capitulos_pendientes": [],
            "banner_reactivo": None
        }

    punto = info.get("punto_montaje") or info.get("ruta_montaje")
    carpeta_raiz = getattr(cfg, "carpeta_raiz_pendrive", CARPETA_RAIZ_PENDRIVE_DEFECTO)
    part_files = listar_archivos_part_huerfanos(punto, carpeta_raiz)

    # Conteo y desglose de archivos pendientes en sala de espera
    base_destino = getattr(cfg, "ruta_destino_base", RUTA_DESTINO_DEFECTO)
    caps = escanear_capitulos_para_envio(base_destino)
    tot_arch = 0
    sub_f = getattr(cfg, "subcarpeta_fotos", "fotos")
    sub_v = getattr(cfg, "subcarpeta_videos", "videos")
    caps_detalle = []

    for c in caps:
        ruta_c = c["ruta_absoluta"]
        cant_vids = 0
        cant_fotos = 0
        bytes_cap = 0

        d_v = os.path.join(ruta_c, sub_v)
        if os.path.isdir(d_v):
            for x in os.listdir(d_v):
                p = os.path.join(d_v, x)
                if os.path.isfile(p) and not x.startswith("."):
                    cant_vids += 1
                    try:
                        bytes_cap += os.path.getsize(p)
                    except OSError:
                        pass

        d_f = os.path.join(ruta_c, sub_f)
        if os.path.isdir(d_f):
            for x in os.listdir(d_f):
                p = os.path.join(d_f, x)
                if os.path.isfile(p) and not x.startswith("."):
                    cant_fotos += 1
                    try:
                        bytes_cap += os.path.getsize(p)
                    except OSError:
                        pass

        for x in os.listdir(ruta_c):
            p = os.path.join(ruta_c, x)
            if os.path.isfile(p) and not x.startswith("."):
                _, ext = os.path.splitext(x)
                if _es_extension_video(ext):
                    cant_vids += 1
                    try:
                        bytes_cap += os.path.getsize(p)
                    except OSError:
                        pass
                elif _es_extension_foto(ext):
                    cant_fotos += 1
                    try:
                        bytes_cap += os.path.getsize(p)
                    except OSError:
                        pass

        tot_c = cant_vids + cant_fotos
        if tot_c > 0:
            tot_arch += tot_c
            caps_detalle.append({
                "personaje": c["personaje"],
                "capitulo": c["capitulo"],
                "videos": cant_vids,
                "fotos": cant_fotos,
                "total_archivos": tot_c,
                "bytes_totales": bytes_cap,
                "bytes_totales_fmt": formatear_bytes(bytes_cap)
            })

    banner = None
    if tot_arch > 0:
        banner = {
            "mostrar": True,
            "mensaje": f"Pendrive detectado: {tot_arch} archivo(s) de {len(caps_detalle)} capítulo(s) listos para enviar",
            "archivos": tot_arch,
            "capitulos": len(caps_detalle)
        }

    esp_libre = info.get("espacio_libre_bytes", 0)
    esp_total = info.get("espacio_total_bytes", 0)
    esp_usado = info.get("espacio_usado_bytes", 0)

    return {
        "conectado": True,
        "sin_respuesta": False,
        "id": info["id"],
        "punto_montaje": punto,
        "sistema_archivos": info.get("sistema_archivos"),
        "espacio_libre_bytes": esp_libre,
        "espacio_libre_fmt": formatear_bytes(esp_libre),
        "espacio_total_bytes": esp_total,
        "espacio_total_fmt": formatear_bytes(esp_total),
        "espacio_usado_bytes": esp_usado,
        "unidad_candidata": None,
        "archivos_part_huerfanos": part_files,
        "archivos_pendientes_conteo": tot_arch,
        "capitulos_pendientes_conteo": len(caps_detalle),
        "capitulos_pendientes": caps_detalle,
        "banner_reactivo": banner
    }


def obtener_estado_pendrive(config: Optional[ConfiguracionBandeja] = None,
                            db: Optional[GestorBaseDatosBandeja] = None,
                            timeout_segundos: float = 3.0) -> Dict[str, Any]:
    """
    Obtiene el estado completo del pendrive ejecutando la lectura fuera del hilo principal
    con límite estricto de timeout_segundos (por defecto 3 s).
    Si el pendrive se cuelga o no responde, retorna sin bloquear indicando sin_respuesta=True.
    """
    res = ejecutar_lectura_pendrive_con_timeout(_leer_estado_pendrive_raw, config, db, timeout_segundos=timeout_segundos)
    if not isinstance(res, dict) or res.get("sin_respuesta"):
        return {
            "conectado": False,
            "sin_respuesta": True,
            "error": "Pendrive sin respuesta",
            "mensaje": "Pendrive sin respuesta",
            "id": None,
            "punto_montaje": None,
            "sistema_archivos": None,
            "espacio_libre_bytes": 0,
            "espacio_total_bytes": 0,
            "espacio_usado_bytes": 0,
            "archivos_part_huerfanos": [],
            "archivos_pendientes_conteo": 0,
            "capitulos_pendientes_conteo": 0,
            "banner_reactivo": None
        }
    return res


def simular_envio_capitulos(capitulos_filtro: Optional[List[str]] = None,
                            config: Optional[ConfiguracionBandeja] = None,
                            db: Optional[GestorBaseDatosBandeja] = None,
                            **kwargs) -> Dict[str, Any]:
    """
    Genera el plan de envío con simulación previa obligatoria por lote.
    Verifica:
    - Identidad y presencia del pendrive (.lucie_pendrive.json).
    - Espacio libre suficiente con margen de seguridad (1 GiB).
    - Límite de 4 GiB en particiones FAT32/vfat (bloqueo preventivo).
    - Colisiones case-insensitive y conflictos de hash (distinto hash bloquea la copia).
    - Deduplicación contra el manifiesto append-only (mismo hash se omite e informa 'ya enviado').
    - Exclusión y aviso de archivos sueltos no multimedia en la raíz del capítulo.
    - Advertencia si algún capítulo sigue abierto en la sala de espera.
    """
    cfg = config or ConfiguracionBandeja()
    carpeta_raiz = cfg.carpeta_raiz_pendrive
    capitulos_lista = capitulos_filtro if capitulos_filtro is not None else kwargs.get("capitulos")

    if capitulos_lista:
        for c_item in capitulos_lista:
            c_str = str(c_item).strip()
            if ".." in c_str or c_str.startswith("/") or "\\" in c_str:
                raise ValueError(f"Intento de path traversal o nombre inválido en capítulo: '{c_item}'")

    info_pendrive = detectar_pendrive(cfg)
    if not info_pendrive or not info_pendrive.get("conectado"):
        return {
            "puede_enviar": False,
            "error": "No se detectó ningún pendrive vinculado con marcador .lucie_pendrive.json conectado.",
            "archivos_a_copiar": [],
            "archivos_omitidos": [],
            "archivos_conflictos": [],
            "archivos_bloqueados": [],
            "archivos_no_multimedia": [],
            "avisos": ["Conecte y vincule un pendrive antes de realizar el envío."],
            "totales": {}
        }

    pendrive_montaje = info_pendrive["ruta_montaje"]
    sistema_archivos = info_pendrive["sistema_archivos"]
    espacio_libre = info_pendrive["espacio_libre_bytes"]
    margen_libre = getattr(cfg, "margen_libre_bytes", 1024 * 1024 * 1024)

    # 1. Leer manifiesto del pendrive para deduplicación por SHA-256
    entradas_manifiesto = leer_manifiesto_pendrive(pendrive_montaje, carpeta_raiz)
    hashes_manifiesto: Set[str] = set()
    for e in entradas_manifiesto:
        h = e.get("sha256")
        if h and e.get("estado") != "revertido":
            hashes_manifiesto.add(h.lower())

    # 2. Obtener capítulos candidatos en la sala de espera
    todos_capitulos = escanear_capitulos_para_envio(cfg.ruta_destino_base)
    capitulos_seleccionados = []

    if capitulos_lista:
        filtro_normalizado = {c.strip().lower() for c in capitulos_lista if c.strip()}
        if "todos" in filtro_normalizado or not filtro_normalizado:
            capitulos_seleccionados = todos_capitulos
        else:
            for c in todos_capitulos:
                clave_completa = f"{c['personaje']}/{c['capitulo']}".lower()
                clave_corta = c["capitulo"].lower()
                if clave_completa in filtro_normalizado or clave_corta in filtro_normalizado:
                    capitulos_seleccionados.append(c)
    else:
        capitulos_seleccionados = todos_capitulos

    # 3. Consultar capítulos abiertos si db está disponible
    capitulos_abiertos_nombres = set()
    if db:
        try:
            abiertos = db.listar_capitulos_abiertos()
            for ab in abiertos:
                capitulos_abiertos_nombres.add((ab.get("personaje", ""), ab.get("nombre", "")))
        except Exception:
            pass

    archivos_a_copiar = []
    archivos_omitidos = []
    archivos_conflictos = []
    archivos_bloqueados = []
    archivos_no_multimedia = []
    avisos = []

    sub_fotos = getattr(cfg, "subcarpeta_fotos", "fotos")
    sub_videos = getattr(cfg, "subcarpeta_videos", "videos")

    es_fat = sistema_archivos in ("vfat", "fat32", "fat")

    for c in capitulos_seleccionados:
        pers = c["personaje"]
        cap = c["capitulo"]
        ruta_cap = c["ruta_absoluta"]

        if (pers, cap) in capitulos_abiertos_nombres:
            avisos.append(f"Aviso: El capítulo '{pers}/{cap}' sigue abierto en la sala de espera; podrían llegar más archivos.")

        # Recorrer archivos dentro del capítulo
        candidatos_archivos = []  # (ruta_origen, subcarpeta_origen, nombre_archivo)

        # a) subcarpeta fotos
        dir_fotos = os.path.join(ruta_cap, sub_fotos)
        if os.path.isdir(dir_fotos):
            for arch in sorted(os.listdir(dir_fotos)):
                p = os.path.join(dir_fotos, arch)
                if os.path.isfile(p) and not arch.startswith("."):
                    candidatos_archivos.append((p, sub_fotos, arch))

        # b) subcarpeta videos
        dir_videos = os.path.join(ruta_cap, sub_videos)
        if os.path.isdir(dir_videos):
            for arch in sorted(os.listdir(dir_videos)):
                p = os.path.join(dir_videos, arch)
                if os.path.isfile(p) and not arch.startswith("."):
                    candidatos_archivos.append((p, sub_videos, arch))

        # c) archivos sueltos en la raíz del capítulo
        for item in sorted(os.listdir(ruta_cap)):
            p = os.path.join(ruta_cap, item)
            if os.path.isfile(p) and not item.startswith("."):
                _, ext = os.path.splitext(item)
                if _es_extension_multimedia(ext):
                    sub_asignada = sub_videos if _es_extension_video(ext) else sub_fotos
                    candidatos_archivos.append((p, sub_asignada, item))
                else:
                    archivos_no_multimedia.append({
                        "personaje": pers,
                        "capitulo": cap,
                        "nombre": item,
                        "ruta_origen": p,
                        "tamanio_bytes": os.path.getsize(p),
                        "aviso": "Archivo suelto con extensión no multimedia en la raíz del capítulo: omitido del envío."
                    })
                    avisos.append(f"Archivo suelto no multimedia omitido: '{pers}/{cap}/{item}'.")

        # Evaluar cada archivo candidato
        for ruta_orig, sub_orig, nombre in candidatos_archivos:
            try:
                st = os.stat(ruta_orig)
                tam = st.st_size
            except OSError:
                continue

            _, ext = os.path.splitext(nombre)
            tipo_media = "crudo" if _es_extension_video(ext) else "imagen"
            sub_dest = "videos sin editar" if tipo_media == "crudo" else "imagenes"

            ruta_rel_pendrive = os.path.join(sub_dest, pers, cap, nombre)
            ruta_abs_pendrive = os.path.join(pendrive_montaje, carpeta_raiz, ruta_rel_pendrive)
            dir_dest_pendrive = os.path.dirname(ruta_abs_pendrive)

            sha_orig = calcular_sha256(ruta_orig)

            item_info = {
                "personaje": pers,
                "capitulo": cap,
                "nombre": nombre,
                "tipo": tipo_media,
                "subcarpeta_origen": sub_orig,
                "ruta_origen": ruta_orig,
                "ruta_relativa_pendrive": ruta_rel_pendrive,
                "ruta_destino_absoluta": ruta_abs_pendrive,
                "tamanio_bytes": tam,
                "sha256": sha_orig,
                "estado": "nuevo",
                "aviso": ""
            }

            # 1. Chequeo contra manifiesto append-only: mismo sha256 -> ya enviado
            if sha_orig.lower() in hashes_manifiesto:
                item_info["estado"] = "ya_enviado"
                item_info["aviso"] = "ya enviado (mismo SHA-256 en manifiesto)"
                archivos_omitidos.append(item_info)
                continue

            # 2. Chequeo de colisión en destino físico (case-insensitive para FAT/exFAT)
            archivo_colisionante = None
            if os.path.isdir(dir_dest_pendrive):
                for f_dest in os.listdir(dir_dest_pendrive):
                    if f_dest.lower() == nombre.lower():
                        archivo_colisionante = f_dest
                        break

            if archivo_colisionante:
                ruta_colision = os.path.join(dir_dest_pendrive, archivo_colisionante)
                sha_dest = calcular_sha256(ruta_colision)
                if sha_dest == sha_orig:
                    item_info["estado"] = "ya_enviado"
                    item_info["aviso"] = f"ya enviado (archivo idéntico preexistente en destino: '{archivo_colisionante}')"
                    archivos_omitidos.append(item_info)
                    continue
                else:
                    item_info["estado"] = "conflicto"
                    item_info["aviso"] = f"Conflicto: en pendrive ya existe '{archivo_colisionante}' con distinto hash ({sha_dest[:8]}... vs {sha_orig[:8]}...). No se copia ni pisa."
                    archivos_conflictos.append(item_info)
                    continue

            # 3. Chequeo límite FAT32 > 4 GiB
            if es_fat and tam > 4294967296:
                item_info["estado"] = "bloqueado_fat32"
                item_info["aviso"] = f"Bloqueado: el archivo ({tam} bytes) excede el límite de 4 GiB del sistema de archivos FAT32/vfat."
                archivos_bloqueados.append(item_info)
                continue

            # Archivo nuevo listo para enviar
            archivos_a_copiar.append(item_info)

    bytes_a_copiar = sum(a["tamanio_bytes"] for a in archivos_a_copiar)
    espacio_suficiente = (espacio_libre >= bytes_a_copiar + margen_libre)

    puede_enviar = (
        len(archivos_a_copiar) > 0 and
        espacio_suficiente and
        len(archivos_conflictos) == 0 and
        len(archivos_bloqueados) == 0
    )

    motivo_bloqueo = None
    if len(archivos_a_copiar) == 0:
        if len(archivos_omitidos) > 0:
            motivo_bloqueo = "Todos los archivos del capítulo ya fueron enviados al pendrive."
        else:
            motivo_bloqueo = "No se encontraron archivos para transferir."
    elif not espacio_suficiente:
        deficit = (bytes_a_copiar + margen_libre) - espacio_libre
        motivo_bloqueo = f"Espacio insuficiente en pendrive: libre {formatear_bytes(espacio_libre)}, se requieren {formatear_bytes(bytes_a_copiar)} + {formatear_bytes(margen_libre)} de margen (déficit: {formatear_bytes(deficit)})."
    elif len(archivos_conflictos) > 0:
        motivo_bloqueo = f"Se detectaron {len(archivos_conflictos)} conflicto(s) de destino con distinto hash. Resuelva los conflictos antes de enviar."
    elif len(archivos_bloqueados) > 0:
        motivo_bloqueo = f"Se detectaron {len(archivos_bloqueados)} archivo(s) que superan el límite de 4 GiB en partición FAT32."

    return {
        "puede_enviar": puede_enviar,
        "motivo_bloqueo": motivo_bloqueo,
        "pendrive": {
            "id": info_pendrive["id"],
            "ruta_montaje": pendrive_montaje,
            "sistema_archivos": sistema_archivos,
            "espacio_libre_bytes": espacio_libre,
            "espacio_total_bytes": info_pendrive["espacio_total_bytes"],
            "margen_libre_bytes": margen_libre
        },
        "capitulos_seleccionados": [f"{c['personaje']}/{c['capitulo']}" for c in capitulos_seleccionados],
        "archivos_a_copiar": archivos_a_copiar,
        "archivos_omitidos": archivos_omitidos,
        "archivos_conflictos": archivos_conflictos,
        "archivos_bloqueados": archivos_bloqueados,
        "archivos_no_multimedia": archivos_no_multimedia,
        "avisos": avisos,
        "totales": {
            "total_evaluados": len(archivos_a_copiar) + len(archivos_omitidos) + len(archivos_conflictos) + len(archivos_bloqueados),
            "a_copiar_cantidad": len(archivos_a_copiar),
            "a_copiar_bytes": bytes_a_copiar,
            "omitidos_ya_enviados": len(archivos_omitidos),
            "conflictos": len(archivos_conflictos),
            "bloqueados_fat32": len(archivos_bloqueados),
            "no_multimedia": len(archivos_no_multimedia)
        }
    }


def ejecutar_envio_pendrive(simulacion_o_capitulos: Any,
                            config: Optional[ConfiguracionBandeja] = None,
                            db: Optional[GestorBaseDatosBandeja] = None,
                            movimientos: Optional[Any] = None) -> Dict[str, Any]:
    """
    Ejecuta la transferencia física segura de archivos hacia el pendrive siguiendo el protocolo:
    1. Re-validación del plan o simulación previa (o ejecución de simulación si se pasan capítulos).
    2. Copia en bloques binarios (1 MiB) hacia <destino>.part con cálculo de SHA-256 en la misma pasada.
    3. Sincronización a disco con os.fsync.
    4. Renombrado con os.rename a su nombre final tras comprobar ausencia de colisión.
    5. Re-lectura del archivo final para verificar que su SHA-256 coincide con el origen.
       Si ocurre error o discrepancia, el archivo .part se preserva (NO se borra) y el lote se interrumpe.
    6. Preservación del archivo original: se mueve con os.rename a ~/Descargas/_lucie/_enviados/<pers>/<cap>/(fotos|videos)/<arch>
       (con sufijo numérico si ya existiera en _enviados).
    7. Registro en manifiesto.jsonl del pendrive en modo append-only ('a').
    8. Registro del evento 'envio_pendrive' en bitacora_bandeja.jsonl.
    """
    cfg = config or ConfiguracionBandeja()

    # 1. Obtener o re-ejecutar simulación
    if isinstance(simulacion_o_capitulos, dict) and "archivos_a_copiar" in simulacion_o_capitulos and "puede_enviar" in simulacion_o_capitulos:
        simulacion = simulacion_o_capitulos
    else:
        simulacion = simular_envio_capitulos(simulacion_o_capitulos, cfg, db)

    if not simulacion.get("puede_enviar"):
        motivo = simulacion.get("motivo_bloqueo") or "El plan de envío no está habilitado para confirmación."
        raise ValueError(motivo)

    archivos_a_copiar = simulacion.get("archivos_a_copiar", [])
    if not archivos_a_copiar:
        raise ValueError("No hay archivos para transferir en el plan de envío.")

    pendrive_info = simulacion.get("pendrive", {})
    pendrive_montaje = pendrive_info.get("ruta_montaje")
    if not pendrive_montaje or not os.path.isdir(pendrive_montaje):
        raise ValueError("El punto de montaje del pendrive no existe o fue desconectado.")

    carpeta_raiz = getattr(cfg, "carpeta_raiz_pendrive", CARPETA_RAIZ_PENDRIVE_DEFECTO)
    base_origen = os.path.realpath(getattr(cfg, "ruta_destino_base", RUTA_DESTINO_DEFECTO))
    pendrive_raiz = os.path.realpath(os.path.join(pendrive_montaje, carpeta_raiz))

    if not os.path.isdir(pendrive_raiz):
        raise ValueError(f"La estructura base '{carpeta_raiz}' no existe en el pendrive. Debe vincular la unidad primero.")

    id_envio = f"env_{uuid.uuid4().hex[:12]}"
    fecha_iso = datetime.datetime.now().isoformat()
    equipo_host = platform.node() or "localhost"
    pendrive_id = pendrive_info.get("id", "")

    archivos_transferidos = []

    # 2. Transferencia física archivo por archivo
    for item in archivos_a_copiar:
        ruta_orig = item["ruta_origen"]
        ruta_orig_real = os.path.realpath(ruta_orig)

        # Confinamiento de origen
        if os.path.islink(ruta_orig) or not (ruta_orig_real == base_origen or ruta_orig_real.startswith(base_origen + os.sep)):
            raise ErrorSeguridadBandeja(f"Violación de confinamiento: archivo de origen fuera de la sala de espera: '{ruta_orig}'")

        if not os.path.exists(ruta_orig):
            raise FileNotFoundError(f"El archivo de origen '{ruta_orig}' ya no existe.")

        rel_dest = item["ruta_relativa_pendrive"]
        if ".." in rel_dest or rel_dest.startswith("/") or rel_dest.startswith("\\"):
            raise ErrorSeguridadBandeja(f"Intento de path traversal en ruta relativa: '{rel_dest}'")

        ruta_dest = os.path.abspath(os.path.join(pendrive_raiz, rel_dest))
        dest_dir = os.path.dirname(ruta_dest)
        dest_dir_real = os.path.realpath(dest_dir)

        # Confinamiento de destino
        if not (dest_dir_real == pendrive_raiz or dest_dir_real.startswith(pendrive_raiz + os.sep)):
            raise ErrorSeguridadBandeja(f"Violación de confinamiento en destino del pendrive: '{ruta_dest}'")

        if os.path.exists(ruta_dest):
            raise RuntimeError(f"Colisión en destino antes de copiar: '{ruta_dest}' ya existe. Transferencia abortada.")

        os.makedirs(dest_dir, exist_ok=True)
        ruta_part = ruta_dest + ".part"

        # Copia en bloques hacia .part calculando SHA-256
        h_orig = hashlib.sha256()
        h_part = hashlib.sha256()
        try:
            with open(ruta_orig, "rb") as f_in, open(ruta_part, "wb") as f_out:
                while True:
                    bloque = f_in.read(1048576)
                    if not bloque:
                        break
                    h_orig.update(bloque)
                    h_part.update(bloque)
                    f_out.write(bloque)
                f_out.flush()
                os.fsync(f_out.fileno())
        except Exception as e:
            # El archivo .part NO se borra
            raise RuntimeError(f"Fallo durante la escritura a '{ruta_part}': {e}. El archivo .part ha sido preservado en el pendrive.")

        sha_in = h_orig.hexdigest().lower()
        sha_out = h_part.hexdigest().lower()
        sha_esperado = item["sha256"].lower()

        if sha_in != sha_esperado or sha_out != sha_esperado:
            raise RuntimeError(f"Discrepancia de SHA-256 durante la copia de '{ruta_orig}'. Esperado {sha_esperado}, calculado {sha_out}. El archivo .part ha sido preservado.")

        if os.path.exists(ruta_dest):
            raise RuntimeError(f"El destino final '{ruta_dest}' apareció inesperadamente antes del renombrado.")

        # Renombrar de .part a destino final
        os.rename(ruta_part, ruta_dest)

        # Re-lectura para verificar integridad post-copia
        sha_releido = calcular_sha256(ruta_dest).lower()
        if sha_releido != sha_esperado:
            raise RuntimeError(f"Discrepancia en la verificación post-copia de '{ruta_dest}'. Esperado {sha_esperado}, obtenido {sha_releido}.")

        # Preservación del original en _enviados
        sub_orig = item.get("subcarpeta_origen") or ("videos" if item["tipo"] == "crudo" else "fotos")
        dir_enviados = os.path.join(base_origen, "_enviados", item["personaje"], item["capitulo"], sub_orig)
        os.makedirs(dir_enviados, exist_ok=True)
        nombre_arch = item["nombre"]
        dest_enviados = os.path.join(dir_enviados, nombre_arch)
        if os.path.exists(dest_enviados):
            base_n, ext_n = os.path.splitext(nombre_arch)
            suf = 1
            while os.path.exists(dest_enviados):
                dest_enviados = os.path.join(dir_enviados, f"{base_n}_{suf}{ext_n}")
                suf += 1

        os.rename(ruta_orig, dest_enviados)

        if db:
            try:
                db.registrar_o_actualizar(
                    hash_val=sha_esperado,
                    ruta_actual=dest_enviados,
                    estado="enviado_pendrive",
                    personaje=item["personaje"],
                    escena=item["capitulo"]
                )
            except Exception:
                pass

        archivos_transferidos.append({
            "id_envio": id_envio,
            "fecha": fecha_iso,
            "equipo": equipo_host,
            "pendrive_id": pendrive_id,
            "personaje": item["personaje"],
            "capitulo": item["capitulo"],
            "tipo": item["tipo"],
            "nombre": nombre_arch,
            "subcarpeta_origen": sub_orig,
            "ruta_relativa": rel_dest,
            "sha256": sha_esperado,
            "bytes": item["tamanio_bytes"],
            "estado": "enviado",
            "ruta_destino_absoluta": ruta_dest,
            "ruta_origen_espera": ruta_orig,
            "ruta_enviados": dest_enviados
        })

    # 3. Asentamiento append-only en manifiesto.jsonl del pendrive
    dir_lucie = os.path.join(pendrive_raiz, ".lucie")
    os.makedirs(dir_lucie, exist_ok=True)
    ruta_manifiesto = os.path.join(dir_lucie, NOMBRE_MANIFIESTO_PENDRIVE)
    with open(ruta_manifiesto, "a", encoding="utf-8") as f_man:
        for r in archivos_transferidos:
            ent = {
                "id_envio": r["id_envio"],
                "fecha": r["fecha"],
                "equipo": r["equipo"],
                "pendrive_id": r["pendrive_id"],
                "personaje": r["personaje"],
                "capitulo": r["capitulo"],
                "tipo": r["tipo"],
                "nombre": r["nombre"],
                "ruta_relativa": r["ruta_relativa"],
                "sha256": r["sha256"],
                "bytes": r["bytes"],
                "estado": "enviado"
            }
            f_man.write(json.dumps(ent, ensure_ascii=False) + "\n")
        f_man.flush()
        os.fsync(f_man.fileno())

    # 4. Asentamiento en bitácora local
    ruta_bitacora = getattr(movimientos, "ruta_bitacora", "bitacora_bandeja.jsonl") if movimientos else "bitacora_bandeja.jsonl"
    os.makedirs(os.path.dirname(os.path.abspath(ruta_bitacora)), exist_ok=True)
    evento_bitacora = {
        "evento": "envio_pendrive",
        "id_operacion": id_envio,
        "fecha": fecha_iso,
        "pendrive_id": pendrive_id,
        "pendrive_montaje": pendrive_montaje,
        "total_archivos": len(archivos_transferidos),
        "bytes_totales": sum(r["bytes"] for r in archivos_transferidos),
        "capitulos": sorted(list({r["capitulo"] for r in archivos_transferidos})),
        "archivos": archivos_transferidos
    }
    with open(ruta_bitacora, "a", encoding="utf-8") as f_bit:
        f_bit.write(json.dumps(evento_bitacora, ensure_ascii=False) + "\n")
        f_bit.flush()

    return {
        "exito": True,
        "id_envio": id_envio,
        "fecha": fecha_iso,
        "pendrive_id": pendrive_id,
        "total_transferidos": len(archivos_transferidos),
        "bytes_totales": sum(r["bytes"] for r in archivos_transferidos),
        "capitulos": sorted(list({r["capitulo"] for r in archivos_transferidos})),
        "archivos": [
            {
                "nombre": r["nombre"],
                "personaje": r["personaje"],
                "capitulo": r["capitulo"],
                "ruta_relativa": r["ruta_relativa"],
                "sha256": r["sha256"],
                "bytes": r["bytes"]
            }
            for r in archivos_transferidos
        ]
    }


def deshacer_envio_pendrive(id_operacion: str,
                            operacion: Optional[Dict[str, Any]] = None,
                            config: Optional[ConfiguracionBandeja] = None,
                            db: Optional[GestorBaseDatosBandeja] = None,
                            ruta_bitacora: Optional[str] = None) -> Dict[str, Any]:
    """
    Revierte una operación de envío al pendrive sin borrar absolutamente nada:
    1. Comprueba la bitácora local para encontrar la operación y validar que no fue revertida antes.
    2. Localiza el pendrive correspondiente por ID.
    3. Fase preventiva: verifica que cada archivo en el pendrive y en _enviados existe, y
       COMPRUEBA ESTRICTAMENTE que la ruta de origen en la sala de espera NO ESTÉ OCUPADA.
       Si algún destino en la sala de espera está ocupado, la reversión se NIEGA por completo.
    4. Fase de ejecución:
       - Mueve la copia en pendrive hacia LucieSinReglas/_revertidos/<id_envio>/<ruta_relativa> con os.rename.
       - Restituye el original desde _enviados a la sala de espera con os.rename.
    5. Registra el evento 'envio_revertido' en manifiesto.jsonl del pendrive y en bitacora_bandeja.jsonl.
    """
    cfg = config or ConfiguracionBandeja()
    bit_path = ruta_bitacora or "bitacora_bandeja.jsonl"

    op_encontrada = operacion
    if not op_encontrada:
        if not os.path.exists(bit_path):
            raise ErrorDeshacer("No existe archivo de bitácora para deshacer operaciones.")
        with open(bit_path, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea:
                    try:
                        d = json.loads(linea)
                        if d.get("id_operacion") == id_operacion and d.get("evento") == "envio_pendrive":
                            op_encontrada = d
                    except Exception:
                        pass

    if not op_encontrada:
        raise ErrorDeshacer(f"No se encontró la operación de envío '{id_operacion}' en la bitácora.")

    # Validar que no haya sido ya deshecha
    if os.path.exists(bit_path):
        with open(bit_path, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea:
                    try:
                        d = json.loads(linea)
                        if d.get("evento") == "deshacer" and d.get("id_operacion_revertida") == id_operacion:
                            raise ErrorDeshacer(f"La operación de envío '{id_operacion}' ya fue deshecha previamente.")
                    except ErrorDeshacer:
                        raise
                    except Exception:
                        pass

    # Localizar pendrive montado
    pendrive_id = op_encontrada.get("pendrive_id", "")
    info_pendrive = detectar_pendrive(cfg)
    punto_montaje = None
    if info_pendrive and info_pendrive.get("id") == pendrive_id:
        punto_montaje = info_pendrive.get("punto_montaje") or info_pendrive.get("ruta_montaje")
    elif op_encontrada.get("pendrive_montaje") and os.path.isdir(op_encontrada["pendrive_montaje"]):
        m = leer_marcador_pendrive(op_encontrada["pendrive_montaje"])
        if m and m.get("id") == pendrive_id:
            punto_montaje = op_encontrada["pendrive_montaje"]

    if not punto_montaje:
        raise ErrorDeshacer(f"No se detectó el pendrive con ID '{pendrive_id}' necesario para revertir el envío.")

    carpeta_raiz = getattr(cfg, "carpeta_raiz_pendrive", CARPETA_RAIZ_PENDRIVE_DEFECTO)
    pendrive_raiz = os.path.realpath(os.path.join(punto_montaje, carpeta_raiz))
    archivos = op_encontrada.get("archivos", [])
    if not archivos:
        raise ErrorDeshacer("La operación de envío no contiene archivos registrados.")

    # Fase 1: Verificaciones preventivas estrictas
    items_plan = []
    for r in archivos:
        rel_path = r["ruta_relativa"]
        ruta_en_pendrive = os.path.join(pendrive_raiz, rel_path)
        ruta_en_enviados = r["ruta_enviados"]
        ruta_origen_espera = r["ruta_origen_espera"]
        ruta_dest_revertido = os.path.join(pendrive_raiz, "_revertidos", id_operacion, rel_path)

        if not os.path.exists(ruta_en_pendrive):
            raise ErrorDeshacer(f"No se puede deshacer: el archivo en pendrive '{ruta_en_pendrive}' ya no existe o fue movido.")

        if not os.path.exists(ruta_en_enviados):
            raise ErrorDeshacer(f"No se puede deshacer: el archivo preservado en _enviados '{ruta_en_enviados}' ya no existe o fue alterado.")

        # REGLA ESTRICTA 5.4: Si la ruta de origen en la sala de espera está ocupada, se niega terminantemente
        if os.path.exists(ruta_origen_espera):
            raise ErrorDeshacer(
                f"No se puede deshacer: la ruta original en sala de espera '{ruta_origen_espera}' ya se encuentra ocupada por otro archivo. "
                f"No se sobrescribe ni se altera ningún archivo."
            )

        if os.path.exists(ruta_dest_revertido):
            raise ErrorDeshacer(f"No se puede deshacer: el destino en _revertidos '{ruta_dest_revertido}' ya se encuentra ocupado.")

        items_plan.append((ruta_en_pendrive, ruta_dest_revertido, ruta_en_enviados, ruta_origen_espera, r))

    # Fase 2: Ejecución de movimientos
    for ruta_pendrive, ruta_revertido, ruta_enviados, ruta_espera, r in items_plan:
        os.makedirs(os.path.dirname(ruta_revertido), exist_ok=True)
        os.rename(ruta_pendrive, ruta_revertido)

        os.makedirs(os.path.dirname(ruta_espera), exist_ok=True)
        os.rename(ruta_enviados, ruta_espera)

        if db:
            try:
                db.registrar_o_actualizar(
                    hash_val=r["sha256"],
                    ruta_actual=ruta_espera,
                    estado="detectado",
                    personaje=r.get("personaje"),
                    escena=r.get("capitulo")
                )
            except Exception:
                pass

    # 5. Registro en manifiesto del pendrive
    dir_lucie = os.path.join(pendrive_raiz, ".lucie")
    ruta_manifiesto = os.path.join(dir_lucie, NOMBRE_MANIFIESTO_PENDRIVE)
    try:
        os.makedirs(dir_lucie, exist_ok=True)
        with open(ruta_manifiesto, "a", encoding="utf-8") as f_man:
            for _, _, _, _, r in items_plan:
                ent = {
                    "id_envio": id_operacion,
                    "fecha": datetime.datetime.now().isoformat(),
                    "equipo": platform.node() or "localhost",
                    "pendrive_id": pendrive_id,
                    "personaje": r.get("personaje", ""),
                    "capitulo": r.get("capitulo", ""),
                    "tipo": r.get("tipo", ""),
                    "nombre": r["nombre"],
                    "ruta_relativa": r["ruta_relativa"],
                    "sha256": r["sha256"],
                    "bytes": r.get("bytes", 0),
                    "estado": "envio_revertido"
                }
                f_man.write(json.dumps(ent, ensure_ascii=False) + "\n")
            f_man.flush()
            os.fsync(f_man.fileno())
    except Exception:
        pass

    # 6. Registro en bitácora local
    evento_reversion = {
        "evento": "deshacer",
        "id_operacion_revertida": id_operacion,
        "tipo_operacion": "envio_pendrive",
        "fecha": datetime.datetime.now().isoformat(),
        "total_revertidos": len(items_plan)
    }
    with open(bit_path, "a", encoding="utf-8") as f_bit:
        f_bit.write(json.dumps(evento_reversion, ensure_ascii=False) + "\n")
        f_bit.flush()

    return {
        "exito": True,
        "id_operacion": id_operacion,
        "total_revertidos": len(items_plan),
        "mensaje": f"Envío '{id_operacion}' revertido exitosamente: archivos devueltos a la sala de espera y copias en pendrive preservadas en _revertidos."
    }


class VigilanteBandeja:
    """Hilo de vigilancia periódica (polling) de ~/Descargas."""

    def __init__(self, config: ConfiguracionBandeja, db: GestorBaseDatosBandeja,
                 filtro: FiltroListaBlanca, detector: DetectorDescargasActivas,
                 agrupador: AgrupadorLotes):
        self.config = config
        self.db = db
        self.filtro = filtro
        self.detector = detector
        self.agrupador = agrupador
        self._detener = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._lotes_actuales: List[Dict[str, Any]] = []
        self._lotes_anteriores_actuales: List[Dict[str, Any]] = []
        self._sin_identificar_actuales: List[Dict[str, Any]] = []
        self._escenas_existentes_actuales: List[Dict[str, Any]] = []
        self._ultimo_conteo_lotes = 0
        self._estado_pendrive: Dict[str, Any] = {"conectado": False, "sin_respuesta": False}
        self._lock = threading.Lock()

    def iniciar(self):
        self._hilo = threading.Thread(target=self._bucle_sondeo, daemon=True, name="VigilanteBandeja")
        self._hilo.start()

    def detener(self):
        self._detener.set()
        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=2.0)

    def _notificar_escritorio(self, mensaje: str):
        """Emite una notificación mediante notify-send si está disponible."""
        notificar_escritorio("Bandeja Lucie", mensaje)

    def escanear(self):
        """Realiza un pase de escaneo no invasivo en ~/Descargas."""
        if not os.path.exists(self.config.ruta_descargas):
            return

        candidatos_estables = []
        candidatos_anteriores = []
        sin_identificar = []
        escenas_existentes = []
        rutas_existentes = set()

        try:
            entradas = os.listdir(self.config.ruta_descargas)
        except OSError:
            return

        cap_foco = self.db.obtener_capitulo_en_foco()
        es_cap_foco = bool(cap_foco and cap_foco.get("habilitado") and cap_foco.get("nombre"))
        ts_corte_capitulo = 0.0
        if es_cap_foco:
            fecha_ini_str = cap_foco.get("fecha_inicio")
            if fecha_ini_str:
                try:
                    dt_ini = datetime.datetime.fromisoformat(fecha_ini_str)
                    ts_ini = dt_ini.timestamp()
                except Exception:
                    ts_ini = 0.0
                margen_segundos = getattr(self.config, "minutos_antes_inicio_capitulo", 0) * 60
                ts_corte_capitulo = ts_ini - margen_segundos

        for entrada in entradas:
            ruta_completa = os.path.join(self.config.ruta_descargas, entrada)
            rutas_existentes.add(ruta_completa)

            # Caso 1: Carpetas de primer nivel
            if os.path.isdir(ruta_completa):
                if self.filtro.es_carpeta_escena_existente(entrada):
                    personaje_deducido = self.filtro.obtener_personaje_de_carpeta_escena(entrada)
                    escenas_existentes.append({
                        "nombre": entrada,
                        "personaje": personaje_deducido,
                        "tipo": "descargas_alias",
                        "ruta": ruta_completa
                    })
                continue

            # Caso 2: Archivos en Descargas
            if not os.path.isfile(ruta_completa):
                continue

            tipo_clasificacion = self.filtro.clasificar_archivo(entrada)
            if tipo_clasificacion == "ignorar":
                continue

            # Verificar si ya es estable (no descarga activa)
            if not self.detector.es_archivo_estable(ruta_completa):
                continue

            try:
                st = os.stat(ruta_completa)
                tamanio = st.st_size
                mtime = st.st_mtime
                fecha_llegada = obtener_fecha_llegada(st)
            except OSError:
                continue

            # Comprobar si el archivo es anterior al capítulo en foco o según horas_material_reciente
            es_anterior = False
            if es_cap_foco and fecha_llegada < ts_corte_capitulo:
                es_anterior = True

            horas_reciente = float(getattr(self.config, "horas_material_reciente", 0) or 0)
            if horas_reciente > 0:
                ts_corte_reciente = time.time() - (horas_reciente * 3600.0)
                if fecha_llegada < ts_corte_reciente:
                    es_anterior = True

            # Comprobar en base de datos SQLite si ya tiene decisión tomada
            reg = self.db.obtener_por_ruta(ruta_completa)
            hash_val = reg["hash"] if reg else calcular_sha256(ruta_completa)
            if not reg:
                reg_hash = self.db.obtener_por_hash(hash_val)
                if reg_hash:
                    reg = reg_hash

            if es_anterior:
                # Regla 2: Archivo anterior al inicio del capítulo activo:
                # NO se asigna al capítulo ni se preselecciona.
                pers_alias = self.filtro.obtener_personaje_de_alias_inicial(entrada) if tipo_clasificacion == "candidato" else None
                personaje_actual = pers_alias
                escena_actual = None
                raiz_escena = None
                estado_actual = "detectado"
                if not reg or reg.get("estado") != "detectado" or reg.get("personaje") != personaje_actual or reg.get("escena") is not None:
                    id_db = self.db.registrar_o_actualizar(
                        hash_val, ruta_completa, "detectado",
                        personaje=personaje_actual, escena=None, limpiar_escena=True
                    )
                    logger.info(
                        f"[BANDEJA][REGISTRADO] Archivo: '{entrada}' (anterior) | Hash: {hash_val[:12]}... | "
                        f"Estado: detectado | Personaje: {personaje_actual} | "
                        f"ts: {datetime.datetime.now().isoformat()}"
                    )
                else:
                    id_db = reg["id"]
            else:
                if reg and reg["estado"] != "detectado":
                    # Archivo ya detectado previamente con decisión tomada: respetar
                    id_db = reg["id"]
                    estado_actual = reg["estado"]
                    personaje_actual = reg.get("personaje")
                    escena_actual = reg.get("escena")
                    if escena_actual:
                        raiz_escena = f"{personaje_actual}::{escena_actual}" if personaje_actual else escena_actual.lower()
                    else:
                        raiz_escena = self.filtro.obtener_raiz_escena(entrada)
                else:
                    # Material nuevo o primer escaneo
                    if es_cap_foco:
                        # Asignación automática por capítulo en foco
                        personaje_actual = cap_foco["personaje"]
                        escena_actual = cap_foco["nombre"]
                        estado_actual = "clasificado"
                        if not reg or reg.get("estado") != "clasificado" or reg.get("personaje") != personaje_actual or reg.get("escena") != escena_actual:
                            id_db = self.db.registrar_o_actualizar(
                                hash_val, ruta_completa, "clasificado",
                                personaje=personaje_actual, escena=escena_actual
                            )
                            logger.info(
                                f"[BANDEJA][REGISTRADO] Archivo: '{entrada}' | Hash: {hash_val[:12]}... | "
                                f"Estado: clasificado | Personaje: {personaje_actual} | Escena: {escena_actual} | "
                                f"ts: {datetime.datetime.now().isoformat()}"
                            )
                        else:
                            id_db = reg["id"]
                        raiz_escena = f"{personaje_actual}::{escena_actual}"
                    else:
                        # Modo de respaldo por alias al inicio sin capítulo en foco
                        pers_alias = self.filtro.obtener_personaje_de_alias_inicial(entrada)
                        if pers_alias:
                            personaje_actual = pers_alias
                            escena_actual = self.filtro.extraer_escena_sugerida(entrada)
                            raiz_escena = self.filtro.obtener_raiz_escena(entrada)
                            if not reg or reg.get("estado") != "detectado" or reg.get("personaje") != personaje_actual or reg.get("escena") != escena_actual:
                                id_db = self.db.registrar_o_actualizar(
                                    hash_val, ruta_completa, "detectado",
                                    personaje=personaje_actual, escena=escena_actual
                                )
                                logger.info(
                                    f"[BANDEJA][REGISTRADO] Archivo: '{entrada}' | Hash: {hash_val[:12]}... | "
                                    f"Estado: detectado | Personaje: {personaje_actual} | Escena: {escena_actual} | "
                                    f"ts: {datetime.datetime.now().isoformat()}"
                                )
                            else:
                                id_db = reg["id"]
                            estado_actual = "detectado"
                        else:
                            personaje_actual = None
                            escena_actual = None
                            raiz_escena = None
                            estado_actual = "detectado"
                            if not reg or reg.get("estado") != "detectado":
                                id_db = self.db.registrar_o_actualizar(hash_val, ruta_completa, "detectado")
                                logger.info(
                                    f"[BANDEJA][REGISTRADO] Archivo: '{entrada}' | Hash: {hash_val[:12]}... | "
                                    f"Estado: detectado | ts: {datetime.datetime.now().isoformat()}"
                                )
                            else:
                                id_db = reg["id"]

            fecha_llegada_str = datetime.datetime.fromtimestamp(fecha_llegada).strftime("%Y-%m-%d %H:%M:%S")
            item_info = {
                "id_db": id_db,
                "nombre": entrada,
                "ruta": ruta_completa,
                "tamanio": tamanio,
                "mtime": mtime,
                "fecha_llegada": fecha_llegada_str,
                "fecha_llegada_ts": fecha_llegada,
                "hash": hash_val,
                "estado": estado_actual,
                "personaje": personaje_actual,
                "escena": escena_actual,
                "raiz_escena": raiz_escena,
                "es_anterior": es_anterior
            }

            if es_anterior:
                if tipo_clasificacion == "candidato":
                    candidatos_anteriores.append(item_info)
                elif tipo_clasificacion == "sin_identificar" and estado_actual != "ignorado":
                    sin_identificar.append(item_info)
            else:
                if tipo_clasificacion == "candidato" or estado_actual == "clasificado" or es_cap_foco:
                    candidatos_estables.append(item_info)
                elif tipo_clasificacion == "sin_identificar" and estado_actual != "ignorado":
                    sin_identificar.append(item_info)

        # También descubrir escenas ya creadas en el destino base
        if os.path.exists(self.config.ruta_destino_base):
            try:
                for pers in ("lucie", "roli", "mailen"):
                    # Sala de espera plana: <destino>/<personaje>/<escena>
                    carpeta_pers = os.path.join(self.config.ruta_destino_base, pers)
                    sub_fotos = getattr(self.config, "subcarpeta_fotos", "fotos").lower()
                    sub_videos = getattr(self.config, "subcarpeta_videos", "videos").lower()
                    if os.path.isdir(carpeta_pers):
                        for sub in os.listdir(carpeta_pers):
                            ruta_sub = os.path.join(carpeta_pers, sub)
                            sub_lower = sub.lower()
                            if (os.path.isdir(ruta_sub) and 
                                sub_lower not in ("videos sin editar", "imagenes", "_descartados", "fotos", "videos", sub_fotos, sub_videos) and 
                                not sub.startswith("_")):
                                if not any(e["nombre"] == sub and e["personaje"] == pers for e in escenas_existentes):
                                    escenas_existentes.append({
                                        "nombre": sub,
                                        "personaje": pers,
                                        "tipo": "destino_existente",
                                        "ruta": ruta_sub
                                    })
                    # Escenas legadas en subcarpetas de tipo
                    subcarpetas_tipo = ["videos sin editar", "imagenes"]
                    for sub_tipo in subcarpetas_tipo:
                        carpeta_tipo = os.path.join(self.config.ruta_destino_base, pers, sub_tipo)
                        if os.path.isdir(carpeta_tipo):
                            for sub in os.listdir(carpeta_tipo):
                                ruta_sub = os.path.join(carpeta_tipo, sub)
                                sub_lower = sub.lower()
                                if (os.path.isdir(ruta_sub) and 
                                    not sub.startswith("_") and 
                                    sub_lower not in ("fotos", "videos", sub_fotos, sub_videos)):
                                    if not any(e["nombre"] == sub and e["personaje"] == pers for e in escenas_existentes):
                                        escenas_existentes.append({
                                            "nombre": sub,
                                            "personaje": pers,
                                            "tipo": "destino_existente",
                                            "ruta": ruta_sub
                                        })
            except OSError:
                pass

        self.detector.limpiar_rutas_inexistentes(rutas_existentes)
        lotes_generados_raw = self.agrupador.agrupar(candidatos_estables)
        lotes_generados = []
        lotes_extra_ant = []
        for l in lotes_generados_raw:
            if l.get("es_anterior"):
                l["es_anterior"] = True
                l["escena_sugerida"] = ""
                l["lote_id"] = f"ant_{l['lote_id']}" if not l["lote_id"].startswith("ant_") else l["lote_id"]
                for a in l.get("archivos", []):
                    a["es_anterior"] = True
                    a["escena"] = ""
                lotes_extra_ant.append(l)
            else:
                l["es_anterior"] = False
                lotes_generados.append(l)

        lotes_anteriores = []
        if candidatos_anteriores:
            lotes_anteriores = self.agrupador.agrupar(candidatos_anteriores)
            for idx, l in enumerate(lotes_anteriores, 1):
                l["es_anterior"] = True
                l["escena_sugerida"] = ""
                l["lote_id"] = f"ant_{l['lote_id']}" if not l["lote_id"].startswith("ant_") else l["lote_id"]
                for a in l.get("archivos", []):
                    a["es_anterior"] = True
                    a["escena"] = ""
        lotes_anteriores.extend(lotes_extra_ant)

        # Sondeo de estado del pendrive fuera del hilo HTTP (con timeout 3s)
        try:
            estado_pen = obtener_estado_pendrive(self.config, self.db, timeout_segundos=3.0)
        except Exception:
            estado_pen = {"conectado": False, "sin_respuesta": False}

        with self._lock:
            self._lotes_actuales = lotes_generados
            self._lotes_anteriores_actuales = lotes_anteriores
            self._sin_identificar_actuales = sin_identificar
            self._escenas_existentes_actuales = escenas_existentes
            self._estado_pendrive = estado_pen

            # Notificar si hay nuevos lotes en la lista principal (NUNCA en Anteriores)
            lotes_principales = [l for l in lotes_generados if not l.get("es_anterior")]
            if len(lotes_principales) > self._ultimo_conteo_lotes:
                nuevos = len(lotes_principales) - self._ultimo_conteo_lotes
                self._notificar_escritorio(f"Se detectaron {nuevos} lote(s) nuevo(s) listos para ordenar.")
            self._ultimo_conteo_lotes = len(lotes_principales)

    def _bucle_sondeo(self):
        while not self._detener.is_set():
            try:
                self.escanear()
            except Exception:
                pass
            self._detener.wait(self.config.intervalo_sondeo_segundos)

    def obtener_estado(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "lotes": list(self._lotes_actuales),
                "lotes_anteriores": list(self._lotes_anteriores_actuales),
                "sin_identificar": list(self._sin_identificar_actuales),
                "escenas": list(self._escenas_existentes_actuales),
                "pendrive": dict(self._estado_pendrive)
            }

    def obtener_token_version(self) -> str:
        """
        Calcula un token determinista basado en todo lo que afecta a la vista:
        - Lotes principales y lotes anteriores (IDs, hashes, estados).
        - Cantidad de archivos sin identificar.
        - Capítulos abiertos, cerrados y descartados.
        - Capítulo en foco y balance (pendientes/movidos).
        - Estado de alertas (olvidado).
        - Estado de conexión y archivos pendientes del pendrive.
        """
        with self._lock:
            res_lotes = []
            for l in self._lotes_actuales:
                archs = [(a.get("id_db"), a.get("hash"), a.get("estado"), a.get("es_anterior")) for a in l.get("archivos", [])]
                res_lotes.append((l.get("lote_id"), l.get("escena_sugerida"), l.get("personaje_sugerido"), archs))

            res_anteriores = []
            for l in self._lotes_anteriores_actuales:
                archs = [(a.get("id_db"), a.get("hash"), a.get("estado"), a.get("es_anterior")) for a in l.get("archivos", [])]
                res_anteriores.append((l.get("lote_id"), archs))

            res_sin_id = [(a.get("id_db"), a.get("hash"), a.get("nombre")) for a in self._sin_identificar_actuales]
            res_escenas = [(e.get("nombre"), e.get("personaje"), e.get("tipo")) for e in self._escenas_existentes_actuales]
            pen_token = (
                self._estado_pendrive.get("conectado"),
                self._estado_pendrive.get("id"),
                self._estado_pendrive.get("archivos_pendientes_conteo")
            )

        res_db = self.db.obtener_resumen_version()
        alerta_olvidado = self.db.es_capitulo_olvidado(float(self.config.horas_alerta_capitulo_olvidado))
        cap_foco = self.db.obtener_capitulo_en_foco()

        balance = (0, 0)
        if cap_foco and cap_foco.get("habilitado") and cap_foco.get("personaje") and cap_foco.get("nombre"):
            bal_dict = self.db.calcular_balance_capitulo(cap_foco["personaje"], cap_foco["nombre"], verificar_disco=False)
            balance = (bal_dict.get("pendientes", 0), bal_dict.get("movidos", 0))

        raw_payload = (
            res_lotes,
            res_anteriores,
            res_sin_id,
            res_escenas,
            res_db,
            alerta_olvidado,
            cap_foco.get("id"),
            cap_foco.get("en_foco"),
            balance,
            pen_token
        )
        return hashlib.sha256(repr(raw_payload).encode("utf-8")).hexdigest()[:16]


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

        if ruta in ("/", "/index.html"):
            self._servir_html_spa()
        elif ruta == "/api/estado-version":
            token = self.vigilante.obtener_token_version()
            estado_pen = getattr(self.vigilante, "_estado_pendrive", {})
            self._enviar_json({
                "version": token,
                "refresco_panel_segundos": getattr(self.config, "refresco_panel_segundos", 4),
                "banner_pendrive": estado_pen.get("banner_reactivo")
            })
        elif ruta == "/api/lotes":
            estado = self.vigilante.obtener_estado()
            self._enviar_json({
                "lotes": estado["lotes"],
                "lotes_anteriores": estado.get("lotes_anteriores", [])
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

    def _servir_html_spa(self):
        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bandeja de Descargas - Proyecto Lucie</title>
  <style>
    :root {{
      --bg: #121212;
      --card-bg: #1e1e1e;
      --card-alt: #252525;
      --text: #e0e0e0;
      --text-muted: #9e9e9e;
      --accent: #bb86fc;
      --accent-hover: #9955e8;
      --teal: #03dac6;
      --danger: #cf6679;
      --border: #333333;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background-color: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.5;
      padding-bottom: 60px;
    }}
    header {{
      background: #181818;
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    h1 {{ font-size: 1.25rem; font-weight: 600; color: #fff; }}
    .badge {{
      background: var(--teal);
      color: #000;
      font-size: 0.75rem;
      font-weight: bold;
      padding: 4px 8px;
      border-radius: 4px;
      text-transform: uppercase;
    }}
    nav {{
      display: flex;
      gap: 12px;
      padding: 16px 24px;
      background: var(--card-bg);
      border-bottom: 1px solid var(--border);
    }}
    .nav-btn {{
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 16px;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 500;
    }}
    .nav-btn.active {{
      background: var(--accent);
      color: #000;
      border-color: var(--accent);
    }}
    main {{ max-width: 1200px; margin: 24px auto; padding: 0 16px; }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
    }}
    .lote-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      padding: 6px 12px;
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border);
      border-radius: 6px;
    }}
    .archivos-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }}
    .archivo-item {{
      background: var(--card-alt);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      position: relative;
      transition: border-color 0.2s;
    }}
    .archivo-item:hover {{
      border-color: var(--accent);
    }}
    .chk-container {{
      position: absolute;
      top: 8px;
      left: 8px;
      z-index: 10;
      background: rgba(0, 0, 0, 0.75);
      border-radius: 4px;
      padding: 3px 6px;
      display: flex;
      align-items: center;
      cursor: pointer;
    }}
    .chk-container input[type="checkbox"] {{
      cursor: pointer;
      width: 16px;
      height: 16px;
      accent-color: var(--accent);
    }}
    .miniatura-wrap {{
      width: 100%;
      height: 110px;
      background: #000;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }}
    .miniatura-wrap img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .archivo-meta {{
      padding: 8px;
      font-size: 0.8rem;
    }}
    .archivo-nombre {{
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      margin-bottom: 4px;
    }}
    .archivo-peso {{ color: var(--text-muted); }}
    .form-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      background: var(--card-alt);
      padding: 12px;
      border-radius: 6px;
    }}
    .campo-escena-wrap {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .error-inline {{
      color: var(--danger);
      font-size: 0.8rem;
      font-weight: 500;
    }}
    label {{ font-size: 0.85rem; font-weight: 500; }}
    select, input[type="text"] {{
      background: #141414;
      border: 1px solid var(--border);
      color: #fff;
      padding: 8px 12px;
      border-radius: 4px;
      font-size: 0.9rem;
    }}
    button.btn-accion {{
      background: var(--accent);
      color: #000;
      border: none;
      padding: 8px 18px;
      border-radius: 4px;
      font-weight: 600;
      cursor: pointer;
      margin-left: auto;
      transition: background 0.2s, opacity 0.2s;
    }}
    button.btn-accion:hover:not(:disabled) {{ background: var(--accent-hover); }}
    button.btn-accion:disabled {{
      background: #333;
      color: #777;
      cursor: not-allowed;
      opacity: 0.65;
    }}
    .btn-sm {{
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 0.8rem;
      cursor: pointer;
      transition: background 0.2s, border-color 0.2s;
    }}
    .btn-sm:hover:not(:disabled) {{
      background: rgba(255, 255, 255, 0.08);
      border-color: var(--accent);
    }}
    .btn-sm:disabled {{
      opacity: 0.5;
      cursor: not-allowed;
    }}
    .badge-movido {{
      background: rgba(3, 218, 198, 0.2);
      color: var(--teal);
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
    }}
    .badge-deshecho {{
      background: rgba(207, 102, 121, 0.2);
      color: var(--danger);
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
    }}
    .badge-descartado {{
      background: rgba(245, 158, 11, 0.2);
      color: #f59e0b;
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
    }}
    /* Modal de Simulación */
    .modal-overlay {{
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.75);
      z-index: 200;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}
    .modal-content {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      width: 90vw;
      max-width: 1200px;
      max-height: 85vh;
      overflow-y: auto;
      padding: 24px;
    }}
    .modal-actions {{
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      margin-top: 20px;
    }}
    .btn-cancelar {{
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 16px;
      border-radius: 4px;
      cursor: pointer;
    }}
    .btn-confirmar {{
      background: var(--teal);
      border: none;
      color: #000;
      padding: 8px 20px;
      border-radius: 4px;
      font-weight: bold;
      cursor: pointer;
    }}
    .alert-error {{
      background: rgba(207, 102, 121, 0.15);
      border: 1px solid var(--danger);
      color: var(--danger);
      padding: 12px;
      border-radius: 6px;
      margin-bottom: 16px;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; margin: 12px 0; }}
    th, td {{ border: 1px solid var(--border); padding: 8px; text-align: left; }}
    th {{ background: var(--card-alt); }}
    .modal-tabla {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
      margin: 14px 0;
      table-layout: fixed;
    }}
    .modal-tabla th, .modal-tabla td {{
      padding: 10px 12px;
      border: 1px solid var(--border);
      text-align: left;
      vertical-align: middle;
    }}
    .modal-tabla th {{
      background: var(--card-alt);
      font-size: 0.85rem;
      color: var(--text-muted);
    }}
    .ruta-celda {{
      word-break: break-word;
      overflow-wrap: anywhere;
      white-space: normal;
      font-size: 0.85rem;
      line-height: 1.4;
    }}
    .destino-celda {{
      color: var(--text);
    }}
    .tag-tipo {{
      display: inline-block;
      padding: 2px 7px;
      border-radius: 4px;
      font-size: 0.78rem;
      font-weight: 600;
      margin: 0 2px;
      vertical-align: middle;
    }}
    .tag-video {{
      background: rgba(168, 85, 247, 0.2);
      color: #c084fc;
      border: 1px solid rgba(168, 85, 247, 0.4);
    }}
    .tag-imagen {{
      background: rgba(14, 165, 233, 0.2);
      color: #38bdf8;
      border: 1px solid rgba(14, 165, 233, 0.4);
    }}
    .card-capitulo {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px 20px;
      margin-bottom: 20px;
    }}
    .badge-capitulo-activo {{
      background: #f59e0b;
      color: #000;
      border: 1px solid #f59e0b;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}
    .badge-capitulo-inactivo {{
      background: rgba(255, 255, 255, 0.08);
      color: var(--text-muted);
      border: 1px solid var(--border);
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .banner-capitulo-activo {{
      background: #1e1b4b;
      border: 1px solid #f59e0b;
      border-radius: 8px;
      padding: 14px 20px;
      margin-bottom: 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 4px 14px rgba(0,0,0,0.5);
    }}
    .banner-capitulo-olvidado {{
      background: #451a03;
      border: 1px solid #f59e0b;
      color: #fef3c7;
      border-radius: 8px;
      padding: 12px 18px;
      margin-bottom: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    }}
    .banner-aviso {{
      background: #14352b;
      border-bottom: 2px solid var(--teal);
      color: #e0f2f1;
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 61px;
      z-index: 95;
      box-shadow: 0 4px 12px rgba(0,0,0,0.6);
    }}
    .banner-aviso-texto {{
      font-size: 0.95rem;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .banner-aviso-acciones {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .btn-deshacer-aviso {{
      background: var(--teal);
      color: #000;
      border: none;
      padding: 6px 16px;
      border-radius: 4px;
      font-weight: 600;
      font-size: 0.85rem;
      cursor: pointer;
      transition: background 0.2s;
    }}
    .btn-deshacer-aviso:hover {{
      background: #04bfae;
    }}
    .btn-cerrar-aviso {{
      background: transparent;
      border: none;
      color: #aaa;
      font-size: 1.35rem;
      cursor: pointer;
      line-height: 1;
      padding: 2px 6px;
      transition: color 0.2s;
    }}
    .btn-cerrar-aviso:hover {{
      color: #fff;
    }}
    .banner-desconexion {{
      background: #7f1d1d;
      border-bottom: 2px solid #ef4444;
      color: #fee2e2;
      padding: 10px 24px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      font-weight: 600;
      position: sticky;
      top: 61px;
      z-index: 96;
      box-shadow: 0 4px 12px rgba(0,0,0,0.6);
    }}
    .toast-llegada {{
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #065f46;
      border: 1px solid #10b981;
      color: #ecfdf5;
      padding: 12px 20px;
      border-radius: 8px;
      font-weight: 600;
      box-shadow: 0 4px 16px rgba(0,0,0,0.6);
      z-index: 300;
      transition: opacity 0.3s ease, transform 0.3s ease;
      opacity: 0;
      pointer-events: none;
      transform: translateY(10px);
    }}
    .toast-llegada.visible {{
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Bandeja de Descargas &bull; Proyecto Lucie</h1>
      <small style="color:var(--text-muted)">Confinado estrictamente a ~/Descargas</small>
    </div>
    <span class="badge">127.0.0.1:{self.config.puerto_servidor}</span>
  </header>

  <div id="banner-desconexion" class="banner-desconexion" style="display:none;">
    <span>⚠️ Sin conexión con la bandeja de descargas. Reintentando reconectar...</span>
  </div>

  <div id="banner-aviso" class="banner-aviso" style="display:none;">
    <div class="banner-aviso-texto">
      <span style="color:var(--teal); font-weight:bold;">&#10003;</span>
      <span id="banner-aviso-msg"></span>
    </div>
    <div class="banner-aviso-acciones">
      <button class="btn-deshacer-aviso" id="btn-banner-deshacer" onclick="deshacerDesdeAviso()">Deshacer</button>
      <button class="btn-cerrar-aviso" id="btn-banner-cerrar" onclick="cerrarAviso()" title="Cerrar aviso">&times;</button>
    </div>
  </div>

  <div id="banner-pendrive-detectado" class="banner-aviso" style="display:none; background:#1e3a8a; border-bottom:2px solid #3b82f6;">
    <div class="banner-aviso-texto">
      <span style="font-size:1.2rem;">💾</span>
      <span id="banner-pendrive-texto">Pendrive detectado</span>
    </div>
    <div class="banner-aviso-acciones">
      <button class="btn-deshacer-aviso" style="background:#38bdf8; color:#000;" onclick="abrirModalPlanEnvio()">Ver plan</button>
      <button class="btn-cerrar-aviso" onclick="cerrarBannerPendrive()" title="Cerrar aviso">&times;</button>
    </div>
  </div>

  <nav>
    <button class="nav-btn active" id="nav-btn-lotes" onclick="mostrarPestana('lotes', event)">Lotes Detectados</button>
    <button class="nav-btn" id="nav-btn-sin-identificar" onclick="mostrarPestana('sin-identificar', event)">Sin Identificar</button>
    <button class="nav-btn" id="nav-btn-capitulos-abiertos" onclick="mostrarPestana('capitulos-abiertos', event)">Capítulos Abiertos (<span id="conteo-nav-abiertos">0</span>)</button>
    <button class="nav-btn" id="nav-btn-capitulos-cerrados" onclick="mostrarPestana('capitulos-cerrados', event)">Capítulos Cerrados</button>
    <button class="nav-btn" id="nav-btn-descartados" onclick="mostrarPestana('descartados', event)">Descartados</button>
    <button class="nav-btn" id="nav-btn-pendrive" onclick="mostrarPestana('pendrive', event)">Pendrive</button>
    <button class="nav-btn" id="nav-btn-historial" onclick="mostrarPestana('historial', event)">Historial</button>
    <button class="nav-btn" onclick="recargarVistaActual()">Refrescar</button>
  </nav>

  <main>
    <!-- Alerta de capítulo olvidado (>12h) -->
    <div id="banner-capitulo-olvidado" class="banner-capitulo-olvidado" style="display:none;">
      <div id="banner-olvidado-texto" style="font-weight:600; font-size:0.95rem;">
        ⚠️ ¿Sigue activo este capítulo?
      </div>
      <div style="display:flex; gap:10px; align-items:center;">
        <button class="btn-sm" onclick="posponerAlertaCapitulo()" style="background:#f59e0b; color:#000; font-weight:600; padding:6px 14px;">Seguir</button>
        <button class="btn-sm" onclick="abrirModalTerminarCapitulo()" style="background:var(--error); color:#fff; font-weight:600; padding:6px 14px;">Terminar</button>
      </div>
    </div>

    <!-- Banner superior permanente cuando el capítulo está en foco -->
    <div id="banner-capitulo-activo" class="banner-capitulo-activo" style="display:none;">
      <div>
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="badge-capitulo-activo">⭐ EN FOCO</span>
          <span id="banner-capitulo-titulo" style="font-weight:700; font-size:1.1rem; color:#e0e7ff;">Capítulo en foco:</span>
          <span id="banner-otros-abiertos" style="font-size:0.85rem; color:#a5b4fc; cursor:pointer; text-decoration:underline;" onclick="mostrarPestana('capitulos-abiertos')"></span>
        </div>
        <div id="banner-capitulo-subtitulo" style="font-size:0.85rem; color:#a5b4fc; margin-top:4px;">
          Cargando detalles...
        </div>
      </div>
      <div style="display:flex; gap:10px; align-items:center;">
        <button class="btn-sm" id="btn-enviar-capitulo-activo" onclick="iniciarEnvioCapituloActivo()" style="background:#10b981; color:#000; font-weight:600; padding:8px 16px; border:none; border-radius:4px; cursor:pointer;" title="Enviar material del capítulo en foco al pendrive">
          Enviar al pendrive
        </button>
        <button class="btn-sm" id="btn-descartar-capitulo-activo" onclick="descartarCapituloActivo()" style="background:#4b5563; color:#fff; font-weight:600; padding:8px 16px; border:none; border-radius:4px; cursor:pointer;">
          Descartar capítulo
        </button>
        <button class="btn-sm" id="btn-terminar-capitulo" onclick="abrirModalTerminarCapitulo()" style="background:#ef4444; color:#fff; font-weight:600; padding:8px 16px; border:none; border-radius:4px; cursor:pointer;">
          Terminar capítulo
        </button>
      </div>
    </div>

    <!-- Banner aviso cuando hay capítulos abiertos pero ninguno en foco -->
    <div id="banner-sin-foco" class="banner-capitulo-olvidado" style="display:none; background:#1e1b4b; border:1px solid #6366f1;">
      <div style="display:flex; align-items:center; gap:10px;">
        <span style="font-size:1.2rem;">ℹ️</span>
        <div>
          <div style="font-weight:700; color:#e0e7ff;">Ningún capítulo en foco</div>
          <div style="font-size:0.85rem; color:#a5b4fc;">El material nuevo se clasifica por alias inicial. Podés elegir cuál poner en foco en la pestaña Capítulos Abiertos.</div>
        </div>
      </div>
      <div>
        <button class="btn-sm" onclick="mostrarPestana('capitulos-abiertos')" style="background:var(--accent); color:#000; font-weight:600; padding:6px 14px; border:none; border-radius:4px; cursor:pointer;">
          Ver capítulos abiertos
        </button>
      </div>
    </div>

    <!-- Controles para Empezar Capítulo (cuando no hay capítulo activo) -->
    <div id="card-empezar-capitulo" class="card-capitulo" style="display:none;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-weight:600; font-size:0.95rem;">Empezar Capítulo:</span>
          <span class="badge-capitulo-inactivo">Sin capítulo activo</span>
        </div>
        <div style="font-size:0.8rem; color:var(--text-muted);">
          Modo de respaldo activo (se asignará por alias al inicio del nombre).
        </div>
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:center;">
        <label style="font-size:0.85rem;">Personaje:
          <select id="sel-capitulo-personaje">
            <option value="lucie">Lucie</option>
            <option value="roli">Roli</option>
            <option value="mailen">Mailen</option>
          </select>
        </label>
        <input type="text" id="txt-capitulo-nombre" placeholder="Nombre del nuevo capítulo" style="min-width:240px;">
        <button class="btn-sm" id="btn-empezar-capitulo" onclick="empezarCapitulo()" style="background:var(--accent); color:#000; font-weight:600; padding:6px 16px;">
          Empezar capítulo
        </button>
        <span id="error-capitulo-activo" class="error-inline" style="display:none;"></span>
      </div>
    </div>

    <div id="alert-box" style="display:none;" class="alert-error"></div>

    <section id="sec-lotes">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
        <h2 style="font-size:1.15rem;">Lotes Detectados</h2>
        <button id="btn-mover-lotes-listos" class="btn-accion" onclick="simularMoverLotesListos()" style="margin-left:0;">
          Mover lotes listos
        </button>
      </div>
      <div id="contenedor-lotes">Cargando lotes...</div>

      <div id="sec-lotes-anteriores" style="display:none; margin-top:24px;">
        <details id="details-anteriores" style="background:var(--card-bg, #1a1a1a); border:1px solid #333; border-radius:8px; padding:12px 16px;">
          <summary style="font-size:1.05rem; font-weight:600; cursor:pointer; color:var(--text-muted, #aaa);">
            Anteriores al capítulo (<span id="conteo-lotes-anteriores">0</span>)
          </summary>
          <p style="font-size:0.85rem; color:var(--text-muted, #888); margin:8px 0 16px 0;">
            Material descargado antes del inicio del capítulo activo. No está preasignado ni seleccionado.
          </p>
          <div id="contenedor-lotes-anteriores"></div>
        </details>
      </div>
    </section>

    <section id="sec-sin-identificar" style="display:none;">
      <div class="card">
        <h2>Archivos multimedia sin clasificar</h2>
        <p style="color:var(--text-muted); margin-bottom:16px;">
          Archivos de media sin patrón conocido. Marcá si corresponden al proyecto o ignorar. La decisión se recuerda por hash.
        </p>
        <div id="contenedor-sin-identificar">Cargando...</div>
      </div>
    </section>

    <section id="sec-capitulos-abiertos" style="display:none;">
      <div class="card" style="margin-bottom:20px;">
        <div class="card-header">
          <div>
            <h2>Capítulos Abiertos</h2>
            <small style="color:var(--text-muted)">Historias en paralelo. El capítulo en foco recibe las descargas nuevas automáticamente.</small>
          </div>
          <button class="btn-sm" onclick="cargarCapitulosAbiertos()">Actualizar</button>
        </div>
        <div id="contenedor-capitulos-abiertos">Cargando capítulos abiertos...</div>
      </div>

      <div class="card">
        <h3 style="margin-bottom:12px; font-size:1rem;">Empezar nuevo capítulo en paralelo</h3>
        <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:center;">
          <label style="font-size:0.85rem;">Personaje:
            <select id="sel-nuevo-capitulo-pers">
              <option value="lucie">Lucie</option>
              <option value="roli">Roli</option>
              <option value="mailen">Mailen</option>
            </select>
          </label>
          <input type="text" id="txt-nuevo-capitulo-nom" placeholder="Nombre del nuevo capítulo" style="min-width:240px;">
          <button class="btn-sm" onclick="empezarCapituloSecundario()" style="background:var(--accent); color:#000; font-weight:600; padding:6px 16px;">
            Empezar capítulo
          </button>
          <span id="error-nuevo-capitulo" class="error-inline" style="display:none;"></span>
        </div>
      </div>
    </section>

    <section id="sec-capitulos-cerrados" style="display:none;">
      <div class="card">
        <div class="card-header">
          <div>
            <h2>Capítulos Cerrados</h2>
            <small style="color:var(--text-muted)">Historial de capítulos finalizados. Podés reabrir cualquiera para seguir agregando archivos.</small>
          </div>
          <button class="btn-sm" onclick="cargarCapitulosCerrados()">Actualizar</button>
        </div>
        <div id="contenedor-capitulos-cerrados">Cargando capítulos...</div>
      </div>
    </section>

    <section id="sec-descartados" style="display:none;">
      <div class="card">
        <div class="card-header">
          <div>
            <h2>Capítulos Descartados</h2>
            <small style="color:var(--text-muted)">Capítulos en cuarentena dentro de _descartados. Los archivos no fueron borrados y se pueden consultar o restaurar.</small>
          </div>
          <button class="btn-sm" onclick="cargarCapitulosDescartados()">Actualizar</button>
        </div>
        <div id="contenedor-capitulos-descartados">Cargando descartados...</div>
      </div>
    </section>

    <section id="sec-historial" style="display:none;">
      <div class="card">
        <div class="card-header">
          <div>
            <h2>Historial de movimientos</h2>
            <small style="color:var(--text-muted)">Últimos 50 movimientos registrados en la bitácora</small>
          </div>
          <button class="btn-sm" id="btn-deshacer-ultimo-lote" onclick="deshacerUltimoLote()" style="background:var(--accent); color:#000; font-weight:600; padding:6px 14px;">Deshacer último lote</button>
        </div>
        <div id="contenedor-historial">Cargando historial...</div>
      </div>
    </section>

    <section id="sec-pendrive" style="display:none;">
      <div class="card">
        <div class="card-header">
          <div>
            <h2>Unidad Pendrive</h2>
            <small style="color:var(--text-muted)">Detección y envío seguro hacia la estructura aislada LucieSinReglas/</small>
          </div>
          <div style="display:flex; gap:10px; align-items:center;">
            <button class="btn-sm" onclick="cargarVistaPendrive()">Actualizar estado</button>
            <button class="btn-sm" id="btn-vincular-pendrive" onclick="abrirModalVincularPendrive()" style="display:none; background:var(--accent); color:#000; font-weight:600;">Vincular pendrive</button>
          </div>
        </div>
        <div id="contenedor-estado-pendrive">Cargando estado del pendrive...</div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <h2>Capítulos listos para enviar al pendrive</h2>
            <small style="color:var(--text-muted)">Material clasificado en la sala de espera (~/Descargas/_lucie/)</small>
          </div>
          <button class="btn-sm" id="btn-enviar-todos-pendrive" onclick="abrirModalPlanEnvio()" style="background:var(--teal); color:#000; font-weight:600; padding:6px 14px;">
            Enviar todos al pendrive
          </button>
        </div>
        <div id="contenedor-capitulos-pendrive">Cargando capítulos...</div>
      </div>

      <div class="card" id="card-part-pendrive" style="display:none;">
        <div class="card-header">
          <div>
            <h2 style="color:var(--danger)">Archivos incompletos (.part huérfanos)</h2>
            <small style="color:var(--text-muted)">Archivos interrumpidos durante copias previas. Quedan visibles en el pendrive y NO se borran.</small>
          </div>
        </div>
        <div id="contenedor-part-pendrive"></div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <h2>Historial de envíos al pendrive</h2>
            <small style="color:var(--text-muted)">Últimas operaciones de envío con capacidad de deshacer sin borrar nada</small>
          </div>
        </div>
        <div id="contenedor-historial-pendrive">Cargando historial de envíos...</div>
      </div>
    </section>
  </main>

  <!-- Modal para Terminar Capítulo con Resumen de Balance -->
  <div id="modal-terminar-capitulo" class="modal-overlay">
    <div class="modal-content" style="max-width:550px;">
      <h2>Terminar Capítulo</h2>
      <div id="modal-terminar-resumen" style="margin:16px 0; font-size:1rem; line-height:1.6;">
        Cargando resumen...
      </div>
      <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px; flex-wrap:wrap;">
        <button class="btn-sm" onclick="cerrarModalTerminarCapitulo()">Cancelar</button>
        <button class="btn-sm" id="btn-terminar-sin-mover" onclick="ejecutarTerminarCapitulo(false)" style="background:var(--card-alt); color:var(--text); border:1px solid var(--border);">Terminar sin mover</button>
        <button class="btn-sm" id="btn-mover-y-terminar" onclick="ejecutarMoverYTerminar()" style="background:var(--accent); color:#000; font-weight:600;">Mover pendientes y terminar</button>
      </div>
    </div>
  </div>

  <!-- Modal para Descartar Capítulo con Simulación y Confirmación por Nombre -->
  <div id="modal-descartar-capitulo" class="modal-overlay">
    <div class="modal-content" style="max-width:620px;">
      <h2 style="color:var(--text); margin-bottom:12px;">Descartar Capítulo</h2>
      <div id="modal-descartar-detalles" style="margin:16px 0; font-size:0.95rem; line-height:1.6;">
        Cargando detalles de descarte...
      </div>
      <div id="modal-descartar-aviso" style="background:rgba(245, 158, 11, 0.15); border:1px solid #f59e0b; color:#fef3c7; padding:12px 16px; border-radius:6px; margin:16px 0; font-weight:500;">
        ⚠️ Esto NO borra: mueve a _descartados y se puede deshacer.
      </div>
      <div id="modal-descartar-confirmacion-box" style="margin:16px 0;">
        <label for="txt-confirmar-descartar" style="display:block; font-size:0.9rem; margin-bottom:6px;">
          Para confirmar, escribí el nombre exacto del capítulo (<strong id="nombre-capitulo-esperado" style="color:var(--teal)"></strong>):
        </label>
        <input type="text" id="txt-confirmar-descartar" placeholder="Nombre exacto del capítulo" style="width:100%; padding:8px 12px; background:var(--card-alt); border:1px solid var(--border); color:var(--text); border-radius:4px;" oninput="validarConfirmacionDescartar()">
        <span id="error-confirmar-descartar" class="error-inline" style="display:none; color:var(--danger); font-size:0.8rem; margin-top:4px;"></span>
      </div>
      <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
        <button class="btn-cancelar" onclick="cerrarModalDescartarCapitulo()">Cancelar</button>
        <button class="btn-sm" id="btn-confirmar-descartar" onclick="ejecutarDescarteCapitulo()" disabled style="background:#ef4444; color:#fff; font-weight:600; padding:8px 18px; border:none; border-radius:4px; cursor:not-allowed; opacity:0.5;">
          Descartar capítulo
        </button>
      </div>
    </div>
  </div>

  <div id="modal-simulacion" class="modal-overlay">
    <div class="modal-content">
      <h2>Simulación previa de movimientos</h2>
      <p style="color:var(--text-muted); margin-bottom:12px;">
        Verificá el origen y destino exacto antes de autorizar.
      </p>
      <div id="simulacion-contenido"></div>
      <div class="modal-actions">
        <button class="btn-cancelar" onclick="cerrarModal()">Cancelar</button>
        <button class="btn-confirmar" id="btn-ejecutar-mover">Confirmar y Mover</button>
      </div>
    </div>
  </div>

  <!-- Modal de Plan de Envío al Pendrive -->
  <div id="modal-plan-envio" class="modal-overlay">
    <div class="modal-content" style="max-width:980px;">
      <h2>Plan de Envío al Pendrive</h2>
      <p style="color:var(--text-muted); margin-bottom:12px;">
        Verificá los archivos a transferir, el espacio libre y las comprobaciones de integridad antes de confirmar.
      </p>
      <div id="contenido-plan-envio">Cargando simulación del envío...</div>
      <div class="modal-actions">
        <button class="btn-cancelar" onclick="cerrarModalPlanEnvio()">Cancelar</button>
        <button class="btn-confirmar" id="btn-confirmar-envio-pendrive" onclick="confirmarEnvioPendrive()" disabled style="opacity:0.5; cursor:not-allowed;">Confirmar y enviar</button>
      </div>
    </div>
  </div>

  <!-- Modal para Vincular Pendrive -->
  <div id="modal-vincular-pendrive" class="modal-overlay">
    <div class="modal-content" style="max-width:650px;">
      <h2>Vincular Pendrive a Proyecto Lucie</h2>
      <div id="contenido-vincular-pendrive" style="margin:16px 0; font-size:0.95rem; line-height:1.6;">
        Cargando datos de la unidad...
      </div>
      <div class="modal-actions">
        <button class="btn-cancelar" onclick="cerrarModalVincularPendrive()">Cancelar</button>
        <button class="btn-confirmar" id="btn-confirmar-vincular" onclick="confirmarVincularPendrive()">Confirmar y vincular</button>
      </div>
    </div>
  </div>

  <script>
    const CSRF_TOKEN = "{self.token_csrf}";
    const REFRESCO_PANEL_SEGUNDOS = {getattr(self.config, "refresco_panel_segundos", 4)};
    const TITULO_BASE = document.title;
    let versionActualToken = null;
    let temporizadorSondeo = null;
    let sondeoEnCurso = false;
    let reintentoEsperaSegundos = REFRESCO_PANEL_SEGUNDOS > 0 ? REFRESCO_PANEL_SEGUNDOS : 4;
    let desconectado = false;
    let lotesNuevosSegundoPlano = 0;
    let temporizadorToast = null;

    let datosEstado = {{ lotes: [], lotes_anteriores: [], sin_identificar: [], escenas: [], personajes: [], ultimo_personaje: "lucie", capitulo_activo: null, capitulo_foco: null, capitulos_abiertos: [], cantidad_abiertos: 0, alerta_olvidado: false, horas_limite: 12, balance_capitulo: {{ pendientes: 0, movidos: 0 }} }};
    let simulacionActiva = null;
    let descarteSimulacionActiva = null;
    let loteActivoId = null;
    let terminarCapituloTrasMover = false;
    let pestanaActual = 'lotes';
    let historialActual = [];
    let operacionAvisoActual = null;

    let bannerPendriveDescartado = false;
    let ultimoTextoBannerPendrive = null;

    function mostrarBannerPendrive(texto) {{
      if (texto !== ultimoTextoBannerPendrive) {{
        bannerPendriveDescartado = false;
        ultimoTextoBannerPendrive = texto;
      }}
      if (bannerPendriveDescartado) return;
      const b = document.getElementById('banner-pendrive-detectado');
      const t = document.getElementById('banner-pendrive-texto');
      if (b && t) {{
        t.innerText = texto;
        b.style.display = 'flex';
      }}
    }}

    function ocultarBannerPendrive() {{
      const b = document.getElementById('banner-pendrive-detectado');
      if (b) b.style.display = 'none';
    }}

    function cerrarBannerPendrive() {{
      ocultarBannerPendrive();
      bannerPendriveDescartado = true;
    }}

    function mostrarToastLlegada(mensaje) {{
      const toast = document.getElementById('toast-llegada');
      if (!toast) return;
      toast.innerText = mensaje;
      toast.classList.add('visible');
      if (temporizadorToast) clearTimeout(temporizadorToast);
      temporizadorToast = setTimeout(() => {{
        toast.classList.remove('visible');
      }}, 5000);
    }}

    function mostrarAvisoDesconexion() {{
      const banner = document.getElementById('banner-desconexion');
      if (banner) banner.style.display = 'flex';
    }}

    function ocultarAvisoDesconexion() {{
      const banner = document.getElementById('banner-desconexion');
      if (banner) banner.style.display = 'none';
    }}

    function hayModalAbierto() {{
      const idsModales = ['modal-simulacion', 'modal-terminar-capitulo', 'modal-descartar-capitulo', 'modal-plan-envio', 'modal-vincular-pendrive'];
      return idsModales.some(id => {{
        const el = document.getElementById(id);
        return el && el.style.display && el.style.display !== 'none';
      }});
    }}

    function hayCampoEnEdicion() {{
      const activo = document.activeElement;
      if (activo && (activo.tagName === 'INPUT' || activo.tagName === 'SELECT' || activo.tagName === 'TEXTAREA')) {{
        return true;
      }}
      const inputs = document.querySelectorAll('input[id^="txt-nueva-escena-"]');
      for (const inp of inputs) {{
        if (inp.value && inp.value.trim().length > 0 && inp.style.display !== 'none') {{
          return true;
        }}
      }}
      return false;
    }}

    function capturarEstadoUI() {{
      const snap = {{
        archivosChecked: {{}},
        lotesListosChecked: {{}},
        lotesAnterioresChecked: {{}},
        persSeleccionado: {{}},
        escenaSeleccionada: {{}},
        nuevaEscenaTexto: {{}},
        detailsAnterioresAbierto: false,
        scrollY: window.scrollY || document.documentElement.scrollTop || 0,
        pestana: pestanaActual
      }};

      document.querySelectorAll('.chk-archivo').forEach(cb => {{
        const id = cb.getAttribute('data-id');
        if (id) snap.archivosChecked[id] = cb.checked;
      }});

      document.querySelectorAll('.cb-lote-listo').forEach(cb => {{
        const loteId = cb.getAttribute('data-lote-id');
        if (loteId) snap.lotesListosChecked[loteId] = cb.checked;
      }});

      document.querySelectorAll('.cb-lote-anterior').forEach(cb => {{
        const loteId = cb.getAttribute('data-lote-id');
        if (loteId) snap.lotesAnterioresChecked[loteId] = cb.checked;
      }});

      document.querySelectorAll('select[id^="sel-pers-"]').forEach(sel => {{
        const loteId = sel.id.replace('sel-pers-', '');
        snap.persSeleccionado[loteId] = sel.value;
      }});

      document.querySelectorAll('select[id^="sel-escena-"]').forEach(sel => {{
        const loteId = sel.id.replace('sel-escena-', '');
        snap.escenaSeleccionada[loteId] = sel.value;
      }});

      document.querySelectorAll('input[id^="txt-nueva-escena-"]').forEach(inp => {{
        const loteId = inp.id.replace('txt-nueva-escena-', '');
        snap.nuevaEscenaTexto[loteId] = inp.value;
      }});

      const detailsAnt = document.getElementById('details-anteriores');
      if (detailsAnt) {{
        snap.detailsAnterioresAbierto = detailsAnt.hasAttribute('open');
      }}

      return snap;
    }}

    function restaurarEstadoUI(snap) {{
      if (!snap) return;

      document.querySelectorAll('.chk-archivo').forEach(cb => {{
        const id = cb.getAttribute('data-id');
        if (id && Object.prototype.hasOwnProperty.call(snap.archivosChecked, id)) {{
          cb.checked = snap.archivosChecked[id];
        }}
      }});

      document.querySelectorAll('.cb-lote-listo').forEach(cb => {{
        const loteId = cb.getAttribute('data-lote-id');
        if (loteId && Object.prototype.hasOwnProperty.call(snap.lotesListosChecked, loteId)) {{
          cb.checked = snap.lotesListosChecked[loteId];
        }}
      }});

      document.querySelectorAll('.cb-lote-anterior').forEach(cb => {{
        const loteId = cb.getAttribute('data-lote-id');
        if (loteId && Object.prototype.hasOwnProperty.call(snap.lotesAnterioresChecked, loteId)) {{
          cb.checked = snap.lotesAnterioresChecked[loteId];
        }}
      }});

      for (const loteId in snap.persSeleccionado) {{
        const sel = document.getElementById(`sel-pers-${{loteId}}`);
        if (sel) sel.value = snap.persSeleccionado[loteId];
      }}

      for (const loteId in snap.escenaSeleccionada) {{
        const sel = document.getElementById(`sel-escena-${{loteId}}`);
        if (sel) {{
          sel.value = snap.escenaSeleccionada[loteId];
          toggleNuevaEscena(loteId, sel.value);
        }}
      }}

      for (const loteId in snap.nuevaEscenaTexto) {{
        const inp = document.getElementById(`txt-nueva-escena-${{loteId}}`);
        if (inp && snap.nuevaEscenaTexto[loteId] !== undefined) {{
          inp.value = snap.nuevaEscenaTexto[loteId];
          validarInputEscena(loteId);
        }}
      }}

      const detailsAnt = document.getElementById('details-anteriores');
      if (detailsAnt) {{
        if (snap.detailsAnterioresAbierto) {{
          detailsAnt.setAttribute('open', '');
        }} else {{
          detailsAnt.removeAttribute('open');
        }}
      }}

      const todosLotes = (datosEstado.lotes || []).concat(datosEstado.lotes_anteriores || []);
      todosLotes.forEach(l => {{
        actualizarSeleccionLote(l.lote_id);
      }});

      if (typeof snap.scrollY === 'number') {{
        window.scrollTo(0, snap.scrollY);
      }}
    }}

    function escapeHTML(str) {{
      return String(str || '').replace(/[&<>'"]/g, tag => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
      }}[tag] || tag));
    }}

    function mostrarAvisoMover(totalMovidos, personaje, escena, idOperacion) {{
      operacionAvisoActual = idOperacion;
      const banner = document.getElementById('banner-aviso');
      const msg = document.getElementById('banner-aviso-msg');
      if (personaje === 'varios') {{
        msg.innerText = `Se movieron ${{totalMovidos}} archivos en ${{escena}}`;
      }} else {{
        msg.innerText = `Se movieron ${{totalMovidos}} archivos a ${{personaje}}/${{escena}}`;
      }}
      banner.style.display = 'flex';
    }}

    function mostrarAvisoDescartar(personaje, escena, idOperacion) {{
      operacionAvisoActual = idOperacion;
      const banner = document.getElementById('banner-aviso');
      const msg = document.getElementById('banner-aviso-msg');
      if (msg) {{
        msg.innerText = `Se descartó el capítulo ${{personaje}}/${{escena}} (movido a _descartados)`;
      }}
      if (banner) banner.style.display = 'flex';
    }}

    function cerrarAviso() {{
      const banner = document.getElementById('banner-aviso');
      banner.style.display = 'none';
      operacionAvisoActual = null;
    }}

    async function deshacerDesdeAviso() {{
      if (!operacionAvisoActual) return;
      const idOp = operacionAvisoActual;
      if (!confirm("¿Confirmás deshacer esta operación? Los archivos regresarán a sus rutas originales.")) {{
        return;
      }}
      try {{
        const res = await apiFetch('/api/deshacer', {{
          method: 'POST',
          body: JSON.stringify({{ id_operacion: idOp }})
        }});
        cerrarAviso();
        await cargarDatos();
        if (pestanaActual === 'historial') {{
          await cargarHistorial();
        }} else if (pestanaActual === 'capitulos-cerrados') {{
          await cargarCapitulosCerrados();
        }} else if (pestanaActual === 'descartados') {{
          await cargarCapitulosDescartados();
        }}
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    let capituloATerminarId = null;

    function mostrarPestana(pestana, ev) {{
      pestanaActual = pestana;
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      if (ev && ev.target) {{
        ev.target.classList.add('active');
      }} else {{
        const btn = document.getElementById(`nav-btn-${{pestana}}`);
        if (btn) btn.classList.add('active');
      }}

      document.getElementById('sec-lotes').style.display = (pestana === 'lotes') ? 'block' : 'none';
      document.getElementById('sec-sin-identificar').style.display = (pestana === 'sin-identificar') ? 'block' : 'none';
      document.getElementById('sec-capitulos-abiertos').style.display = (pestana === 'capitulos-abiertos') ? 'block' : 'none';
      document.getElementById('sec-capitulos-cerrados').style.display = (pestana === 'capitulos-cerrados') ? 'block' : 'none';
      document.getElementById('sec-descartados').style.display = (pestana === 'descartados') ? 'block' : 'none';
      document.getElementById('sec-pendrive').style.display = (pestana === 'pendrive') ? 'block' : 'none';
      document.getElementById('sec-historial').style.display = (pestana === 'historial') ? 'block' : 'none';

      if (pestana === 'historial') {{
        cargarHistorial();
      }} else if (pestana === 'pendrive') {{
        cargarVistaPendrive();
      }} else if (pestana === 'capitulos-abiertos') {{
        cargarCapitulosAbiertos();
      }} else if (pestana === 'capitulos-cerrados') {{
        cargarCapitulosCerrados();
      }} else if (pestana === 'descartados') {{
        cargarCapitulosDescartados();
      }}
    }}

    async function recargarVistaActual() {{
      if (pestanaActual === 'historial') {{
        await cargarHistorial();
      }} else if (pestanaActual === 'pendrive') {{
        await cargarVistaPendrive();
      }} else if (pestanaActual === 'capitulos-abiertos') {{
        await cargarCapitulosAbiertos();
      }} else if (pestanaActual === 'capitulos-cerrados') {{
        await cargarCapitulosCerrados();
      }} else if (pestanaActual === 'descartados') {{
        await cargarCapitulosDescartados();
      }} else {{
        await cargarDatos();
      }}
    }}

    function mostrarError(msg) {{
      const b = document.getElementById('alert-box');
      b.innerText = msg;
      b.style.display = 'block';
      setTimeout(() => {{ b.style.display = 'none'; }}, 8000);
    }}

    async function apiFetch(url, options = {{}}) {{
      options.headers = options.headers || {{}};
      if (options.method && options.method.toUpperCase() === 'POST') {{
        options.headers['Content-Type'] = 'application/json';
        options.headers['X-CSRF-Token'] = CSRF_TOKEN;
      }}
      const res = await fetch(url, options);
      if (!res.ok) {{
        const err = await res.json().catch(() => ({{ error: res.statusText }}));
        throw new Error(err.error || 'Error en la petición');
      }}
      return await res.json();
    }}

    async function cargarDatos() {{
      try {{
        const [lotesRes, sinIdRes, escenasRes, persRes, capRes, versionRes] = await Promise.all([
          apiFetch('/api/lotes'),
          apiFetch('/api/sin-identificar'),
          apiFetch('/api/escenas'),
          apiFetch('/api/personajes'),
          apiFetch('/api/capitulos/estado'),
          apiFetch('/api/estado-version').catch(() => null)
        ]);
        if (versionRes && versionRes.version) {{
          versionActualToken = versionRes.version;
        }}
        datosEstado.lotes = lotesRes.lotes || [];
        datosEstado.lotes_anteriores = lotesRes.lotes_anteriores || [];
        datosEstado.sin_identificar = sinIdRes.sin_identificar || [];
        datosEstado.escenas = escenasRes.escenas || [];
        datosEstado.personajes = persRes.personajes || [];
        datosEstado.ultimo_personaje = persRes.ultimo_personaje;
        datosEstado.capitulo_activo = capRes.capitulo_foco || capRes.capitulo;
        datosEstado.capitulo_foco = capRes.capitulo_foco;
        datosEstado.capitulos_abiertos = capRes.capitulos_abiertos || [];
        datosEstado.cantidad_abiertos = capRes.cantidad_abiertos || 0;
        datosEstado.alerta_olvidado = capRes.alerta_olvidado;
        datosEstado.horas_limite = capRes.horas_limite;
        datosEstado.balance_capitulo = capRes.balance;
        renderCapituloActivo();
        renderLotes();
        renderLotesAnteriores();
        renderSinIdentificar();
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function recargarConPreservacion() {{
      const snap = capturarEstadoUI();
      const enEdicion = hayCampoEnEdicion();

      try {{
        const [lotesRes, sinIdRes, escenasRes, persRes, capRes, versionRes] = await Promise.all([
          apiFetch('/api/lotes'),
          apiFetch('/api/sin-identificar'),
          apiFetch('/api/escenas'),
          apiFetch('/api/personajes'),
          apiFetch('/api/capitulos/estado'),
          apiFetch('/api/estado-version').catch(() => null)
        ]);

        if (versionRes && versionRes.version) {{
          versionActualToken = versionRes.version;
        }}

        const nuevosLotes = lotesRes.lotes || [];
        const nuevosAnt = lotesRes.lotes_anteriores || [];

        const idsLotesPrevios = new Set((datosEstado.lotes || []).map(l => l.lote_id));
        const lotesNuevosEntrantes = nuevosLotes.filter(l => !l.es_anterior && !idsLotesPrevios.has(l.lote_id));

        const idsArchivosPrevios = new Set();
        (datosEstado.lotes || []).forEach(l => (l.archivos || []).forEach(a => idsArchivosPrevios.add(String(a.id_db))));
        (datosEstado.lotes_anteriores || []).forEach(l => (l.archivos || []).forEach(a => idsArchivosPrevios.add(String(a.id_db))));

        let cantArchivosNuevos = 0;
        nuevosLotes.forEach(l => (l.archivos || []).forEach(a => {{
          if (!idsArchivosPrevios.has(String(a.id_db))) cantArchivosNuevos++;
        }}));
        nuevosAnt.forEach(l => (l.archivos || []).forEach(a => {{
          if (!idsArchivosPrevios.has(String(a.id_db))) cantArchivosNuevos++;
        }}));

        datosEstado.lotes = nuevosLotes;
        datosEstado.lotes_anteriores = nuevosAnt;
        datosEstado.sin_identificar = sinIdRes.sin_identificar || [];
        datosEstado.escenas = escenasRes.escenas || [];
        datosEstado.personajes = persRes.personajes || [];
        datosEstado.ultimo_personaje = persRes.ultimo_personaje;
        datosEstado.capitulo_activo = capRes.capitulo_foco || capRes.capitulo;
        datosEstado.capitulo_foco = capRes.capitulo_foco;
        datosEstado.capitulos_abiertos = capRes.capitulos_abiertos || [];
        datosEstado.cantidad_abiertos = capRes.cantidad_abiertos || 0;
        datosEstado.alerta_olvidado = capRes.alerta_olvidado;
        datosEstado.horas_limite = capRes.horas_limite;
        datosEstado.balance_capitulo = capRes.balance;

        renderCapituloActivo();
        if (enEdicion) {{
          renderLotesIncremental();
          renderLotesAnterioresIncremental();
        }} else {{
          renderLotes();
          renderLotesAnteriores();
        }}
        renderSinIdentificar();
        restaurarEstadoUI(snap);

        if (cantArchivosNuevos > 0) {{
          mostrarToastLlegada(`Llegaron ${{cantArchivosNuevos}} archivo(s) nuevo(s)`);
          if (document.hidden && lotesNuevosEntrantes.length > 0) {{
            lotesNuevosSegundoPlano += lotesNuevosEntrantes.length;
            document.title = `(${{lotesNuevosSegundoPlano}}) ${{TITULO_BASE}}`;
          }}
        }}

        if (pestanaActual === 'capitulos-abiertos') {{
          await cargarCapitulosAbiertos();
        }} else if (pestanaActual === 'capitulos-cerrados') {{
          await cargarCapitulosCerrados();
        }} else if (pestanaActual === 'descartados') {{
          await cargarCapitulosDescartados();
        }} else if (pestanaActual === 'pendrive') {{
          await cargarVistaPendrive();
        }} else if (pestanaActual === 'historial') {{
          await cargarHistorial();
        }}
      }} catch (e) {{
        console.error('Error al recargar con preservación:', e);
      }}
    }}

    function programarSiguienteSondeo(esperaMs) {{
      if (temporizadorSondeo) {{
        clearTimeout(temporizadorSondeo);
        temporizadorSondeo = null;
      }}
      if (REFRESCO_PANEL_SEGUNDOS <= 0) return;

      const ms = (typeof esperaMs === 'number') ? esperaMs : (reintentoEsperaSegundos * 1000);
      temporizadorSondeo = setTimeout(verificarVersionEstado, ms);
    }}

    async function verificarVersionEstado() {{
      if (REFRESCO_PANEL_SEGUNDOS <= 0) return;
      if (sondeoEnCurso) return;
      if (temporizadorSondeo) {{
        clearTimeout(temporizadorSondeo);
        temporizadorSondeo = null;
      }}

      if (document.hidden) {{
        return;
      }}

      if (hayModalAbierto()) {{
        programarSiguienteSondeo();
        return;
      }}

      sondeoEnCurso = true;
      try {{
        const res = await apiFetch('/api/estado-version');

        if (res.banner_pendrive) {{
          if (typeof res.banner_pendrive === 'string') {{
            mostrarBannerPendrive(res.banner_pendrive);
          }} else if (res.banner_pendrive.mensaje) {{
            mostrarBannerPendrive(res.banner_pendrive.mensaje);
          }}
        }} else {{
          ocultarBannerPendrive();
        }}

        if (desconectado) {{
          desconectado = false;
          ocultarAvisoDesconexion();
          reintentoEsperaSegundos = REFRESCO_PANEL_SEGUNDOS > 0 ? REFRESCO_PANEL_SEGUNDOS : 4;
          versionActualToken = res.version;
          await recargarConPreservacion();
          programarSiguienteSondeo();
          return;
        }}

        reintentoEsperaSegundos = REFRESCO_PANEL_SEGUNDOS > 0 ? REFRESCO_PANEL_SEGUNDOS : 4;

        if (versionActualToken === null) {{
          versionActualToken = res.version;
        }} else if (res.version !== versionActualToken) {{
          versionActualToken = res.version;
          await recargarConPreservacion();
        }}

        programarSiguienteSondeo();
      }} catch (e) {{
        console.warn('Fallo en sondeo de estado-version:', e);
        desconectado = true;
        mostrarAvisoDesconexion();
        reintentoEsperaSegundos = Math.min(reintentoEsperaSegundos * 2, 30);
        programarSiguienteSondeo(reintentoEsperaSegundos * 1000);
      }} finally {{
        sondeoEnCurso = false;
      }}
    }}

    document.addEventListener('visibilitychange', () => {{
      if (!document.hidden) {{
        lotesNuevosSegundoPlano = 0;
        document.title = TITULO_BASE;
        verificarVersionEstado();
      }}
    }});

    window.addEventListener('focus', () => {{
      lotesNuevosSegundoPlano = 0;
      document.title = TITULO_BASE;
    }});

    function renderCapituloActivo() {{
      const bannerActivo = document.getElementById('banner-capitulo-activo');
      const bannerSinFoco = document.getElementById('banner-sin-foco');
      const cardEmpezar = document.getElementById('card-empezar-capitulo');
      const bannerOlvidado = document.getElementById('banner-capitulo-olvidado');
      const errSpan = document.getElementById('error-capitulo-activo');
      if (errSpan) {{
        errSpan.style.display = 'none';
        errSpan.innerText = '';
      }}

      const capFoco = datosEstado.capitulo_foco;
      const esFoco = capFoco && capFoco.habilitado && capFoco.nombre;
      const cantAbiertos = datosEstado.cantidad_abiertos || 0;

      const badgeNav = document.getElementById('conteo-nav-abiertos');
      if (badgeNav) badgeNav.innerText = cantAbiertos;

      if (esFoco) {{
        if (cardEmpezar) cardEmpezar.style.display = 'none';
        if (bannerSinFoco) bannerSinFoco.style.display = 'none';
        if (bannerActivo) {{
          bannerActivo.style.display = 'flex';
          const titulo = document.getElementById('banner-capitulo-titulo');
          const subtitulo = document.getElementById('banner-capitulo-subtitulo');
          const otrosSpan = document.getElementById('banner-otros-abiertos');

          if (titulo) titulo.innerText = `Capítulo en foco: ${{capFoco.personaje}}/${{capFoco.nombre}}`;
          if (otrosSpan) {{
            if (cantAbiertos > 1) {{
              otrosSpan.innerText = `(+${{cantAbiertos - 1}} abierto(s))`;
              otrosSpan.style.display = 'inline';
            }} else {{
              otrosSpan.style.display = 'none';
            }}
          }}
          if (subtitulo) {{
            const fechaTxt = capFoco.fecha_inicio ? capFoco.fecha_inicio.replace('T', ' ').slice(0, 19) : '';
            const movidos = (datosEstado.balance_capitulo && datosEstado.balance_capitulo.movidos !== undefined) ? datosEstado.balance_capitulo.movidos : (capFoco.archivos_movidos || 0);
            let textoSub = `Iniciado: ${{fechaTxt}} | ${{movidos}} archivo(s) movido(s). Todo archivo nuevo entrante se asigna a esta historia.`;
            if (capFoco.carpeta_info && capFoco.carpeta_info.ya_existia && capFoco.carpeta_info.total_archivos > 0) {{
              textoSub += ` • ℹ️ ${{capFoco.carpeta_info.mensaje}}`;
            }} else if (datosEstado.mensaje_carpeta_existente) {{
              textoSub += ` • ℹ️ ${{datosEstado.mensaje_carpeta_existente}}`;
            }}
            subtitulo.innerText = textoSub;
          }}
        }}
        if (bannerOlvidado) {{
          bannerOlvidado.style.display = datosEstado.alerta_olvidado ? 'flex' : 'none';
          const txtOlv = document.getElementById('banner-olvidado-texto');
          if (txtOlv) txtOlv.innerText = `⚠️ ¿Sigue activo este capítulo? Lleva más de ${{datosEstado.horas_limite || 12}} horas abierto.`;
        }}
      }} else {{
        if (bannerActivo) bannerActivo.style.display = 'none';
        if (bannerOlvidado) bannerOlvidado.style.display = 'none';
        if (cantAbiertos > 0) {{
          if (bannerSinFoco) bannerSinFoco.style.display = 'flex';
          if (cardEmpezar) cardEmpezar.style.display = 'none';
        }} else {{
          if (bannerSinFoco) bannerSinFoco.style.display = 'none';
          if (cardEmpezar) {{
            cardEmpezar.style.display = 'block';
            const txtNombre = document.getElementById('txt-capitulo-nombre');
            if (txtNombre && (!datosEstado.capitulo_activo || !datosEstado.capitulo_activo.nombre)) txtNombre.value = '';
          }}
        }}
      }}
    }}

    async function empezarCapitulo() {{
      const selPers = document.getElementById('sel-capitulo-personaje');
      const txtNombre = document.getElementById('txt-capitulo-nombre');
      const errSpan = document.getElementById('error-capitulo-activo');

      const personaje = (selPers ? selPers.value : 'lucie').trim();
      const nombre = (txtNombre ? txtNombre.value : '').trim();

      const err = validarNombreEscena(nombre);
      if (err) {{
        if (errSpan) {{
          errSpan.innerText = err;
          errSpan.style.display = 'inline-block';
        }}
        return;
      }}
      if (errSpan) {{ errSpan.style.display = 'none'; }}

      try {{
        const res = await apiFetch('/api/capitulos/empezar', {{
          method: 'POST',
          body: JSON.stringify({{ personaje, nombre }})
        }});
        if (txtNombre) txtNombre.value = '';
        if (res && res.carpeta_info && res.carpeta_info.ya_existia && res.carpeta_info.total_archivos > 0) {{
          datosEstado.mensaje_carpeta_existente = res.carpeta_info.mensaje;
        }} else {{
          datosEstado.mensaje_carpeta_existente = null;
        }}
        await cargarDatos();
      }} catch (e) {{
        if (errSpan) {{
          errSpan.innerText = e.message;
          errSpan.style.display = 'inline-block';
        }} else {{
          mostrarError(e.message);
        }}
      }}
    }}

    async function empezarCapituloSecundario() {{
      const selPers = document.getElementById('sel-nuevo-capitulo-pers');
      const txtNombre = document.getElementById('txt-nuevo-capitulo-nom');
      const errSpan = document.getElementById('error-nuevo-capitulo');

      const personaje = (selPers ? selPers.value : 'lucie').trim();
      const nombre = (txtNombre ? txtNombre.value : '').trim();

      const err = validarNombreEscena(nombre);
      if (err) {{
        if (errSpan) {{
          errSpan.innerText = err;
          errSpan.style.display = 'inline-block';
        }}
        return;
      }}
      if (errSpan) {{ errSpan.style.display = 'none'; }}

      try {{
        await apiFetch('/api/capitulos/empezar', {{
          method: 'POST',
          body: JSON.stringify({{ personaje, nombre }})
        }});
        if (txtNombre) txtNombre.value = '';
        await cargarDatos();
        await cargarCapitulosAbiertos();
      }} catch (e) {{
        if (errSpan) {{
          errSpan.innerText = e.message;
          errSpan.style.display = 'inline-block';
        }} else {{
          mostrarError(e.message);
        }}
      }}
    }}

    async function cargarCapitulosAbiertos() {{
      const cont = document.getElementById('contenedor-capitulos-abiertos');
      if (!cont) return;
      try {{
        const res = await apiFetch('/api/capitulos/abiertos');
        const abiertos = res.abiertos || [];
        const badgeNav = document.getElementById('conteo-nav-abiertos');
        if (badgeNav) badgeNav.innerText = abiertos.length;

        if (!abiertos.length) {{
          cont.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay capítulos abiertos actualmente.</p>';
          return;
        }}

        cont.innerHTML = `
          <table class="tabla-historial">
            <thead>
              <tr>
                <th style="width:12%;">Personaje</th>
                <th style="width:22%;">Capítulo</th>
                <th style="width:14%; text-align:center;">Foco</th>
                <th style="width:16%;">Fecha Inicio</th>
                <th style="width:8%; text-align:center;">Movidos</th>
                <th style="width:8%; text-align:center;">Pendientes</th>
                <th style="width:20%; text-align:center;">Acciones</th>
              </tr>
            </thead>
            <tbody>
              ${{abiertos.map(c => {{
                const bal = c.balance || {{ pendientes: 0, movidos: 0 }};
                const mov = bal.movidos !== undefined ? bal.movidos : (c.archivos_movidos || 0);
                const fechaTxt = (c.fecha_inicio || '').replace('T', ' ').slice(0, 19);
                const badgeFoco = c.en_foco 
                  ? '<span class="badge" style="background:#f59e0b; color:#000; font-weight:700;">⭐ En foco</span>'
                  : '<span style="color:var(--text-muted); font-size:0.85rem;">Secundario</span>';
                
                const btnFoco = !c.en_foco
                  ? `<button class="btn-sm" onclick="ponerEnFoco(${{c.id}})" style="background:var(--accent); color:#000; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;" title="Poner en foco para recibir descargas nuevas">Poner en foco</button>`
                  : '';
                
                return `
                  <tr style="${{c.en_foco ? 'background:rgba(99, 102, 241, 0.1);' : ''}}">
                    <td><code>${{escapeHTML(c.personaje)}}</code></td>
                    <td><strong>${{escapeHTML(c.nombre)}}</strong></td>
                    <td style="text-align:center;">${{badgeFoco}}</td>
                    <td style="color:var(--text-muted);">${{fechaTxt}}</td>
                    <td style="text-align:center;"><strong>${{mov}}</strong></td>
                    <td style="text-align:center;">${{bal.pendientes}}</td>
                    <td style="text-align:center;">
                      <div style="display:flex; gap:6px; justify-content:center; align-items:center; flex-wrap:wrap;">
                        ${{btnFoco}}
                        <button class="btn-sm" onclick="abrirModalPlanEnvio('${{escapeHTML(c.personaje)}}/${{escapeHTML(c.nombre)}}')" style="background:#10b981; color:#000; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;" title="Enviar material al pendrive">
                          Enviar al pendrive
                        </button>
                        <button class="btn-sm" onclick="abrirModalTerminarCapitulo(${{c.id}})" style="background:#ef4444; color:#fff; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;">
                          Terminar
                        </button>
                        <button class="btn-sm" onclick="abrirModalDescartarCapitulo(${{c.id}}, '${{escapeHTML(c.nombre)}}', '${{escapeHTML(c.personaje)}}')" style="background:#4b5563; color:#fff; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;">
                          Descartar
                        </button>
                      </div>
                    </td>
                  </tr>
                `;
              }}).join('')}}
            </tbody>
          </table>
        `;
      }} catch (e) {{
        cont.innerHTML = `<p style="color:var(--error); padding:16px;">Error al cargar capítulos abiertos: ${{escapeHTML(e.message)}}</p>`;
      }}
    }}

    async function ponerEnFoco(id) {{
      try {{
        await apiFetch('/api/capitulos/en-foco', {{
          method: 'POST',
          body: JSON.stringify({{ id: id }})
        }});
        await cargarDatos();
        await cargarCapitulosAbiertos();
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function abrirModalTerminarCapitulo(idCap) {{
      try {{
        capituloATerminarId = (idCap !== undefined && idCap !== null) ? idCap : ((datosEstado.capitulo_foco && datosEstado.capitulo_foco.id) || null);
        const res = await apiFetch('/api/capitulos/estado');
        let cap = res.capitulo_foco || res.capitulo;
        let bal = res.balance || {{ pendientes: 0, movidos: 0 }};

        if (idCap && datosEstado.capitulos_abiertos) {{
          const capObj = datosEstado.capitulos_abiertos.find(c => c.id === idCap);
          if (capObj) {{
            cap = capObj;
            bal = capObj.balance || bal;
          }}
        }}

        const cont = document.getElementById('modal-terminar-resumen');
        if (cont && cap) {{
          cont.innerHTML = `
            <p style="margin-bottom:8px;">Capítulo a terminar: <strong>${{escapeHTML(cap.personaje)}} / ${{escapeHTML(cap.nombre)}}</strong></p>
            <div style="background:var(--card-alt); padding:12px; border-radius:6px; margin:12px 0;">
              <div style="margin-bottom:6px;">📁 <strong>${{bal.pendientes}}</strong> archivo(s) pendiente(s) en Descargas</div>
              <div>📦 <strong>${{bal.movidos}}</strong> archivo(s) ya movido(s) al destino</div>
            </div>
            <p style="color:var(--text-muted); font-size:0.85rem;">
              Al terminar, el capítulo queda cerrado: no se le asignará ningún archivo nuevo y lo que llegue después seguirá el circuito sin capítulo en foco.
            </p>
          `;
        }}
        document.getElementById('modal-terminar-capitulo').style.display = 'flex';
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    function cerrarModalTerminarCapitulo() {{
      document.getElementById('modal-terminar-capitulo').style.display = 'none';
      capituloATerminarId = null;
      programarSiguienteSondeo(500);
    }}

    async function ejecutarTerminarCapitulo(trasMover) {{
      try {{
        const payload = {{
          accion: trasMover ? 'mover_pendientes' : 'sin_mover'
        }};
        if (capituloATerminarId !== null) {{
          payload.id = capituloATerminarId;
        }}
        await apiFetch('/api/capitulos/terminar', {{
          method: 'POST',
          body: JSON.stringify(payload)
        }});
        cerrarModalTerminarCapitulo();
        await cargarDatos();
        if (pestanaActual === 'capitulos-abiertos') {{
          await cargarCapitulosAbiertos();
        }} else if (pestanaActual === 'capitulos-cerrados') {{
          await cargarCapitulosCerrados();
        }}
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function posponerAlertaCapitulo() {{
      try {{
        await apiFetch('/api/capitulos/posponer_alerta', {{
          method: 'POST',
          body: JSON.stringify({{}})
        }});
        await cargarDatos();
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function ejecutarMoverYTerminar() {{
      cerrarModalTerminarCapitulo();
      const cap = datosEstado.capitulo_activo;
      if (!cap || !cap.habilitado) {{
        await ejecutarTerminarCapitulo(false);
        return;
      }}
      const lotesCapitulo = datosEstado.lotes.filter(l =>
        (l.personaje_sugerido === cap.personaje || cap.personaje) &&
        (l.escena_sugerida === cap.nombre || l.raiz_escena === `${{cap.personaje}}::${{cap.nombre}}`)
      );
      if (!lotesCapitulo.length) {{
        await ejecutarTerminarCapitulo(true);
        return;
      }}
      terminarCapituloTrasMover = true;
      if (lotesCapitulo.length === 1) {{
        await simularMoverLote(lotesCapitulo[0].lote_id);
      }} else {{
        await simularMoverLotesListos();
      }}
    }}

    async function cargarCapitulosCerrados() {{
      const cont = document.getElementById('contenedor-capitulos-cerrados');
      if (!cont) return;
      try {{
        const res = await apiFetch('/api/capitulos/cerrados');
        const cerrados = res.cerrados || [];
        if (!cerrados.length) {{
          cont.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay capítulos cerrados en el historial.</p>';
          return;
        }}
        cont.innerHTML = `
          <table class="tabla-historial">
            <thead>
              <tr>
                <th style="width:12%;">Personaje</th>
                <th style="width:25%;">Capítulo</th>
                <th style="width:18%;">Fecha Inicio</th>
                <th style="width:18%;">Fecha Fin</th>
                <th style="width:9%; text-align:center;">Movidos</th>
                <th style="width:18%; text-align:center;">Acción</th>
              </tr>
            </thead>
            <tbody>
              ${{cerrados.map(c => `
                <tr>
                  <td><code>${{escapeHTML(c.personaje)}}</code></td>
                  <td><strong>${{escapeHTML(c.nombre)}}</strong></td>
                  <td style="color:var(--text-muted);">${{(c.fecha_inicio || '').replace('T', ' ').slice(0, 19)}}</td>
                  <td style="color:var(--text-muted);">${{(c.fecha_fin || '').replace('T', ' ').slice(0, 19)}}</td>
                  <td style="text-align:center;"><strong>${{c.archivos_movidos || 0}}</strong></td>
                  <td style="text-align:center;">
                    <button class="btn-sm" onclick="abrirModalPlanEnvio('${{escapeHTML(c.personaje)}}/${{escapeHTML(c.nombre)}}')" style="background:#10b981; color:#000; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;" title="Enviar material al pendrive">
                      Enviar al pendrive
                    </button>
                    <button class="btn-sm" onclick="reabrirCapitulo(${{c.id}})" style="background:var(--teal); color:#000; font-weight:600; padding:4px 10px; border-radius:4px; border:none; cursor:pointer; margin-left:6px;">
                      Reabrir
                    </button>
                    <button class="btn-sm" onclick="abrirModalDescartarCapitulo(${{c.id}}, '${{escapeHTML(c.nombre)}}', '${{escapeHTML(c.personaje)}}')" style="background:#4b5563; color:#fff; font-weight:600; padding:4px 10px; border-radius:4px; border:none; cursor:pointer; margin-left:6px;">
                      Descartar
                    </button>
                  </td>
                </tr>
              `).join('')}}
            </tbody>
          </table>
        `;
      }} catch (e) {{
        cont.innerHTML = `<p style="color:var(--error); padding:16px;">Error al cargar capítulos: ${{escapeHTML(e.message)}}</p>`;
      }}
    }}

    async function reabrirCapitulo(id) {{
      try {{
        await apiFetch('/api/capitulos/reabrir', {{
          method: 'POST',
          body: JSON.stringify({{ id: id }})
        }});
        await cargarDatos();
        mostrarPestana('lotes');
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function cargarCapitulosDescartados() {{
      const cont = document.getElementById('contenedor-capitulos-descartados');
      if (!cont) return;
      try {{
        const res = await apiFetch('/api/capitulos/descartados');
        const descartados = res.descartados || [];
        if (!descartados.length) {{
          cont.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay capítulos descartados en cuarentena.</p>';
          return;
        }}
        cont.innerHTML = `
          <table class="tabla-historial">
            <thead>
              <tr>
                <th style="width:12%;">Personaje</th>
                <th style="width:25%;">Capítulo</th>
                <th style="width:22%;">Fecha Inicio</th>
                <th style="width:22%;">Fecha Descarte</th>
                <th style="width:19%; text-align:center;">Estado</th>
              </tr>
            </thead>
            <tbody>
              ${{descartados.map(c => `
                <tr>
                  <td><code>${{escapeHTML(c.personaje)}}</code></td>
                  <td><strong>${{escapeHTML(c.nombre)}}</strong></td>
                  <td style="color:var(--text-muted);">${{(c.fecha_inicio || '').replace('T', ' ').slice(0, 19)}}</td>
                  <td style="color:var(--text-muted);">${{(c.fecha_descartado || c.fecha_fin || '').replace('T', ' ').slice(0, 19)}}</td>
                  <td style="text-align:center;">
                    <span class="badge-descartado">Descartado</span>
                  </td>
                </tr>
              `).join('')}}
            </tbody>
          </table>
        `;
      }} catch (e) {{
        cont.innerHTML = `<p style="color:var(--error); padding:16px;">Error al cargar descartados: ${{escapeHTML(e.message)}}</p>`;
      }}
    }}

    function descartarCapituloActivo() {{
      const cap = datosEstado.capitulo_activo;
      if (!cap || !cap.id) {{
        mostrarError("No hay capítulo activo para descartar.");
        return;
      }}
      abrirModalDescartarCapitulo(cap.id, cap.nombre, cap.personaje);
    }}

    async function abrirModalDescartarCapitulo(idCapitulo, nombreCapitulo, personaje) {{
      try {{
        const modal = document.getElementById('modal-descartar-capitulo');
        const detalles = document.getElementById('modal-descartar-detalles');
        const txtConfirm = document.getElementById('txt-confirmar-descartar');
        const lblEsperado = document.getElementById('nombre-capitulo-esperado');
        const btnConfirm = document.getElementById('btn-confirmar-descartar');
        const errSpan = document.getElementById('error-confirmar-descartar');

        txtConfirm.value = '';
        btnConfirm.disabled = true;
        btnConfirm.style.cursor = 'not-allowed';
        btnConfirm.style.opacity = '0.5';
        if (errSpan) {{
          errSpan.style.display = 'none';
          errSpan.innerText = '';
        }}
        if (lblEsperado) lblEsperado.innerText = nombreCapitulo || '';

        detalles.innerHTML = '<p style="color:var(--text-muted)">Calculando simulación de descarte...</p>';
        modal.style.display = 'flex';

        const sim = await apiFetch('/api/capitulos/descartar-simular', {{
          method: 'POST',
          body: JSON.stringify({{ id: idCapitulo }})
        }});
        descarteSimulacionActiva = sim;

        let notaVacio = '';
        if (!sim.carpeta_existe || sim.carpeta_vacia) {{
          notaVacio = '<p style="color:#f59e0b; margin-top:8px;"><em>Nota: La carpeta no existe o está vacía. Se descartará el registro en la base de datos sin mover archivos.</em></p>';
        }}

        detalles.innerHTML = `
          <p style="margin-bottom:8px;">Capítulo: <strong>${{escapeHTML(sim.escena)}}</strong> (${{escapeHTML(sim.personaje)}})</p>
          <div style="background:var(--card-alt); padding:12px; border-radius:6px; margin:12px 0; font-size:0.9rem;">
            <div>📁 <strong>Origen:</strong> <code style="word-break:break-all;">${{escapeHTML(sim.origen_carpeta)}}</code></div>
            <div style="margin-top:6px;">📦 <strong>Destino en cuarentena:</strong> <code style="word-break:break-all; color:var(--teal);">${{escapeHTML(sim.destino_carpeta)}}</code></div>
            <div style="margin-top:6px;">📊 <strong>Total archivos:</strong> ${{sim.total_archivos}} &bull; <strong>Peso:</strong> ${{escapeHTML(sim.peso_total_fmt || '0 B')}}</div>
          </div>
          ${{notaVacio}}
        `;
      }} catch (e) {{
        mostrarError(e.message);
        cerrarModalDescartarCapitulo();
      }}
    }}

    function validarConfirmacionDescartar() {{
      const txtConfirm = document.getElementById('txt-confirmar-descartar');
      const btnConfirm = document.getElementById('btn-confirmar-descartar');
      const errSpan = document.getElementById('error-confirmar-descartar');
      if (!descarteSimulacionActiva || !txtConfirm || !btnConfirm) return;

      const esperado = (descarteSimulacionActiva.escena || '').trim();
      const ingresado = txtConfirm.value.trim();

      if (ingresado === esperado) {{
        btnConfirm.disabled = false;
        btnConfirm.style.cursor = 'pointer';
        btnConfirm.style.opacity = '1';
        if (errSpan) errSpan.style.display = 'none';
      }} else {{
        btnConfirm.disabled = true;
        btnConfirm.style.cursor = 'not-allowed';
        btnConfirm.style.opacity = '0.5';
      }}
    }}

    async function ejecutarDescarteCapitulo() {{
      if (!descarteSimulacionActiva) return;
      const txtConfirm = document.getElementById('txt-confirmar-descartar');
      const nombreConfirmacion = (txtConfirm ? txtConfirm.value : '').trim();
      const escena = descarteSimulacionActiva.escena;
      const pers = descarteSimulacionActiva.personaje;

      try {{
        const res = await apiFetch('/api/capitulos/descartar', {{
          method: 'POST',
          body: JSON.stringify({{
            simulacion: descarteSimulacionActiva,
            nombre_confirmacion: nombreConfirmacion
          }})
        }});
        cerrarModalDescartarCapitulo();
        mostrarAvisoDescartar(pers, escena, res.id_operacion);
        await cargarDatos();
        if (pestanaActual === 'capitulos-cerrados') {{
          await cargarCapitulosCerrados();
        }} else if (pestanaActual === 'descartados') {{
          await cargarCapitulosDescartados();
        }} else if (pestanaActual === 'historial') {{
          await cargarHistorial();
        }}
      }} catch (e) {{
        const errSpan = document.getElementById('error-confirmar-descartar');
        if (errSpan) {{
          errSpan.innerText = e.message;
          errSpan.style.display = 'block';
        }} else {{
          mostrarError(e.message);
        }}
      }}
    }}

    function cerrarModalDescartarCapitulo() {{
      const modal = document.getElementById('modal-descartar-capitulo');
      if (modal) modal.style.display = 'none';
      descarteSimulacionActiva = null;
      programarSiguienteSondeo(500);
    }}

    async function guardarCapituloActivo(habilitar) {{
      const selPers = document.getElementById('sel-capitulo-personaje');
      const txtNombre = document.getElementById('txt-capitulo-nombre');
      const errSpan = document.getElementById('error-capitulo-activo');

      const personaje = (selPers ? selPers.value : 'lucie').trim();
      const nombre = (txtNombre ? txtNombre.value : '').trim();

      if (habilitar) {{
        const err = validarNombreEscena(nombre);
        if (err) {{
          if (errSpan) {{
            errSpan.innerText = err;
            errSpan.style.display = 'inline-block';
          }}
          return;
        }}
      }}
      if (errSpan) {{
        errSpan.style.display = 'none';
        errSpan.innerText = '';
      }}

      try {{
        await apiFetch('/api/capitulo-activo', {{
          method: 'POST',
          body: JSON.stringify({{ personaje, nombre, habilitado }})
        }});
        await cargarDatos();
      }} catch (e) {{
        if (errSpan) {{
          errSpan.innerText = e.message;
          errSpan.style.display = 'inline-block';
        }} else {{
          mostrarError(e.message);
        }}
      }}
    }}

    function generarHtmlCardLote(lote) {{
      const capFoco = (datosEstado.capitulo_foco && datosEstado.capitulo_foco.habilitado) ? datosEstado.capitulo_foco : 
                      ((datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado) ? datosEstado.capitulo_activo : null);
      const capsAbiertos = datosEstado.capitulos_abiertos || [];
      const nombresAbiertos = new Set(capsAbiertos.map(c => c.nombre));

      const persPre = capFoco ? capFoco.personaje : (lote.personaje_sugerido || datosEstado.ultimo_personaje || 'lucie');
      const escenaPre = capFoco ? capFoco.nombre : (lote.escena_sugerida || '');

      const persOptions = datosEstado.personajes.map(p => 
        `<option value="${{p.id}}" ${{p.id === persPre ? 'selected' : ''}}>${{p.nombre}}</option>`
      ).join('');

      let optFoco = '';
      if (capFoco) {{
        optFoco = `<option value="${{escapeHTML(capFoco.nombre)}}" data-tipo="capitulo_foco" data-personaje="${{escapeHTML(capFoco.personaje)}}" selected>[Capítulo en foco] ${{escapeHTML(capFoco.nombre)}}</option>`;
      }}

      const optsAbiertosSecundarios = capsAbiertos
        .filter(c => !capFoco || c.id !== capFoco.id)
        .map(c => {{
          const isSelected = (!capFoco && c.nombre === escenaPre);
          return `<option value="${{escapeHTML(c.nombre)}}" data-tipo="capitulo_abierto" data-personaje="${{escapeHTML(c.personaje)}}" ${{isSelected ? 'selected' : ''}}>[Capítulo abierto] ${{escapeHTML(c.personaje)}}/${{escapeHTML(c.nombre)}}</option>`;
        }})
        .join('');

      const matchAbiertoSecundario = !capFoco && capsAbiertos.some(c => c.nombre === escenaPre);
      const matchOtraEscena = !capFoco && (datosEstado.escenas || []).some(e => !nombresAbiertos.has(e.nombre) && e.nombre === escenaPre);
      const esNueva = !capFoco && !matchAbiertoSecundario && !matchOtraEscena;

      const optNueva = `<option value="__nueva__" ${{esNueva ? 'selected' : ''}}>+ Crear nueva escena...</option>`;

      const otrasEscenas = (datosEstado.escenas || [])
        .filter(e => !nombresAbiertos.has(e.nombre))
        .map(e => `<option value="${{escapeHTML(e.nombre)}}" data-tipo="${{e.tipo}}" ${{(matchOtraEscena && e.nombre === escenaPre) ? 'selected' : ''}}>[${{e.tipo === 'descargas_alias' ? 'En Descargas' : 'Destino'}}] ${{escapeHTML(e.nombre)}}</option>`)
        .join('');

      const escenasOptions = optFoco + optsAbiertosSecundarios + optNueva + otrasEscenas;

      return `
        <div class="card" id="card-${{lote.lote_id}}">
          <div class="card-header">
            <div style="display:flex; align-items:center; gap:10px;">
              <input type="checkbox" class="cb-lote-listo" data-lote-id="${{lote.lote_id}}" checked title="Tildar para mover con 'Mover lotes listos'">
              <h3>Lote #${{lote.numero}} (${{lote.total_archivos}} archivos &bull; ${{formatearBytes(lote.total_bytes)}})</h3>
            </div>
            <span style="color:var(--text-muted);font-size:0.85rem">${{lote.fecha}}</span>
          </div>
          <div class="lote-toolbar">
            <span id="lbl-sel-${{lote.lote_id}}" style="font-size:0.85rem; color:var(--text-muted);">${{lote.archivos.length}} seleccionados</span>
            <div style="display:flex; gap:8px;">
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${{lote.lote_id}}', true)">Seleccionar todos</button>
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${{lote.lote_id}}', false)">Ninguno</button>
            </div>
          </div>
          <div class="archivos-grid">
            ${{lote.archivos.map(a => `
              <div class="archivo-item" title="Archivo: ${{a.nombre}}&#10;Fecha llegada: ${{a.fecha_llegada || a.fecha || ''}}&#10;Fecha modificación: ${{a.fecha || ''}}&#10;Tamaño: ${{formatearBytes(a.tamanio)}}">
                <div class="chk-container">
                  <input type="checkbox" class="chk-archivo chk-lote-${{lote.lote_id}}" data-id="${{a.id_db}}" checked onchange="actualizarSeleccionLote('${{lote.lote_id}}')">
                </div>
                <div class="miniatura-wrap">
                  <img src="/api/miniatura?id=${{a.id_db}}" alt="${{a.nombre}}" onerror="this.onerror=null;this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><rect width=%22100%%22 height=%22100%%22 fill=%22%23222%22/><text x=%2250%%22 y=%2250%%22 fill=%22%23888%22 text-anchor=%22middle%22 dy=%22.3em%22>Media</text></svg>';">
                </div>
                <div class="archivo-meta">
                  <div class="archivo-nombre" title="${{a.nombre}}">${{a.nombre}}</div>
                  <div class="archivo-peso">${{formatearBytes(a.tamanio)}}</div>
                  <div class="archivo-llegada" style="font-size:0.75rem; color:var(--text-muted);" title="Fecha de llegada: ${{a.fecha_llegada || a.fecha || ''}}">🕒 ${{a.fecha_llegada || a.fecha || ''}}</div>
                </div>
              </div>
            `).join('')}}
          </div>
          <div class="form-row">
            <label>Personaje: <select id="sel-pers-${{lote.lote_id}}">${{persOptions}}</select></label>
            <label>Escena:
              <select id="sel-escena-${{lote.lote_id}}" onchange="toggleNuevaEscena('${{lote.lote_id}}', this.value)">
                ${{escenasOptions}}
              </select>
            </label>
            <div class="campo-escena-wrap">
              <input type="text" id="txt-nueva-escena-${{lote.lote_id}}" value="${{esNueva ? escapeHTML(escenaPre) : ''}}" placeholder="Nombre de escena nueva" style="max-width:200px; display:${{esNueva ? 'inline-block' : 'none'}};" oninput="validarInputEscena('${{lote.lote_id}}')">
              <span id="error-escena-${{lote.lote_id}}" class="error-inline" style="display:none;"></span>
            </div>
            <button class="btn-accion" id="btn-mover-${{lote.lote_id}}" onclick="iniciarMover('${{lote.lote_id}}')">Mover seleccionados (${{lote.archivos.length}})</button>
          </div>
        </div>
      `;
    }}

    function generarHtmlCardLoteAnterior(lote) {{
      const persPre = lote.personaje_sugerido || datosEstado.ultimo_personaje || 'lucie';
      const persOptions = datosEstado.personajes.map(p => 
        `<option value="${{p.id}}" ${{p.id === persPre ? 'selected' : ''}}>${{p.nombre}}</option>`
      ).join('');

      const capFocoAnt = (datosEstado.capitulo_foco && datosEstado.capitulo_foco.habilitado) ? datosEstado.capitulo_foco : 
                         ((datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado) ? datosEstado.capitulo_activo : null);
      const capsAbiertosAnt = datosEstado.capitulos_abiertos || [];
      const nombresAbiertosAnt = new Set(capsAbiertosAnt.map(c => c.nombre));

      let optFocoAnt = '';
      if (capFocoAnt) {{
        optFocoAnt = `<option value="${{escapeHTML(capFocoAnt.nombre)}}" data-tipo="capitulo_foco" data-personaje="${{escapeHTML(capFocoAnt.personaje)}}">[Capítulo en foco] ${{escapeHTML(capFocoAnt.nombre)}}</option>`;
      }}

      const optsAbiertosSecundariosAnt = capsAbiertosAnt
        .filter(c => !capFocoAnt || c.id !== capFocoAnt.id)
        .map(c => `<option value="${{escapeHTML(c.nombre)}}" data-tipo="capitulo_abierto" data-personaje="${{escapeHTML(c.personaje)}}">[Capítulo abierto] ${{escapeHTML(c.personaje)}}/${{escapeHTML(c.nombre)}}</option>`)
        .join('');

      const otrasEscenasAnt = (datosEstado.escenas || [])
        .filter(e => !nombresAbiertosAnt.has(e.nombre))
        .map(e => `<option value="${{escapeHTML(e.nombre)}}" data-tipo="${{e.tipo}}">[${{e.tipo === 'descargas_alias' ? 'En Descargas' : 'Destino'}}] ${{escapeHTML(e.nombre)}}</option>`)
        .join('');

      const escenasOptions = optFocoAnt + optsAbiertosSecundariosAnt + otrasEscenasAnt;

      return `
        <div class="card" id="card-${{lote.lote_id}}" style="border:1px solid #333; margin-bottom:12px;">
          <div class="card-header">
            <div style="display:flex; align-items:center; gap:10px;">
              <input type="checkbox" class="cb-lote-anterior" data-lote-id="${{lote.lote_id}}" title="Lote anterior al capítulo" onchange="seleccionarTodosLote('${{lote.lote_id}}', this.checked)">
              <h3>Lote #${{lote.numero}} (${{lote.total_archivos}} archivos &bull; ${{formatearBytes(lote.total_bytes)}})</h3>
            </div>
            <span style="color:var(--text-muted);font-size:0.85rem">${{lote.fecha}}</span>
          </div>
          <div class="lote-toolbar">
            <span id="lbl-sel-${{lote.lote_id}}" style="font-size:0.85rem; color:var(--text-muted);">0 seleccionados</span>
            <div style="display:flex; gap:8px;">
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${{lote.lote_id}}', true)">Seleccionar todos</button>
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${{lote.lote_id}}', false)">Ninguno</button>
            </div>
          </div>
          <div class="archivos-grid">
            ${{lote.archivos.map(a => `
              <div class="archivo-item" title="Archivo: ${{a.nombre}}&#10;Fecha llegada: ${{a.fecha_llegada || a.fecha || ''}}&#10;Fecha modificación: ${{a.fecha || ''}}&#10;Tamaño: ${{formatearBytes(a.tamanio)}}">
                <div class="chk-container">
                  <input type="checkbox" class="chk-archivo chk-lote-${{lote.lote_id}}" data-id="${{a.id_db}}" onchange="actualizarSeleccionLote('${{lote.lote_id}}')">
                </div>
                <div class="miniatura-wrap">
                  <img src="/api/miniatura?id=${{a.id_db}}" alt="${{a.nombre}}" onerror="this.onerror=null;this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><rect width=%22100%%22 height=%22100%%22 fill=%22%23222%22/><text x=%2250%%22 y=%2250%%22 fill=%22%23888%22 text-anchor=%22middle%22 dy=%22.3em%22>Media</text></svg>';">
                </div>
                <div class="archivo-meta">
                  <div class="archivo-nombre" title="${{a.nombre}}">${{a.nombre}}</div>
                  <div class="archivo-peso">${{formatearBytes(a.tamanio)}}</div>
                  <div class="archivo-llegada" style="font-size:0.75rem; color:var(--text-muted);" title="Fecha de llegada: ${{a.fecha_llegada || a.fecha || ''}}">🕒 ${{a.fecha_llegada || a.fecha || ''}}</div>
                </div>
              </div>
            `).join('')}}
          </div>
          <div class="form-row">
            <label>Personaje: <select id="sel-pers-${{lote.lote_id}}">${{persOptions}}</select></label>
            <label>Escena:
              <select id="sel-escena-${{lote.lote_id}}" onchange="toggleNuevaEscena('${{lote.lote_id}}', this.value)">
                <option value="__nueva__" selected>+ Crear nueva escena...</option>
                ${{escenasOptions}}
              </select>
            </label>
            <div class="campo-escena-wrap">
              <input type="text" id="txt-nueva-escena-${{lote.lote_id}}" value="" placeholder="Nombre de escena nueva" style="max-width:200px; display:inline-block;" oninput="validarInputEscena('${{lote.lote_id}}')">
              <span id="error-escena-${{lote.lote_id}}" class="error-inline" style="display:none;"></span>
            </div>
            <button class="btn-accion" id="btn-mover-${{lote.lote_id}}" onclick="iniciarMover('${{lote.lote_id}}')" disabled>Mover seleccionados (0)</button>
          </div>
        </div>
      `;
    }}

    function renderLotes() {{
      const cont = document.getElementById('contenedor-lotes');
      const lotesActivos = (datosEstado.lotes || []).filter(l => !l.es_anterior);
      if (!lotesActivos.length) {{
        cont.innerHTML = '<div class="card"><p style="color:var(--text-muted)">No hay nuevos lotes de candidatos en ~/Descargas.</p></div>';
        return;
      }}
      cont.innerHTML = lotesActivos.map(lote => generarHtmlCardLote(lote)).join('');
    }}

    function renderLotesIncremental() {{
      const cont = document.getElementById('contenedor-lotes');
      const lotesActivos = (datosEstado.lotes || []).filter(l => !l.es_anterior);
      if (!lotesActivos.length) {{
        cont.innerHTML = '<div class="card"><p style="color:var(--text-muted)">No hay nuevos lotes de candidatos en ~/Descargas.</p></div>';
        return;
      }}
      const pVacio = cont.querySelector('p');
      if (pVacio && pVacio.innerText.includes('No hay nuevos lotes')) {{
        cont.innerHTML = '';
      }}

      const idsActivos = new Set(lotesActivos.map(l => l.lote_id));
      const cardsExistentes = cont.querySelectorAll('[id^="card-"]');
      cardsExistentes.forEach(card => {{
        const id = card.id.replace('card-', '');
        if (!idsActivos.has(id)) {{
          card.remove();
        }}
      }});

      lotesActivos.forEach(lote => {{
        const cardExistente = document.getElementById(`card-${{lote.lote_id}}`);
        if (!cardExistente) {{
          const divTemp = document.createElement('div');
          divTemp.innerHTML = generarHtmlCardLote(lote).trim();
          const nuevaCard = divTemp.firstElementChild;
          cont.appendChild(nuevaCard);
        }}
      }});
    }}

    function renderLotesAnteriores() {{
      const sec = document.getElementById('sec-lotes-anteriores');
      const cont = document.getElementById('contenedor-lotes-anteriores');
      const conteo = document.getElementById('conteo-lotes-anteriores');
      if (!sec || !cont) return;

      const capActivo = datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado ? datosEstado.capitulo_activo : null;
      const lotesAnt = datosEstado.lotes_anteriores || [];

      if (!capActivo || !lotesAnt.length) {{
        sec.style.display = 'none';
        cont.innerHTML = '';
        if (conteo) conteo.innerText = '0';
        return;
      }}

      sec.style.display = 'block';
      if (conteo) conteo.innerText = String(lotesAnt.length);
      cont.innerHTML = lotesAnt.map(lote => generarHtmlCardLoteAnterior(lote)).join('');
    }}

    function renderLotesAnterioresIncremental() {{
      const sec = document.getElementById('sec-lotes-anteriores');
      const cont = document.getElementById('contenedor-lotes-anteriores');
      const conteo = document.getElementById('conteo-lotes-anteriores');
      if (!sec || !cont) return;

      const capActivo = datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado ? datosEstado.capitulo_activo : null;
      const lotesAnt = datosEstado.lotes_anteriores || [];

      if (!capActivo || !lotesAnt.length) {{
        sec.style.display = 'none';
        cont.innerHTML = '';
        if (conteo) conteo.innerText = '0';
        return;
      }}

      sec.style.display = 'block';
      if (conteo) conteo.innerText = String(lotesAnt.length);

      const idsAnt = new Set(lotesAnt.map(l => l.lote_id));
      const cardsExistentes = cont.querySelectorAll('[id^="card-"]');
      cardsExistentes.forEach(card => {{
        const id = card.id.replace('card-', '');
        if (!idsAnt.has(id)) {{
          card.remove();
        }}
      }});

      lotesAnt.forEach(lote => {{
        const cardExistente = document.getElementById(`card-${{lote.lote_id}}`);
        if (!cardExistente) {{
          const divTemp = document.createElement('div');
          divTemp.innerHTML = generarHtmlCardLoteAnterior(lote).trim();
          const nuevaCard = divTemp.firstElementChild;
          cont.appendChild(nuevaCard);
        }}
      }});
    }}

    function seleccionarTodosLote(loteId, marcar) {{
      const checkboxes = document.querySelectorAll(`.chk-lote-${{loteId}}`);
      checkboxes.forEach(cb => {{ cb.checked = marcar; }});
      actualizarSeleccionLote(loteId);
    }}

    function actualizarSeleccionLote(loteId) {{
      const checkboxes = document.querySelectorAll(`.chk-lote-${{loteId}}`);
      let marcados = 0;
      checkboxes.forEach(cb => {{ if (cb.checked) marcados++; }});

      const lbl = document.getElementById(`lbl-sel-${{loteId}}`);
      if (lbl) {{
        lbl.innerText = `${{marcados}} seleccionados`;
      }}

      const btn = document.getElementById(`btn-mover-${{loteId}}`);
      if (btn) {{
        btn.innerText = `Mover seleccionados (${{marcados}})`;
        btn.disabled = (marcados === 0);
      }}
    }}

    function validarNombreEscena(nombre) {{
      if (!nombre || !nombre.trim()) {{
        return "El nombre de la escena no puede estar vacío.";
      }}
      const trim = nombre.trim();
      if (trim.length > 100) {{
        return "El nombre no puede exceder 100 caracteres.";
      }}
      if (trim.endsWith('.') || trim.endsWith(' ')) {{
        return "El nombre no puede terminar en punto ni en espacio.";
      }}
      if (trim.includes('..') || trim.includes('/') || trim.includes('\\\\')) {{
        return "El nombre no puede contener '/', '\\\\' ni '..'.";
      }}
      if (/[<>:"|?*\\x00-\\x1F]/.test(trim)) {{
        return "Contiene caracteres inválidos (< > : \\\" | ? * o de control).";
      }}
      const reservados = ["CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"];
      const baseNombre = trim.split('.')[0].toUpperCase();
      if (reservados.includes(trim.toUpperCase()) || reservados.includes(baseNombre)) {{
        return `\\"${{trim}}\\" es un nombre reservado del sistema.`;
      }}
      return null;
    }}

    function validarInputEscena(loteId) {{
      const input = document.getElementById(`txt-nueva-escena-${{loteId}}`);
      const errSpan = document.getElementById(`error-escena-${{loteId}}`);
      if (!input || !errSpan) return true;

      const selEscena = document.getElementById(`sel-escena-${{loteId}}`).value;
      if (selEscena !== '__nueva__') {{
        errSpan.style.display = 'none';
        errSpan.innerText = '';
        return true;
      }}

      const error = validarNombreEscena(input.value);
      if (error) {{
        errSpan.innerText = error;
        errSpan.style.display = 'block';
        return false;
      }} else {{
        errSpan.style.display = 'none';
        errSpan.innerText = '';
        return true;
      }}
    }}

    function toggleNuevaEscena(loteId, valor) {{
      const txt = document.getElementById(`txt-nueva-escena-${{loteId}}`);
      const errSpan = document.getElementById(`error-escena-${{loteId}}`);
      const selEscena = document.getElementById(`sel-escena-${{loteId}}`);
      const selPers = document.getElementById(`sel-pers-${{loteId}}`);

      if (selEscena && selPers && selEscena.selectedIndex >= 0) {{
        const opt = selEscena.options[selEscena.selectedIndex];
        const persOpt = opt ? opt.getAttribute('data-personaje') : null;
        if (persOpt) {{
          selPers.value = persOpt;
        }}
      }}

      if (valor === '__nueva__') {{
        txt.style.display = 'inline-block';
        validarInputEscena(loteId);
      }} else {{
        txt.style.display = 'none';
        if (errSpan) {{
          errSpan.style.display = 'none';
          errSpan.innerText = '';
        }}
      }}
    }}

    function renderSinIdentificar() {{
      const cont = document.getElementById('contenedor-sin-identificar');
      if (!datosEstado.sin_identificar.length) {{
        cont.innerHTML = '<p style="color:var(--text-muted)">No hay archivos multimedia sin clasificar.</p>';
        return;
      }}
      cont.innerHTML = `
        <table>
          <thead>
            <tr><th>Archivo</th><th>Tamaño</th><th>Acción</th></tr>
          </thead>
          <tbody>
            ${{datosEstado.sin_identificar.map(a => `
              <tr>
                <td>${{a.nombre}}</td>
                <td>${{formatearBytes(a.tamanio)}}</td>
                <td>
                  <button class="btn-accion" style="padding:4px 8px;font-size:0.75rem;" onclick="clasificarSinId('${{a.hash}}', '${{a.ruta.replace(/'/g, "\\\\\\'")}}', true)">Del Proyecto</button>
                  <button class="btn-cancelar" style="padding:4px 8px;font-size:0.75rem;" onclick="clasificarSinId('${{a.hash}}', '${{a.ruta.replace(/'/g, "\\\\\\'")}}', false)">Ignorar</button>
                </td>
              </tr>
            `).join('')}}
          </tbody>
        </table>
      `;
    }}

    async function clasificarSinId(hash, ruta, esProyecto) {{
      try {{
        await apiFetch('/api/clasificar-sin-identificar', {{
          method: 'POST',
          body: JSON.stringify({{ hash, ruta, es_proyecto: esProyecto }})
        }});
        await cargarDatos();
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function cargarHistorial() {{
      const cont = document.getElementById('contenedor-historial');
      cont.innerHTML = '<p style="color:var(--text-muted)">Cargando historial...</p>';
      try {{
        const res = await apiFetch('/api/historial');
        historialActual = res.historial || [];
        renderHistorial();
      }} catch (e) {{
        cont.innerHTML = '<p style="color:var(--danger)">Error al cargar historial.</p>';
        mostrarError(e.message);
      }}
    }}

    function renderHistorial() {{
      const cont = document.getElementById('contenedor-historial');
      const btnUltimo = document.getElementById('btn-deshacer-ultimo-lote');

      if (!historialActual.length) {{
        cont.innerHTML = '<p style="color:var(--text-muted)">No hay movimientos registrados en la bitácora aún.</p>';
        if (btnUltimo) btnUltimo.disabled = true;
        return;
      }}

      const primerReversible = historialActual.find(m => m.estado === 'movido' || m.estado === 'descartado');
      if (btnUltimo) {{
        btnUltimo.disabled = !primerReversible;
      }}

      cont.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Archivo</th>
              <th>Origen</th>
              <th>Destino</th>
              <th>Estado</th>
              <th>Acción</th>
            </tr>
          </thead>
          <tbody>
            ${{historialActual.map(m => `
              <tr>
                <td><small>${{m.fecha}}</small></td>
                <td><strong>${{m.archivo}}</strong></td>
                <td><small title="${{m.origen}}">${{m.origen}}</small></td>
                <td><small style="color:var(--teal)" title="${{m.destino}}">${{m.destino}}</small></td>
                <td>
                  <span class="${{m.estado === 'deshecho' ? 'badge-deshecho' : (m.estado === 'descartado' ? 'badge-descartado' : 'badge-movido')}}">
                    ${{m.estado}}
                  </span>
                </td>
                <td>
                  ${{(m.estado === 'movido' || m.estado === 'descartado') ? `
                    <button class="btn-sm" onclick="deshacerMovimiento('${{m.id_operacion}}')">
                      Deshacer
                    </button>
                  ` : `
                    <span style="color:var(--text-muted)">-</span>
                  `}}
                </td>
              </tr>
            `).join('')}}
          </tbody>
        </table>
      `;
    }}

    async function deshacerMovimiento(idOperacion) {{
      if (!idOperacion) return;
      if (!confirm("¿Confirmás deshacer esta operación? Los archivos serán restaurados a su ubicación original.")) {{
        return;
      }}
      try {{
        const res = await apiFetch('/api/deshacer', {{
          method: 'POST',
          body: JSON.stringify({{ id_operacion: idOperacion }})
        }});
        if (operacionAvisoActual === idOperacion) {{
          cerrarAviso();
        }}
        await cargarHistorial();
        await cargarDatos();
        if (pestanaActual === 'descartados') {{
          await cargarCapitulosDescartados();
        }} else if (pestanaActual === 'capitulos-cerrados') {{
          await cargarCapitulosCerrados();
        }}
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function deshacerUltimoLote() {{
      const primerReversible = historialActual.find(m => m.estado === 'movido' || m.estado === 'descartado');
      if (!primerReversible) {{
        mostrarError("No hay operaciones pendientes de deshacer en el historial.");
        return;
      }}
      await deshacerMovimiento(primerReversible.id_operacion);
    }}

    async function iniciarMover(loteId) {{
      const lote = datosEstado.lotes.find(l => l.lote_id === loteId) ||
                   (datosEstado.lotes_anteriores && datosEstado.lotes_anteriores.find(l => l.lote_id === loteId));
      if (!lote) return;

      const checkboxes = document.querySelectorAll(`.chk-lote-${{loteId}}:checked`);
      const idsSeleccionados = new Set(Array.from(checkboxes).map(cb => cb.getAttribute('data-id')));
      const archivosSeleccionados = lote.archivos.filter(a => idsSeleccionados.has(String(a.id_db)));

      if (!archivosSeleccionados.length) {{
        mostrarError("Debés seleccionar al menos un archivo para mover.");
        return;
      }}

      const selPers = document.getElementById(`sel-pers-${{loteId}}`).value;
      const selEscena = document.getElementById(`sel-escena-${{loteId}}`).value;
      let nombreEscena = selEscena;
      let esExistenteDescargas = false;

      if (selEscena === '__nueva__') {{
        if (!validarInputEscena(loteId)) {{
          const txt = document.getElementById(`txt-nueva-escena-${{loteId}}`);
          if (txt) txt.focus();
          return;
        }}
        nombreEscena = document.getElementById(`txt-nueva-escena-${{loteId}}`).value.trim();
      }} else {{
        const opt = document.querySelector(`#sel-escena-${{loteId}} option[value="${{selEscena}}"]`);
        if (opt && opt.getAttribute('data-tipo') === 'descargas_alias') {{
          esExistenteDescargas = true;
        }}
      }}

      try {{
        const sim = await apiFetch('/api/simular-mover', {{
          method: 'POST',
          body: JSON.stringify({{
            archivos: archivosSeleccionados,
            personaje: selPers,
            escena: nombreEscena,
            es_existente_descargas: esExistenteDescargas
          }})
        }});

        simulacionActiva = sim;
        loteActivoId = loteId;
        mostrarModalSimulacion(sim);
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function simularMoverLotesListos() {{
      const cbs = document.querySelectorAll('#contenedor-lotes .cb-lote-listo:checked');
      if (!cbs.length) {{
        mostrarError("No hay ningún lote seleccionado para mover.");
        return;
      }}

      const lotesPayload = [];
      for (const cb of cbs) {{
        const loteId = cb.getAttribute('data-lote-id');
        const lote = datosEstado.lotes.find(l => l.lote_id === loteId);
        if (!lote || lote.es_anterior) continue;

        const chkArchivos = document.querySelectorAll(`.chk-lote-${{loteId}}:checked`);
        const idsSel = new Set(Array.from(chkArchivos).map(c => c.getAttribute('data-id')));
        const archivosSel = lote.archivos.filter(a => idsSel.has(String(a.id_db)));
        if (!archivosSel.length) {{
          continue;
        }}

        const selPers = document.getElementById(`sel-pers-${{loteId}}`).value;
        const selEscena = document.getElementById(`sel-escena-${{loteId}}`).value;
        let nombreEscena = selEscena;
        let esExistenteDescargas = false;

        if (selEscena === '__nueva__') {{
          if (!validarInputEscena(loteId)) {{
            const txt = document.getElementById(`txt-nueva-escena-${{loteId}}`);
            if (txt) txt.focus();
            return;
          }}
          nombreEscena = document.getElementById(`txt-nueva-escena-${{loteId}}`).value.trim();
        }} else {{
          const opt = document.querySelector(`#sel-escena-${{loteId}} option[value="${{selEscena}}"]`);
          if (opt && opt.getAttribute('data-tipo') === 'descargas_alias') {{
            esExistenteDescargas = true;
          }}
        }}

        lotesPayload.push({{
          lote_id: loteId,
          archivos: archivosSel,
          personaje: selPers,
          escena: nombreEscena,
          es_existente_descargas: esExistenteDescargas
        }});
      }}

      if (!lotesPayload.length) {{
        mostrarError("No hay archivos seleccionados en los lotes tildados.");
        return;
      }}

      try {{
        const sim = await apiFetch('/api/simular-mover', {{
          method: 'POST',
          body: JSON.stringify({{ lotes: lotesPayload }})
        }});
        simulacionActiva = sim;
        loteActivoId = null;
        mostrarModalSimulacion(sim);
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    function formatearDestinoCliente(m) {{
      const rel = (m.destino_relativo || m.destino || '').replace(/\\\\/g, '/');
      return escapeHTML(rel);
    }}

    function mostrarModalSimulacion(sim) {{
      const cont = document.getElementById('simulacion-contenido');
      if (sim.html) {{
        cont.innerHTML = sim.html;
      }} else {{
        const alertaOtro = sim.hay_otro_tipo ? `
          <div style="margin:8px 0 14px 0; padding:10px 14px; background:rgba(234, 179, 8, 0.15); border:1px solid #eab308; border-radius:6px; color:#fde047; font-size:0.9rem;">
            <strong>⚠️ Archivo no multimedia detectado:</strong> Contiene archivos con extensión distinta a fotos o videos. Se moverán a la raíz de la escena conservando su nombre original sin sobreescritura.
          </div>
        ` : '';
        cont.innerHTML = `
          ${{alertaOtro}}
          <p><strong>Personaje:</strong> ${{escapeHTML(sim.personaje || '')}} | <strong>Escena:</strong> ${{escapeHTML(sim.escena || '')}} ${{sim.es_existente_descargas ? '(En Descargas)' : ''}}</p>
          <table class="modal-tabla">
            <thead>
              <tr>
                <th style="width:35%;">Archivo (Renombrado)</th>
                <th style="width:30%;">Origen</th>
                <th style="width:35%;">Destino</th>
              </tr>
            </thead>
            <tbody>
              ${{sim.movimientos.map(m => `
                <tr>
                  <td><strong>${{escapeHTML(m.nombre_original || m.origen.split('/').pop())}}</strong> &rarr; <span class="badge-renombrado" style="color:${{m.es_otro_tipo ? 'var(--text-warning, #f59e0b)' : 'var(--accent-primary, #60a5fa)'}}; font-weight:600;">${{escapeHTML(m.nombre_nuevo || m.destino.split('/').pop())}}${{m.es_otro_tipo ? ' (sin renombrar)' : ''}}</span></td>
                  <td class="ruta-celda" title="${{escapeHTML(m.origen)}}"><small style="color:var(--text-muted)">${{escapeHTML(m.origen)}}</small></td>
                  <td class="ruta-celda destino-celda" title="${{escapeHTML(m.destino)}}" data-destino="${{escapeHTML(m.destino)}}">${{formatearDestinoCliente(m)}}</td>
                </tr>
              `).join('')}}
            </tbody>
          </table>
        `;
      }}
      document.getElementById('modal-simulacion').style.display = 'flex';
      document.getElementById('btn-ejecutar-mover').onclick = ejecutarMoverLote;
    }}

    function cerrarModal() {{
      document.getElementById('modal-simulacion').style.display = 'none';
      simulacionActiva = null;
      loteActivoId = null;
      terminarCapituloTrasMover = false;
      programarSiguienteSondeo(500);
    }}

    async function ejecutarMoverLote() {{
      if (!simulacionActiva) return;
      try {{
        let bodyReq;
        if (simulacionActiva.es_multilote) {{
          bodyReq = {{ simulacion: simulacionActiva }};
        }} else {{
          if (!loteActivoId) return;
          bodyReq = {{ simulacion: simulacionActiva, lote_id: loteActivoId }};
        }}

        const res = await apiFetch('/api/mover-lote', {{
          method: 'POST',
          body: JSON.stringify(bodyReq)
        }});
        cerrarModal();

        if (terminarCapituloTrasMover) {{
          terminarCapituloTrasMover = false;
          try {{
            await apiFetch('/api/capitulos/terminar', {{
              method: 'POST',
              body: JSON.stringify({{ accion: 'mover_pendientes' }})
            }});
          }} catch (errTerminar) {{
            console.error('Error al terminar capítulo tras mover:', errTerminar);
          }}
        }}

        if (res.es_multilote) {{
          const primerRes = (res.resultados && res.resultados.length > 0) ? res.resultados[0] : null;
          mostrarAvisoMover(
            res.total_movidos,
            primerRes ? primerRes.personaje : 'varios',
            primerRes ? (res.resultados.length > 1 ? `${{primerRes.escena}} y otros` : primerRes.escena) : 'lotes',
            res.id_operacion || res.ultimo_id_operacion
          );
        }} else {{
          mostrarAvisoMover(
            res.total_movidos,
            res.personaje || simulacionActiva.personaje,
            res.escena || simulacionActiva.escena,
            res.id_operacion
          );
        }}

        await cargarDatos();
        if (pestanaActual === 'historial') {{
          await cargarHistorial();
        }}
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    function formatearBytes(b) {{
      if (b < 1024) return b + ' B';
      if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
      return (b / 1048576).toFixed(1) + ' MB';
    }}

    function iniciarEnvioCapituloActivo() {{
      const cap = datosEstado.capitulo_foco || datosEstado.capitulo_activo;
      if (!cap || !cap.nombre) {{
        mostrarError("No hay un capítulo activo en foco para enviar.");
        return;
      }}
      abrirModalPlanEnvio(`${{cap.personaje}}/${{cap.nombre}}`);
    }}

    let planEnvioActivo = null;

    async function abrirModalPlanEnvio(capitulo = null) {{
      try {{
        const modal = document.getElementById('modal-plan-envio');
        const cont = document.getElementById('contenido-plan-envio');
        const btnConfirm = document.getElementById('btn-confirmar-envio-pendrive');

        btnConfirm.disabled = true;
        btnConfirm.style.cursor = 'not-allowed';
        btnConfirm.style.opacity = '0.5';

        cont.innerHTML = '<p style="color:var(--text-muted); padding:20px 0;">Calculando simulación de envío y verificando pendrive...</p>';
        modal.style.display = 'flex';

        const body = capitulo ? {{ capitulos: [capitulo] }} : {{}};
        const sim = await apiFetch('/api/pendrive/envio-simular', {{
          method: 'POST',
          body: JSON.stringify(body)
        }});

        planEnvioActivo = sim;

        let alertasHtml = '';
        if (sim.capitulo_abierto) {{
          alertasHtml += `
            <div style="background:rgba(245, 158, 11, 0.15); border:1px solid #f59e0b; color:#fef3c7; padding:10px 14px; border-radius:6px; margin-bottom:12px; font-weight:500;">
              ⚠️ <strong>Atención:</strong> Uno o más capítulos seleccionados siguen abiertos en el panel; podrían recibirse más archivos luego.
            </div>
          `;
        }}

        if (sim.advertencias && sim.advertencias.length > 0) {{
          alertasHtml += `
            <div style="background:rgba(207, 102, 121, 0.15); border:1px solid var(--danger); color:var(--danger); padding:10px 14px; border-radius:6px; margin-bottom:12px; font-size:0.9rem;">
              <strong>Advertencias del sistema:</strong>
              <ul style="margin:6px 0 0 18px;">
                ${{sim.advertencias.map(a => `<li>${{escapeHTML(a)}}</li>`).join('')}}
              </ul>
            </div>
          `;
        }}

        if (sim.archivos_omitidos && sim.archivos_omitidos.length > 0) {{
          alertasHtml += `
            <div style="background:rgba(14, 165, 233, 0.15); border:1px solid #0ea5e9; color:#bae6fd; padding:10px 14px; border-radius:6px; margin-bottom:12px; font-size:0.9rem;">
              <strong>ℹ️ Archivos omitidos (ya enviados anteriormente o no multimedia):</strong>
              <ul style="margin:6px 0 0 18px;">
                ${{sim.archivos_omitidos.map(o => `<li><code>${{escapeHTML(o.nombre)}}</code>: ${{escapeHTML(o.motivo)}}</li>`).join('')}}
              </ul>
            </div>
          `;
        }}

        const infoPendrive = `
          <div style="display:flex; flex-wrap:wrap; gap:16px; background:var(--card-alt); padding:12px 16px; border-radius:6px; margin-bottom:14px; font-size:0.85rem;">
            <div><strong>Pendrive ID:</strong> <code>${{escapeHTML((sim.pendrive_id || '').slice(0, 8))}}...</code></div>
            <div><strong>Punto montaje:</strong> <code>${{escapeHTML(sim.punto_montaje || '')}}</code></div>
            <div><strong>Filesystem:</strong> <code>${{escapeHTML(sim.sistema_archivos || '')}}</code></div>
            <div><strong>Espacio libre:</strong> ${{escapeHTML(sim.espacio_libre_fmt || '0 B')}} (Margen: ${{escapeHTML(sim.margen_libre_fmt || '1 GiB')}})</div>
            <div><strong>Total a enviar:</strong> <strong>${{sim.total_archivos_a_enviar}} archivo(s)</strong> (${{escapeHTML(sim.bytes_a_enviar_fmt || '0 B')}})</div>
          </div>
        `;

        let tablaArchivos = '';
        if (sim.archivos && sim.archivos.length > 0) {{
          tablaArchivos = `
            <table class="modal-tabla">
              <thead>
                <tr>
                  <th style="width:25%;">Archivo</th>
                  <th style="width:12%;">Tipo</th>
                  <th style="width:13%;">Tamaño</th>
                  <th style="width:35%;">Destino relativo en pendrive</th>
                  <th style="width:15%;">Estado</th>
                </tr>
              </thead>
              <tbody>
                ${{sim.archivos.map(a => {{
                  const tagTipo = a.tipo === 'video' ? '<span class="tag-tipo tag-video">VIDEO</span>' : '<span class="tag-tipo tag-imagen">IMAGEN</span>';
                  const badgeEstado = a.conflicto
                    ? '<span style="color:var(--danger); font-weight:bold;">⚠️ Conflicto (hash distinto)</span>'
                    : '<span style="color:var(--teal); font-weight:600;">Listo para enviar</span>';
                  return `
                    <tr style="${{a.conflicto ? 'background:rgba(207, 102, 121, 0.1);' : ''}}">
                      <td><strong>${{escapeHTML(a.nombre)}}</strong></td>
                      <td>${{tagTipo}}</td>
                      <td>${{escapeHTML(a.tamanio_fmt || formatearBytes(a.tamanio_bytes))}}</td>
                      <td class="ruta-celda"><code style="color:var(--teal)">${{escapeHTML(a.destino_relativo)}}</code></td>
                      <td>${{badgeEstado}}</td>
                    </tr>
                  `;
                }}).join('')}}
              </tbody>
            </table>
          `;
        }} else {{
          tablaArchivos = '<p style="color:var(--text-muted); padding:16px 0;">No hay archivos pendientes de transferir en los capítulos seleccionados.</p>';
        }}

        cont.innerHTML = alertasHtml + infoPendrive + tablaArchivos;

        if (sim.puede_enviar && sim.total_archivos_a_enviar > 0) {{
          btnConfirm.disabled = false;
          btnConfirm.style.cursor = 'pointer';
          btnConfirm.style.opacity = '1';
        }} else {{
          btnConfirm.disabled = true;
          btnConfirm.style.cursor = 'not-allowed';
          btnConfirm.style.opacity = '0.5';
        }}
      }} catch (e) {{
        mostrarError(e.message);
        cerrarModalPlanEnvio();
      }}
    }}

    function cerrarModalPlanEnvio() {{
      const modal = document.getElementById('modal-plan-envio');
      if (modal) modal.style.display = 'none';
      planEnvioActivo = null;
      programarSiguienteSondeo(500);
    }}

    async function confirmarEnvioPendrive() {{
      if (!planEnvioActivo || !planEnvioActivo.puede_enviar) return;
      const btn = document.getElementById('btn-confirmar-envio-pendrive');
      if (btn) {{
        btn.disabled = true;
        btn.innerText = 'Enviando...';
      }}
      try {{
        const res = await apiFetch('/api/pendrive/envio', {{
          method: 'POST',
          body: JSON.stringify({{ simulacion: planEnvioActivo }})
        }});
        cerrarModalPlanEnvio();
        mostrarToastLlegada(`Envío exitoso: ${{res.total_archivos_enviados}} archivo(s) transferidos al pendrive`);
        await cargarDatos();
        if (pestanaActual === 'pendrive') {{
          await cargarVistaPendrive();
        }} else if (pestanaActual === 'historial') {{
          await cargarHistorial();
        }}
      }} catch (e) {{
        mostrarError(`Error al enviar material al pendrive: ${{e.message}}`);
        if (btn) {{
          btn.disabled = false;
          btn.innerText = 'Confirmar y enviar';
        }}
      }}
    }}

    async function cargarVistaPendrive() {{
      const contEstado = document.getElementById('contenedor-estado-pendrive');
      const contCaps = document.getElementById('contenedor-capitulos-pendrive');
      const cardPart = document.getElementById('card-part-pendrive');
      const contPart = document.getElementById('contenedor-part-pendrive');
      const contHist = document.getElementById('contenedor-historial-pendrive');
      const btnVincular = document.getElementById('btn-vincular-pendrive');
      const btnEnviarTodos = document.getElementById('btn-enviar-todos-pendrive');

      if (!contEstado) return;

      try {{
        const [estadoPen, histRes] = await Promise.all([
          apiFetch('/api/pendrive/estado'),
          apiFetch('/api/historial').catch(() => ({{ historial: [] }}))
        ]);

        // 1. Tarjeta Estado Físico
        if (estadoPen.sin_respuesta) {{
          contEstado.innerHTML = `
            <div style="background:rgba(245, 158, 11, 0.15); border:1px solid #f59e0b; padding:16px; border-radius:6px; color:#fef3c7;">
              <h3 style="display:flex; align-items:center; gap:8px;">⚠️ Pendrive sin respuesta</h3>
              <p style="margin-top:6px; font-size:0.9rem;">El dispositivo montado no responde a las solicitudes de lectura dentro del tiempo límite de 3 segundos.</p>
            </div>
          `;
          if (btnVincular) btnVincular.style.display = 'none';
          if (btnEnviarTodos) btnEnviarTodos.disabled = true;
        }} else if (!estadoPen.conectado) {{
          const cand = estadoPen.unidad_candidata;
          if (cand) {{
            contEstado.innerHTML = `
              <div style="background:rgba(99, 102, 241, 0.1); border:1px solid #6366f1; padding:16px; border-radius:6px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <div>
                    <h3 style="color:#e0e7ff;">Unidad candidata detectada (sin vincular)</h3>
                    <p style="color:var(--text-muted); font-size:0.85rem; margin-top:4px;">
                      Punto de montaje: <code>${{escapeHTML(cand.punto_montaje)}}</code> &bull; Filesystem: <code>${{escapeHTML(cand.sistema_archivos || 'desconocido')}}</code> &bull; Libre: ${{escapeHTML(cand.espacio_libre_fmt)}}
                    </p>
                  </div>
                  <button class="btn-sm" onclick="abrirModalVincularPendrive('${{escapeHTML(cand.punto_montaje)}}')" style="background:var(--accent); color:#000; font-weight:700; padding:8px 18px; border:none; border-radius:4px; cursor:pointer;">
                    Vincular pendrive
                  </button>
                </div>
              </div>
            `;
            if (btnVincular) btnVincular.style.display = 'none';
          }} else {{
            contEstado.innerHTML = `
              <div style="background:var(--card-alt); padding:16px; border-radius:6px; color:var(--text-muted);">
                <p>🔌 Ningún pendrive vinculado detectado en el sistema.</p>
                <small>Conectá tu pendrive para transferir el material o vincularlo por primera vez.</small>
              </div>
            `;
            if (btnVincular) btnVincular.style.display = 'inline-block';
          }}
          if (btnEnviarTodos) btnEnviarTodos.disabled = true;
        }} else {{
          // Pendrive Conectado y Vinculado
          if (btnVincular) btnVincular.style.display = 'none';
          if (btnEnviarTodos) btnEnviarTodos.disabled = (estadoPen.archivos_pendientes_conteo === 0);

          contEstado.innerHTML = `
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px;">
              <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Estado</div>
                <div style="font-size:1.1rem; font-weight:700; color:var(--teal); margin-top:4px;">● Conectado y Vinculado</div>
              </div>
              <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">ID Marcador</div>
                <div style="font-size:0.95rem; font-family:monospace; margin-top:4px;" title="${{escapeHTML(estadoPen.id)}}">${{escapeHTML((estadoPen.id || '').slice(0, 13))}}...</div>
              </div>
              <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Punto de Montaje</div>
                <div style="font-size:0.85rem; font-family:monospace; margin-top:4px; word-break:break-all;" title="${{escapeHTML(estadoPen.punto_montaje)}}">${{escapeHTML(estadoPen.punto_montaje)}}</div>
              </div>
              <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Sistema de Archivos</div>
                <div style="font-size:1rem; font-weight:600; margin-top:4px;">${{escapeHTML(estadoPen.sistema_archivos || 'N/D')}}</div>
              </div>
              <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Espacio Disponible</div>
                <div style="font-size:1rem; font-weight:600; color:#38bdf8; margin-top:4px;">
                  ${{escapeHTML(estadoPen.espacio_libre_fmt)}} <span style="font-size:0.8rem; color:var(--text-muted); font-weight:normal;">/ ${{escapeHTML(estadoPen.espacio_total_fmt)}}</span>
                </div>
              </div>
            </div>
          `;
        }}

        // 2. Capítulos Pendientes
        const capsPendientes = estadoPen.capitulos_pendientes || [];
        if (!capsPendientes.length) {{
          contCaps.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay archivos en la sala de espera listos para transferir.</p>';
        }} else {{
          contCaps.innerHTML = `
            <table class="tabla-historial">
              <thead>
                <tr>
                  <th style="width:15%;">Personaje</th>
                  <th style="width:25%;">Capítulo</th>
                  <th style="width:12%; text-align:center;">Videos</th>
                  <th style="width:12%; text-align:center;">Fotos</th>
                  <th style="width:16%;">Tamaño</th>
                  <th style="width:20%; text-align:center;">Acción</th>
                </tr>
              </thead>
              <tbody>
                ${{capsPendientes.map(c => `
                  <tr>
                    <td><code>${{escapeHTML(c.personaje)}}</code></td>
                    <td><strong>${{escapeHTML(c.capitulo)}}</strong></td>
                    <td style="text-align:center;"><span class="tag-tipo tag-video">${{c.videos}}</span></td>
                    <td style="text-align:center;"><span class="tag-tipo tag-imagen">${{c.fotos}}</span></td>
                    <td>${{escapeHTML(c.bytes_totales_fmt)}}</td>
                    <td style="text-align:center;">
                      <button class="btn-sm" onclick="abrirModalPlanEnvio('${{escapeHTML(c.personaje)}}/${{escapeHTML(c.capitulo)}}')" style="background:#10b981; color:#000; font-weight:600; padding:6px 14px; border:none; border-radius:4px; cursor:pointer;" title="Enviar este capítulo">
                        Enviar al pendrive
                      </button>
                    </td>
                  </tr>
                `).join('')}}
              </tbody>
            </table>
          `;
        }}

        // 3. Archivos .part huérfanos
        const parts = estadoPen.archivos_part_huerfanos || [];
        if (parts.length > 0) {{
          cardPart.style.display = 'block';
          contPart.innerHTML = `
            <table class="tabla-historial">
              <thead>
                <tr>
                  <th>Archivo .part</th>
                  <th>Ubicación relativa</th>
                  <th>Tamaño</th>
                  <th>Modificado</th>
                </tr>
              </thead>
              <tbody>
                ${{parts.map(p => `
                  <tr>
                    <td><strong style="color:var(--danger)">${{escapeHTML(p.nombre)}}</strong></td>
                    <td class="ruta-celda"><code>${{escapeHTML(p.ruta_relativa)}}</code></td>
                    <td>${{escapeHTML(p.tamanio_fmt)}}</td>
                    <td><small style="color:var(--text-muted)">${{escapeHTML((p.fecha_modificacion || '').replace('T', ' ').slice(0, 19))}}</small></td>
                  </tr>
                `).join('')}}
              </tbody>
            </table>
          `;
        }} else {{
          cardPart.style.display = 'none';
          contPart.innerHTML = '';
        }}

        // 4. Historial de envíos
        const hist = histRes.historial || [];
        const enviosPendrive = hist.filter(h => h.evento === 'envio_pendrive');
        if (!enviosPendrive.length) {{
          contHist.innerHTML = '<p style="color:var(--text-muted); padding:16px;">Aún no se registraron transferencias al pendrive en la bitácora.</p>';
        }} else {{
          contHist.innerHTML = `
            <table class="tabla-historial">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Capítulo</th>
                  <th>Archivos</th>
                  <th>Bytes</th>
                  <th>Estado</th>
                  <th style="text-align:center;">Acción</th>
                </tr>
              </thead>
              <tbody>
                ${{enviosPendrive.map(e => `
                  <tr>
                    <td><small>${{escapeHTML(e.fecha)}}</small></td>
                    <td><strong>${{escapeHTML(e.personaje || '')}}/${{escapeHTML(e.capitulo || '')}}</strong></td>
                    <td>${{e.total_archivos || (e.archivos ? e.archivos.length : 1)}} archivo(s)</td>
                    <td>${{formatearBytes(e.total_bytes || 0)}}</td>
                    <td><span class="${{e.estado === 'deshecho' ? 'badge-deshecho' : 'badge-movido'}}">${{escapeHTML(e.estado)}}</span></td>
                    <td style="text-align:center;">
                      ${{e.estado !== 'deshecho' ? `
                        <button class="btn-sm" onclick="deshacerEnvio('${{escapeHTML(e.id_operacion)}}')" style="background:var(--card-alt); border:1px solid var(--border); color:var(--text); padding:4px 10px; border-radius:4px; cursor:pointer;">
                          Deshacer envío
                        </button>
                      ` : '<span style="color:var(--text-muted)">Revertido</span>'}}
                    </td>
                  </tr>
                `).join('')}}
              </tbody>
            </table>
          `;
        }}
      }} catch (e) {{
        contEstado.innerHTML = `<p style="color:var(--danger)">Error al cargar vista de pendrive: ${{escapeHTML(e.message)}}</p>`;
      }}
    }}

    async function deshacerEnvio(idOperacion) {{
      if (!confirm("¿Confirmás deshacer este envío al pendrive? La copia en el pendrive se moverá a _revertidos/ y los archivos originales regresarán a la sala de espera si sus ubicaciones siguen libres.")) {{
        return;
      }}
      try {{
        await apiFetch('/api/deshacer', {{
          method: 'POST',
          body: JSON.stringify({{ id_operacion: idOperacion }})
        }});
        mostrarToastLlegada("Envío revertido con éxito.");
        await cargarVistaPendrive();
        await cargarDatos();
      }} catch (e) {{
        mostrarError(`Error al deshacer envío: ${{e.message}}`);
      }}
    }}

    let puntoMontajeVincular = null;

    async function abrirModalVincularPendrive(punto = null) {{
      try {{
        puntoMontajeVincular = punto;
        const modal = document.getElementById('modal-vincular-pendrive');
        const cont = document.getElementById('contenido-vincular-pendrive');
        cont.innerHTML = '<p style="color:var(--text-muted)">Inspeccionando unidad...</p>';
        modal.style.display = 'flex';

        const body = punto ? {{ punto_montaje: punto }} : {{}};
        const sim = await apiFetch('/api/pendrive/vincular-simular', {{
          method: 'POST',
          body: JSON.stringify(body)
        }});

        puntoMontajeVincular = sim.punto_montaje;
        cont.innerHTML = `
          <div style="background:var(--card-alt); padding:16px; border-radius:6px; margin-bottom:12px;">
            <p><strong>Punto de montaje:</strong> <code>${{escapeHTML(sim.punto_montaje)}}</code></p>
            <p style="margin-top:6px;"><strong>Sistema de archivos:</strong> <code>${{escapeHTML(sim.sistema_archivos || 'desconocido')}}</code></p>
            <p style="margin-top:6px;"><strong>Espacio libre:</strong> ${{escapeHTML(sim.espacio_libre_fmt)}} de ${{escapeHTML(sim.espacio_total_fmt)}}</p>
          </div>
          <p style="font-size:0.9rem; color:var(--text-muted);">
            Al vincular, se creará el marcador de identidad <code>.lucie_pendrive.json</code> en la raíz y la estructura base <code>LucieSinReglas/</code> con sus subcarpetas.
            <strong>Nada de lo que ya exista en el pendrive será modificado ni tocado.</strong>
          </p>
        `;
      }} catch (e) {{
        mostrarError(e.message);
        cerrarModalVincularPendrive();
      }}
    }}

    function cerrarModalVincularPendrive() {{
      const modal = document.getElementById('modal-vincular-pendrive');
      if (modal) modal.style.display = 'none';
      puntoMontajeVincular = null;
      programarSiguienteSondeo(500);
    }}

    async function confirmarVincularPendrive() {{
      try {{
        const body = puntoMontajeVincular ? {{ punto_montaje: puntoMontajeVincular }} : {{}};
        await apiFetch('/api/pendrive/vincular', {{
          method: 'POST',
          body: JSON.stringify(body)
        }});
        cerrarModalVincularPendrive();
        mostrarToastLlegada("Pendrive vinculado exitosamente.");
        await cargarVistaPendrive();
      }} catch (e) {{
        mostrarError(`Error al vincular pendrive: ${{e.message}}`);
      }}
    }}

    cargarDatos().then(() => {{
      programarSiguienteSondeo();
    }});
  </script>
  <div id="toast-llegada" class="toast-llegada"></div>
</body>
</html>
"""
        cuerpo = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
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


def main():
    parser = argparse.ArgumentParser(description="Bandeja de Descargas - Proyecto Lucie")
    parser.add_argument("--config", "-c", default="config_bandeja.json", help="Ruta al archivo config_bandeja.json")
    parser.add_argument("--puerto", "-p", type=int, default=None, help="Puerto HTTP del panel (por defecto 8766)")
    parser.add_argument("--descargas", "-d", default=None, help="Ruta alternativa de ~/Descargas")
    parser.add_argument("--destino", default=None, help="Ruta base destino (por defecto ~/Descargas/_lucie)")
    args = parser.parse_args()

    config = ConfiguracionBandeja(ruta_config=args.config)
    if args.puerto:
        config.puerto_servidor = args.puerto
    if args.descargas:
        config.ruta_descargas = os.path.abspath(os.path.expanduser(args.descargas))
    if args.destino:
        config.ruta_destino_base = os.path.abspath(os.path.expanduser(args.destino))

    db = GestorBaseDatosBandeja()
    filtro = FiltroListaBlanca(config)
    detector = DetectorDescargasActivas()
    agrupador = AgrupadorLotes(config.ventana_lote_minutos)
    movimientos = GestorMovimientosBandeja(
        config.ruta_descargas, config.ruta_destino_base, db,
        subcarpeta_fotos=config.subcarpeta_fotos, subcarpeta_videos=config.subcarpeta_videos
    )
    miniaturas = GeneradorMiniaturas(db)

    vigilante = VigilanteBandeja(config, db, filtro, detector, agrupador)
    vigilante.iniciar()

    token_csrf = secrets.token_urlsafe(32)
    servidor = crear_servidor(config, db, vigilante, movimientos, miniaturas, token_csrf=token_csrf)

    print(f"[*] Bandeja de Descargas iniciada en http://{config.host_servidor}:{config.puerto_servidor}")
    print(f"[*] Vigilando: {config.ruta_descargas}")
    print(f"[*] Destino:   {config.ruta_destino_base}")

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Deteniendo servidor y vigilante...")
    finally:
        vigilante.detener()
        servidor.server_close()


if __name__ == "__main__":
    main()
