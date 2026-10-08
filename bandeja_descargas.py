#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bandeja_descargas.py

Punto de entrada compatible y facade de la bandeja de descargas del proyecto Lucie.
Re-exporta la interfaz pública del paquete modular 'bandeja' y expone el comando principal.

Cumple estrictamente con las 7 Reglas de Oro del proyecto:
- PROHIBICIÓN ABSOLUTA DE BORRADO Y SOBRESCRITURA DESTRUCTIVA.
- Simulación previa obligatoria (dry-run).
- Verificación de destino (nunca sobrescribir).
- Registro auditable .jsonl y función de deshacer con os.rename (sin borrar).
- Confinamiento estricto a ~/Descargas.
- Análisis estático AST anti-borrado: 0 violaciones.
"""

import argparse
import errno
import logging
import os
import secrets
import sys
from typing import Dict, List, Optional, Set, Tuple, Any, Union

from bandeja import *
from bandeja.servidor import HandlerServidorBandeja, crear_servidor, GeneradorMiniaturas

# Reconfiguración de consola para evitar fallos de codificación en Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger("bandeja_descargas")
if not logger.handlers:
    _handler_log = logging.StreamHandler()
    _handler_log.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_handler_log)
    logger.setLevel(logging.INFO)


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

    token_csrf = secrets.token_urlsafe(32)
    try:
        servidor = crear_servidor(config, db, vigilante, movimientos, miniaturas, token_csrf=token_csrf)
    except OSError as e:
        err_str = str(e).lower()
        err_code = getattr(e, "winerror", None) or getattr(e, "errno", None)
        if err_code in (errno.EADDRINUSE, 98, 10048) or "already in use" in err_str or "un solo uso" in err_str or "address already in use" in err_str:
            print(f"Ya hay una bandeja corriendo en el puerto {config.puerto_servidor}")
            sys.exit(0)
        raise

    vigilante.iniciar()

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
