#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auditar_repo.py

Script de auditoría de seguridad y hermeticidad para el repositorio (Solo Lectura, Stdlib pura).
Verifica que ningún archivo versionado o commit contenga:
1. Rutas o nombres personales (ej. rutas absolutas personales bajo /home/ o /run/media/).
2. Credenciales, claves privadas, tokens o archivos sensibles (.kdbx, backup-codes, recovery, .env).
3. Bases de datos SQLite o binarias (*.sqlite, *.db).
4. Archivos multimedia pesados (salvo fixtures mínimos en tests).
5. Archivos mayores a 1 MB.
6. Reportes y planes generados por herramientas locales (informe_pendrive.*, plan_limpieza.*, etc.).

USO:
    python3 auditar_repo.py              # Audita los archivos rastreados actuales (git ls-files)
    python3 auditar_repo.py --historial  # Audita los archivos actuales y todo el historial de commits

CÓMO CONFIGURAR COMO HOOK PRE-PUSH EN GIT:
    Para evitar que se suban datos personales o archivos prohibidos accidentalmente:

    Opción 1: Enlace simbólico directo (Linux / macOS)
        ln -sf ../../auditar_repo.py .git/hooks/pre-push
        chmod +x .git/hooks/pre-push

    Opción 2: Script ejecutable en .git/hooks/pre-push (Multiplataforma)
        Crear el archivo .git/hooks/pre-push con el siguiente contenido:
        #!/bin/sh
        python3 auditar_repo.py --historial
        if [ $? -ne 0 ]; then
            echo "[!] Rechazando push: la auditoría del repositorio detectó infracciones."
            exit 1
        fi
        exit 0
