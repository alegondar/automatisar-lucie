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


def obtener_ruta_descargas_windows() -> str:
    """
    Resuelve la carpeta de descargas real del usuario en Windows mediante SHGetKnownFolderPath (FOLDERID_Downloads).
    En caso de error o entorno sin soporte, utiliza como respaldo %USERPROFILE%\\Downloads.
    """
    respaldo = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Downloads")
    if os.name != "nt":
        return respaldo

    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8)
            ]

        # FOLDERID_Downloads: {374DE290-123F-4565-9164-39C4925E467B}
        FOLDERID_Downloads = GUID(
            0x374DE290, 0x123F, 0x4565,
            (wintypes.BYTE * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B)
        )

        windll = getattr(ctypes, "windll", None)
        if not windll:
            return respaldo

        SHGetKnownFolderPath = windll.shell32.SHGetKnownFolderPath
        SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.LPWSTR)
        ]
        SHGetKnownFolderPath.restype = ctypes.c_long

        CoTaskMemFree = windll.ole32.CoTaskMemFree
        CoTaskMemFree.argtypes = [wintypes.LPVOID]
        CoTaskMemFree.restype = None

        path_ptr = wintypes.LPWSTR()
        hr = SHGetKnownFolderPath(ctypes.byref(FOLDERID_Downloads), 0, None, ctypes.byref(path_ptr))
        if hr == 0 and path_ptr.value:
            res = str(path_ptr.value)
            CoTaskMemFree(path_ptr)
            return res
    except Exception as e:
        logger.debug(f"Error al invocar SHGetKnownFolderPath: {e}")

    return respaldo


def obtener_ruta_descargas_defecto() -> str:
    """Retorna la ruta por defecto a la carpeta de descargas del usuario según la plataforma."""
    if os.name == "nt":
        return obtener_ruta_descargas_windows()

    ruta_usuario = os.path.expanduser("~/Descargas")
    if os.path.isdir(ruta_usuario):
        return ruta_usuario
    ruta_en = os.path.expanduser("~/Downloads")
    if os.path.isdir(ruta_en):
        return ruta_en
    return ruta_usuario


def obtener_ruta_exportacion_capcut() -> str:
    """
    Retorna la ruta por defecto a la carpeta de exportaciones de CapCut según plataforma.
    En Windows: %LOCALAPPDATA%\\CapCut\\Videos (o %USERPROFILE%\\AppData\\Local\\CapCut\\Videos).
    En otros entornos: ruta bajo XDG_DATA_HOME o ~/.local/share/CapCut/Videos.
    """
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA")
        if not local_app:
            user_prof = os.environ.get("USERPROFILE", os.path.expanduser("~"))
            local_app = os.path.join(user_prof, "AppData", "Local")
        return os.path.join(local_app, "CapCut", "Videos")

    base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, "CapCut", "Videos")


def verificar_archivo_exclusivo(ruta: str) -> bool:
    """
    Verifica si un archivo se puede abrir de forma exclusiva o sin bloqueos de escritura activos.
    Retorna True si el archivo está libre y completo, False si está en uso, bloqueado o inaccesible.
    """
    if not ruta or not os.path.isfile(ruta):
        return False
    try:
        modo = "r+b" if os.access(ruta, os.W_OK) else "rb"
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            # Mantener la apertura Python bajo la guardia hermetica de tests.
            with open(ruta, "rb"):
                pass
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            crear_archivo = kernel32.CreateFileW
            crear_archivo.argtypes = (
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
            )
            crear_archivo.restype = wintypes.HANDLE
            cerrar_handle = kernel32.CloseHandle
            cerrar_handle.argtypes = (wintypes.HANDLE,)
            cerrar_handle.restype = wintypes.BOOL
            # GENERIC_READ, sin comparticion, OPEN_EXISTING: nunca crea ni pisa.
            # Un bloqueo de bytes msvcrt no detecta escritores sin bloqueo explicito.
            handle = crear_archivo(os.fspath(ruta), 0x80000000, 0, None, 3, 0x80, None)
            if handle == wintypes.HANDLE(-1).value:
                return False
            try:
                return True
            finally:
                cerrar_handle(handle)
        else:
            import fcntl
            with open(ruta, modo) as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    return True
                except (OSError, IOError, PermissionError):
                    return False
    except (PermissionError, OSError, IOError):
        return False



