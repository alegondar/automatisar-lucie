#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/capitulos.py

Gestión y ciclo de vida de capítulos:
- Cálculo de balance de archivos (pendientes vs movidos en BD y disco).
- Detección de capítulos olvidados según umbral horario.
- Descarte seguro de capítulos hacia _descartados/ con verificación de integridad por hash.
- Reversión atómica de descartes mediante os.rename sin sobrescritura.
"""

import datetime
import json
import logging
import os
import secrets
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from bandeja.config import (
    ErrorSeguridadBandeja,
    ErrorValidacionEscena,
    ErrorDeshacer,
    ErrorMovimiento,
    calcular_sha256,
    formatear_bytes,
)
from bandeja.clasificacion import ValidadorEscenas
from bandeja.plataforma import esta_confinado_en_raiz, validar_longitud_ruta

logger = logging.getLogger("bandeja_descargas")


def validar_confinamiento_destino_base(ruta: str, ruta_destino_base: str):
    """Asegura que la ruta canónica permanezca estrictamente dentro de ruta_destino_base y rechaza symlinks."""
    if not validar_longitud_ruta(ruta):
        raise ErrorSeguridadBandeja(
            f"Violación de seguridad: la ruta '{ruta}' excede los 260 caracteres permitidos (MAX_PATH)."
        )
    if not esta_confinado_en_raiz(ruta, ruta_destino_base):
        base_confinada = os.path.realpath(ruta_destino_base)
        raise ErrorSeguridadBandeja(
            f"Violación de seguridad: la ruta '{ruta}' escapa del confinamiento de '{base_confinada}'."
        )
    if os.path.islink(ruta):
        raise ErrorSeguridadBandeja(f"Violación de seguridad: '{ruta}' es un enlace simbólico no permitido.")


def calcular_balance_capitulo(
    db: Any,
    personaje: str,
    nombre: str,
    verificar_disco: bool = False,
    ruta_destino_base: Optional[str] = None
) -> Dict[str, int]:
    """
    Calcula la cantidad de archivos pendientes y ya movidos para un personaje y capítulo.
    """
    with db._lock, db._conectar() as con:
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

        mov_disco = 0
        dest_base = ruta_destino_base or getattr(db, "ruta_destino_base", None)
        if verificar_disco and dest_base:
            carpeta_cap = os.path.join(dest_base, personaje, nombre)
            if os.path.exists(carpeta_cap) and os.path.isdir(carpeta_cap):
                for _, _, files in os.walk(carpeta_cap):
                    mov_disco += len(files)

        return {
            "pendientes": pendientes,
            "movidos": max(mov_cap, mov_arch, mov_disco)
        }


def es_capitulo_olvidado(
    db: Any,
    horas_limite: float = 12.0,
    ahora: Optional[datetime.datetime] = None
) -> bool:
    """
    Determina si el capítulo activo excede las horas límite configuradas.
    """
    cap = db.obtener_capitulo_activo()
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


def simular_descartar_capitulo(
    db: Any,
    ruta_destino_base: str,
    ruta_descargas: str,
    capitulo_id: int
) -> Dict[str, Any]:
    """
    Simula el descarte de un capítulo moviéndolo hacia ~/Descargas/_lucie/_descartados/<personaje>/<escena>_<timestamp>/.
    Retorna origen, destino, conteo de archivos, peso total y aviso anti-borrado.
    """
    cap = db.obtener_capitulo_por_id(capitulo_id)
    if not cap:
        raise ValueError(f"Capítulo con ID {capitulo_id} no encontrado.")

    personaje = cap.get("personaje", "lucie").strip().lower()
    nombre = cap.get("nombre", "").strip()

    valido, motivo = ValidadorEscenas.validar_nombre_escena(
        nombre, ruta_destino_base, ruta_descargas,
        es_existente_descargas=False, personaje=personaje
    )
    if not valido:
        raise ErrorValidacionEscena(f"Nombre de capítulo inválido para descarte: {motivo}")

    origen_carpeta = os.path.join(ruta_destino_base, personaje, nombre)
    validar_confinamiento_destino_base(origen_carpeta, ruta_destino_base)

    # Destino dentro de _descartados
    fecha_tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    nombre_dest = f"{nombre}_{fecha_tag}"
    destino_base = os.path.join(ruta_destino_base, "_descartados", personaje, nombre_dest)
    validar_confinamiento_destino_base(destino_base, ruta_destino_base)

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
        base_real = os.path.realpath(ruta_destino_base)
        for root, dirs, files in os.walk(origen_carpeta):
            for d in dirs:
                d_path = os.path.join(root, d)
                if os.path.islink(d_path):
                    real_d = os.path.realpath(d_path)
                    if not esta_confinado_en_raiz(real_d, base_real):
                        raise ErrorSeguridadBandeja(f"Symlink saliente detectado en directorio: '{d_path}' -> '{real_d}'.")
            for f in files:
                f_path = os.path.join(root, f)
                if os.path.islink(f_path):
                    real_f = os.path.realpath(f_path)
                    if not esta_confinado_en_raiz(real_f, base_real):
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


def ejecutar_descartar_capitulo(
    db: Any,
    ruta_destino_base: str,
    ruta_descargas: str,
    ruta_bitacora: str,
    simulacion: Dict[str, Any],
    nombre_confirmacion: str,
    lock: Optional[Any] = None
) -> Dict[str, Any]:
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

    def _ejecutar_con_lock():
        validar_confinamiento_destino_base(origen_carpeta, ruta_destino_base)
        validar_confinamiento_destino_base(destino_carpeta, ruta_destino_base)

        movio_carpeta = False
        hashes_antes = {}
        if carpeta_existe:
            if not os.path.exists(origen_carpeta):
                raise ErrorMovimiento(f"La carpeta origen '{origen_carpeta}' ya no existe.")
            if os.path.exists(destino_carpeta):
                raise ErrorMovimiento(f"El destino '{destino_carpeta}' ya existe.")

            for root, _, files in os.walk(origen_carpeta):
                for f in files:
                    p_orig = os.path.join(root, f)
                    rel = os.path.relpath(p_orig, origen_carpeta)
                    hashes_antes[rel] = calcular_sha256(p_orig)

            os.makedirs(os.path.dirname(destino_carpeta), exist_ok=True)
            os.rename(origen_carpeta, destino_carpeta)
            movio_carpeta = True

            for rel, h_esperado in hashes_antes.items():
                p_dest = os.path.join(destino_carpeta, rel)
                h_post = calcular_sha256(p_dest)
                if h_post != h_esperado:
                    raise ErrorMovimiento(
                        f"Fallo de integridad post-descarte: el hash de '{rel}' no coincide en '{p_dest}'."
                    )

            db.actualizar_rutas_archivos_descarte(origen_carpeta, destino_carpeta, es_reversion=False)

        era_activo = False
        cap_activo = db.obtener_capitulo_activo()
        if cap_activo and cap_activo.get("habilitado") and cap_activo.get("id") == capitulo_id:
            era_activo = True

        db.marcar_capitulo_descartado(capitulo_id, descartado=True)

        if era_activo:
            db.guardar_capitulo_activo("", "", False)

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
            "hashes_verificados": len(hashes_antes),
            "fecha": fecha_iso
        }
        with open(ruta_bitacora, "a", encoding="utf-8", newline="\n") as f:
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

    if lock is not None:
        with lock:
            return _ejecutar_con_lock()
    return _ejecutar_con_lock()


def revertir_descarte_capitulo(
    db: Any,
    ruta_bitacora: str,
    operacion_encontrada: Dict[str, Any],
    id_operacion: str,
    lock: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Revierte una operación de descarte de capítulo restaurando la carpeta mediante os.rename.
    """
    def _revertir_con_lock():
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
            db.actualizar_rutas_archivos_descarte(destino_carpeta, origen_carpeta, es_reversion=True)

        if cap_id:
            db.marcar_capitulo_descartado(cap_id, descartado=False)

        evento_reversion = {
            "evento": "deshacer",
            "id_operacion_revertida": id_operacion,
            "fecha": datetime.datetime.now().isoformat(),
            "total_revertidos": total_archivos
        }
        with open(ruta_bitacora, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(evento_reversion, ensure_ascii=False) + "\n")

        return {
            "exito": True,
            "id_operacion": id_operacion,
            "total_revertidos": total_archivos,
            "mensaje": f"Capítulo '{operacion_encontrada.get('escena')}' restaurado exitosamente a su ubicación original."
        }

    if lock is not None:
        with lock:
            return _revertir_con_lock()
    return _revertir_con_lock()
