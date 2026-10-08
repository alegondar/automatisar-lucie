#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_limpieza.py

Generador y Validador del Plan de Limpieza en Modo Simulación (Dry-Run).
Reglas de Oro del Proyecto:
- Modo 100% de solo lectura sobre el almacenamiento extraíble.
- Cero operaciones de borrado, movimiento o renombre en este script.
- Genera plan_limpieza.json y plan_limpieza.md en el repositorio local.
- Clasificación de duplicados: inter-carpeta (a cuarentena) vs intra-carpeta (a decidir a mano).
- Diferencias detalladas en carpetas sospechosas (>= 75% similitud, ej. laroli vs videos1/laroli).
- Clasificación de sueltos por alias-personajes.json.
- Huella de integridad con recálculo de SHA-256 en vivo para validación pre-ejecución tolerante a FAT.
"""

import argparse
import fnmatch
from difflib import SequenceMatcher
import json
import os
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

from inventario_pendrive import (
    ArchivoInfo,
    normalizar_raiz,
    esta_dentro_de_raiz,
    formatear_bytes,
    formatear_duracion,
    CacheInventario,
    AuditorPendrive,
    calcular_sha256,
)


class HuellaInvalidaError(Exception):
    """Excepción lanzada cuando la validación de integridad pre-ejecución falla."""
    pass


class ViolacionSoloLecturaError(Exception):
    """Excepción lanzada ante cualquier intento de escribir dentro del pendrive."""
    pass


@dataclass
class AccionPlan:
    id: int
    tipo: str  # 'mover_duplicado', 'duplicado_intra_carpeta_manual', 'duplicado_protegido_manual', 'mover_suelto', 'suelto_sin_clasificar', 'diferencia_carpeta_sospechosa', 'carpeta_vacia'
    origen: str
    destino: Optional[str]
    motivo: str
    detalles: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfiguracionLimpieza:
    carpetas_ignoradas: List[str] = field(default_factory=lambda: [
        "_a_revisar", "code", "System Volume Information", "$RECYCLE.BIN", ".Trash-*"
    ])
    carpetas_protegidas: List[str] = field(default_factory=lambda: [
        "laroli", "videos1/laroli"
    ])
    umbral_similitud_carpetas: float = 0.75
    prefijo_destino_duplicados: str = "_a_revisar/duplicados"
    prioridad_carpetas_duplicados: List[str] = field(default_factory=lambda: ["videos completos"])
    criterio_desempate_duplicados: str = "mas_reciente"
    tolerancia_mtime_segundos: float = 2.0
    ruta_alias_personajes: str = "alias-personajes.json"
    reglas_alias: List[Dict[str, Any]] = field(default_factory=list)


def cargar_configuracion(ruta_config: str = "config_limpieza.json") -> ConfiguracionLimpieza:
    """Carga la configuración general y el mapeo de alias de personajes."""
    config = ConfiguracionLimpieza()
    
    if os.path.exists(ruta_config):
        try:
            with open(ruta_config, "r", encoding="utf-8", newline="\n") as f:
                data = json.load(f)
            if "carpetas_ignoradas" in data:
                config.carpetas_ignoradas = data["carpetas_ignoradas"]
            if "carpetas_protegidas" in data:
                config.carpetas_protegidas = data["carpetas_protegidas"]
            if "umbral_similitud_carpetas" in data:
                config.umbral_similitud_carpetas = float(data["umbral_similitud_carpetas"])
            if "prefijo_destino_duplicados" in data:
                config.prefijo_destino_duplicados = data["prefijo_destino_duplicados"]
            if "tolerancia_mtime_segundos" in data:
                config.tolerancia_mtime_segundos = float(data["tolerancia_mtime_segundos"])
            if "ruta_alias_personajes" in data:
                config.ruta_alias_personajes = data["ruta_alias_personajes"]
            if "reglas_duplicados" in data:
                rd = data["reglas_duplicados"]
                if "prioridad_carpetas" in rd:
                    config.prioridad_carpetas_duplicados = rd["prioridad_carpetas"]
                if "criterio_desempate" in rd:
                    config.criterio_desempate_duplicados = rd["criterio_desempate"]
        except Exception as e:
            print(f"[!] Advertencia al leer {ruta_config}: {e}. Usando valores por defecto.", file=sys.stderr)

    # Cargar alias de personajes
    ruta_alias = config.ruta_alias_personajes
    if not os.path.isabs(ruta_alias) and os.path.dirname(ruta_config):
        ruta_alias_rel = os.path.join(os.path.dirname(ruta_config), ruta_alias)
        if os.path.exists(ruta_alias_rel):
            ruta_alias = ruta_alias_rel

    if os.path.exists(ruta_alias):
        try:
            with open(ruta_alias, "r", encoding="utf-8", newline="\n") as f:
                data_alias = json.load(f)
            config.reglas_alias = data_alias.get("reglas", [])
        except Exception as e:
            print(f"[!] Advertencia al leer {ruta_alias}: {e}.", file=sys.stderr)

    return config


def es_ruta_ignorada(ruta_relativa: str, carpetas_ignoradas: List[str]) -> bool:
    """Verifica si la ruta relativa contiene alguna de las carpetas ignoradas."""
    partes = Path(ruta_relativa).parts
    for parte in partes:
        p_lower = parte.lower()
        for ign in carpetas_ignoradas:
            ign_lower = ign.lower()
            if fnmatch.fnmatch(p_lower, ign_lower) or p_lower == ign_lower:
                return True
    return False


def esta_en_carpeta_protegida(ruta_relativa: str, carpetas_protegidas: List[str]) -> bool:
    """
    Verifica si una ruta relativa se encuentra dentro de alguna de las carpetas protegidas.
    Compara los componentes de la ruta normalizada para evitar falsos positivos por prefijo de texto.
    """
    if not carpetas_protegidas:
        return False
    norm_r = os.path.normpath(ruta_relativa).replace("\\", "/")
    r_parts = tuple(part for part in norm_r.split("/") if part and part != ".")
    for cp in carpetas_protegidas:
        norm_cp = os.path.normpath(cp).replace("\\", "/")
        cp_parts = tuple(part for part in norm_cp.split("/") if part and part != ".")
        if len(r_parts) > len(cp_parts):
            if tuple(p.lower() for p in r_parts[:len(cp_parts)]) == tuple(p.lower() for p in cp_parts):
                return True
    return False


class GeneradorPlanLimpieza:
    """
    Genera el plan de limpieza en simulación estricta a partir del inventario y su caché.
    """

    def __init__(self, ruta_raiz: str, ruta_cache: str = ".cache/inventario_pendrive_cache.sqlite",
                 config: Optional[ConfiguracionLimpieza] = None):
        self.raiz_real = normalizar_raiz(ruta_raiz)
        self.ruta_cache = os.path.abspath(ruta_cache)
        self.config = config or cargar_configuracion()
        self.acciones: List[AccionPlan] = []
        self._contador_id = 1

    def _siguiente_id(self) -> int:
        act_id = self._contador_id
        self._contador_id += 1
        return act_id

    def validar_seguridad_salida(self, ruta_salida: str):
        """Asegura bajo la Regla de Oro que ninguna salida se escriba dentro del pendrive."""
        ruta_abs = os.path.abspath(ruta_salida)
        if esta_dentro_de_raiz(ruta_abs, self.raiz_real):
            raise ViolacionSoloLecturaError(
                f"Violación de Solo Lectura: La ruta de salida '{ruta_salida}' "
                f"no puede estar dentro del pendrive '{self.raiz_real}'."
            )

    def generar_plan(self) -> Dict[str, Any]:
        """Ejecuta el análisis y produce el diccionario completo del plan de limpieza."""
        print(f"[*] Analizando almacenamiento: {self.raiz_real}")
        print(f"[*] Usando caché: {self.ruta_cache}")

        auditor = AuditorPendrive(
            ruta_raiz=self.raiz_real,
            incluir_ocultos=False,
            ruta_cache=self.ruta_cache
        )
        auditor.escanear()
        auditor.procesar_metadatos_y_duracion()

        # Filtrar archivos según carpetas ignoradas (ej: _a_revisar, code)
        archivos_filtrados = [
            a for a in auditor.archivos
            if not es_ruta_ignorada(a.ruta_relativa, self.config.carpetas_ignoradas)
        ]
        carpetas_filtradas = [
            c for c in auditor.carpetas_encontradas
            if not es_ruta_ignorada(c, self.config.carpetas_ignoradas)
        ]

        # Asegurar cálculo/reutilización de SHA-256 para todos los archivos a evaluar
        for a in archivos_filtrados:
            if not a.sha256:
                cached = auditor.cache.obtener(a.ruta_relativa, a.tamanio_bytes, a.mtime)
                if cached and cached[0]:
                    a.sha256 = cached[0]
                    if a.categoria == 'video' and a.duracion_segundos is None:
                        a.duracion_segundos = cached[1]
                else:
                    a.sha256 = calcular_sha256(a.ruta_absoluta)
                    auditor.cache.guardar(
                        a.ruta_relativa, a.tamanio_bytes, a.mtime,
                        a.sha256, a.duracion_segundos, a.categoria
                    )

        print(f"[*] Archivos operativos a evaluar: {len(archivos_filtrados)} "
              f"(excluidas carpetas: {self.config.carpetas_ignoradas})")

        # Conjunto de rutas existentes en disco para verificar que ningún destino colisione
        rutas_existentes_pendrive: Set[str] = set(a.ruta_relativa for a in auditor.archivos)

        self.acciones = []
        self._contador_id = 1

        archivos_en_acciones_mover: Set[str] = set()

        # --------------------------------------------------------------------------
        # 1. DUPLICADOS EXACTOS (INTER-CARPETA VS INTRA-CARPETA)
        # --------------------------------------------------------------------------
        # Agrupar por hash
        grupos_hash: Dict[str, List[ArchivoInfo]] = {}
        for a in archivos_filtrados:
            if a.sha256 and a.tamanio_bytes > 0:
                grupos_hash.setdefault(a.sha256, []).append(a)

        duplicados_confirmados = [lista for lista in grupos_hash.values() if len(lista) > 1]
        duplicados_inter_count = 0
        duplicados_intra_count = 0
        duplicados_protegidos_count = 0
        espacio_recuperable_duplicados = 0

        for grupo in duplicados_confirmados:
            carpetas_p1_unicas = sorted(list(set(
                a.carpeta_primer_nivel if a.carpeta_primer_nivel else "(raíz)"
                for a in grupo
            )))

            # Comprobar si ALGUNA copia reside en una carpeta protegida
            copias_en_protegida = [
                a for a in grupo
                if esta_en_carpeta_protegida(a.ruta_relativa, self.config.carpetas_protegidas)
            ]

            detalles_copias = []
            for a in grupo:
                mtime_dt = datetime.fromtimestamp(a.mtime)
                detalles_copias.append({
                    "ruta_relativa": a.ruta_relativa,
                    "tamanio_bytes": a.tamanio_bytes,
                    "tamanio_legible": formatear_bytes(a.tamanio_bytes),
                    "mtime": a.mtime,
                    "fecha": mtime_dt.strftime("%Y-%m-%d %H:%M:%S")
                })

            # (A) DUPLICADOS CON COPIA EN CARPETA PROTEGIDA: NO MOVER NINGUNA COPIA (DECIDIR A MANO)
            if copias_en_protegida:
                duplicados_protegidos_count += 1
                carpetas_prot_detectadas = sorted(list(set(
                    cp for cp in self.config.carpetas_protegidas
                    if any(esta_en_carpeta_protegida(a.ruta_relativa, [cp]) for a in grupo)
                )))

                self.acciones.append(AccionPlan(
                    id=self._siguiente_id(),
                    tipo="duplicado_protegido_manual",
                    origen=grupo[0].ruta_relativa,
                    destino=None,
                    motivo=f"Duplicados exactos con copia en carpeta protegida ({', '.join(carpetas_prot_detectadas)}). No se mueve ninguna copia automáticamente; decidir a mano.",
                    detalles={
                        "sha256": grupo[0].sha256,
                        "tamanio_bytes": grupo[0].tamanio_bytes,
                        "carpeta": ", ".join(carpetas_p1_unicas),
                        "carpetas_protegidas": carpetas_prot_detectadas,
                        "copias": detalles_copias
                    }
                ))

            # (B) DUPLICADOS INTRA-CARPETA (misma carpeta de primer nivel): DECIDIR A MANO
            elif len(carpetas_p1_unicas) == 1:
                duplicados_intra_count += 1
                carpeta_nombre = carpetas_p1_unicas[0]
                rutas_grupo = [a.ruta_relativa for a in grupo]

                self.acciones.append(AccionPlan(
                    id=self._siguiente_id(),
                    tipo="duplicado_intra_carpeta_manual",
                    origen=rutas_grupo[0],
                    destino=None,
                    motivo=f"Duplicados exactos dentro de la misma carpeta ('{carpeta_nombre}'). No se mueven automáticamente; decidir a mano.",
                    detalles={
                        "sha256": grupo[0].sha256,
                        "tamanio_bytes": grupo[0].tamanio_bytes,
                        "carpeta": carpeta_nombre,
                        "copias": detalles_copias
                    }
                ))
            else:
                # (C) DUPLICADOS INTER-CARPETA SIN COPIAS PROTEGIDAS: APLICAR REGLA DE CONSERVACIÓN Y MOVER RESTO
                duplicados_inter_count += 1
                
                # Seleccionar copia a conservar según prioridad
                copia_conservar = None
                for prioridad in self.config.prioridad_carpetas_duplicados:
                    candidatos_prioridad = [
                        a for a in grupo
                        if a.carpeta_primer_nivel and a.carpeta_primer_nivel.lower() == prioridad.lower()
                    ]
                    if candidatos_prioridad:
                        # Si hay empate en la prioridad, elegir la más reciente
                        candidatos_prioridad.sort(key=lambda x: x.mtime, reverse=True)
                        copia_conservar = candidatos_prioridad[0]
                        break

                if not copia_conservar:
                    # Desempate general por fecha más reciente
                    grupo_ordenado = sorted(grupo, key=lambda x: x.mtime, reverse=True)
                    copia_conservar = grupo_ordenado[0]

                # Las demás copias se proponen para mover a _a_revisar/duplicados/
                for copia in grupo:
                    if copia == copia_conservar:
                        continue
                    
                    espacio_recuperable_duplicados += copia.tamanio_bytes
                    archivos_en_acciones_mover.add(copia.ruta_relativa)

                    destino_propuesto = f"{self.config.prefijo_destino_duplicados}/{copia.ruta_relativa}"
                    
                    # Validación de no colisión previa en destino
                    colision = destino_propuesto in rutas_existentes_pendrive or os.path.exists(os.path.join(self.raiz_real, destino_propuesto))
                    if colision:
                        motivo = f"CONFLICTO: Destino '{destino_propuesto}' ya existe físicamente. No se puede mover sin sobrescribir."
                        destino_final = None
                    else:
                        motivo = (f"Duplicado exacto de '{copia_conservar.ruta_relativa}'. "
                                  f"Copia conservada en '{copia_conservar.carpeta_primer_nivel or '(raíz)'}'.")
                        destino_final = destino_propuesto

                    mtime_dt = datetime.fromtimestamp(copia.mtime)
                    self.acciones.append(AccionPlan(
                        id=self._siguiente_id(),
                        tipo="mover_duplicado",
                        origen=copia.ruta_relativa,
                        destino=destino_final,
                        motivo=motivo,
                        detalles={
                            "sha256": copia.sha256,
                            "tamanio_bytes": copia.tamanio_bytes,
                            "tamanio_legible": formatear_bytes(copia.tamanio_bytes),
                            "copia_conservada": copia_conservar.ruta_relativa,
                            "carpeta_conservada": copia_conservar.carpeta_primer_nivel or "(raíz)",
                            "mtime": copia.mtime,
                            "fecha": mtime_dt.strftime("%Y-%m-%d %H:%M:%S")
                        }
                    ))

        # --------------------------------------------------------------------------
        # 2. CARPETAS SOSPECHOSAS (SIMILITUD >= 75%)
        # --------------------------------------------------------------------------
        # Construir mapa de hashes por carpeta
        carpetas_map: Dict[str, Dict] = {}
        for c in carpetas_filtradas:
            carpetas_map[c] = {'archivos': [], 'hashes': set()}

        for a in archivos_filtrados:
            dir_padre = os.path.dirname(a.ruta_relativa)
            if dir_padre in carpetas_map:
                carpetas_map[dir_padre]['archivos'].append(a)
                if a.sha256:
                    carpetas_map[dir_padre]['hashes'].add(a.sha256)

        lista_carpetas = [c for c in sorted(carpetas_filtradas) if carpetas_map[c]['hashes']]
        pares_sospechosos = []

        for i in range(len(lista_carpetas)):
            for j in range(i + 1, len(lista_carpetas)):
                c1 = lista_carpetas[i]
                c2 = lista_carpetas[j]

                # Evitar comparar carpetas padre con sus propias subcarpetas directas
                if c2.startswith(c1 + "/") or c1.startswith(c2 + "/"):
                    continue

                h1 = carpetas_map[c1]['hashes']
                h2 = carpetas_map[c2]['hashes']
                if not h1 or not h2:
                    continue

                interseccion = h1 & h2
                union = h1 | h2
                coef = len(interseccion) / len(union) if union else 0.0

                # Umbral de similitud o inclusión expresa del par 'laroli' vs 'videos1/laroli'
                es_par_laroli = (c1 == "laroli" and c2 == "videos1/laroli") or (c2 == "laroli" and c1 == "videos1/laroli")
                if coef >= self.config.umbral_similitud_carpetas or es_par_laroli:
                    pares_sospechosos.append({
                        "carpeta1": c1,
                        "carpeta2": c2,
                        "similitud_pct": round(coef * 100, 1),
                        "archivos_compartidos": len(interseccion),
                        "hashes_c1": h1,
                        "hashes_c2": h2
                    })

        # Para cada par sospechoso, listar exclusivamente los archivos disjuntos
        diferencias_sospechosas_count = 0
        for par in pares_sospechosos:
            c1 = par["carpeta1"]
            c2 = par["carpeta2"]
            similitud = par["similitud_pct"]
            
            exclusivos_c1 = [a for a in carpetas_map[c1]['archivos'] if a.sha256 not in par["hashes_c2"]]
            exclusivos_c2 = [a for a in carpetas_map[c2]['archivos'] if a.sha256 not in par["hashes_c1"]]

            for a in exclusivos_c1:
                diferencias_sospechosas_count += 1
                mtime_dt = datetime.fromtimestamp(a.mtime)
                self.acciones.append(AccionPlan(
                    id=self._siguiente_id(),
                    tipo="diferencia_carpeta_sospechosa",
                    origen=a.ruta_relativa,
                    destino=None,
                    motivo=f"Archivo exclusivo de '{c1}' ausente en carpeta similar '{c2}' (similitud: {similitud}%).",
                    detalles={
                        "par": [c1, c2],
                        "carpeta_origen": c1,
                        "carpeta_comparada": c2,
                        "similitud_par_pct": similitud,
                        "tamanio_bytes": a.tamanio_bytes,
                        "tamanio_legible": formatear_bytes(a.tamanio_bytes),
                        "mtime": a.mtime,
                        "fecha": mtime_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "sha256": a.sha256
                    }
                ))

            for a in exclusivos_c2:
                diferencias_sospechosas_count += 1
                mtime_dt = datetime.fromtimestamp(a.mtime)
                self.acciones.append(AccionPlan(
                    id=self._siguiente_id(),
                    tipo="diferencia_carpeta_sospechosa",
                    origen=a.ruta_relativa,
                    destino=None,
                    motivo=f"Archivo exclusivo de '{c2}' ausente en carpeta similar '{c1}' (similitud: {similitud}%).",
                    detalles={
                        "par": [c1, c2],
                        "carpeta_origen": c2,
                        "carpeta_comparada": c1,
                        "similitud_par_pct": similitud,
                        "tamanio_bytes": a.tamanio_bytes,
                        "tamanio_legible": formatear_bytes(a.tamanio_bytes),
                        "mtime": a.mtime,
                        "fecha": mtime_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "sha256": a.sha256
                    }
                ))

        # --------------------------------------------------------------------------
        # 3. ARCHIVOS SUELTOS (CLASIFICACIÓN CON ALIAS-PERSONAJES.JSON)
        # --------------------------------------------------------------------------
        sueltos_clasificados_count = 0
        sueltos_sin_clasificar_count = 0

        for a in archivos_filtrados:
            if (a.es_suelto_raiz or a.es_suelto_primer_nivel) and a.ruta_relativa not in archivos_en_acciones_mover:
                nombre_lower = a.nombre.lower()
                regla_match = None

                for r in self.config.reglas_alias:
                    for patron in r.get("patrones", []):
                        if fnmatch.fnmatch(nombre_lower, patron.lower()):
                            regla_match = r
                            break
                    if regla_match:
                        break

                mtime_dt = datetime.fromtimestamp(a.mtime)
                if regla_match:
                    sueltos_clasificados_count += 1
                    personaje = regla_match["personaje"]
                    dest_carpeta = regla_match.get("destino_carpeta", personaje)
                    req_conf = regla_match.get("requiere_confirmacion", False)
                    nota = f" ({regla_match.get('nota', 'a confirmar')})" if req_conf else ""
                    
                    destino_propuesto = f"{dest_carpeta}/{a.nombre}"
                    colision = destino_propuesto in rutas_existentes_pendrive or os.path.exists(os.path.join(self.raiz_real, destino_propuesto))
                    if colision:
                        destino_final = None
                        motivo = f"CONFLICTO: Destino '{destino_propuesto}' ya existe. Coincide con alias '{personaje}'{nota}."
                    else:
                        destino_final = destino_propuesto
                        motivo = f"Archivo suelto coincide con alias '{personaje}'{nota}. Propuesta de traslado a carpeta '{dest_carpeta}'."

                    self.acciones.append(AccionPlan(
                        id=self._siguiente_id(),
                        tipo="mover_suelto",
                        origen=a.ruta_relativa,
                        destino=destino_final,
                        motivo=motivo,
                        detalles={
                            "personaje": personaje,
                            "requiere_confirmacion": req_conf,
                            "tamanio_bytes": a.tamanio_bytes,
                            "tamanio_legible": formatear_bytes(a.tamanio_bytes),
                            "mtime": a.mtime,
                            "fecha": mtime_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "sha256": a.sha256
                        }
                    ))
                else:
                    sueltos_sin_clasificar_count += 1
                    self.acciones.append(AccionPlan(
                        id=self._siguiente_id(),
                        tipo="suelto_sin_clasificar",
                        origen=a.ruta_relativa,
                        destino=None,
                        motivo="Archivo suelto sin coincidencia en el mapa de alias de personajes. Sin clasificar; no se propone acción.",
                        detalles={
                            "tamanio_bytes": a.tamanio_bytes,
                            "tamanio_legible": formatear_bytes(a.tamanio_bytes),
                            "mtime": a.mtime,
                            "fecha": mtime_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "sha256": a.sha256
                        }
                    ))

        # --------------------------------------------------------------------------
        # 4. CARPETAS VACÍAS
        # --------------------------------------------------------------------------
        carpetas_vacias_detectadas = []
        for c in carpetas_filtradas:
            if not carpetas_map[c]['archivos']:
                carpetas_vacias_detectadas.append(c)
                self.acciones.append(AccionPlan(
                    id=self._siguiente_id(),
                    tipo="carpeta_vacia",
                    origen=c,
                    destino=None,
                    motivo="Carpeta vacía sin archivos válidos. Registro informativo; sin acción de borrado.",
                    detalles={"ruta_carpeta": c}
                ))

        # --------------------------------------------------------------------------
        # 5. HUELLA DE INTEGRIDAD (SNAPSHOT)
        # --------------------------------------------------------------------------
        # Registrar huella de todos los archivos evaluados para la validación pre-ejecución
        huella_archivos: Dict[str, Dict[str, Any]] = {}
        for a in archivos_filtrados:
            huella_archivos[a.ruta_relativa] = {
                "size_bytes": a.tamanio_bytes,
                "sha256": a.sha256,
                "mtime": a.mtime
            }

        plan_id = str(uuid.uuid4())
        fecha_creacion = datetime.now().isoformat()

        resumen = {
            "total_acciones": len(self.acciones),
            "duplicados_inter_a_mover": sum(1 for a in self.acciones if a.tipo == "mover_duplicado"),
            "duplicados_intra_a_mano": duplicados_intra_count,
            "duplicados_protegidos_a_mano": duplicados_protegidos_count,
            "duplicados_a_decidir_a_mano": duplicados_intra_count + duplicados_protegidos_count,
            "espacio_recuperable_duplicados_bytes": espacio_recuperable_duplicados,
            "espacio_recuperable_duplicados_legible": formatear_bytes(espacio_recuperable_duplicados),
            "pares_carpetas_sospechosas": len(pares_sospechosos),
            "archivos_diferencias_sospechosas": diferencias_sospechosas_count,
            "sueltos_clasificados": sueltos_clasificados_count,
            "sueltos_sin_clasificar": sueltos_sin_clasificar_count,
            "carpetas_vacias": len(carpetas_vacias_detectadas)
        }

        plan_dict = {
            "plan_id": plan_id,
            "fecha_creacion": fecha_creacion,
            "raiz": self.raiz_real,
            "modo": "simulacion_solo_lectura",
            "configuracion": asdict(self.config),
            "resumen": resumen,
            "huella": {
                "plan_id": plan_id,
                "fecha": fecha_creacion,
                "total_archivos": len(huella_archivos),
                "archivos": huella_archivos
            },
            "acciones": [asdict(a) for a in self.acciones]
        }

        return plan_dict

    def guardar_json(self, ruta_salida: str, plan_data: Dict[str, Any]):
        """Exporta el plan a formato JSON con sangría legible."""
        self.validar_seguridad_salida(ruta_salida)
        os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
        with open(ruta_salida, "w", encoding="utf-8", newline="\n") as f:
            json.dump(plan_data, f, indent=2, ensure_ascii=False)
        print(f"[+] Plan JSON guardado exitosamente: {ruta_salida}")

    def renderizar_markdown(self, plan: Dict[str, Any]) -> str:
        """Renderiza el plan de limpieza en un informe Markdown exhaustivo y legible."""
        res = plan["resumen"]
        cfg = plan["configuracion"]
        lineas = []

        lineas.append("# Plan de Limpieza del Pendrive (Modo Simulación)\n")
        lineas.append(f"> **Garantía de Seguridad:** Este plan fue generado en modo de **estricta simulación**. "
                      f"No se ha modificado, movido ni eliminado ningún archivo en la unidad `{plan['raiz']}`.\n")

        lineas.append("## Metadatos y Huella de Integridad")
        lineas.append(f"- **ID del Plan:** `{plan['plan_id']}`")
        lineas.append(f"- **Fecha de Generación:** `{plan['fecha_creacion']}`")
        lineas.append(f"- **Almacenamiento Origen:** `{plan['raiz']}`")
        lineas.append(f"- **Archivos Verificados en Huella:** {plan['huella']['total_archivos']}")
        lineas.append(f"- **Tolerancia mtime FAT/exFAT:** {cfg.get('tolerancia_mtime_segundos', 2.0)}s")
        lineas.append(f"- **Carpetas Ignoradas:** `{', '.join(cfg.get('carpetas_ignoradas', []))}`")
        if cfg.get("carpetas_protegidas"):
            lineas.append(f"- **Carpetas Protegidas:** `{', '.join(cfg.get('carpetas_protegidas', []))}`")
        lineas.append("")

        lineas.append("## Resumen General de Acciones Propuestas")
        lineas.append("| Categoría | Cantidad | Espacio Estimado / Estado |")
        lineas.append("| :--- | :---: | :--- |")
        lineas.append(f"| Duplicados inter-carpeta propuestos a mover | {res['duplicados_inter_a_mover']} | {res['espacio_recuperable_duplicados_legible']} |")
        lineas.append(f"| Duplicados a decidir a mano | {res.get('duplicados_a_decidir_a_mano', res['duplicados_intra_a_mano'])} | Sin movimiento automático |")
        lineas.append(f"| Diferencias en carpetas sospechosas (>=75%) | {res['archivos_diferencias_sospechosas']} | En {res['pares_carpetas_sospechosas']} pares |")
        lineas.append(f"| Archivos sueltos clasificados por alias | {res['sueltos_clasificados']} | Propuesta según alias |")
        lineas.append(f"| Archivos sueltos sin clasificar | {res['sueltos_sin_clasificar']} | Sin acción propuesta |")
        lineas.append(f"| Carpetas vacías detectadas | {res['carpetas_vacias']} | Solo reporte informativo |")
        lineas.append(f"| **Total Acciones Estructuradas** | **{res['total_acciones']}** | **100% Simulación** |\n")

        # 1. Duplicados inter-carpeta
        acciones_dupl_inter = [a for a in plan["acciones"] if a["tipo"] == "mover_duplicado"]
        lineas.append("## 1. Duplicados Inter-Carpeta (Propuesta: Mover a Cuarentena)")
        lineas.append(f"Regla de prioridad aplicada: `{', '.join(cfg.get('prioridad_carpetas_duplicados', []))}` > resto (desempate por fecha más reciente).")
        lineas.append(f"Destino propuesto: `{cfg.get('prefijo_destino_duplicados')}/<ruta_relativa>`.\n")
        if acciones_dupl_inter:
            lineas.append("| ID | Origen (A Mover) | Destino Propuesto | Tamaño | Copia Conservada |")
            lineas.append("| :---: | :--- | :--- | :---: | :--- |")
            for a in acciones_dupl_inter:
                det = a["detalles"]
                lineas.append(f"| {a['id']} | `{a['origen']}` | `{a['destino']}` | {det['tamanio_legible']} | `{det['copia_conservada']}` |")
        else:
            lineas.append("*No se detectaron duplicados inter-carpeta para mover.*")
        lineas.append("")

        # 2. Duplicados a decidir a mano (intra-carpeta y en carpetas protegidas)
        acciones_dupl_manual = [
            a for a in plan["acciones"]
            if a["tipo"] in ("duplicado_intra_carpeta_manual", "duplicado_protegido_manual")
        ]
        lineas.append("## 2. Duplicados a Decidir a Mano")
        lineas.append("> [!NOTE]\n> Estas copias residen dentro de la misma carpeta de primer nivel o involucran carpetas protegidas (ej. 'laroli', 'videos1/laroli'). "
                      "Por seguridad, el sistema NO propone mover ninguna de ellas automáticamente; deben decidirse a mano.\n")
        if acciones_dupl_manual:
            lineas.append("| ID | Carpeta / Contexto | Copias Idénticas Detectadas | Tamaño | Fecha |")
            lineas.append("| :---: | :--- | :--- | :---: | :---: |")
            for a in acciones_dupl_manual:
                det = a["detalles"]
                rutas_str = "<br>".join([f"`{c['ruta_relativa']}` ({c['tamanio_legible']}, {c['fecha']})" for c in det["copias"]])
                lineas.append(f"| {a['id']} | `{det['carpeta']}` | {rutas_str} | {formatear_bytes(det['tamanio_bytes'])} | - |")
        else:
            lineas.append("*No se detectaron duplicados a decidir a mano.*")
        lineas.append("")

        # 3. Diferencias en carpetas sospechosas
        acciones_dif = [a for a in plan["acciones"] if a["tipo"] == "diferencia_carpeta_sospechosa"]
        lineas.append("## 3. Carpetas Sospechosas (Similitud >= 75%): Archivos Disjuntos")
        lineas.append("Para cada par con alta similitud de contenido, se listan los archivos que **NO comparten** (presentes en una y ausentes en la otra). "
                      "**No se propone fusión de carpetas completas**.\n")
        if acciones_dif:
            lineas.append("| ID | Archivo Exclusivo | Carpeta Origen | Ausente En | Tamaño | Fecha |")
            lineas.append("| :---: | :--- | :--- | :--- | :---: | :---: |")
            for a in acciones_dif:
                det = a["detalles"]
                lineas.append(f"| {a['id']} | `{a['origen']}` | `{det['carpeta_origen']}` | `{det['carpeta_comparada']}` | {det['tamanio_legible']} | {det['fecha']} |")
        else:
            lineas.append("*No se registraron diferencias en carpetas sospechosas.*")
        lineas.append("")

        # 4. Archivos sueltos
        acciones_sueltos_mov = [a for a in plan["acciones"] if a["tipo"] == "mover_suelto"]
        acciones_sueltos_sin = [a for a in plan["acciones"] if a["tipo"] == "suelto_sin_clasificar"]
        lineas.append("## 4. Archivos Sueltos")
        lineas.append("### 4.1 Clasificados por Alias de Personajes")
        if acciones_sueltos_mov:
            lineas.append("| ID | Archivo Suelto | Destino Propuesto | Personaje | Tamaño |")
            lineas.append("| :---: | :--- | :--- | :---: | :---: |")
            for a in acciones_sueltos_mov:
                det = a["detalles"]
                conf_str = " (a confirmar)" if det.get("requiere_confirmacion") else ""
                lineas.append(f"| {a['id']} | `{a['origen']}` | `{a['destino']}` | `{det['personaje']}{conf_str}` | {det['tamanio_legible']} |")
        else:
            lineas.append("*No hay archivos sueltos clasificados.*")
        lineas.append("")

        lineas.append("### 4.2 Sin Clasificar (Sin Acción)")
        if acciones_sueltos_sin:
            lineas.append("| ID | Archivo | Motivo | Tamaño |")
            lineas.append("| :---: | :--- | :--- | :---: |")
            for a in acciones_sueltos_sin:
                det = a["detalles"]
                lineas.append(f"| {a['id']} | `{a['origen']}` | {a['motivo']} | {det['tamanio_legible']} |")
        else:
            lineas.append("*No hay archivos sueltos sin clasificar.*")
        lineas.append("")

        # 5. Carpetas vacías
        acciones_vacias = [a for a in plan["acciones"] if a["tipo"] == "carpeta_vacia"]
        lineas.append("## 5. Carpetas Vacías")
        if acciones_vacias:
            lineas.append("| ID | Carpeta Vacía | Estado |")
            lineas.append("| :---: | :--- | :--- |")
            for a in acciones_vacias:
                lineas.append(f"| {a['id']} | `{a['origen']}` | Informativo (sin acción de borrado) |")
        else:
            lineas.append("*No se detectaron carpetas vacías.*")
        lineas.append("")

        lineas.append("---")
        lineas.append("*Fin del Plan de Limpieza en Simulación.*")

        return "\n".join(lineas)

    def guardar_markdown(self, ruta_salida: str, markdown_str: str):
        """Guarda el informe en Markdown en la ruta del repositorio local."""
        self.validar_seguridad_salida(ruta_salida)
        os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
        with open(ruta_salida, "w", encoding="utf-8", newline="\n") as f:
            f.write(markdown_str)
        print(f"[+] Plan Markdown guardado exitosamente: {ruta_salida}")


def validar_huella_pre_ejecucion(ruta_raiz: str, plan_data: Dict[str, Any],
                                 tolerancia_mtime: Optional[float] = None) -> Tuple[bool, List[str]]:
    """
    Validador Pre-Ejecución:
    - NUNCA utiliza la base de datos SQLite para validar.
    - Recalcula el SHA-256 leyendo el archivo físico real en streaming desde el almacenamiento en ese momento.
    - Compara el tamaño exacto y el hash SHA-256 contra los valores registrados en la huella del plan.
    - Trata mtime como informativo, verificando con tolerancia de 2 segundos para acomodar sistemas FAT/exFAT.
    - Retorna (valido, lista_de_errores).
    """
    errores = []
    raiz_real = normalizar_raiz(ruta_raiz)
    huella = plan_data.get("huella", {})
    archivos_huella = huella.get("archivos", {})
    
    if tolerancia_mtime is None:
        cfg = plan_data.get("configuracion", {})
        tolerancia_mtime = float(cfg.get("tolerancia_mtime_segundos", 2.0))

    # Identificar qué archivos tienen acciones de movimiento en el plan
    acciones_mover = [a for a in plan_data.get("acciones", []) if a.get("destino") is not None]
    rutas_a_mover = set(a["origen"] for a in acciones_mover)

    print(f"[*] Validando huella física pre-ejecución sobre {len(rutas_a_mover)} archivos candidatos a movimiento...")

    for rel_path in sorted(rutas_a_mover):
        if rel_path not in archivos_huella:
            errores.append(f"Archivo a mover '{rel_path}' no figura en la huella del plan.")
            continue

        meta_esperado = archivos_huella[rel_path]
        tam_esperado = meta_esperado.get("size_bytes")
        sha_esperado = meta_esperado.get("sha256")
        mtime_esperado = meta_esperado.get("mtime")

        ruta_abs = os.path.join(raiz_real, rel_path)
        if not os.path.exists(ruta_abs):
            errores.append(f"Archivo físico ausente: '{rel_path}' no existe en '{ruta_abs}'.")
            continue

        try:
            stat_real = os.stat(ruta_abs)
        except OSError as e:
            errores.append(f"No se pudo consultar stat de '{rel_path}': {e}")
            continue

        # 1. Comprobación estricta de tamaño en bytes
        if stat_real.st_size != tam_esperado:
            errores.append(
                f"Discrepancia de tamaño en '{rel_path}': esperado {tam_esperado} bytes, "
                f"real en disco {stat_real.st_size} bytes."
            )
            continue

        # 2. Recálculo en tiempo real de SHA-256 leyendo el archivo físico real (SIN USAR CACHÉ SQLITE)
        sha_real = calcular_sha256(ruta_abs)
        if sha_real != sha_esperado:
            errores.append(
                f"Discrepancia de hash SHA-256 en '{rel_path}': "
                f"esperado {sha_esperado}, calculado en disco {sha_real}."
            )

        # 3. Comprobación informativa de mtime con tolerancia FAT/exFAT
        if mtime_esperado is not None:
            dif_mtime = abs(stat_real.st_mtime - mtime_esperado)
            if dif_mtime > tolerancia_mtime:
                # Se reporta como aviso o discrepancia si excede la tolerancia
                errores.append(
                    f"Discrepancia de timestamp mtime en '{rel_path}': "
                    f"esperado {mtime_esperado}, actual {stat_real.st_mtime} (diferencia {dif_mtime:.2f}s > tolerancia {tolerancia_mtime}s)."
                )

    es_valido = (len(errores) == 0)
    return es_valido, errores


def main():
    parser = argparse.ArgumentParser(
        description="Generador y Validador del Plan de Limpieza en Modo Simulación (Dry-Run)"
    )
    # Valor por defecto del pendrive si existe en Linux
    default_raiz = "/run/media/<usuario>/<pendrive>" if os.path.exists("/run/media/<usuario>/<pendrive>") else None
    parser.add_argument("--raiz", default=default_raiz, required=(default_raiz is None),
                        help="Punto de montaje o carpeta raíz del pendrive a auditar.")
    parser.add_argument("--cache", default=".cache/inventario_pendrive_cache.sqlite",
                        help="Ruta a la base de datos SQLite de caché local.")
    parser.add_argument("--config", default="config_limpieza.json",
                        help="Ruta al archivo JSON de configuración editable.")
    parser.add_argument("--salida-json", default="plan_limpieza.json",
                        help="Ruta de destino para el archivo plan_limpieza.json.")
    parser.add_argument("--salida-md", default="plan_limpieza.md",
                        help="Ruta de destino para el informe plan_limpieza.md.")
    parser.add_argument("--validar-huella", action="store_true",
                        help="Valida un plan_limpieza.json existente recalculando los hashes en vivo.")

    args = parser.parse_args()

    if args.validar_huella:
        if not os.path.exists(args.salida_json):
            print(f"[!] Error: no existe el plan JSON para validar: {args.salida_json}", file=sys.stderr)
            sys.exit(1)
        with open(args.salida_json, "r", encoding="utf-8", newline="\n") as f:
            plan_data = json.load(f)
        valido, errores = validar_huella_pre_ejecucion(args.raiz, plan_data)
        if valido:
            print("[+] Validación de huella pre-ejecución EXITOSA: todos los archivos coinciden.")
            sys.exit(0)
        else:
            print("[!] La validación de huella FALLÓ con los siguientes errores:", file=sys.stderr)
            for err in errores:
                print(f"    - {err}", file=sys.stderr)
            sys.exit(2)

    config = cargar_configuracion(args.config)
    generador = GeneradorPlanLimpieza(
        ruta_raiz=args.raiz,
        ruta_cache=args.cache,
        config=config
    )

    plan = generador.generar_plan()
    generador.guardar_json(args.salida_json, plan)
    
    md = generador.renderizar_markdown(plan)
    generador.guardar_markdown(args.salida_md, md)

    print("\n[+] Plan de limpieza simulado generado satisfactoriamente.")
    print(f"    - JSON: {args.salida_json}")
    print(f"    - Markdown: {args.salida_md}")


if __name__ == "__main__":
    main()
