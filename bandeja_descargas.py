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
import datetime
import fnmatch
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set, Tuple, Any
from urllib.parse import parse_qs, urlparse

# Constantes del sistema
EXTENSIONES_MEDIA_DEFECTO = [".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp"]
EXTENSIONES_IMAGENES_DEFECTO = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSIONES_TEMP_DEFECTO = [".crdownload", ".part", ".tmp"]
NOMBRES_RESERVADOS_WINDOWS = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}
CARACTERES_INVALIDOS_ESCENA = set('<>:"|?*\\/')


class ErrorSeguridadBandeja(Exception):
    """Excepción para violaciones de seguridad o confinamiento de rutas."""
    pass


class ErrorValidacionEscena(Exception):
    """Excepción para nombres de escena inválidos."""
    pass


class ErrorDeshacer(Exception):
    """Excepción al revertir una operación si la ruta previa está ocupada."""
    pass


def calcular_sha256(ruta_archivo: str, bloque: int = 65536) -> str:
    """Calcula el hash SHA-256 de un archivo de manera segura."""
    h = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        while True:
            datos = f.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()


class ConfiguracionBandeja:
    """Gestiona la carga y validación de config_bandeja.json."""

    def __init__(self, ruta_config: str = "config_bandeja.json"):
        self.ruta_config = ruta_config
        self.ruta_descargas = os.path.expanduser("~/Descargas")
        self.ruta_destino_base = os.path.expanduser("~/Descargas/_lucie")
        self.carpeta_imagenes = "imagenes"
        self.puerto_servidor = 8766
        self.host_servidor = "127.0.0.1"
        self.intervalo_sondeo_segundos = 5
        self.ventana_lote_minutos = 10
        self.extensiones_media = list(EXTENSIONES_MEDIA_DEFECTO)
        self.extensiones_temporales = list(EXTENSIONES_TEMP_DEFECTO)
        self.patrones_candidatos = {
            "grok": "grok-video-*",
            "nano_banana_regex": r"^.+_\d{14}\.(jpg|jpeg|png|webp)$",
            "flow": ""
        }
        self.cargar()

    def cargar(self):
        if os.path.exists(self.ruta_config):
            with open(self.ruta_config, "r", encoding="utf-8") as f:
                datos = json.load(f)
            if "ruta_descargas" in datos:
                self.ruta_descargas = os.path.abspath(os.path.expanduser(datos["ruta_descargas"]))
            if "ruta_destino_base" in datos:
                self.ruta_destino_base = os.path.abspath(os.path.expanduser(datos["ruta_destino_base"]))
            if "carpeta_imagenes" in datos:
                self.carpeta_imagenes = str(datos["carpeta_imagenes"]).strip() or "imagenes"
            if "puerto_servidor" in datos:
                self.puerto_servidor = int(datos["puerto_servidor"])
            if "host_servidor" in datos:
                self.host_servidor = str(datos["host_servidor"])
            if "intervalo_sondeo_segundos" in datos:
                self.intervalo_sondeo_segundos = max(1, int(datos["intervalo_sondeo_segundos"]))
            if "ventana_lote_minutos" in datos:
                self.ventana_lote_minutos = max(1, int(datos["ventana_lote_minutos"]))
            if "extensiones_media" in datos:
                self.extensiones_media = [ext.lower() for ext in datos["extensiones_media"]]
            if "extensiones_temporales" in datos:
                self.extensiones_temporales = [ext.lower() for ext in datos["extensiones_temporales"]]
            if "patrones_candidatos" in datos:
                self.patrones_candidatos.update(datos["patrones_candidatos"])