def obtener_ruta_destino_defecto() -> str:
    """Retorna la ruta de destino base por defecto (~/Descargas/_lucie)."""
    return os.path.join(obtener_ruta_descargas_defecto(), "_lucie")


def esta_confinado_en_raiz(ruta: str, raiz: str) -> bool:
    """
    Verifica de manera canónica y segura si 'ruta' reside estrictamente dentro de 'raiz'.
    Utiliza os.path.realpath para resolver enlaces simbólicos y evasiones ('..'),
    os.path.normcase para insensibilidad a mayúsculas/minúsculas en Windows, y
    os.path.commonpath para evitar colisiones de prefijo parcial.
    Rechaza rutas en letras de unidad distintas o rutas UNC fuera del árbol.
    """
    if not ruta or not raiz:
        return False
    try:
        if os.name == "posix":
            import re
            if re.match(r"^[a-zA-Z]:", str(ruta)) or str(ruta).startswith("\\\\"):
                return False
        real_ruta = os.path.normcase(os.path.realpath(ruta))
        real_raiz = os.path.normcase(os.path.realpath(raiz))
        return os.path.commonpath([real_ruta, real_raiz]) == real_raiz
    except (ValueError, OSError):
        return False


def validar_longitud_ruta(ruta: str, max_longitud: int = 260) -> bool:
    """Verifica si la ruta excede el límite de 260 caracteres (MAX_PATH en Windows)."""
    if not ruta:
        return True
    try:
        return len(os.path.abspath(ruta)) < max_longitud
    except Exception:
        return len(str(ruta)) < max_longitud
def normalizar_ruta_relativa_posix(ruta_relativa: str) -> str:
    """
    Normaliza una ruta relativa a formato POSIX con '/' (compatible con as_posix).
    Elimina barras iniciales o finales redundantes y reemplaza separadores '\\' de Windows.
    """
    if not ruta_relativa:
        return ""
    s = str(ruta_relativa).replace("\\", "/").strip()
    partes = [p for p in s.split("/") if p and p != "."]
    return "/".join(partes)


def convertir_ruta_relativa_a_local(ruta_relativa: str) -> str:
    """
    Convierte de forma segura una ruta relativa con '/' o '\\' a la convención
    de ruta local del sistema operativo anfitrión (utilizando os.sep).
    Previene traversals ('..') y componentes absolutos.
    """
    if not ruta_relativa:
        return ""
    s = str(ruta_relativa).replace("\\", "/").strip()
    partes = [p for p in s.split("/") if p and p != "." and p != ".."]
    if not partes:
        return ""
    return os.path.join(*partes)



def obtener_sistema_archivos_windows(unidad: str) -> str:
    """
    Consulta el sistema de archivos de un volumen en Windows utilizando GetVolumeInformationW (ctypes).
    Retorna el nombre en minúsculas (ej. 'exfat', 'fat32', 'ntfs') o 'desconocido'.
    """
    try:
        import ctypes
        from ctypes import wintypes

        # Normalizar a raíz con barra final ("D:\\")
        drive, _ = os.path.splitdrive(os.path.abspath(unidad))
        raiz = (drive + "\\") if drive else (unidad if unidad.endswith("\\") else unidad + "\\")

        windll = getattr(ctypes, "windll", None)
        if not windll or not hasattr(windll, "kernel32"):
            return "desconocido"

        k32 = windll.kernel32
        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOOPENFILEERRORBOX = 0x8000
        modo_previo = k32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX)
        try:
            fs_name_buffer = ctypes.create_unicode_buffer(261)
            vol_name_buffer = ctypes.create_unicode_buffer(261)
            serial_num = wintypes.DWORD()
            max_component_len = wintypes.DWORD()
            fs_flags = wintypes.DWORD()

            res = k32.GetVolumeInformationW(
                ctypes.c_wchar_p(raiz),
                vol_name_buffer,
                ctypes.sizeof(vol_name_buffer),
                ctypes.byref(serial_num),
                ctypes.byref(max_component_len),
                ctypes.byref(fs_flags),
                fs_name_buffer,
                ctypes.sizeof(fs_name_buffer)
            )
            if res != 0 and fs_name_buffer.value:
                return fs_name_buffer.value.strip().lower()
        finally:
            k32.SetErrorMode(modo_previo)
    except Exception as e:
        logger.debug(f"Error al consultar sistema de archivos en Windows para '{unidad}': {e}")

    return "desconocido"


