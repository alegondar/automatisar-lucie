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
import shutil
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.pendrive import NOMBRE_MANIFIESTO_PENDRIVE
from bandeja.plataforma import esta_confinado_en_raiz

logger = logging.getLogger("bandeja_edicion")


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
    os.makedirs(dir_lucie, exist_ok=True)
    ruta_manifiesto = os.path.join(dir_lucie, NOMBRE_MANIFIESTO_PENDRIVE)
    with open(ruta_manifiesto, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


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

    sesiones_activas = db.obtener_sesiones_edicion(estado="en_edicion")
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
    if os.path.exists(dir_sin_editar):
        for raiz, _dirs, archivos in os.walk(dir_sin_editar):
            for arch in archivos:
                if arch.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
                    ruta_abs = os.path.join(raiz, arch)
                    rel = os.path.relpath(ruta_abs, dir_sin_editar)
                    partes = rel.split(os.sep)
                    personaje = partes[0] if len(partes) > 1 else "general"
                    capitulo = partes[1] if len(partes) > 2 else "sin_capitulo"
                    _asegurar_conteo(capitulo)

                    identificador_clip = rel.replace(os.sep, "/")
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
                        }
                        if id_media:
                            clip_dict["id_media"] = id_media
                        para_editar.append(clip_dict)

    # 2. Explorar 'videos ya editados'
    if os.path.exists(dir_ya_editados):
        for raiz, _dirs, archivos in os.walk(dir_ya_editados):
            for arch in archivos:
                if arch.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
                    ruta_abs = os.path.join(raiz, arch)
                    rel = os.path.relpath(ruta_abs, dir_ya_editados)
                    partes = rel.split(os.sep)
                    capitulo = partes[1] if len(partes) > 2 else "sin_capitulo"
                    _asegurar_conteo(capitulo)
                    conteos_capitulo[capitulo]["ya_editados"] += 1

    # 3. Explorar 'videos completos'
    if os.path.exists(dir_completos):
        for raiz, _dirs, archivos in os.walk(dir_completos):
            for arch in archivos:
                if arch.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
                    ruta_abs = os.path.join(raiz, arch)
                    rel = os.path.relpath(ruta_abs, dir_completos)
                    partes = rel.split(os.sep)
                    capitulo = partes[1] if len(partes) > 2 else "sin_capitulo"
                    _asegurar_conteo(capitulo)
                    conteos_capitulo[capitulo]["completos"] += 1

    # 4. Exports sin asignar de CapCut
    exports_sin_asignar = db.obtener_exports_pendientes(estado="sin_asignar")

    return {
        "para_editar": para_editar,
        "en_edicion": sesiones_activas,
        "conteos_capitulo": conteos_capitulo,
        "exports_sin_asignar": exports_sin_asignar,
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
    movidos = []
    conflictos = []
    omisiones = []

    for rel_clip in clips:
        # Asegurar ruta confinada
        ruta_orig = os.path.join(dir_sin_editar, rel_clip.replace("/", os.sep))
        ruta_dest = os.path.join(dir_ya_editados, rel_clip.replace("/", os.sep))

        if not esta_confinado_en_raiz(ruta_orig, pendrive_raiz) or not esta_confinado_en_raiz(ruta_dest, pendrive_raiz):
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
        os.rename(ruta_orig, ruta_dest)

        movidos.append({
            "clip": rel_clip,
            "origen": ruta_orig,
            "destino": ruta_dest,
            "sha256": sha_orig,
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
                "sha256": sha_orig,
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
            estado="editado",
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
    revertidos = []
    conflictos = []

    for rel_clip in clips:
        ruta_orig = os.path.join(dir_sin_editar, rel_clip.replace("/", os.sep))
        ruta_dest = os.path.join(dir_ya_editados, rel_clip.replace("/", os.sep))

        if not os.path.isfile(ruta_dest):
            continue

        if os.path.exists(ruta_orig):
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
        db.actualizar_sesion_edicion(sesion_id, estado="en_edicion")

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
    <pendrive>/<carpeta_raiz>/videos completos/<personaje>/<capítulo>/<nombre_final>
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

    pendrive_raiz = os.path.join(pendrive_montaje, carpeta_raiz)
    personaje = sesion.get("personaje", "general")
    capitulo = sesion.get("capitulo", "sin_capitulo")
    nombre_final = sesion.get("nombre") or sesion.get("nombre_final_defecto")
    if not nombre_final.lower().endswith((".mp4", ".mov")):
        nombre_final = f"{nombre_final}.mp4"

    dir_completos = os.path.join(pendrive_raiz, "videos completos", personaje, capitulo)
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
    os.rename(ruta_part, ruta_destino)

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

    return {
        "exito": True,
        "ruta_revertida": dest_revertido,
    }


# =========================================================================
# Lógica de Vinculación Determinista y Cola Offline
# =========================================================================

def vincular_nuevo_export(
    export_info: Dict[str, Any],
    pendrive_montaje: Optional[str],
    db: GestorBaseDatosBandeja,
    carpeta_raiz: str = "LucieSinReglas",
    ruta_bitacora: str = "bitacora_bandeja.jsonl",
) -> Dict[str, Any]:
    """
    Aplica la regla de vinculación determinista:
    - Si existe exactamente 1 sesión en estado 'en_edicion':
      Asocia automáticamente el export a dicha sesión.
      Si el pendrive está vinculado y accesible, ejecuta la copia automática.
      Si el pendrive está desconectado, queda encolado como 'pendiente_copia'.
    - Si hay 0 o >1 sesiones en 'en_edicion':
      Registra el export como 'sin_asignar' para decisión manual del usuario.
    """
    ruta_origen = export_info["ruta_absoluta"]
    nombre = export_info["nombre"]
    tamano = export_info["tamano"]
    mtime = export_info["mtime"]

    sesiones_activas = db.obtener_sesiones_edicion(estado="en_edicion")

    if len(sesiones_activas) == 1:
        sesion = sesiones_activas[0]
        sesion_id = sesion["id"]

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
            )
            resultados.append({"export_id": exp["id"], "exito": True, "detalle": res_copia})
        except Exception as e:
            logger.error(f"Error procesando export encolado {exp['id']}: {e}")
            db.actualizar_export_pendiente(exp["id"], error=str(e))
            resultados.append({"export_id": exp["id"], "exito": False, "error": str(e)})

    return resultados
