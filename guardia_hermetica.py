#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guardia_hermetica.py

Módulo de hermeticidad y aislamiento para la suite de pruebas del proyecto Lucie.
Garantiza que ningún test dependa del entorno del sistema anfitrión:
1. Redirige HOME y variables XDG a un directorio temporal exclusivo.
2. Neutraliza la autodetección de unidades de almacenamiento reales (deja vacía la lista de candidatas).
3. Neutraliza la base SQLite real, la bitácora y la caché de miniaturas por defecto.
4. Intercepta open(), io.open(), os.scandir(), os.listdir() y os.walk() para hacer fallar
   inmediatamente con AssertionError cualquier intento de acceder a rutas bajo /media,
   /run/media, /mnt o las carpetas Descargas/Downloads reales del usuario.
"""

import builtins
import io
import os
import tempfile
from typing import Any, List, Optional, Set, Tuple

# Referencias a las funciones originales del sistema
_ORIGINAL_OPEN = builtins.open
_ORIGINAL_IO_OPEN = io.open
_ORIGINAL_LISTDIR = os.listdir
_ORIGINAL_SCANDIR = os.scandir
_ORIGINAL_WALK = os.walk

# Estado de la guardia
_GUARDIA_ACTIVADA = False
_TMP_HOME_DIR: Optional[str] = None
_RUTAS_PROHIBIDAS: Set[str] = set()


def _resolver_rutas_reales() -> Set[str]:
    """Identifica las rutas reales del host que deben ser estrictamente inaccesibles en tests."""
    rutas = {"/media", "/run/media", "/mnt"}

    # Descargas / Downloads del HOME real actual o del usuario del sistema
    candidatos_home = []
    env_home = os.environ.get("HOME")
    if env_home and not env_home.startswith("/tmp"):
        candidatos_home.append(env_home)

    try:
        import pwd
        pw_home = pwd.getpwuid(os.getuid()).pw_dir
        if pw_home and not pw_home.startswith("/tmp"):
            candidatos_home.append(pw_home)
    except Exception:
        pass

    usuario = os.environ.get("USER")
    if usuario and not usuario.startswith("tmp"):
        candidatos_home.append(f"/home/{usuario}")

    for h in set(candidatos_home):
        if h:
            h_abs = os.path.abspath(h)
            rutas.add(os.path.join(h_abs, "Descargas"))
            rutas.add(os.path.join(h_abs, "Downloads"))

    normalizadas = set()
    for r in rutas:
        try:
            norm = os.path.normcase(os.path.abspath(r))
            normalizadas.add(norm)
        except Exception:
            pass

    return normalizadas


def es_ruta_prohibida(ruta: Any) -> Tuple[bool, str]:
    """Determina si una ruta apunta a una ubicación prohibida del sistema real."""
    if ruta is None or isinstance(ruta, int):
        return False, ""
    try:
        if isinstance(ruta, bytes):
            s = ruta.decode("utf-8", errors="replace")
        elif hasattr(ruta, "__fspath__"):
            s = str(ruta.__fspath__())
        else:
            s = str(ruta)

        abs_p = os.path.abspath(os.path.expanduser(s))
        norm_p = os.path.normcase(abs_p)

        for prohibida in _RUTAS_PROHIBIDAS:
            if norm_p == prohibida or norm_p.startswith(prohibida + os.sep) or norm_p.startswith(prohibida + "/"):
                return True, s
    except Exception:
        pass
    return False, ""


def _hermetic_open(file, *args, **kwargs):
    prohibida, ruta_detectada = es_ruta_prohibida(file)
    if prohibida:
        raise AssertionError(
            f"Violación de hermeticidad en tests: open() sobre ruta prohibida del sistema real: '{ruta_detectada}'"
        )
    return _ORIGINAL_OPEN(file, *args, **kwargs)


def _hermetic_io_open(file, *args, **kwargs):
    prohibida, ruta_detectada = es_ruta_prohibida(file)
    if prohibida:
        raise AssertionError(
            f"Violación de hermeticidad en tests: io.open() sobre ruta prohibida del sistema real: '{ruta_detectada}'"
        )
    return _ORIGINAL_IO_OPEN(file, *args, **kwargs)


def _hermetic_listdir(path=None):
    p = path if path is not None else "."
    prohibida, ruta_detectada = es_ruta_prohibida(p)
    if prohibida:
        raise AssertionError(
            f"Violación de hermeticidad en tests: os.listdir() sobre ruta prohibida del sistema real: '{ruta_detectada}'"
        )
    return _ORIGINAL_LISTDIR(path) if path is not None else _ORIGINAL_LISTDIR()


def _hermetic_scandir(path=None):
    p = path if path is not None else "."
    prohibida, ruta_detectada = es_ruta_prohibida(p)
    if prohibida:
        raise AssertionError(
            f"Violación de hermeticidad en tests: os.scandir() sobre ruta prohibida del sistema real: '{ruta_detectada}'"
        )
    return _ORIGINAL_SCANDIR(path) if path is not None else _ORIGINAL_SCANDIR()


def _hermetic_walk(top, *args, **kwargs):
    prohibida, ruta_detectada = es_ruta_prohibida(top)
    if prohibida:
        raise AssertionError(
            f"Violación de hermeticidad en tests: os.walk() sobre ruta prohibida del sistema real: '{ruta_detectada}'"
        )
    return _ORIGINAL_WALK(top, *args, **kwargs)


def activar_guardia():
    """Activa el entorno hermético y todos los interceptores de aislamiento."""
    global _GUARDIA_ACTIVADA, _TMP_HOME_DIR, _RUTAS_PROHIBIDAS

    if _GUARDIA_ACTIVADA:
        return

    # 1. Resolver rutas prohibidas antes de alterar el HOME
    _RUTAS_PROHIBIDAS = _resolver_rutas_reales()

    # 2. Configurar HOME temporal y variables XDG
    _TMP_HOME_DIR = tempfile.mkdtemp(prefix="lucie_hermetico_home_")
    tmp_descargas = os.path.join(_TMP_HOME_DIR, "Descargas")
    os.makedirs(tmp_descargas, exist_ok=True)
    os.makedirs(os.path.join(tmp_descargas, "_lucie"), exist_ok=True)

    os.environ["HOME"] = _TMP_HOME_DIR
    os.environ["USERPROFILE"] = _TMP_HOME_DIR
    os.environ["HOMEDRIVE"] = ""
    os.environ["HOMEPATH"] = _TMP_HOME_DIR
    os.environ["XDG_DATA_HOME"] = os.path.join(_TMP_HOME_DIR, ".local", "share")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(_TMP_HOME_DIR, ".config")
    os.environ["XDG_CACHE_HOME"] = os.path.join(_TMP_HOME_DIR, ".cache")
    os.environ["XDG_DOWNLOAD_DIR"] = tmp_descargas

    # 3. Interceptar funciones de I/O y recorrido de directorios
    builtins.open = _hermetic_open
    io.open = _hermetic_io_open
    os.listdir = _hermetic_listdir
    os.scandir = _hermetic_scandir
    os.walk = _hermetic_walk

    # 4. Neutralizar autodetección de unidades de almacenamiento reales en el paquete bandeja
    try:
        import bandeja.plataforma
        import bandeja.pendrive
        import bandeja

        def _buscar_candidatos_hermetico(config=None, rutas_candidatas=None):
            rutas_cfg = getattr(config, "rutas_candidatas_pendrive", None) or rutas_candidatas
            if rutas_cfg:
                candidatos = []
                for r in rutas_cfg:
                    if r and os.path.isdir(r):
                        candidatos.append(os.path.realpath(r))
                return list(dict.fromkeys(candidatos))
            if os.name == "nt":
                candidatos = []
                try:
                    for u_info in bandeja.plataforma.obtener_unidades_windows():
                        raiz_u = u_info.get("unidad", "")
                        if raiz_u and os.path.isdir(raiz_u):
                            candidatos.append(os.path.realpath(raiz_u))
                except Exception:
                    pass
                return list(dict.fromkeys(candidatos))
            return []

        bandeja.plataforma.buscar_puntos_montaje_candidatos = _buscar_candidatos_hermetico
        bandeja.pendrive.buscar_puntos_montaje_candidatos = _buscar_candidatos_hermetico
        bandeja.buscar_puntos_montaje_candidatos = _buscar_candidatos_hermetico

        _orig_detectar_particiones = bandeja.plataforma.detectar_particiones_removibles_linux

        def _detectar_particiones_hermetico(sys_dir="/sys", proc_dir="/proc", dev_dir="/dev", udev_dir="/run/udev/data"):
            if sys_dir == "/sys":
                return []
            return _orig_detectar_particiones(sys_dir=sys_dir, proc_dir=proc_dir, dev_dir=dev_dir, udev_dir=udev_dir)

        bandeja.plataforma.detectar_particiones_removibles_linux = _detectar_particiones_hermetico
        bandeja.pendrive.detectar_particiones_removibles_linux = _detectar_particiones_hermetico
        bandeja.detectar_particiones_removibles_linux = _detectar_particiones_hermetico
    except ImportError:
        pass

    # 5. Neutralizar la base SQLite real y bitácora por defecto
    try:
        import bandeja.db
        import bandeja.movimientos
        import bandeja.servidor
        import bandeja.config

        bandeja.config.RUTA_DESCARGAS_DEFECTO = tmp_descargas
        bandeja.config.RUTA_DESTINO_DEFECTO = os.path.join(tmp_descargas, "_lucie")

        _orig_db_init = bandeja.db.GestorBaseDatosBandeja.__init__

        def _hermetic_db_init(self, ruta_db=".cache/inventario_pendrive_cache.sqlite", *args, **kwargs):
            if ruta_db in (".cache/inventario_pendrive_cache.sqlite", os.path.join(".cache", "inventario_pendrive_cache.sqlite")):
                ruta_db = os.path.join(_TMP_HOME_DIR, "inventario_pendrive_cache.sqlite")
            return _orig_db_init(self, ruta_db, *args, **kwargs)

        bandeja.db.GestorBaseDatosBandeja.__init__ = _hermetic_db_init

        _orig_mov_init = bandeja.movimientos.GestorMovimientosBandeja.__init__

        def _hermetic_mov_init(self, ruta_descargas, ruta_destino_base, db, ruta_bitacora="bitacora_bandeja.jsonl", *args, **kwargs):
            if ruta_bitacora == "bitacora_bandeja.jsonl":
                ruta_bitacora = os.path.join(_TMP_HOME_DIR, "bitacora_bandeja.jsonl")
            return _orig_mov_init(self, ruta_descargas, ruta_destino_base, db, ruta_bitacora, *args, **kwargs)

        bandeja.movimientos.GestorMovimientosBandeja.__init__ = _hermetic_mov_init

        _orig_mini_init = bandeja.servidor.GeneradorMiniaturas.__init__

        def _hermetic_mini_init(self, db, ruta_cache_miniaturas=".cache/miniaturas_bandeja", *args, **kwargs):
            if ruta_cache_miniaturas == ".cache/miniaturas_bandeja":
                ruta_cache_miniaturas = os.path.join(_TMP_HOME_DIR, "miniaturas_bandeja")
            return _orig_mini_init(self, db, ruta_cache_miniaturas, *args, **kwargs)

        bandeja.servidor.GeneradorMiniaturas.__init__ = _hermetic_mini_init
    except ImportError:
        pass

    _GUARDIA_ACTIVADA = True


# Activar automáticamente al importar para proteger la suite en cualquier punto
activar_guardia()
