#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/plataforma.py

Capa de abstracción del sistema operativo para la bandeja de descargas:
- Detección de puntos de montaje y unidades candidatas (Linux y Windows).
- Lectura del sistema de archivos vía /proc/mounts.
- Consulta de espacio libre y total en disco.
- Ejecución aislada con tiempo límite (timeout) contra bloqueos de I/O.
- Notificaciones de escritorio del sistema.
- Rutas por defecto según plataforma.
"""

import concurrent.futures
import glob
import logging
import os
import shutil
import string
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bandeja.plataforma")


def obtener_ruta_descargas_defecto() -> str:
    """Retorna la ruta por defecto a la carpeta de descargas del usuario."""
    ruta_usuario = os.path.expanduser("~/Descargas")
    if os.path.isdir(ruta_usuario):
        return ruta_usuario
    ruta_en = os.path.expanduser("~/Downloads")
    if os.path.isdir(ruta_en):
        return ruta_en
    return ruta_usuario


def obtener_ruta_destino_defecto() -> str:
    """Retorna la ruta de destino base por defecto (~/Descargas/_lucie)."""
    return os.path.join(obtener_ruta_descargas_defecto(), "_lucie")


def obtener_sistema_archivos(punto_montaje: str) -> str:
    """
    Determina el sistema de archivos del punto de montaje especificado.
    En Linux consulta /proc/mounts; si no está disponible o falla, retorna 'desconocido'.
    """
    try:
        punto_real = os.path.realpath(punto_montaje)
        if os.name == "posix" and os.path.exists("/proc/mounts"):
            mejor_coincidencia = ""
            mejor_fstype = "desconocido"
            with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
                for linea in f:
                    partes = linea.strip().split()
                    if len(partes) >= 3:
                        mp = os.path.realpath(partes[1])
                        # Coincidencia exacta o la más larga que contenga punto_real
                        if punto_real == mp:
                            return partes[2].lower()
                        elif punto_real.startswith(mp + os.sep) and len(mp) > len(mejor_coincidencia):
                            mejor_coincidencia = mp
                            mejor_fstype = partes[2].lower()
            if mejor_fstype != "desconocido":
                return mejor_fstype
    except Exception as e:
        logger.debug(f"No se pudo consultar /proc/mounts para {punto_montaje}: {e}")

    return "desconocido"


def obtener_espacio_disco(ruta: str) -> Dict[str, int]:
    """
    Retorna el espacio en disco total, usado y libre en bytes para la ruta dada.
    """
    try:
        uso = shutil.disk_usage(ruta)
        return {
            "total": int(uso.total),
            "usado": int(uso.used),
            "libre": int(uso.free)
        }
    except Exception as e:
        logger.warning(f"No se pudo obtener uso de disco para '{ruta}': {e}")
        return {"total": 0, "usado": 0, "libre": 0}


def buscar_puntos_montaje_candidatos(config: Any = None,
                                     rutas_candidatas: Optional[List[str]] = None) -> List[str]:
    """
    Localiza posibles puntos de montaje de pendrives en el sistema según el SO y configuración.
    """
    candidatos: List[str] = []

    # 1. Rutas configuradas explícitamente (para tests o montajes personalizados)
    rutas_cfg = getattr(config, "rutas_candidatas_pendrive", None) or rutas_candidatas
    if rutas_cfg:
        for r in rutas_cfg:
            if r and os.path.isdir(r):
                candidatos.append(os.path.realpath(r))

    # 2. Linux / POSIX: puntos de montaje habituales
    if os.name == "posix":
        patrones = [
            "/media/*/*",
            "/run/media/*/*",
            "/mnt/*"
        ]
        for pat in patrones:
            for p in glob.glob(pat):
                if os.path.isdir(p):
                    candidatos.append(os.path.realpath(p))

        # Pista: /run/media/$USER/MIUNIDAD o /media/$USER/MIUNIDAD
        usuario_actual = os.environ.get("USER", "")
        if usuario_actual:
            pista_run = f"/run/media/{usuario_actual}/MIUNIDAD"
            if os.path.isdir(pista_run):
                candidatos.append(os.path.realpath(pista_run))
            pista_media = f"/media/{usuario_actual}/MIUNIDAD"
            if os.path.isdir(pista_media):
                candidatos.append(os.path.realpath(pista_media))

        # También revisar /proc/mounts por si hay montajes en /media o /run/media
        if os.path.exists("/proc/mounts"):
            try:
                with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
                    for linea in f:
                        partes = linea.strip().split()
                        if len(partes) >= 2:
                            mp = partes[1]
                            if mp.startswith("/media/") or mp.startswith("/run/media/"):
                                if os.path.isdir(mp):
                                    candidatos.append(os.path.realpath(mp))
            except Exception:
                pass

    # 3. Windows: letras de unidad A:\ a Z:\
    elif os.name == "nt":
        for letra in string.ascii_uppercase:
            unidad = f"{letra}:\\"
            if os.path.exists(unidad) and os.path.isdir(unidad):
                candidatos.append(os.path.realpath(unidad))

    # Deduplicar manteniendo orden
    vistos = set()
    resultado: List[str] = []
    for c in candidatos:
        if c not in vistos:
            vistos.add(c)
            resultado.append(c)

    return resultado


def ejecutar_con_timeout(func, *args, timeout_segundos: float = 3.0, **kwargs) -> Any:
    """
    Ejecuta cualquier función potencialmente bloqueante (lecturas de pendrive)
    en un hilo de ThreadPoolExecutor con un tiempo límite estricto de timeout_segundos.
    Si el pendrive o la llamada no responde, retorna un diccionario con
    conectado=False, sin_respuesta=True y error="Pendrive sin respuesta".
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_segundos)
        except concurrent.futures.TimeoutError:
            logger.warning(f"Timeout al ejecutar {getattr(func, '__name__', str(func))} en pendrive ({timeout_segundos}s)")
            return {
                "conectado": False,
                "sin_respuesta": True,
                "error": "Pendrive sin respuesta"
            }
        except Exception as e:
            logger.error(f"Error al ejecutar {getattr(func, '__name__', str(func))} en pendrive: {e}")
            return {
                "conectado": False,
                "sin_respuesta": False,
                "error": str(e)
            }


def notificar_escritorio(titulo: str, mensaje: str):
    """Emite una notificación de escritorio si notify-send está disponible en el sistema."""
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", titulo, mensaje],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        except Exception:
            pass