def obtener_unidades_windows() -> List[Dict[str, Any]]:
    """
    Enumera las unidades de disco en Windows mediante GetLogicalDrives y GetDriveTypeW (ctypes),
    aplicando SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX) para evitar diálogos modales.
    Retorna una lista de diccionarios con info de cada unidad.
    """
    unidades: List[Dict[str, Any]] = []
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if not windll or not hasattr(windll, "kernel32"):
            for letra in string.ascii_uppercase:
                u = f"{letra}:\\"
                if os.path.exists(u):
                    unidades.append({"letra": letra, "unidad": u, "tipo": "desconocido", "tipo_codigo": 0})
            return unidades

        k32 = windll.kernel32
        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOOPENFILEERRORBOX = 0x8000
        modo_previo = k32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX)
        try:
            bitmask = k32.GetLogicalDrives()
            tipos_nombre = {
                0: "desconocido",
                1: "sin_raiz",
                2: "removible",
                3: "fija",
                4: "red",
                5: "cdrom",
                6: "ramdisk"
            }
            for i in range(26):
                if bitmask & (1 << i):
                    letra = chr(ord('A') + i)
                    raiz = f"{letra}:\\"
                    tipo_codigo = k32.GetDriveTypeW(ctypes.c_wchar_p(raiz))
                    unidades.append({
                        "letra": letra,
                        "unidad": raiz,
                        "tipo": tipos_nombre.get(tipo_codigo, "desconocido"),
                        "tipo_codigo": tipo_codigo
                    })
        finally:
            k32.SetErrorMode(modo_previo)
    except Exception as e:
        logger.debug(f"Error al enumerar unidades con ctypes en Windows: {e}")
        for letra in string.ascii_uppercase:
            u = f"{letra}:\\"
            if os.path.exists(u):
                unidades.append({"letra": letra, "unidad": u, "tipo": "desconocido", "tipo_codigo": 0})

    return unidades


def obtener_sistema_archivos(punto_montaje: str) -> str:
    """
    Determina el sistema de archivos del punto de montaje especificado.
    En Linux consulta /proc/mounts.
    En Windows consulta GetVolumeInformationW vía ctypes.
    Si no está disponible o falla, retorna 'desconocido'.
    """
    if os.name == "nt":
        return obtener_sistema_archivos_windows(punto_montaje)

    try:
        punto_real = os.path.realpath(punto_montaje)
        if os.name == "posix" and os.path.exists("/proc/mounts"):
            mejor_coincidencia = ""
            mejor_fstype = "desconocido"
            with open("/proc/mounts", "r", encoding="utf-8", errors="replace", newline="\n") as f:
                for linea in f:
                    partes = linea.strip().split()
                    if len(partes) >= 3:
                        mp = os.path.realpath(partes[1])
                        # Coincidencia exacta o la más larga que contenga punto_real
                        if punto_real == mp:
                            return partes[2].lower()
                        elif esta_confinado_en_raiz(punto_real, mp) and len(mp) > len(mejor_coincidencia):
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
        return list(dict.fromkeys(candidatos))

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

        # También revisar particiones removibles montadas detectadas por sysfs
        try:
            particiones_rem = detectar_particiones_removibles_linux()
            for part in particiones_rem:
                if part.get("montado") and part.get("punto_montaje"):
                    mp = part["punto_montaje"]
                    if os.path.isdir(mp):
                        candidatos.append(os.path.realpath(mp))
        except Exception:
            pass

        # También revisar /proc/mounts por si hay montajes en /media o /run/media
        if os.path.exists("/proc/mounts"):
            try:
                with open("/proc/mounts", "r", encoding="utf-8", errors="replace", newline="\n") as f:
                    for linea in f:
                        partes = linea.strip().split()
                        if len(partes) >= 2:
                            mp = partes[1]
                            if mp.startswith("/media/") or mp.startswith("/run/media/"):
                                if os.path.isdir(mp):
                                    candidatos.append(os.path.realpath(mp))
            except Exception:
                pass

    # 3. Windows: unidades lógicas detectadas con GetLogicalDrives / GetDriveTypeW
    elif os.name == "nt":
        unidades_win = obtener_unidades_windows()
        for u_info in unidades_win:
            raiz_u = u_info["unidad"]
            if os.path.exists(raiz_u) and os.path.isdir(raiz_u):
                candidatos.append(os.path.realpath(raiz_u))

    # Deduplicar manteniendo orden
    vistos = set()
    resultado: List[str] = []
    for c in candidatos:
        if c not in vistos:
            vistos.add(c)
            resultado.append(c)

    # Ordenar priorizando la pista de etiqueta si fue provista en la configuración
    etiqueta_pista = getattr(config, "etiqueta_pendrive_pista", None)
    if etiqueta_pista:
        pista_upper = str(etiqueta_pista).strip().upper()
        resultado.sort(key=lambda c: 0 if os.path.basename(os.path.normpath(c)).upper() == pista_upper else 1)

    return resultado


