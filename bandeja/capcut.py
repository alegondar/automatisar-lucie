#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/capcut.py

Vigilante pasivo y no destructivo para la carpeta de exportación de CapCut.
Cumple estrictamente las 7 Reglas de Oro del proyecto:
- Monitoreo pasivo (solo lectura, nunca altera, renombra ni borra archivos en CapCut).
- Fotografía inicial en arranque: ignora versiones históricas mientras no cambien.
- Escaneo recursivo hasta profundidad 3 (detecta exports sueltos y en subcarpetas).
- Filtrado de extensiones temporales parametrizadas (.tmp, .part, .crdownload, etc.).
- Ventana de estabilidad de tamaño (mínimo N sondeos con tamaño idéntico).
- Verificación de apertura exclusiva (verificar_archivo_exclusivo) antes de notificar.
"""

import datetime
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

from bandeja.plataforma import (
    obtener_ruta_exportacion_capcut,
    verificar_archivo_exclusivo,
)

logger = logging.getLogger("bandeja_capcut")

EXTENSIONES_EXPORT_VALIDAS = {".mp4", ".mov"}
EXTENSIONES_TEMPORALES_DEFECTO = [".tmp", ".part", ".crdownload", ".tmp.mp4"]


class VigilanteCapCut:
    """
    Monitor en segundo plano de la carpeta de exportaciones de CapCut.
    Detecta de forma pasiva y segura nuevos videos exportados.
    """

    def __init__(
        self,
        ruta_capcut: Optional[str] = None,
        extensiones_temporales: Optional[List[str]] = None,
        sondeos_estabilidad: int = 3,
        intervalo_sondeo: float = 2.0,
        callback_nuevo_export: Optional[Callable[[Dict[str, Any]], None]] = None,
        callback_sondeo: Optional[Callable[[], None]] = None,
        exports_registrados: Optional[List[Dict[str, Any]]] = None,
    ):
        if not ruta_capcut or ruta_capcut == "auto":
            self.ruta_capcut = os.path.abspath(obtener_ruta_exportacion_capcut())
        else:
            self.ruta_capcut = os.path.abspath(ruta_capcut)

        self.extensiones_temporales = [
            ext.lower()
            for ext in (extensiones_temporales or EXTENSIONES_TEMPORALES_DEFECTO)
        ]
        self.sondeos_estabilidad = max(1, sondeos_estabilidad)
        self.intervalo_sondeo = max(0.1, intervalo_sondeo)
        self.callback_nuevo_export = callback_nuevo_export
        self.callback_sondeo = callback_sondeo

        self._preexistentes = {}
        self._exports_detectados = {}
        self._registrados = {}
        for export in exports_registrados or []:
            ruta = os.path.normcase(os.path.abspath(export["ruta_origen"]))
            self._registrados.setdefault(ruta, set()).add((export["tamano"], export["mtime"]))
        self._conteo_estabilidad: Dict[str, int] = {}
        self._ultimo_tamano: Dict[str, int] = {}
        self._fotografia_tomada: bool = False

        self._detener = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    @staticmethod
    def _firma(st):
        return (st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)

    def tomar_fotografia_inicial(self) -> int:
        """
        Escanea la carpeta de CapCut y registra todos los archivos preexistentes
        para ignorar esas versiones sin cambios. Retorna la cantidad registrada.
        """
        with self._lock:
            self._preexistentes.clear()
            if not os.path.exists(self.ruta_capcut) or not os.path.isdir(self.ruta_capcut):
                self._fotografia_tomada = True
                return 0

            conteo = 0
            for raiz, dirs, archivos in os.walk(self.ruta_capcut):
                rel = os.path.relpath(raiz, self.ruta_capcut)
                profundidad = 0 if rel == "." else len(rel.split(os.sep))
                if profundidad >= 3:
                    dirs[:] = []

                for arch in archivos:
                    ruta_arch = os.path.join(raiz, arch)
                    norm = os.path.normcase(os.path.abspath(ruta_arch))
                    try:
                        st = os.stat(ruta_arch)
                    except OSError:
                        continue
                    # Una ruta registrada cuyo contenido cambió durante la parada
                    # se procesa como nueva versión; el resto histórico se ignora.
                    if norm in self._registrados and (st.st_size, st.st_mtime) not in self._registrados[norm]:
                        continue
                    self._preexistentes[norm] = self._firma(st)
                    conteo += 1

            self._fotografia_tomada = True
            logger.info(
                f"[CapCut] Fotografía inicial completada en '{self.ruta_capcut}'. "
                f"{conteo} archivos preexistentes ignorados."
            )
            return conteo

    def escanear(self) -> List[Dict[str, Any]]:
        """
        Realiza un pase de escaneo no invasivo.
        Retorna la lista de nuevos archivos de video estabilizados y listos.
        """
        with self._lock:
            if not self._fotografia_tomada:
                self.tomar_fotografia_inicial()
                return []

            if not os.path.exists(self.ruta_capcut) or not os.path.isdir(self.ruta_capcut):
                return []

            nuevos_listos: List[Dict[str, Any]] = []

            for raiz, dirs, archivos in os.walk(self.ruta_capcut):
                rel = os.path.relpath(raiz, self.ruta_capcut)
                profundidad = 0 if rel == "." else len(rel.split(os.sep))
                if profundidad >= 3:
                    dirs[:] = []

                for arch in archivos:
                    ruta_arch = os.path.join(raiz, arch)
                    norm = os.path.normcase(os.path.abspath(ruta_arch))

                    # 1. Ignorar preexistentes y ya detectados
                    if os.path.islink(ruta_arch):
                        continue

                    # 2. Ignorar temporales y ocultos
                    arch_lower = arch.lower()
                    if arch_lower.startswith((".", "~")):
                        continue
                    if any(arch_lower.endswith(ext) for ext in self.extensiones_temporales):
                        continue

                    # 3. Filtrar extensiones válidas de export
                    _, ext = os.path.splitext(arch_lower)
                    if ext not in EXTENSIONES_EXPORT_VALIDAS:
                        continue

                    # 4. Inspeccionar tamaño
                    try:
                        st = os.stat(ruta_arch)
                        tamano_actual = st.st_size
                    except OSError:
                        continue

                    if tamano_actual <= 0:
                        continue
                    firma = self._firma(st)
                    if self._preexistentes.get(norm) == firma or self._exports_detectados.get(norm) == firma:
                        continue

                    # 5. Ventana de estabilidad
                    tamano_anterior = self._ultimo_tamano.get(norm)
                    if tamano_anterior is not None and tamano_anterior == firma:
                        self._conteo_estabilidad[norm] = self._conteo_estabilidad.get(norm, 1) + 1
                    else:
                        self._ultimo_tamano[norm] = firma
                        self._conteo_estabilidad[norm] = 1

                    if self._conteo_estabilidad[norm] < self.sondeos_estabilidad:
                        # Todavía no cumplió la ventana de estabilidad
                        continue

                    # 6. Apertura exclusiva (verificar que CapCut no esté escribiendo)
                    if not verificar_archivo_exclusivo(ruta_arch):
                        logger.debug(f"[CapCut] Archivo '{arch}' estabilizado pero ocupado/bloqueado.")
                        continue

                    # Archivo listo
                    self._exports_detectados[norm] = firma
                    carpeta_rel = "" if rel == "." else rel
                    info = {
                        "ruta_absoluta": ruta_arch,
                        "nombre": arch,
                        "tamano": tamano_actual,
                        "mtime": st.st_mtime,
                        "carpeta_relativa": carpeta_rel,
                        "fecha_deteccion": datetime.datetime.now().isoformat(),
                    }
                    nuevos_listos.append(info)
                    logger.info(f"[CapCut] Nuevo export detectado y verificado: '{arch}' ({tamano_actual} bytes)")

            # Invocar callbacks fuera de loops pero dentro del escaneo
            for info in nuevos_listos:
                if self.callback_nuevo_export:
                    try:
                        self.callback_nuevo_export(info)
                    except Exception as e:
                        self._exports_detectados.pop(os.path.normcase(os.path.abspath(info["ruta_absoluta"])), None)
                        logger.error(f"[CapCut] Error en callback_nuevo_export: {e}")

            if self.callback_sondeo:
                try:
                    self.callback_sondeo()
                except Exception as e:
                    logger.error(f"[CapCut] Error al procesar pendientes: {e}")

            return nuevos_listos

    def _bucle_sondeo(self):
        """Bucle periódico en segundo plano."""
        while not self._detener.is_set():
            try:
                self.escanear()
            except Exception as e:
                logger.error(f"[CapCut] Error durante escaneo: {e}")
            self._detener.wait(timeout=self.intervalo_sondeo)

    def iniciar(self):
        """Inicia el hilo de monitoreo en segundo plano."""
        if not self._fotografia_tomada:
            self.tomar_fotografia_inicial()
        self._detener.clear()
        self._hilo = threading.Thread(
            target=self._bucle_sondeo, daemon=True, name="VigilanteCapCut"
        )
        self._hilo.start()

    def detener(self):
        """Detiene el hilo de monitoreo."""
        self._detener.set()
        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=2.0)
