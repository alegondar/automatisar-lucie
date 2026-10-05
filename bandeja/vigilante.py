#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/vigilante.py

Hilo de vigilancia en segundo plano (polling) de ~/Descargas:
- Detección no invasiva periódica de archivos nuevos y estabilidad.
- Agrupación reactiva en lotes mediante AgrupadorLotes.
- Detección automática y banner reactivo para pendrive.
- Cálculo de hash liviano de estado-versión para refresco condicional (HTTP 304 / ETag).
"""

import datetime
import hashlib
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.clasificacion import FiltroListaBlanca
from bandeja.lotes import (
    DetectorDescargasActivas,
    AgrupadorLotes,
    obtener_fecha_llegada,
)
from bandeja.pendrive import (
    obtener_estado_pendrive,
    detectar_pendrive,
    leer_manifiesto_pendrive,
)
from bandeja.plataforma import notificar_escritorio

logger = logging.getLogger("bandeja_descargas")

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
            entradas = sorted(os.listdir(self.config.ruta_descargas))
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

        # Inicializar índices para detección de duplicados
        hashes_vistos_descargas: Dict[str, str] = {}
        hashes_enviados_pendrive: Dict[str, Dict[str, Any]] = {}
        try:
            pen = detectar_pendrive(self.config)
            if pen and pen.get("punto_montaje"):
                carpeta_raiz = getattr(self.config, "carpeta_raiz_pendrive", "LucieSinReglas")
                manif = leer_manifiesto_pendrive(pen["punto_montaje"], carpeta_raiz)
                for ent in manif:
                    h = ent.get("sha256")
                    if h:
                        if ent.get("estado") == "enviado":
                            hashes_enviados_pendrive[h] = ent
                        elif ent.get("estado") == "envio_revertido" and h in hashes_enviados_pendrive:
                            del hashes_enviados_pendrive[h]
        except Exception:
            pass

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
            if es_cap_foco:
                if fecha_llegada < ts_corte_capitulo:
                    es_anterior = True
            else:
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
                if reg_hash and reg_hash.get("ruta_actual") == ruta_completa:
                    reg = reg_hash

            # Detección de duplicados
            duplicado_info = None
            if hash_val in hashes_vistos_descargas:
                primer_archivo = hashes_vistos_descargas[hash_val]
                duplicado_info = {
                    "es_duplicado": True,
                    "tipo": "descargas",
                    "coincide_con": primer_archivo,
                    "mensaje": f"Coincide con {primer_archivo}"
                }
            else:
                hashes_vistos_descargas[hash_val] = entrada

            if not duplicado_info:
                movido = self.db.obtener_movido_por_hash(hash_val)
                if movido:
                    nombre_movido = os.path.basename(movido.get("ruta_actual") or "") or movido.get("ruta_actual") or "archivo movido"
                    duplicado_info = {
                        "es_duplicado": True,
                        "tipo": "movido",
                        "coincide_con": nombre_movido,
                        "mensaje": f"Ya movido ({nombre_movido})"
                    }

            if not duplicado_info and hash_val in hashes_enviados_pendrive:
                ent_pen = hashes_enviados_pendrive[hash_val]
                nombre_pen = ent_pen.get("nombre") or os.path.basename(ent_pen.get("ruta_relativa") or "") or "pendrive"
                duplicado_info = {
                    "es_duplicado": True,
                    "tipo": "pendrive",
                    "coincide_con": nombre_pen,
                    "mensaje": f"Ya enviado a pendrive ({nombre_pen})"
                }

            if es_anterior:
                # Regla 2: Archivo anterior al inicio del capítulo activo o según ventana reciente:
                # NO se asigna al capítulo ni se preselecciona.
                pers_alias = self.filtro.obtener_personaje_de_alias_inicial(entrada) if tipo_clasificacion == "candidato" else None
                personaje_actual = pers_alias
                escena_actual = None
                raiz_escena = None
                estado_actual = "detectado"
                if not duplicado_info or duplicado_info.get("tipo") == "pendrive":
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
                    id_db = reg["id"] if reg else 0
            else:
                if reg and reg["estado"] != "detectado" and (not duplicado_info or duplicado_info.get("tipo") != "movido"):
                    # Archivo ya detectado previamente con decisión tomada: respetar
                    id_db = reg["id"]
                    estado_actual = reg["estado"]
                    personaje_actual = reg.get("personaje")
                    escena_actual = reg.get("escena")
                    if escena_actual:
                        raiz_escena = f"{personaje_actual}::{escena_actual}" if personaje_actual else escena_actual.lower()
                    else:
                        raiz_escena = self.filtro.obtener_raiz_escena(entrada)
                elif duplicado_info and duplicado_info.get("tipo") in ("movido", "descargas"):
                    # Duplicado: no sobreescribir registro previo en DB
                    id_db = reg["id"] if reg else 0
                    estado_actual = "detectado"
                    if es_cap_foco:
                        personaje_actual = cap_foco["personaje"]
                        escena_actual = cap_foco["nombre"]
                        raiz_escena = f"{personaje_actual}::{escena_actual}"
                    else:
                        pers_alias = self.filtro.obtener_personaje_de_alias_inicial(entrada)
                        if pers_alias:
                            personaje_actual = pers_alias
                            escena_actual = self.filtro.extraer_escena_sugerida(entrada)
                            raiz_escena = self.filtro.obtener_raiz_escena(entrada)
                        else:
                            personaje_actual = None
                            escena_actual = None
                            raiz_escena = None
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
                "es_anterior": es_anterior,
                "duplicado": duplicado_info
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


