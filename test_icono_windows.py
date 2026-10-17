"""Icono con callbacks falsos, shortcut y logs en temporales; nunca iniciar vigilantes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from bandeja.icono_windows import IconoWindows, WM_ICONO, WM_COMMAND, WM_LBUTTONUP


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


@unittest.skipUnless(sys.platform == "win32", "Requiere API nativa de iconos y accesos directos de Windows.")
class TestIconoWindows(unittest.TestCase):
    def crear_icono(self, abrir=lambda: None, nombre=None):
        icono = IconoWindows(54321, abrir)
        icono._nombre_mutex = nombre or "Local\\LuciePrueba-" + uuid.uuid4().hex
        self.addCleanup(icono.detener)
        return icono

    def test_mutex_impide_dos_iconos_y_se_libera_al_cerrar(self):
        primero = self.crear_icono()
        segundo = self.crear_icono(nombre=primero._nombre_mutex)
        self.assertTrue(primero.adquirir_instancia())
        self.assertFalse(segundo.adquirir_instancia())
        segundo.detener()
        self.assertFalse(segundo.adquirir_instancia())
        primero.detener()
        self.assertTrue(segundo.adquirir_instancia())

    def test_icono_nativo_clic_menu_y_salida_sin_archivos(self):
        abierto, salido = threading.Event(), threading.Event()
        icono = self.crear_icono(abierto.set)
        self.assertTrue(icono.adquirir_instancia())
        icono.al_salir = salido.set
        icono.iniciar()
        self.assertIsNone(icono._error)
        self.assertTrue(icono.hwnd)
        self.assertTrue(icono._hicon)
        icono.user.PostMessageW(icono.hwnd, WM_ICONO, 1, WM_LBUTTONUP)
        self.assertTrue(abierto.wait(3), "Un clic debe abrir el panel")
        icono.user.PostMessageW(icono.hwnd, WM_COMMAND, 2, 0)
        self.assertTrue(salido.wait(3), "Salir debe avisar al servicio dueño")
        icono._hilo.join(timeout=3)
        self.assertFalse(icono._hilo.is_alive())
        self.assertIsNone(icono._hicon)

    def test_icono_restaurable_tras_mensaje_taskbarcreated(self):
        icono = self.crear_icono()
        icono.iniciar()
        self.assertTrue(icono._notificar(2))  # Simular pérdida de nuestro propio icono.
        restaurado = threading.Event()
        notificar = icono._notificar

        def observar(operacion):
            resultado = notificar(operacion)
            if operacion == 0 and resultado:
                restaurado.set()
            return resultado

        with patch.object(icono, "_notificar", side_effect=observar):
            icono.user.PostMessageW(icono.hwnd, icono._taskbar_creada, 0, 0)
            self.assertTrue(restaurado.wait(3))

    def test_instalador_simula_instala_y_conserva_acceso_ajeno(self):
        instalador = str(Path(__file__).with_name("instalar_inicio_windows.ps1"))
        with tempfile.TemporaryDirectory(prefix="inicio lucie ") as carpeta:
            destino = Path(carpeta) / "Lucie.lnk"

            def ejecutar(*opciones):
                return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    instalador, "-CarpetaInicio", carpeta, *opciones], capture_output=True, text=True)

            self.assertEqual(ejecutar().returncode, 0)
            self.assertFalse(destino.exists())
            resultado = ejecutar("-Instalar")
            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            original = destino.read_bytes()
            self.assertGreater(len(original), 0)
            self.assertEqual(ejecutar("-Instalar").returncode, 0)
            self.assertEqual(destino.read_bytes(), original)
        with tempfile.TemporaryDirectory(prefix="inicio ajeno ") as carpeta:
            destino = Path(carpeta) / "Lucie.lnk"
            destino.write_bytes(b"acceso ajeno que no se debe sobrescribir")
            resultado = ejecutar("-Instalar")
            self.assertNotEqual(resultado.returncode, 0)
            self.assertEqual(destino.read_bytes(), b"acceso ajeno que no se debe sobrescribir")

    def test_lanzador_pythonw_configura_directorio_y_log_append(self):
        import iniciar_bandeja_windows
        import bandeja_descargas
        with tempfile.TemporaryDirectory() as carpeta:
            argumentos = ["lanzador", "--sin-navegador"]
            with patch.dict(os.environ, {"LOCALAPPDATA": carpeta}), patch("sys.argv", argumentos), \
                 patch("iniciar_bandeja_windows.os.chdir") as cambiar, patch.object(bandeja_descargas, "main") as arrancar:
                def comprobar():
                    self.assertEqual(sys.argv[1:], ["--icono", "--sin-navegador"])
                    print("log de arranque")
                arrancar.side_effect = comprobar
                self.assertEqual(iniciar_bandeja_windows.main(), 0)
                self.assertEqual(iniciar_bandeja_windows.main(), 0)
                self.assertEqual(cambiar.call_count, 2)
                self.assertEqual(arrancar.call_count, 2)
            log = Path(carpeta) / "Lucie" / "logs" / "bandeja_windows.log"
            self.assertEqual(log.read_text(encoding="utf-8"), "log de arranque\nlog de arranque\n")

    def test_error_pythonw_informa_y_preserva_diagnostico(self):
        import ctypes
        import iniciar_bandeja_windows
        import bandeja_descargas
        with tempfile.TemporaryDirectory() as carpeta:
            with patch.dict(os.environ, {"LOCALAPPDATA": carpeta}), \
                 patch("iniciar_bandeja_windows.os.chdir"), \
                 patch.object(bandeja_descargas, "main", side_effect=OSError("fallo sintetico")), \
                 patch.object(ctypes.windll.user32, "MessageBoxW") as aviso:
                self.assertEqual(iniciar_bandeja_windows.main(), 1)
                aviso.assert_called_once()
            log = Path(carpeta) / "Lucie" / "logs" / "bandeja_windows.log"
            self.assertIn("fallo sintetico", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
