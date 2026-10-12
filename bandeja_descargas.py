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
from bandeja.capcut import VigilanteCapCut
from bandeja.edicion import vincular_nuevo_export, procesar_exports_pendientes_copia
from bandeja.pendrive import detectar_pendrive

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


def crear_vigilante_capcut(config, db, ruta_bitacora):
    def punto_montaje():
        info = detectar_pendrive(config)
        if info and info.get("conectado"):
            return info.get("punto_montaje") or info.get("ruta_montaje")
        return None

    def nuevo_export(info):
        vincular_nuevo_export(info, punto_montaje(), db, config.carpeta_raiz_pendrive,
                             ruta_bitacora, copiar_automaticamente=config.envio_exports_capcut == "automatico")

    def procesar_pendientes():
        punto = punto_montaje()
        if config.envio_exports_capcut == "automatico":
            from bandeja.edicion import retomar_export_actual_sin_asignar
            retomar_export_actual_sin_asignar(db, punto, config.carpeta_raiz_pendrive, ruta_bitacora)
        if punto:
            procesar_exports_pendientes_copia(punto, db, config.carpeta_raiz_pendrive, ruta_bitacora)
            if config.envio_exports_capcut == "automatico":
                from bandeja.edicion import copiar_export_sin_sesion_a_sin_publicar
                for export in db.obtener_exports_pendientes(estado="sin_asignar"):
                    if export.get("sesion_id") or export.get("envio_automatico_bloqueado"):
                        continue
                    try:
                        copiar_export_sin_sesion_a_sin_publicar(export, punto, db, config.carpeta_raiz_pendrive, ruta_bitacora)
                    except (OSError, ValueError) as error:
                        if export.get("error") != str(error):
                            db.actualizar_export_pendiente(export["id"], error=str(error))

    return VigilanteCapCut(config.obtener_carpeta_exportacion_capcut(),
                          extensiones_temporales=config.extensiones_temporales_capcut,
                          callback_nuevo_export=nuevo_export, callback_sondeo=procesar_pendientes,
                          exports_registrados=db.obtener_exports_pendientes())


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
    vigilante_capcut = crear_vigilante_capcut(config, db, movimientos.ruta_bitacora)

    token_csrf = secrets.token_urlsafe(32)
    try:
        servidor = crear_servidor(config, db, vigilante, movimientos, miniaturas, token_csrf=token_csrf,
                                 vigilante_capcut=vigilante_capcut)
    except OSError as e:
        err_str = str(e).lower()
        err_code = getattr(e, "winerror", None) or getattr(e, "errno", None)
        if err_code in (errno.EADDRINUSE, 98, 10048) or "already in use" in err_str or "un solo uso" in err_str or "address already in use" in err_str:
            print(f"Ya hay una bandeja corriendo en el puerto {config.puerto_servidor}")
            sys.exit(0)
        raise

    vigilante.iniciar()
    vigilante_capcut.iniciar()

    print(f"[*] Bandeja de Descargas iniciada en http://{config.host_servidor}:{config.puerto_servidor}")
    print(f"[*] Vigilando: {config.ruta_descargas}")
    print(f"[*] Destino:   {config.ruta_destino_base}")

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Deteniendo servidor y vigilante...")
    finally:
        vigilante.detener()
        vigilante_capcut.detener()
        servidor.server_close()



if __name__ == "__main__":
    main()
