#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
instalar_hooks.py

Instalador del hook pre-push de Git para el proyecto Lucie (Solo Stdlib, Creación Exclusiva).
Instala un hook en .git/hooks/pre-push que ejecuta:
    python3 auditar_repo.py --historial
y bloquea cualquier intento de push si la auditoría detecta infracciones.

Garantía de creación exclusiva:
- Si ya existe un hook en .git/hooks/pre-push, NO lo sobrescribe; informa al usuario y sale.
- No utiliza ninguna primitiva de borrado destructivo ni dependencias externas.
"""

import os
import stat
import sys

CONTENIDO_HOOK_PRE_PUSH = """#!/bin/sh
# Hook pre-push generado automáticamente por instalar_hooks.py
# Verifica que el repositorio esté libre de rutas/datos personales, credenciales y reportes.

echo "[*] [Hook pre-push] Ejecutando auditoría de seguridad del repositorio..."
python3 auditar_repo.py --historial
ESTADO=$?

if [ $ESTADO -ne 0 ]; then
    echo ""
    echo "======================================================================"
    echo "[!] ERROR: Push cancelado por auditar_repo.py."
    echo "    Se detectaron datos personales, credenciales o archivos prohibidos."
    echo "======================================================================"
    exit 1
fi

exit 0
"""


def instalar_hook_pre_push(directorio_repo: str = ".") -> int:
    """
    Instala el hook pre-push en el repositorio Git especificado de manera no destructiva.
    Retorna 0 en caso de éxito o si el hook ya existía de forma segura, o 1 en caso de error.
    """
    ruta_git = os.path.join(os.path.abspath(directorio_repo), ".git")
    if not os.path.isdir(ruta_git):
        print(f"[!] Error: No se encontró el directorio .git en '{directorio_repo}'.", file=sys.stderr)
        return 1

    dir_hooks = os.path.join(ruta_git, "hooks")
    os.makedirs(dir_hooks, exist_ok=True)

    ruta_hook = os.path.join(dir_hooks, "pre-push")

    if os.path.exists(ruta_hook):
        print(f"[!] Aviso: El hook pre-push ya existe en '{ruta_hook}'.")
        print("    Por seguridad no se sobrescribió. Si desea reinstalarlo, gestione el archivo existente.")
        return 0

    try:
        # Creación exclusiva: falla si el archivo se crea concurrentemente
        with open(ruta_hook, "x", encoding="utf-8") as f:
            f.write(CONTENIDO_HOOK_PRE_PUSH)

        # Otorgar permisos de ejecución (rwxr-xr-x)
        modo_actual = os.stat(ruta_hook).st_mode
        nuevo_modo = modo_actual | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        os.chmod(ruta_hook, nuevo_modo)

        print(f"[+] Hook pre-push instalado exitosamente en: {ruta_hook}")
        print("    A partir de ahora, 'git push' ejecutará automáticamente 'python3 auditar_repo.py --historial'.")
        return 0
    except FileExistsError:
        print(f"[!] Aviso: El hook '{ruta_hook}' ya existe. No se sobrescribió.")
        return 0
    except Exception as e:
        print(f"[!] Error al instalar el hook pre-push: {e}", file=sys.stderr)
        return 1


def main() -> int:
    repo_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    return instalar_hook_pre_push(repo_dir)


if __name__ == "__main__":
    sys.exit(main())
