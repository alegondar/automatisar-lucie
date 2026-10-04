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


def formatear_bytes(total_bytes: int) -> str:
    """Formatea una cantidad de bytes a una cadena legible (B, KB, MB, GB)."""
    if total_bytes < 1024:
        return f"{total_bytes} B"
    elif total_bytes < 1024 * 1024:
        return f"{total_bytes / 1024:.1f} KB"
    elif total_bytes < 1024 * 1024 * 1024:
        return f"{total_bytes / (1024 * 1024):.1f} MB"
    return f"{total_bytes / (1024 * 1024 * 1024):.1f} GB"


class ConfiguracionBandeja:
    """Gestiona la carga y validación de config_bandeja.json."""

    def __init__(self, ruta_config: str = "config_bandeja.json"):
        self.ruta_config = ruta_config
        self.ruta_descargas = os.path.expanduser("~/Descargas")
        self.ruta_destino_base = os.path.expanduser("~/Descargas/_lucie")
        self.puerto_servidor = 8766
        self.host_servidor = "127.0.0.1"
        self.intervalo_sondeo_segundos = 5
        self.ventana_lote_minutos = 10
        self.extensiones_media = list(EXTENSIONES_MEDIA_DEFECTO)
        self.extensiones_temporales = list(EXTENSIONES_TEMP_DEFECTO)
        self.patrones_candidatos = {
            "grok": "grok-video-*",
            "grok_video": "grok-video-*",
            "grok_image": "grok-image-*",
            "gemini": "Gemini_Generated_Image_*",
            "nano_banana_regex": r"^.+_\d{14}\.(jpg|jpeg|png|webp)$",
            "flow": ""
        }
        self.patrones_ignorar = ["Screenshot_*", "Captura*"]
        self.horas_alerta_capitulo_olvidado = 12
        self.minutos_antes_inicio_capitulo = 0
        self.cargar()

    def cargar(self):
        if os.path.exists(self.ruta_config):
            with open(self.ruta_config, "r", encoding="utf-8") as f:
                datos = json.load(f)
            if "ruta_descargas" in datos:
                self.ruta_descargas = os.path.abspath(os.path.expanduser(datos["ruta_descargas"]))
            if "ruta_destino_base" in datos:
                self.ruta_destino_base = os.path.abspath(os.path.expanduser(datos["ruta_destino_base"]))
            if "puerto_servidor" in datos:
                self.puerto_servidor = int(datos["puerto_servidor"])
            if "host_servidor" in datos:
                self.host_servidor = str(datos["host_servidor"])
            if "horas_alerta_capitulo_olvidado" in datos:
                self.horas_alerta_capitulo_olvidado = max(1, int(datos["horas_alerta_capitulo_olvidado"]))
            if "minutos_antes_inicio_capitulo" in datos:
                self.minutos_antes_inicio_capitulo = max(0, int(datos["minutos_antes_inicio_capitulo"]))
            if "intervalo_sondeo_segundos" in datos:
                self.intervalo_sondeo_segundos = max(1, int(datos["intervalo_sondeo_segundos"]))
            if "ventana_lote_minutos" in datos:
                self.ventana_lote_minutos = max(1, int(datos["ventana_lote_minutos"]))
            if "extensiones_media" in datos:
                self.extensiones_media = [ext.lower() for ext in datos["extensiones_media"]]
            if "extensiones_temporales" in datos:
                self.extensiones_temporales = [ext.lower() for ext in datos["extensiones_temporales"]]
            if "patrones_candidatos" in datos:
                if isinstance(datos["patrones_candidatos"], dict):
                    self.patrones_candidatos.update(datos["patrones_candidatos"])
                elif isinstance(datos["patrones_candidatos"], list):
                    for idx, pat in enumerate(datos["patrones_candidatos"]):
                        self.patrones_candidatos[f"patron_{idx}"] = pat
            if "patrones_ignorar" in datos:
                self.patrones_ignorar = [str(p) for p in datos["patrones_ignorar"]]