def formatear_bytes_tam(num_bytes: int) -> str:
    """Formatea bytes a representación legible (B, KB, MB, GB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024**2:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024**3:
        return f"{num_bytes / (1024**2):.1f} MB"
    else:
        return f"{num_bytes / (1024**3):.1f} GB"


def _parsear_montajes_linux(proc_dir: str = "/proc") -> Dict[str, Dict[str, Any]]:
    """
    Lee /proc/self/mountinfo y /proc/mounts.
    Retorna un diccionario indexado por dispositivo fuente, maj_min y realpath
    con información de punto de montaje y tipo de filesystem.
    Reconoce montajes FUSE (fuse, fuseblk, ntfs-3g, exfat-fuse).
    """
    montajes: Dict[str, Dict[str, Any]] = {}

    # 1. /proc/self/mountinfo
    mountinfo_path = os.path.join(proc_dir, "self", "mountinfo")
    if os.path.exists(mountinfo_path):
        try:
            with open(mountinfo_path, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                for linea in f:
                    partes = linea.strip().split()
                    if len(partes) >= 7 and " - " in linea:
                        idx_sep = partes.index("-")
                        if idx_sep + 2 < len(partes):
                            fstype = partes[idx_sep + 1].lower()
                            source = partes[idx_sep + 2]
                            mountpoint = partes[4]
                            maj_min = partes[2]
                            es_fuse = any(x in fstype for x in ("fuse", "fuseblk", "ntfs-3g", "exfat-fuse"))
                            info = {
                                "punto_montaje": mountpoint,
                                "sistema_archivos": fstype,
                                "dispositivo_fuente": source,
                                "es_fuse": es_fuse,
                                "maj_min": maj_min
                            }
                            montajes[maj_min] = info
                            montajes[source] = info
                            try:
                                montajes[os.path.realpath(source)] = info
                            except Exception:
                                pass
        except Exception as e:
            logger.debug(f"Error al leer mountinfo en {mountinfo_path}: {e}")

    # 2. /proc/mounts (complementario)
    mounts_path = os.path.join(proc_dir, "mounts")
    if os.path.exists(mounts_path):
        try:
            with open(mounts_path, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                for linea in f:
                    partes = linea.strip().split()
                    if len(partes) >= 3:
                        source = partes[0]
                        mountpoint = partes[1]
                        fstype = partes[2].lower()
                        es_fuse = any(x in fstype for x in ("fuse", "fuseblk", "ntfs-3g", "exfat-fuse"))
                        info = {
                            "punto_montaje": mountpoint,
                            "sistema_archivos": fstype,
                            "dispositivo_fuente": source,
                            "es_fuse": es_fuse
                        }
                        if source not in montajes:
                            montajes[source] = info
                        try:
                            rp = os.path.realpath(source)
                            if rp not in montajes:
                                montajes[rp] = info
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"Error al leer mounts en {mounts_path}: {e}")

    return montajes


def _parsear_etiquetas_por_label(dev_dir: str = "/dev") -> Dict[str, str]:
    """
    Lee /dev/disk/by-label y mapea cada ruta de dispositivo real a su etiqueta.
    """
    etiquetas: Dict[str, str] = {}
    by_label_dir = os.path.join(dev_dir, "disk", "by-label")
    if os.path.isdir(by_label_dir):
        try:
            for nombre_etiqueta in os.listdir(by_label_dir):
                ruta_symlink = os.path.join(by_label_dir, nombre_etiqueta)
                try:
                    destino_real = os.path.realpath(ruta_symlink)
                    etiquetas[destino_real] = nombre_etiqueta
                    etiquetas[os.path.basename(destino_real)] = nombre_etiqueta
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Error al leer etiquetas en {by_label_dir}: {e}")
    return etiquetas


def _leer_info_udev_bloque(maj_min: str, udev_dir: str = "/run/udev/data") -> Dict[str, str]:
    """
    Lee /run/udev/data/b<major>:<minor> si existe para extraer ID_FS_TYPE, ID_FS_LABEL, ID_MODEL.
    """
    res: Dict[str, str] = {}
    if not udev_dir or not os.path.isdir(udev_dir) or not maj_min:
        return res
    archivo = os.path.join(udev_dir, f"b{maj_min}")
    if os.path.isfile(archivo):
        try:
            with open(archivo, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                for linea in f:
                    linea_strip = linea.strip()
                    if linea_strip.startswith("E:ID_FS_TYPE="):
                        res["fs_type"] = linea_strip.split("=", 1)[1].lower()
                    elif linea_strip.startswith("E:ID_FS_LABEL="):
                        res["fs_label"] = linea_strip.split("=", 1)[1]
                    elif linea_strip.startswith("E:ID_MODEL="):
                        res["model"] = linea_strip.split("=", 1)[1].replace("_", " ").strip()
        except Exception:
            pass
    return res


def detectar_particiones_removibles_linux(sys_dir: str = "/sys",
                                         proc_dir: str = "/proc",
                                         dev_dir: str = "/dev",
                                         udev_dir: str = "/run/udev/data",
                                         etiqueta_pista: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Detecta particiones pertenecientes a dispositivos de bloque removibles (/sys/block/*/removable == 1)
    en Linux, tanto montadas como sin montar, sin usar subprocess.
    """
    if os.name != "posix" or not os.path.isdir(sys_dir):
        return []

    montajes = _parsear_montajes_linux(proc_dir)
    etiquetas = _parsear_etiquetas_por_label(dev_dir)

    sys_block = os.path.join(sys_dir, "block")
    if not os.path.isdir(sys_block):
        return []

    particiones_removibles: List[Dict[str, Any]] = []

    try:
        discos = sorted(os.listdir(sys_block))
    except Exception:
        return []

    for disco in discos:
        if disco.startswith(("loop", "ram", "zram")):
            continue

        disco_dir = os.path.join(sys_block, disco)
        removable_path = os.path.join(disco_dir, "removable")
        es_removible = False

        if os.path.isfile(removable_path):
            try:
                with open(removable_path, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                    es_removible = (f.read().strip() == "1")
            except Exception:
                pass

        if not es_removible:
            continue

        candidatos_nodos = []
        try:
            for item in os.listdir(disco_dir):
                item_path = os.path.join(disco_dir, item)
                if os.path.isdir(item_path):
                    part_file = os.path.join(item_path, "partition")
                    if os.path.isfile(part_file) or (item.startswith(disco) and os.path.isfile(os.path.join(item_path, "size"))):
                        candidatos_nodos.append(item)
        except Exception:
            pass

        if not candidatos_nodos:
            candidatos_nodos = [disco]

        for nodo in sorted(candidatos_nodos):
            nodo_dir = os.path.join(disco_dir, nodo) if nodo != disco else disco_dir
            disp_path = f"/dev/{nodo}"

            tam_bytes = 0
            size_path = os.path.join(nodo_dir, "size")
            if os.path.isfile(size_path):
                try:
                    with open(size_path, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                        tam_bytes = int(f.read().strip()) * 512
                except Exception:
                    pass

            maj_min = ""
            dev_file = os.path.join(nodo_dir, "dev")
            if os.path.isfile(dev_file):
                try:
                    with open(dev_file, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                        maj_min = f.read().strip()
                except Exception:
                    pass

            udev_info = _leer_info_udev_bloque(maj_min, udev_dir)
            etiqueta = etiquetas.get(disp_path) or etiquetas.get(nodo) or udev_info.get("fs_label", "")

            info_montaje = montajes.get(disp_path) or montajes.get(maj_min) or montajes.get(nodo)
            montado = bool(info_montaje)
            punto_montaje = info_montaje.get("punto_montaje") if info_montaje else None

            if info_montaje and info_montaje.get("sistema_archivos") and not info_montaje.get("es_fuse"):
                fs = info_montaje["sistema_archivos"]
            elif udev_info.get("fs_type"):
                fs = udev_info["fs_type"]
            elif info_montaje:
                fs = info_montaje.get("sistema_archivos", "desconocido")
            else:
                fs = "desconocido"

            disco_padre = f"/dev/{disco}"

            particiones_removibles.append({
                "dispositivo": disp_path,
                "nodo": nodo,
                "disco_padre": disco_padre,
                "nodo_padre": disco,
                "removible": True,
                "montado": montado,
                "punto_montaje": punto_montaje,
                "etiqueta": etiqueta,
                "sistema_archivos": fs,
                "tamanio_bytes": tam_bytes,
                "tamanio_fmt": formatear_bytes_tam(tam_bytes),
                "es_fuse": info_montaje.get("es_fuse", False) if info_montaje else False,
                "modelo": udev_info.get("model", "")
            })

    # Prioridad: etiqueta de pista al principio si coincide
    pista_upper = str(etiqueta_pista).strip().upper() if etiqueta_pista else None
    particiones_removibles.sort(
        key=lambda x: (
            0 if (pista_upper and (x.get("etiqueta") or "").upper() == pista_upper) else 1,
            x["dispositivo"]
        )
    )

    return particiones_removibles


def diagnosticar_todas_particiones_linux(sys_dir: str = "/sys",
                                         proc_dir: str = "/proc",
                                         dev_dir: str = "/dev",
                                         udev_dir: str = "/run/udev/data") -> List[Dict[str, Any]]:
    """
    Evalúa todas las particiones del sistema y retorna diagnóstico para
    el bloque '¿Por qué no veo mi pendrive?'.
    """
    if os.name != "posix" or not os.path.isdir(sys_dir):
        return []

    montajes = _parsear_montajes_linux(proc_dir)
    etiquetas = _parsear_etiquetas_por_label(dev_dir)

    sys_block = os.path.join(sys_dir, "block")
    if not os.path.isdir(sys_block):
        return []

    diagnostico: List[Dict[str, Any]] = []

    try:
        discos = sorted(os.listdir(sys_block))
    except Exception:
        return []

    for disco in discos:
        if disco.startswith(("loop", "ram", "zram")):
            continue

        disco_dir = os.path.join(sys_block, disco)
        removable_path = os.path.join(disco_dir, "removable")
        es_removible = False

        if os.path.isfile(removable_path):
            try:
                with open(removable_path, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                    es_removible = (f.read().strip() == "1")
            except Exception:
                pass

        candidatos = []
        try:
            for item in os.listdir(disco_dir):
                item_path = os.path.join(disco_dir, item)
                if os.path.isdir(item_path):
                    part_file = os.path.join(item_path, "partition")
                    if os.path.isfile(part_file) or (item.startswith(disco) and os.path.isfile(os.path.join(item_path, "size"))):
                        candidatos.append(item)
        except Exception:
            pass

        if not candidatos:
            candidatos = [disco]

        for nodo in sorted(candidatos):
            nodo_dir = os.path.join(disco_dir, nodo) if nodo != disco else disco_dir
            disp_path = f"/dev/{nodo}"

            tam_bytes = 0
            size_path = os.path.join(nodo_dir, "size")
            if os.path.isfile(size_path):
                try:
                    with open(size_path, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                        tam_bytes = int(f.read().strip()) * 512
                except Exception:
                    pass

            maj_min = ""
            dev_file = os.path.join(nodo_dir, "dev")
            if os.path.isfile(dev_file):
                try:
                    with open(dev_file, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                        maj_min = f.read().strip()
                except Exception:
                    pass

            udev_info = _leer_info_udev_bloque(maj_min, udev_dir)
            etiqueta = etiquetas.get(disp_path) or etiquetas.get(nodo) or udev_info.get("fs_label", "")

            info_montaje = montajes.get(disp_path) or montajes.get(maj_min) or montajes.get(nodo)
            montado = bool(info_montaje)
            punto_montaje = info_montaje.get("punto_montaje") if info_montaje else None

            fs = udev_info.get("fs_type") or (info_montaje.get("sistema_archivos") if info_montaje else "desconocido")

            if not es_removible:
                motivo = "Disco interno (no removible)"
            elif not montado:
                motivo = "Unidad removible detectada pero no montada"
            else:
                motivo = "Unidad removible montada"

            diagnostico.append({
                "dispositivo": disp_path,
                "nodo": nodo,
                "removible": es_removible,
                "montado": montado,
                "punto_montaje": punto_montaje,
                "etiqueta": etiqueta,
                "sistema_archivos": fs,
                "tamanio_bytes": tam_bytes,
                "tamanio_fmt": formatear_bytes_tam(tam_bytes),
                "motivo": motivo
            })

    return diagnostico


def obtener_disco_padre_particion(dispositivo: str, sys_dir: str = "/sys") -> str:
    """
    Resuelve el disco físico padre de una partición (ej: /dev/sda1 -> /dev/sda, nvme0n1p1 -> /dev/nvme0n1).
    Utiliza sysfs (/sys/class/block/<nodo>) y resolución de directorios sin subprocess.
    """
    if not dispositivo:
        return ""
    nodo = os.path.basename(dispositivo)
    nodo_block_path = os.path.join(sys_dir, "class", "block", nodo)
    if os.path.exists(nodo_block_path):
        try:
            ruta_real = os.path.realpath(nodo_block_path)
            padre_nombre = os.path.basename(os.path.dirname(ruta_real))
            if padre_nombre and padre_nombre != "block":
                return f"/dev/{padre_nombre}"
        except Exception:
            pass

    import re
    m_nvme = re.match(r"^(/dev/nvme\d+n\d+)p\d+$", dispositivo)
    if m_nvme:
        return m_nvme.group(1)
    m = re.match(r"^(/dev/[a-zA-Z]+)\d+$", dispositivo)
    if m:
        return m.group(1)
    return dispositivo


def listar_procesos_ocupando_montaje(punto_montaje: str, proc_dir: str = "/proc") -> List[Dict[str, Any]]:
    """
    Escanea /proc/*/cwd y /proc/*/fd para identificar qué procesos del usuario
    tienen directorios de trabajo o descriptores abiertos dentro de punto_montaje.
    No requiere privilegios de superusuario para procesos del usuario actual.
    """
    if not punto_montaje or not os.path.exists(punto_montaje):
        return []

    punto_real = os.path.realpath(punto_montaje)
    procesos_dict: Dict[int, Dict[str, Any]] = {}

    if not os.path.isdir(proc_dir):
        return []

    try:
        pids = [p for p in os.listdir(proc_dir) if p.isdigit()]
    except Exception:
        return []

    for p_str in pids:
        pid = int(p_str)
        p_dir = os.path.join(proc_dir, p_str)

        retiene = False
        detalle_retencion = ""

        cwd_link = os.path.join(p_dir, "cwd")
        try:
            cwd_dest = os.path.realpath(cwd_link)
            if esta_confinado_en_raiz(cwd_dest, punto_real):
                retiene = True
                detalle_retencion = f"CWD en {cwd_dest}"
        except (PermissionError, FileNotFoundError, OSError):
            pass

        if not retiene:
            fd_dir = os.path.join(p_dir, "fd")
            if os.path.isdir(fd_dir):
                try:
                    for fd_name in os.listdir(fd_dir):
                        fd_link = os.path.join(fd_dir, fd_name)
                        try:
                            fd_dest = os.path.realpath(fd_link)
                            if esta_confinado_en_raiz(fd_dest, punto_real):
                                retiene = True
                                detalle_retencion = f"Archivo abierto en {fd_dest}"
                                break
                        except (PermissionError, FileNotFoundError, OSError):
                            pass
                except (PermissionError, FileNotFoundError, OSError):
                    pass

        if retiene:
            comm = ""
            comm_file = os.path.join(p_dir, "comm")
            try:
                with open(comm_file, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                    comm = f.read().strip()
            except Exception:
                pass

            cmdline = ""
            cmdline_file = os.path.join(p_dir, "cmdline")
            try:
                with open(cmdline_file, "r", encoding="utf-8", errors="replace", newline="\n") as f:
                    cmdline = f.read().replace("\x00", " ").strip()
            except Exception:
                pass

            procesos_dict[pid] = {
                "pid": pid,
                "nombre": comm or f"proceso_{pid}",
                "comando": cmdline or comm,
                "detalle": detalle_retencion
            }

    return list(procesos_dict.values())


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
