#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja_descargas.py

Módulo de detección, agrupación en lotes y organización segura de contenido nuevo
del proyecto Lucie que cae en ~/Descargas hacia la jerarquía de personaje y escena.

Cumple estrictamente con las 7 Reglas de Oro del proyecto:
- PROHIBICIÓN ABSOLUTA DE BORRADO Y SOBRESCRITURA DESTRUCTIVA.
- Simulación previa obligatoria (dry-run).
- Verificación de destino (nunca sobrescribir).
- Registro auditable .jsonl y función de deshacer con os.rename (sin borrar).
- Confinamiento estricto a ~/Descargas.
- Análisis estático AST anti-borrado: 0 violaciones.
"""

import argparse
import concurrent.futures
import datetime
import fnmatch
import glob
import hashlib
import hmac
import html
import json
import contextlib
import logging
import os
import platform
import re
import secrets
import shutil
import sqlite3
import string
import subprocess
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("bandeja_descargas")
if not logger.handlers:
    _handler_log = logging.StreamHandler()
    _handler_log.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_handler_log)
    logger.setLevel(logging.INFO)
from bandeja.plataforma import notificar_escritorio
from bandeja.config import (
    RUTA_DESCARGAS_DEFECTO,
    RUTA_DESTINO_DEFECTO,
    CARPETA_RAIZ_PENDRIVE_DEFECTO,
    EXTENSIONES_MEDIA_DEFECTO,
    EXTENSIONES_IMAGENES_DEFECTO,
    EXTENSIONES_VIDEOS_DEFECTO,
    EXTENSIONES_TEMP_DEFECTO,
    NOMBRES_RESERVADOS_WINDOWS,
    CARACTERES_INVALIDOS_ESCENA,
    ErrorSeguridadBandeja,
    ErrorValidacionEscena,
    ErrorDeshacer,
    calcular_sha256,
    formatear_bytes,
    ConfiguracionBandeja,
)


from bandeja.db import GestorBaseDatosBandeja
from bandeja.clasificacion import (
    clasificar_familia_medio,
    FiltroListaBlanca,
    ValidadorEscenas,
    asegurar_carpeta_capitulo,
)
from bandeja.lotes import (
    obtener_fecha_llegada,
    DetectorDescargasActivas,
    AgrupadorLotes,
)
from bandeja.capitulos import (
    calcular_balance_capitulo,
    es_capitulo_olvidado,
    simular_descartar_capitulo,
    ejecutar_descartar_capitulo,
    revertir_descarte_capitulo,
)



from bandeja.movimientos import (
    generar_html_simulacion,
    GestorMovimientosBandeja,
)



# ==============================================================================
# MÓDULO DE ENVÍO A PENDRIVE (LucieSinReglas) - DETECCIÓN, MARCADOR Y SEGURIDAD
# ==============================================================================

from bandeja.pendrive import (
    NOMBRE_MARCADOR_PENDRIVE,
    CARPETA_RAIZ_PENDRIVE_DEFECTO,
    NOMBRE_MANIFIESTO_PENDRIVE,
    validar_marcador_pendrive,
    leer_marcador_pendrive,
    detectar_pendrive,
    detectar_pendrive_seguro,
    detectar_unidad_candidata_sin_vincular,
    simular_vinculacion_pendrive,
    vincular_pendrive,
    leer_manifiesto_pendrive,
    _es_extension_video,
    _es_extension_foto,
    _es_extension_multimedia,
    escanear_capitulos_para_envio,
    listar_archivos_part_huerfanos,
    _leer_estado_pendrive_raw,
    obtener_estado_pendrive,
    simular_envio_capitulos,
    ejecutar_envio_pendrive,
    deshacer_envio_pendrive,
    obtener_sistema_archivos,
    obtener_espacio_disco,
    buscar_puntos_montaje_candidatos,
    ejecutar_lectura_pendrive_con_timeout,
)


from bandeja.vigilante import VigilanteBandeja


from bandeja.servidor import (
    GeneradorMiniaturas,
    HandlerServidorBandeja,
    crear_servidor,
)

def main():
    parser = argparse.ArgumentParser(description="Bandeja de Descargas - Proyecto Lucie")
    parser.add_argument("--config", "-c", default="config_bandeja.json", help="Ruta al archivo config_bandeja.json")
    parser.add_argument("--puerto", "-p", type=int, default=None, help="Puerto HTTP del panel (por defecto 8766)")
    parser.add_argument("--descargas", "-d", default=None, help="Ruta alternativa de ~/Descargas")
    parser.add_argument("--destino", default=None, help="Ruta base destino (por defecto ~/Descargas/_lucie)")
    args = parser.parse_args()

    config = ConfiguracionBandeja(ruta_config=args.config)
    if args.puerto:
        config.puerto_servidor = args.puerto
    if args.descargas:
        config.ruta_descargas = os.path.abspath(os.path.expanduser(args.descargas))
    if args.destino:
        config.ruta_destino_base = os.path.abspath(os.path.expanduser(args.destino))

    db = GestorBaseDatosBandeja()
    filtro = FiltroListaBlanca(config)
    detector = DetectorDescargasActivas()
    agrupador = AgrupadorLotes(config.ventana_lote_minutos)
    movimientos = GestorMovimientosBandeja(
        config.ruta_descargas, config.ruta_destino_base, db,
        subcarpeta_fotos=config.subcarpeta_fotos, subcarpeta_videos=config.subcarpeta_videos
    )
    miniaturas = GeneradorMiniaturas(db)

    vigilante = VigilanteBandeja(config, db, filtro, detector, agrupador)
    vigilante.iniciar()

    token_csrf = secrets.token_urlsafe(32)
    servidor = crear_servidor(config, db, vigilante, movimientos, miniaturas, token_csrf=token_csrf)

    print(f"[*] Bandeja de Descargas iniciada en http://{config.host_servidor}:{config.puerto_servidor}")
    print(f"[*] Vigilando: {config.ruta_descargas}")
    print(f"[*] Destino:   {config.ruta_destino_base}")

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Deteniendo servidor y vigilante...")
    finally:
        vigilante.detener()
        servidor.server_close()


if __name__ == "__main__":
    main()