class GestorBaseDatosBandeja:
    """Administra la tabla bandeja_archivos y bandeja_estado en SQLite."""

    def __init__(self, ruta_db: str = ".cache/inventario_pendrive_cache.sqlite",
                 ruta_destino_base: Optional[str] = None, ruta_descargas: Optional[str] = None):
        self.ruta_db = ruta_db
        self.ruta_destino_base = ruta_destino_base
        self.ruta_descargas = ruta_descargas
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
            cur.execute("""
            CREATE TABLE IF NOT EXISTS bandeja_capitulos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                personaje TEXT NOT NULL,
                nombre TEXT NOT NULL,
                estado TEXT NOT NULL CHECK(estado IN ('activo', 'cerrado')),
                fecha_inicio TEXT NOT NULL,
                fecha_fin TEXT,
                fecha_ultimo_aviso TEXT,
                archivos_movidos INTEGER DEFAULT 0,
                descartado INTEGER DEFAULT 0,
                fecha_descartado TEXT,
                en_foco INTEGER DEFAULT 0
            );
            """)
            cur.execute("DROP INDEX IF EXISTS idx_capitulo_unico_activo;")
            # Migración segura para bases de datos existentes
            cur.execute("PRAGMA table_info(bandeja_capitulos);")
            cols_cap = [r["name"] for r in cur.fetchall()]
            if "descartado" not in cols_cap:
                cur.execute("ALTER TABLE bandeja_capitulos ADD COLUMN descartado INTEGER DEFAULT 0;")
            if "fecha_descartado" not in cols_cap:
                cur.execute("ALTER TABLE bandeja_capitulos ADD COLUMN fecha_descartado TEXT;")
            if "en_foco" not in cols_cap:
                cur.execute("ALTER TABLE bandeja_capitulos ADD COLUMN en_foco INTEGER DEFAULT 0;")

            cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_capitulo_en_foco
            ON bandeja_capitulos(en_foco) WHERE en_foco = 1;
            """)

            # Migración: si hay capítulo activo sin foco y ninguno en foco, poner en foco el más reciente
            cur.execute("SELECT id FROM bandeja_capitulos WHERE en_foco = 1 LIMIT 1")
            if not cur.fetchone():
                cur.execute("""
                SELECT id FROM bandeja_capitulos
                WHERE estado = 'activo' AND (descartado IS NULL OR descartado = 0)
                ORDER BY id DESC LIMIT 1
                """)
                row_act = cur.fetchone()
                if row_act:
                    cur.execute("UPDATE bandeja_capitulos SET en_foco = 1 WHERE id = ?", (row_act["id"],))

            con.commit()

    def registrar_o_actualizar(self, hash_val: str, ruta_actual: str, estado: str,
                               personaje: Optional[str] = None, escena: Optional[str] = None,
                               limpiar_escena: bool = False) -> int:
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
                escena = CASE WHEN ? THEN NULL ELSE COALESCE(excluded.escena, bandeja_archivos.escena) END,
                fecha = excluded.fecha;
            """, (hash_val, ruta_actual, estado, personaje, escena, fecha_iso, 1 if limpiar_escena else 0))
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

    def asegurar_carpeta_capitulo(self, personaje: str, nombre: str,
                                  ruta_destino_base: Optional[str] = None,
                                  ruta_descargas: Optional[str] = None) -> Dict[str, Any]:
        dest_base = ruta_destino_base or self.ruta_destino_base
        if not dest_base:
            dest_base = os.path.expanduser("~/Descargas/_lucie")
        desc = ruta_descargas or self.ruta_descargas or os.path.expanduser("~/Descargas")
        return asegurar_carpeta_capitulo(personaje, nombre, dest_base, desc)

    def empezar_capitulo(self, personaje: str, nombre: str, fecha_inicio: Optional[str] = None,
                         ruta_destino_base: Optional[str] = None, ruta_descargas: Optional[str] = None) -> Dict[str, Any]:
        """
        Inicia un nuevo capítulo activo. Falla si ya existe otro capítulo activo.
        Asegura la creación de la carpeta física si ruta_destino_base está disponible o configurada.
        """
        nombre_limpio = (nombre or "").strip()
        personaje_limpio = (personaje or "").strip().lower() or "lucie"
        if not nombre_limpio:
            raise ValueError("El nombre del capítulo no puede estar vacío.")

        dest_base = ruta_destino_base or self.ruta_destino_base
        desc = ruta_descargas or self.ruta_descargas
        info_carpeta = None
        if dest_base:
            info_carpeta = self.asegurar_carpeta_capitulo(personaje_limpio, nombre_limpio, dest_base, desc)

        fecha_ini = fecha_inicio or datetime.datetime.now().isoformat()
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            # Apagar foco anterior en una sola transacción atómica
            cur.execute("UPDATE bandeja_capitulos SET en_foco = 0 WHERE en_foco = 1")

            cur.execute("""
            INSERT INTO bandeja_capitulos (personaje, nombre, estado, fecha_inicio, fecha_ultimo_aviso, archivos_movidos, en_foco)
            VALUES (?, ?, 'activo', ?, ?, 0, 1)
            """, (personaje_limpio, nombre_limpio, fecha_ini, fecha_ini))
            con.commit()
            cap_id = cur.lastrowid
            cur.execute("SELECT * FROM bandeja_capitulos WHERE id = ?", (cap_id,))
            row = cur.fetchone()

        self.guardar_capitulo_activo(personaje_limpio, nombre_limpio, True)
        d = dict(row)
        d["habilitado"] = True
        if info_carpeta:
            d["carpeta_info"] = info_carpeta
        return d

    def obtener_capitulo_en_foco(self) -> Dict[str, Any]:
        """
        Retorna el capítulo abierto en foco (en_foco = 1) desde bandeja_capitulos.
        Si no hay ninguno en foco, retorna diccionario con habilitado=False.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            SELECT * FROM bandeja_capitulos
            WHERE estado = 'activo' AND en_foco = 1 AND (descartado IS NULL OR descartado = 0)
            LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                d = dict(row)
                d["habilitado"] = True
                return d
            return {
                "habilitado": False,
                "id": None,
                "personaje": None,
                "nombre": "",
                "estado": "cerrado",
                "fecha_inicio": None,
                "fecha_ultimo_aviso": None,
                "archivos_movidos": 0,
                "en_foco": 0
            }

    def obtener_capitulo_activo(self) -> Dict[str, Any]:
        """
        Retorna el capítulo en foco actual desde bandeja_capitulos.
        Si no existe o ninguno está en foco, retorna diccionario con habilitado=False.
        """
        return self.obtener_capitulo_en_foco()

    def poner_capitulo_en_foco(self, id_capitulo: int) -> Dict[str, Any]:
        """
        Pone en foco el capítulo abierto especificado por id_capitulo de manera atómica,
        apagando el foco previo. Lanza ValueError si el capítulo no existe, está cerrado o descartado.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            SELECT * FROM bandeja_capitulos
            WHERE id = ? AND estado = 'activo' AND (descartado IS NULL OR descartado = 0)
            """, (id_capitulo,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Capítulo con ID {id_capitulo} no encontrado o no está abierto.")

            cur.execute("UPDATE bandeja_capitulos SET en_foco = 0 WHERE en_foco = 1")
            cur.execute("UPDATE bandeja_capitulos SET en_foco = 1 WHERE id = ?", (id_capitulo,))
            con.commit()

            cur.execute("SELECT * FROM bandeja_capitulos WHERE id = ?", (id_capitulo,))
            updated = dict(cur.fetchone())

        self.guardar_capitulo_activo(updated["personaje"], updated["nombre"], True)
        updated["habilitado"] = True
        return updated

    def listar_capitulos_abiertos(self) -> List[Dict[str, Any]]:
        """
        Retorna la lista de capítulos con estado 'activo' y descartado = 0,
        ordenados con el capítulo en foco primero, y luego cronológicamente inverso por id.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            SELECT * FROM bandeja_capitulos
            WHERE estado = 'activo' AND (descartado IS NULL OR descartado = 0)
            ORDER BY en_foco DESC, id DESC
            """)
            return [dict(r) for r in cur.fetchall()]

    def guardar_capitulo_activo(self, personaje: str, nombre: str, habilitado: bool, fecha_inicio: Optional[str] = None):
        """
        Mantiene sincronizado el estado básico en bandeja_estado y bandeja_capitulos.
        """
        now_iso = fecha_inicio or datetime.datetime.now().isoformat()
        pers = (personaje or "").strip() if personaje else "lucie"
        nom = (nombre or "").strip()
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            INSERT INTO bandeja_estado (clave, valor) VALUES ('capitulo_activo_habilitado', ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor;
            """, ("1" if habilitado else "0",))
            cur.execute("""
            INSERT INTO bandeja_estado (clave, valor) VALUES ('capitulo_activo_personaje', ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor;
            """, (pers,))
            cur.execute("""
            INSERT INTO bandeja_estado (clave, valor) VALUES ('capitulo_activo_nombre', ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor;
            """, (nom,))

            if habilitado and nom:
                cur.execute("SELECT id, estado FROM bandeja_capitulos WHERE estado = 'activo' AND en_foco = 1 LIMIT 1")
                act = cur.fetchone()
                if not act:
                    cur.execute("UPDATE bandeja_capitulos SET en_foco = 0 WHERE en_foco = 1")
                    cur.execute("""
                    INSERT INTO bandeja_capitulos (personaje, nombre, estado, fecha_inicio, fecha_ultimo_aviso, archivos_movidos, en_foco)
                    VALUES (?, ?, 'activo', ?, ?, 0, 1)
                    """, (pers, nom, now_iso, now_iso))
                else:
                    cur.execute("""
                    UPDATE bandeja_capitulos SET personaje = ?, nombre = ? WHERE id = ?
                    """, (pers, nom, act["id"]))
            elif not habilitado:
                cur.execute("UPDATE bandeja_capitulos SET en_foco = 0 WHERE en_foco = 1")
            con.commit()

    def terminar_capitulo(self, id_capitulo: Optional[int] = None, fecha_fin: Optional[str] = None) -> bool:
        """
        Cierra el capítulo activo (o el especificado por id).
        Si el capítulo cerrado estaba en foco, deja el foco vacío (en_foco = 0).
        Retorna True si se cerró.
        """
        fin_iso = fecha_fin or datetime.datetime.now().isoformat()
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            if id_capitulo is not None:
                cur.execute("""
                UPDATE bandeja_capitulos SET estado = 'cerrado', fecha_fin = ?, en_foco = 0
                WHERE id = ? AND estado = 'activo'
                """, (fin_iso, id_capitulo))
            else:
                cur.execute("SELECT id FROM bandeja_capitulos WHERE estado = 'activo' AND en_foco = 1")
                row = cur.fetchone()
                if not row:
                    cur.execute("SELECT id FROM bandeja_capitulos WHERE estado = 'activo' LIMIT 1")
                    row = cur.fetchone()
                if row:
                    cur.execute("""
                    UPDATE bandeja_capitulos SET estado = 'cerrado', fecha_fin = ?, en_foco = 0
                    WHERE id = ?
                    """, (fin_iso, row["id"]))
                else:
                    return False
            con.commit()
            afectados = cur.rowcount > 0

        if afectados:
            cap_foco = self.obtener_capitulo_en_foco()
            if not cap_foco or not cap_foco.get("habilitado"):
                self.guardar_capitulo_activo("", "", False)
        return afectados

    def reabrir_capitulo(self, id_capitulo: int,
                         ruta_destino_base: Optional[str] = None,
                         ruta_descargas: Optional[str] = None) -> Dict[str, Any]:
        """
        Reabre un capítulo cerrado como activo.
        No falla si ya existen otros capítulos abiertos:
        - Si no hay ningún capítulo en foco, este toma el foco (en_foco = 1).
        - Si ya hay un capítulo en foco, queda abierto pero sin foco (en_foco = 0).
        Asegura la creación de la carpeta física si ruta_destino_base está disponible o configurada.
        """
        dest_base = ruta_destino_base or self.ruta_destino_base
        desc = ruta_descargas or self.ruta_descargas
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM bandeja_capitulos WHERE id = ?", (id_capitulo,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Capítulo no encontrado.")

            info_carpeta = None
            if dest_base:
                info_carpeta = self.asegurar_carpeta_capitulo(row["personaje"], row["nombre"], dest_base, desc)

            if row["estado"] == "activo" and (row["descartado"] is None or row["descartado"] == 0):
                d = dict(row)
                d["habilitado"] = True
                if info_carpeta:
                    d["carpeta_info"] = info_carpeta
                return d

            # Determinar si toma foco
            cur.execute("""
            SELECT id FROM bandeja_capitulos
            WHERE estado = 'activo' AND en_foco = 1 AND (descartado IS NULL OR descartado = 0)
            """)
            hay_foco = cur.fetchone() is not None
            nuevo_foco = 0 if hay_foco else 1

            now_iso = datetime.datetime.now().isoformat()
            cur.execute("""
            UPDATE bandeja_capitulos
            SET estado = 'activo', descartado = 0, fecha_descartado = NULL,
                fecha_fin = NULL, fecha_ultimo_aviso = ?, en_foco = ?
            WHERE id = ?
            """, (now_iso, nuevo_foco, id_capitulo))
            con.commit()

            cur.execute("SELECT * FROM bandeja_capitulos WHERE id = ?", (id_capitulo,))
            updated = dict(cur.fetchone())

        if nuevo_foco == 1:
            self.guardar_capitulo_activo(updated["personaje"], updated["nombre"], True)
        updated["habilitado"] = True
        if info_carpeta:
            updated["carpeta_info"] = info_carpeta
        return updated

    def obtener_capitulo_por_id(self, id_capitulo: int) -> Optional[Dict[str, Any]]:
        """
        Retorna un capítulo por su ID único.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM bandeja_capitulos WHERE id = ?", (id_capitulo,))
            row = cur.fetchone()
            return dict(row) if row else None

    def listar_capitulos_cerrados(self) -> List[Dict[str, Any]]:
        """
        Retorna la lista de capítulos con estado 'cerrado' no descartados, ordenados cronológicamente inverso.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            SELECT * FROM bandeja_capitulos
            WHERE estado = 'cerrado' AND (descartado IS NULL OR descartado = 0)
            ORDER BY id DESC
            """)
            return [dict(r) for r in cur.fetchall()]

    def listar_capitulos_descartados(self) -> List[Dict[str, Any]]:
        """
        Retorna la lista de capítulos marcados como descartados, ordenados cronológicamente inverso.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            SELECT * FROM bandeja_capitulos
            WHERE descartado = 1
            ORDER BY id DESC
            """)
            return [dict(r) for r in cur.fetchall()]

    def marcar_capitulo_descartado(self, id_capitulo: int, descartado: bool = True):
        """
        Marca o desmarca un capítulo como descartado.
        """
        now_iso = datetime.datetime.now().isoformat()
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT nombre, en_foco FROM bandeja_capitulos WHERE id = ?", (id_capitulo,))
            nom_row = cur.fetchone()
            nombre_cap = nom_row["nombre"] if nom_row else ""
            era_foco = bool(nom_row["en_foco"]) if nom_row and "en_foco" in nom_row.keys() else False

            if descartado:
                cur.execute("""
                UPDATE bandeja_capitulos
                SET descartado = 1, estado = 'cerrado', en_foco = 0, fecha_fin = COALESCE(fecha_fin, ?), fecha_descartado = ?
                WHERE id = ?
                """, (now_iso, now_iso, id_capitulo))
                if era_foco:
                    cur.execute("SELECT valor FROM bandeja_estado WHERE clave = 'capitulo_activo_nombre'")
                    r = cur.fetchone()
                    if r and r["valor"] == nombre_cap:
                        cur.execute("UPDATE bandeja_estado SET valor = '0' WHERE clave = 'capitulo_activo_habilitado'")
            else:
                cur.execute("""
                UPDATE bandeja_capitulos
                SET descartado = 0, estado = 'cerrado', en_foco = 0, fecha_descartado = NULL
                WHERE id = ?
                """, (id_capitulo,))
            con.commit()

    def actualizar_rutas_archivos_descarte(self, origen_carpeta: str, destino_carpeta: str, es_reversion: bool = False):
        """
        Actualiza ruta_actual y estado en bandeja_archivos para todos los archivos contenidos
        en origen_carpeta reubicados a destino_carpeta.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT id, hash, ruta_actual, estado FROM bandeja_archivos")
            filas = cur.fetchall()
            norm_orig = os.path.realpath(origen_carpeta)
            nuevo_estado = "movido" if es_reversion else "descartado"
            for f in filas:
                r_act = os.path.realpath(f["ruta_actual"])
                if r_act == norm_orig or r_act.startswith(norm_orig + os.sep):
                    rel = os.path.relpath(r_act, norm_orig)
                    nueva_ruta = os.path.join(destino_carpeta, rel)
                    cur.execute("""
                    UPDATE bandeja_archivos
                    SET ruta_actual = ?, estado = ?
                    WHERE id = ?
                    """, (nueva_ruta, nuevo_estado, f["id"]))
            con.commit()

    def posponer_alerta_capitulo(self, id_capitulo: Optional[int] = None, nueva_fecha: Optional[str] = None) -> bool:
        """
        Actualiza fecha_ultimo_aviso para postergar el aviso de capítulo olvidado.
        """
        fecha_aviso = nueva_fecha or datetime.datetime.now().isoformat()
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            if id_capitulo:
                cur.execute("""
                UPDATE bandeja_capitulos SET fecha_ultimo_aviso = ? WHERE id = ? AND estado = 'activo'
                """, (fecha_aviso, id_capitulo))
            else:
                cur.execute("""
                UPDATE bandeja_capitulos SET fecha_ultimo_aviso = ? WHERE estado = 'activo'
                """, (fecha_aviso,))
            con.commit()
            return cur.rowcount > 0

    def incrementar_movidos_capitulo(self, personaje: str, escena: str, cantidad: int = 1, id_capitulo: Optional[int] = None):
        """
        Incrementa el contador de archivos movidos para el capítulo correspondiente.
        Prioriza el capítulo activo que coincida en personaje y nombre (o el especificado por id).
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            if id_capitulo is not None:
                cur.execute("""
                UPDATE bandeja_capitulos
                SET archivos_movidos = archivos_movidos + ?
                WHERE id = ?
                """, (cantidad, id_capitulo))
            else:
                cur.execute("""
                UPDATE bandeja_capitulos
                SET archivos_movidos = archivos_movidos + ?
                WHERE personaje = ? AND nombre = ? AND estado = 'activo' AND (descartado IS NULL OR descartado = 0)
                """, (cantidad, personaje, escena))
                if cur.rowcount == 0:
                    cur.execute("""
                    UPDATE bandeja_capitulos
                    SET archivos_movidos = archivos_movidos + ?
                    WHERE personaje = ? AND nombre = ?
                    """, (cantidad, personaje, escena))
            con.commit()

    def calcular_balance_capitulo(self, personaje: str, nombre: str, verificar_disco: bool = False) -> Dict[str, int]:
        """
        Calcula la cantidad de archivos pendientes y ya movidos para un personaje y capítulo.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            SELECT ruta_actual FROM bandeja_archivos
            WHERE personaje = ? AND escena = ? AND estado IN ('detectado', 'clasificado')
            """, (personaje, nombre))
            filas = cur.fetchall()
            if verificar_disco:
                pendientes = sum(1 for f in filas if os.path.exists(f["ruta_actual"]))
            else:
                pendientes = len(filas)

            cur.execute("""
            SELECT archivos_movidos FROM bandeja_capitulos
            WHERE personaje = ? AND nombre = ?
            ORDER BY id DESC LIMIT 1
            """, (personaje, nombre))
            row_cap = cur.fetchone()
            mov_cap = row_cap["archivos_movidos"] if row_cap and row_cap["archivos_movidos"] is not None else 0

            cur.execute("""
            SELECT COUNT(*) as c FROM bandeja_archivos
            WHERE personaje = ? AND escena = ? AND estado = 'movido'
            """, (personaje, nombre))
            mov_arch = cur.fetchone()["c"]

            return {
                "pendientes": pendientes,
                "movidos": max(mov_cap, mov_arch)
            }

    def es_capitulo_olvidado(self, horas_limite: float = 12.0, ahora: Optional[datetime.datetime] = None) -> bool:
        """
        Determina si el capítulo activo excede las horas límite configuradas.
        """
        cap = self.obtener_capitulo_activo()
        if not cap or not cap.get("habilitado") or cap.get("estado") != "activo":
            return False

        fecha_ref_str = cap.get("fecha_ultimo_aviso") or cap.get("fecha_inicio")
        if not fecha_ref_str:
            return False

        try:
            fecha_ref = datetime.datetime.fromisoformat(fecha_ref_str)
        except (ValueError, TypeError):
            return False

        ahora_dt = ahora or datetime.datetime.now()
        diferencia_horas = (ahora_dt - fecha_ref).total_seconds() / 3600.0
        return diferencia_horas >= horas_limite


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
        if nombre_lower.startswith("_") or "_descartados" in nombre_lower:
            return False
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

    def obtener_personaje_de_alias_inicial(self, nombre_archivo: str) -> Optional[str]:
        """
        Deduce el personaje estrictamente a partir del alias que se encuentre
        al INICIO (prefijo) del nombre del archivo.
        Si el nombre contiene menciones a otros personajes en posiciones posteriores
        (ej: 'rolitirandoaguaalucie.jpg'), el personaje inicial ('roli') prevalece sin cambios.
        """
        nombre_lower = os.path.basename(nombre_archivo).lower()
        for al in self.alias_personajes:
            if nombre_lower.startswith(al):
                if al in ("roli", "laroli", "magui"):
                    return "roli"
                if al in ("lucie", "luci"):
                    return "lucie"
                if al in ("mailen",):
                    return "mailen"
                if "roli" in al or "magui" in al:
                    return "roli"
                if "lucie" in al or "luci" in al:
                    return "lucie"
                if "mailen" in al:
                    return "mailen"
                return "lucie"
        return None

    def extraer_escena_sugerida(self, nombre_archivo: str) -> str:
        """
        Extrae el nombre de escena sugerido a partir del nombre del archivo:
        - Remueve la extensión.
        - Remueve el sufijo de duplicados de Chrome ' (n)'.
        - Remueve números finales.
        - Conserva intacto el prefijo del personaje.
        Ejemplos:
          'lucie atendiendo (1).mp4' -> 'lucie atendiendo'
          'roliyacussi 02.mp4' -> 'roliyacussi'
          'lucieasado.mp4' -> 'lucieasado'
        """
        nombre_base, _ = os.path.splitext(os.path.basename(nombre_archivo))
        sug = re.sub(r"\s*\(\d+\)$", "", nombre_base)
        sug = re.sub(r"[\s_\-]*\d+$", "", sug).strip()
        sug = sug.rstrip(" _-").strip()
        return sug if sug else nombre_base

    def obtener_raiz_escena(self, nombre_archivo: str) -> Optional[str]:
        """
        Retorna la raíz de la escena para agrupación si el archivo comienza con un alias conocido,
        o None si es un archivo sin raíz reconocible (agrupable por ventana de tiempo).
        """
        pers = self.obtener_personaje_de_alias_inicial(nombre_archivo)
        if pers:
            sug = self.extraer_escena_sugerida(nombre_archivo)
            return sug.lower()
        return None

    def clasificar_archivo(self, nombre_archivo: str) -> str:
        """
        Retorna:
        - 'candidato': coincide con lista blanca y patrones (Grok, Nano Banana, Flow, Gemini, o alias al inicio).
        - 'sin_identificar': es archivo de media pero sin patrón conocido.
        - 'ignorar': fuera de la lista blanca, archivo temporal o coincidente con patrones_ignorar.
        """
        nombre_lower = os.path.basename(nombre_archivo).lower()
        _, ext = os.path.splitext(nombre_lower)

        # 1. Descartar patrones ignorados explícitamente (ej: Screenshot_*, Captura*)
        for pat in self.config.patrones_ignorar:
            if fnmatch.fnmatch(nombre_archivo, pat) or fnmatch.fnmatch(nombre_lower, pat.lower()):
                return "ignorar"

        # 2. Ignorar temporales inmediatamente
        if ext in self.config.extensiones_temporales:
            return "ignorar"

        # 3. Si no es extensión de media permitida, NUNCA se procesa
        if ext not in self.config.extensiones_media:
            return "ignorar"

        # 4. Si el nombre comienza con un alias de personaje, es candidato directo
        if self.obtener_personaje_de_alias_inicial(nombre_archivo) is not None:
            return "candidato"

        # 5. Evaluar patrones de proyecto conocidos
        # 5a. Grok video
        pat_grok_vid = self.config.patrones_candidatos.get("grok_video") or self.config.patrones_candidatos.get("grok", "grok-video-*")
        if fnmatch.fnmatch(nombre_lower, pat_grok_vid.lower()):
            return "candidato"

        # 5b. Grok image
        pat_grok_img = self.config.patrones_candidatos.get("grok_image", "grok-image-*")
        if fnmatch.fnmatch(nombre_lower, pat_grok_img.lower()):
            return "candidato"

        # 5c. Gemini
        pat_gemini = self.config.patrones_candidatos.get("gemini", "Gemini_Generated_Image_*")
        if fnmatch.fnmatch(nombre_archivo, pat_gemini) or fnmatch.fnmatch(nombre_lower, pat_gemini.lower()):
            return "candidato"

        # 5d. Nano Banana (14 dígitos)
        if self._regex_nano_banana.match(nombre_archivo):
            return "candidato"

        # 5e. Flow
        pat_flow = self.config.patrones_candidatos.get("flow", "").strip()
        if pat_flow and fnmatch.fnmatch(nombre_lower, pat_flow.lower()):
            return "candidato"

        # 6. Es archivo de media válido pero sin patrón conocido
        return "sin_identificar"


class ValidadorEscenas:
    """Valida nombres de escena contra restricciones de seguridad y sistemas de archivos."""

    @staticmethod
    def validar_nombre_escena(nombre: str, ruta_destino_base: str, ruta_descargas: str,
                              es_existente_descargas: bool = False, personaje: str = "lucie",
                              **kwargs) -> Tuple[bool, str]:
        """
        Valida que el nombre de escena sea seguro, cumpla reglas de longitud y caracteres,
        y no escape de su destino base.
        """
        if not nombre or not nombre.strip():
            return False, "El nombre de la escena no puede estar vacío."

        # Caracteres prohibidos y de control
        if ".." in nombre or "/" in nombre or "\\" in nombre:
            return False, "El nombre de la escena no puede contener separadores de ruta ('/', '\\') ni '..'."

        nombre_lower = nombre.strip().lower()
        if nombre_lower in ("_descartados", "_lucie", "_a_revisar", "_enviados") or "_descartados" in nombre_lower:
            return False, "El nombre de la escena no puede contener ni llamarse '_descartados'."

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
                ruta_final = os.path.join(ruta_destino_base, personaje, nombre)
                ruta_final_real = os.path.realpath(ruta_final)
                if not (ruta_final_real == base_confinada or ruta_final_real.startswith(base_confinada + os.sep)):
                    return False, "La ruta de la escena escapa de los límites permitidos del directorio de destino."
        except Exception as e:
            return False, f"Error al validar confinamiento de la escena: {str(e)}"

        return True, ""


def asegurar_carpeta_capitulo(
    personaje: str,
    nombre: str,
    ruta_destino_base: str,
    ruta_descargas: str = ""
) -> Dict[str, Any]:
    """
    Asegura la creación física y segura de la carpeta ~/Descargas/_lucie/<personaje>/<nombre>/
    al empezar o reabrir un capítulo.
    Valida previamente el nombre con ValidadorEscenas y el confinamiento con realpath.
    Si ya existía, no modifica ni borra nada y contabiliza los archivos existentes.
    """
    nombre_limpio = (nombre or "").strip()
    personaje_limpio = (personaje or "").strip().lower()
    if personaje_limpio not in ("lucie", "roli", "mailen"):
        raise ValueError(f"Personaje inválido: '{personaje}'. Debe ser 'lucie', 'roli' o 'mailen'.")

    if not nombre_limpio:
        raise ValueError("El nombre del capítulo no puede estar vacío.")

    valido, motivo = ValidadorEscenas.validar_nombre_escena(
        nombre_limpio, ruta_destino_base, ruta_descargas,
        es_existente_descargas=False, personaje=personaje_limpio
    )
    if not valido:
        raise ValueError(f"Nombre de capítulo inválido: {motivo}")

    carpeta = os.path.join(ruta_destino_base, personaje_limpio, nombre_limpio)
    base_confinada = os.path.realpath(ruta_destino_base)
    carpeta_real = os.path.realpath(carpeta)
    if not (carpeta_real == base_confinada or carpeta_real.startswith(base_confinada + os.sep)):
        raise ValueError("La ruta del capítulo escapa de los límites permitidos del directorio de destino.")

    ya_existia = os.path.exists(carpeta)
    total_archivos = 0
    if ya_existia:
        if not os.path.isdir(carpeta):
            raise ValueError(f"La ruta de destino existe pero no es un directorio: {carpeta}")
        for _, _, files in os.walk(carpeta):
            total_archivos += len(files)
        if total_archivos > 0:
            mensaje = f"La carpeta ya existía y tiene {total_archivos} archivos"
        else:
            mensaje = "La carpeta ya existía y está vacía"
    else:
        os.makedirs(carpeta, exist_ok=True)
        mensaje = "Carpeta creada exitosamente"

    return {
        "carpeta": carpeta,
        "ya_existia": ya_existia,
        "total_archivos": total_archivos,
        "mensaje": mensaje
    }


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
    """Agrupa archivos multimedia candidatos por raíz compartida y proximidad temporal."""

    def __init__(self, ventana_minutos: int = 10):
        self.ventana_segundos = ventana_minutos * 60

    def agrupar(self, candidatos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Agrupa los candidatos:
        1. Si hay mezcla de candidatos anteriores y nuevos, se particionan estrictamente
           para que ningún archivo anterior contamine los lotes nuevos.
        2. Archivos con raíz de escena reconocible (o capítulo asignado) se agrupan estrictamente
           por dicha raíz compartida, independientemente de la hora. Raíces distintas NUNCA se mezclan.
        3. Archivos sin raíz reconocible se agrupan por proximidad temporal (ventana_minutos).
        4. Los lotes resultantes se ordenan cronológicamente.
        """
        if not candidatos:
            return []

        # Partición estricta de lote mixto: anteriores y nuevos nunca comparten lote
        cand_nuevos = [c for c in candidatos if not c.get("es_anterior")]
        cand_ant = [c for c in candidatos if c.get("es_anterior")]
        if cand_nuevos and cand_ant:
            lotes_nuevos = self.agrupar(cand_nuevos)
            lotes_anteriores = self.agrupar(cand_ant)
            for l in lotes_nuevos:
                l["es_anterior"] = False
            for idx, l in enumerate(lotes_anteriores, 1):
                l["es_anterior"] = True
                l["escena_sugerida"] = ""
                l["lote_id"] = f"ant_{l['lote_id']}" if not l["lote_id"].startswith("ant_") else l["lote_id"]
                for a in l.get("archivos", []):
                    a["es_anterior"] = True
                    a["escena"] = ""
            return lotes_nuevos + lotes_anteriores

        # Separar candidatos con raíz reconocible de aquellos sin raíz
        con_raiz: Dict[str, List[Dict[str, Any]]] = {}
        sin_raiz: List[Dict[str, Any]] = []

        for item in candidatos:
            raiz = item.get("raiz_escena")
            if raiz:
                con_raiz.setdefault(raiz, []).append(item)
            else:
                sin_raiz.append(item)

        grupos_totales: List[List[Dict[str, Any]]] = []

        # 1. Agregar cada grupo de raíz compartida como un lote independiente
        for raiz_val, grupo in con_raiz.items():
            grupos_totales.append(sorted(grupo, key=lambda x: x["mtime"]))

        # 2. Agrupar los archivos sin raíz por proximidad temporal (ventana de 10 min)
        if sin_raiz:
            sin_raiz_ordenados = sorted(sin_raiz, key=lambda x: x["mtime"])
            lote_actual: List[Dict[str, Any]] = []
            for item in sin_raiz_ordenados:
                if not lote_actual:
                    lote_actual.append(item)
                else:
                    mtime_anterior = lote_actual[-1]["mtime"]
                    if (item["mtime"] - mtime_anterior) <= self.ventana_segundos:
                        lote_actual.append(item)
                    else:
                        grupos_totales.append(lote_actual)
                        lote_actual = [item]
            if lote_actual:
                grupos_totales.append(lote_actual)

        # 3. Ordenar todos los grupos cronológicamente por su mtime mínimo
        grupos_totales.sort(key=lambda g: min(x["mtime"] for x in g))

        # 4. Formatear la estructura de salida de cada lote
        resultado = []
        for idx, grupo in enumerate(grupos_totales, 1):
            mtime_min = min(g["mtime"] for g in grupo)
            mtime_max = max(g["mtime"] for g in grupo)
            fecha_legible = datetime.datetime.fromtimestamp(mtime_min).strftime("%Y-%m-%d %H:%M:%S")
            bytes_totales = sum(g["tamanio"] for g in grupo)
            lote_id = f"lote_{int(mtime_min)}_{idx}"

            es_ant = any(bool(g.get("es_anterior")) for g in grupo)

            # Extraer personaje y escena sugeridos para el lote si están disponibles
            personaje_sug = next((g.get("personaje") for g in grupo if g.get("personaje")), None)
            escena_sug = "" if es_ant else next((g.get("escena") for g in grupo if g.get("escena")), None)
            raiz_sug = "" if es_ant else next((g.get("raiz_escena") for g in grupo if g.get("raiz_escena")), None)

            for arch in grupo:
                if "fecha" not in arch and "mtime" in arch:
                    arch["fecha"] = datetime.datetime.fromtimestamp(arch["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
                if es_ant:
                    arch["es_anterior"] = True
                    arch["escena"] = ""

            resultado.append({
                "lote_id": lote_id,
                "numero": idx,
                "fecha": fecha_legible,
                "mtime_min": mtime_min,
                "mtime_max": mtime_max,
                "total_archivos": len(grupo),
                "total_bytes": bytes_totales,
                "personaje_sugerido": personaje_sug,
                "escena_sugerida": escena_sug,
                "raiz_escena": raiz_sug,
                "es_anterior": es_ant,
                "archivos": grupo
            })

        return resultado


def generar_html_simulacion(simulacion: Dict[str, Any]) -> str:
    """
    Genera el marcado HTML para el modal de simulación previa.
    Muestra para cada archivo 'nombre_original -> nombre_nuevo' y la ruta de destino
    (manteniendo la ruta de destino completa en el tooltip title de cada archivo).
    Elimina las etiquetas legadas de subcarpetas de tipo (imagenes / videos sin editar).
    """
    personaje = html.escape(str(simulacion.get("personaje", "")))
    escena = html.escape(str(simulacion.get("escena", "")))
    es_descargas = simulacion.get("es_existente_descargas", False)
    descargas_tag = " (En Descargas)" if es_descargas else ""

    alerta_personaje = ""
    if simulacion.get("diferente_personaje_capitulo"):
        pers_cap = html.escape(str(simulacion.get("personaje_capitulo", "")))
        alerta_personaje = (
            f'<div style="margin:8px 0 14px 0; padding:10px 14px; background:rgba(234, 179, 8, 0.15); border:1px solid #eab308; border-radius:6px; color:#fde047; font-size:0.9rem;">'
            f'<strong>Aviso de Personaje:</strong> El personaje seleccionado para este lote es <strong>{personaje}</strong>, '
            f'el cual difiere del personaje del capítulo activo (<strong>{pers_cap}</strong>). '
            f'Los archivos se moverán a la ruta resultante: <code>_lucie/{personaje}/{escena}</code>.'
            f'</div>\n'
        )

    filas = []
    for m in simulacion.get("movimientos", []):
        origen = m.get("origen", "")
        destino_completo = m.get("destino", "")
        destino_relativo = m.get("destino_relativo") or destino_completo
        nombre_original = m.get("nombre_original") or os.path.basename(origen)
        nombre_nuevo = m.get("nombre_nuevo") or os.path.basename(destino_completo)

        destino_limpio = destino_relativo.replace("\\", "/")

        origen_esc = html.escape(origen)
        destino_esc = html.escape(destino_completo)
        nombre_orig_esc = html.escape(nombre_original)
        nombre_nuev_esc = html.escape(nombre_nuevo)
        destino_limpio_esc = html.escape(destino_limpio)

        fila = (
            f'<tr>'
            f'<td><strong>{nombre_orig_esc}</strong> &rarr; <span class="badge-renombrado" style="color:var(--accent-primary, #60a5fa); font-weight:600;">{nombre_nuev_esc}</span></td>'
            f'<td class="ruta-celda" title="{origen_esc}"><small style="color:var(--text-muted)">{origen_esc}</small></td>'
            f'<td class="ruta-celda destino-celda" title="{destino_esc}" data-destino="{destino_esc}">{destino_limpio_esc}</td>'
            f'</tr>'
        )
        filas.append(fila)

    filas_html = "\n".join(filas)
    return (
        f'{alerta_personaje}'
        f'<p><strong>Personaje:</strong> {personaje} | <strong>Escena:</strong> {escena}{descargas_tag}</p>\n'
        f'<table class="modal-tabla">\n'
        f'  <thead>\n'
        f'    <tr>\n'
        f'      <th style="width:35%;">Archivo (Renombrado)</th>\n'
        f'      <th style="width:30%;">Origen</th>\n'
        f'      <th style="width:35%;">Destino</th>\n'
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
    renombrado automático atómico (<base><número>.<ext> con contadores separados para fotos y videos),
    registro en bitácora .jsonl y reversión estricta (deshacer).
    """

    EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp"}
    EXTENSIONES_VIDEO = {".mp4", ".mov", ".webm"}

    def __init__(self, ruta_descargas: str, ruta_destino_base: str, db: GestorBaseDatosBandeja,
                 ruta_bitacora: str = "bitacora_bandeja.jsonl", ruta_alias: str = "alias-personajes.json",
                 **kwargs):
        self.ruta_descargas = os.path.realpath(ruta_descargas)
        self.ruta_destino_base = os.path.realpath(ruta_destino_base)
        self.db = db
        self.ruta_bitacora = ruta_bitacora
        self.ruta_alias = ruta_alias
        self.alias_map = self._cargar_alias(ruta_alias)
        self._lock = threading.Lock()

    def asegurar_carpeta_capitulo(self, personaje: str, nombre: str) -> Dict[str, Any]:
        """Asegura la creación segura y validada de la carpeta de capítulo en el destino."""
        return asegurar_carpeta_capitulo(personaje, nombre, self.ruta_destino_base, self.ruta_descargas)

    def _cargar_alias(self, ruta_alias: Optional[str]) -> Dict[str, Set[str]]:
        alias_map: Dict[str, Set[str]] = {
            "lucie": {"lucie", "luci"},
            "roli": {"roli", "laroli", "magui"},
            "mailen": {"mailen"}
        }
        if ruta_alias and os.path.exists(ruta_alias):
            try:
                with open(ruta_alias, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                if isinstance(datos, dict):
                    if "reglas" in datos:
                        for r in datos.get("reglas", []):
                            pers = str(r.get("personaje", "")).strip().lower()
                            if pers:
                                if pers not in alias_map:
                                    alias_map[pers] = {pers}
                                for pat in r.get("patrones", []):
                                    limpio = pat.replace("*", "").strip().lower()
                                    if limpio:
                                        alias_map[pers].add(limpio)
                    else:
                        for pers, pats in datos.items():
                            p_key = str(pers).strip().lower()
                            if p_key not in alias_map:
                                alias_map[p_key] = {p_key}
                            if isinstance(pats, list):
                                for pat in pats:
                                    limpio = str(pat).replace("*", "").strip().lower()
                                    if limpio:
                                        alias_map[p_key].add(limpio)
            except Exception:
                pass
        return alias_map

    def _validar_confinamiento(self, ruta: str):
        """Asegura que la ruta canónica permanezca estrictamente dentro de ~/Descargas."""
        real = os.path.realpath(ruta)
        if not (real == self.ruta_descargas or real.startswith(self.ruta_descargas + os.sep)):
            raise ErrorSeguridadBandeja(f"Violación de seguridad: la ruta '{ruta}' no pertenece a ~/Descargas.")

    def _validar_confinamiento_destino_base(self, ruta: str):
        """Asegura que la ruta canónica permanezca estrictamente dentro de ~/Descargas/_lucie y rechaza symlinks."""
        base_confinada = os.path.realpath(self.ruta_destino_base)
        real = os.path.realpath(ruta)
        if not (real == base_confinada or real.startswith(base_confinada + os.sep)):
            raise ErrorSeguridadBandeja(
                f"Violación de seguridad: la ruta '{ruta}' escapa del confinamiento de '{base_confinada}'."
            )
        if os.path.islink(ruta):
            raise ErrorSeguridadBandeja(f"Violación de seguridad: '{ruta}' es un enlace simbólico no permitido.")

    def calcular_base_escena(self, personaje: str, nombre_escena: str) -> str:
        """
        Calcula la base del nombre para los archivos a mover:
        - Omitir el prefijo SOLO si la escena (en minúscula y compacta) empieza con el nombre del
          personaje elegido o con un alias de ESE personaje.
        - Si empieza con un alias de OTRO personaje, o con ninguno, la base es <personaje><escena_compacta>.
        - Elimina todos los espacios internos y caracteres de separación visual para dejar
          un estilo compacto (ej. 'lucie trapitos' -> 'lucietrapitos').
        - Garantiza que obtener_personaje_de_alias_inicial deduzca exactamente el personaje elegido.
        """
        pers = (personaje or "lucie").strip().lower()
        escena_raw = (nombre_escena or "").strip().lower()
        # Eliminar todos los espacios internos y caracteres de separación visual
        escena_compacta = re.sub(r'[\s]+', '', escena_raw)

        # Determinar el personaje canónico si se ingresó un alias
        pers_canonico = pers
        for can, aliases in self.alias_map.items():
            if pers == can or pers in aliases:
                pers_canonico = can
                break

        # Conjunto de alias exclusivos de este personaje
        sus_alias = set(self.alias_map.get(pers_canonico, {pers_canonico})) | {pers_canonico, pers}
        alias_ordenados = sorted(sus_alias, key=len, reverse=True)

        for al in alias_ordenados:
            if escena_compacta.startswith(al):
                return escena_compacta

        return f"{pers_canonico}{escena_compacta}"

    @classmethod
    def clasificar_familia_medio(cls, extension: str) -> str:
        """Clasifica la extensión en familia 'foto', 'video' u 'otro'."""
        ext = extension.strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        if ext in cls.EXTENSIONES_FOTO:
            return "foto"
        if ext in cls.EXTENSIONES_VIDEO:
            return "video"
        return "otro"

    def obtener_contadores_carpeta_destino(self, carpeta_destino: str, base: str) -> Dict[str, int]:
        """
        Inspecciona la carpeta destino buscando archivos existentes que coincidan con la base
        mediante regex case-insensitive ^<base>(\\d+)(?:\\s*\\(\\d+\\))?\\.<ext>$.
        Retorna el número inicial a usar para cada tipo: max_existente + 1.
        """
        max_foto = 0
        max_video = 0
        max_otro = 0

        if os.path.exists(carpeta_destino) and os.path.isdir(carpeta_destino):
            patron = re.compile(rf"^{re.escape(base)}(\d+)(?:\s*\(\d+\))?\.([a-zA-Z0-9]+)$", re.IGNORECASE)
            try:
                for f in os.listdir(carpeta_destino):
                    m = patron.match(f)
                    if m:
                        num = int(m.group(1))
                        ext = "." + m.group(2).lower()
                        familia = self.clasificar_familia_medio(ext)
                        if familia == "foto":
                            if num > max_foto:
                                max_foto = num
                        elif familia == "video":
                            if num > max_video:
                                max_video = num
                        else:
                            if num > max_otro:
                                max_otro = num
            except OSError:
                pass

        return {
            "foto": max_foto + 1,
            "video": max_video + 1,
            "otro": max_otro + 1
        }

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
                                nombre_escena: str, es_existente_descargas: bool = False,
                                destinos_reservados: Optional[Set[str]] = None) -> Dict[str, Any]:
        """Calcula el origen y destino exactos para cada archivo del lote antes de mover con renombrado."""
        # 1. Validar nombre de escena
        valido, motivo = ValidadorEscenas.validar_nombre_escena(
            nombre_escena, self.ruta_destino_base, self.ruta_descargas,
            es_existente_descargas=es_existente_descargas, personaje=personaje
        )
        if not valido:
            raise ErrorValidacionEscena(motivo)

        base = self.calcular_base_escena(personaje, nombre_escena)

        if es_existente_descargas:
            carpeta_destino = os.path.join(self.ruta_descargas, nombre_escena)
            base_rel = self.ruta_descargas
        else:
            carpeta_destino = os.path.join(self.ruta_destino_base, personaje, nombre_escena)
            base_rel = self.ruta_destino_base

        self._validar_confinamiento(carpeta_destino)

        # Contadores iniciales según archivos existentes en la carpeta de destino
        contadores = self.obtener_contadores_carpeta_destino(carpeta_destino, base)

        # Archivos existentes en disco (case-insensitive para FAT32/exFAT)
        archivos_disco_lower: Set[str] = set()
        if os.path.exists(carpeta_destino) and os.path.isdir(carpeta_destino):
            try:
                archivos_disco_lower = {f.lower() for f in os.listdir(carpeta_destino)}
            except OSError:
                pass

        # Conjunto de rutas destino reservadas (en minúsculas)
        destinos_vistos: Set[str] = set()
        if destinos_reservados:
            destinos_vistos.update(d.lower() for d in destinos_reservados)

        # Ordenar archivos del lote por mtime ascendente y desempate por nombre original
        def _orden_key(item: Dict[str, Any]) -> Tuple[float, str]:
            r = item.get("ruta", "")
            n = os.path.basename(r).lower()
            try:
                mt = os.path.getmtime(r)
            except OSError:
                mt = 0.0
            return (mt, n)

        archivos_ordenados = sorted(archivos, key=_orden_key)
        movimientos_simulados = []

        for arch in archivos_ordenados:
            origen = os.path.realpath(arch["ruta"])
            self._validar_confinamiento(origen)
            nombre_archivo_original = os.path.basename(origen)
            _, ext_raw = os.path.splitext(nombre_archivo_original)
            ext_lower = ext_raw.lower()
            familia = self.clasificar_familia_medio(ext_lower)

            # Asignar siguiente número correlativo disponible sin colisiones
            while True:
                num = contadores[familia]
                nombre_candidato = f"{base}{num}{ext_lower}"
                ruta_candidata = os.path.join(carpeta_destino, nombre_candidato)
                nombre_candidato_lower = nombre_candidato.lower()
                ruta_candidata_lower = ruta_candidata.lower()
                contadores[familia] += 1

                if nombre_candidato_lower not in archivos_disco_lower and ruta_candidata_lower not in destinos_vistos:
                    destinos_vistos.add(ruta_candidata_lower)
                    destino_final = ruta_candidata
                    nombre_nuevo = nombre_candidato
                    break

            destino_relativo = os.path.relpath(destino_final, base_rel).replace("\\", "/")

            movimientos_simulados.append({
                "id_db": arch.get("id_db"),
                "origen": origen,
                "destino": destino_final,
                "destino_relativo": destino_relativo,
                "nombre_original": nombre_archivo_original,
                "nombre_nuevo": nombre_nuevo,
                "subcarpeta_tipo": "",
                "tamanio": arch.get("tamanio", 0),
                "hash": arch.get("hash", "")
            })

        diferente_personaje_capitulo = False
        personaje_capitulo = None
        if self.db:
            try:
                cap_activo = self.db.obtener_capitulo_activo()
                if cap_activo and cap_activo.get("habilitado") and cap_activo.get("nombre"):
                    personaje_capitulo = cap_activo.get("personaje")
                    if personaje_capitulo and personaje_capitulo.lower() != personaje.lower():
                        diferente_personaje_capitulo = True
            except Exception:
                pass

        resultado_sim = {
            "valido": True,
            "personaje": personaje,
            "escena": nombre_escena,
            "base": base,
            "es_existente_descargas": es_existente_descargas,
            "total_archivos": len(movimientos_simulados),
            "movimientos": movimientos_simulados,
            "diferente_personaje_capitulo": diferente_personaje_capitulo,
            "personaje_capitulo": personaje_capitulo
        }
        resultado_sim["html"] = generar_html_simulacion(resultado_sim)
        return resultado_sim

    def ejecutar_movimiento_lote(self, simulacion: Dict[str, Any], lote_id: str) -> Dict[str, Any]:
        """Ejecuta los movimientos atómicos con os.rename renombrando al destino y los asienta en la bitácora .jsonl."""
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

                # Red de seguridad final para garantizar inexistencia previa
                destino_final = self.resolver_destino_sin_colision(destino)

                # Mover y renombrar atómicamente en el mismo sistema de archivos (sin borrar, sin pisar)
                os.rename(origen, destino_final)

                # Calcular hash si no estaba calculado
                hash_val = item.get("hash") or calcular_sha256(destino_final)

                nombre_orig = item.get("nombre_original") or os.path.basename(origen)
                nombre_nuev = os.path.basename(destino_final)

                # Actualizar base de datos SQLite con la nueva ruta y nombre
                self.db.registrar_o_actualizar(
                    hash_val=hash_val,
                    ruta_actual=destino_final,
                    estado="movido",
                    personaje=simulacion["personaje"],
                    escena=simulacion["escena"]
                )

                movimientos_realizados.append({
                    "origen_anterior": origen,
                    "destino_nuevo": destino_final,
                    "nombre_original": nombre_orig,
                    "nombre_nuevo": nombre_nuev,
                    "hash": hash_val,
                    "tamanio": item["tamanio"]
                })

            # Guardar último personaje usado
            self.db.guardar_ultimo_personaje(simulacion["personaje"])
            # Incrementar contador de movidos para el capítulo si corresponde
            self.db.incrementar_movidos_capitulo(simulacion["personaje"], simulacion["escena"], len(movimientos_realizados))

            # Escribir en la bitácora reversible .jsonl
            registro_bitacora = {
                "id_operacion": id_operacion,
                "lote_id": lote_id,
                "fecha": fecha_iso,
                "personaje": simulacion["personaje"],
                "escena": simulacion["escena"],
                "base": simulacion.get("base", ""),
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

    def simular_descartar_capitulo(self, capitulo_id: int) -> Dict[str, Any]:
        """
        Simula el descarte de un capítulo moviéndolo hacia ~/Descargas/_lucie/_descartados/<personaje>/<escena>_<timestamp>/.
        Retorna origen, destino, conteo de archivos, peso total y aviso anti-borrado.
        """
        cap = self.db.obtener_capitulo_por_id(capitulo_id)
        if not cap:
            raise ValueError(f"Capítulo con ID {capitulo_id} no encontrado.")

        personaje = cap.get("personaje", "lucie").strip().lower()
        nombre = cap.get("nombre", "").strip()

        valido, motivo = ValidadorEscenas.validar_nombre_escena(
            nombre, self.ruta_destino_base, self.ruta_descargas,
            es_existente_descargas=False, personaje=personaje
        )
        if not valido:
            raise ErrorValidacionEscena(f"Nombre de capítulo inválido para descarte: {motivo}")

        origen_carpeta = os.path.join(self.ruta_destino_base, personaje, nombre)
        self._validar_confinamiento_destino_base(origen_carpeta)

        # Destino dentro de _descartados
        fecha_tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        nombre_dest = f"{nombre}_{fecha_tag}"
        destino_base = os.path.join(self.ruta_destino_base, "_descartados", personaje, nombre_dest)
        self._validar_confinamiento_destino_base(destino_base)

        destino_carpeta = destino_base
        sufijo = 1
        while os.path.exists(destino_carpeta):
            destino_carpeta = f"{destino_base} ({sufijo})"
            sufijo += 1

        carpeta_existe = os.path.exists(origen_carpeta) and os.path.isdir(origen_carpeta)
        archivos_encontrados = []
        peso_total = 0

        if carpeta_existe:
            if os.path.islink(origen_carpeta):
                raise ErrorSeguridadBandeja(f"Violación de seguridad: '{origen_carpeta}' es un enlace simbólico.")
            base_real = os.path.realpath(self.ruta_destino_base)
            for root, dirs, files in os.walk(origen_carpeta):
                for d in dirs:
                    d_path = os.path.join(root, d)
                    if os.path.islink(d_path):
                        real_d = os.path.realpath(d_path)
                        if not (real_d == base_real or real_d.startswith(base_real + os.sep)):
                            raise ErrorSeguridadBandeja(f"Symlink saliente detectado en directorio: '{d_path}' -> '{real_d}'.")
                for f in files:
                    f_path = os.path.join(root, f)
                    if os.path.islink(f_path):
                        real_f = os.path.realpath(f_path)
                        if not (real_f == base_real or real_f.startswith(base_real + os.sep)):
                            raise ErrorSeguridadBandeja(f"Symlink saliente detectado en archivo: '{f_path}' -> '{real_f}'.")
                    try:
                        sz = os.path.getsize(f_path)
                    except OSError:
                        sz = 0
                    peso_total += sz
                    archivos_encontrados.append({
                        "nombre": f,
                        "ruta_relativa": os.path.relpath(f_path, origen_carpeta),
                        "tamanio": sz
                    })

        total_archivos = len(archivos_encontrados)
        carpeta_vacia = (total_archivos == 0)

        if carpeta_existe:
            if carpeta_vacia:
                aviso = "La carpeta está vacía: se moverá a _descartados y se puede deshacer."
            else:
                aviso = "Esto NO borra: mueve a _descartados y se puede deshacer."
        else:
            aviso = "La carpeta no existe en disco. El capítulo se marcará como descartado en la base de datos."

        return {
            "valido": True,
            "capitulo_id": capitulo_id,
            "personaje": personaje,
            "escena": nombre,
            "origen_carpeta": origen_carpeta,
            "destino_carpeta": destino_carpeta,
            "total_archivos": total_archivos,
            "peso_total": peso_total,
            "peso_total_fmt": formatear_bytes(peso_total),
            "carpeta_existe": carpeta_existe,
            "carpeta_vacia": carpeta_vacia,
            "aviso": aviso,
            "archivos": archivos_encontrados
        }

    def ejecutar_descartar_capitulo(self, simulacion: Dict[str, Any], nombre_confirmacion: str) -> Dict[str, Any]:
        """
        Ejecuta el descarte del capítulo trasladando su carpeta a _descartados con un único os.rename.
        Exige coincidencia exacta de nombre_confirmacion con el nombre del capítulo.
        """
        escena_esperada = simulacion.get("escena", "")
        if not nombre_confirmacion or nombre_confirmacion != escena_esperada:
            raise ValueError(
                f"Confirmación inválida: debe escribir exactamente '{escena_esperada}' para confirmar el descarte."
            )

        capitulo_id = simulacion["capitulo_id"]
        personaje = simulacion["personaje"]
        origen_carpeta = simulacion["origen_carpeta"]
        destino_carpeta = simulacion["destino_carpeta"]
        carpeta_existe = bool(simulacion.get("carpeta_existe"))
        carpeta_vacia = bool(simulacion.get("carpeta_vacia"))

        with self._lock:
            # Revalidar confinamiento
            self._validar_confinamiento_destino_base(origen_carpeta)
            self._validar_confinamiento_destino_base(destino_carpeta)

            movio_carpeta = False
            if carpeta_existe:
                if not os.path.exists(origen_carpeta):
                    raise ErrorMovimiento(f"La carpeta origen '{origen_carpeta}' ya no existe.")
                if os.path.exists(destino_carpeta):
                    raise ErrorMovimiento(f"El destino '{destino_carpeta}' ya existe.")

                os.makedirs(os.path.dirname(destino_carpeta), exist_ok=True)
                os.rename(origen_carpeta, destino_carpeta)
                movio_carpeta = True
                self.db.actualizar_rutas_archivos_descarte(origen_carpeta, destino_carpeta, es_reversion=False)

            # Verificar si era el capítulo activo antes de marcarlo como descartado
            era_activo = False
            cap_activo = self.db.obtener_capitulo_activo()
            if cap_activo and cap_activo.get("habilitado") and cap_activo.get("id") == capitulo_id:
                era_activo = True

            # Marcar en base de datos
            self.db.marcar_capitulo_descartado(capitulo_id, descartado=True)

            if era_activo:
                self.db.guardar_capitulo_activo("", "", False)

            # Escribir en bitácora
            id_operacion = f"op_desc_{int(time.time())}_{secrets.token_hex(4)}"
            fecha_iso = datetime.datetime.now().isoformat()
            registro_bitacora = {
                "evento": "descartar_capitulo",
                "id_operacion": id_operacion,
                "capitulo_id": capitulo_id,
                "personaje": personaje,
                "escena": escena_esperada,
                "origen_carpeta": origen_carpeta if movio_carpeta else "",
                "destino_carpeta": destino_carpeta if movio_carpeta else "",
                "total_archivos": simulacion.get("total_archivos", 0),
                "peso_total": simulacion.get("peso_total", 0),
                "fecha": fecha_iso
            }
            with open(self.ruta_bitacora, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro_bitacora, ensure_ascii=False) + "\n")

            if movio_carpeta:
                if carpeta_vacia:
                    mensaje = f"Capítulo '{escena_esperada}' descartado. Se movió la carpeta vacía a _descartados."
                else:
                    mensaje = f"Capítulo '{escena_esperada}' descartado. Se movieron {simulacion.get('total_archivos', 0)} archivos a _descartados."
            else:
                mensaje = f"Capítulo '{escena_esperada}' descartado en la base de datos (no existía carpeta en disco)."

            return {
                "exito": True,
                "id_operacion": id_operacion,
                "capitulo_id": capitulo_id,
                "personaje": personaje,
                "escena": escena_esperada,
                "mensaje": mensaje,
                "total_archivos": simulacion.get("total_archivos", 0),
                "destino": destino_carpeta if movio_carpeta else ""
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
                        try:
                            op = json.loads(linea)
                            todas_operaciones.append(op)
                            if op.get("id_operacion") == id_operacion:
                                operacion_encontrada = op
                        except Exception:
                            pass

            if not operacion_encontrada:
                raise ErrorDeshacer(f"No se encontró la operación '{id_operacion}' en la bitácora.")

            for op in todas_operaciones:
                if op.get("evento") == "deshacer" and op.get("id_operacion_revertida") == id_operacion:
                    raise ErrorDeshacer(f"La operación '{id_operacion}' ya fue deshecha previamente.")

            # Caso especial: Reversión de descarte de capítulo
            if operacion_encontrada.get("evento") == "descartar_capitulo":
                origen_carpeta = operacion_encontrada.get("origen_carpeta", "")
                destino_carpeta = operacion_encontrada.get("destino_carpeta", "")
                cap_id = operacion_encontrada.get("capitulo_id")
                total_archivos = operacion_encontrada.get("total_archivos", 0)

                if origen_carpeta and destino_carpeta:
                    if not os.path.exists(destino_carpeta):
                        raise ErrorDeshacer(
                            f"No se puede deshacer: la carpeta descartada '{destino_carpeta}' ya no existe o fue alterada externamente."
                        )
                    if os.path.exists(origen_carpeta):
                        raise ErrorDeshacer(
                            f"No se puede deshacer: la ruta original '{origen_carpeta}' ya se encuentra ocupada. "
                            f"No se sobrescribe ni se altera ningún archivo."
                        )
                    os.makedirs(os.path.dirname(origen_carpeta), exist_ok=True)
                    os.rename(destino_carpeta, origen_carpeta)
                    self.db.actualizar_rutas_archivos_descarte(destino_carpeta, origen_carpeta, es_reversion=True)

                if cap_id:
                    self.db.marcar_capitulo_descartado(cap_id, descartado=False)

                evento_reversion = {
                    "evento": "deshacer",
                    "id_operacion_revertida": id_operacion,
                    "fecha": datetime.datetime.now().isoformat(),
                    "total_revertidos": total_archivos
                }
                with open(self.ruta_bitacora, "a", encoding="utf-8") as f:
                    f.write(json.dumps(evento_reversion, ensure_ascii=False) + "\n")

                return {
                    "exito": True,
                    "id_operacion": id_operacion,
                    "total_revertidos": total_archivos,
                    "mensaje": f"Capítulo '{operacion_encontrada.get('escena')}' restaurado exitosamente a su ubicación original."
                }

            # Fase 1: Verificación preventiva integral para movimientos normales
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

            # Fase 2: Ejecución de la reversión con os.rename restaurando nombre original
            archivos_revertidos = []
            for mov in operacion_encontrada["movimientos"]:
                origen_anterior = mov["origen_anterior"]
                destino_nuevo = mov["destino_nuevo"]

                os.makedirs(os.path.dirname(origen_anterior), exist_ok=True)
                os.rename(destino_nuevo, origen_anterior)

                # Actualizar estado en la base SQLite restaurando la ruta original
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
        Mantiene compatibilidad con líneas legadas que no incluyan nombre_original o nombre_nuevo.
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

                if e.get("evento") == "descartar_capitulo":
                    estado = "deshecho" if id_op in revertidas else "descartado"
                    escena_nombre = e.get("escena", "")
                    pers = e.get("personaje", "")
                    origen = e.get("origen_carpeta", "")
                    destino = e.get("destino_carpeta", "")
                    movimientos_resultado.append({
                        "id_operacion": id_op,
                        "fecha": fecha_op,
                        "archivo": f"Capítulo '{escena_nombre}' ({pers})",
                        "nombre_original": escena_nombre,
                        "nombre_nuevo": os.path.basename(destino) if destino else "(sin carpeta)",
                        "origen": origen or "(sin carpeta)",
                        "destino": destino or "(sin carpeta)",
                        "tamanio": e.get("peso_total", 0),
                        "hash": "",
                        "estado": estado,
                        "tipo_evento": "descartar_capitulo"
                    })
                    if len(movimientos_resultado) >= limite:
                        return movimientos_resultado
                    continue

                estado = "deshecho" if id_op in revertidas else "movido"

                for mov in reversed(e.get("movimientos", [])):
                    origen = mov.get("origen_anterior", "")
                    destino = mov.get("destino_nuevo", "")
                    nombre_orig = mov.get("nombre_original") or os.path.basename(origen)
                    nombre_nuev = mov.get("nombre_nuevo") or os.path.basename(destino)
                    movimientos_resultado.append({
                        "id_operacion": id_op,
                        "fecha": fecha_op,
                        "archivo": nombre_orig,
                        "nombre_original": nombre_orig,
                        "nombre_nuevo": nombre_nuev,
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
        self._lotes_anteriores_actuales: List[Dict[str, Any]] = []
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
            except OSError:
                continue

            # Comprobar si el archivo es anterior al capítulo en foco
            es_anterior = False
            if es_cap_foco and mtime < ts_corte_capitulo:
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
                if tipo_clasificacion == "candidato":
                    pers_alias = self.filtro.obtener_personaje_de_alias_inicial(entrada)
                    personaje_actual = pers_alias
                    escena_actual = None
                    raiz_escena = None
                    estado_actual = "detectado"
                    id_db = self.db.registrar_o_actualizar(
                        hash_val, ruta_completa, "detectado",
                        personaje=personaje_actual, escena=None, limpiar_escena=True
                    )
                else:
                    personaje_actual = None
                    escena_actual = None
                    raiz_escena = None
                    estado_actual = "detectado"
                    id_db = self.db.registrar_o_actualizar(
                        hash_val, ruta_completa, "detectado",
                        personaje=None, escena=None, limpiar_escena=True
                    )
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
                        id_db = self.db.registrar_o_actualizar(
                            hash_val, ruta_completa, "clasificado",
                            personaje=personaje_actual, escena=escena_actual
                        )
                        raiz_escena = f"{personaje_actual}::{escena_actual}"
                    else:
                        # Modo de respaldo por alias al inicio sin capítulo en foco
                        pers_alias = self.filtro.obtener_personaje_de_alias_inicial(entrada)
                        if pers_alias:
                            personaje_actual = pers_alias
                            escena_actual = self.filtro.extraer_escena_sugerida(entrada)
                            raiz_escena = self.filtro.obtener_raiz_escena(entrada)
                            id_db = self.db.registrar_o_actualizar(
                                hash_val, ruta_completa, "detectado",
                                personaje=personaje_actual, escena=escena_actual
                            )
                            estado_actual = "detectado"
                        else:
                            personaje_actual = None
                            escena_actual = None
                            raiz_escena = None
                            id_db = self.db.registrar_o_actualizar(hash_val, ruta_completa, "detectado")
                            estado_actual = "detectado"

            item_info = {
                "id_db": id_db,
                "nombre": entrada,
                "ruta": ruta_completa,
                "tamanio": tamanio,
                "mtime": mtime,
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
                    if os.path.isdir(carpeta_pers):
                        for sub in os.listdir(carpeta_pers):
                            ruta_sub = os.path.join(carpeta_pers, sub)
                            if os.path.isdir(ruta_sub) and sub not in ("videos sin editar", "imagenes", "_descartados") and not sub.startswith("_"):
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
                                if os.path.isdir(ruta_sub) and not sub.startswith("_"):
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

        with self._lock:
            self._lotes_actuales = lotes_generados
            self._lotes_anteriores_actuales = lotes_anteriores
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
                "lotes_anteriores": list(self._lotes_anteriores_actuales),
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
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada.")

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
        else:
            self._enviar_error(HTTPStatus.NOT_FOUND, "Endpoint POST no encontrado.")

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
      background: rgba(3, 218, 198, 0.2);
      color: var(--teal);
      border: 1px solid var(--teal);
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: bold;
      text-transform: uppercase;
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
      border: 1px solid #6366f1;
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
    <button class="nav-btn" id="nav-btn-capitulos-abiertos" onclick="mostrarPestana('capitulos-abiertos', event)">Capítulos Abiertos (<span id="conteo-nav-abiertos">0</span>)</button>
    <button class="nav-btn" id="nav-btn-capitulos-cerrados" onclick="mostrarPestana('capitulos-cerrados', event)">Capítulos Cerrados</button>
    <button class="nav-btn" id="nav-btn-descartados" onclick="mostrarPestana('descartados', event)">Descartados</button>
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
          <span class="badge-capitulo-activo">En Foco</span>
          <span id="banner-capitulo-titulo" style="font-weight:700; font-size:1.1rem; color:#e0e7ff;">Capítulo en foco:</span>
          <span id="banner-otros-abiertos" style="font-size:0.85rem; color:#a5b4fc; cursor:pointer; text-decoration:underline;" onclick="mostrarPestana('capitulos-abiertos')"></span>
        </div>
        <div id="banner-capitulo-subtitulo" style="font-size:0.85rem; color:#a5b4fc; margin-top:4px;">
          Cargando detalles...
        </div>
      </div>
      <div style="display:flex; gap:10px; align-items:center;">
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

  <script>
    const CSRF_TOKEN = "{self.token_csrf}";
    let datosEstado = {{ lotes: [], lotes_anteriores: [], sin_identificar: [], escenas: [], personajes: [], ultimo_personaje: "lucie", capitulo_activo: null, capitulo_foco: null, capitulos_abiertos: [], cantidad_abiertos: 0, alerta_olvidado: false, horas_limite: 12, balance_capitulo: {{ pendientes: 0, movidos: 0 }} }};
    let simulacionActiva = null;
    let descarteSimulacionActiva = null;
    let loteActivoId = null;
    let terminarCapituloTrasMover = false;
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
      document.getElementById('sec-historial').style.display = (pestana === 'historial') ? 'block' : 'none';

      if (pestana === 'historial') {{
        cargarHistorial();
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
        const [lotesRes, sinIdRes, escenasRes, persRes, capRes] = await Promise.all([
          apiFetch('/api/lotes'),
          apiFetch('/api/sin-identificar'),
          apiFetch('/api/escenas'),
          apiFetch('/api/personajes'),
          apiFetch('/api/capitulos/estado')
        ]);
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
                    <button class="btn-sm" onclick="reabrirCapitulo(${{c.id}})" style="background:var(--teal); color:#000; font-weight:600; padding:4px 10px; border-radius:4px; border:none; cursor:pointer;">
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

    function renderLotes() {{
      const cont = document.getElementById('contenedor-lotes');
      const lotesActivos = (datosEstado.lotes || []).filter(l => !l.es_anterior);
      if (!lotesActivos.length) {{
        cont.innerHTML = '<div class="card"><p style="color:var(--text-muted)">No hay nuevos lotes de candidatos en ~/Descargas.</p></div>';
        return;
      }}

      const capFoco = (datosEstado.capitulo_foco && datosEstado.capitulo_foco.habilitado) ? datosEstado.capitulo_foco : 
                      ((datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado) ? datosEstado.capitulo_activo : null);
      const capsAbiertos = datosEstado.capitulos_abiertos || [];
      const nombresAbiertos = new Set(capsAbiertos.map(c => c.nombre));

      cont.innerHTML = lotesActivos.map(lote => {{
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
      }}).join('');
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

      cont.innerHTML = lotesAnt.map(lote => {{
        const persPre = lote.personaje_sugerido || datosEstado.ultimo_personaje || 'lucie';
        const escenaPre = '';

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
                <div class="archivo-item" title="Archivo: ${{a.nombre}}&#10;Fecha: ${{a.fecha || lote.fecha || ''}}&#10;Tamaño: ${{formatearBytes(a.tamanio)}}">
                  <div class="chk-container">
                    <input type="checkbox" class="chk-archivo chk-lote-${{lote.lote_id}}" data-id="${{a.id_db}}" onchange="actualizarSeleccionLote('${{lote.lote_id}}')">
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
        cont.innerHTML = `
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
                  <td><strong>${{escapeHTML(m.nombre_original || m.origen.split('/').pop())}}</strong> &rarr; <span class="badge-renombrado" style="color:var(--accent-primary, #60a5fa); font-weight:600;">${{escapeHTML(m.nombre_nuevo || m.destino.split('/').pop())}}</span></td>
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
        config.ruta_descargas, config.ruta_destino_base, db
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
