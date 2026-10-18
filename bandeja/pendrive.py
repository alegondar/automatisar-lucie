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
import subprocess
import time
import uuid
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from bandeja.plataforma import (
    obtener_sistema_archivos,
    obtener_espacio_disco,
    buscar_puntos_montaje_candidatos,
    ejecutar_con_timeout,
    ejecutar_con_timeout as ejecutar_lectura_pendrive_con_timeout,
    notificar_escritorio,
    detectar_particiones_removibles_linux,
    diagnosticar_todas_particiones_linux,
    obtener_disco_padre_particion,
    listar_procesos_ocupando_montaje,
    esta_confinado_en_raiz,
    validar_longitud_ruta,
    normalizar_ruta_relativa_posix,
    convertir_ruta_relativa_a_local,
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
        with open(ruta_marcador, "r", encoding="utf-8", newline="\n") as f:
            datos = json.load(f)
        valido, marcador, err = validar_marcador_pendrive(datos)
        if valido:
            return marcador
        logger.warning(f"Marcador inválido en '{ruta_marcador}': {err}")
        return None
    except Exception as e:
        logger.warning(f"Error al leer marcador en '{ruta_marcador}': {e}")
        return None


_unidades_silenciadas: Set[str] = set()
_operacion_pendrive_activa: bool = False
_lock_operacion_pendrive = threading.Lock()


@contextmanager
def operacion_pendrive_exclusiva():
    """Serializa envío, reversión y eliminación manual; bloquea el desmontaje."""
    global _operacion_pendrive_activa
    if not _lock_operacion_pendrive.acquire(blocking=False):
        raise ValueError('Hay otra operación en curso sobre el pendrive. Esperá a que termine.')
    _operacion_pendrive_activa = True
    try:
        yield
    finally:
        _operacion_pendrive_activa = False
        _lock_operacion_pendrive.release()


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
        with open(ruta_manifiesto, "r", encoding="utf-8", errors="replace", newline="\n") as f:
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
    return _es_extension_video(ext) or _es_extension_foto(ext) or ext.lower() == ".mp3"


def escanear_sala_espera_carpetas(ruta_destino_base: str,
                                   db: Optional[GestorBaseDatosBandeja] = None,
                                   hashes_manifiesto: Optional[Set[str]] = None,
                                   vigilante: Optional[Any] = None) -> List[Dict[str, Any]]:
    """
    Escanea recursivamente la sala de espera ~/Descargas/_lucie/<personaje>/<carpeta>/
    omitiendo carpetas del sistema (_enviados, _revertidos, _descartados, _a_revisar).
    - No sigue symlinks (followlinks=False).
    - Tiene un tope de profundidad de 6 niveles.
    - No descarta carpetas que solo tienen subcarpetas con archivos: acumula el total recursivo.
    - Clasifica cada carpeta cruzando con bandeja_capitulos:
      * 'Capítulo en foco' (activo y en foco en la BD).
      * 'Capítulo abierto' (activo en la BD).
      * 'Capítulo cerrado' (cerrado en la BD).
      * 'Carpeta heredada' (sin estructura canónica de capítulo, ej: imagenes o subcarpetas no estándar).
      * 'Escena suelta' (resto no registrado en la BD pero con estructura válida).
    - Computa fotos, videos, no multimedia, tamaño total, fecha más reciente y cotejo contra manifiesto.
    """
    ruta_real_base = os.path.realpath(os.path.expanduser(ruta_destino_base))
    if not os.path.isdir(ruta_real_base):
        return []

    carpetas_ignoradas = {"_enviados", "_revertidos", "_descartados", "_a_revisar"}
    mapa_caps: Dict[Tuple[str, str], Dict[str, Any]] = {}
    mapa_hashes_db: Dict[str, str] = {}

    if db:
        try:
            with db._conectar() as conn:
                for r in conn.execute("SELECT personaje, nombre, estado, en_foco FROM bandeja_capitulos").fetchall():
                    p = str(r["personaje"]).strip().lower()
                    n = str(r["nombre"]).strip().lower()
                    mapa_caps[(p, n)] = dict(r)
                    n_norm = n.replace(" ", "").replace("-", "").replace("_", "")
                    mapa_caps[(p, n_norm)] = dict(r)

                for r in conn.execute("SELECT ruta_actual, hash FROM bandeja_archivos WHERE hash IS NOT NULL").fetchall():
                    mapa_hashes_db[r["ruta_actual"]] = str(r["hash"]).lower()
        except Exception as e:
            logger.warning(f"Error al consultar base de datos para escanear sala de espera: {e}")

    hashes_man_set = {h.lower() for h in (hashes_manifiesto or set())}
    resultado = []

    for pers in sorted(os.listdir(ruta_real_base)):
        if pers.startswith("_") or pers in carpetas_ignoradas:
            continue
        ruta_pers = os.path.join(ruta_real_base, pers)
        if not os.path.isdir(ruta_pers):
            continue

        for cap in sorted(os.listdir(ruta_pers)):
            if cap.startswith("_") or cap in carpetas_ignoradas:
                continue
            ruta_cap = os.path.join(ruta_pers, cap)
            if not os.path.isdir(ruta_cap):
                continue

            cant_fotos = 0
            cant_vids = 0
            cant_audios = 0
            cant_no_media = 0
            bytes_totales = 0
            mtime_max = 0.0
            cant_enviados = 0
            archivos_lista = []
            tiene_subcarpetas_no_estandar = False

            base_depth = ruta_cap.rstrip(os.sep).count(os.sep)

            for root, dirs, files in os.walk(ruta_cap, followlinks=False):
                cur_depth = root.rstrip(os.sep).count(os.sep) - base_depth
                if cur_depth >= 6:
                    dirs.clear()
                    continue

                rel_root = os.path.relpath(root, ruta_cap)
                if rel_root == ".":
                    for d in dirs:
                        if d not in ("fotos", "videos") and not d.startswith("_"):
                            tiene_subcarpetas_no_estandar = True

                for f in sorted(files):
                    if f.startswith("."):
                        continue
                    p_file = os.path.join(root, f)
                    try:
                        st = os.stat(p_file)
                        sz = st.st_size
                        mt = st.st_mtime
                    except OSError:
                        continue

                    bytes_totales += sz
                    if mt > mtime_max:
                        mtime_max = mt

                    _, ext = os.path.splitext(f)
                    ext_lower = ext.lower()
                    es_vid = _es_extension_video(ext_lower)
                    es_fot = _es_extension_foto(ext_lower)

                    if es_vid:
                        cant_vids += 1
                        tipo_arch = "video"
                    elif es_fot:
                        cant_fotos += 1
                        tipo_arch = "foto"
                    elif ext_lower == ".mp3":
                        cant_audios += 1
                        tipo_arch = "audio"
                    else:
                        cant_no_media += 1
                        tipo_arch = "otro"

                    # id_media opaco para la vista previa
                    id_m = None
                    if vigilante and hasattr(vigilante, "registrar_ruta_media"):
                        id_m = vigilante.registrar_ruta_media(p_file)
                    else:
                        id_m = hashlib.sha256(f"media:{p_file}".encode("utf-8")).hexdigest()[:32]

                    # Chequeo contra manifiesto si está disponible
                    h_archivo = mapa_hashes_db.get(p_file)
                    ya_env = False
                    if h_archivo and hashes_man_set:
                        ya_env = (h_archivo in hashes_man_set)
                    if ya_env:
                        cant_enviados += 1

                    archivos_lista.append({
                        "nombre": f,
                        "ruta_relativa": normalizar_ruta_relativa_posix(os.path.relpath(p_file, ruta_cap)),
                        "ruta_absoluta": p_file,
                        "tamanio_bytes": sz,
                        "tamanio_fmt": formatear_bytes(sz),
                        "mtime": mt,
                        "fecha_modificacion": datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M:%S") if mt > 0 else "N/D",
                        "tipo": tipo_arch,
                        "id_media": id_m,
                        "ya_enviado": ya_env
                    })

            # Clasificación de tipo
            p_key = pers.strip().lower()
            c_key = cap.strip().lower()
            c_norm = c_key.replace(" ", "").replace("-", "").replace("_", "")

            db_entry = mapa_caps.get((p_key, c_key)) or mapa_caps.get((p_key, c_norm))

            if db_entry:
                if db_entry.get("en_foco") == 1 and db_entry.get("estado") == "activo":
                    tipo_carpeta = "Capítulo en foco"
                elif db_entry.get("estado") == "activo":
                    tipo_carpeta = "Capítulo abierto"
                else:
                    tipo_carpeta = "Capítulo cerrado"
            else:
                if cap.lower() in ("imagenes", "fotos", "videos", "legacy", "heredado") or tiene_subcarpetas_no_estandar:
                    tipo_carpeta = "Carpeta heredada"
                else:
                    tipo_carpeta = "Escena suelta"

            fecha_fmt = datetime.datetime.fromtimestamp(mtime_max).strftime("%Y-%m-%d %H:%M:%S") if mtime_max > 0 else "N/D"

            resultado.append({
                "personaje": pers,
                "carpeta": cap,
                "capitulo": cap,
                "tipo": tipo_carpeta,
                "es_heredada": (tipo_carpeta == "Carpeta heredada"),
                "ruta_absoluta": ruta_cap,
                "fotos": cant_fotos,
                "videos": cant_vids,
                "audios": cant_audios,
                "no_multimedia": cant_no_media,
                "total_archivos": len(archivos_lista),
                "bytes_totales": bytes_totales,
                "bytes_totales_fmt": formatear_bytes(bytes_totales),
                "fecha_ultimo_archivo": fecha_fmt,
                "mtime_max": mtime_max,
                "enviados_conteo": cant_enviados,
                "pendientes_conteo": len(archivos_lista) - cant_enviados,
                "archivos": archivos_lista
            })

    return resultado


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
                "carpeta": cap,
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
                        "ruta_relativa": normalizar_ruta_relativa_posix(os.path.relpath(p, raiz_completa)),
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

    particiones_rem = detectar_particiones_removibles_linux(etiqueta_pista=getattr(cfg, "etiqueta_pendrive_pista", None))
    todas_diag = diagnosticar_todas_particiones_linux()

    # Limpiar de _unidades_silenciadas aquellas que ya no existen físicamente
    nodos_activos = {p["dispositivo"] for p in particiones_rem} | {p["nodo"] for p in particiones_rem} | {p.get("punto_montaje") for p in particiones_rem if p.get("punto_montaje")}
    for u in list(_unidades_silenciadas):
        if u and u not in nodos_activos:
            _unidades_silenciadas.discard(u)

    info = detectar_pendrive(cfg)
    if not info or not info.get("conectado"):
        cand = detectar_unidad_candidata_sin_vincular(cfg)
        if cand:
            estado_unidad = "conectada_sin_vincular"
            cand_p = cand.get("punto_montaje")
            part_match = next((p for p in particiones_rem if p.get("punto_montaje") == cand_p), None)
            disp_cand = part_match.get("dispositivo") if part_match else None
            nodo_cand = part_match.get("nodo") if part_match else None
            padre_cand = part_match.get("disco_padre") if part_match else None
            etiq_cand = part_match.get("etiqueta") if part_match else None
            acciones = ["desmontar", "expulsar", "vincular"] if os.name != "nt" else ["vincular"]

            return {
                "conectado": False,
                "sin_respuesta": False,
                "estado_unidad": estado_unidad,
                "id": None,
                "punto_montaje": cand_p,
                "dispositivo": disp_cand,
                "nodo": nodo_cand,
                "disco_padre": padre_cand,
                "etiqueta": etiq_cand,
                "sistema_archivos": cand.get("sistema_archivos"),
                "espacio_libre_bytes": cand.get("espacio_libre_bytes", 0),
                "espacio_libre_fmt": formatear_bytes(cand.get("espacio_libre_bytes", 0)),
                "espacio_total_bytes": cand.get("espacio_total_bytes", 0),
                "espacio_total_fmt": formatear_bytes(cand.get("espacio_total_bytes", 0)),
                "espacio_usado_bytes": cand.get("espacio_usado_bytes", 0),
                "unidad_candidata": cand,
                "acciones_disponibles": acciones,
                "archivos_part_huerfanos": [],
                "archivos_pendientes_conteo": 0,
                "capitulos_pendientes_conteo": 0,
                "capitulos_pendientes": [],
                "banner_reactivo": None,
                "todas_unidades_removibles": particiones_rem,
                "diagnostico_particiones": todas_diag,
                "es_windows": (os.name == "nt")
            }

        # Removibles no montadas
        no_montadas = [p for p in particiones_rem if not p.get("montado")]
        if no_montadas:
            p_sel = no_montadas[0]
            acciones = ["montar"] if os.name != "nt" else []
            return {
                "conectado": False,
                "sin_respuesta": False,
                "estado_unidad": "detectada_sin_montar",
                "id": None,
                "punto_montaje": None,
                "dispositivo": p_sel.get("dispositivo"),
                "nodo": p_sel.get("nodo"),
                "disco_padre": p_sel.get("disco_padre"),
                "etiqueta": p_sel.get("etiqueta") or "",
                "sistema_archivos": p_sel.get("sistema_archivos") or "desconocido",
                "espacio_libre_bytes": 0,
                "espacio_libre_fmt": "0 B",
                "espacio_total_bytes": p_sel.get("tamanio_bytes", 0),
                "espacio_total_fmt": p_sel.get("tamanio_fmt", "0 B"),
                "espacio_usado_bytes": 0,
                "unidad_candidata": p_sel,
                "acciones_disponibles": acciones,
                "archivos_part_huerfanos": [],
                "archivos_pendientes_conteo": 0,
                "capitulos_pendientes_conteo": 0,
                "capitulos_pendientes": [],
                "banner_reactivo": None,
                "todas_unidades_removibles": particiones_rem,
                "diagnostico_particiones": todas_diag,
                "es_windows": (os.name == "nt")
            }

        # Sin ninguna unidad
        return {
            "conectado": False,
            "sin_respuesta": False,
            "estado_unidad": "sin_unidad",
            "id": None,
            "punto_montaje": None,
            "dispositivo": None,
            "nodo": None,
            "disco_padre": None,
            "etiqueta": None,
            "sistema_archivos": None,
            "espacio_libre_bytes": 0,
            "espacio_libre_fmt": "0 B",
            "espacio_total_bytes": 0,
            "espacio_total_fmt": "0 B",
            "espacio_usado_bytes": 0,
            "unidad_candidata": None,
            "acciones_disponibles": [],
            "archivos_part_huerfanos": [],
            "archivos_pendientes_conteo": 0,
            "capitulos_pendientes_conteo": 0,
            "capitulos_pendientes": [],
            "banner_reactivo": None,
            "todas_unidades_removibles": particiones_rem,
            "diagnostico_particiones": todas_diag,
            "es_windows": (os.name == "nt")
        }

    # Caso conectado y vinculado (vinculado_listo)
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

    # Cotejar con particiones removibles detectadas
    part_match = next((p for p in particiones_rem if p.get("punto_montaje") == punto), None)
    disp_id = part_match.get("dispositivo") if part_match else None
    nodo_id = part_match.get("nodo") if part_match else None
    padre_id = part_match.get("disco_padre") if part_match else None
    etiq_id = part_match.get("etiqueta") if part_match else None

    esta_silenciada = (disp_id in _unidades_silenciadas or nodo_id in _unidades_silenciadas or punto in _unidades_silenciadas)

    banner = None
    if tot_arch > 0 and not esta_silenciada:
        banner = {
            "mostrar": True,
            "mensaje": f"Pendrive detectado: {tot_arch} archivo(s) de {len(caps_detalle)} capítulo(s) listos para enviar",
            "archivos": tot_arch,
            "capitulos": len(caps_detalle)
        }

    esp_libre = info.get("espacio_libre_bytes", 0)
    esp_total = info.get("espacio_total_bytes", 0)
    esp_usado = info.get("espacio_usado_bytes", 0)
    acciones = ["desmontar", "expulsar"] if os.name != "nt" else []

    return {
        "conectado": True,
        "sin_respuesta": False,
        "estado_unidad": "vinculado_listo",
        "id": info.get("id", ""),
        "punto_montaje": punto,
        "dispositivo": disp_id,
        "nodo": nodo_id,
        "disco_padre": padre_id,
        "etiqueta": etiq_id,
        "sistema_archivos": info.get("sistema_archivos"),
        "espacio_libre_bytes": esp_libre,
        "espacio_libre_fmt": formatear_bytes(esp_libre),
        "espacio_total_bytes": esp_total,
        "espacio_total_fmt": formatear_bytes(esp_total),
        "espacio_usado_bytes": esp_usado,
        "unidad_candidata": None,
        "acciones_disponibles": acciones,
        "archivos_part_huerfanos": part_files,
        "archivos_pendientes_conteo": tot_arch,
        "capitulos_pendientes_conteo": len(caps_detalle),
        "capitulos_pendientes": caps_detalle,
        "banner_reactivo": banner,
        "todas_unidades_removibles": particiones_rem,
        "diagnostico_particiones": todas_diag,
        "es_windows": (os.name == "nt")
    }


def obtener_estado_pendrive(config: Optional[ConfiguracionBandeja] = None,
                            db: Optional[GestorBaseDatosBandeja] = None,
                            timeout_segundos: float = 3.0) -> Dict[str, Any]:
    """
    Obtiene el estado completo del pendrive ejecutando la lectura fuera del hilo principal
    con límite estricto de timeout_segundos (por defecto 3 s).
    Si el pendrive se cuelga o no responde, retorna sin bloquear indicando sin_respuesta=True.
    """
    try:
        res = ejecutar_lectura_pendrive_con_timeout(_leer_estado_pendrive_raw, config, db, timeout_segundos=timeout_segundos)
    except Exception:
        res = {"sin_respuesta": True}
    if not isinstance(res, dict) or res.get("sin_respuesta"):
        return {
            "conectado": False,
            "sin_respuesta": True,
            "estado_unidad": "sin_respuesta",
            "error": "Pendrive sin respuesta",
            "mensaje": "Pendrive sin respuesta",
            "id": None,
            "punto_montaje": None,
            "dispositivo": None,
            "nodo": None,
            "disco_padre": None,
            "etiqueta": None,
            "sistema_archivos": None,
            "espacio_libre_bytes": 0,
            "espacio_total_bytes": 0,
            "espacio_usado_bytes": 0,
            "unidad_candidata": None,
            "acciones_disponibles": [],
            "todas_unidades_removibles": [],
            "diagnostico_particiones": [],
            "es_windows": (os.name == "nt"),
            "archivos_part_huerfanos": [],
            "archivos_pendientes_conteo": 0,
            "capitulos_pendientes_conteo": 0,
            "capitulos_pendientes": [],
            "banner_reactivo": None
        }
    return res


def montar_unidad_pendrive(dispositivo: str,
                           timeout: float = 15.0,
                           config: Optional[ConfiguracionBandeja] = None,
                           db: Optional[GestorBaseDatosBandeja] = None) -> Dict[str, Any]:
    """
    Monta una partición extraíble usando udisksctl mount -b <dispositivo>.
    Valida que el dispositivo esté en la lista blanca de particiones removibles detectadas.
    Registra el evento en la bitácora si hay db configurada.
    """
    if not dispositivo or not isinstance(dispositivo, str):
        raise ValueError("El nodo de dispositivo no puede estar vacío.")

    disp_limpio = dispositivo.strip()
    if os.name == "nt":
        return {
            "exito": False,
            "error": "El montaje de unidades con udisksctl no está disponible en Windows.",
            "no_soportado": True,
            "dispositivo": disp_limpio
        }

    if not re.match(r"^/dev/[a-zA-Z0-9_\-]+$", disp_limpio):
        raise ValueError(f"Formato de dispositivo inválido o inseguro: '{disp_limpio}'")

    # Validación de lista blanca
    removibles = detectar_particiones_removibles_linux()
    dispositivos_validos = {p["dispositivo"] for p in removibles}
    cfg = config or ConfiguracionBandeja()
    rutas_cfg = getattr(cfg, "rutas_candidatas_pendrive", None) or []
    for r in rutas_cfg:
        dispositivos_validos.add(r)
        try:
            dispositivos_validos.add(os.path.realpath(r))
        except Exception:
            pass

    if disp_limpio not in dispositivos_validos and not any(disp_limpio.endswith(p["nodo"]) for p in removibles):
        raise ValueError(f"Dispositivo no permitido o no detectado como removible: '{disp_limpio}'")

    cmd = ["udisksctl", "mount", "-b", disp_limpio]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        salida = (proc.stdout if isinstance(proc.stdout, str) else str(proc.stdout or "")).strip()
        error = (proc.stderr if isinstance(proc.stderr, str) else str(proc.stderr or "")).strip()
        exito = (proc.returncode == 0)

        punto_montaje = None
        if exito:
            m = re.search(r" at\s+(/[^\s\.]+)", salida)
            if m:
                punto_montaje = m.group(1).rstrip(".")
            if disp_limpio in _unidades_silenciadas:
                _unidades_silenciadas.discard(disp_limpio)
            if os.path.basename(disp_limpio) in _unidades_silenciadas:
                _unidades_silenciadas.discard(os.path.basename(disp_limpio))

        if db:
            try:
                db.registrar_evento("montar_unidad", {
                    "dispositivo": disp_limpio,
                    "exito": exito,
                    "salida": salida,
                    "error": error,
                    "punto_montaje": punto_montaje
                })
            except Exception as e_db:
                logger.debug(f"No se pudo registrar evento montar_unidad en bitácora: {e_db}")

        if exito:
            return {
                "exito": True,
                "mensaje": salida or f"Unidad '{disp_limpio}' montada exitosamente.",
                "dispositivo": disp_limpio,
                "punto_montaje": punto_montaje,
                "comando_ejecutado": f"udisksctl mount -b {disp_limpio}"
            }
        else:
            return {
                "exito": False,
                "error": error or salida or "Error desconocido al montar la unidad.",
                "dispositivo": disp_limpio,
                "comando_manual": f"udisksctl mount -b {disp_limpio}",
                "comando_ejecutado": f"udisksctl mount -b {disp_limpio}"
            }
    except FileNotFoundError:
        return {
            "exito": False,
            "error": "El comando 'udisksctl' no está instalado en este sistema.",
            "dispositivo": disp_limpio,
            "comando_manual": f"udisksctl mount -b {disp_limpio}",
            "comando_ejecutado": f"udisksctl mount -b {disp_limpio}"
        }
    except subprocess.TimeoutExpired:
        return {
            "exito": False,
            "error": f"Tiempo de espera agotado ({timeout}s) al intentar montar '{disp_limpio}'.",
            "dispositivo": disp_limpio,
            "comando_manual": f"udisksctl mount -b {disp_limpio}",
            "comando_ejecutado": f"udisksctl mount -b {disp_limpio}"
        }


def desmontar_unidad_pendrive(dispositivo: str,
                              expulsar: bool = False,
                              timeout: float = 15.0,
                              config: Optional[ConfiguracionBandeja] = None,
                              db: Optional[GestorBaseDatosBandeja] = None) -> Dict[str, Any]:
    """
    Desmonta una unidad usando udisksctl unmount -b <dispositivo> y opcionalmente
    ejecuta udisksctl power-off -b <disco_padre> si expulsar=True.
    Precondiciones:
    - Verifica que no haya transferencia o deshacer en curso ni .part activo.
    - Ejecuta os.sync().
    - Si falla por estar ocupada (busy), inspecciona procesos ocupantes vía /proc.
    - Silencia el banner reactivo para la unidad retirada.
    """
    global _operacion_pendrive_activa

    if not dispositivo or not isinstance(dispositivo, str):
        raise ValueError("El nodo de dispositivo no puede estar vacío.")

    disp_limpio = dispositivo.strip()
    if _operacion_pendrive_activa:
        return {
            "exito": False,
            "error": "No se puede desmontar: hay un envío o reversión de transferencia en curso en este momento.",
            "dispositivo": disp_limpio,
            "bloqueado": True
        }

    if os.name == "nt":
        return {
            "exito": False,
            "error": "El desmontaje de unidades con udisksctl no está disponible en Windows.",
            "no_soportado": True,
            "dispositivo": disp_limpio
        }

    removibles = detectar_particiones_removibles_linux()
    dispositivos_validos = {p["dispositivo"] for p in removibles}
    info_part = next((p for p in removibles if p["dispositivo"] == disp_limpio or p["nodo"] == os.path.basename(disp_limpio)), None)

    cfg = config or ConfiguracionBandeja()
    rutas_cfg = getattr(cfg, "rutas_candidatas_pendrive", None) or []
    for r in rutas_cfg:
        dispositivos_validos.add(r)
        try:
            dispositivos_validos.add(os.path.realpath(r))
        except Exception:
            pass

    if disp_limpio not in dispositivos_validos and not any(disp_limpio.endswith(p["nodo"]) for p in removibles):
        raise ValueError(f"Dispositivo no permitido o no detectado como removible: '{disp_limpio}'")

    punto_montaje = info_part.get("punto_montaje") if info_part else None

    # Verificar si hay archivos .part activos en el pendrive
    if punto_montaje and os.path.isdir(punto_montaje):
        carpeta_raiz = getattr(cfg, "carpeta_raiz_pendrive", CARPETA_RAIZ_PENDRIVE_DEFECTO)
        parts_huerfanos = listar_archivos_part_huerfanos(punto_montaje, carpeta_raiz)
        if len(parts_huerfanos) > 0:
            logger.info(f"Desmontando con {len(parts_huerfanos)} archivos .part preservados en pendrive.")

    # os.sync() antes de desmontar (solo si está disponible en la plataforma)
    if hasattr(os, "sync"):
        try:
            os.sync()
        except Exception as e_sync:
            logger.debug(f"os.sync previo al unmount: {e_sync}")

    cmd_unmount = ["udisksctl", "unmount", "-b", disp_limpio]
    try:
        proc = subprocess.run(cmd_unmount, capture_output=True, text=True, timeout=timeout)
        salida = (proc.stdout if isinstance(proc.stdout, str) else str(proc.stdout or "")).strip()
        error = (proc.stderr if isinstance(proc.stderr, str) else str(proc.stderr or "")).strip()
        exito = (proc.returncode == 0)

        if not exito:
            es_busy = any(w in error.lower() or w in salida.lower() for w in ("busy", "target is busy", "en uso", "ocupado"))
            procesos_ocupantes = []
            if es_busy and punto_montaje:
                procesos_ocupantes = listar_procesos_ocupando_montaje(punto_montaje)

            msg_error = error or salida or "Error al desmontar la unidad."
            if es_busy:
                msg_error = f"La unidad está ocupada por otras aplicaciones ({len(procesos_ocupantes)} proceso(s) detectado(s)). Cerrá esas ventanas o terminales antes de desmontar."

            return {
                "exito": False,
                "error": msg_error,
                "ocupado": es_busy,
                "procesos_ocupantes": procesos_ocupantes,
                "procesos_ocupando": procesos_ocupantes,
                "dispositivo": disp_limpio,
                "comando_manual": f"udisksctl unmount -b {disp_limpio}",
                "comando_ejecutado": f"udisksctl unmount -b {disp_limpio}"
            }

        # Silenciar unidad tras desmontaje exitoso
        _unidades_silenciadas.add(disp_limpio)
        _unidades_silenciadas.add(os.path.basename(disp_limpio))
        if punto_montaje:
            _unidades_silenciadas.add(punto_montaje)

        power_off_exito = False
        power_off_msg = ""
        disco_padre = None

        if expulsar:
            disco_padre = info_part.get("disco_padre") if info_part else obtener_disco_padre_particion(disp_limpio)
            if not disco_padre:
                disco_padre = disp_limpio

            cmd_poweroff = ["udisksctl", "power-off", "-b", disco_padre]
            proc_po = subprocess.run(cmd_poweroff, capture_output=True, text=True, timeout=timeout)
            power_off_exito = (proc_po.returncode == 0)
            po_stdout = (proc_po.stdout if isinstance(proc_po.stdout, str) else str(proc_po.stdout or "")).strip()
            po_stderr = (proc_po.stderr if isinstance(proc_po.stderr, str) else str(proc_po.stderr or "")).strip()
            if power_off_exito:
                power_off_msg = po_stdout
                _unidades_silenciadas.add(disco_padre)
                _unidades_silenciadas.add(os.path.basename(disco_padre))
            else:
                power_off_msg = po_stderr or po_stdout

        if db:
            try:
                db.registrar_evento("desmontar_unidad", {
                    "dispositivo": disp_limpio,
                    "expulsar": expulsar,
                    "exito_unmount": True,
                    "exito_power_off": power_off_exito if expulsar else None,
                    "disco_padre": disco_padre,
                    "punto_montaje": punto_montaje
                })
            except Exception as e_db:
                logger.debug(f"No se pudo registrar evento desmontar_unidad en bitácora: {e_db}")

        mensaje_final = "Unidad desmontada exitosamente."
        if expulsar:
            if power_off_exito:
                mensaje_final = "Unidad desmontada y apagada exitosamente. Ya podés retirar el pendrive."
            else:
                mensaje_final = f"Unidad desmontada, pero falló la expulsión eléctrica: {power_off_msg}."

        return {
            "exito": True,
            "expulsado": (expulsar and power_off_exito),
            "mensaje": mensaje_final,
            "dispositivo": disp_limpio,
            "disco_padre": disco_padre,
            "comando_ejecutado": f"udisksctl unmount -b {disp_limpio}" + (f" && udisksctl power-off -b {disco_padre}" if expulsar else "")
        }

    except FileNotFoundError:
        return {
            "exito": False,
            "error": "El comando 'udisksctl' no está disponible en este sistema.",
            "dispositivo": disp_limpio,
            "comando_manual": f"udisksctl unmount -b {disp_limpio}"
        }
    except subprocess.TimeoutExpired:
        return {
            "exito": False,
            "error": f"Tiempo de espera agotado ({timeout}s) al intentar desmontar '{disp_limpio}'.",
            "dispositivo": disp_limpio,
            "comando_manual": f"udisksctl unmount -b {disp_limpio}"
        }


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
    carpetas_arg = kwargs.get("carpetas")
    capitulos_lista = capitulos_filtro if capitulos_filtro is not None else (carpetas_arg if carpetas_arg is not None else kwargs.get("capitulos"))

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

    # 2. Obtener carpetas candidatas en la sala de espera
    todas_carpetas = escanear_sala_espera_carpetas(cfg.ruta_destino_base, db=db, hashes_manifiesto=hashes_manifiesto)
    carpetas_seleccionadas = []

    if capitulos_lista:
        filtro_normalizado = {str(c).strip().lower() for c in capitulos_lista if str(c).strip()}
        if "todos" in filtro_normalizado or not filtro_normalizado:
            carpetas_seleccionadas = todas_carpetas
        else:
            for c in todas_carpetas:
                clave_completa = f"{c['personaje']}/{c['carpeta']}".lower()
                clave_corta = c["carpeta"].lower()
                if clave_completa in filtro_normalizado or clave_corta in filtro_normalizado:
                    carpetas_seleccionadas.append(c)
    else:
        carpetas_seleccionadas = todas_carpetas

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

    for c in carpetas_seleccionadas:
        pers = c["personaje"]
        cap = c["carpeta"]
        ruta_cap = c["ruta_absoluta"]

        if (pers, cap) in capitulos_abiertos_nombres:
            avisos.append(f"Aviso: El capítulo '{pers}/{cap}' sigue abierto en la sala de espera; podrían llegar más archivos.")

        # Recorrer archivos dentro de la carpeta (recursivo seguro)
        candidatos_archivos = []  # (ruta_origen, subcarpeta_origen, nombre_archivo, tipo_media, sub_dest)

        for arch in c.get("archivos", []):
            p = arch["ruta_absoluta"]
            nombre = arch["nombre"]
            tipo_arch = arch["tipo"]
            rel_dir = os.path.dirname(arch.get("ruta_relativa", ""))

            tam = arch.get("tamanio_bytes", 0)
            if tipo_arch == "video":
                candidatos_archivos.append((p, rel_dir or sub_videos, nombre, "crudo", "videos sin editar", tam))
            elif tipo_arch == "foto":
                candidatos_archivos.append((p, rel_dir or sub_fotos, nombre, "imagen", "imagenes", tam))
            elif tipo_arch == "audio":
                candidatos_archivos.append((p, rel_dir or 'audios', nombre, "audio", "audios", tam))
            else:
                item_no_med = {
                    "personaje": pers,
                    "capitulo": cap,
                    "nombre": nombre,
                    "ruta_origen": p,
                    "tamanio_bytes": tam,
                    "motivo": "No multimedia (omitido)",
                    "aviso": "Archivo con extensión no multimedia omitido del envío."
                }
                archivos_no_multimedia.append(item_no_med)
                avisos.append(f"Archivo no multimedia omitido: '{pers}/{cap}/{nombre}'.")

        # Evaluar cada archivo candidato
        for ruta_orig, sub_orig, nombre, tipo_media, sub_dest, tam in candidatos_archivos:

            ruta_rel_pendrive = normalizar_ruta_relativa_posix(os.path.join(sub_dest, pers, cap, nombre))
            ruta_abs_pendrive = os.path.join(pendrive_montaje, carpeta_raiz, convertir_ruta_relativa_a_local(ruta_rel_pendrive))
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
        "capitulos_seleccionados": [f"{c['personaje']}/{c.get('carpeta') or c.get('capitulo')}" for c in carpetas_seleccionadas],
        "carpetas_seleccionadas": [f"{c['personaje']}/{c.get('carpeta') or c.get('capitulo')}" for c in carpetas_seleccionadas],
        "archivos_a_copiar": archivos_a_copiar,
        "archivos_omitidos": archivos_omitidos,
        "archivos_conflictos": archivos_conflictos,
        "archivos_bloqueados": archivos_bloqueados,
        "archivos_no_multimedia": archivos_no_multimedia,
        "avisos": avisos,
        "advertencias": avisos,
        "total_archivos_a_enviar": len(archivos_a_copiar),
        "bytes_a_enviar": bytes_a_copiar,
        "bytes_a_enviar_fmt": formatear_bytes(bytes_a_copiar),
        "pendrive_id": info_pendrive.get("id"),
        "punto_montaje": pendrive_montaje,
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
    """Ejecuta la transferencia física segura de archivos hacia el pendrive."""
    with operacion_pendrive_exclusiva():
        return _ejecutar_envio_pendrive_interno(simulacion_o_capitulos, config, db, movimientos)


def _limpiar_carpetas_vacias_enviadas(base_origen, archivos_transferidos, ruta_bitacora=None):
    """Excepción autorizada: rmdir de carpetas vacías de capítulos enviados.

    Incluye huérfanas de envíos anteriores registrados en la misma sala.
    Nunca elimina archivos, la sala de espera, personajes, áreas de respaldo
    ni capítulos ajenos. Un contenido nuevo o un error conserva la carpeta.
    Solo se invoca tras un envío completo, verificado y registrado.
    """
    if not archivos_transferidos:
        return []
    registros = list(archivos_transferidos)
    if ruta_bitacora:
        try:
            with open(ruta_bitacora, "r", encoding="utf-8") as historial:
                for linea in historial:
                    try:
                        evento = json.loads(linea)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(evento, dict) or evento.get("evento") != "envio_pendrive":
                        continue
                    archivos = evento.get("archivos")
                    if isinstance(archivos, list):
                        registros.extend(r for r in archivos if isinstance(r, dict))
        except (OSError, UnicodeError) as error:
            logger.warning("No se pudo revisar el historial de carpetas enviadas: %s", error)
    base = os.path.abspath(base_origen)
    eliminadas = []
    capitulos = set()
    for registro in registros:
        origen = registro.get("ruta_origen_espera")
        personaje = registro.get("personaje")
        nombre_capitulo = registro.get("capitulo")
        if not all(isinstance(valor, str) and valor for valor in (origen, personaje, nombre_capitulo)):
            continue
        capitulo = os.path.join(base, personaje, nombre_capitulo)
        if (esta_confinado_en_raiz(origen, capitulo)
                and os.path.abspath(origen) != os.path.abspath(capitulo)):
            capitulos.add(capitulo)
    for capitulo in sorted(capitulos):
        relativa = os.path.relpath(capitulo, base)
        partes = relativa.split(os.sep)
        if len(partes) != 2 or any(p in ("", ".", "..") or p.startswith(("_", ".")) for p in partes):
            continue
        if not esta_confinado_en_raiz(capitulo, base):
            continue
        # No atravesar enlaces ni junctions, incluidos los padres de la raíz.
        actual = capitulo
        segura = True
        while True:
            if os.path.islink(actual) or (hasattr(os.path, "isjunction") and os.path.isjunction(actual)):
                segura = False
                break
            padre = os.path.dirname(actual)
            if padre == actual:
                break
            actual = padre
        if not segura:
            continue
        candidatas = []
        for ruta, dirs, files in os.walk(capitulo, topdown=True, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(("_", "."))
                       and not os.path.islink(os.path.join(ruta, d))
                       and not (hasattr(os.path, "isjunction") and os.path.isjunction(os.path.join(ruta, d)))]
            if esta_confinado_en_raiz(ruta, capitulo):
                candidatas.append(ruta)
        for ruta in sorted(candidatas, key=lambda p: len(os.path.normpath(p).split(os.sep)), reverse=True):
            actual = ruta
            segura = True
            while True:
                if os.path.islink(actual) or (hasattr(os.path, "isjunction") and os.path.isjunction(actual)):
                    segura = False
                    break
                padre = os.path.dirname(actual)
                if padre == actual:
                    break
                actual = padre
            if not segura or not esta_confinado_en_raiz(ruta, capitulo):
                continue
            try:
                # El sistema operativo comprueba atomicamente que esté vacía.
                os.rmdir(ruta)
                eliminadas.append(ruta)
            except OSError:
                pass
    return eliminadas


def _ejecutar_envio_pendrive_interno(simulacion_o_capitulos: Any,
                                     config: Optional[ConfiguracionBandeja] = None,
                                     db: Optional[GestorBaseDatosBandeja] = None,
                                     movimientos: Optional[Any] = None) -> Dict[str, Any]:
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
        validar_longitud_ruta(ruta_orig)

        # Confinamiento de origen
        if os.path.islink(ruta_orig) or not esta_confinado_en_raiz(ruta_orig, base_origen):
            raise ErrorSeguridadBandeja(f"Violación de confinamiento: archivo de origen fuera de la sala de espera: '{ruta_orig}'")

        if not os.path.exists(ruta_orig):
            raise FileNotFoundError(f"El archivo de origen '{ruta_orig}' ya no existe.")

        rel_dest = normalizar_ruta_relativa_posix(item["ruta_relativa_pendrive"])
        if ".." in rel_dest or rel_dest.startswith("/"):
            raise ErrorSeguridadBandeja(f"Intento de path traversal en ruta relativa: '{rel_dest}'")

        ruta_dest = os.path.abspath(os.path.join(pendrive_raiz, convertir_ruta_relativa_a_local(rel_dest)))
        validar_longitud_ruta(ruta_dest)
        dest_dir = os.path.dirname(ruta_dest)

        # Confinamiento de destino
        if not esta_confinado_en_raiz(dest_dir, pendrive_raiz):
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
    with open(ruta_manifiesto, "a", encoding="utf-8", newline="\n") as f_man:
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
        "limpieza_carpetas_vacias": "capitulos del envio e huerfanas de envios anteriores registrados, despues de verificar y registrar",
        "id_operacion": id_envio,
        "fecha": fecha_iso,
        "pendrive_id": pendrive_id,
        "pendrive_montaje": pendrive_montaje,
        "total_archivos": len(archivos_transferidos),
        "bytes_totales": sum(r["bytes"] for r in archivos_transferidos),
        "capitulos": sorted(list({r["capitulo"] for r in archivos_transferidos})),
        "archivos": archivos_transferidos
    }
    with open(ruta_bitacora, "a", encoding="utf-8", newline="\n") as f_bit:
        f_bit.write(json.dumps(evento_bitacora, ensure_ascii=False) + "\n")
        f_bit.flush()

    # Solo después de las copias verificadas y de ambos registros exitosos.
    carpetas_vacias_eliminadas = _limpiar_carpetas_vacias_enviadas(base_origen, archivos_transferidos, ruta_bitacora)

    return {
        "exito": True,
        "carpetas_vacias_eliminadas": carpetas_vacias_eliminadas,
        "id_envio": id_envio,
        "fecha": fecha_iso,
        "pendrive_id": pendrive_id,
        "total_transferidos": len(archivos_transferidos),
        "total_archivos_enviados": len(archivos_transferidos),
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
    """Revierte una operación de envío al pendrive sin borrar absolutamente nada."""
    with operacion_pendrive_exclusiva():
        return _deshacer_envio_pendrive_interno(id_operacion, operacion, config, db, ruta_bitacora)


def _deshacer_envio_pendrive_interno(id_operacion: str,
                                     operacion: Optional[Dict[str, Any]] = None,
                                     config: Optional[ConfiguracionBandeja] = None,
                                     db: Optional[GestorBaseDatosBandeja] = None,
                                     ruta_bitacora: Optional[str] = None) -> Dict[str, Any]:
    cfg = config or ConfiguracionBandeja()
    bit_path = ruta_bitacora or "bitacora_bandeja.jsonl"

    op_encontrada = operacion
    if not op_encontrada:
        if not os.path.exists(bit_path):
            raise ErrorDeshacer("No existe archivo de bitácora para deshacer operaciones.")
        with open(bit_path, "r", encoding="utf-8", newline="\n") as f:
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
        with open(bit_path, "r", encoding="utf-8", newline="\n") as f:
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
        rel_path = normalizar_ruta_relativa_posix(r["ruta_relativa"])
        rel_local = convertir_ruta_relativa_a_local(rel_path)
        ruta_en_pendrive = os.path.join(pendrive_raiz, rel_local)
        ruta_en_enviados = r["ruta_enviados"]
        ruta_origen_espera = r["ruta_origen_espera"]
        ruta_dest_revertido = os.path.join(pendrive_raiz, "_revertidos", id_operacion, rel_local)

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
        with open(ruta_manifiesto, "a", encoding="utf-8", newline="\n") as f_man:
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
    with open(bit_path, "a", encoding="utf-8", newline="\n") as f_bit:
        f_bit.write(json.dumps(evento_reversion, ensure_ascii=False) + "\n")
        f_bit.flush()

    return {
        "exito": True,
        "id_operacion": id_operacion,
        "total_revertidos": len(items_plan),
        "mensaje": f"Envío '{id_operacion}' revertido exitosamente: archivos devueltos a la sala de espera y copias en pendrive preservadas en _revertidos."
    }


