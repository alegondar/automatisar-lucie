#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/pendrive.py

Módulo de gestión e integración segura con pendrive:
- Detección reactiva de unidades montadas y validación de marcador .lucie_pendrive.json.
- Vinculación segura de nuevas unidades con creación de estructura LucieSinReglas/.
- Simulación de plan de envío por lotes con verificación de FAT32, espacio y colisiones.
- Transferencia segura mediante archivos .part, fsync y verificación de integridad sha256.
- Manifiesto append-only (manifiesto.jsonl) y bitácora local.
- Deshacer reversible sin borrado trasladando a LucieSinReglas/_revertidos/.
"""

import concurrent.futures
import datetime
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import socket
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from bandeja.plataforma import (
    obtener_sistema_archivos,
    obtener_espacio_disco,
    buscar_puntos_montaje_candidatos,
    ejecutar_con_timeout,
    ejecutar_con_timeout as ejecutar_lectura_pendrive_con_timeout,
)
from bandeja.config import (
    ConfiguracionBandeja,
    ErrorSeguridadBandeja,
    ErrorDeshacer,
    ErrorValidacionEscena,
    CARACTERES_INVALIDOS_ESCENA,
    NOMBRES_RESERVADOS_WINDOWS,
    calcular_sha256,
    formatear_bytes,
    RUTA_DESTINO_DEFECTO,
)
from bandeja.db import GestorBaseDatosBandeja

logger = logging.getLogger("bandeja_descargas")

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


