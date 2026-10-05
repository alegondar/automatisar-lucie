#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/lotes.py

Agrupación temporal y temática de lotes de descarga:
- Detección de descargas activas e inestables (DetectorDescargasActivas).
- Determinación de fecha de llegada efectiva (obtener_fecha_llegada).
- Agrupación por raíz de escena y ventana temporal (AgrupadorLotes).
"""

import datetime
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("bandeja_descargas")


def obtener_fecha_llegada(archivo_o_stat: Union[str, os.stat_result, Any]) -> float:
    """
    Retorna la fecha de llegada efectiva de un archivo: max(st_mtime, st_ctime).
    st_ctime se actualiza al crear, descargar, escribir, renombrar o copiar en el sistema de
    archivos local y no puede ser manipulado con os.utime, evitando que archivos descargados
    con Last-Modified antiguo del servidor caigan erróneamente en material anterior.
    """
    if hasattr(archivo_o_stat, "st_mtime") and hasattr(archivo_o_stat, "st_ctime"):
        return max(float(archivo_o_stat.st_mtime), float(archivo_o_stat.st_ctime))
    if isinstance(archivo_o_stat, dict):
        mt = archivo_o_stat.get("st_mtime", archivo_o_stat.get("mtime", 0.0))
        ct = archivo_o_stat.get("st_ctime", archivo_o_stat.get("ctime", 0.0))
        return max(float(mt), float(ct))
    if isinstance(archivo_o_stat, (int, float)):
        return float(archivo_o_stat)
    st = os.stat(str(archivo_o_stat))
    return max(float(st.st_mtime), float(st.st_ctime))


class DetectorDescargasActivas:
    """Verifica si un archivo se encuentra en descarga activa o inestable (ventana de 5s)."""

    def __init__(self, ventana_estabilidad_segundos: float = 5.0):
        self.ventana = ventana_estabilidad_segundos
        self._historial_tamanio: Dict[str, Tuple[int, float]] = {}
        self._estables_notificados: Set[str] = set()

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
            logger.info(
                f"[BANDEJA][DETECTADO] Archivo: '{os.path.basename(ruta_completa)}' | "
                f"Tamaño: {tamanio_actual} B | mtime: {st.st_mtime:.2f} | ctime: {st.st_ctime:.2f} | "
                f"ts: {datetime.datetime.now().isoformat()}"
            )
            return False

        tamanio_previo, timestamp_previo = self._historial_tamanio[ruta_completa]
        if tamanio_actual != tamanio_previo:
            self._historial_tamanio[ruta_completa] = (tamanio_actual, ahora)
            return False

        # Si el tamaño no cambió, comprobar si ya pasaron los segundos requeridos
        if (ahora - timestamp_previo) >= self.ventana:
            if ruta_completa not in self._estables_notificados:
                self._estables_notificados.add(ruta_completa)
                logger.info(
                    f"[BANDEJA][ESTABLE] Archivo: '{os.path.basename(ruta_completa)}' | "
                    f"Tamaño: {tamanio_actual} B | Estable tras {ahora - timestamp_previo:.1f}s | "
                    f"ts: {datetime.datetime.now().isoformat()}"
                )
            return True

        return False

    def limpiar_rutas_inexistentes(self, rutas_existentes: Set[str]):
        rutas_borrar = [r for r in self._historial_tamanio if r not in rutas_existentes]
        for r in rutas_borrar:
            self._historial_tamanio.pop(r, None)
            self._estables_notificados.discard(r)


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
                if "fecha_llegada" not in arch:
                    fl_ts = arch.get("fecha_llegada_ts", arch.get("mtime", 0.0))
                    arch["fecha_llegada"] = datetime.datetime.fromtimestamp(fl_ts).strftime("%Y-%m-%d %H:%M:%S")
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
