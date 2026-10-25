"""Chrome: servidores temporales y procesos simulados; nunca abrir navegador real."""
import errno
import os
import tempfile
import threading
import unittest
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bandeja.navegador import abrir_dashboard_chrome, localizar_chrome


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestNavegador(unittest.TestCase):
    def servidor(self, respuestas):
        peticiones = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                peticiones.append(self.path)
                codigo, cuerpo = respuestas[min(len(peticiones) - 1, len(respuestas) - 1)]
                self.send_response(codigo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *args):
                pass

        servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        return servidor.server_port, peticiones

    def test_chrome_linux_se_localiza_en_path(self):
        with patch("bandeja.navegador.sys.platform", "linux"), patch("bandeja.navegador.shutil.which", side_effect=lambda nombre: "chrome-sintetico" if nombre == "google-chrome-stable" else None):
            self.assertEqual(localizar_chrome(), "chrome-sintetico")

    def test_chrome_windows_instalacion_usuario_temporal(self):
        with tempfile.TemporaryDirectory() as base:
            ruta = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            os.makedirs(os.path.dirname(ruta))
            with open(ruta, "xb") as archivo:
                archivo.write(b"ejecutable sintetico, nunca se ejecuta")
            with patch("bandeja.navegador.sys.platform", "win32"), patch.dict(os.environ, {"LOCALAPPDATA": base}, clear=True):
                self.assertEqual(localizar_chrome(), ruta)

    def test_windows_chrome_en_registro_app_paths(self):
        import sys
        registro = Mock(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2)
        registro.OpenKey.return_value.__enter__ = Mock(return_value="clave")
        registro.OpenKey.return_value.__exit__ = Mock(return_value=False)
        registro.QueryValueEx.return_value = ("chrome-sintetico", 1)
        with patch("bandeja.navegador.sys.platform", "win32"), patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"winreg": registro}), patch("bandeja.navegador.os.path.isfile", return_value=True):
            self.assertEqual(localizar_chrome(), "chrome-sintetico")

    def test_espera_dashboard_listo_y_abre_una_sola_pestana_con_puerto_real(self):
        html = b'<title>Lucie Sin Reglas</title><script src="/panel.js"></script>'
        puerto, peticiones = self.servidor([(503, b"iniciando"), (200, html)])
        with patch("bandeja.navegador.localizar_chrome", return_value="chrome-sintetico"), patch("bandeja.navegador.subprocess.Popen") as lanzar:
            self.assertTrue(abrir_dashboard_chrome(puerto, espera=2))
            self.assertEqual(peticiones, ["/panel.html", "/panel.html"])
            lanzar.assert_called_once()
            self.assertEqual(lanzar.call_args.args[0], ["chrome-sintetico", "--new-tab", f"http://127.0.0.1:{puerto}/"])
            self.assertNotIn("shell", lanzar.call_args.kwargs)

    def test_puerto_ocupado_por_otro_servicio_no_abre_chrome(self):
        puerto, _ = self.servidor([(200, b"otro servicio")])
        with patch("bandeja.navegador.localizar_chrome", return_value="chrome-sintetico"), patch("bandeja.navegador.subprocess.Popen") as lanzar:
            self.assertFalse(abrir_dashboard_chrome(puerto, espera=0.1))
            lanzar.assert_not_called()

    def test_sin_chrome_no_hay_procesos_ni_sondeo_y_fallo_al_lanzar_no_corta(self):
        with patch("bandeja.navegador.localizar_chrome", return_value=None), patch("bandeja.navegador.http.client.HTTPConnection") as conectar, patch("bandeja.navegador.subprocess.Popen") as lanzar:
            self.assertFalse(abrir_dashboard_chrome(12345))
            conectar.assert_not_called()
            lanzar.assert_not_called()
        puerto, _ = self.servidor([(200, b'<title>Lucie Sin Reglas</title><script src="/panel.js"></script>')])
        with patch("bandeja.navegador.localizar_chrome", return_value="chrome-sintetico"), patch("bandeja.navegador.subprocess.Popen", side_effect=OSError("lanzamiento rechazado")):
            self.assertFalse(abrir_dashboard_chrome(puerto))

    def contexto_main(self, stack, argumentos, ocupado=False):
        import bandeja_descargas
        config = SimpleNamespace(puerto_servidor=12345, host_servidor="127.0.0.1",
            ruta_descargas="temporal", ruta_destino_base="temporal", ventana_lote_minutos=10,
            subcarpeta_fotos="fotos", subcarpeta_videos="videos")
        stack.enter_context(patch("sys.argv", ["bandeja_descargas.py", *argumentos]))
        stack.enter_context(patch("builtins.print"))
        for nombre in ("GestorBaseDatosBandeja", "FiltroListaBlanca", "DetectorDescargasActivas", "AgrupadorLotes", "GestorMovimientosBandeja", "GeneradorMiniaturas"):
            stack.enter_context(patch.object(bandeja_descargas, nombre))
        stack.enter_context(patch.object(bandeja_descargas, "ConfiguracionBandeja", return_value=config))
        vigilante = stack.enter_context(patch.object(bandeja_descargas, "VigilanteBandeja")).return_value
        capcut = stack.enter_context(patch.object(bandeja_descargas, "crear_vigilante_capcut")).return_value
        servidor = Mock(server_address=("127.0.0.1", 54321))
        servidor.serve_forever.side_effect = KeyboardInterrupt
        stack.enter_context(patch.object(bandeja_descargas, "crear_servidor", return_value=servidor,
            side_effect=OSError(errno.EADDRINUSE, "Address already in use") if ocupado else None))
        hilo = stack.enter_context(patch("bandeja_descargas.threading.Thread"))
        abrir = stack.enter_context(patch.object(bandeja_descargas, "abrir_dashboard_chrome"))
        return bandeja_descargas, vigilante, capcut, servidor, hilo, abrir

    def test_main_abre_chrome_despues_de_crear_servidor_o_respeta_sin_navegador(self):
        for argumentos in ([], ["--sin-navegador"]):
            with self.subTest(argumentos=argumentos), ExitStack() as stack:
                app, vigilante, capcut, servidor, hilo, abrir = self.contexto_main(stack, argumentos)
                app.main()
                vigilante.iniciar.assert_called_once()
                capcut.iniciar.assert_called_once()
                servidor.serve_forever.assert_called_once()
                servidor.server_close.assert_called_once()
                abrir.assert_not_called()
                if argumentos:
                    hilo.assert_not_called()
                else:
                    self.assertEqual(hilo.call_args.kwargs["target"], abrir)
                    self.assertEqual(hilo.call_args.kwargs["args"], (54321,))
                    self.assertTrue(hilo.call_args.kwargs["daemon"])
                    hilo.return_value.start.assert_called_once()

    def test_main_instancia_existente_abre_panel_sin_iniciar_vigilantes(self):
        with ExitStack() as stack:
            app, vigilante, capcut, _, hilo, abrir = self.contexto_main(stack, ["--puerto", "23456"], ocupado=True)
            with self.assertRaises(SystemExit) as salida:
                app.main()
            self.assertEqual(salida.exception.code, 0)
            abrir.assert_called_once_with(23456)
            vigilante.iniciar.assert_not_called()
            capcut.iniciar.assert_not_called()
            hilo.assert_not_called()

    def test_icono_se_conecta_a_panel_existente_sin_base_ni_vigilantes(self):
        with ExitStack() as stack:
            app, vigilante, capcut, servidor, _, abrir = self.contexto_main(stack, ["--icono", "--sin-navegador"])
            stack.enter_context(patch.object(app.sys, "platform", "win32"))
            stack.enter_context(patch.object(app, "dashboard_disponible", return_value=True))
            icono = stack.enter_context(patch("bandeja.icono_windows.IconoWindows")).return_value
            icono.adquirir_instancia.return_value = True
            app.main()
            app.GestorBaseDatosBandeja.assert_not_called()
            vigilante.iniciar.assert_not_called()
            capcut.iniciar.assert_not_called()
            servidor.serve_forever.assert_not_called()
            abrir.assert_not_called()
            icono.iniciar.assert_called_once()
            icono.esperar.assert_called_once()
            icono.detener.assert_called_once()

    def test_icono_duplicado_no_inicia_servicio_ni_otro_icono(self):
        for argumentos in (["--icono"], ["--icono", "--sin-navegador"]):
            with self.subTest(argumentos=argumentos), ExitStack() as stack:
                app, vigilante, capcut, _, _, abrir = self.contexto_main(stack, argumentos)
                stack.enter_context(patch.object(app.sys, "platform", "win32"))
                icono = stack.enter_context(patch("bandeja.icono_windows.IconoWindows")).return_value
                icono.adquirir_instancia.return_value = False
                app.main()
                app.GestorBaseDatosBandeja.assert_not_called()
                vigilante.iniciar.assert_not_called()
                capcut.iniciar.assert_not_called()
                icono.iniciar.assert_not_called()
                icono.detener.assert_called_once()
                self.assertEqual(abrir.call_count, 0 if "--sin-navegador" in argumentos else 1)

    def test_icono_inicia_y_detiene_el_servicio_que_le_pertenece(self):
        with ExitStack() as stack:
            app, vigilante, capcut, servidor, _, abrir = self.contexto_main(stack, ["--icono", "--sin-navegador"])
            stack.enter_context(patch.object(app.sys, "platform", "win32"))
            stack.enter_context(patch.object(app, "dashboard_disponible", return_value=False))
            icono = stack.enter_context(patch("bandeja.icono_windows.IconoWindows")).return_value
            icono.adquirir_instancia.return_value = True
            app.main()
            icono.iniciar.assert_called_once()
            icono.detener.assert_called_once()
            self.assertEqual(icono.al_salir, servidor.shutdown)
            vigilante.iniciar.assert_called_once()
            capcut.iniciar.assert_called_once()
            vigilante.detener.assert_called_once()
            capcut.detener.assert_called_once()
            servidor.server_close.assert_called_once()
            abrir.assert_not_called()

    def test_icono_rechaza_otro_servicio_y_libera_mutex(self):
        with ExitStack() as stack:
            app, vigilante, capcut, _, _, abrir = self.contexto_main(stack, ["--icono"], ocupado=True)
            stack.enter_context(patch.object(app.sys, "platform", "win32"))
            stack.enter_context(patch.object(app, "dashboard_disponible", return_value=False))
            icono = stack.enter_context(patch("bandeja.icono_windows.IconoWindows")).return_value
            icono.adquirir_instancia.return_value = True
            with self.assertRaisesRegex(OSError, "otro servicio"):
                app.main()
            icono.iniciar.assert_not_called()
            icono.detener.assert_called_once()
            vigilante.iniciar.assert_not_called()
            capcut.iniciar.assert_not_called()
            abrir.assert_not_called()

    def test_icono_linux_inicia_servicio_sin_cargar_backend_windows(self):
        with ExitStack() as stack:
            app, vigilante, _, servidor, _, _ = self.contexto_main(stack, ["--icono", "--sin-navegador"])
            stack.enter_context(patch.object(app.sys, "platform", "linux"))
            stack.enter_context(patch.object(app, "dashboard_disponible", return_value=False))
            icono = stack.enter_context(patch("bandeja.icono_windows.IconoWindows"))
            linux = stack.enter_context(patch("bandeja.icono_linux.IconoLinux")).return_value
            linux.adquirir_instancia.return_value = True
            app.main()
            icono.assert_not_called()
            vigilante.iniciar.assert_called_once()
            servidor.serve_forever.assert_called_once()
            linux.iniciar.assert_called_once()
            linux.detener.assert_called_once()
            self.assertEqual(linux.al_salir, servidor.shutdown)

    def test_fallo_icono_libera_servidor_sin_iniciar_vigilantes(self):
        with ExitStack() as stack:
            app, vigilante, capcut, servidor, _, _ = self.contexto_main(stack, ["--icono", "--sin-navegador"])
            stack.enter_context(patch.object(app.sys, "platform", "win32"))
            stack.enter_context(patch.object(app, "dashboard_disponible", return_value=False))
            icono = stack.enter_context(patch("bandeja.icono_windows.IconoWindows")).return_value
            icono.adquirir_instancia.return_value = True
            icono.iniciar.side_effect = OSError("No hay icono")
            with self.assertRaisesRegex(OSError, "No hay icono"):
                app.main()
            icono.detener.assert_called_once()
            vigilante.iniciar.assert_not_called()
            capcut.iniciar.assert_not_called()
            servidor.server_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
