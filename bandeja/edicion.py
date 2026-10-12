#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/edicion.py

Gestor de posproducción, sesiones de edición y transiciones en pendrive (Tramo 3).
Cumple estrictamente las 7 Reglas de Oro del proyecto:
- Regla #1: Prohibición absoluta de borrado y pisado destructivo.
- Regla #2: Validación estricta y nombres normalizados.
- Regla #3: Excepción única y controlada para copia automática a videos completos con deshacer inmediato.
- Regla #4: Verificación de integridad SHA-256 en vuelo y por relectura.
- Regla #5: Transición atómica de crudos vía os.rename dentro del pendrive.
- Regla #6: Registro append-only en manifiesto.jsonl y bitácora reversible.
- Regla #7: Auditoría AST con 0 infracciones.
"""

import datetime
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.pendrive import NOMBRE_MANIFIESTO_PENDRIVE, operacion_pendrive_exclusiva
from bandeja.plataforma import esta_confinado_en_raiz, verificar_archivo_exclusivo, mover_sin_sobrescribir

logger = logging.getLogger("bandeja_edicion")
_lock_manifiesto_edicion = threading.Lock()


def nombre_carpeta_video(nombre: str, fecha: Optional[datetime.datetime] = None) -> str:
    """Nombre del video, día, semana del mes, mes español y año del traslado."""
    fecha = fecha or datetime.datetime.now()
    from bandeja.clasificacion import nombre_carpeta_documentado
    base = os.path.splitext(os.path.basename(nombre))[0]
    return nombre_carpeta_documentado(base, fecha)


def nombre_carpeta_ya_editado(nombre: str, fecha: Optional[datetime.datetime] = None) -> str:
    """Etiqueta de crudos editados, independiente del nombre del export final."""
    fecha = fecha or datetime.datetime.now()
    meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    base = os.path.splitext(os.path.basename(nombre))[0].strip()
    base = re.sub(r"(?i)[ _-]*video[ _-]*completo$", "", base).strip(" _-")
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    base = re.sub(r"\s+", "_", base).strip(" ._") or "edicion"
    return f"videoyaeditado_{base}_semana_{(fecha.day - 1) // 7 + 1}_{meses[fecha.month - 1]}_{fecha.year}"


def _destinos_editados_sesion(pendrive_raiz: str, identificador: str, incluir_preservados=False):
    """Recupera rutas efectivas del manifiesto para reintentos y deshacer sin fecha actual."""
    ruta = os.path.join(pendrive_raiz, ".lucie", NOMBRE_MANIFIESTO_PENDRIVE)
    destinos = {}
    preservados = set()
    if not os.path.isfile(ruta):
        return (destinos, preservados) if incluir_preservados else destinos
    with open(ruta, "r", encoding="utf-8") as archivo:
        for linea in archivo:
            try:
                evento = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if evento.get("sesion_id") != identificador:
                continue
            clip = evento.get("clip")
            if evento.get("tipo_evento") == "editado" and evento.get("ruta_destino"):
                destinos[clip] = os.path.join(pendrive_raiz, evento["ruta_destino"].replace("/", os.sep))
                if evento.get("original_preservado"):
                    preservados.add(clip)
                else:
                    preservados.discard(clip)
            elif evento.get("tipo_evento") == "deshacer_editado":
                destinos.pop(clip, None)
                preservados.discard(clip)
    return (destinos, preservados) if incluir_preservados else destinos


def _copiar_crudo_bloqueado(origen, destino, sha_esperado, pendrive_raiz):
    """Copia verificada sin alterar el original retenido por CapCut."""
    temporal = destino + "." + str(uuid.uuid4()) + ".part"
    if shutil.disk_usage(pendrive_raiz).free < os.path.getsize(origen) + 10_000_000:
        raise OSError("No hay espacio suficiente para conservar original y copia editada.")
    try:
        with open(origen, "rb") as entrada, open(temporal, "xb") as salida:
            shutil.copyfileobj(entrada, salida, 1024 * 1024)
            salida.flush()
            os.fsync(salida.fileno())
        if calcular_sha256(temporal) != sha_esperado or calcular_sha256(origen) != sha_esperado:
            raise ValueError("El clip cambió durante la copia o la copia no coincide con el original.")
        if os.path.exists(destino):
            raise FileExistsError("El destino se ocupó durante la copia; no se sobrescribe.")
        mover_sin_sobrescribir(temporal, destino)
    except Exception:
        if os.path.isfile(temporal):
            revision = os.path.join(pendrive_raiz, "_a_revisar", "copias_fallidas")
            if not esta_confinado_en_raiz(revision, pendrive_raiz):
                raise ValueError("Ruta de revisión fuera del pendrive.")
            os.makedirs(revision, exist_ok=True)
            os.rename(temporal, os.path.join(revision, os.path.basename(temporal)))
            registrar_evento_manifiesto_edicion(pendrive_raiz, {
                "id_evento": str(uuid.uuid4()), "fecha": datetime.datetime.now().isoformat(),
                "tipo_evento": "copia_editado_fallida", "origen": origen,
                "ruta_conservada": os.path.relpath(os.path.join(revision, os.path.basename(temporal)), pendrive_raiz).replace(os.sep, "/"),
                "sha256_esperado": sha_esperado})
        raise


def calcular_nombre_defecto(clips: List[str], capitulo: str) -> str:
    """
    Calcula el nombre por defecto del video final:
    - Si hay múltiples clips o sesión para capítulo: <capítulo>videocompleto.mp4
    - Si hay un solo clip: <nombre_sin_ext>videocompleto.mp4
    """
    cap_limpio = (capitulo or "capitulo").strip().lower()
    for char in '<>:"/\\|?* .':
        cap_limpio = cap_limpio.replace(char, "")

    if len(clips) == 1:
        base_clip = os.path.basename(clips[0])
        nombre_sin_ext, _ = os.path.splitext(base_clip)
        limpio = nombre_sin_ext.strip().lower()
        for char in '<>:"/\\|?* .':
            limpio = limpio.replace(char, "")
        if limpio:
            return f"{limpio}videocompleto.mp4"

    return f"{cap_limpio}videocompleto.mp4"


def registrar_evento_manifiesto_edicion(
    pendrive_raiz: str,
    evento: Dict[str, Any],
):
    """
    Registra un evento append-only en <pendrive_raiz>/.lucie/manifiesto.jsonl.
    """
    dir_lucie = os.path.join(pendrive_raiz, ".lucie")
    if not esta_confinado_en_raiz(dir_lucie, pendrive_raiz):
        raise ValueError("Metadatos fuera del pendrive.")
    os.makedirs(dir_lucie, exist_ok=True)
    ruta_manifiesto = os.path.join(dir_lucie, NOMBRE_MANIFIESTO_PENDRIVE)
    if not esta_confinado_en_raiz(ruta_manifiesto, pendrive_raiz):
        raise ValueError("Manifiesto fuera del pendrive.")
    with _lock_manifiesto_edicion, open(ruta_manifiesto, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def registrar_bitacora_edicion(
    ruta_bitacora: str,
    evento: Dict[str, Any],
):
    """
    Registra un evento append-only en la bitácora local.
    """
    os.makedirs(os.path.dirname(os.path.abspath(ruta_bitacora)), exist_ok=True)
    with open(ruta_bitacora, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


# =========================================================================
# Inspección de Secciones desde el Pendrive
# =========================================================================

def obtener_sesiones_con_crudos_pendientes(db):
    return [s for s in db.obtener_sesiones_edicion()
            if s["estado"] == "en_edicion" or (s["estado"] == "completado" and not s.get("fecha_cierre"))]


def obtener_secciones_edicion(
    pendrive_montaje: str,
    db: GestorBaseDatosBandeja,
    carpeta_raiz: str = "LucieSinReglas",
    vigilante: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Inspecciona el pendrive (fuente de verdad) y la base de datos para construir
    las tres secciones de la vista Edición:
    1. 'para_editar': clips crudos en 'videos sin editar' que no están en sesiones activas.
    2. 'en_edicion': sesiones actualmente abiertas con sus clips agrupados.
    3. 'editados_y_completos': resumen por capítulo de crudos ya editados y videos completos.
    4. 'exports_sin_asignar': exports de CapCut detectados sin vincular.
    """
    pendrive_raiz = os.path.join(pendrive_montaje, carpeta_raiz)
    dir_sin_editar = os.path.join(pendrive_raiz, "videos sin editar")
    dir_ya_editados = os.path.join(pendrive_raiz, "videos ya editados")
    dir_completos = os.path.join(pendrive_raiz, "videos completos")
    capitulos_por_ruta = {}
    for sesion in db.obtener_sesiones_edicion():
        rutas = list(_destinos_editados_sesion(pendrive_raiz, sesion["identificador"]).values())
        if sesion.get("video_completo_ruta"):
            rutas.append(sesion["video_completo_ruta"])
        for ruta in rutas:
            capitulos_por_ruta[os.path.normcase(os.path.abspath(ruta))] = sesion["capitulo"]

    sesiones_activas = obtener_sesiones_con_crudos_pendientes(db)
    clips_finalizados = set()
    for s in db.obtener_sesiones_edicion():
        if s["estado"] in ("editado", "completado") and s.get("fecha_cierre"):
            clips_finalizados.update(c for c, ruta in _destinos_editados_sesion(pendrive_raiz, s["identificador"]).items() if os.path.isfile(ruta))
    clips_en_sesion: Set[str] = set()
    for s in sesiones_activas:
        for c in s.get("clips", []):
            clips_en_sesion.add(c)

    para_editar: List[Dict[str, Any]] = []
    conteos_capitulo: Dict[str, Dict[str, int]] = {}

    def _asegurar_conteo(cap: str):
        if cap not in conteos_capitulo:
            conteos_capitulo[cap] = {
                "sin_editar": 0,
                "en_edicion": 0,
                "ya_editados": 0,
                "completos": 0,
            }

    # 1. Explorar 'videos sin editar'
    for base_crudos, prefijo in ((dir_sin_editar, ""), (os.path.join(pendrive_raiz, "audios"), "audios/")):
        for raiz, _dirs, archivos in os.walk(base_crudos):
            for arch in archivos:
                if arch.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".mp3")):
                    ruta_abs = os.path.join(raiz, arch)
                    rel = os.path.relpath(ruta_abs, base_crudos)
                    partes = rel.split(os.sep)
                    personaje = partes[0] if len(partes) > 1 else "general"
                    capitulo = partes[1] if len(partes) > 2 else "sin_capitulo"
                    _asegurar_conteo(capitulo)

                    identificador_clip = prefijo + rel.replace(os.sep, "/")
                    if identificador_clip in clips_finalizados:
                        continue
                    try:
                        st = os.stat(ruta_abs)
                        tamano = st.st_size
                        mtime = st.st_mtime
                    except OSError:
                        tamano = 0
                        mtime = 0

                    id_media = None
                    if vigilante and hasattr(vigilante, "registrar_ruta_media"):
                        try:
                            id_media = vigilante.registrar_ruta_media(ruta_abs)
                        except Exception:
                            id_media = None

                    if identificador_clip in clips_en_sesion:
                        conteos_capitulo[capitulo]["en_edicion"] += 1
                    else:
                        conteos_capitulo[capitulo]["sin_editar"] += 1
                        clip_dict: Dict[str, Any] = {
                            "identificador": identificador_clip,
                            "nombre": arch,
                            "personaje": personaje,
                            "capitulo": capitulo,
                            "ruta_relativa": identificador_clip,
                            "tamano": tamano,
                            "mtime": mtime,
                            "tipo": "audio" if arch.lower().endswith(".mp3") else "video",
                        }
                        if id_media:
                            clip_dict["id_media"] = id_media
                        para_editar.append(clip_dict)

    # 2. Explorar 'videos ya editados'
    if os.path.exists(dir_ya_editados):
        for raiz, _dirs, archivos in os.walk(dir_ya_editados):
            for arch in archivos:
                if arch.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".mp3")):
                    ruta_abs = os.path.join(raiz, arch)
                    rel = os.path.relpath(ruta_abs, dir_ya_editados)
                    partes = rel.split(os.sep)
                    capitulo = capitulos_por_ruta.get(os.path.normcase(os.path.abspath(ruta_abs))) or (partes[1] if len(partes) > 2 else "sin_capitulo")
                    _asegurar_conteo(capitulo)
                    conteos_capitulo[capitulo]["ya_editados"] += 1

    # 3. Explorar 'videos completos'
    if os.path.exists(dir_completos):
        for raiz, _dirs, archivos in os.walk(dir_completos):
            for arch in archivos:
                if arch.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".mp3")):
                    ruta_abs = os.path.join(raiz, arch)
                    rel = os.path.relpath(ruta_abs, dir_completos)
                    partes = rel.split(os.sep)
                    if partes[0] == "videos sin publicar":
                        partes = partes[1:]
                    capitulo = capitulos_por_ruta.get(os.path.normcase(os.path.abspath(ruta_abs))) or (partes[1] if len(partes) > 2 else "sin_capitulo")
                    _asegurar_conteo(capitulo)
                    conteos_capitulo[capitulo]["completos"] += 1

    # 4. Exports sin asignar de CapCut
    exports_sin_asignar = db.obtener_exports_pendientes(estado="sin_asignar")

    return {
        "para_editar": para_editar,
        "en_edicion": sesiones_activas,
        "conteos_capitulo": conteos_capitulo,
        "exports_sin_asignar": exports_sin_asignar,
        "videos_completados": obtener_videos_completados(db),
        "sesiones_para_export": obtener_sesiones_para_export(db),
    }


