#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/movimientos.py

Gestión de movimientos atómicos, simulación, renombrado y reversión:
- Simulación previa con HTML de resumen (generar_html_simulacion).
- Renombrado atómico con contadores separados para fotos y videos.
- Bitácora append-only reversible (.jsonl).
- Reversión estricta (deshacer) sin sobrescritura.
"""

import datetime
import html
import json
import logging
import os
import re
import secrets
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from bandeja.config import (
    ConfiguracionBandeja,
    ErrorSeguridadBandeja,
    ErrorValidacionEscena,
    ErrorDeshacer,
    ErrorMovimiento,
    calcular_sha256,
    formatear_bytes,
    CARACTERES_INVALIDOS_ESCENA,
    NOMBRES_RESERVADOS_WINDOWS,
)
from bandeja.db import GestorBaseDatosBandeja
from bandeja.clasificacion import (
    ValidadorEscenas,
    clasificar_familia_medio,
    asegurar_carpeta_capitulo,
)
from bandeja.capitulos import (
    simular_descartar_capitulo,
    ejecutar_descartar_capitulo,
    revertir_descarte_capitulo,
    validar_confinamiento_destino_base,
)
from bandeja.plataforma import esta_confinado_en_raiz, validar_longitud_ruta

logger = logging.getLogger("bandeja_descargas")


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

    alerta_otro_tipo = ""
    if simulacion.get("hay_otro_tipo"):
        alerta_otro_tipo = (
            f'<div style="margin:8px 0 14px 0; padding:10px 14px; background:rgba(234, 179, 8, 0.15); border:1px solid #eab308; border-radius:6px; color:#fde047; font-size:0.9rem;">'
            f'<strong>⚠️ Archivo no multimedia detectado:</strong> Contiene archivos con extensión distinta a fotos o videos. '
            f'Se moverán a la raíz de la escena conservando su nombre original sin sobreescritura.'
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

        if m.get("es_otro_tipo"):
            badge_span = f'<span class="badge-renombrado" style="color:var(--text-warning, #f59e0b); font-weight:600;">{nombre_nuev_esc} (sin renombrar)</span>'
        else:
            badge_span = f'<span class="badge-renombrado" style="color:var(--accent-primary, #60a5fa); font-weight:600;">{nombre_nuev_esc}</span>'

        fila = (
            f'<tr>'
            f'<td><strong>{nombre_orig_esc}</strong> &rarr; {badge_span}</td>'
            f'<td class="ruta-celda" title="{origen_esc}"><small style="color:var(--text-muted)">{origen_esc}</small></td>'
            f'<td class="ruta-celda destino-celda" title="{destino_esc}" data-destino="{destino_esc}">{destino_limpio_esc}</td>'
            f'</tr>'
        )
        filas.append(fila)

    filas_html = "\n".join(filas)
    return (
        f'{alerta_personaje}'
        f'{alerta_otro_tipo}'
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
                 subcarpeta_fotos: str = "fotos", subcarpeta_videos: str = "videos",
                 **kwargs):
        self.ruta_descargas = os.path.realpath(ruta_descargas)
        self.ruta_destino_base = os.path.realpath(ruta_destino_base)
        self.db = db
        self.ruta_bitacora = ruta_bitacora
        self.ruta_alias = kwargs.get("archivo_alias_personajes") or ruta_alias
        self.subcarpeta_fotos = str(kwargs.get("subcarpeta_fotos") or subcarpeta_fotos or "fotos").strip() or "fotos"
        self.subcarpeta_videos = str(kwargs.get("subcarpeta_videos") or subcarpeta_videos or "videos").strip() or "videos"
        self.alias_map = self._cargar_alias(self.ruta_alias)
        self._lock = threading.Lock()
        self.config = kwargs.get("config")

    def asegurar_carpeta_capitulo(self, personaje: str, nombre: str) -> Dict[str, Any]:
        """Asegura la creación segura y validada de la carpeta de capítulo en el destino."""
        return asegurar_carpeta_capitulo(personaje, nombre, self.ruta_destino_base, self.ruta_descargas)

    def _cargar_alias(self, ruta_alias: Optional[str]) -> Dict[str, Set[str]]:
        alias_map: Dict[str, Set[str]] = {
            "lucie": {"lucie", "luci"},
            "roli": {"roli", "laroli", "magui"},
            "mailen": {"mailen"},
            "luna": {"luna"}
        }
        if ruta_alias and os.path.exists(ruta_alias):
            try:
                with open(ruta_alias, "r", encoding="utf-8", newline="\n") as f:
                    datos = json.load(f)
                if isinstance(datos, dict):
                    if "reglas" in datos:
                        for r in datos.get("reglas", []):
                            pers = unicodedata.normalize("NFC", str(r.get("personaje", "")).strip().lower())
                            if pers:
                                if pers not in alias_map:
                                    alias_map[pers] = {pers}
                                for pat in r.get("patrones", []):
                                    limpio = unicodedata.normalize("NFC", pat.replace("*", "").strip().lower())
                                    if limpio:
                                        alias_map[pers].add(limpio)
                    else:
                        for pers, pats in datos.items():
                            p_key = unicodedata.normalize("NFC", str(pers).strip().lower())
                            if p_key not in alias_map:
                                alias_map[p_key] = {p_key}
                            if isinstance(pats, list):
                                for pat in pats:
                                    limpio = unicodedata.normalize("NFC", str(pat).replace("*", "").strip().lower())
                                    if limpio:
                                        alias_map[p_key].add(limpio)
            except Exception:
                pass
        return alias_map

    def _validar_confinamiento(self, ruta: str):
        """Asegura que la ruta canónica permanezca estrictamente dentro de ~/Descargas."""
        if not validar_longitud_ruta(ruta):
            raise ErrorSeguridadBandeja(f"Violación de seguridad: la ruta '{ruta}' excede los 260 caracteres permitidos (MAX_PATH).")
        if not esta_confinado_en_raiz(ruta, self.ruta_descargas):
            raise ErrorSeguridadBandeja(f"Violación de seguridad: la ruta '{ruta}' no pertenece a ~/Descargas.")

    def _validar_confinamiento_destino_base(self, ruta: str):
        """Asegura que la ruta canónica permanezca estrictamente dentro de ~/Descargas/_lucie y rechaza symlinks."""
        validar_confinamiento_destino_base(ruta, self.ruta_destino_base)

    def calcular_base_escena(self, personaje: str, nombre_escena: str) -> str:
        """
        Calcula la base del nombre para los archivos a mover:
        - Omitir el prefijo SOLO si la escena (en minúscula y compacta) empieza con el nombre del
          personaje elegido o con un alias de ESE personaje.
        - Si empieza con un alias de OTRO personaje, o con ninguno, la base es <personaje><escena_compacta>.
        - Elimina todos los espacios internos y caracteres de separación visual para dejar
          un estilo compacto (ej. 'lucie trapitos' -> 'lucietrapitos').
        - Garantiza que obtener_personaje_de_alias_inicial deduzca exactamente el personaje elegido.
        - Normaliza a NFC.
        """
        pers = unicodedata.normalize("NFC", (personaje or "lucie").strip().lower())
        escena_raw = unicodedata.normalize("NFC", (nombre_escena or "").strip().lower())
        # La fecha documenta la carpeta, no modifica la base de los archivos.
        escena_raw = re.sub(r" - (lunes|martes|miércoles|jueves|viernes|sábado|domingo) - semana [1-5] - [a-z]+ - [0-9]{4}$", "", escena_raw)
        escena_compacta = re.sub(r'[\s]+', '', escena_raw)

        pers_canonico = pers
        for can, aliases in self.alias_map.items():
            if pers == can or pers in aliases:
                pers_canonico = can
                break

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
        if ext == ".mp3":
            return "audio"
        return "otro"

    def obtener_contadores_carpeta_destino(self, carpeta_destino: str, base: str) -> Dict[str, int]:
        """
        Inspecciona la carpeta destino y todas sus subcarpetas (raíz, fotos/, videos/, etc.)
        buscando archivos existentes que coincidan con la base mediante regex case-insensitive
        ^<base>(\\d+)(?:\\s*\\(\\d+\\))?\\.<ext>$.
        Retorna el número inicial a usar para cada tipo: max_existente + 1.
        """
        max_foto = 0
        max_video = 0
        max_otro = 0

        if os.path.exists(carpeta_destino) and os.path.isdir(carpeta_destino):
            patron = re.compile(rf"^{re.escape(base)}(\d+)(?:\s*\(\d+\))?\.([a-zA-Z0-9]+)$", re.IGNORECASE)
            try:
                for _, _, files in os.walk(carpeta_destino):
                    for f in files:
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
                                destinos_reservados: Optional[Set[str]] = None,
                                documentar_fecha: bool = False) -> Dict[str, Any]:
        """Calcula el origen y destino exactos para cada archivo del lote antes de mover con renombrado."""
        valido, motivo = ValidadorEscenas.validar_nombre_escena(
            nombre_escena, self.ruta_destino_base, self.ruta_descargas,
            es_existente_descargas=es_existente_descargas, personaje=personaje
        )
        if not valido:
            raise ErrorValidacionEscena(motivo)

        if documentar_fecha and not es_existente_descargas:
            existente = os.path.join(self.ruta_destino_base, personaje, nombre_escena)
            foco = self.db.obtener_capitulo_en_foco()
            conocido = foco and foco.get("personaje") == personaje and foco.get("nombre") == nombre_escena
            if not os.path.isdir(existente) and not conocido:
                from bandeja.clasificacion import nombre_carpeta_documentado
                nombre_escena = nombre_carpeta_documentado(nombre_escena)
                valido, motivo = ValidadorEscenas.validar_nombre_escena(
                    nombre_escena, self.ruta_destino_base, self.ruta_descargas, personaje=personaje)
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

        contadores = self.obtener_contadores_carpeta_destino(carpeta_destino, base)

        destinos_vistos: Set[str] = set()
        if destinos_reservados:
            destinos_vistos.update(d.lower() for d in destinos_reservados)

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

            if not es_existente_descargas:
                if familia == "foto":
                    subcarpeta = self.subcarpeta_fotos
                elif familia == "video":
                    subcarpeta = self.subcarpeta_videos
                elif familia == "audio":
                    subcarpeta = "audios"
                else:
                    subcarpeta = ""
            else:
                subcarpeta = ""

            carpeta_target = os.path.join(carpeta_destino, subcarpeta) if subcarpeta else carpeta_destino

            archivos_target_lower: Set[str] = set()
            if os.path.exists(carpeta_target) and os.path.isdir(carpeta_target):
                try:
                    archivos_target_lower = {f.lower() for f in os.listdir(carpeta_target)}
                except OSError:
                    pass

            es_otro = (familia == "otro")
            advertencia = ""

            if es_otro or familia == "audio":
                if es_otro:
                    advertencia = "Extensión no multimedia: se moverá a la raíz de la escena con su nombre original."
                nombre_base_orig, ext_orig = os.path.splitext(nombre_archivo_original)
                candidato_nombre = nombre_archivo_original
                candidato_ruta = os.path.join(carpeta_target, candidato_nombre)
                sufijo_idx = 1
                while (candidato_nombre.lower() in archivos_target_lower or
                       candidato_ruta.lower() in destinos_vistos or
                       os.path.exists(candidato_ruta)):
                    candidato_nombre = f"{nombre_base_orig} ({sufijo_idx}){ext_orig}"
                    candidato_ruta = os.path.join(carpeta_target, candidato_nombre)
                    sufijo_idx += 1

                destinos_vistos.add(candidato_ruta.lower())
                destino_final = candidato_ruta
                nombre_nuevo = candidato_nombre
            else:
                while True:
                    num = contadores[familia]
                    nombre_candidato = f"{base}{num}{ext_lower}"
                    ruta_candidata = os.path.join(carpeta_target, nombre_candidato)
                    nombre_candidato_lower = nombre_candidato.lower()
                    ruta_candidata_lower = ruta_candidata.lower()
                    contadores[familia] += 1

                    if (nombre_candidato_lower not in archivos_target_lower and
                        ruta_candidata_lower not in destinos_vistos and
                        not os.path.exists(ruta_candidata)):
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
                "subcarpeta_tipo": subcarpeta,
                "es_otro_tipo": es_otro,
                "advertencia": advertencia,
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
            "hay_otro_tipo": any(m.get("es_otro_tipo") for m in movimientos_simulados),
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
            archivos_en_uso = []
            id_operacion = f"op_{int(time.time())}_{secrets.token_hex(4)}"
            fecha_iso = datetime.datetime.now().isoformat()

            for item in simulacion["movimientos"]:
                origen = item["origen"]
                destino = item["destino"]
                self._validar_confinamiento(origen)
                self._validar_confinamiento(destino)

                if not os.path.exists(origen):
                    raise FileNotFoundError(f"El archivo de origen '{origen}' ya no existe.")

                # Validar que origen y destino compartan unidad antes de intentar rename
                drive_orig, _ = os.path.splitdrive(os.path.abspath(origen))
                drive_dest, _ = os.path.splitdrive(os.path.abspath(destino))
                if drive_orig.upper() != drive_dest.upper():
                    raise ErrorMovimiento(
                        f"No es posible mover con rename entre diferentes unidades ({drive_orig} -> {drive_dest})."
                    )

                dir_destino = os.path.dirname(destino)
                if not simulacion.get("es_existente_descargas"):
                    self._validar_confinamiento_destino_base(dir_destino)
                else:
                    self._validar_confinamiento(dir_destino)
                os.makedirs(dir_destino, exist_ok=True)

                destino_final = self.resolver_destino_sin_colision(destino)

                # Intentar mover el archivo manejando posibles bloqueos de proceso en Windows
                try:
                    os.rename(origen, destino_final)
                except (PermissionError, OSError) as e_lock:
                    # Capturar WinError 32 o PermissionError
                    cod = getattr(e_lock, "winerror", None) or getattr(e_lock, "errno", None)
                    if isinstance(e_lock, PermissionError) or cod in (32, 13):
                        logger.warning(f"Archivo en uso o bloqueado al mover '{origen}': {e_lock}")
                        archivos_en_uso.append({
                            "archivo": origen,
                            "motivo": "archivo en uso"
                        })
                        continue
                    raise

                hash_val = item.get("hash") or calcular_sha256(destino_final)

                nombre_orig = item.get("nombre_original") or os.path.basename(origen)
                nombre_nuev = os.path.basename(destino_final)

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

            self.db.guardar_ultimo_personaje(simulacion["personaje"])
            self.db.incrementar_movidos_capitulo(simulacion["personaje"], simulacion["escena"], len(movimientos_realizados))

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

            with open(self.ruta_bitacora, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(registro_bitacora, ensure_ascii=False) + "\n")

            personaje = simulacion.get("personaje", "")
            escena = simulacion.get("escena", "")
            total_movidos = len(movimientos_realizados)
            mensaje_aviso = f"Se movieron {total_movidos} archivos a {personaje}/{escena}"
            if archivos_en_uso:
                mensaje_aviso += f" ({len(archivos_en_uso)} archivos en uso no se pudieron mover)"

            return {
                "exito": True,
                "id_operacion": id_operacion,
                "total_movidos": total_movidos,
                "archivos_en_uso": archivos_en_uso,
                "personaje": personaje,
                "escena": escena,
                "mensaje_aviso": mensaje_aviso
            }

    def simular_descartar_capitulo(self, capitulo_id: int) -> Dict[str, Any]:
        """
        Simula el descarte de un capítulo moviéndolo hacia ~/Descargas/_lucie/_descartados/<personaje>/<escena>_<timestamp>/.
        Retorna origen, destino, conteo de archivos, peso total y aviso anti-borrado.
        """
        return simular_descartar_capitulo(
            db=self.db,
            ruta_destino_base=self.ruta_destino_base,
            ruta_descargas=self.ruta_descargas,
            capitulo_id=capitulo_id,
        )

    def ejecutar_descartar_capitulo(self, simulacion: Dict[str, Any], nombre_confirmacion: str) -> Dict[str, Any]:
        """
        Ejecuta el descarte del capítulo trasladando su carpeta a _descartados con un único os.rename.
        Exige coincidencia exacta de nombre_confirmacion con el nombre del capítulo.
        """
        return ejecutar_descartar_capitulo(
            db=self.db,
            ruta_destino_base=self.ruta_destino_base,
            ruta_descargas=self.ruta_descargas,
            ruta_bitacora=self.ruta_bitacora,
            simulacion=simulacion,
            nombre_confirmacion=nombre_confirmacion,
            lock=self._lock,
        )

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

            operacion_encontrada = None
            todas_operaciones = []
            with open(self.ruta_bitacora, "r", encoding="utf-8", newline="\n") as f:
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
                return revertir_descarte_capitulo(
                    db=self.db,
                    ruta_bitacora=self.ruta_bitacora,
                    operacion_encontrada=operacion_encontrada,
                    id_operacion=id_operacion,
                )

            # Caso especial 2: Reversión de envío al pendrive
            if operacion_encontrada.get("evento") == "envio_pendrive":
                try:
                    from bandeja.pendrive import deshacer_envio_pendrive
                except ImportError:
                    from bandeja_descargas import deshacer_envio_pendrive
                return deshacer_envio_pendrive(
                    id_operacion=id_operacion,
                    operacion=operacion_encontrada,
                    config=getattr(self, "config", None),
                    db=self.db,
                    ruta_bitacora=self.ruta_bitacora
                )

            # Fase 1: Verificación preventiva integral para movimientos normales
            for mov in operacion_encontrada["movimientos"]:
                origen_anterior = mov["origen_anterior"]
                destino_nuevo = mov["destino_nuevo"]

                if not os.path.exists(destino_nuevo):
                    raise ErrorDeshacer(
                        f"No se puede deshacer: el archivo en '{destino_nuevo}' ya no existe o fue movido externamente."
                    )

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

                self.db.registrar_o_actualizar(
                    hash_val=mov["hash"],
                    ruta_actual=origen_anterior,
                    estado="detectado"
                )
                archivos_revertidos.append(origen_anterior)

            evento_reversion = {
                "evento": "deshacer",
                "id_operacion_revertida": id_operacion,
                "fecha": datetime.datetime.now().isoformat(),
                "total_revertidos": len(archivos_revertidos)
            }
            with open(self.ruta_bitacora, "a", encoding="utf-8", newline="\n") as f:
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
                with open(self.ruta_bitacora, "r", encoding="utf-8", newline="\n") as f:
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

                if e.get("evento") == "envio_pendrive":
                    estado = "deshecho" if id_op in revertidas else "enviado"
                    total_arch = e.get("total_archivos", 0)
                    caps_txt = ", ".join(e.get("capitulos", []))
                    movimientos_resultado.append({
                        "id_operacion": id_op,
                        "fecha": fecha_op,
                        "archivo": f"Envío pendrive: {total_arch} archivo(s) ({caps_txt})",
                        "nombre_original": f"{total_arch} archivo(s)",
                        "nombre_nuevo": f"Pendrive ({str(e.get('pendrive_id', ''))[:8]}...)",
                        "origen": "Sala de espera",
                        "destino": e.get("pendrive_montaje", "Pendrive"),
                        "tamanio": e.get("bytes_totales", 0),
                        "hash": "",
                        "estado": estado,
                        "tipo_evento": "envio_pendrive",
                        "archivos": e.get("archivos", [])
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
