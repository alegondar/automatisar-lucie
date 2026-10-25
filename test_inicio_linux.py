"""Inicio/icono con callbacks falsos y archivos temporales; nunca vigilantes reales."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


@unittest.skipUnless(sys.platform.startswith("linux"), "Requiere Linux/XDG y flock.")
class TestInicioLinux(unittest.TestCase):
    def test_simular_no_escribe_instala_idempotente_y_conserva_ajeno(self):
        from instalar_inicio_linux import simular, instalar
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "autostart"
            plan = simular(destino)
            self.assertFalse(destino.exists())
            self.assertTrue(instalar(plan))
            acceso = Path(plan["destino"])
            original = acceso.read_bytes()
            self.assertFalse(instalar(simular(destino)))
            self.assertEqual(acceso.read_bytes(), original)
            acceso.write_text("acceso ajeno", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                simular(destino)
            self.assertEqual(acceso.read_text(), "acceso ajeno")

    def test_cambio_entre_simular_e_instalar_conserva_destino(self):
        from instalar_inicio_linux import simular, instalar
        with tempfile.TemporaryDirectory() as carpeta:
            plan = simular(carpeta)
            Path(plan["destino"]).write_text("nuevo acceso ajeno")
            with self.assertRaises(FileExistsError):
                instalar(plan)
            self.assertEqual(Path(plan["destino"]).read_text(), "nuevo acceso ajeno")

    def test_rechaza_enlaces_y_rutas_con_saltos(self):
        from instalar_inicio_linux import simular, _argumento
        with tempfile.TemporaryDirectory() as carpeta:
            enlace = Path(carpeta) / "autostart"
            enlace.symlink_to(carpeta, target_is_directory=True)
            with self.assertRaises(ValueError):
                simular(enlace)
            with self.assertRaises(ValueError):
                _argumento("ruta\nExec=otro")

    def test_xdg_config_home_y_python_sin_modificar_config(self):
        from instalar_inicio_linux import simular
        with tempfile.TemporaryDirectory() as carpeta, patch.dict(os.environ, {"XDG_CONFIG_HOME": carpeta}):
            plan = simular()
            self.assertEqual(Path(plan["destino"]).parent, Path(carpeta) / "autostart")
            self.assertFalse(Path(plan["destino"]).exists())
            self.assertIn("--sin-navegador", plan["contenido"])

    def test_desktop_exec_preserva_argumentos_especiales_sin_shell(self):
        from instalar_inicio_linux import simular, instalar
        try:
            import gi
            from gi.repository import Gio
        except ImportError:
            self.skipTest("No está disponible PyGObject/Gio para interpretar Desktop Entry nativo.")
        with tempfile.TemporaryDirectory(prefix='lucie $ ` % " \\ ') as carpeta:
            raiz = Path(carpeta)
            script = raiz / "iniciar_bandeja_linux.py"
            resultado = raiz / "argumentos.json"
            # Reemplazo sintético del lanzador, sin importar la aplicación real.
            script.write_text("import sys,json\nfrom pathlib import Path\n"
                              "Path(__file__).with_name('argumentos.json').write_text(json.dumps(sys.argv))\n")
            plan = simular(raiz / "inicio", proyecto=raiz)
            instalar(plan)
            if shutil.which("desktop-file-validate"):
                validado = subprocess.run(["desktop-file-validate", plan["destino"]], capture_output=True, text=True)
                self.assertEqual(validado.returncode, 0, validado.stderr)
            app = Gio.DesktopAppInfo.new_from_filename(plan["destino"])
            self.assertIsNotNone(app)
            self.assertTrue(app.launch([], None))
            import time
            limite = time.monotonic() + 5
            while not resultado.exists() and time.monotonic() < limite:
                time.sleep(0.02)
            self.assertEqual(json.loads(resultado.read_text()), [str(script), "--sin-navegador"])

    def test_lock_unico_se_libera_sin_borrar_archivo(self):
        from bandeja.icono_linux import IconoLinux
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = str(Path(carpeta) / "lucie.lock")
            uno, dos = (IconoLinux(54321, lambda: None, ruta_lock=ruta) for _ in range(2))
            try:
                self.assertTrue(uno.adquirir_instancia())
                self.assertFalse(dos.adquirir_instancia())
                inode = os.stat(ruta).st_ino
                uno.detener()
                self.assertTrue(dos.adquirir_instancia())
                self.assertEqual(os.stat(ruta).st_ino, inode)
            finally:
                uno.detener()
                dos.detener()

    def test_lock_rechaza_enlace(self):
        from bandeja.icono_linux import IconoLinux
        with tempfile.TemporaryDirectory() as carpeta:
            real = Path(carpeta) / "ajeno"
            real.write_bytes(b"intacto")
            enlace = Path(carpeta) / "lock"
            enlace.symlink_to(real)
            with self.assertRaises(OSError):
                IconoLinux(54321, lambda: None, ruta_lock=str(enlace)).adquirir_instancia()
            self.assertEqual(real.read_bytes(), b"intacto")

    def test_falta_sesion_grafica_falla_antes_de_iniciar_servicio(self):
        from bandeja.icono_linux import IconoLinux
        with patch.dict(os.environ, {"DISPLAY": ""}):
            icono = IconoLinux(54321, lambda: None)
            with self.assertRaisesRegex(OSError, "sesión gráfica"):
                icono.iniciar()
            icono.detener()

    def test_lanzador_fija_cwd_argumentos_log_append_y_restaura(self):
        import bandeja_descargas
        import iniciar_bandeja_linux
        with tempfile.TemporaryDirectory() as carpeta:
            anterior = os.getcwd()
            argumentos = ["lanzador", "--sin-navegador"]
            def comprobar():
                self.assertEqual(sys.argv[1:], ["--icono", "--sin-navegador"])
                self.assertEqual(os.getcwd(), str(Path(iniciar_bandeja_linux.__file__).parent))
                print("arranque sintético")
            with patch.dict(os.environ, {"XDG_STATE_HOME": carpeta}), patch.object(sys, "argv", argumentos), \
                    patch.object(bandeja_descargas, "main", side_effect=comprobar):
                self.assertEqual(iniciar_bandeja_linux.main(), 0)
                self.assertEqual(iniciar_bandeja_linux.main(), 0)
                self.assertIs(sys.argv, argumentos)
            self.assertEqual(os.getcwd(), anterior)
            log = Path(carpeta) / "lucie/logs/bandeja_linux.log"
            self.assertEqual(log.read_text(), "arranque sintético\n" * 2)

    def test_lanzador_preserva_diagnostico_del_error(self):
        import bandeja_descargas
        import iniciar_bandeja_linux
        with tempfile.TemporaryDirectory() as carpeta, patch.dict(os.environ, {"XDG_STATE_HOME": carpeta}), \
                patch.object(bandeja_descargas, "main", side_effect=OSError("fallo sintético")):
            self.assertEqual(iniciar_bandeja_linux.main(), 1)
            self.assertIn("fallo sintético", (Path(carpeta) / "lucie/logs/bandeja_linux.log").read_text())

    def test_icono_adjunto_no_crea_otro_servicio(self):
        import bandeja_descargas
        with patch.object(sys, "argv", ["bandeja", "--icono", "--sin-navegador"]), \
                patch.object(bandeja_descargas, "crear_icono_bandeja") as crear, \
                patch.object(bandeja_descargas, "dashboard_disponible", return_value=True), \
                patch.object(bandeja_descargas, "ejecutar_bandeja") as servicio:
            crear.return_value.adquirir_instancia.return_value = True
            bandeja_descargas.main()
            servicio.assert_not_called()
            crear.return_value.iniciar.assert_called_once()
            crear.return_value.esperar.assert_called_once()
            crear.return_value.detener.assert_called_once()

    def test_icono_nativo_gtk_con_callbacks_falsos_en_xvfb(self):
        if not shutil.which("xvfb-run"):
            self.skipTest("No está disponible Xvfb para aislar las pruebas GTK.")
        try:
            import gi
            gi.require_version("Gtk", "3.0")
        except (ImportError, ValueError):
            self.skipTest("No están disponibles GTK3/PyGObject.")
        codigo = '''
import os, tempfile, threading
import guardia_hermetica
guardia_hermetica.activar_guardia()
from bandeja.icono_linux import IconoLinux
from gi.repository import GLib
os.environ['XDG_SESSION_TYPE']='x11'
with tempfile.TemporaryDirectory() as carpeta:
    abierto, salido = threading.Event(), threading.Event()
    icono=IconoLinux(54321, abierto.set, ruta_lock=carpeta+'/icono.lock')
    icono.al_salir=salido.set
    try:
        assert icono.adquirir_instancia()
        icono.iniciar()
        assert icono._icono.get_visible()
        assert icono._icono.get_pixbuf().get_width()==32
        def probar():
            items=icono._menu.get_children()
            assert [i.get_label() for i in items]==['Abrir panel de Lucie','Salir de Lucie']
            icono._icono.emit('activate')
            return False
        GLib.idle_add(probar)
        assert abierto.wait(3)
        GLib.idle_add(lambda: (icono._menu.get_children()[1].activate(),False)[1])
        assert salido.wait(3)
        icono._hilo.join(3)
        assert not icono._hilo.is_alive()
        assert not icono._icono.get_visible()
    finally: icono.detener()
print('GTK nativo OK, sin vigilantes')
'''
        resultado = subprocess.run(["xvfb-run", "-a", sys.executable, "-c", codigo],
                                   capture_output=True, text=True, timeout=20)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("GTK nativo OK", resultado.stdout)


if __name__ == "__main__":
    unittest.main()
