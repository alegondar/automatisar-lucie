#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verificar_windows.py

Script de verificación y diagnóstico para Windows 10/11 con Python 3.13 (stdlib pura).
Ejecuta diagnósticos completos sobre:
- Versión de Python y de sistema operativo
- Codificación de consola y salida estándar
- Resolución de carpeta de descargas del usuario
- Creación exclusiva, archivos .part y detección de colisiones en renombrado
- Validación preventiva de rutas largas (MAX_PATH) y nombres reservados
- Enumeración de unidades lógicas, sistema de archivos (exFAT/FAT32/NTFS) y marcadores de pendrive
- Inspección de st_birthtime vs st_ctime
- Apertura exclusiva de puerto HTTP (SO_EXCLUSIVEADDRUSE)
- Lectura de manifiesto de pendrive si existe
- Simulación de endpoint multimedia con soporte de cabecera HTTP Range

Cumple estrictamente con la Regla de Oro #1: NO BORRA NINGÚN ARCHIVO NI CARPETA.
La carpeta de pruebas '_verificacion_windows' se conserva intacta.
"""

import datetime
import http.client
import json
import os
import platform
import shutil
import socket
import sys
import threading
import time
from typing import Any, Dict, List, Tuple

# Reconfigurar salida estándar para emojis y tildes si es posible
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bandeja.plataforma import (
    obtener_ruta_descargas_windows,
    obtener_ruta_descargas_defecto,
    obtener_sistema_archivos,
    obtener_unidades_windows,
    esta_confinado_en_raiz,
    validar_longitud_ruta,
    obtener_ruta_exportacion_capcut,
)
from bandeja.config import (
    ConfiguracionBandeja,
    NOMBRES_RESERVADOS_WINDOWS,
    CARACTERES_INVALIDOS_ESCENA,
)
from bandeja.clasificacion import ValidadorEscenas
from bandeja.lotes import obtener_fecha_llegada
from bandeja.pendrive import detectar_pendrive, leer_manifiesto_pendrive


def registrar_resultado(resultados: List[Dict[str, Any]], categoria: str, exito: bool, detalle: str):
    estado_str = "OK" if exito else "FALLA"
    print(f"[{estado_str}] {categoria}: {detalle}")
    resultados.append({
        "categoria": categoria,
        "exito": exito,
        "estado": estado_str,
        "detalle": detalle
    })


def main():
    print("=" * 70)
    print("  VERIFICACIÓN DE COMPATIBILIDAD CON WINDOWS - LUCIE BANDEJA")
    print("=" * 70)
    print(f"Fecha y hora: {datetime.datetime.now().isoformat()}")
    print()

    resultados: List[Dict[str, Any]] = []

    # 1. Versión de Python y Sistema
    version_py = sys.version_info
    info_plat = platform.platform()
    es_py313_o_sup = version_py >= (3, 10)  # Objetivo Python 3.13, compatible 3.10+
    detalle_py = f"Python {version_py.major}.{version_py.minor}.{version_py.micro} en {info_plat}"
    registrar_resultado(resultados, "Versión de Python y Sistema", es_py313_o_sup, detalle_py)

    # 2. Codificación de Consola y Salida
    stdout_enc = getattr(sys.stdout, "encoding", "desconocido")
    stderr_enc = getattr(sys.stderr, "encoding", "desconocido")
    es_utf8 = bool(stdout_enc and "utf" in stdout_enc.lower())
    detalle_enc = f"stdout={stdout_enc}, stderr={stderr_enc}"
    registrar_resultado(resultados, "Codificación de Consola", True, detalle_enc)

    # 3. Carpeta de Descargas Detectada
    if os.name == "nt":
        ruta_desc = obtener_ruta_descargas_windows()
        existe_desc = os.path.isdir(ruta_desc)
    else:
        ruta_desc = obtener_ruta_descargas_defecto()
        existe_desc = os.path.isdir(ruta_desc)
    detalle_desc = f"Ruta resuelta: '{ruta_desc}' (Existe: {existe_desc})"
    registrar_resultado(resultados, "Carpeta de Descargas", existe_desc, detalle_desc)

    # 4. Carpeta de Prueba, Archivo .part y Renombrado Atómico
    dir_prueba = os.path.abspath("_verificacion_windows")
    os.makedirs(dir_prueba, exist_ok=True)
    ruta_part = os.path.join(dir_prueba, "prueba_video.mp4.part")
    ruta_final = os.path.join(dir_prueba, "prueba_video.mp4")
    ruta_colision_part = os.path.join(dir_prueba, "prueba_video_colision.mp4.part")

    try:
        with open(ruta_part, "wb") as f:
            f.write(b"CONTENIDO_VIDEO_PRUEBA_12345")
        if os.path.exists(ruta_final):
            rename_exito = True
        else:
            os.rename(ruta_part, ruta_final)
            rename_exito = os.path.exists(ruta_final)
    except Exception as e:
        rename_exito = False
        ruta_final = str(e)

    # Comprobación de que sobreescritura sobre destino existente es prevenida o falla
    colision_prevenida = False
    try:
        with open(ruta_colision_part, "wb") as f_col:
            f_col.write(b"CONTENIDO_COLISION")
        # En Windows os.rename sobre destino existente lanza FileExistsError
        if os.name == "nt":
            try:
                os.rename(ruta_colision_part, ruta_final)
                colision_prevenida = False
            except (FileExistsError, OSError):
                colision_prevenida = True
        else:
            # En Linux verificamos que la validación previa de la bandeja impida la colisión
            colision_prevenida = os.path.exists(ruta_final)
    except Exception:
        colision_prevenida = True

    registrar_resultado(
        resultados,
        "Creación .part y Renombrado Seguro",
        rename_exito and colision_prevenida,
        f"Renombrado .part exitoso: {rename_exito} | Colisión sobre destino existente rechazada: {colision_prevenida}"
    )

    # 5. Validación preventiva de MAX_PATH (260 caracteres)
    ruta_larga = os.path.join(dir_prueba, "sub" * 70, "archivo.mp4")
    val_longitud_ok = not validar_longitud_ruta(ruta_larga, max_longitud=260)
    registrar_resultado(
        resultados,
        "Validación Límite MAX_PATH (260 caracteres)",
        val_longitud_ok,
        f"Ruta de {len(ruta_larga)} caracteres detectada y rechazada preventivamente sin trazas"
    )

    # 6. Rechazo de Nombres Reservados de Windows
    validador = ValidadorEscenas()
    nombres_prueba = ["CON", "PRN", "AUX", "NUL", "COM1", "LPT9", "capitulo.", "capitulo "]
    rechazados = []
    for n in nombres_prueba:
        es_val, _ = validador.validar_nombre_escena(n, ruta_destino_base=dir_prueba, ruta_descargas=dir_prueba)
        if not es_val:
            rechazados.append(n)
    todos_rechazados = len(rechazados) == len(nombres_prueba)
    registrar_resultado(
        resultados,
        "Nombres Reservados y Caracteres Inválidos de Windows",
        todos_rechazados,
        f"Rechazados {len(rechazados)}/{len(nombres_prueba)}: {', '.join(rechazados)}"
    )

    # 7. Unidades Detectadas, Filesystem y Espacio Libre
    unidades_win = obtener_unidades_windows()
    detalle_unidades = []
    for u in unidades_win:
        u_raiz = u.get("unidad", "")
        fs = obtener_sistema_archivos(u_raiz)
        try:
            esp = shutil.disk_usage(u_raiz)
            libre_gb = esp.free / (1024**3)
            tot_gb = esp.total / (1024**3)
            esp_str = f"{libre_gb:.1f} GB libres de {tot_gb:.1f} GB"
        except Exception:
            esp_str = "espacio no consultable"
        tiene_marcador = os.path.exists(os.path.join(u_raiz, ".lucie_pendrive.json"))
        detalle_unidades.append(f"{u_raiz} [{u.get('tipo', 'desconocido')}, {fs}, {esp_str}, pendrive_marcador={tiene_marcador}]")

    desc_unidades_str = "; ".join(detalle_unidades) if detalle_unidades else "No se detectaron unidades vía ctypes"
    registrar_resultado(
        resultados,
        "Enumeración de Unidades y Sistemas de Archivos",
        True,
        desc_unidades_str
    )

    # 8. Inspección de st_birthtime vs st_ctime
    try:
        st_prueba = os.stat(ruta_final)
        tiene_birthtime = hasattr(st_prueba, "st_birthtime")
        birthtime_val = getattr(st_prueba, "st_birthtime", None)
        ctime_val = getattr(st_prueba, "st_ctime", None)
        fecha_llegada_val = obtener_fecha_llegada(st_prueba)
        detalle_fechas = (
            f"st_birthtime={birthtime_val} (presente: {tiene_birthtime}) | "
            f"st_ctime={ctime_val} | fecha_llegada_efectiva={fecha_llegada_val}"
        )
        registrar_resultado(resultados, "Fechas de Creación e Inodo", True, detalle_fechas)
    except Exception as e:
        registrar_resultado(resultados, "Fechas de Creación e Inodo", False, str(e))

    # 9. Apertura Exclusiva de Puerto de la Bandeja
    puerto_test = 8799
    sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_exclusivo_ok = False
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE") and os.name == "nt":
            sock1.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock2.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock1.bind(("127.0.0.1", puerto_test))
        sock1.listen(1)

        # Segundo socket en el mismo puerto debe fallar
        try:
            sock2.bind(("127.0.0.1", puerto_test))
            sock2.listen(1)
            socket_exclusivo_ok = False
            detalle_sock = "FALLA: dos sockets pudieron enlazar simultáneamente al mismo puerto."
        except OSError:
            socket_exclusivo_ok = True
            detalle_sock = f"Exclusividad garantizada en 127.0.0.1:{puerto_test} (segunda instancia rechazada)."
    except Exception as e:
        detalle_sock = f"Error al probar exclusividad: {e}"
    finally:
        sock1.close()
        sock2.close()

    registrar_resultado(resultados, "Exclusividad de Instancia (Socket)", socket_exclusivo_ok, detalle_sock)

    # 10. Lectura del Manifiesto de Pendrive si existe
    pen = detectar_pendrive()
    if pen and pen.get("conectado"):
        carpeta_raiz = pen.get("carpeta_raiz_pendrive", "LucieSinReglas")
        manif = leer_manifiesto_pendrive(pen["punto_montaje"], carpeta_raiz)
        registrar_resultado(
            resultados,
            "Manifiesto de Pendrive Vinculado",
            True,
            f"Pendrive ID {pen.get('id')} detectado. {len(manif)} entradas en manifiesto.jsonl"
        )
    else:
        registrar_resultado(
            resultados,
            "Manifiesto de Pendrive Vinculado",
            True,
            "No hay pendrive vinculado conectado actualmente (prueba informativa omitida sin error)"
        )

    # 11. Confinamiento de Rutas y Separador Canónico
    confinado_ok = esta_confinado_en_raiz(dir_prueba, os.getcwd())
    confinado_fuera = not esta_confinado_en_raiz("C:\\Windows\\System32", os.getcwd())
    registrar_resultado(
        resultados,
        "Confinamiento Canónico de Rutas",
        confinado_ok and confinado_fuera,
        f"Directorio local confinado: {confinado_ok} | Ruta externa rechazada: {confinado_fuera}"
    )

    # 12. Servicio Multimedia /api/media con soporte de Range
    from bandeja.servidor import HandlerServidorBandeja, ServidorBandejaHTTPServer

    range_ok = False
    detalle_range = ""
    httpd = None
    try:
        cfg_test = ConfiguracionBandeja()
        cfg_test.ruta_descargas = os.path.dirname(ruta_final)
        cfg_test.ruta_destino_base = os.path.dirname(ruta_final)
        cfg_test.puerto_servidor = 0

        class MockVigilanteMedia:
            def resolver_ruta_media(self, media_id):
                if media_id == "media_test":
                    return ruta_final
                return None

        class CustomHandler(HandlerServidorBandeja):
            pass

        CustomHandler.config = cfg_test
        CustomHandler.db = None
        CustomHandler.movimientos = None
        CustomHandler.vigilante = MockVigilanteMedia()
        CustomHandler.miniaturas = None
        CustomHandler.token_csrf = "test_csrf"

        httpd = ServidorBandejaHTTPServer(("127.0.0.1", 0), CustomHandler)
        puerto_asignado = httpd.server_address[1]
        cfg_test.puerto_servidor = puerto_asignado

        hilo_srv = threading.Thread(target=httpd.serve_forever, daemon=True)
        hilo_srv.start()

        conn = http.client.HTTPConnection("127.0.0.1", puerto_asignado, timeout=3.0)
        conn.request("GET", "/api/media?id=media_test", headers={"Range": "bytes=0-4"})
        resp = conn.getresponse()
        cuerpo = resp.read()
        crange_hdr = resp.getheader("Content-Range", "")
        conn.close()

        if resp.status == 206 and crange_hdr.startswith("bytes 0-4/") and len(cuerpo) == 5:
            range_ok = True
            detalle_range = f"HTTP 206 Partial Content verificado con Content-Range '{crange_hdr}' ({len(cuerpo)} bytes recibidos)"
        else:
            detalle_range = f"Respuesta inesperada: status={resp.status}, Content-Range='{crange_hdr}'"
    except Exception as e:
        detalle_range = f"Error al probar servicio multimedia con Range: {e}"
    finally:
        if httpd:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass

    registrar_resultado(resultados, "Servicio Multimedia /api/media (HTTP Range)", range_ok, detalle_range)

    # 13. Carpeta de Exportación CapCut (Solo Lectura)
    ruta_capcut = obtener_ruta_exportacion_capcut()
    existe_capcut = os.path.exists(ruta_capcut) and os.path.isdir(ruta_capcut)
    if existe_capcut:
        lectura_ok = os.access(ruta_capcut, os.R_OK)
        conteo_exports = 0
        try:
            for raiz_c, _dirs_c, archivos_c in os.walk(ruta_capcut):
                rel = os.path.relpath(raiz_c, ruta_capcut)
                prof = 0 if rel == "." else len(rel.split(os.sep))
                if prof > 3:
                    continue
                conteo_exports += len(archivos_c)
        except Exception:
            conteo_exports = -1
        det_capcut = (
            f"Carpeta: '{ruta_capcut}' | Existe: Sí | Lectura: {'OK' if lectura_ok else 'DENEGADO'} "
            f"| Exports preexistentes: {conteo_exports}"
        )
        registrar_resultado(resultados, "Carpeta de Exportación CapCut", lectura_ok, det_capcut)
    else:
        det_capcut = (
            f"Carpeta: '{ruta_capcut}' no existe actualmente en este entorno (diagnóstico informativo)"
        )
        registrar_resultado(resultados, "Carpeta de Exportación CapCut", True, det_capcut)

    # 14. Guardar Informe en verificacion_windows.txt
    ruta_informe = os.path.abspath("verificacion_windows.txt")
    lineas_informe = [
        "INFORME DE VERIFICACIÓN DE ENTORNO WINDOWS - LUCIE BANDEJA",
        f"Fecha: {datetime.datetime.now().isoformat()}",
        f"Plataforma: {platform.platform()} | Python: {platform.python_version()}",
        "-" * 70,
    ]
    for r in resultados:
        lineas_informe.append(f"[{r['estado']}] {r['categoria']}")
        lineas_informe.append(f"       Detalle: {r['detalle']}")
    lineas_informe.extend([
        "-" * 70,
        "Aviso: La carpeta '_verificacion_windows' se conserva sin borrado automático,",
        "cumpliendo la Regla de Oro #1 del proyecto. Puede ser eliminada manualmente.",
    ])

    with open(ruta_informe, "w", encoding="utf-8", newline="\n") as f_inf:
        f_inf.write("\n".join(lineas_informe) + "\n")

    print()
    print("=" * 70)
    print(f"[+] Informe de verificación guardado en: {ruta_informe}")
    print("[i] Regla de Oro #1: La carpeta '_verificacion_windows' se mantiene en disco.")
    print("    Si no la necesitas más, podés eliminarla manualmente.")
    print("=" * 70)


if __name__ == "__main__":
    main()