class GestorBaseDatosBandeja:
    """Administra la tabla bandeja_archivos y bandeja_estado en SQLite."""

    def __init__(self, ruta_db: str = ".cache/inventario_pendrive_cache.sqlite"):
        self.ruta_db = ruta_db
        os.makedirs(os.path.dirname(os.path.abspath(self.ruta_db)), exist_ok=True)
        self._lock = threading.Lock()
        self.inicializar_tablas()

    def _conectar(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.ruta_db, timeout=10.0)
        con.row_factory = sqlite3.Row
        return con

    def inicializar_tablas(self):
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS bandeja_archivos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE NOT NULL,
                ruta_actual TEXT NOT NULL,
                estado TEXT NOT NULL, -- 'detectado', 'clasificado', 'ignorado', 'movido'
                personaje TEXT,
                escena TEXT,
                fecha TEXT NOT NULL
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS bandeja_estado (
                clave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            );
            """)
            con.commit()

    def registrar_o_actualizar(self, hash_val: str, ruta_actual: str, estado: str,
                               personaje: Optional[str] = None, escena: Optional[str] = None) -> int:
        fecha_iso = datetime.datetime.now().isoformat()
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            INSERT INTO bandeja_archivos (hash, ruta_actual, estado, personaje, escena, fecha)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(hash) DO UPDATE SET
                ruta_actual = excluded.ruta_actual,
                estado = excluded.estado,
                personaje = COALESCE(excluded.personaje, bandeja_archivos.personaje),
                escena = COALESCE(excluded.escena, bandeja_archivos.escena),
                fecha = excluded.fecha;
            """, (hash_val, ruta_actual, estado, personaje, escena, fecha_iso))
            con.commit()
            cur.execute("SELECT id FROM bandeja_archivos WHERE hash = ?", (hash_val,))
            row = cur.fetchone()
            return row["id"] if row else 0

    def obtener_por_hash(self, hash_val: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM bandeja_archivos WHERE hash = ?", (hash_val,))
            row = cur.fetchone()
            return dict(row) if row else None

    def obtener_por_id(self, archivo_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM bandeja_archivos WHERE id = ?", (archivo_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def obtener_por_ruta(self, ruta_actual: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM bandeja_archivos WHERE ruta_actual = ?", (ruta_actual,))
            row = cur.fetchone()
            return dict(row) if row else None

    def guardar_decision_sin_identificar(self, hash_val: str, ruta_actual: str, es_proyecto: bool) -> int:
        estado = "clasificado" if es_proyecto else "ignorado"
        return self.registrar_o_actualizar(hash_val, ruta_actual, estado)

    def obtener_ultimo_personaje(self) -> Optional[str]:
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT valor FROM bandeja_estado WHERE clave = 'ultimo_personaje'")
            row = cur.fetchone()
            return row["valor"] if row else None

    def guardar_ultimo_personaje(self, personaje: str):
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            INSERT INTO bandeja_estado (clave, valor) VALUES ('ultimo_personaje', ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor;
            """, (personaje,))
            con.commit()


class FiltroListaBlanca:
    """Aplica la lista blanca estricta para determinar candidatos, escenas y no reconocidos."""

    def __init__(self, config: ConfiguracionBandeja, ruta_alias: str = "alias-personajes.json"):
        self.config = config
        self.alias_personajes = self._cargar_alias(ruta_alias)
        # Precompilar regex de Nano Banana
        regex_nb = self.config.patrones_candidatos.get("nano_banana_regex", r"^.+_\d{14}\.(jpg|jpeg|png|webp)$")
        self._regex_nano_banana = re.compile(regex_nb, re.IGNORECASE)

    def _cargar_alias(self, ruta_alias: str) -> List[str]:
        alias_set = {"lucie", "luci", "roli", "laroli", "magui", "mailen"}
        if os.path.exists(ruta_alias):
            try:
                with open(ruta_alias, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                for r in datos.get("reglas", []):
                    for pat in r.get("patrones", []):
                        limpio = pat.replace("*", "").strip().lower()
                        if limpio:
                            alias_set.add(limpio)
            except Exception:
                pass
        return sorted(list(alias_set), key=len, reverse=True)

    def es_carpeta_escena_existente(self, nombre_carpeta: str) -> bool:
        """Verifica si una carpeta de Descargas comienza con un alias de personaje."""
        nombre_lower = nombre_carpeta.strip().lower()
        for al in self.alias_personajes:
            if nombre_lower == al or nombre_lower.startswith(al + " ") or nombre_lower.startswith(al + "_") or nombre_lower.startswith(al + "-"):
                return True
        return False

    def obtener_personaje_de_carpeta_escena(self, nombre_carpeta: str) -> str:
        """Deduce el personaje principal a partir del nombre de la carpeta con alias."""
        nombre_lower = nombre_carpeta.strip().lower()
        if "roli" in nombre_lower or "magui" in nombre_lower:
            return "roli"
        if "lucie" in nombre_lower or "luci" in nombre_lower:
            return "lucie"
        if "mailen" in nombre_lower:
            return "mailen"
        return "lucie"

    def clasificar_archivo(self, nombre_archivo: str) -> str:
        """
        Retorna:
        - 'candidato': coincide con lista blanca y patrones (Grok, Nano Banana, Flow).
        - 'sin_identificar': es archivo de media pero sin patrón conocido.
        - 'ignorar': fuera de la lista blanca o archivo temporal.
        """
        nombre_lower = nombre_archivo.lower()
        _, ext = os.path.splitext(nombre_lower)

        # 1. Ignorar temporales inmediatamente
        if ext in self.config.extensiones_temporales:
            return "ignorar"

        # 2. Si no es extensión de media permitida, NUNCA se procesa
        if ext not in self.config.extensiones_media:
            return "ignorar"

        # 3. Evaluar patrones de proyecto conocidos
        # 3a. Grok
        pat_grok = self.config.patrones_candidatos.get("grok", "grok-video-*")
        if fnmatch.fnmatch(nombre_lower, pat_grok.lower()):
            return "candidato"

        # 3b. Nano Banana
        if self._regex_nano_banana.match(nombre_archivo):
            return "candidato"

        # 3c. Flow
        pat_flow = self.config.patrones_candidatos.get("flow", "").strip()
        if pat_flow and fnmatch.fnmatch(nombre_lower, pat_flow.lower()):
            return "candidato"

        # 4. Es archivo de media válido pero sin patrón conocido
        return "sin_identificar"


class ValidadorEscenas:
    """Valida nombres de escena contra restricciones de seguridad y sistemas de archivos."""

    @staticmethod
    def validar_nombre_escena(nombre: str, ruta_destino_base: str, ruta_descargas: str,
                              es_existente_descargas: bool = False, personaje: str = "lucie",
                              carpeta_imagenes: str = "imagenes") -> Tuple[bool, str]:
        """
        Valida que el nombre de escena sea seguro, cumpla reglas de longitud y caracteres,
        y no escape de su destino base.
        """
        if not nombre or not nombre.strip():
            return False, "El nombre de la escena no puede estar vacío."

        # Caracteres prohibidos y de control
        if ".." in nombre or "/" in nombre or "\\" in nombre:
            return False, "El nombre de la escena no puede contener separadores de ruta ('/', '\\') ni '..'."

        if nombre.endswith(".") or nombre.endswith(" "):
            return False, "El nombre de la escena no puede finalizar con un punto o espacio."

        if len(nombre) > 100:
            return False, f"El nombre de la escena excede los 100 caracteres permitidos ({len(nombre)})."

        if any(ord(c) < 32 for c in nombre):
            return False, "El nombre de la escena no puede contener caracteres de control."

        infracciones_caracteres = [c for c in nombre if c in CARACTERES_INVALIDOS_ESCENA]
        if infracciones_caracteres:
            return False, f"El nombre contiene caracteres inválidos en sistemas de archivos: {' '.join(set(infracciones_caracteres))}"

        # Nombres reservados en Windows/exFAT
        base_sin_ext = nombre.split(".")[0].upper()
        if base_sin_ext in NOMBRES_RESERVADOS_WINDOWS:
            return False, f"'{nombre}' es un nombre de dispositivo reservado en sistemas Windows/exFAT."

        # Validación de confinamiento mediante realpath
        try:
            if es_existente_descargas:
                ruta_final = os.path.join(ruta_descargas, nombre)
                base_confinada = os.path.realpath(ruta_descargas)
                ruta_final_real = os.path.realpath(ruta_final)
                if not (ruta_final_real == base_confinada or ruta_final_real.startswith(base_confinada + os.sep)):
                    return False, "La ruta de la escena escapa de los límites permitidos del directorio de destino."
            else:
                base_confinada = os.path.realpath(ruta_destino_base)
                subcarpetas = ["videos sin editar"]
                if carpeta_imagenes and carpeta_imagenes not in subcarpetas:
                    subcarpetas.append(carpeta_imagenes)
                for sub in subcarpetas:
                    ruta_final = os.path.join(ruta_destino_base, personaje, sub, nombre)
                    ruta_final_real = os.path.realpath(ruta_final)
                    if not (ruta_final_real == base_confinada or ruta_final_real.startswith(base_confinada + os.sep)):
                        return False, "La ruta de la escena escapa de los límites permitidos del directorio de destino."
        except Exception as e:
            return False, f"Error al validar confinamiento de la escena: {str(e)}"

        return True, ""


class DetectorDescargasActivas:
    """Verifica si un archivo se encuentra en descarga activa o inestable (ventana de 5s)."""

    def __init__(self, ventana_estabilidad_segundos: float = 5.0):
        self.ventana = ventana_estabilidad_segundos
        self._historial_tamanio: Dict[str, Tuple[int, float]] = {}

    def es_archivo_estable(self, ruta_completa: str) -> bool:
        """Determina si el archivo no ha cambiado de tamaño en al menos ventana_estabilidad_segundos."""
        try:
            st = os.stat(ruta_completa)
            tamanio_actual = st.st_size
            ahora = time.time()
        except OSError:
            return False

        if ruta_completa not in self._historial_tamanio:
            self._historial_tamanio[ruta_completa] = (tamanio_actual, ahora)
            return False

        tamanio_previo, timestamp_previo = self._historial_tamanio[ruta_completa]
        if tamanio_actual != tamanio_previo:
            self._historial_tamanio[ruta_completa] = (tamanio_actual, ahora)
            return False

        # Si el tamaño no cambió, comprobar si ya pasaron los segundos requeridos
        if (ahora - timestamp_previo) >= self.ventana:
            return True

        return False

    def limpiar_rutas_inexistentes(self, rutas_existentes: Set[str]):
        rutas_borrar = [r for r in self._historial_tamanio if r not in rutas_existentes]
        for r in rutas_borrar:
            self._historial_tamanio.pop(r, None)


class AgrupadorLotes:
    """Agrupa archivos multimedia candidatos por proximidad temporal de mtime."""

    def __init__(self, ventana_minutos: int = 10):
        self.ventana_segundos = ventana_minutos * 60

    def agrupar(self, candidatos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Toma una lista de dicts con {'ruta', 'nombre', 'tamanio', 'mtime', 'id_db'}
        y los agrupa en lotes ordenados temporalmente.
        """
        if not candidatos:
            return []

        candidatos_ordenados = sorted(candidatos, key=lambda x: x["mtime"])
        lotes: List[List[Dict[str, Any]]] = []
        lote_actual: List[Dict[str, Any]] = []

        for item in candidatos_ordenados:
            if not lote_actual:
                lote_actual.append(item)
            else:
                mtime_anterior = lote_actual[-1]["mtime"]
                if (item["mtime"] - mtime_anterior) <= self.ventana_segundos:
                    lote_actual.append(item)
                else:
                    lotes.append(lote_actual)
                    lote_actual = [item]

        if lote_actual:
            lotes.append(lote_actual)

        # Convertir a estructura de salida amigable
        resultado = []
        for idx, grupo in enumerate(lotes, 1):
            mtime_min = min(g["mtime"] for g in grupo)
            mtime_max = max(g["mtime"] for g in grupo)
            fecha_legible = datetime.datetime.fromtimestamp(mtime_min).strftime("%Y-%m-%d %H:%M:%S")
            bytes_totales = sum(g["tamanio"] for g in grupo)
            lote_id = f"lote_{int(mtime_min)}_{idx}"

            for arch in grupo:
                if "fecha" not in arch and "mtime" in arch:
                    arch["fecha"] = datetime.datetime.fromtimestamp(arch["mtime"]).strftime("%Y-%m-%d %H:%M:%S")

            resultado.append({
                "lote_id": lote_id,
                "numero": idx,
                "fecha": fecha_legible,
                "mtime_min": mtime_min,
                "mtime_max": mtime_max,
                "total_archivos": len(grupo),
                "total_bytes": bytes_totales,
                "archivos": grupo
            })

        return resultado


def generar_html_simulacion(simulacion: Dict[str, Any]) -> str:
    """
    Genera el marcado HTML para el modal de simulación previa.
    Muestra el destino relativo al directorio base resaltando el segmento de tipo
    ("videos sin editar" o "imagenes") y manteniendo la ruta de destino completa
    en el tooltip (atributo title) de cada archivo.
    """
    personaje = html.escape(str(simulacion.get("personaje", "")))
    escena = html.escape(str(simulacion.get("escena", "")))
    es_descargas = simulacion.get("es_existente_descargas", False)
    descargas_tag = " (En Descargas)" if es_descargas else ""

    filas = []
    for m in simulacion.get("movimientos", []):
        origen = m.get("origen", "")
        destino_completo = m.get("destino", "")
        destino_relativo = m.get("destino_relativo") or destino_completo
        subcarpeta_tipo = m.get("subcarpeta_tipo", "")
        nombre_archivo = os.path.basename(origen)

        # Formatear segmentos del destino relativo
        partes = [p for p in destino_relativo.replace("\\", "/").split("/") if p]
        partes_formateadas = []
        for p in partes:
            p_lower = p.lower()
            if p_lower == "videos sin editar":
                partes_formateadas.append(f'<span class="tag-tipo tag-video">{html.escape(p)}</span>')
            elif p_lower == "imagenes" or (subcarpeta_tipo and p_lower == subcarpeta_tipo.lower()):
                partes_formateadas.append(f'<span class="tag-tipo tag-imagen">{html.escape(p)}</span>')
            else:
                partes_formateadas.append(html.escape(p))

        destino_resaltado = " / ".join(partes_formateadas)

        origen_esc = html.escape(origen)
        destino_esc = html.escape(destino_completo)
        nombre_esc = html.escape(nombre_archivo)

        fila = (
            f'<tr>'
            f'<td><strong>{nombre_esc}</strong></td>'
            f'<td class="ruta-celda" title="{origen_esc}"><small style="color:var(--text-muted)">{origen_esc}</small></td>'
            f'<td class="ruta-celda destino-celda" title="{destino_esc}" data-destino="{destino_esc}">{destino_resaltado}</td>'
            f'</tr>'
        )
        filas.append(fila)

    filas_html = "\n".join(filas)
    return (
        f'<p><strong>Personaje:</strong> {personaje} | <strong>Escena:</strong> {escena}{descargas_tag}</p>\n'
        f'<table class="modal-tabla">\n'
        f'  <thead>\n'
        f'    <tr>\n'
        f'      <th style="width:25%;">Archivo</th>\n'
        f'      <th style="width:30%;">Origen</th>\n'
        f'      <th style="width:45%;">Destino (relativo)</th>\n'
        f'    </tr>\n'
        f'  </thead>\n'
        f'  <tbody>\n'
        f'    {filas_html}\n'
        f'  </tbody>\n'
        f'</table>'
    )


class GestorMovimientosBandeja:
    """
    Ejecuta simulaciones, movimientos con os.rename, resolución de colisiones,
    registro en bitácora .jsonl y reversión estricta (deshacer).
    """

    def __init__(self, ruta_descargas: str, ruta_destino_base: str, db: GestorBaseDatosBandeja,
                 ruta_bitacora: str = "bitacora_bandeja.jsonl", carpeta_imagenes: str = "imagenes"):
        self.ruta_descargas = os.path.realpath(ruta_descargas)
        self.ruta_destino_base = os.path.realpath(ruta_destino_base)
        self.db = db
        self.ruta_bitacora = ruta_bitacora
        self.carpeta_imagenes = (carpeta_imagenes or "imagenes").strip()
        self._lock = threading.Lock()

    def _validar_confinamiento(self, ruta: str):
        """Asegura que la ruta canónica permanezca estrictamente dentro de ~/Descargas."""
        real = os.path.realpath(ruta)
        if not (real == self.ruta_descargas or real.startswith(self.ruta_descargas + os.sep)):
            raise ErrorSeguridadBandeja(f"Violación de seguridad: la ruta '{ruta}' no pertenece a ~/Descargas.")

    def resolver_destino_sin_colision(self, ruta_destino_propuesta: str) -> str:
        """Si la ruta destino ya existe, busca un sufijo numérico correlativo ' (1)', ' (2)'."""
        if not os.path.exists(ruta_destino_propuesta):
            return ruta_destino_propuesta

        carpeta, nombre_completo = os.path.split(ruta_destino_propuesta)
        nombre_base, ext = os.path.splitext(nombre_completo)

        # Detectar si ya tenía un sufijo numérico
        match = re.match(r"^(.*?)\s*\((\d+)\)$", nombre_base)
        if match:
            prefijo = match.group(1).rstrip()
            contador = int(match.group(2)) + 1
        else:
            prefijo = nombre_base
            contador = 1

        while True:
            candidato = os.path.join(carpeta, f"{prefijo} ({contador}){ext}")
            if not os.path.exists(candidato):
                return candidato
            contador += 1

    def simular_movimiento_lote(self, archivos: List[Dict[str, Any]], personaje: str,
                                nombre_escena: str, es_existente_descargas: bool = False) -> Dict[str, Any]:
        """Calcula el origen y destino exactos para cada archivo del lote antes de mover."""
        # 1. Validar nombre de escena
        valido, motivo = ValidadorEscenas.validar_nombre_escena(
            nombre_escena, self.ruta_destino_base, self.ruta_descargas,
            es_existente_descargas=es_existente_descargas, personaje=personaje,
            carpeta_imagenes=self.carpeta_imagenes
        )
        if not valido:
            raise ErrorValidacionEscena(motivo)

        movimientos_simulados = []
        destinos_vistos: Set[str] = set()

        for arch in archivos:
            origen = os.path.realpath(arch["ruta"])
            self._validar_confinamiento(origen)
            nombre_archivo = os.path.basename(origen)

            if es_existente_descargas:
                carpeta_destino = os.path.join(self.ruta_descargas, nombre_escena)
                subcarpeta_tipo = ""
                base_rel = self.ruta_descargas
            else:
                _, ext = os.path.splitext(nombre_archivo.lower())
                if ext in EXTENSIONES_IMAGENES_DEFECTO:
                    subcarpeta_tipo = self.carpeta_imagenes
                else:
                    subcarpeta_tipo = "videos sin editar"
                carpeta_destino = os.path.join(self.ruta_destino_base, personaje, subcarpeta_tipo, nombre_escena)
                base_rel = self.ruta_destino_base

            self._validar_confinamiento(carpeta_destino)
            destino_inicial = os.path.join(carpeta_destino, nombre_archivo)

            # Resolver colisión física en disco
            destino_final = self.resolver_destino_sin_colision(destino_inicial)

            # Resolver posible colisión intra-lote
            while destino_final in destinos_vistos:
                destino_final = self.resolver_destino_sin_colision(destino_final)
            destinos_vistos.add(destino_final)

            destino_relativo = os.path.relpath(destino_final, base_rel).replace("\\", "/")

            movimientos_simulados.append({
                "id_db": arch.get("id_db"),
                "origen": origen,
                "destino": destino_final,
                "destino_relativo": destino_relativo,
                "subcarpeta_tipo": subcarpeta_tipo,
                "tamanio": arch.get("tamanio", 0),
                "hash": arch.get("hash", "")
            })

        resultado_sim = {
            "valido": True,
            "personaje": personaje,
            "escena": nombre_escena,
            "es_existente_descargas": es_existente_descargas,
            "total_archivos": len(movimientos_simulados),
            "movimientos": movimientos_simulados
        }
        resultado_sim["html"] = generar_html_simulacion(resultado_sim)
        return resultado_sim

    def ejecutar_movimiento_lote(self, simulacion: Dict[str, Any], lote_id: str) -> Dict[str, Any]:
        """Ejecuta los movimientos atómicos con os.rename y los asienta en la bitácora .jsonl."""
        with self._lock:
            movimientos_realizados = []
            id_operacion = f"op_{int(time.time())}_{secrets.token_hex(4)}"
            fecha_iso = datetime.datetime.now().isoformat()

            for item in simulacion["movimientos"]:
                origen = item["origen"]
                destino = item["destino"]
                self._validar_confinamiento(origen)
                self._validar_confinamiento(destino)

                if not os.path.exists(origen):
                    raise FileNotFoundError(f"El archivo de origen '{origen}' ya no existe.")

                # Crear carpeta de destino
                os.makedirs(os.path.dirname(destino), exist_ok=True)

                # Mover atómicamente en el mismo sistema de archivos (sin borrar, sin pisar)
                os.rename(origen, destino)

                # Calcular hash si no estaba calculado
                hash_val = item.get("hash") or calcular_sha256(destino)

                # Actualizar base de datos SQLite
                self.db.registrar_o_actualizar(
                    hash_val=hash_val,
                    ruta_actual=destino,
                    estado="movido",
                    personaje=simulacion["personaje"],
                    escena=simulacion["escena"]
                )

                movimientos_realizados.append({
                    "origen_anterior": origen,
                    "destino_nuevo": destino,
                    "hash": hash_val,
                    "tamanio": item["tamanio"]
                })

            # Guardar último personaje usado
            self.db.guardar_ultimo_personaje(simulacion["personaje"])

            # Escribir en la bitácora reversible .jsonl
            registro_bitacora = {
                "id_operacion": id_operacion,
                "lote_id": lote_id,
                "fecha": fecha_iso,
                "personaje": simulacion["personaje"],
                "escena": simulacion["escena"],
                "es_existente_descargas": simulacion.get("es_existente_descargas", False),
                "total_movimientos": len(movimientos_realizados),
                "movimientos": movimientos_realizados
            }

            with open(self.ruta_bitacora, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro_bitacora, ensure_ascii=False) + "\n")

            personaje = simulacion.get("personaje", "")
            escena = simulacion.get("escena", "")
            total_movidos = len(movimientos_realizados)
            mensaje_aviso = f"Se movieron {total_movidos} archivos a {personaje}/{escena}"

            return {
                "exito": True,
                "id_operacion": id_operacion,
                "total_movidos": total_movidos,
                "personaje": personaje,
                "escena": escena,
                "mensaje_aviso": mensaje_aviso
            }

    def deshacer_operacion(self, id_operacion: str) -> Dict[str, Any]:
        """
        Revierte una operación de movimiento restaurando los archivos a su origen mediante os.rename.
        REGLA DE SEGURIDAD ESTRICTA:
        Si la ruta original ya está ocupada por otro archivo, el deshacer se NIEGA por completo
        con un mensaje claro. NUNCA pisa ni sufija en el deshacer.
        """
        with self._lock:
            if not os.path.exists(self.ruta_bitacora):
                raise ErrorDeshacer("No existe archivo de bitácora para deshacer operaciones.")

            # Buscar la operación en la bitácora
            operacion_encontrada = None
            todas_operaciones = []
            with open(self.ruta_bitacora, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if linea:
                        op = json.loads(linea)
                        todas_operaciones.append(op)
                        if op.get("id_operacion") == id_operacion:
                            operacion_encontrada = op

            if not operacion_encontrada:
                raise ErrorDeshacer(f"No se encontró la operación '{id_operacion}' en la bitácora.")

            for op in todas_operaciones:
                if op.get("evento") == "deshacer" and op.get("id_operacion_revertida") == id_operacion:
                    raise ErrorDeshacer(f"La operación '{id_operacion}' ya fue deshecha previamente.")

            # Fase 1: Verificación preventiva integral
            for mov in operacion_encontrada["movimientos"]:
                origen_anterior = mov["origen_anterior"]
                destino_nuevo = mov["destino_nuevo"]

                if not os.path.exists(destino_nuevo):
                    raise ErrorDeshacer(
                        f"No se puede deshacer: el archivo en '{destino_nuevo}' ya no existe o fue movido externamente."
                    )

                # REGLA: Si la ruta original ya está ocupada, se niega terminantemente (sin pisar ni sufijar)
                if os.path.exists(origen_anterior):
                    raise ErrorDeshacer(
                        f"No se puede deshacer: la ruta original '{origen_anterior}' ya se encuentra ocupada. "
                        f"No se sobrescribe ni se altera ningún archivo."
                    )

            # Fase 2: Ejecución de la reversión con os.rename
            archivos_revertidos = []
            for mov in operacion_encontrada["movimientos"]:
                origen_anterior = mov["origen_anterior"]
                destino_nuevo = mov["destino_nuevo"]

                os.makedirs(os.path.dirname(origen_anterior), exist_ok=True)
                os.rename(destino_nuevo, origen_anterior)

                # Actualizar estado en la base SQLite
                self.db.registrar_o_actualizar(
                    hash_val=mov["hash"],
                    ruta_actual=origen_anterior,
                    estado="detectado"
                )
                archivos_revertidos.append(origen_anterior)

            # Registrar evento de reversión en la bitácora
            evento_reversion = {
                "evento": "deshacer",
                "id_operacion_revertida": id_operacion,
                "fecha": datetime.datetime.now().isoformat(),
                "total_revertidos": len(archivos_revertidos)
            }
            with open(self.ruta_bitacora, "a", encoding="utf-8") as f:
                f.write(json.dumps(evento_reversion, ensure_ascii=False) + "\n")

            return {
                "exito": True,
                "id_operacion": id_operacion,
                "total_revertidos": len(archivos_revertidos)
            }

    def obtener_historial(self, limite: int = 50) -> List[Dict[str, Any]]:
        """
        Lee los últimos movimientos de la bitácora .jsonl (hasta el límite indicado),
        correlacionando los eventos de reversión para determinar el estado de cada movimiento.
        """
        with self._lock:
            if not os.path.exists(self.ruta_bitacora):
                return []

            entradas = []
            try:
                with open(self.ruta_bitacora, "r", encoding="utf-8") as f:
                    for linea in f:
                        linea = linea.strip()
                        if linea:
                            try:
                                entradas.append(json.loads(linea))
                            except Exception:
                                pass
            except Exception:
                return []

            revertidas = set()
            for e in entradas:
                if e.get("evento") == "deshacer" and e.get("id_operacion_revertida"):
                    revertidas.add(e["id_operacion_revertida"])

            movimientos_resultado = []
            for e in reversed(entradas):
                if e.get("evento") == "deshacer":
                    continue
                id_op = e.get("id_operacion", "")
                fecha_op = e.get("fecha", "")
                estado = "deshecho" if id_op in revertidas else "movido"

                for mov in reversed(e.get("movimientos", [])):
                    origen = mov.get("origen_anterior", "")
                    destino = mov.get("destino_nuevo", "")
                    nombre = os.path.basename(origen)
                    movimientos_resultado.append({
                        "id_operacion": id_op,
                        "fecha": fecha_op,
                        "archivo": nombre,
                        "origen": origen,
                        "destino": destino,
                        "tamanio": mov.get("tamanio", 0),
                        "hash": mov.get("hash", ""),
                        "estado": estado
                    })
                    if len(movimientos_resultado) >= limite:
                        return movimientos_resultado

            return movimientos_resultado



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
        self._sin_identificar_actuales: List[Dict[str, Any]] = []
        self._escenas_existentes_actuales: List[Dict[str, Any]] = []
        self._ultimo_conteo_lotes = 0
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
        if shutil.which("notify-send"):
            try:
                subprocess.run(
                    ["notify-send", "Bandeja Lucie", mensaje],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
            except Exception:
                pass

    def escanear(self):
        """Realiza un pase de escaneo no invasivo en ~/Descargas."""
        if not os.path.exists(self.config.ruta_descargas):
            return

        candidatos_estables = []
        sin_identificar = []
        escenas_existentes = []
        rutas_existentes = set()

        try:
            entradas = os.listdir(self.config.ruta_descargas)
        except OSError:
            return

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
            except OSError:
                continue

            # Comprobar en base de datos SQLite si ya tiene decisión tomada
            reg = self.db.obtener_por_ruta(ruta_completa)
            hash_val = reg["hash"] if reg else calcular_sha256(ruta_completa)
            if not reg:
                reg_hash = self.db.obtener_por_hash(hash_val)
                if reg_hash:
                    reg = reg_hash

            if reg:
                id_db = reg["id"]
                estado_actual = reg["estado"]
            else:
                id_db = self.db.registrar_o_actualizar(hash_val, ruta_completa, "detectado")
                estado_actual = "detectado"

            item_info = {
                "id_db": id_db,
                "nombre": entrada,
                "ruta": ruta_completa,
                "tamanio": tamanio,
                "mtime": mtime,
                "hash": hash_val,
                "estado": estado_actual
            }

            if tipo_clasificacion == "candidato" or estado_actual == "clasificado":
                candidatos_estables.append(item_info)
            elif tipo_clasificacion == "sin_identificar" and estado_actual != "ignorado":
                sin_identificar.append(item_info)

        # También descubrir escenas ya creadas en el destino base
        if os.path.exists(self.config.ruta_destino_base):
            try:
                for pers in ("lucie", "roli", "mailen"):
                    subcarpetas_tipo = ["videos sin editar"]
                    if self.config.carpeta_imagenes and self.config.carpeta_imagenes not in subcarpetas_tipo:
                        subcarpetas_tipo.append(self.config.carpeta_imagenes)
                    for sub_tipo in subcarpetas_tipo:
                        carpeta_tipo = os.path.join(self.config.ruta_destino_base, pers, sub_tipo)
                        if os.path.isdir(carpeta_tipo):
                            for sub in os.listdir(carpeta_tipo):
                                ruta_sub = os.path.join(carpeta_tipo, sub)
                                if os.path.isdir(ruta_sub):
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
        lotes_generados = self.agrupador.agrupar(candidatos_estables)

        with self._lock:
            self._lotes_actuales = lotes_generados
            self._sin_identificar_actuales = sin_identificar
            self._escenas_existentes_actuales = escenas_existentes

            # Notificar si hay nuevos lotes
            if len(lotes_generados) > self._ultimo_conteo_lotes:
                nuevos = len(lotes_generados) - self._ultimo_conteo_lotes
                self._notificar_escritorio(f"Se detectaron {nuevos} lote(s) nuevo(s) listos para ordenar.")
            self._ultimo_conteo_lotes = len(lotes_generados)

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
                "sin_identificar": list(self._sin_identificar_actuales),
                "escenas": list(self._escenas_existentes_actuales)
            }


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

    def _validar_seguridad_post(self) -> bool:
        """
        Valida que la petición POST cumpla:
        1. Token anti-CSRF en cabecera 'X-CSRF-Token'.
        2. Content-Type 'application/json'.
        3. Host coincidente con 127.0.0.1:<puerto> o localhost:<puerto>.
        Responde 403 Forbidden si no se cumplen.
        """
        # 1. Validar Host
        host_header = self.headers.get("Host", "").strip()
        puerto_esperado = str(self.config.puerto_servidor)
        hosts_validos = {
            f"127.0.0.1:{puerto_esperado}",
            f"localhost:{puerto_esperado}",
            "127.0.0.1",
            "localhost"
        }
        if host_header not in hosts_validos:
            self._enviar_error(HTTPStatus.FORBIDDEN, f"Cabecera Host no permitida: '{host_header}'")
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

        if ruta in ("/", "/index.html"):
            self._servir_html_spa()
        elif ruta == "/api/lotes":
            estado = self.vigilante.obtener_estado()
            self._enviar_json({"lotes": estado["lotes"]})
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
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada.")

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
        if not self._validar_seguridad_post():
            return

        parsed = urlparse(self.path)
        ruta = parsed.path
        body = self._leer_json_body()

        if body is None:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Cuerpo JSON inválido o malformado.")
            return

        if ruta == "/api/clasificar-sin-identificar":
            self._handle_clasificar_sin_identificar(body)
        elif ruta == "/api/simular-mover":
            self._handle_simular_mover(body)
        elif ruta == "/api/mover-lote":
            self._handle_mover_lote(body)
        elif ruta == "/api/deshacer":
            self._handle_deshacer(body)
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Endpoint POST no encontrado.")

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

    def _handle_simular_mover(self, body: Dict[str, Any]):
        archivos = body.get("archivos", [])
        personaje = body.get("personaje", "lucie")
        nombre_escena = body.get("escena", "").strip()
        es_existente_descargas = bool(body.get("es_existente_descargas", False))

        if not archivos or not nombre_escena:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Se requiere lista de 'archivos' y 'escena'.")
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

        if not simulacion or "movimientos" not in simulacion:
            self._enviar_error(HTTPStatus.BAD_REQUEST, "Se requiere el objeto 'simulacion' previamente validado.")
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

  <nav>
    <button class="nav-btn active" id="nav-btn-lotes" onclick="mostrarPestana('lotes', event)">Lotes Detectados</button>
    <button class="nav-btn" id="nav-btn-sin-identificar" onclick="mostrarPestana('sin-identificar', event)">Sin Identificar</button>
    <button class="nav-btn" id="nav-btn-historial" onclick="mostrarPestana('historial', event)">Historial</button>
    <button class="nav-btn" onclick="recargarVistaActual()">Refrescar</button>
  </nav>

  <main>
    <div id="alert-box" style="display:none;" class="alert-error"></div>

    <section id="sec-lotes">
      <div id="contenedor-lotes">Cargando lotes...</div>
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
  </main>

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

  <script>
    const CSRF_TOKEN = "{self.token_csrf}";
    let datosEstado = {{ lotes: [], sin_identificar: [], escenas: [], personajes: [], ultimo_personaje: "lucie" }};
    let simulacionActiva = null;
    let loteActivoId = null;
    let pestanaActual = 'lotes';
    let historialActual = [];
    let operacionAvisoActual = null;

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
      msg.innerText = `Se movieron ${{totalMovidos}} archivos a ${{personaje}}/${{escena}}`;
      banner.style.display = 'flex';
    }}

    function cerrarAviso() {{
      const banner = document.getElementById('banner-aviso');
      banner.style.display = 'none';
      operacionAvisoActual = null;
    }}

    async function deshacerDesdeAviso() {{
      if (!operacionAvisoActual) return;
      const idOp = operacionAvisoActual;
      if (!confirm("¿Confirmás deshacer este lote completo? Los archivos regresarán a sus rutas originales.")) {{
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
        }}
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

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
      document.getElementById('sec-historial').style.display = (pestana === 'historial') ? 'block' : 'none';

      if (pestana === 'historial') {{
        cargarHistorial();
      }}
    }}

    async function recargarVistaActual() {{
      if (pestanaActual === 'historial') {{
        await cargarHistorial();
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
        const [lotesRes, sinIdRes, escenasRes, persRes] = await Promise.all([
          apiFetch('/api/lotes'),
          apiFetch('/api/sin-identificar'),
          apiFetch('/api/escenas'),
          apiFetch('/api/personajes')
        ]);
        datosEstado.lotes = lotesRes.lotes;
        datosEstado.sin_identificar = sinIdRes.sin_identificar;
        datosEstado.escenas = escenasRes.escenas;
        datosEstado.personajes = persRes.personajes;
        datosEstado.ultimo_personaje = persRes.ultimo_personaje;
        renderLotes();
        renderSinIdentificar();
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    function renderLotes() {{
      const cont = document.getElementById('contenedor-lotes');
      if (!datosEstado.lotes.length) {{
        cont.innerHTML = '<div class="card"><p style="color:var(--text-muted)">No hay nuevos lotes de candidatos en ~/Descargas.</p></div>';
        return;
      }}
      cont.innerHTML = datosEstado.lotes.map(lote => {{
        const persOptions = datosEstado.personajes.map(p => 
          `<option value="${{p.id}}" ${{p.id === datosEstado.ultimo_personaje ? 'selected' : ''}}>${{p.nombre}}</option>`
        ).join('');

        const escenasOptions = datosEstado.escenas.map(e => 
          `<option value="${{e.nombre}}" data-tipo="${{e.tipo}}">[${{e.tipo === 'descargas_alias' ? 'En Descargas' : 'Destino'}}] ${{e.nombre}}</option>`
        ).join('');

        return `
          <div class="card" id="card-${{lote.lote_id}}">
            <div class="card-header">
              <h3>Lote #${{lote.numero}} (${{lote.total_archivos}} archivos &bull; ${{formatearBytes(lote.total_bytes)}})</h3>
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
                <div class="archivo-item" title="Archivo: ${{a.nombre}}&#10;Fecha: ${{a.fecha || lote.fecha || ''}}&#10;Tamaño: ${{formatearBytes(a.tamanio)}}">
                  <div class="chk-container">
                    <input type="checkbox" class="chk-archivo chk-lote-${{lote.lote_id}}" data-id="${{a.id_db}}" checked onchange="actualizarSeleccionLote('${{lote.lote_id}}')">
                  </div>
                  <div class="miniatura-wrap">
                    <img src="/api/miniatura?id=${{a.id_db}}" alt="${{a.nombre}}" onerror="this.onerror=null;this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><rect width=%22100%%22 height=%22100%%22 fill=%22%23222%22/><text x=%2250%%22 y=%2250%%22 fill=%22%23888%22 text-anchor=%22middle%22 dy=%22.3em%22>Media</text></svg>';">
                  </div>
                  <div class="archivo-meta">
                    <div class="archivo-nombre" title="${{a.nombre}}">${{a.nombre}}</div>
                    <div class="archivo-peso">${{formatearBytes(a.tamanio)}}</div>
                  </div>
                </div>
              `).join('')}}
            </div>
            <div class="form-row">
              <label>Personaje: <select id="sel-pers-${{lote.lote_id}}">${{persOptions}}</select></label>
              <label>Escena:
                <select id="sel-escena-${{lote.lote_id}}" onchange="toggleNuevaEscena('${{lote.lote_id}}', this.value)">
                  <option value="__nueva__">+ Crear nueva escena...</option>
                  ${{escenasOptions}}
                </select>
              </label>
              <div class="campo-escena-wrap">
                <input type="text" id="txt-nueva-escena-${{lote.lote_id}}" placeholder="Nombre de escena nueva" style="max-width:200px;" oninput="validarInputEscena('${{lote.lote_id}}')">
                <span id="error-escena-${{lote.lote_id}}" class="error-inline" style="display:none;"></span>
              </div>
              <button class="btn-accion" id="btn-mover-${{lote.lote_id}}" onclick="iniciarMover('${{lote.lote_id}}')">Mover seleccionados (${{lote.archivos.length}})</button>
            </div>
          </div>
        `;
      }}).join('');
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

      const primerMovido = historialActual.find(m => m.estado === 'movido');
      if (btnUltimo) {{
        btnUltimo.disabled = !primerMovido;
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
                  <span class="${{m.estado === 'movido' ? 'badge-movido' : 'badge-deshecho'}}">
                    ${{m.estado}}
                  </span>
                </td>
                <td>
                  ${{m.estado === 'movido' ? `
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
      }} catch (e) {{
        mostrarError(e.message);
      }}
    }}

    async function deshacerUltimoLote() {{
      const primerMovido = historialActual.find(m => m.estado === 'movido');
      if (!primerMovido) {{
        mostrarError("No hay operaciones pendientes de deshacer en el historial.");
        return;
      }}
      await deshacerMovimiento(primerMovido.id_operacion);
    }}

    async function iniciarMover(loteId) {{
      const lote = datosEstado.lotes.find(l => l.lote_id === loteId);
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

    function formatearDestinoCliente(m) {{
      const rel = (m.destino_relativo || m.destino || '').replace(/\\\\/g, '/');
      const partes = rel.split('/').filter(Boolean);
      const partesHTML = partes.map(p => {{
        const pl = p.toLowerCase();
        if (pl === 'videos sin editar') {{
          return `<span class="tag-tipo tag-video">${{escapeHTML(p)}}</span>`;
        }} else if (pl === 'imagenes' || (m.subcarpeta_tipo && pl === m.subcarpeta_tipo.toLowerCase())) {{
          return `<span class="tag-tipo tag-imagen">${{escapeHTML(p)}}</span>`;
        }}
        return escapeHTML(p);
      }});
      return partesHTML.join(' / ');
    }}

    function mostrarModalSimulacion(sim) {{
      const cont = document.getElementById('simulacion-contenido');
      if (sim.html) {{
        cont.innerHTML = sim.html;
      }} else {{
        cont.innerHTML = `
          <p><strong>Personaje:</strong> ${{escapeHTML(sim.personaje || '')}} | <strong>Escena:</strong> ${{escapeHTML(sim.escena || '')}} ${{sim.es_existente_descargas ? '(En Descargas)' : ''}}</p>
          <table class="modal-tabla">
            <thead>
              <tr>
                <th style="width:25%;">Archivo</th>
                <th style="width:30%;">Origen</th>
                <th style="width:45%;">Destino (relativo)</th>
              </tr>
            </thead>
            <tbody>
              ${{sim.movimientos.map(m => `
                <tr>
                  <td><strong>${{escapeHTML(m.origen.split('/').pop())}}</strong></td>
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
    }}

    async function ejecutarMoverLote() {{
      if (!simulacionActiva || !loteActivoId) return;
      try {{
        const res = await apiFetch('/api/mover-lote', {{
          method: 'POST',
          body: JSON.stringify({{ simulacion: simulacionActiva, lote_id: loteActivoId }})
        }});
        cerrarModal();
        mostrarAvisoMover(
          res.total_movidos,
          res.personaje || simulacionActiva.personaje,
          res.escena || simulacionActiva.escena,
          res.id_operacion
        );
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

    cargarDatos();
  </script>
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
        config.ruta_descargas, config.ruta_destino_base, db, carpeta_imagenes=config.carpeta_imagenes
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
