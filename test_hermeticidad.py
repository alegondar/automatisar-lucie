#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_hermeticidad.py

Suite de pruebas de hermeticidad y aislamiento del entorno:
1. Verifica que la guardia de hermeticidad bloquee accesos a /media, /run/media, /mnt y ~/Descargas real.
2. Verifica que las variables HOME y XDG apunten a directorios temporales aislados.
3. Verifica que la suite opere sin ver ningún pendrive real ni pendrive falso simulado en /media.
4. Verifica que la base SQLite de caché y la bitácora por defecto no ensucien el repositorio.
"""

import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import guardia_hermetica
from bandeja.config import ConfiguracionBandeja
from bandeja.db import GestorBaseDatosBandeja
from bandeja.movimientos import GestorMovimientosBandeja
from bandeja.pendrive import (
    buscar_puntos_montaje_candidatos,
    detectar_pendrive,
    detectar_unidad_candidata_sin_vincular,
    obtener_estado_pendrive,
)
from bandeja.plataforma import (
    obtener_ruta_descargas_defecto,
    obtener_ruta_descargas_windows,
)


def setUpModule():
    guardia_hermetica.activar_guardia()


class TestGuardiaHermetica(unittest.TestCase):
    """Verifica que los interceptores de guardia_hermetica hagan fallar accesos al entorno real."""

    def test_open_bloqueado_en_rutas_prohibidas(self):
        """open() e io.open() deben lanzar AssertionError al intentar acceder a rutas del host."""
        rutas_prohibidas = [
            "/media/test_archivo.txt",
            "/run/media/usuario/MIUNIDAD/test.txt",
            "/mnt/disco_externo/datos.bin",
        ]
        for ruta in rutas_prohibidas:
            with self.subTest(ruta=ruta):
                with self.assertRaises(AssertionError) as cm:
                    open(ruta, "r")
                self.assertIn("Violación de hermeticidad en tests", str(cm.exception))

    def test_exploracion_directorios_bloqueada_en_rutas_prohibidas(self):
        """os.listdir, os.scandir y os.walk deben lanzar AssertionError en rutas prohibidas."""
        rutas_prohibidas = ["/media", "/run/media", "/mnt"]
        for ruta in rutas_prohibidas:
            with self.subTest(operacion="listdir", ruta=ruta):
                with self.assertRaises(AssertionError) as cm:
                    os.listdir(ruta)
                self.assertIn("os.listdir() sobre ruta prohibida", str(cm.exception))

            with self.subTest(operacion="scandir", ruta=ruta):
                with self.assertRaises(AssertionError) as cm:
                    os.scandir(ruta)
                self.assertIn("os.scandir() sobre ruta prohibida", str(cm.exception))

            with self.subTest(operacion="walk", ruta=ruta):
                with self.assertRaises(AssertionError) as cm:
                    next(os.walk(ruta))
                self.assertIn("os.walk() sobre ruta prohibida", str(cm.exception))

    def test_home_y_xdg_apuntan_a_directorio_temporal(self):
        """HOME y XDG deben apuntar a directorios temporales y Descargas por defecto debe ser hermético."""
        home_actual = os.environ.get("HOME", "")
        self.assertTrue(home_actual.startswith("/tmp") or "temp" in home_actual.lower() or "lucie_hermetico" in home_actual.lower(), f"HOME no es temporal: {home_actual}")
        self.assertFalse(home_actual.startswith("/home/"), f"HOME apunta al usuario real: {home_actual}")
        if os.name == "nt":
            perfil_win = guardia_hermetica.obtener_perfil_real()
            if perfil_win:
                self.assertFalse(home_actual.lower() == perfil_win.lower(), f"HOME apunta al perfil real de Windows: {home_actual}")

        ruta_descargas = obtener_ruta_descargas_defecto()
        self.assertTrue(ruta_descargas.startswith(home_actual) or "temp" in ruta_descargas.lower() or "lucie_hermetico" in ruta_descargas.lower(), f"Descargas por defecto fuera de HOME temporal: {ruta_descargas}")
        self.assertFalse(ruta_descargas.startswith("/home/"), f"Descargas por defecto apunta a Descargas real: {ruta_descargas}")
        if os.name == "nt":
            dl_real_win = guardia_hermetica.obtener_ruta_descargas_real()
            if dl_real_win:
                self.assertFalse(ruta_descargas.lower() == dl_real_win.lower(), f"Descargas apunta a Descargas real de Windows: {ruta_descargas}")

    def test_variables_entorno_windows_redirigidas_a_temporal(self):
        """USERPROFILE, HOMEDRIVE, HOMEPATH, APPDATA, LOCALAPPDATA y TEMP deben apuntar a directorio temporal."""
        if os.name != "nt":
            return

        perfil_win = guardia_hermetica.obtener_perfil_real()

        userprofile = os.environ.get("USERPROFILE", "")
        self.assertTrue(userprofile, "USERPROFILE no está configurado")
        if perfil_win:
            self.assertFalse(userprofile.lower() == perfil_win.lower(), f"USERPROFILE apunta al usuario real: {userprofile}")
        self.assertTrue("temp" in userprofile.lower() or "lucie_hermetico" in userprofile.lower(), f"USERPROFILE no es temporal: {userprofile}")

        appdata = os.environ.get("APPDATA", "")
        self.assertTrue("AppData" in appdata and ("temp" in appdata.lower() or "lucie_hermetico" in appdata.lower()), f"APPDATA no es temporal: {appdata}")

        localappdata = os.environ.get("LOCALAPPDATA", "")
        self.assertTrue("AppData" in localappdata and ("temp" in localappdata.lower() or "lucie_hermetico" in localappdata.lower()), f"LOCALAPPDATA no es temporal: {localappdata}")

        temp_env = os.environ.get("TEMP", "")
        self.assertTrue("Temp" in temp_env and ("temp" in temp_env.lower() or "lucie_hermetico" in temp_env.lower()), f"TEMP no es temporal: {temp_env}")

    def test_acceso_bloqueado_a_descargas_real_y_unidades_externas_windows(self):
        """Verifica que abrir, listar o recorrer Downloads real o unidades externas lance AssertionError en Windows."""
        if os.name != "nt":
            return

        dl_real = guardia_hermetica.obtener_ruta_descargas_real() or obtener_ruta_descargas_windows()
        if guardia_hermetica.es_ruta_prohibida(dl_real)[0]:
            with self.assertRaises(AssertionError) as cm:
                open(os.path.join(dl_real, "archivo_prohibido.txt"), "r")
            self.assertIn("Violación de hermeticidad", str(cm.exception))

            with self.assertRaises(AssertionError) as cm:
                os.listdir(dl_real)
            self.assertIn("os.listdir() sobre ruta prohibida", str(cm.exception))

            with self.assertRaises(AssertionError) as cm:
                next(os.walk(dl_real))
            self.assertIn("os.walk() sobre ruta prohibida", str(cm.exception))

        # Verificar unidades removibles o externas registradas en la guardia
        unidades_externas = [
            r for r in guardia_hermetica._RUTAS_PROHIBIDAS
            if len(r) <= 3 and ":" in r
        ]
        for u in unidades_externas:
            with self.subTest(unidad=u):
                with self.assertRaises(AssertionError) as cm:
                    open(os.path.join(u, "test.txt"), "r")
                self.assertIn("Violación de hermeticidad", str(cm.exception))

                with self.assertRaises(AssertionError) as cm:
                    os.listdir(u)
                self.assertIn("os.listdir() sobre ruta prohibida", str(cm.exception))

                with self.assertRaises(AssertionError) as cm:
                    next(os.walk(u))
                self.assertIn("os.walk() sobre ruta prohibida", str(cm.exception))


class TestAislamientoPendriveFalso(unittest.TestCase):
    """
    Paso 4: Verificación con un 'pendrive falso' en ruta simulada de /media.
    Confirma que ningún test ni componente de la suite lo ve por defecto.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_pendrive_falso_")
        self.ruta_pendrive_simulada = "/media/usuario/PENDRIVE_FALSO"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_buscar_candidatos_no_ve_pendrive_falso_en_media(self):
        """buscar_puntos_montaje_candidatos() devuelve lista vacía y no inspecciona /media."""
        candidatos = buscar_puntos_montaje_candidatos()
        self.assertEqual(candidatos, [])

        # Con configuración por defecto (sin rutas explícitas) tampoco debe ver nada
        cfg_defecto = ConfiguracionBandeja()
        candidatos_cfg = buscar_puntos_montaje_candidatos(cfg_defecto)
        self.assertEqual(candidatos_cfg, [])

    def test_detectar_pendrive_no_ve_pendrive_en_media(self):
        """detectar_pendrive() y detectar_unidad_candidata_sin_vincular() no detectan unidades en /media."""
        pen = detectar_pendrive()
        self.assertIsNone(pen)

        cand = detectar_unidad_candidata_sin_vincular()
        self.assertIsNone(cand)

        # Estado reporta desconectado
        cfg = ConfiguracionBandeja()
        db = GestorBaseDatosBandeja(os.path.join(self.tmp_dir, "test.db"))
        estado = obtener_estado_pendrive(cfg, db)
        self.assertFalse(estado.get("conectado"))
        self.assertIsNone(estado.get("punto_montaje"))

    def test_guardia_bloquea_intento_de_leer_pendrive_falso_en_media(self):
        """Cualquier componente que intente leer el pendrive simulado bajo /media es interceptado."""
        with self.assertRaises(AssertionError) as cm:
            open(f"{self.ruta_pendrive_simulada}/.lucie_pendrive.json", "r")
        self.assertIn("Violación de hermeticidad en tests", str(cm.exception))

    def test_plan_limpieza_cli_hermetico_con_pendrive_simulado_en_tmp(self):
        """plan_limpieza.main() opera herméticamente sobre directorios temporales."""
        import plan_limpieza

        tmp_pen = os.path.join(self.tmp_dir, "pendrive")
        tmp_repo = os.path.join(self.tmp_dir, "repo")
        os.makedirs(tmp_pen, exist_ok=True)
        os.makedirs(tmp_repo, exist_ok=True)

        config_path = os.path.join(tmp_repo, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

        stdout_cap = io.StringIO()
        stderr_cap = io.StringIO()
        with patch("sys.argv", [
            "plan_limpieza.py",
            "--raiz", tmp_pen,
            "--cache", os.path.join(tmp_repo, "cache.sqlite"),
            "--config", config_path,
            "--validar-huella",
            "--salida-json", "/no/existe/plan.json"
        ]):
            with patch("sys.stdout", stdout_cap):
                with patch("sys.stderr", stderr_cap):
                    with self.assertRaises(SystemExit) as cm:
                        plan_limpieza.main()
                    self.assertEqual(cm.exception.code, 1)


class TestAislamientoArchivosProyecto(unittest.TestCase):
    """Verifica que las instancias por defecto no modifiquen la bitácora ni la caché del repo."""

    def test_instancias_por_defecto_no_tocan_archivos_del_repositorio(self):
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        bitacora_repo = os.path.join(repo_dir, "bitacora_bandeja.jsonl")
        mtime_bitacora_antes = os.path.getmtime(bitacora_repo) if os.path.exists(bitacora_repo) else None

        # Instanciar GestorBaseDatosBandeja y GestorMovimientosBandeja con valores por defecto
        with tempfile.TemporaryDirectory() as tmp_esc:
            desc = os.path.join(tmp_esc, "desc")
            dest = os.path.join(tmp_esc, "dest")
            os.makedirs(desc, exist_ok=True)
            os.makedirs(dest, exist_ok=True)

            db = GestorBaseDatosBandeja()
            # La ruta de db debe estar en un directorio temporal
            self.assertTrue(db.ruta_db.startswith("/tmp") or "temp" in db.ruta_db.lower() or "lucie_hermetico" in db.ruta_db.lower(), f"DB por defecto no es temporal: {db.ruta_db}")

            mov = GestorMovimientosBandeja(desc, dest, db)
            # La ruta de bitácora debe estar en un directorio temporal
            self.assertTrue(mov.ruta_bitacora.startswith("/tmp") or "temp" in mov.ruta_bitacora.lower() or "lucie_hermetico" in mov.ruta_bitacora.lower(), f"Bitácora por defecto no es temporal: {mov.ruta_bitacora}")

        if mtime_bitacora_antes is not None and os.path.exists(bitacora_repo):
            self.assertEqual(os.path.getmtime(bitacora_repo), mtime_bitacora_antes, "bitacora_bandeja.jsonl fue modificada")


class TestAuditoriaEstaticaHermeticidad(unittest.TestCase):
    """Audita estáticamente que el código operativo y los tests cumplan los estándares de hermeticidad."""

    def test_archivos_operativos_no_contienen_rutas_de_usuario(self):
        """Verifica que ningún archivo .py operativo contenga identificadores de usuario ni rutas personales absolutas."""
        from seguridad_anti_borrado import descubrir_archivos_operativos
        import re

        repo_dir = os.path.dirname(os.path.abspath(__file__))
        archivos = descubrir_archivos_operativos(repo_dir)
        patron_ruta_personal = re.compile(
            r"(?:/home/|/run/media/)(?!<usuario>|<user>|<punto-de-montaje>|usuario|user|test|\.\.\.)[a-zA-Z0-9_-]+"
        )
        usuario_prohibido = "".join(["dark", "sun"])

        infracciones = []
        for arch in archivos:
            with open(arch, "r", encoding="utf-8", errors="ignore") as f:
                for num_linea, linea in enumerate(f, 1):
                    if usuario_prohibido in linea.lower():
                        infracciones.append(f"{os.path.basename(arch)}:{num_linea} contiene identificador de usuario prohibido")
                    m = patron_ruta_personal.search(linea)
                    if m:
                        infracciones.append(f"{os.path.basename(arch)}:{num_linea} contiene ruta personal '{m.group(0)}'")

        self.assertEqual(
            infracciones, [],
            f"Se encontraron rutas de usuario o datos personales en archivos operativos:\n" + "\n".join(infracciones)
        )

    def test_archivos_test_no_contienen_rutas_de_usuario(self):
        """Verifica que ningún archivo test_*.py contenga rutas de usuario en Windows o Linux no exceptuadas."""
        import re

        repo_dir = os.path.dirname(os.path.abspath(__file__))
        archivos_test = [
            os.path.join(repo_dir, f) for f in os.listdir(repo_dir)
            if f.startswith("test_") and f.endswith(".py")
        ]
        patron_win = re.compile(r"[A-Za-z]:(?:\\\\|/|\\)Users(?:\\\\|/|\\)([a-zA-Z0-9_<>-]+)", re.IGNORECASE)
        patron_posix = re.compile(r"/home/([a-zA-Z0-9_<>-]+)", re.IGNORECASE)
        excepciones = {"public", "default", "<usuario>", "<user>", "usuario", "user", "test", "...", "<punto-de-montaje>", "<nombre>", "nombre"}
        usuario_prohibido = "".join(["dark", "sun"])

        infracciones = []
        for arch in archivos_test:
            with open(arch, "r", encoding="utf-8", errors="ignore") as f:
                for num_linea, linea in enumerate(f, 1):
                    if usuario_prohibido in linea.lower():
                        infracciones.append(f"{os.path.basename(arch)}:{num_linea} contiene identificador de usuario prohibido")
                    for m in patron_win.finditer(linea):
                        if m.group(1).lower() not in excepciones:
                            infracciones.append(f"{os.path.basename(arch)}:{num_linea} contiene ruta de usuario Windows '{m.group(0)}'")
                    for m in patron_posix.finditer(linea):
                        if m.group(1).lower() not in excepciones:
                            infracciones.append(f"{os.path.basename(arch)}:{num_linea} contiene ruta de usuario Linux '{m.group(0)}'")

        self.assertEqual(
            infracciones, [],
            f"Se encontraron rutas de usuario en archivos de test:\n" + "\n".join(infracciones)
        )

    def test_guardia_hermetica_usada_en_todos_los_archivos_de_test(self):
        """Verifica que todo test_*.py defina setUpModule() y active guardia_hermetica."""
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        archivos_test = [
            f for f in os.listdir(repo_dir)
            if f.startswith("test_") and f.endswith(".py")
        ]
        self.assertTrue(len(archivos_test) >= 6, "No se encontraron suficientes archivos de tests")

        faltantes = []
        for arch in sorted(archivos_test):
            ruta_completa = os.path.join(repo_dir, arch)
            with open(ruta_completa, "r", encoding="utf-8", errors="ignore") as f:
                contenido = f.read()

            tiene_import = "guardia_hermetica" in contenido
            tiene_setup = "def setUpModule(" in contenido
            tiene_activar = "guardia_hermetica.activar_guardia()" in contenido

            if not (tiene_import and tiene_setup and tiene_activar):
                faltantes.append(arch)

        self.assertEqual(
            faltantes, [],
            f"Los siguientes archivos de test no utilizan la guardia de hermeticidad (setUpModule + activar_guardia):\n"
            + "\n".join(faltantes)
        )


if __name__ == "__main__":
    unittest.main()