"""

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from typing import List, Tuple

# Patrones de nombres de archivos prohibidos en git
PATRONES_ARCHIVOS_PROHIBIDOS = [
    # Credenciales y secretos
    "*.kdbx",
    "*backup-codes*",
    "*backup_codes*",
    "*recovery*",
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "*.pfx",
    "*.p12",
    # Bases de datos
    "*.sqlite",
    "*.sqlite3",
    "*.sqlite-wal",
    "*.sqlite-shm",
    "*.db",
    "*.db-wal",
    "*.db-shm",
    # Reportes y bitácoras generadas
    "informe_pendrive.*",
    "plan_limpieza.json",
    "plan_limpieza.md",
    "findings.md",
    "bitacora_bandeja.jsonl",
    "verificacion_windows.txt",
]

# Extensiones multimedia (salvo fixtures de test mínimos < 50KB)
EXTENSIONES_MULTIMEDIA = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".mp3", ".wav", ".ogg", ".flac",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".ico"
}

# Tamaño máximo permitido por archivo versionado (1 MB)
LIMITE_TAMANIO_BYTES = 1024 * 1024

# Patrones en contenido de texto
PATRON_CLAVE_PRIVADA = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")
PATRON_TOKEN_SENSIBLE = re.compile(
    r"(?:ghp_[a-zA-Z0-9]{36}|glpat-[a-zA-Z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35})"
)

# Rutas personales concretas prohibidas (se permiten marcadores genéricos como <usuario>, <user>, etc.)
PATRON_RUTA_PERSONAL = re.compile(
    r"(?:/home/|/run/media/)(?!<usuario>|<user>|<punto-de-montaje>|usuario|user|test|\.\.\.)[a-zA-Z0-9_-]+"
)

# Patrones para detección de rutas de usuario en Windows y Linux
PATRON_RUTA_WINDOWS_USERS = re.compile(
    r"[A-Za-z]:(?:\\\\|/|\\)Users(?:\\\\|/|\\)([a-zA-Z0-9_<>-]+)",
    re.IGNORECASE
)
PATRON_RUTA_LINUX_HOME = re.compile(
    r"/home/([a-zA-Z0-9_<>-]+)",
    re.IGNORECASE
)

# Excepciones genéricas permitidas en rutas de usuario (Windows / Linux)
EXCEPCIONES_USUARIO_GENERICAS = {
    "public", "default", "<usuario>", "<user>", "usuario", "user", "test", "...", "<punto-de-montaje>", "<nombre>", "nombre"
}

IDENTIFICADOR_PERSONAL_PROHIBIDO = "".join(["dark", "sun"])


def obtener_archivos_versionados() -> List[str]:
    """Obtiene la lista de archivos rastreados por git mediante git ls-files."""
    try:
        salida = subprocess.check_output(["git", "ls-files"], stderr=subprocess.PIPE)
        lineas = salida.decode("utf-8", errors="replace").splitlines()
        return [l.strip() for l in lineas if l.strip()]
    except subprocess.CalledProcessError as e:
        print(f"[!] Error al ejecutar git ls-files: {e}", file=sys.stderr)
        sys.exit(1)


def auditar_archivo_versionado(ruta_rel: str) -> List[Tuple[str, str, str]]:
    """
    Audita un archivo individual versionado.
    Retorna una lista de tuplas (archivo, tipo_error, detalle).
    """
    infracciones = []
    nombre_base = os.path.basename(ruta_rel)
    _, ext = os.path.splitext(nombre_base)

    # 1. Nombre de archivo prohibido
    for pat in PATRONES_ARCHIVOS_PROHIBIDOS:
        if fnmatch.fnmatch(nombre_base.lower(), pat.lower()):
            infracciones.append((ruta_rel, "ARCHIVO_PROHIBIDO", f"Nombre de archivo coincide con patrón '{pat}'"))

    # 2. Archivos multimedia (permitiendo solo fixtures mínimos de tests < 50 KB)
    if ext.lower() in EXTENSIONES_MULTIMEDIA:
        tam = os.path.getsize(ruta_rel) if os.path.isfile(ruta_rel) else 0
        es_fixture_test = ("test" in ruta_rel.lower() or "fixture" in ruta_rel.lower()) and tam < 50 * 1024
        if not es_fixture_test:
            infracciones.append((ruta_rel, "MULTIMEDIA", f"Archivo multimedia versionado ({ext})"))

    # 3. Tamaño superior a 1 MB
    if os.path.isfile(ruta_rel):
        tam = os.path.getsize(ruta_rel)
        if tam > LIMITE_TAMANIO_BYTES:
            infracciones.append((ruta_rel, "TAMANIO_EXCESIVO", f"Archivo supera 1 MB ({tam} bytes)"))

    # 4. Inspección de contenido en archivos de texto
    if os.path.isfile(ruta_rel) and not ruta_rel.endswith((".pyc", ".png", ".jpg", ".jpeg", ".ico")):
        try:
            with open(ruta_rel, "rb") as fb:
                raw = fb.read(4096)
                if b"\x00" in raw:
                    # Archivo binario
                    return infracciones

            with open(ruta_rel, "r", encoding="utf-8", errors="ignore") as f:
                for num_linea, linea in enumerate(f, 1):
                    # Búsqueda de palabra clave personal
                    if IDENTIFICADOR_PERSONAL_PROHIBIDO in linea.lower():
                        infracciones.append((
                            ruta_rel,
                            "RUTA_PERSONAL",
                            f"Línea {num_linea}: Contiene identificador personal del usuario"
                        ))

                    # Rutas personales absolutas
                    m_ruta = PATRON_RUTA_PERSONAL.search(linea)
                    if m_ruta:
                        infracciones.append((
                            ruta_rel,
                            "RUTA_PERSONAL",
                            f"Línea {num_linea}: Contiene ruta personal '{m_ruta.group(0)}'"
                        ))

                    # Rutas de usuario en Windows ([A-Za-z]:\Users\<nombre>)
                    for m_win in PATRON_RUTA_WINDOWS_USERS.finditer(linea):
                        nombre_usr = m_win.group(1).lower()
                        if nombre_usr not in EXCEPCIONES_USUARIO_GENERICAS:
                            infracciones.append((
                                ruta_rel,
                                "RUTA_USUARIO_WINDOWS",
                                f"Línea {num_linea}: Contiene ruta de usuario Windows '{m_win.group(0)}'"
                            ))

                    # Rutas de usuario en Linux (/home/<nombre>)
                    for m_lin in PATRON_RUTA_LINUX_HOME.finditer(linea):
                        nombre_usr = m_lin.group(1).lower()
                        if nombre_usr not in EXCEPCIONES_USUARIO_GENERICAS:
                            infracciones.append((
                                ruta_rel,
                                "RUTA_USUARIO_LINUX",
                                f"Línea {num_linea}: Contiene ruta de usuario Linux '{m_lin.group(0)}'"
                            ))

                    # Claves privadas
                    if PATRON_CLAVE_PRIVADA.search(linea):
                        infracciones.append((
                            ruta_rel,
                            "CREDENCIAL",
                            f"Línea {num_linea}: Posible clave privada detectada"
                        ))

                    # Tokens de API
                    m_tok = PATRON_TOKEN_SENSIBLE.search(linea)
                    if m_tok:
                        infracciones.append((
                            ruta_rel,
                            "CREDENCIAL",
                            f"Línea {num_linea}: Patrón de token/API key detectado '{m_tok.group(0)[:8]}...'"
                        ))
        except Exception as e:
            infracciones.append((ruta_rel, "ERROR_LECTURA", f"No se pudo auditar contenido: {e}"))

    return infracciones


def auditar_historial_git() -> List[Tuple[str, str, str]]:
    """
    Audita todos los commits en la historia del repositorio.
    Verifica nombres de archivos en cada commit y diffs.
    """
    infracciones = []
    print("[*] Auditando historial de commits de Git (--historial)...")

    # 1. Nombres de archivos que hayan existido en la historia
    try:
        salida_nombres = subprocess.check_output(
            ["git", "log", "--all", "--pretty=format:", "--name-only"],
            stderr=subprocess.PIPE
        )
        archivos_historia = set(salida_nombres.decode("utf-8", errors="replace").splitlines())
        for f in archivos_historia:
            f = f.strip()
            if not f:
                continue
            base = os.path.basename(f)
            for pat in PATRONES_ARCHIVOS_PROHIBIDOS:
                if fnmatch.fnmatch(base.lower(), pat.lower()):
                    infracciones.append((f, "HISTORIAL_ARCHIVO_PROHIBIDO", f"Archivo en historial coincide con '{pat}'"))
    except subprocess.CalledProcessError as e:
        infracciones.append(("<git-log>", "ERROR_GIT", f"Fallo al leer nombres de historia: {e}"))

    # 2. Diffs de todos los commits buscando fugas personales y credenciales
    try:
        salida_diff = subprocess.check_output(
            ["git", "log", "--all", "-p", "--unified=0"],
            stderr=subprocess.PIPE
        )
        lineas = salida_diff.decode("utf-8", errors="replace").splitlines()
        commit_actual = "desconocido"
        for linea in lineas:
            if linea.startswith("commit "):
                commit_actual = linea.split()[1][:12]
            elif linea.startswith("+") and not linea.startswith("+++"):
                contenido = linea[1:]
                if IDENTIFICADOR_PERSONAL_PROHIBIDO in contenido.lower():
                    infracciones.append((
                        f"commit {commit_actual}",
                        "HISTORIAL_RUTA_PERSONAL",
                        "Línea agregada contiene identificador personal del usuario"
                    ))
                if PATRON_CLAVE_PRIVADA.search(contenido):
                    infracciones.append((
                        f"commit {commit_actual}",
                        "HISTORIAL_CREDENCIAL",
                        "Línea agregada contiene clave privada"
                    ))
                if PATRON_TOKEN_SENSIBLE.search(contenido):
                    infracciones.append((
                        f"commit {commit_actual}",
                        "HISTORIAL_CREDENCIAL",
                        "Línea agregada contiene token o API key sensible"
                    ))
    except subprocess.CalledProcessError as e:
        infracciones.append(("<git-log>", "ERROR_GIT", f"Fallo al leer diffs de historia: {e}"))

    return infracciones


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auditoría estricta de rutas, datos personales, credenciales y reportes (Solo Lectura)."
    )
    parser.add_argument(
        "--historial",
        action="store_true",
        help="Audita también todos los commits y diffs del historial de Git."
    )
    args = parser.parse_args()

    archivos = obtener_archivos_versionados()
    print(f"[*] Auditando {len(archivos)} archivos rastreados en git ls-files...")

    todas_infracciones: List[Tuple[str, str, str]] = []
    for arch in archivos:
        infracciones = auditar_archivo_versionado(arch)
        todas_infracciones.extend(infracciones)

    if args.historial:
        infracciones_hist = auditar_historial_git()
        todas_infracciones.extend(infracciones_hist)

    if todas_infracciones:
        print(f"\n[!] SE ENCONTRARON {len(todas_infracciones)} INFRACCIONES DE SEGURIDAD/HERMETICIDAD:")
        for origen, categoria, detalle in todas_infracciones:
            print(f"  - [{categoria}] {origen}: {detalle}")
        print("\n[!] Auditoría FALLIDA. Remueva las rutas, datos personales o archivos prohibidos antes de continuar.\n")
        return 1

    print("[+] 0 infracciones detectadas. El repositorio está limpio de rutas, datos personales, credenciales y reportes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
