#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja/config.py

Gestión de configuración, rutas base y constantes operativas para la bandeja de descargas.
"""

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Union

from bandeja.plataforma import obtener_ruta_descargas_defecto, obtener_ruta_destino_defecto

logger = logging.getLogger("bandeja.config")

# Constantes del sistema
RUTA_DESCARGAS_DEFECTO = obtener_ruta_descargas_defecto()
RUTA_DESTINO_DEFECTO = obtener_ruta_destino_defecto()
CARPETA_RAIZ_PENDRIVE_DEFECTO = "LucieSinReglas"
EXTENSIONES_MEDIA_DEFECTO = [".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".mp3"]
EXTENSIONES_IMAGENES_DEFECTO = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSIONES_VIDEOS_DEFECTO = {".mp4", ".mov", ".webm"}
EXTENSIONES_TEMP_DEFECTO = [".crdownload", ".part", ".tmp"]
NOMBRES_RESERVADOS_WINDOWS = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}
CARACTERES_INVALIDOS_ESCENA = set('<>:"|?*\\/')


class ErrorSeguridadBandeja(Exception):
    """Excepción para violaciones de seguridad o confinamiento de rutas."""
    pass


class ErrorValidacionEscena(Exception):
    """Excepción para nombres de escena inválidos."""
    pass


class ErrorDeshacer(Exception):
    """Excepción al revertir una operación si la ruta previa está ocupada."""
    pass


class ErrorMovimiento(Exception):
    """Excepción al ocurrir un error durante el movimiento seguro de archivos o carpetas."""
    pass


def calcular_sha256(ruta_archivo: str, bloque: int = 65536) -> str:
    """Calcula el hash SHA-256 de un archivo de manera segura."""
    h = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        while True:
            datos = f.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()


def formatear_bytes(total_bytes: int) -> str:
    """Formatea una cantidad de bytes a una cadena legible (B, KB, MB, GB)."""
    if total_bytes < 1024:
        return f"{total_bytes} B"
    elif total_bytes < 1024 * 1024:
        return f"{total_bytes / 1024:.1f} KB"
    elif total_bytes < 1024 * 1024 * 1024:
        return f"{total_bytes / (1024 * 1024):.1f} MB"
    return f"{total_bytes / (1024 * 1024 * 1024):.1f} GB"


class ConfiguracionBandeja:
    """Gestiona la carga y validación de config_bandeja.json."""

    def __init__(self, ruta_config: str = "config_bandeja.json", ruta_config_local: Optional[str] = None):
        self.ruta_config = ruta_config
        if ruta_config_local is not None:
            self.ruta_config_local = ruta_config_local
        elif os.path.basename(ruta_config) == "config_bandeja.json":
            dir_base = os.path.dirname(os.path.abspath(ruta_config))
            self.ruta_config_local = os.path.join(dir_base, "config_bandeja.local.json")
        else:
            self.ruta_config_local = ""
        self.ruta_descargas = obtener_ruta_descargas_defecto()
        self.ruta_destino_base = obtener_ruta_destino_defecto()
        self.puerto_servidor = 8766
        self.host_servidor = "127.0.0.1"
        self.intervalo_sondeo_segundos = 5
        self.ventana_lote_minutos = 10
        self.extensiones_media = list(EXTENSIONES_MEDIA_DEFECTO)
        self.extensiones_temporales = list(EXTENSIONES_TEMP_DEFECTO)
        self.patrones_candidatos = {
            "grok": "grok-video-*",
            "grok_video": "grok-video-*",
            "grok_image": "grok-image-*",
            "gemini": "Gemini_Generated_Image_*",
            "nano_banana_regex": r"^.+_\d{14}\.(jpg|jpeg|png|webp)$",
            "flow": ""
        }
        self.patrones_ignorar = ["Screenshot_*", "Captura*"]
        self.horas_alerta_capitulo_olvidado = 12
        self.minutos_antes_inicio_capitulo = 0
        self.horas_material_reciente = 168.0
        self.refresco_panel_segundos = 4
        self.subcarpeta_fotos = "fotos"
        self.subcarpeta_videos = "videos"
        self.carpeta_raiz_pendrive = CARPETA_RAIZ_PENDRIVE_DEFECTO
        self.rutas_candidatas_pendrive: List[str] = []
        self.etiqueta_pendrive_pista: Optional[str] = "MIUNIDAD"
        self.margen_libre_bytes = 1024 * 1024 * 1024  # 1 GiB por defecto
        self.carpeta_exportacion_capcut: str = "auto"
        self.al_exportar: str = "preguntar"  # "preguntar" | "automatico" | "manual"
        self.extensiones_temporales_capcut: List[str] = [".tmp", ".part", ".crdownload", ".tmp.mp4"]
        self._inicializar_config_local_windows()
        self.cargar()

    def _inicializar_config_local_windows(self):
        """Crea config_bandeja.local.json en Windows en modo 'xb' si no existe."""
        if os.name == "nt" and self.ruta_config_local and not os.path.exists(self.ruta_config_local):
            datos_locales = {
                "ruta_descargas": "auto",
                "carpeta_exportacion_capcut": "auto"
            }
            try:
                with open(self.ruta_config_local, "xb") as f:
                    contenido = json.dumps(datos_locales, indent=2, ensure_ascii=False) + "\n"
                    f.write(contenido.encode("utf-8"))
            except FileExistsError:
                pass
            except Exception as e:
                logger.debug(f"No se pudo crear {self.ruta_config_local}: {e}")

    def cargar(self):
        datos = {}
        if os.path.exists(self.ruta_config):
            with open(self.ruta_config, "r", encoding="utf-8", newline="\n") as f:
                datos = json.load(f)

        if self.ruta_config_local and os.path.exists(self.ruta_config_local):
            try:
                with open(self.ruta_config_local, "r", encoding="utf-8", newline="\n") as f_local:
                    datos_local = json.load(f_local)
                    if isinstance(datos_local, dict):
                        datos.update(datos_local)
            except Exception as e:
                logger.warning(f"Error al leer {self.ruta_config_local}: {e}")

        if "ruta_descargas" in datos:
            val_desc = str(datos["ruta_descargas"]).strip()
            if val_desc.lower() == "auto":
                self.ruta_descargas = obtener_ruta_descargas_defecto()
            else:
                self.ruta_descargas = os.path.abspath(os.path.expanduser(val_desc))
            if "ruta_destino_base" not in datos:
                self.ruta_destino_base = os.path.join(self.ruta_descargas, "_lucie")

        if "ruta_destino_base" in datos:
            val_dest = str(datos["ruta_destino_base"]).strip()
            if val_dest.lower() == "auto":
                self.ruta_destino_base = os.path.join(self.ruta_descargas, "_lucie")
            else:
                self.ruta_destino_base = os.path.abspath(os.path.expanduser(val_dest))
        if "puerto_servidor" in datos:
            self.puerto_servidor = int(datos["puerto_servidor"])
        if "host_servidor" in datos:
            self.host_servidor = str(datos["host_servidor"])
        if "horas_alerta_capitulo_olvidado" in datos:
            self.horas_alerta_capitulo_olvidado = max(1, int(datos["horas_alerta_capitulo_olvidado"]))
        if "minutos_antes_inicio_capitulo" in datos:
            self.minutos_antes_inicio_capitulo = max(0, int(datos["minutos_antes_inicio_capitulo"]))
        if "horas_material_reciente" in datos:
            try:
                self.horas_material_reciente = max(0.0, float(datos["horas_material_reciente"]))
            except (ValueError, TypeError):
                self.horas_material_reciente = 0.0
        if "refresco_panel_segundos" in datos:
            try:
                self.refresco_panel_segundos = max(0, int(datos["refresco_panel_segundos"]))
            except (ValueError, TypeError):
                self.refresco_panel_segundos = 4
        if "subcarpeta_fotos" in datos:
            val = str(datos["subcarpeta_fotos"]).strip()
            if val:
                self.subcarpeta_fotos = val
        if "subcarpeta_videos" in datos:
            val = str(datos["subcarpeta_videos"]).strip()
            if val:
                self.subcarpeta_videos = val
        if "carpeta_raiz_pendrive" in datos:
            val = str(datos["carpeta_raiz_pendrive"]).strip()
            if val:
                self.carpeta_raiz_pendrive = val
        if "rutas_candidatas_pendrive" in datos and isinstance(datos["rutas_candidatas_pendrive"], list):
            self.rutas_candidatas_pendrive = [os.path.abspath(os.path.expanduser(str(r))) for r in datos["rutas_candidatas_pendrive"] if str(r).strip()]
        if "etiqueta_pendrive_pista" in datos:
            val_etiq = str(datos["etiqueta_pendrive_pista"]).strip()
            self.etiqueta_pendrive_pista = val_etiq if val_etiq else None
        if "margen_libre_bytes" in datos:
            try:
                self.margen_libre_bytes = max(0, int(datos["margen_libre_bytes"]))
            except (ValueError, TypeError):
                self.margen_libre_bytes = 1024 * 1024 * 1024
        if "intervalo_sondeo_segundos" in datos:
            self.intervalo_sondeo_segundos = max(1, int(datos["intervalo_sondeo_segundos"]))
        if "ventana_lote_minutos" in datos:
            self.ventana_lote_minutos = max(1, int(datos["ventana_lote_minutos"]))
        if "extensiones_media" in datos:
            self.extensiones_media = [ext.lower() for ext in datos["extensiones_media"]]
        if "extensiones_temporales" in datos:
            self.extensiones_temporales = [ext.lower() for ext in datos["extensiones_temporales"]]
        if "patrones_candidatos" in datos:
            if isinstance(datos["patrones_candidatos"], dict):
                self.patrones_candidatos.update(datos["patrones_candidatos"])
            elif isinstance(datos["patrones_candidatos"], list):
                for idx, pat in enumerate(datos["patrones_candidatos"]):
                    self.patrones_candidatos[f"patron_{idx}"] = pat
        if "patrones_ignorar" in datos:
            self.patrones_ignorar = [str(p) for p in datos["patrones_ignorar"]]
        if "carpeta_exportacion_capcut" in datos:
            val_cap = str(datos["carpeta_exportacion_capcut"]).strip()
            if val_cap.lower() == "auto":
                self.carpeta_exportacion_capcut = "auto"
            else:
                self.carpeta_exportacion_capcut = os.path.abspath(os.path.expanduser(val_cap))
        if "al_exportar" in datos:
            val_al = str(datos["al_exportar"]).strip().lower()
            if val_al in ("preguntar", "automatico", "manual"):
                self.al_exportar = val_al
        if "extensiones_temporales_capcut" in datos and isinstance(datos["extensiones_temporales_capcut"], list):
            self.extensiones_temporales_capcut = [str(ext).lower().strip() for ext in datos["extensiones_temporales_capcut"] if str(ext).strip()]

    def obtener_carpeta_exportacion_capcut(self) -> str:
        """Retorna la ruta resuelta a la carpeta de exportaciones de CapCut según plataforma."""
        if self.carpeta_exportacion_capcut == "auto":
            from bandeja.plataforma import obtener_ruta_exportacion_capcut
            return obtener_ruta_exportacion_capcut()
        return self.carpeta_exportacion_capcut
