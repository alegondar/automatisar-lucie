#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/db.py

Gestor de base de datos SQLite para la bandeja de descargas:
- Tablas bandeja_archivos, bandeja_estado, bandeja_capitulos.
- Gestión de transacciones, bloqueos thread-safe y migraciones automáticas.
- Registro de decisiones, capítulos en foco, balances y marcas de descarte.
"""

import contextlib
import datetime
import logging
import os
import re
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

from bandeja.config import (
    RUTA_DESTINO_DEFECTO,
    EXTENSIONES_IMAGENES_DEFECTO,
    EXTENSIONES_MEDIA_DEFECTO,
    EXTENSIONES_VIDEOS_DEFECTO,
)

from bandeja.clasificacion import asegurar_carpeta_capitulo

logger = logging.getLogger("bandeja.db")


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

    @contextlib.contextmanager
    def _conectar(self):
        con = sqlite3.connect(self.ruta_db, timeout=10.0)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

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

    def obtener_movido_por_hash(self, hash_val: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM bandeja_archivos WHERE hash = ? AND estado = 'movido' ORDER BY id DESC LIMIT 1", (hash_val,))
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
        """Calcula la cantidad de archivos pendientes y ya movidos para un personaje y capítulo."""
        from bandeja.capitulos import calcular_balance_capitulo
        return calcular_balance_capitulo(self, personaje, nombre, verificar_disco, self.ruta_destino_base)

    def es_capitulo_olvidado(self, horas_limite: float = 12.0, ahora: Optional[datetime.datetime] = None) -> bool:
        """Determina si el capítulo activo excede las horas límite configuradas."""
        from bandeja.capitulos import es_capitulo_olvidado
        return es_capitulo_olvidado(self, horas_limite, ahora)

    def obtener_resumen_version(self) -> Dict[str, Any]:
        """
        Retorna un resumen liviano del estado de la base de datos relevante para la vista.
        """
        with self._lock, self._conectar() as con:
            cur = con.cursor()
            cur.execute("""
            SELECT id, personaje, nombre, estado, descartado, en_foco, fecha_inicio, fecha_fin, fecha_ultimo_aviso, archivos_movidos
            FROM bandeja_capitulos
            ORDER BY id ASC
            """)
            capitulos = [tuple(r) for r in cur.fetchall()]

            cur.execute("""
            SELECT estado, COUNT(*) as c
            FROM bandeja_archivos
            GROUP BY estado
            ORDER BY estado ASC
            """)
            conteos_estado = [(r["estado"], r["c"]) for r in cur.fetchall()]

            cur.execute("SELECT MAX(id) as max_id, COUNT(*) as tot FROM bandeja_archivos")
            row_arch = cur.fetchone()
            max_arch_id = row_arch["max_id"] or 0
            tot_arch = row_arch["tot"] or 0

            return {
                "capitulos": capitulos,
                "conteos_estado": conteos_estado,
                "max_arch_id": max_arch_id,
                "tot_arch": tot_arch
            }