# =========================================================================
# Ciclo de Vida de Sesiones
# =========================================================================

def crear_sesion(
    db: GestorBaseDatosBandeja,
    clips: List[str],
    personaje: str,
    capitulo: str,
    nombre_sesion: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Crea una sesión de edición con uno o más clips seleccionados.
    No mueve ningún archivo físico en el pendrive (Regla de Oro #1).
    """
    if not clips:
        raise ValueError("Debe seleccionar al menos un clip para iniciar una sesión de edición.")

    nombre_final_def = calcular_nombre_defecto(clips, capitulo)
    nombre = (nombre_sesion or nombre_final_def).strip()
    identificador = str(uuid.uuid4())

    sesion_id = db.crear_sesion_edicion(
        identificador=identificador,
        nombre=nombre,
        nombre_final_defecto=nombre_final_def,
        personaje=personaje,
        capitulo=capitulo,
        clips=clips,
    )

    return {
        "id": sesion_id,
        "identificador": identificador,
        "nombre": nombre,
        "nombre_final_defecto": nombre_final_def,
        "personaje": personaje,
        "capitulo": capitulo,
        "clips": clips,
        "estado": "en_edicion",
    }


def _origen_clip(pendrive_raiz, clip):
    """Los videos conservan IDs históricos; audios usan prefijo audios/."""
    audio = clip.startswith("audios/")
    base = os.path.join(pendrive_raiz, "audios" if audio else "videos sin editar")
    relativa = clip[len("audios/"):] if audio else clip
    return base, os.path.join(base, relativa.replace("/", os.sep))


def obtener_carpeta_edicion(sesion, punto_montaje, carpeta_raiz="LucieSinReglas"):
    """Devuelve la carpeta del capítulo de los videos, o de audios si no hay video."""
    clips = sesion.get("clips", [])
    if not clips:
        raise ValueError("La sesión no tiene archivos seleccionados.")
    clip = next((c for c in clips if not c.startswith("audios/")), clips[0])
    partes = clip.split("/")
    relativa = partes[1:] if partes[0] == "audios" else partes
    if len(relativa) < 3 or any(p in ("", ".", "..") or "\\" in p or ":" in p for p in partes):
        raise ValueError("Ruta de edición inválida.")
    if relativa[:2] != [sesion["personaje"], sesion["capitulo"]]:
        raise ValueError("El archivo no corresponde al capítulo de la sesión.")
    raiz = os.path.join(punto_montaje, carpeta_raiz)
    base, _ = _origen_clip(raiz, clip)
    carpeta = os.path.join(base, *relativa[:2])
    actual = carpeta
    while True:
        if os.path.islink(actual) or (hasattr(os.path, "isjunction") and os.path.isjunction(actual)):
            raise ValueError("No se permiten enlaces en la carpeta de edición.")
        padre = os.path.dirname(actual)
        if padre == actual:
            break
        actual = padre
    if not esta_confinado_en_raiz(carpeta, raiz) or not os.path.isdir(carpeta):
        raise ValueError("La carpeta del capítulo no está disponible en el pendrive.")
    return os.path.abspath(carpeta)


def sumar_videos_sesion(db, sesion_id, clips, punto_montaje, carpeta_raiz="LucieSinReglas"):
    """Agrega referencias de crudos a una sesión abierta sin mover archivos."""
    if not isinstance(clips, list) or not clips or any(not isinstance(c, str) for c in clips):
        raise ValueError("Seleccioná al menos un video válido.")
    for clip in clips:
        partes = clip.split("/")
        if len(partes) < 3 or any(p in ("", ".", "..") or "\\" in p or ":" in p for p in partes):
            raise ValueError("Ruta de video inválida.")
        base, ruta = _origen_clip(os.path.join(punto_montaje, carpeta_raiz), clip)
        actual = ruta
        while True:
            if os.path.islink(actual) or (hasattr(os.path, "isjunction") and os.path.isjunction(actual)):
                raise ValueError("No se admiten enlaces en la ruta del video.")
            padre = os.path.dirname(actual)
            if padre == actual:
                break
            actual = padre
        if os.path.commonpath([os.path.realpath(base), os.path.realpath(ruta)]) != os.path.realpath(base):
            raise ValueError("Video fuera de la carpeta de crudos.")
        if not os.path.isfile(ruta) or not ruta.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".mp3")):
            raise ValueError("El video ya no está disponible en la carpeta de crudos.")
    return db.sumar_clips_sesion_edicion(sesion_id, clips)


def cancelar_sesion(
    db: GestorBaseDatosBandeja,
    sesion_id: int,
) -> bool:
    """
    Cancela una sesión de edición abierta.
    No altera archivos físicos; los clips vuelven a 'Para editar'.
    """
    sesion = db.obtener_sesion_por_id(sesion_id)
    if not sesion or sesion["estado"] != "en_edicion":
        return False
    return db.actualizar_sesion_edicion(
        sesion_id,
        estado="cancelado",
        fecha_cierre=datetime.datetime.now().isoformat(),
    )


# =========================================================================
# Transición "Terminé de editar" (videos sin editar -> videos ya editados)
# =========================================================================

def finalizar_edicion_crudos(
    db: GestorBaseDatosBandeja,
    sesion_id: int,
    pendrive_montaje: str,
    carpeta_raiz: str = "LucieSinReglas",
    ruta_bitacora: str = "bitacora_bandeja.jsonl",
) -> Dict[str, Any]:
    """
    Mueve los clips crudos de la sesión de 'videos sin editar' a 'videos ya editados'
    utilizando os.rename dentro del mismo pendrive.
    Verifica que el destino no exista; si existe con distinto hash, marca conflicto.
    """
    sesion = db.obtener_sesion_por_id(sesion_id)
    if not sesion:
        raise ValueError(f"No existe la sesión {sesion_id}")

    pendrive_raiz = os.path.join(pendrive_montaje, carpeta_raiz)
    dir_sin_editar = os.path.join(pendrive_raiz, "videos sin editar")
    dir_ya_editados = os.path.join(pendrive_raiz, "videos ya editados")

    clips = sesion.get("clips", [])
    destinos_registrados = _destinos_editados_sesion(pendrive_raiz, sesion["identificador"])
    fecha_traslado = datetime.datetime.now()
    movidos = []
    conflictos = []
    omisiones = []

    # Validar el lote entero antes de mover el primer clip. Un faltante no debe
    # dejar más archivos trasladados ni una sesión parcialmente finalizada.
    for rel_clip in clips:
        base_orig, ruta_orig = _origen_clip(pendrive_raiz, rel_clip)
        ruta_anterior = os.path.join(dir_ya_editados, rel_clip.replace("/", os.sep))
        ruta_dest = destinos_registrados.get(rel_clip) or (
            ruta_anterior if os.path.exists(ruta_anterior) else os.path.join(
                dir_ya_editados, sesion["personaje"],
                nombre_carpeta_ya_editado(sesion.get("nombre") or sesion["nombre_final_defecto"], fecha_traslado),
                os.path.basename(ruta_anterior)))
        if not esta_confinado_en_raiz(ruta_orig, base_orig) or not esta_confinado_en_raiz(ruta_dest, dir_ya_editados):
            conflictos.append({"clip": rel_clip, "error": "Ruta no confinada en el pendrive"})
        elif not os.path.isfile(ruta_orig) and not os.path.isfile(ruta_dest):
            conflictos.append({"clip": rel_clip, "error": f"Archivo de origen no existe: '{ruta_orig}'"})
        elif os.path.exists(ruta_dest) and os.path.isfile(ruta_orig):
            if not os.path.isfile(ruta_dest) or calcular_sha256(ruta_orig) != calcular_sha256(ruta_dest):
                conflictos.append({"clip": rel_clip, "error": "Destino ocupado con contenido distinto. Prohibido sobreescribir."})
    if conflictos:
        return {"exito": False, "sesion_id": sesion_id, "id_operacion": None,
                "movidos": [], "conflictos": conflictos, "omisiones": [], "fase": "validacion_previa"}

    for rel_clip in clips:
        # Asegurar ruta confinada
        base_orig, ruta_orig = _origen_clip(pendrive_raiz, rel_clip)
        ruta_anterior = os.path.join(dir_ya_editados, rel_clip.replace("/", os.sep))
        ruta_dest = destinos_registrados.get(rel_clip)
        if not ruta_dest:
            ruta_dest = ruta_anterior if os.path.exists(ruta_anterior) else os.path.join(
                dir_ya_editados, sesion["personaje"],
                nombre_carpeta_ya_editado(sesion.get("nombre") or sesion["nombre_final_defecto"], fecha_traslado),
                os.path.basename(ruta_anterior),
            )

        if not esta_confinado_en_raiz(ruta_orig, base_orig) or not esta_confinado_en_raiz(ruta_dest, dir_ya_editados):
            conflictos.append({"clip": rel_clip, "error": "Ruta no confinada en el pendrive"})
            continue

        if not os.path.isfile(ruta_orig):
            # Podría haber sido ya movido previamente
            if os.path.isfile(ruta_dest):
                omisiones.append({"clip": rel_clip, "detalle": "Ya se encontraba en videos ya editados"})
                continue
            conflictos.append({"clip": rel_clip, "error": f"Archivo de origen no existe: '{ruta_orig}'"})
            continue

        if os.path.exists(ruta_dest):
            # Comprobación de contenido por hash
            sha_orig = calcular_sha256(ruta_orig)
            sha_dest = calcular_sha256(ruta_dest)
            if sha_orig and sha_orig == sha_dest:
                omisiones.append({"clip": rel_clip, "detalle": "Destino ya existe con contenido idéntico"})
                continue
            else:
                conflictos.append({
                    "clip": rel_clip,
                    "error": "Destino ya existe con contenido distinto. Prohibido sobreescribir."
                })
                continue

        # Traslado seguro
        os.makedirs(os.path.dirname(ruta_dest), exist_ok=True)
        sha_orig = calcular_sha256(ruta_orig)
        original_preservado = False
        try:
            os.rename(ruta_orig, ruta_dest)
        except OSError as e:
            if getattr(e, "winerror", None) not in (32, 33):
                conflictos.append({"clip": rel_clip, "error": str(e)})
                continue
            try:
                _copiar_crudo_bloqueado(ruta_orig, ruta_dest, sha_orig, pendrive_raiz)
                original_preservado = True
            except (OSError, ValueError) as copia_error:
                conflictos.append({"clip": rel_clip, "error": f"No se pudo copiar el clip en uso: {copia_error}"})
                continue

        movidos.append({
            "clip": rel_clip,
            "origen": ruta_orig,
            "destino": ruta_dest,
            "sha256": sha_orig,
            "original_preservado": original_preservado,
        })

        # Registrar evento en manifiesto del pendrive
        registrar_evento_manifiesto_edicion(
            pendrive_raiz,
            {
                "id_evento": str(uuid.uuid4()),
                "fecha": datetime.datetime.now().isoformat(),
                "tipo_evento": "editado",
                "sesion_id": sesion["identificador"],
                "clip": rel_clip,
                "ruta_destino": os.path.relpath(ruta_dest, pendrive_raiz).replace(os.sep, "/"),
                "sha256": sha_orig,
                "original_preservado": original_preservado,
            }
        )

    # Registrar en bitácora local
    id_operacion_edicion = str(uuid.uuid4())
    registro_bit = {
        "id_operacion": id_operacion_edicion,
        "tipo_operacion": "finalizar_edicion_crudos",
        "fecha": datetime.datetime.now().isoformat(),
        "sesion_id": sesion["id"],
        "sesion_identificador": sesion["identificador"],
        "movidos": movidos,
        "pendrive_raiz": pendrive_raiz,
    }
    registrar_bitacora_edicion(ruta_bitacora, registro_bit)

    # Actualizar sesión si no hubo conflictos
    if not conflictos:
        db.actualizar_sesion_edicion(
            sesion_id,
            estado="completado" if sesion.get("video_completo_ruta") else "editado",
            fecha_cierre=datetime.datetime.now().isoformat(),
        )

    return {
        "exito": len(conflictos) == 0,
        "sesion_id": sesion_id,
        "id_operacion": id_operacion_edicion,
        "movidos": movidos,
        "conflictos": conflictos,
        "omisiones": omisiones,
    }


def deshacer_finalizar_edicion(
    db: GestorBaseDatosBandeja,
    sesion_id: int,
    pendrive_montaje: str,
    carpeta_raiz: str = "LucieSinReglas",
    ruta_bitacora: str = "bitacora_bandeja.jsonl",
) -> Dict[str, Any]:
    """
    Deshace el paso de crudos a 'videos ya editados', retornándolos a 'videos sin editar'.
    Solo revierte si el origen en 'videos sin editar' está libre.
    """
    sesion = db.obtener_sesion_por_id(sesion_id)
    if not sesion:
        raise ValueError(f"No existe la sesión {sesion_id}")

    pendrive_raiz = os.path.join(pendrive_montaje, carpeta_raiz)
    dir_sin_editar = os.path.join(pendrive_raiz, "videos sin editar")
    dir_ya_editados = os.path.join(pendrive_raiz, "videos ya editados")

    clips = sesion.get("clips", [])
    destinos_registrados, originales_preservados = _destinos_editados_sesion(pendrive_raiz, sesion["identificador"], incluir_preservados=True)
    revertidos = []
    conflictos = []

    for rel_clip in clips:
        base_orig, ruta_orig = _origen_clip(pendrive_raiz, rel_clip)
        ruta_dest = destinos_registrados.get(rel_clip) or os.path.join(dir_ya_editados, rel_clip.replace("/", os.sep))

        if not esta_confinado_en_raiz(ruta_orig, base_orig) or not esta_confinado_en_raiz(ruta_dest, dir_ya_editados):
            conflictos.append({"clip": rel_clip, "error": "Ruta no confinada en el pendrive"})
            continue

        if not os.path.isfile(ruta_dest):
            continue

        if os.path.exists(ruta_orig):
            if rel_clip in originales_preservados and os.path.isfile(ruta_orig) and calcular_sha256(ruta_orig) == calcular_sha256(ruta_dest):
                conservada = os.path.join(pendrive_raiz, "_revertidos", str(uuid.uuid4()), os.path.basename(ruta_dest))
                if not esta_confinado_en_raiz(conservada, pendrive_raiz):
                    conflictos.append({"clip": rel_clip, "error": "Ruta de reversión fuera del pendrive"})
                    continue
                os.makedirs(os.path.dirname(conservada), exist_ok=True)
                os.rename(ruta_dest, conservada)
                revertidos.append({"clip": rel_clip, "de": ruta_dest, "a": conservada, "original_conservado": ruta_orig})
                registrar_evento_manifiesto_edicion(pendrive_raiz, {
                    "id_evento": str(uuid.uuid4()), "fecha": datetime.datetime.now().isoformat(),
                    "tipo_evento": "deshacer_editado", "sesion_id": sesion["identificador"], "clip": rel_clip,
                    "ruta_conservada": os.path.relpath(conservada, pendrive_raiz).replace(os.sep, "/")})
                continue
            conflictos.append({
                "clip": rel_clip,
                "error": f"La ruta de retorno '{ruta_orig}' está ocupada. Reversión cancelada sin pisar."
            })
            continue

        os.makedirs(os.path.dirname(ruta_orig), exist_ok=True)
        os.rename(ruta_dest, ruta_orig)
        revertidos.append({"clip": rel_clip, "de": ruta_dest, "a": ruta_orig})

        registrar_evento_manifiesto_edicion(
            pendrive_raiz,
            {
                "id_evento": str(uuid.uuid4()),
                "fecha": datetime.datetime.now().isoformat(),
                "tipo_evento": "deshacer_editado",
                "sesion_id": sesion["identificador"],
                "clip": rel_clip,
            }
        )

    # Registrar en bitácora
    registro_bit = {
        "id_operacion": str(uuid.uuid4()),
        "tipo_operacion": "deshacer_finalizar_edicion",
        "fecha": datetime.datetime.now().isoformat(),
        "sesion_id": sesion["id"],
        "revertidos": revertidos,
    }
    registrar_bitacora_edicion(ruta_bitacora, registro_bit)

    if revertidos:
        db.actualizar_sesion_edicion(sesion_id, estado="completado" if sesion.get("video_completo_ruta") else "en_edicion", fecha_cierre=None)

    return {
        "exito": len(conflictos) == 0,
        "sesion_id": sesion_id,
        "revertidos": revertidos,
        "conflictos": conflictos,
    }


# =========================================================================
# Copia Segura a 'videos completos' (Excepción Única Controlada)
# =========================================================================

def copiar_export_a_videos_completos(
    ruta_origen: str,
    sesion: Dict[str, Any],
    pendrive_montaje: str,
    db: GestorBaseDatosBandeja,
    carpeta_raiz: str = "LucieSinReglas",
    ruta_bitacora: str = "bitacora_bandeja.jsonl",
) -> Dict[str, Any]:
    """
    Copia de forma segura el video final exportado por CapCut a:
    <pendrive>/<carpeta_raiz>/videos completos/<personaje>/<video - día - semana del mes - mes - año>/<nombre_final>
    Protocolo de seguridad:
    1. Comprueba espacio suficiente en pendrive.
    2. Comprueba que destino no exista (evita pisado ciego).
    3. Copia en bloques a archivo temporal .part calculando SHA-256 en vuelo.
    4. Aplica fsync y renombre atómico a destino final.
    5. Relee el archivo copiado para confirmar hash idéntico.
    6. Asienta evento 'completo' en manifiesto y bitácora.
    """
    if not os.path.isfile(ruta_origen):
        raise FileNotFoundError(f"El archivo exportado no existe: '{ruta_origen}'")
    if not verificar_archivo_exclusivo(ruta_origen):
        raise OSError("El export sigue en uso. Espera a que CapCut termine de escribirlo.")

    pendrive_raiz = os.path.join(pendrive_montaje, carpeta_raiz)
    personaje = sesion.get("personaje", "general")
    capitulo = sesion.get("capitulo", "sin_capitulo")
    nombre_final = sesion.get("nombre") or sesion.get("nombre_final_defecto")
    if not nombre_final.lower().endswith((".mp4", ".mov")):
        nombre_final = f"{nombre_final}.mp4"

    dir_completos = os.path.join(pendrive_raiz, "videos completos", personaje, capitulo)
    ruta_anterior = os.path.join(dir_completos, nombre_final)
    sesion_actual = db.obtener_sesion_por_id(sesion["id"]) or sesion
    ruta_registrada = sesion_actual.get("video_completo_ruta")
    if ruta_registrada and esta_confinado_en_raiz(ruta_registrada, pendrive_raiz) and os.path.exists(ruta_registrada):
        raise FileExistsError(f"La sesion ya tiene un video completo en '{ruta_registrada}'. No se sobreescribe.")
    if esta_confinado_en_raiz(ruta_anterior, pendrive_raiz) and os.path.exists(ruta_anterior):
        raise FileExistsError(f"El destino anterior '{ruta_anterior}' ya existe. No se sobreescribe.")
    dir_completos = os.path.join(pendrive_raiz, "videos completos", "videos sin publicar", personaje, nombre_carpeta_video(nombre_final))
    ruta_destino = os.path.join(dir_completos, nombre_final)

    if not esta_confinado_en_raiz(ruta_destino, pendrive_raiz):
        raise ValueError(f"Ruta de destino no confinada: '{ruta_destino}'")

    if os.path.exists(ruta_destino):
        raise FileExistsError(
            f"El destino '{ruta_destino}' ya existe. No se sobreescribe según Regla de Oro #1."
        )

    # 1. Comprobación de espacio
    tamano_origen = os.path.getsize(ruta_origen)
    uso = shutil.disk_usage(pendrive_montaje)
    espacio_necesario = int(tamano_origen * 1.05) + 10_000_000
    if uso.free < espacio_necesario:
        raise OSError(
            f"Espacio insuficiente en pendrive: disponible {uso.free} bytes, requerido {espacio_necesario} bytes."
        )

    os.makedirs(dir_completos, exist_ok=True)
    ruta_part = f"{ruta_destino}.part"

    # 2. Copia por bloques a .part con hash en vuelo
    hasher_origen = hashlib.sha256()
    try:
        with open(ruta_origen, "rb") as f_src, open(ruta_part, "xb") as f_dst:
            while True:
                bloque = f_src.read(65536)
                if not bloque:
                    break
                hasher_origen.update(bloque)
                f_dst.write(bloque)
            f_dst.flush()
            os.fsync(f_dst.fileno())
    except Exception as e:
        # En caso de error, dejamos el archivo o informamos sin borrar destructivamente
        raise IOError(f"Error al escribir archivo temporal .part: {e}")

    sha_esperado = hasher_origen.hexdigest()

    # 3. Renombrado atómico de .part a destino
    mover_sin_sobrescribir(ruta_part, ruta_destino)

    # 4. Verificación de hash por relectura íntegra
    hasher_verif = hashlib.sha256()
    with open(ruta_destino, "rb") as f_chk:
        while True:
            bloque = f_chk.read(65536)
            if not bloque:
                break
            hasher_verif.update(bloque)
    sha_obtenido = hasher_verif.hexdigest()

    if sha_obtenido != sha_esperado:
        raise ValueError(
            f"Fallo de integridad post-copia: esperado {sha_esperado}, obtenido {sha_obtenido}"
        )

    # 5. Registrar evento en manifiesto del pendrive
    registrar_evento_manifiesto_edicion(
        pendrive_raiz,
        {
            "id_evento": str(uuid.uuid4()),
            "fecha": datetime.datetime.now().isoformat(),
            "tipo_evento": "completo",
            "sesion_id": sesion["identificador"],
            "personaje": personaje,
            "capitulo": capitulo,
            "nombre": nombre_final,
            "ruta_destino": os.path.relpath(ruta_destino, pendrive_raiz).replace(os.sep, "/"),
            "sha256": sha_obtenido,
            "tamano": tamano_origen,
        }
    )

    # 6. Registrar en bitácora local
    id_operacion_copia = str(uuid.uuid4())
    registrar_bitacora_edicion(
        ruta_bitacora,
        {
            "id_operacion": id_operacion_copia,
            "tipo_operacion": "copiar_export_a_videos_completos",
            "fecha": datetime.datetime.now().isoformat(),
            "sesion_id": sesion["id"],
            "origen": ruta_origen,
            "destino": ruta_destino,
            "sha256": sha_obtenido,
            "tamano": tamano_origen,
        }
    )

    # 7. Actualizar BD
    db.actualizar_sesion_edicion(
        sesion["id"],
        export_asociado=ruta_origen,
        video_completo_ruta=ruta_destino,
        estado="completado",
    )

    return {
        "exito": True,
        "sesion_id": sesion["id"],
        "id_operacion": id_operacion_copia,
        "destino": ruta_destino,
        "sha256": sha_obtenido,
        "tamano": tamano_origen,
    }


def deshacer_copia_completo(
    video_completo_ruta: str,
    pendrive_montaje: str,
    db: GestorBaseDatosBandeja,
    carpeta_raiz: str = "LucieSinReglas",
    ruta_bitacora: str = "bitacora_bandeja.jsonl",
) -> Dict[str, Any]:
    """
    Deshace la copia a 'videos completos' trasladando el archivo a
    <pendrive>/<carpeta_raiz>/_revertidos/<nombre> mediante os.rename.
    NO BORRA NUNCA EL ARCHIVO (Regla de Oro #1).
    """
    pendrive_raiz = os.path.join(pendrive_montaje, carpeta_raiz)
    if not esta_confinado_en_raiz(video_completo_ruta, os.path.join(pendrive_raiz, "videos completos")):
        raise ValueError("El video debe estar dentro de videos completos del pendrive vinculado.")
    if not os.path.isfile(video_completo_ruta):
        raise FileNotFoundError(f"El archivo no existe: '{video_completo_ruta}'")

    pendrive_raiz = os.path.join(pendrive_montaje, carpeta_raiz)
    dir_revertidos = os.path.join(pendrive_raiz, "_revertidos")
    os.makedirs(dir_revertidos, exist_ok=True)

    nombre_base = os.path.basename(video_completo_ruta)
    nombre_revertido = nombre_base
    dest_revertido = os.path.join(dir_revertidos, nombre_revertido)

    # Si ya existe en _revertidos, sufijar con timestamp para no pisar
    if os.path.exists(dest_revertido):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        raiz_n, ext_n = os.path.splitext(nombre_base)
        dest_revertido = os.path.join(dir_revertidos, f"{raiz_n}_{ts}{ext_n}")

    os.rename(video_completo_ruta, dest_revertido)

    # Registrar en manifiesto
    registrar_evento_manifiesto_edicion(
        pendrive_raiz,
        {
            "id_evento": str(uuid.uuid4()),
            "fecha": datetime.datetime.now().isoformat(),
            "tipo_evento": "deshacer_completo",
            "ruta_revertida": dest_revertido,
        }
    )

    # Registrar en bitácora
    registrar_bitacora_edicion(
        ruta_bitacora,
        {
            "id_operacion": str(uuid.uuid4()),
            "tipo_operacion": "deshacer_copia_completo",
            "fecha": datetime.datetime.now().isoformat(),
            "desde": video_completo_ruta,
            "hacia": dest_revertido,
        }
    )

    for sesion in db.obtener_sesiones_edicion():
        if sesion.get("video_completo_ruta") != video_completo_ruta:
            continue
        db.actualizar_sesion_edicion(sesion["id"], video_completo_ruta=None,
                                    estado="editado" if sesion.get("fecha_cierre") else "en_edicion")
        for export in db.obtener_exports_pendientes():
            if export.get("sesion_id") == sesion["id"] and export["estado"] == "copiado":
                db.actualizar_export_pendiente(export["id"], estado="sin_asignar", fecha_copia=None, error=None,
                                              ruta_destino=None, envio_automatico_bloqueado=1)
    for export in db.obtener_exports_pendientes():
        if export.get("ruta_destino") == video_completo_ruta:
            db.actualizar_export_pendiente(export["id"], estado="sin_asignar", fecha_copia=None, error=None,
                                          ruta_destino=None, envio_automatico_bloqueado=1)
    return {"exito": True, "ruta_revertida": dest_revertido}


# =========================================================================
# Lógica de Vinculación Determinista y Cola Offline
# =========================================================================

def obtener_sesiones_para_export(db: GestorBaseDatosBandeja) -> List[Dict[str, Any]]:
    """Una sesion terminada sigue esperando su export hasta que se asocie uno."""
    return [s for s in db.obtener_sesiones_edicion()
            if s["estado"] in ("en_edicion", "editado") and not s.get("export_asociado")]


def elegir_sesion_export_automatico(sesiones):
    """Prioriza una única edición en curso sobre ediciones antiguas pendientes."""
    en_edicion = [s for s in sesiones if s["estado"] == "en_edicion"]
    if len(en_edicion) == 1:
        return en_edicion[0]
    if not en_edicion and len(sesiones) == 1:
        return sesiones[0]
    return None


def obtener_videos_completados(db: GestorBaseDatosBandeja) -> List[Dict[str, Any]]:
    sesiones = {s["id"]: s for s in db.obtener_sesiones_edicion()}
    resultado = []
    for export in db.obtener_exports_pendientes():
        if export["estado"] == "descartado":
            continue
        sesion = sesiones.get(export.get("sesion_id")) or {}
        reemplazado = False
        try:
            st = os.stat(export["ruta_origen"])
            reemplazado = st.st_size != export["tamano"] or st.st_mtime != export["mtime"]
        except OSError:
            pass
        resultado.append({**export, "nombre_video": sesion.get("nombre") or export["nombre"],
                          "archivo_reemplazado": reemplazado,
                          "ruta_destino": sesion.get("video_completo_ruta") or export.get("ruta_destino"),
                          "capitulo": sesion.get("capitulo"),
                          "personaje": sesion.get("personaje")})
    return resultado


def vincular_nuevo_export(
    export_info: Dict[str, Any],
    pendrive_montaje: Optional[str],
    db: GestorBaseDatosBandeja,
    carpeta_raiz: str = "LucieSinReglas",
    ruta_bitacora: str = "bitacora_bandeja.jsonl",
    copiar_automaticamente: bool = True,
) -> Dict[str, Any]:
    """
    Aplica la regla de vinculación determinista:
    - Si hay una única sesión en_edicion, tiene prioridad sobre las editadas.
      Si no hay ninguna en_edicion, exige una única sesión editada esperando export.
      Asocia automáticamente el export a dicha sesión.
      En modo automático, si el pendrive está accesible, ejecuta la copia.
      Si el pendrive está desconectado, queda encolado como 'pendiente_copia'.
      En modo manual, espera el envío explícito desde el dashboard.
    - Si hay 0 o >1 sesiones esperando export:
      Registra el export como 'sin_asignar' para decisión manual del usuario.
    """
    ruta_origen = export_info["ruta_absoluta"]
    nombre = export_info["nombre"]
    tamano = export_info["tamano"]
    mtime = export_info["mtime"]

    existente = next((e for e in db.obtener_exports_pendientes() if e["ruta_origen"] == ruta_origen and e["tamano"] == tamano and e["mtime"] == mtime), None)
    if existente and existente.get("envio_automatico_bloqueado"):
        return {"vinculado": False, "modo": "revertido", "export_id": existente["id"]}
    if existente and (existente.get("sesion_id") or existente["estado"] != "sin_asignar"):
        return {"vinculado": bool(existente.get("sesion_id")), "modo": "ya_registrado", "export_id": existente["id"]}
    sesiones_activas = obtener_sesiones_para_export(db)

    sesion = elegir_sesion_export_automatico(sesiones_activas)
    if sesion:
        sesion_id = sesion["id"]
        db.actualizar_sesion_edicion(sesion_id, export_asociado=ruta_origen)
        if existente:
            db.actualizar_export_pendiente(existente["id"], sesion_id=sesion_id,
                                          estado="pendiente_copia" if copiar_automaticamente else "sin_asignar")

        if not copiar_automaticamente:
            export_id = db.registrar_export_pendiente(ruta_origen, nombre, tamano, mtime,
                                                     sesion_id=sesion_id, estado="sin_asignar")
            return {"vinculado": True, "modo": "esperando_envio", "sesion_id": sesion_id, "export_id": export_id}

        if pendrive_montaje and os.path.isdir(pendrive_montaje):
            # Pendrive conectado: copia automática inmediata
            export_id = db.registrar_export_pendiente(
                ruta_origen=ruta_origen,
                nombre=nombre,
                tamano=tamano,
                mtime=mtime,
                sesion_id=sesion_id,
                estado="pendiente_copia",
            )
            try:
                res_copia = copiar_export_a_videos_completos(
                    ruta_origen=ruta_origen,
                    sesion=sesion,
                    pendrive_montaje=pendrive_montaje,
                    db=db,
                    carpeta_raiz=carpeta_raiz,
                    ruta_bitacora=ruta_bitacora,
                )
                db.actualizar_export_pendiente(
                    export_id,
                    estado="copiado",
                    fecha_copia=datetime.datetime.now().isoformat(),
                    sha256=res_copia.get("sha256"),
                    error=None,
                )
                return {
                    "vinculado": True,
                    "modo": "copia_automatica",
                    "sesion_id": sesion_id,
                    "resultado_copia": res_copia,
                }
            except Exception as e:
                logger.error(f"Error al copiar export automáticamente: {e}")
                db.actualizar_export_pendiente(export_id, error=str(e))
                return {
                    "vinculado": True,
                    "modo": "error_copia",
                    "sesion_id": sesion_id,
                    "error": str(e),
                }
        else:
            # Pendrive no disponible: encolar
            export_id = db.registrar_export_pendiente(
                ruta_origen=ruta_origen,
                nombre=nombre,
                tamano=tamano,
                mtime=mtime,
                sesion_id=sesion_id,
                estado="pendiente_copia",
            )
            return {
                "vinculado": True,
                "modo": "encolado_offline",
                "sesion_id": sesion_id,
                "export_id": export_id,
            }

    # 0 o >1 sesiones: dejar sin asignar
    export_id = db.registrar_export_pendiente(
        ruta_origen=ruta_origen,
        nombre=nombre,
        tamano=tamano,
        mtime=mtime,
        sesion_id=None,
        estado="sin_asignar",
    )
    return {
        "vinculado": False,
        "modo": "sin_asignar",
        "export_id": export_id,
        "cantidad_sesiones_activas": len(sesiones_activas),
    }


def verificar_version_export(export):
    """No asociar ni servir un archivo nuevo mediante un registro histórico."""
    st = os.stat(export["ruta_origen"])
    if st.st_size != export["tamano"] or st.st_mtime != export["mtime"]:
        raise ValueError("CapCut reemplazó este export. Elegí la nueva versión en Videos completados.")


def copiar_export_sin_sesion_a_sin_publicar(exp, pendrive_montaje, db, carpeta_raiz, ruta_bitacora):
    """Resguarda exports sin sesión en la cola, sin inventar una asociación."""
    with operacion_pendrive_exclusiva():
        return _resguardar_export_sin_sesion(exp, pendrive_montaje, db, carpeta_raiz, ruta_bitacora)


def _resguardar_export_sin_sesion(exp, pendrive_montaje, db, carpeta_raiz, ruta_bitacora):
    verificar_version_export(exp)
    if exp["tamano"] <= 0:
        raise ValueError("El export está vacío; todavía no se resguarda.")
    if not verificar_archivo_exclusivo(exp["ruta_origen"]):
        raise OSError("El export sigue en escritura o está ocupado. Se reintentará.")
    raiz = os.path.join(pendrive_montaje, carpeta_raiz)
    carpeta = os.path.join(raiz, "videos completos", "videos sin publicar")
    if not esta_confinado_en_raiz(carpeta, raiz):
        raise ValueError("Carpeta sin publicar fuera del pendrive.")
    actual = os.path.abspath(carpeta)
    while True:
        if os.path.islink(actual) or (hasattr(os.path, "isjunction") and os.path.isjunction(actual)):
            raise ValueError("No se permiten enlaces en la cola de publicación.")
        padre = os.path.dirname(actual)
        if padre == actual:
            break
        actual = padre
    os.makedirs(carpeta, exist_ok=True)
    sha = calcular_sha256(exp["ruta_origen"])
    nombre = os.path.basename(exp["ruta_origen"])
    destino = os.path.join(carpeta, nombre)
    if os.path.exists(destino) and calcular_sha256(destino) != sha:
        base, extension = os.path.splitext(nombre)
        destino = os.path.join(carpeta, base[:120] + "_version_" + sha[:12] + extension)
    if os.path.exists(destino):
        if calcular_sha256(destino) != sha:
            raise FileExistsError("Hay otro video en el destino. No se sobrescribe.")
    else:
        _copiar_crudo_bloqueado(exp["ruta_origen"], destino, sha, raiz)
    registrar_evento_manifiesto_edicion(raiz, {"id_evento": str(uuid.uuid4()),
        "tipo_evento": "export_sin_sesion_resguardado", "fecha": datetime.datetime.now().isoformat(),
        "export_id": exp["id"], "ruta_destino": os.path.relpath(destino, raiz).replace(os.sep, "/"), "sha256": sha})
    registrar_bitacora_edicion(ruta_bitacora, {"id_operacion": str(uuid.uuid4()),
        "tipo_operacion": "export_sin_sesion_resguardado", "export_id": exp["id"],
        "origen": exp["ruta_origen"], "destino": destino, "sha256": sha})
    db.actualizar_export_pendiente(exp["id"], estado="copiado", ruta_destino=destino, sha256=sha,
                                  fecha_copia=datetime.datetime.now().isoformat(), error=None, envio_automatico_bloqueado=0)
    return destino


def retomar_export_actual_sin_asignar(db, pendrive_montaje, carpeta_raiz, ruta_bitacora):
    """Retoma solo un export inequívoco generado durante la única edición activa.

    Evita asociar exports históricos sin asignar a una nueva sesión al reiniciar.
    Si hay varios candidatos recientes, mantiene la elección manual.
    """
    activas = [s for s in obtener_sesiones_para_export(db) if s["estado"] == "en_edicion"]
    if len(activas) != 1:
        return None
    inicio = datetime.datetime.fromisoformat(activas[0]["fecha_creacion"]).timestamp()
    candidatos = []
    for exp in db.obtener_exports_pendientes(estado="sin_asignar"):
        if exp.get("sesion_id") or exp.get("envio_automatico_bloqueado") or exp["mtime"] < inicio:
            continue
        try:
            verificar_version_export(exp)
        except (OSError, ValueError):
            continue
        candidatos.append(exp)
    if len(candidatos) != 1:
        return None
    exp = candidatos[0]
    return vincular_nuevo_export({"ruta_absoluta": exp["ruta_origen"], "nombre": exp["nombre"],
                                 "tamano": exp["tamano"], "mtime": exp["mtime"]},
                                pendrive_montaje, db, carpeta_raiz, ruta_bitacora)


def procesar_exports_pendientes_copia(
    pendrive_montaje: str,
    db: GestorBaseDatosBandeja,
    carpeta_raiz: str = "LucieSinReglas",
    ruta_bitacora: str = "bitacora_bandeja.jsonl",
) -> List[Dict[str, Any]]:
    """
    Procesa los exports encolados como 'pendiente_copia' cuando se conecta o vincula el pendrive.
    """
    pendientes = db.obtener_exports_pendientes(estado="pendiente_copia")
    resultados = []

    for exp in pendientes:
        sesion_id = exp.get("sesion_id")
        if not sesion_id:
            continue
        sesion = db.obtener_sesion_por_id(sesion_id)
        if not sesion:
            continue

        try:
            verificar_version_export(exp)
            res_copia = copiar_export_a_videos_completos(
                ruta_origen=exp["ruta_origen"],
                sesion=sesion,
                pendrive_montaje=pendrive_montaje,
                db=db,
                carpeta_raiz=carpeta_raiz,
                ruta_bitacora=ruta_bitacora,
            )
            db.actualizar_export_pendiente(
                exp["id"],
                estado="copiado",
                fecha_copia=datetime.datetime.now().isoformat(),
                sha256=res_copia.get("sha256"),
                error=None,
            )
            resultados.append({"export_id": exp["id"], "exito": True, "detalle": res_copia})
        except Exception as e:
            logger.error(f"Error procesando export encolado {exp['id']}: {e}")
            db.actualizar_export_pendiente(exp["id"], error=str(e))
            resultados.append({"export_id": exp["id"], "exito": False, "error": str(e)})

    return resultados
