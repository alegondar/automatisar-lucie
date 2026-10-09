#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inventario_pendrive.py

Script de auditoría e inventario integral para unidades de almacenamiento (pendrives/USB).
- Controla TODO el contenido del pendrive partiendo de --raiz.
- Confinamiento estricto: resuelve con realpath y rechaza symlinks/rutas que apunten afuera.
- Ignora carpetas de sistema (System Volume Information, $RECYCLE.BIN, .Trash-*, lost+found).
- Ignora archivos/carpetas ocultos (con opción --incluir-ocultos para verlos).
- Clasifica por extensión: video, foto, audio, documento, subtítulo, otro.
- Duración mediante ffprobe (exclusivamente para videos).
- Resumen por carpeta de primer nivel (archivos, peso, desglose por tipo y duración).
- Capacidad total del pendrive vs espacio usado y archivos escaneados.
- Duplicados en TODO el pendrive (detección global y cross-carpeta por SHA-256).
- Detección de carpetas vacías y carpetas aparentemente duplicadas (por contenido y nombre).
- Detección de archivos sueltos en la raíz y en la raíz de cada carpeta de primer nivel.
- GARANTÍA DE SOLO LECTURA: no escribe nada en el pendrive.
  Cualquier caché se almacena en el repositorio local.
"""

import os
import sys
import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ==============================================================================
# CONSTANTES Y CONFIGURACIÓN
# ==============================================================================

CARPETAS_SISTEMA_EXCLUIDAS = {
    'system volume information',
    '$recycle.bin',
    'lost+found'
}

PATRONES_CARPETAS_SISTEMA = [
    '.trash-*',
    '.spotlight-*',
    '.fseventsd'
]

EXTENSIONES_CATEGORIA: Dict[str, Set[str]] = {
    'video': {
        '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v',
        '.ts', '.mpg', '.mpeg', '.3gp', '.vob', '.ogv', '.mts', '.m2ts',
        '.asf', '.f4v', '.rm', '.rmvb', '.divx'
    },
    'foto': {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
        '.svg', '.raw', '.heic', '.heif', '.ico', '.cr2', '.nef', '.arw',
        '.dng', '.psd', '.ai', '.eps'
    },
    'audio': {
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma', '.opus',
        '.aiff', '.alac', '.mid', '.midi', '.ac3', '.mka'
    },
    'documento': {
        '.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt', '.xls', '.xlsx',
        '.ppt', '.pptx', '.csv', '.tsv', '.md', '.log', '.epub', '.mobi',
        '.html', '.htm', '.xml', '.json', '.yaml', '.yml', '.cfg', '.ini',
        '.inf', '.kdbx', '.tex', '.sh', '.py', '.js', '.ts', '.css', '.c',
        '.cpp', '.h', '.java', '.sql', '.conf', '.env'
    },
    'subtítulo': {
        '.srt', '.vtt', '.ass', '.ssa', '.sub', '.sbv', '.idx', '.smi'
    }
}

BUFFER_HASH_BYTES = 1024 * 1024  # 1 MB para lectura en streaming


# ==============================================================================
# MODELOS DE DATOS
# ==============================================================================

@dataclass
class ArchivoInfo:
    ruta_relativa: str
    ruta_absoluta: str
    nombre: str
    tamanio_bytes: int
    mtime: float
    categoria: str
    extension: str
    carpeta_primer_nivel: str  # "" si está en la raíz
    es_suelto_raiz: bool
    es_suelto_primer_nivel: bool
    sha256: Optional[str] = None
    duracion_segundos: Optional[float] = None


@dataclass
class ResumenCategoria:
    cantidad: int = 0
    tamanio_bytes: int = 0
    duracion_segundos: float = 0.0


@dataclass
class ResumenCarpeta:
    nombre: str
    total_archivos: int = 0
    total_bytes: int = 0
    duracion_video_segundos: float = 0.0
    desglose: Dict[str, ResumenCategoria] = field(default_factory=dict)
    archivos_sueltos_count: int = 0
    archivos_sueltos: List[str] = field(default_factory=list)


# ==============================================================================
# UTILIDADES DE FORMATO
# ==============================================================================

def formatear_bytes(tamanio: int) -> str:
    """Convierte bytes a formato legible (B, KB, MB, GB, TB)."""
    if tamanio < 0:
        return "0 B"
    unidades = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    valor = float(tamanio)
    idx = 0
    while valor >= 1024.0 and idx < len(unidades) - 1:
        valor /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(valor)} B"
    return f"{valor:.2f} {unidades[idx]}"


def formatear_duracion(segundos: Optional[float]) -> str:
    """Convierte segundos a formato HH:MM:SS o mm:ss."""
    if segundos is None or segundos <= 0:
        return "00:00"
    total_s = int(round(segundos))
    horas = total_s // 3600
    minutos = (total_s % 3600) // 60
    segs = total_s % 60
    if horas > 0:
        return f"{horas:02d}:{minutos:02d}:{segs:02d}"
    return f"{minutos:02d}:{segs:02d}"


# ==============================================================================
# SEGURIDAD Y CONFINAMIENTO DE RUTAS
# ==============================================================================

def normalizar_raiz(ruta_raiz: str) -> str:
    """
    Resuelve con realpath y normaliza el punto de montaje.
    Lanza excepción si no existe o no es directorio.
    """
    if not ruta_raiz:
        raise ValueError("La ruta raíz (--raiz) no puede estar vacía.")

    ruta_abs = os.path.abspath(ruta_raiz)
    ruta_real = os.path.realpath(ruta_abs)

    if not os.path.exists(ruta_real):
        raise FileNotFoundError(f"La ruta especificada no existe: '{ruta_raiz}' (resuelta como '{ruta_real}')")

    if not os.path.isdir(ruta_real):
        raise NotADirectoryError(f"La ruta no es un directorio: '{ruta_raiz}' (resuelta como '{ruta_real}')")

    return ruta_real


def esta_dentro_de_raiz(ruta_destino: str, raiz_real: str) -> bool:
    """
    Verifica mediante realpath que la ruta esté estrictamente contenida dentro de la raíz.
    Evita que symlinks apunten fuera del pendrive.
    """
    try:
        destino_real = os.path.realpath(ruta_destino)
        # commonpath lanza ValueError si están en letras de unidad diferentes en Windows
        comun = os.path.commonpath([raiz_real, destino_real])
        return comun == raiz_real
    except (ValueError, OSError):
        return False


# ==============================================================================
# FILTRADO DE SISTEMA Y ELEMENTOS OCULTOS
# ==============================================================================

def es_carpeta_sistema(nombre_dir: str) -> bool:
    """Determina si un directorio es una carpeta de sistema reservada."""
    nombre_lower = nombre_dir.lower()
    if nombre_lower in CARPETAS_SISTEMA_EXCLUIDAS:
        return True
    for patron in PATRONES_CARPETAS_SISTEMA:
        if fnmatch.fnmatch(nombre_lower, patron):
            return True
    return False


def es_elemento_oculto(nombre: str, ruta_completa: str) -> bool:
    """
    Detecta si un archivo o carpeta está oculto (prefijo '.' en Linux/Unix
    o atributo oculto/sistema en Windows).
    """
    if nombre.startswith('.'):
        return True

    # Comprobación de atributos en Windows
    if os.name == 'nt':
        try:
            import ctypes
            atributos = ctypes.windll.kernel32.GetFileAttributesW(ruta_completa)
            # 2 = FILE_ATTRIBUTE_HIDDEN, 4 = FILE_ATTRIBUTE_SYSTEM
            if atributos != -1 and (atributos & 2 or atributos & 4):
                return True
        except Exception:
            pass

    return False


def clasificar_archivo(nombre_archivo: str) -> str:
    """Clasifica el archivo según su extensión."""
    _, ext = os.path.splitext(nombre_archivo)
    ext_lower = ext.lower()
    for cat, exts in EXTENSIONES_CATEGORIA.items():
        if ext_lower in exts:
            return cat
    return 'otro'


# ==============================================================================
# CACHÉ PERSISTENTE LOCAL (EN EL REPOSITORIO, SOLO LECTURA EN PENDRIVE)
# ==============================================================================

class CacheInventario:
    """
    Administra la caché en SQLite local (en el repositorio).
    GARANTÍA: Nunca escribe dentro de la ruta del pendrive.
    """

    def __init__(self, ruta_cache: str, raiz_real: str, desactivar: bool = False):
        self.desactivar = desactivar
        self.raiz_real = raiz_real
        self.ruta_cache = os.path.abspath(ruta_cache)

        # Validación estricta de seguridad: la caché NO puede estar dentro del pendrive
        if esta_dentro_de_raiz(self.ruta_cache, self.raiz_real):
            raise RuntimeError(
                f"Violación de Solo Lectura: La caché '{self.ruta_cache}' "
                f"no puede estar dentro del pendrive '{self.raiz_real}'."
            )

        if not self.desactivar:
            os.makedirs(os.path.dirname(self.ruta_cache), exist_ok=True)
            self._init_db()

    def _conectar_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.ruta_cache, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
        except Exception:
            pass
        return conn

    def _init_db(self):
        conn = self._conectar_db()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_archivos (
                    rel_path TEXT PRIMARY KEY,
                    size_bytes INTEGER,
                    mtime REAL,
                    sha256 TEXT,
                    duration REAL,
                    categoria TEXT,
                    actualizado_en TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def obtener(self, rel_path: str, size_bytes: int, mtime: float) -> Optional[Tuple[Optional[str], Optional[float]]]:
        if self.desactivar:
            return None
        conn = None
        try:
            conn = self._conectar_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sha256, duration, size_bytes, mtime FROM cache_archivos WHERE rel_path = ?",
                (rel_path,)
            )
            row = cursor.fetchone()
            if row:
                c_sha, c_dur, c_size, c_mtime = row
                # Tolerancia de 0.01s para diferencias de precisión de timestamp
                if c_size == size_bytes and abs(c_mtime - mtime) < 0.05:
                    return c_sha, c_dur
        except Exception as e:
            print(f"[!] Error al leer de caché ({rel_path}): {e}", file=sys.stderr)
        finally:
            if conn:
                conn.close()
        return None

    def guardar(self, rel_path: str, size_bytes: int, mtime: float,
                sha256: Optional[str], duration: Optional[float], categoria: str):
        if self.desactivar:
            return
        conn = None
        try:
            conn = self._conectar_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO cache_archivos 
                (rel_path, size_bytes, mtime, sha256, duration, categoria, actualizado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                rel_path, size_bytes, mtime, sha256, duration,
                categoria, datetime.now().isoformat()
            ))
            conn.commit()
        except Exception as e:
            print(f"[!] Error al guardar en caché ({rel_path}): {e}", file=sys.stderr)
        finally:
            if conn:
                conn.close()

    def limpiar(self):
        if os.path.exists(self.ruta_cache):
            conn = None
            try:
                conn = self._conectar_db()
                conn.execute("DELETE FROM cache_archivos")
                conn.commit()
                print(f"[+] Caché vaciada: {self.ruta_cache}")
            except Exception as e:
                print(f"[!] Error al vaciar caché: {e}", file=sys.stderr)
            finally:
                if conn:
                    conn.close()


# ==============================================================================
# EXTRACCIÓN DE DURACIÓN Y CÁLCULO DE HASH
# ==============================================================================

def verificar_ffprobe_instalado() -> bool:
    """Verifica si ffprobe está disponible en el PATH del sistema."""
    return shutil.which("ffprobe") is not None


def obtener_duracion_video(ruta_archivo: str, timeout_segundos: int = 15) -> Optional[float]:
    """
    Obtiene la duración en segundos de un archivo de video mediante ffprobe.
    Aplica exclusivamente a videos.
    """
    if not verificar_ffprobe_instalado():
        return None

    comando = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        ruta_archivo
    ]

    try:
        res = subprocess.run(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_segundos,
            shell=False
        )
        if res.returncode == 0:
            salida = res.stdout.strip()
            if salida and salida != "N/A":
                return float(salida)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def calcular_sha256(ruta_archivo: str) -> Optional[str]:
    """Calcula el hash SHA-256 de un archivo en streaming de solo lectura."""
    hasher = hashlib.sha256()
    try:
        with open(ruta_archivo, 'rb') as f:
            while True:
                bloque = f.read(BUFFER_HASH_BYTES)
                if not bloque:
                    break
                hasher.update(bloque)
        return hasher.hexdigest()
    except (OSError, PermissionError) as e:
        print(f"[!] Error al leer archivo para hash: {ruta_archivo} ({e})", file=sys.stderr)
        return None


# ==============================================================================
# MOTOR PRINCIPAL DE ESCANEO Y ANÁLISIS
# ==============================================================================

class AuditorPendrive:
    """
    Motor de auditoría e inventario del pendrive.
    """

    def __init__(
        self,
        ruta_raiz: str,
        incluir_ocultos: bool = False,
        ruta_cache: Optional[str] = None,
        desactivar_cache: bool = False,
        verboso: bool = False
    ):
        self.raiz_real = normalizar_raiz(ruta_raiz)
        self.incluir_ocultos = incluir_ocultos
        self.verboso = verboso
        self.ffprobe_disponible = verificar_ffprobe_instalado()

        # Determinar directorio del repositorio/script para la caché
        dir_repo = os.path.dirname(os.path.abspath(__file__))
        if not ruta_cache:
            ruta_cache = os.path.join(dir_repo, ".cache", "inventario_pendrive_cache.sqlite")

        self.cache = CacheInventario(ruta_cache, self.raiz_real, desactivar=desactivar_cache)

        # Estructuras de resultados
        self.archivos: List[ArchivoInfo] = []
        self.carpetas_encontradas: Set[str] = set()
        self.carpetas_vacias: List[str] = []
        self.rutas_descartadas_seguridad: List[str] = []
        self.carpetas_sistema_ignoradas: List[str] = []

    def escanear(self):
        """
        Recorre el árbol de directorios del pendrive respetando las reglas de seguridad
        y filtros de sistema/ocultos.
        """
        print(f"[*] Iniciando escaneo en: {self.raiz_real}")
        if not self.ffprobe_disponible:
            print("[!] Aviso: ffprobe no está instalado. No se podrá extraer duración de videos.", file=sys.stderr)

        carpetas_con_archivos: Set[str] = set()
        todas_carpetas_rel: Set[str] = set()

        for dirpath, dirnames, filenames in os.walk(self.raiz_real, topdown=True, followlinks=False):
            # 1. Comprobar que el directorio actual no escape de la raíz
            if not esta_dentro_de_raiz(dirpath, self.raiz_real):
                self.rutas_descartadas_seguridad.append(dirpath)
                dirnames.clear()
                continue

            rel_dir = os.path.relpath(dirpath, self.raiz_real)
            if rel_dir == '.':
                rel_dir = ""

            # 2. Filtrar subdirectorios in-place (dirnames)
            directorios_filtrados = []
            for d in dirnames:
                ruta_subdir = os.path.join(dirpath, d)

                # Seguridad de symlinks / rutas externas
                if not esta_dentro_de_raiz(ruta_subdir, self.raiz_real):
                    self.rutas_descartadas_seguridad.append(ruta_subdir)
                    continue

                # Carpetas de sistema
                if es_carpeta_sistema(d):
                    self.carpetas_sistema_ignoradas.append(os.path.join(rel_dir, d))
                    continue

                # Carpetas ocultas
                if not self.incluir_ocultos and es_elemento_oculto(d, ruta_subdir):
                    continue

                directorios_filtrados.append(d)
                sub_rel = os.path.join(rel_dir, d) if rel_dir else d
                todas_carpetas_rel.add(sub_rel)

            dirnames[:] = directorios_filtrados

            # 3. Procesar archivos
            for f in filenames:
                ruta_archivo = os.path.join(dirpath, f)

                # Seguridad de symlinks / escape
                if not esta_dentro_de_raiz(ruta_archivo, self.raiz_real):
                    self.rutas_descartadas_seguridad.append(ruta_archivo)
                    continue

                # Archivos ocultos
                if not self.incluir_ocultos and es_elemento_oculto(f, ruta_archivo):
                    continue

                try:
                    stat_info = os.stat(ruta_archivo)
                except (OSError, PermissionError) as e:
                    print(f"[!] No se pudo obtener stat de '{ruta_archivo}': {e}", file=sys.stderr)
                    continue

                # Identificar carpeta de primer nivel y sueltos
                partes = Path(rel_dir).parts if rel_dir else ()
                if len(partes) == 0:
                    carpeta_p1 = ""
                    es_suelto_raiz = True
                    es_suelto_p1 = False
                else:
                    carpeta_p1 = partes[0]
                    es_suelto_raiz = False
                    es_suelto_p1 = (len(partes) == 1)

                rel_file = os.path.join(rel_dir, f) if rel_dir else f
                cat = clasificar_archivo(f)
                _, ext = os.path.splitext(f)

                info = ArchivoInfo(
                    ruta_relativa=rel_file,
                    ruta_absoluta=ruta_archivo,
                    nombre=f,
                    tamanio_bytes=stat_info.st_size,
                    mtime=stat_info.st_mtime,
                    categoria=cat,
                    extension=ext.lower(),
                    carpeta_primer_nivel=carpeta_p1,
                    es_suelto_raiz=es_suelto_raiz,
                    es_suelto_primer_nivel=es_suelto_p1
                )
                self.archivos.append(info)

                # Registrar que esta carpeta (y todos sus ancestros) tienen archivos
                curr = rel_dir
                while curr:
                    carpetas_con_archivos.add(curr)
                    padre = os.path.dirname(curr)
                    if padre == curr:
                        break
                    curr = padre

        # Identificar carpetas verdaderamente vacías
        self.carpetas_encontradas = todas_carpetas_rel
        self.carpetas_vacias = sorted(list(todas_carpetas_rel - carpetas_con_archivos))
        print(f"[+] Total de archivos detectados: {len(self.archivos)}")
        print(f"[+] Carpetas escaneadas: {len(self.carpetas_encontradas)} (Vacías: {len(self.carpetas_vacias)})")

    def procesar_metadatos_y_duracion(self):
        """
        Calcula la duración con ffprobe para videos utilizando la caché local en el repo.
        """
        videos = [a for a in self.archivos if a.categoria == 'video']
        if not videos or not self.ffprobe_disponible:
            return

        print(f"[*] Analizando duración de {len(videos)} videos (con caché)...")
        for i, video in enumerate(videos, 1):
            cached = self.cache.obtener(video.ruta_relativa, video.tamanio_bytes, video.mtime)
            if cached and cached[1] is not None:
                video.duracion_segundos = cached[1]
                video.sha256 = cached[0]
            else:
                dur = obtener_duracion_video(video.ruta_absoluta)
                video.duracion_segundos = dur
                # Guardar en caché (el sha256 se actualizará más adelante si se calcula)
                self.cache.guardar(
                    video.ruta_relativa, video.tamanio_bytes, video.mtime,
                    video.sha256, dur, video.categoria
                )

    def analizar_duplicados_globales(self) -> Tuple[List[Dict], int]:
        """
        Detecta duplicados en TODO el pendrive (incluso cross-carpetas de distinto tipo).
        Estrategia de 2 fases:
        1. Agrupar por tamaño de bytes (> 0). Los archivos con tamaño único se descartan de inmediato.
        2. Para los grupos con 2 o más archivos de igual tamaño, calcular/reutilizar SHA-256.
        """
        print("[*] Buscando archivos duplicados en todo el pendrive...")

        # Agrupar por tamaño
        grupos_tamanio: Dict[int, List[ArchivoInfo]] = {}
        for a in self.archivos:
            if a.tamanio_bytes > 0:
                grupos_tamanio.setdefault(a.tamanio_bytes, []).append(a)

        candidatos_hash: List[ArchivoInfo] = []
        for tam, lista in grupos_tamanio.items():
            if len(lista) > 1:
                candidatos_hash.extend(lista)

        print(f"[*] {len(candidatos_hash)} archivos comparten tamaño idéntico. Calculando hashes...")

        # Hashear candidatos
        grupos_hash: Dict[str, List[ArchivoInfo]] = {}
        for a in candidatos_hash:
            cached = self.cache.obtener(a.ruta_relativa, a.tamanio_bytes, a.mtime)
            if cached and cached[0]:
                a.sha256 = cached[0]
                if a.categoria == 'video' and a.duracion_segundos is None:
                    a.duracion_segundos = cached[1]
            else:
                h = calcular_sha256(a.ruta_absoluta)
                a.sha256 = h
                self.cache.guardar(
                    a.ruta_relativa, a.tamanio_bytes, a.mtime,
                    h, a.duracion_segundos, a.categoria
                )

            if a.sha256:
                grupos_hash.setdefault(a.sha256, []).append(a)

        # Filtrar duplicados confirmados
        duplicados_confirmados = []
        espacio_total_desperdiciado = 0

        for h, lista in grupos_hash.items():
            if len(lista) > 1:
                tamanio = lista[0].tamanio_bytes
                desperdicio = (len(lista) - 1) * tamanio
                espacio_total_desperdiciado += desperdicio

                # Determinar si son de distintas carpetas de primer nivel
                carpetas_involucradas = sorted(list(set(
                    a.carpeta_primer_nivel if a.carpeta_primer_nivel else "(raíz)"
                    for a in lista
                )))
                categorias_involucradas = sorted(list(set(a.categoria for a in lista)))

                duplicados_confirmados.append({
                    'sha256': h,
                    'tamanio_bytes': tamanio,
                    'cantidad_copias': len(lista),
                    'desperdicio_bytes': desperdicio,
                    'carpetas': carpetas_involucradas,
                    'categorias': categorias_involucradas,
                    'es_inter_carpeta': len(carpetas_involucradas) > 1,
                    'archivos': [a.ruta_relativa for a in lista]
                })

        # Ordenar por desperdicio descendente
        duplicados_confirmados.sort(key=lambda x: x['desperdicio_bytes'], reverse=True)
        print(f"[+] Grupos de archivos duplicados encontrados: {len(duplicados_confirmados)} "
              f"({formatear_bytes(espacio_total_desperdiciado)} desperdiciados)")

        return duplicados_confirmados, espacio_total_desperdiciado

    def analizar_carpetas_duplicadas(self) -> List[Dict]:
        """
        Detecta carpetas que parecen duplicadas entre sí:
        1. Por contenido 100% idéntico (mismo conjunto de hashes).
        2. Por contenido altamente similar (>= 75% de similitud de contenido).
        3. Por nombre similar (ej. 'videos' y 'videos1', 'lucie-fotos' y 'lucieroligym').
        """
        print("[*] Analizando similitud y duplicados entre carpetas...")

        # Mapear cada carpeta con sus archivos y hashes
        carpetas_map: Dict[str, Dict] = {}
        for c in self.carpetas_encontradas:
            carpetas_map[c] = {
                'archivos_rel': [],
                'hashes': set(),
                'bytes_total': 0
            }

        for a in self.archivos:
            dir_padre = os.path.dirname(a.ruta_relativa)
            if dir_padre in carpetas_map:
                nombre_base = os.path.basename(a.ruta_relativa)
                carpetas_map[dir_padre]['archivos_rel'].append(nombre_base)
                if a.sha256:
                    carpetas_map[dir_padre]['hashes'].add(a.sha256)
                carpetas_map[dir_padre]['bytes_total'] += a.tamanio_bytes

        lista_carpetas = [c for c in sorted(self.carpetas_encontradas) if carpetas_map[c]['hashes']]
        sospechosas = []

        for i in range(len(lista_carpetas)):
            for j in range(i + 1, len(lista_carpetas)):
                c1 = lista_carpetas[i]
                c2 = lista_carpetas[j]

                # Evitar comparar una carpeta con una subcarpeta directa suya si es redundante
                if c2.startswith(c1 + os.sep) or c1.startswith(c2 + os.sep):
                    continue

                h1 = carpetas_map[c1]['hashes']
                h2 = carpetas_map[c2]['hashes']

                if not h1 or not h2:
                    continue

                interseccion = h1 & h2
                union = h1 | h2
                coeficiente_jaccard = len(interseccion) / len(union) if union else 0.0

                nombre_c1 = os.path.basename(c1).lower()
                nombre_c2 = os.path.basename(c2).lower()
                similitud_nombre = SequenceMatcher(None, nombre_c1, nombre_c2).ratio()

                es_duplicada_exacta = (h1 == h2 and len(h1) > 0)
                es_alta_similitud = (coeficiente_jaccard >= 0.75 and len(interseccion) >= 2)
                es_nombre_similar = (similitud_nombre >= 0.8 and abs(len(nombre_c1) - len(nombre_c2)) <= 3)

                if es_duplicada_exacta or es_alta_similitud or (es_nombre_similar and len(interseccion) > 0):
                    sospechosas.append({
                        'carpeta1': c1,
                        'carpeta2': c2,
                        'tipo_coincidencia': (
                            '100% Contenido Idéntico' if es_duplicada_exacta else
                            ('Alta similitud de contenido' if es_alta_similitud else 'Nombre y contenido compartido')
                        ),
                        'similitud_contenido_pct': round(coeficiente_jaccard * 100, 1),
                        'similitud_nombre_pct': round(similitud_nombre * 100, 1),
                        'archivos_compartidos': len(interseccion),
                        'total_c1': len(h1),
                        'total_c2': len(h2),
                        'peso_c1_bytes': carpetas_map[c1]['bytes_total'],
                        'peso_c2_bytes': carpetas_map[c2]['bytes_total']
                    })

        return sospechosas

    def generar_resumenes_primer_nivel(self) -> Tuple[Dict[str, ResumenCarpeta], ResumenCarpeta]:
        """
        Genera el resumen por carpeta de primer nivel y de archivos sueltos en la raíz.
        """
        resumenes: Dict[str, ResumenCarpeta] = {}
        resumen_raiz = ResumenCarpeta(nombre="(Raíz del pendrive)")

        # Inicializar carpetas de primer nivel
        carpetas_p1 = set()
        for a in self.archivos:
            if a.carpeta_primer_nivel:
                carpetas_p1.add(a.carpeta_primer_nivel)
        for c in self.carpetas_encontradas:
            p = Path(c).parts
            if p:
                carpetas_p1.add(p[0])

        for c1 in sorted(carpetas_p1):
            resumenes[c1] = ResumenCarpeta(nombre=c1)

        for a in self.archivos:
            if a.es_suelto_raiz:
                resumen_raiz.total_archivos += 1
                resumen_raiz.total_bytes += a.tamanio_bytes
                resumen_raiz.archivos_sueltos_count += 1
                resumen_raiz.archivos_sueltos.append(a.nombre)
                cat_info = resumen_raiz.desglose.setdefault(a.categoria, ResumenCategoria())
                cat_info.cantidad += 1
                cat_info.tamanio_bytes += a.tamanio_bytes
                if a.duracion_segundos:
                    cat_info.duracion_segundos += a.duracion_segundos
                    resumen_raiz.duracion_video_segundos += a.duracion_segundos
            else:
                c1 = a.carpeta_primer_nivel
                if c1 in resumenes:
                    rc = resumenes[c1]
                    rc.total_archivos += 1
                    rc.total_bytes += a.tamanio_bytes
                    cat_info = rc.desglose.setdefault(a.categoria, ResumenCategoria())
                    cat_info.cantidad += 1
                    cat_info.tamanio_bytes += a.tamanio_bytes
                    if a.duracion_segundos:
                        cat_info.duracion_segundos += a.duracion_segundos
                        rc.duracion_video_segundos += a.duracion_segundos
                    if a.es_suelto_primer_nivel:
                        rc.archivos_sueltos_count += 1
                        rc.archivos_sueltos.append(a.nombre)

        return resumenes, resumen_raiz

    def obtener_espacio_disco(self) -> Dict:
        """Obtiene las estadísticas de capacidad y uso del disco."""
        try:
            total, used, free = shutil.disk_usage(self.raiz_real)
            pct_used = (used / total * 100) if total > 0 else 0
        except OSError:
            total, used, free, pct_used = 0, 0, 0, 0

        peso_escaneado = sum(a.tamanio_bytes for a in self.archivos)

        return {
            'total_bytes': total,
            'usado_bytes': used,
            'libre_bytes': free,
            'porcentaje_usado': round(pct_used, 1),
            'peso_archivos_escaneados_bytes': peso_escaneado,
            'diferencia_sistema_bytes': max(0, used - peso_escaneado)
        }


# ==============================================================================
# GENERADOR DE REPORTES (CONSOLA, MARKDOWN, JSON)
# ==============================================================================

class GeneradorReporte:
    """Construye los informes legibles y estructurados."""

    def __init__(self, auditor: AuditorPendrive):
        self.auditor = auditor

    def generar_reporte_completo(self) -> Dict:
        disco = self.auditor.obtener_espacio_disco()
        resumen_p1, resumen_raiz = self.auditor.generar_resumenes_primer_nivel()
        duplicados, desperdicio = self.auditor.analizar_duplicados_globales()
        carpetas_sospechosas = self.auditor.analizar_carpetas_duplicadas()

        # Archivos sueltos en raíz y en primer nivel
        sueltos_raiz = [a for a in self.auditor.archivos if a.es_suelto_raiz]
        sueltos_p1 = [a for a in self.auditor.archivos if a.es_suelto_primer_nivel]

        return {
            'fecha': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'raiz': self.auditor.raiz_real,
            'disco': disco,
            'resumen_primer_nivel': resumen_p1,
            'resumen_raiz': resumen_raiz,
            'duplicados_globales': duplicados,
            'desperdicio_duplicados_bytes': desperdicio,
            'carpetas_vacias': self.auditor.carpetas_vacias,
            'carpetas_sospechosas_duplicadas': carpetas_sospechosas,
            'archivos_sueltos_raiz': sueltos_raiz,
            'archivos_sueltos_primer_nivel': sueltos_p1,
            'rutas_descartadas_seguridad': self.auditor.rutas_descartadas_seguridad,
            'carpetas_sistema_ignoradas': self.auditor.carpetas_sistema_ignoradas,
            'total_archivos': len(self.auditor.archivos)
        }

    def renderizar_markdown(self, datos: Dict) -> str:
        d = datos['disco']
        lines = [
            f"# 📊 Informe de Auditoría e Inventario del Pendrive",
            f"",
            f"- **Punto de Montaje:** `{datos['raiz']}`",
            f"- **Fecha de Análisis:** {datos['fecha']}",
            f"- **Total de Archivos Auditados:** {datos['total_archivos']:,}",
            f"- **Total Carpetas:** {len(self.auditor.carpetas_encontradas)} ({len(datos['carpetas_vacias'])} vacías)",
            f"",
            f"---",
            f"",
            f"## 💾 1. Capacidad y Uso del Almacenamiento",
            f"",
            f"| Métrica | Capacidad / Tamaño | Porcentaje |",
            f"| :--- | :--- | :--- |",
            f"| **Capacidad Total del Pendrive** | {formatear_bytes(d['total_bytes'])} | 100.0% |",
            f"| **Espacio Usado en Disco** | {formatear_bytes(d['usado_bytes'])} | {d['porcentaje_usado']}% |",
            f"| **Espacio Libre** | {formatear_bytes(d['libre_bytes'])} | {round(100.0 - d['porcentaje_usado'], 1)}% |",
            f"| **Peso Total Archivos Escaneados** | {formatear_bytes(d['peso_archivos_escaneados_bytes'])} | - |",
            f"| **Diferencia / Archivos del Sistema** | {formatear_bytes(d['diferencia_sistema_bytes'])} | - |",
            f"| **Espacio Desperdiciado en Duplicados** | **{formatear_bytes(datos['desperdicio_duplicados_bytes'])}** | - |",
            f"",
            f"---",
            f"",
            f"## 📁 2. Resumen por Carpeta de Primer Nivel",
            f"",
            f"Desglose detallado del contenido por directorio principal:",
            f""
        ]

        # Tabla de carpetas de primer nivel
        headers = ["Carpeta", "Archivos", "Peso Total", "Videos (Duración)", "Fotos", "Audios", "Docs", "Subs", "Otros", "Sueltos"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join([":---"] + [":---:"] * (len(headers) - 1)) + " |")

        # Agregar carpetas de primer nivel
        for c1, rc in datos['resumen_primer_nivel'].items():
            des = rc.desglose
            v_cnt = des.get('video', ResumenCategoria()).cantidad
            v_dur = formatear_duracion(rc.duracion_video_segundos) if v_cnt > 0 else "-"
            f_cnt = des.get('foto', ResumenCategoria()).cantidad
            a_cnt = des.get('audio', ResumenCategoria()).cantidad
            d_cnt = des.get('documento', ResumenCategoria()).cantidad
            s_cnt = des.get('subtítulo', ResumenCategoria()).cantidad
            o_cnt = des.get('otro', ResumenCategoria()).cantidad

            lines.append(
                f"| **`{c1}`** | {rc.total_archivos} | {formatear_bytes(rc.total_bytes)} | "
                f"{v_cnt} ({v_dur}) | {f_cnt} | {a_cnt} | {d_cnt} | {s_cnt} | {o_cnt} | {rc.archivos_sueltos_count} |"
            )

        # Fila para la raíz
        rz = datos['resumen_raiz']
        rz_des = rz.desglose
        v_cnt = rz_des.get('video', ResumenCategoria()).cantidad
        v_dur = formatear_duracion(rz.duracion_video_segundos) if v_cnt > 0 else "-"
        lines.append(
            f"| **`(Archivos en Raíz)`** | {rz.total_archivos} | {formatear_bytes(rz.total_bytes)} | "
            f"{v_cnt} ({v_dur}) | {rz_des.get('foto', ResumenCategoria()).cantidad} | "
            f"{rz_des.get('audio', ResumenCategoria()).cantidad} | "
            f"{rz_des.get('documento', ResumenCategoria()).cantidad} | "
            f"{rz_des.get('subtítulo', ResumenCategoria()).cantidad} | "
            f"{rz_des.get('otro', ResumenCategoria()).cantidad} | {rz.archivos_sueltos_count} |"
        )

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 📄 3. Archivos Sueltos Detectados",
            f"",
            f"### A. Archivos Sueltos en la Raíz del Pendrive ({len(datos['archivos_sueltos_raiz'])})",
            f""
        ])

        if datos['archivos_sueltos_raiz']:
            lines.append("| Archivo | Tipo | Tamaño | Duración |")
            lines.append("| :--- | :---: | :---: | :---: |")
            for a in datos['archivos_sueltos_raiz']:
                dur_str = formatear_duracion(a.duracion_segundos) if a.duracion_segundos else "-"
                lines.append(f"| `{a.nombre}` | {a.categoria} | {formatear_bytes(a.tamanio_bytes)} | {dur_str} |")
        else:
            lines.append("_No hay archivos sueltos en la raíz del pendrive._")

        lines.extend([
            f"",
            f"### B. Archivos Sueltos en la Raíz de Carpetas de Primer Nivel ({len(datos['archivos_sueltos_primer_nivel'])})",
            f""
        ])

        if datos['archivos_sueltos_primer_nivel']:
            lines.append("| Carpeta | Archivo | Tipo | Tamaño |")
            lines.append("| :--- | :--- | :---: | :---: |")
            for a in datos['archivos_sueltos_primer_nivel']:
                lines.append(f"| `{a.carpeta_primer_nivel}` | `{a.nombre}` | {a.categoria} | {formatear_bytes(a.tamanio_bytes)} |")
        else:
            lines.append("_No se encontraron archivos sueltos en las raíces de las carpetas de primer nivel._")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 👯 4. Duplicados Globales en TODO el Pendrive",
            f"",
            f"- **Grupos de duplicados detectados:** {len(datos['duplicados_globales'])}",
            f"- **Espacio recuperable si se eliminan copias redundantes:** **{formatear_bytes(datos['desperdicio_duplicados_bytes'])}**",
            f""
        ])

        if datos['duplicados_globales']:
            for idx, g in enumerate(datos['duplicados_globales'][:40], 1):
                inter = "🔄 (Entre distintas carpetas)" if g['es_inter_carpeta'] else "📁 (En la misma carpeta)"
                lines.append(f"#### #{idx}. Tamaño unitario: {formatear_bytes(g['tamanio_bytes'])} | Copias: {g['cantidad_copias']} | Desperdicio: {formatear_bytes(g['desperdicio_bytes'])} {inter}")
                lines.append(f"- **Hash SHA-256:** `{g['sha256']}`")
                lines.append(f"- **Ubicaciones:**")
                for ruta in g['archivos']:
                    lines.append(f"  - `{ruta}`")
                lines.append("")
            if len(datos['duplicados_globales']) > 40:
                lines.append(f"_... y {len(datos['duplicados_globales']) - 40} grupos de duplicados adicionales._\n")
        else:
            lines.append("✅ _No se detectaron archivos duplicados en la unidad._\n")

        lines.extend([
            f"---",
            f"",
            f"## 📂 5. Carpetas Vacías y Carpetas Sospechosas de Duplicación",
            f"",
            f"### A. Carpetas Vacías ({len(datos['carpetas_vacias'])})",
            f""
        ])

        if datos['carpetas_vacias']:
            lines.append("| Carpeta Vacía |")
            lines.append("| :--- |")
            for cv in datos['carpetas_vacias']:
                lines.append(f"| `{cv}` |")
        else:
            lines.append("✅ _No se encontraron carpetas vacías._")

        lines.extend([
            f"",
            f"### B. Carpetas que Parecen Duplicadas entre Sí ({len(datos['carpetas_sospechosas_duplicadas'])})",
            f""
        ])

        if datos['carpetas_sospechosas_duplicadas']:
            lines.append("| Carpeta A | Carpeta B | Criterio | Similitud Contenido | Similitud Nombre | Archivos Compartidos |")
            lines.append("| :--- | :--- | :--- | :---: | :---: | :---: |")
            for cs in datos['carpetas_sospechosas_duplicadas']:
                lines.append(
                    f"| `{cs['carpeta1']}` | `{cs['carpeta2']}` | {cs['tipo_coincidencia']} | "
                    f"{cs['similitud_contenido_pct']}% | {cs['similitud_nombre_pct']}% | {cs['archivos_compartidos']} |"
                )
        else:
            lines.append("✅ _No se detectaron carpetas sospechosas de duplicación._")

        # Seguridad y exclusiones
        if datos['rutas_descartadas_seguridad'] or datos['carpetas_sistema_ignoradas']:
            lines.extend([
                f"",
                f"---",
                f"",
                f"## 🛡️ 6. Auditoría de Seguridad y Exclusiones",
                f""
            ])
            if datos['carpetas_sistema_ignoradas']:
                lines.append(f"- **Carpetas de sistema ignoradas:** {', '.join(f'`{c}`' for c in set(datos['carpetas_sistema_ignoradas']))}")
            if datos['rutas_descartadas_seguridad']:
                lines.append(f"- ⚠️ **Rutas descartadas por seguridad (fuera de la raíz o symlinks inválidos):**")
                for r in datos['rutas_descartadas_seguridad']:
                    lines.append(f"  - `{r}`")

        return "\n".join(lines)

    def imprimir_consola(self, datos: Dict):
        """Imprime un resumen visual enriquecido en terminal."""
        d = datos['disco']
        print("\n" + "=" * 70)
        print(" 📊 RESUMEN AUDITORÍA DE PENDRIVE (SOLO LECTURA)")
        print("=" * 70)
        print(f" Raíz auditada:    {datos['raiz']}")
        print(f" Capacidad total:  {formatear_bytes(d['total_bytes'])}")
        print(f" Espacio usado:    {formatear_bytes(d['usado_bytes'])} ({d['porcentaje_usado']}%)")
        print(f" Espacio libre:    {formatear_bytes(d['libre_bytes'])}")
        print(f" Archivos totales: {datos['total_archivos']:,} ({formatear_bytes(d['peso_archivos_escaneados_bytes'])})")
        print(f" Duplicados:       {len(datos['duplicados_globales'])} grupos ({formatear_bytes(datos['desperdicio_duplicados_bytes'])} recuperables)")
        print(f" Carpetas vacías:  {len(datos['carpetas_vacias'])}")
        print(f" Carpetas simil.:  {len(datos['carpetas_sospechosas_duplicadas'])}")
        print("=" * 70)

        print("\n📁 RESUMEN POR CARPETA DE PRIMER NIVEL:")
        print(f"{'Carpeta':<25} | {'Archivos':<8} | {'Peso':<10} | {'Videos (Duración)':<20} | {'Sueltos':<7}")
        print("-" * 75)
        for c1, rc in datos['resumen_primer_nivel'].items():
            des = rc.desglose
            v_cnt = des.get('video', ResumenCategoria()).cantidad
            v_dur = formatear_duracion(rc.duracion_video_segundos) if v_cnt > 0 else "-"
            vid_str = f"{v_cnt} ({v_dur})"
            print(f"{c1[:24]:<25} | {rc.total_archivos:<8} | {formatear_bytes(rc.total_bytes):<10} | {vid_str:<20} | {rc.archivos_sueltos_count:<7}")

        rz = datos['resumen_raiz']
        v_cnt = rz.desglose.get('video', ResumenCategoria()).cantidad
        v_dur = formatear_duracion(rz.duracion_video_segundos) if v_cnt > 0 else "-"
        print(f"{'(Archivos en Raíz)':<25} | {rz.total_archivos:<8} | {formatear_bytes(rz.total_bytes):<10} | {f'{v_cnt} ({v_dur})':<20} | {rz.archivos_sueltos_count:<7}")
        print("-" * 75)

        if datos['duplicados_globales']:
            print(f"\n👯 TOP 5 DUPLICADOS POR ESPACIO PERDIDO:")
            for idx, g in enumerate(datos['duplicados_globales'][:5], 1):
                inter = "[CROSS-CARPETA]" if g['es_inter_carpeta'] else "[LOCAL]"
                print(f"  {idx}. {formatear_bytes(g['desperdicio_bytes'])} desperdiciados ({g['cantidad_copias']} copias de {formatear_bytes(g['tamanio_bytes'])}) {inter}")
                for r in g['archivos'][:3]:
                    print(f"     -> {r}")
                if len(g['archivos']) > 3:
                    print(f"     -> ... y {len(g['archivos']) - 3} copias más")

        if datos['carpetas_sospechosas_duplicadas']:
            print(f"\n📂 CARPETAS SOSPECHOSAS DE DUPLICACIÓN:")
            for cs in datos['carpetas_sospechosas_duplicadas'][:5]:
                print(f"  • '{cs['carpeta1']}' <==> '{cs['carpeta2']}' ({cs['tipo_coincidencia']} - {cs['similitud_contenido_pct']}% contenido compartido)")

        if datos['carpetas_vacias']:
            print(f"\n🗑️  CARPETAS VACÍAS ({len(datos['carpetas_vacias'])}):")
            for cv in datos['carpetas_vacias'][:5]:
                print(f"  • {cv}")
            if len(datos['carpetas_vacias']) > 5:
                print(f"  • ... y {len(datos['carpetas_vacias']) - 5} carpetas vacías más.")

        print("\n" + "=" * 70 + "\n")


# ==============================================================================
# ENTRADA PRINCIPAL Y PARSER DE ARGUMENTOS
# ==============================================================================

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auditoría e inventario exhaustivo de pendrives (Solo Lectura)."
    )

    parser.add_argument(
        "--raiz",
        default=None,
        help="Punto de montaje o letra de unidad del pendrive. Si no se especifica, busca un pendrive vinculado pidiendo confirmación."
    )

    parser.add_argument(
        "--incluir-ocultos",
        action="store_true",
        help="Incluir archivos y carpetas ocultos en el análisis."
    )

    parser.add_argument(
        "--salida",
        default="informe_pendrive.md",
        help="Ruta del archivo de informe generado (se guarda en el repositorio local, no en el pendrive)."
    )

    parser.add_argument(
        "--formato",
        choices=["markdown", "json", "texto"],
        default="markdown",
        help="Formato del informe generado en archivo (markdown, json, texto)."
    )

    parser.add_argument(
        "--sin-cache",
        action="store_true",
        help="Desactiva el uso de caché persistente (fuerza recálculo completo de hashes y duraciones)."
    )

    parser.add_argument(
        "--limpiar-cache",
        action="store_true",
        help="Elimina la base de datos de caché local antes de comenzar."
    )

    parser.add_argument(
        "--cache-path",
        default=None,
        help="Ruta personalizada para el archivo SQLite de caché (debe estar fuera del pendrive)."
    )

    parser.add_argument(
        "--verboso",
        action="store_true",
        help="Muestra detalles adicionales durante la ejecución."
    )

    return parser


def main():
    parser = construir_parser()
    args = parser.parse_args()

    raiz_arg = args.raiz
    if not raiz_arg:
        try:
            from bandeja.pendrive import detectar_pendrive
            from bandeja.config import ConfiguracionBandeja
            cfg = ConfiguracionBandeja()
            info_pen = detectar_pendrive(cfg)
        except Exception:
            info_pen = None

        if not info_pen or not info_pen.get("punto_montaje"):
            print("[!] Error: No se especificó --raiz y no se detectó ningún pendrive vinculado con marcador .lucie_pendrive.json.", file=sys.stderr)
            sys.exit(1)

        ruta_detectada = os.path.realpath(info_pen["punto_montaje"])
        print(f"[*] Pendrive vinculado detectado en: '{ruta_detectada}' (ID: {info_pen.get('id')})")
        try:
            confirmacion = input(f"¿Desea usar la ruta resuelta '{ruta_detectada}'? [s/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            confirmacion = "n"

        if confirmacion not in ("s", "si", "y", "yes"):
            print("[!] Operación cancelada por el usuario. Especifique --raiz manualmente.", file=sys.stderr)
            sys.exit(1)
        raiz_arg = ruta_detectada

    try:
        raiz_valida = normalizar_raiz(raiz_arg)
    except Exception as e:
        print(f"[!] Error al acceder a la raíz: {e}", file=sys.stderr)
        sys.exit(1)

    # Validar que el archivo de salida no esté dentro del pendrive
    salida_abs = os.path.abspath(args.salida)
    if esta_dentro_de_raiz(salida_abs, raiz_valida):
        print(
            f"[!] Error de Solo Lectura: El archivo de salida '{args.salida}' "
            f"no puede guardarse dentro del pendrive '{raiz_valida}'.",
            file=sys.stderr
        )
        sys.exit(1)

    # Inicializar auditor
    try:
        auditor = AuditorPendrive(
            ruta_raiz=raiz_valida,
            incluir_ocultos=args.incluir_ocultos,
            ruta_cache=args.cache_path,
            desactivar_cache=args.sin_cache,
            verboso=args.verboso
        )
    except Exception as e:
        print(f"[!] Error de inicialización: {e}", file=sys.stderr)
        sys.exit(1)

    if args.limpiar_cache:
        auditor.cache.limpiar()

    # Ejecutar etapas
    inicio = time.time()
    auditor.escanear()
    auditor.procesar_metadatos_y_duracion()

    generador = GeneradorReporte(auditor)
    datos = generador.generar_reporte_completo()

    # Mostrar en consola
    generador.imprimir_consola(datos)

    # Escribir informe en archivo
    os.makedirs(os.path.dirname(salida_abs), exist_ok=True)
    if args.formato == "markdown":
        contenido = generador.renderizar_markdown(datos)
        with open(salida_abs, "w", encoding="utf-8", newline="\n") as f:
            f.write(contenido)
    elif args.formato == "json":
        # Para serializar dataclasses y sets
        def serializador(obj):
            if isinstance(obj, set):
                return sorted(list(obj))
            if hasattr(obj, '__dict__'):
                return asdict(obj)
            return str(obj)

        with open(salida_abs, "w", encoding="utf-8", newline="\n") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False, default=serializador)
    else:
        # Texto plano
        contenido = generador.renderizar_markdown(datos)
        with open(salida_abs, "w", encoding="utf-8", newline="\n") as f:
            f.write(contenido)

    tiempo_total = time.time() - inicio
    print(f"[+] Informe generado exitosamente en: {salida_abs}")
    print(f"[+] Tiempo total de ejecución: {tiempo_total:.2f} segundos.")


if __name__ == "__main__":
    main()
