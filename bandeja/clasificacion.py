#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/clasificacion.py

Filtro de lista blanca, resolución de alias de personajes, validación
de nombres de escenas y aseguramiento de carpetas de capítulos.
"""

import fnmatch
import json
import logging
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

from bandeja.config import (
    CARACTERES_INVALIDOS_ESCENA,
    ConfiguracionBandeja,
    EXTENSIONES_IMAGENES_DEFECTO,
    EXTENSIONES_MEDIA_DEFECTO,
    NOMBRES_RESERVADOS_WINDOWS,
)
from bandeja.plataforma import esta_confinado_en_raiz, validar_longitud_ruta

logger = logging.getLogger("bandeja.clasificacion")


def clasificar_familia_medio(extension: str) -> str:
    """Retorna 'fotos' para imágenes o 'videos' para videos."""
    ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    if ext in EXTENSIONES_IMAGENES_DEFECTO:
        return "fotos"
    if ext == ".mp3":
        return "audios"
    return "videos"


def nombre_carpeta_documentado(nombre, fecha=None):
    """Fecha local; semanas del mes: 1-7, 8-14, 15-21, 22-28, 29-31."""
    import datetime
    fecha = fecha or datetime.datetime.now()
    dias = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    nombre = str(nombre).strip()
    # Una carpeta ya documentada mantiene su identidad al reabrirla.
    if re.search(r" - (lunes|martes|miércoles|jueves|viernes|sábado|domingo) - semana [1-5] - [a-z]+ - [0-9]{4}$", nombre):
        return nombre
    semana = (fecha.day - 1) // 7 + 1
    return f"{nombre} - {dias[fecha.weekday()]} - semana {semana} - {meses[fecha.month - 1]} - {fecha.year}"


class FiltroListaBlanca:
    """Aplica la lista blanca estricta para determinar candidatos, escenas y no reconocidos."""

    def __init__(self, config: ConfiguracionBandeja, ruta_alias: str = "alias-personajes.json"):
        self.config = config
        self.alias_personajes = self._cargar_alias(ruta_alias)
        # Precompilar regex de Nano Banana
        regex_nb = self.config.patrones_candidatos.get("nano_banana_regex", r"^.+_\d{14}\.(jpg|jpeg|png|webp)$")
        self._regex_nano_banana = re.compile(regex_nb, re.IGNORECASE)

    def _cargar_alias(self, ruta_alias: str) -> List[str]:
        alias_set = {"lucie", "luci", "roli", "laroli", "magui", "mailen", "luna"}
        if os.path.exists(ruta_alias):
            try:
                with open(ruta_alias, "r", encoding="utf-8", newline="\n") as f:
                    datos = json.load(f)
                for r in datos.get("reglas", []):
                    for pat in r.get("patrones", []):
                        limpio = unicodedata.normalize("NFC", pat.replace("*", "").strip().lower())
                        if limpio:
                            alias_set.add(limpio)
            except Exception:
                pass
        return sorted(list(alias_set), key=len, reverse=True)

    def es_carpeta_escena_existente(self, nombre_carpeta: str) -> bool:
        """Verifica si una carpeta de Descargas comienza con un alias de personaje."""
        nombre_lower = unicodedata.normalize("NFC", nombre_carpeta).strip().lower()
        if (nombre_lower.startswith("_") or 
            "_descartados" in nombre_lower or 
            "_enviados" in nombre_lower or 
            "_revertidos" in nombre_lower or 
            nombre_lower in ("fotos", "videos", "_enviados", "_revertidos")):
            return False
        for al in self.alias_personajes:
            if nombre_lower == al or nombre_lower.startswith(al + " ") or nombre_lower.startswith(al + "_") or nombre_lower.startswith(al + "-"):
                return True
        return False

    def obtener_personaje_de_carpeta_escena(self, nombre_carpeta: str) -> str:
        """Deduce el personaje principal a partir del nombre de la carpeta con alias."""
        nombre_lower = unicodedata.normalize("NFC", nombre_carpeta).strip().lower()
        if nombre_lower.startswith("luna"):
            return "luna"
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
        nombre_lower = unicodedata.normalize("NFC", os.path.basename(nombre_archivo)).lower()
        for al in self.alias_personajes:
            if nombre_lower.startswith(al):
                if al in ("roli", "laroli", "magui"):
                    return "roli"
                if al in ("lucie", "luci"):
                    return "lucie"
                if al == "luna":
                    return "luna"
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
        - Normaliza a NFC.
        """
        nombre_base, _ = os.path.splitext(os.path.basename(nombre_archivo))
        nombre_base = unicodedata.normalize("NFC", nombre_base)
        sug = re.sub(r"\s*\(\d+\)$", "", nombre_base)
        sug = re.sub(r"[\s_\-]*\d+$", "", sug).strip()
        sug = sug.rstrip(" _-").strip()
        return unicodedata.normalize("NFC", sug if sug else nombre_base)

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

        # Normalización a NFC
        nombre = unicodedata.normalize("NFC", nombre)

        # Caracteres prohibidos y de control
        if ".." in nombre or "/" in nombre or "\\" in nombre:
            return False, "El nombre de la escena no puede contener separadores de ruta ('/', '\\') ni '..'."

        nombre_lower = nombre.strip().lower()
        if (nombre_lower in ("_descartados", "_lucie", "_a_revisar", "_enviados", "_revertidos", "fotos", "videos") or 
            "_descartados" in nombre_lower or
            "_enviados" in nombre_lower or
            "_revertidos" in nombre_lower):
            return False, f"El nombre de la escena '{nombre}' es una palabra reservada del sistema o contiene nombres reservados (_descartados, _enviados, _revertidos)."

        if nombre.endswith(".") or nombre.endswith(" "):
            return False, "El nombre de la escena no puede finalizar con un punto o espacio."

        if len(nombre) > 100:
            return False, f"El nombre de la escena excede los 100 caracteres permitidos ({len(nombre)})."

        if any(ord(c) < 32 or ord(c) == 127 or unicodedata.category(c) == "Cc" for c in nombre):
            return False, "El nombre de la escena no puede contener caracteres de control."

        infracciones_caracteres = [c for c in nombre if c in CARACTERES_INVALIDOS_ESCENA]
        if infracciones_caracteres:
            return False, f"El nombre contiene caracteres inválidos en sistemas de archivos: {' '.join(set(infracciones_caracteres))}"

        # Nombres reservados en Windows/exFAT
        base_sin_ext = nombre.split(".")[0].upper().strip()
        if base_sin_ext in NOMBRES_RESERVADOS_WINDOWS or nombre.upper().strip() in NOMBRES_RESERVADOS_WINDOWS:
            return False, f"'{nombre}' es un nombre de dispositivo reservado en sistemas Windows/exFAT."

        # Validación de confinamiento y longitud de ruta mediante utilitarios de plataforma
        try:
            if es_existente_descargas:
                ruta_final = os.path.join(ruta_descargas, nombre)
                if not validar_longitud_ruta(ruta_final):
                    return False, f"La ruta de la escena excede los 260 caracteres permitidos (MAX_PATH): '{ruta_final}'."
                if not esta_confinado_en_raiz(ruta_final, ruta_descargas):
                    return False, "La ruta de la escena escapa de los límites permitidos del directorio de destino."
            else:
                ruta_final = os.path.join(ruta_destino_base, personaje, nombre)
                if not validar_longitud_ruta(ruta_final):
                    return False, f"La ruta de la escena excede los 260 caracteres permitidos (MAX_PATH): '{ruta_final}'."
                if not esta_confinado_en_raiz(ruta_final, ruta_destino_base):
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
    nombre_limpio = unicodedata.normalize("NFC", (nombre or "").strip())
    personaje_limpio = unicodedata.normalize("NFC", (personaje or "").strip().lower())
    if personaje_limpio not in ("lucie", "roli", "mailen", "luna"):
        raise ValueError(f"Personaje inválido: '{personaje}'. Debe ser 'lucie', 'roli', 'mailen' o 'luna'.")

    if not nombre_limpio:
        raise ValueError("El nombre del capítulo no puede estar vacío.")

    valido, motivo = ValidadorEscenas.validar_nombre_escena(
        nombre_limpio, ruta_destino_base, ruta_descargas,
        es_existente_descargas=False, personaje=personaje_limpio
    )
    if not valido:
        raise ValueError(f"Nombre de capítulo inválido: {motivo}")

    carpeta = os.path.join(ruta_destino_base, personaje_limpio, nombre_limpio)
    if not validar_longitud_ruta(carpeta):
        raise ValueError(f"La ruta del capítulo excede los 260 caracteres permitidos (MAX_PATH): '{carpeta}'.")
    if not esta_confinado_en_raiz(carpeta, ruta_destino_base):
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
