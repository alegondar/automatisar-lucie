"""Transferencias y publicación probadas solo con temporales y receptor local falso."""
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.edicion import (copiar_export_sin_sesion_a_sin_publicar,
                            deshacer_copia_completo, obtener_secciones_edicion, crear_sesion)
from bandeja.localsend import ClienteLocalSend, validar_destino
from bandeja.publicacion import GestorPublicacion


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class ReceptorTemporal:
    def __init__(self, contexto_tls=None):
        self.preparacion = 200
        self.recepcion = 200
        self.archivos = {}
        self.metadatos = {}
        self.solicitud = threading.Event()
        self.aprobacion = threading.Event()
        self.aprobacion.set()
        self.cortar_upload = False
        self.aceptar_ids = None
        self.cancelaciones = []
        self.codigo_cancelacion = 200
        receptor = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def responder(self, codigo, datos=None):
                cuerpo = json.dumps(datos).encode() if datos is not None else b""
                self.send_response(codigo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                try:
                    self.wfile.write(cuerpo)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def do_GET(self):
                self.responder(200, {"alias": "Celular temporal", "version": "2.0", "fingerprint": "celular-prueba"})

            def do_POST(self):
                ruta = urlparse(self.path)
                cuerpo = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if ruta.path == "/api/localsend/v2/prepare-upload":
                    receptor.metadatos = json.loads(cuerpo)["files"]
                    receptor.solicitud.set()
                    receptor.aprobacion.wait(5)
                    self.responder(receptor.preparacion, {"sessionId": "recepcion-temporal",
                        "files": {i: "token-" + i for i in receptor.metadatos if receptor.aceptar_ids is None or i in receptor.aceptar_ids}} if receptor.preparacion == 200 else {})
                elif ruta.path == "/api/localsend/v2/upload":
                    if receptor.cortar_upload:
                        self.connection.close()
                        return
                    params = parse_qs(ruta.query)
                    identificador = params["fileId"][0]
                    valido = (params["token"][0] == "token-" + identificador and
                              hashlib.sha256(cuerpo).hexdigest() == receptor.metadatos[identificador]["sha256"] and
                              len(cuerpo) == receptor.metadatos[identificador]["size"])
                    if receptor.recepcion == 200 and valido:
                        receptor.archivos[identificador] = cuerpo
                    self.responder(receptor.recepcion if valido else 422)
                elif ruta.path == "/api/localsend/v2/cancel":
                    receptor.cancelaciones.append(parse_qs(ruta.query).get("sessionId", [None])[0])
                    self.responder(receptor.codigo_cancelacion)
                else:
                    self.responder(404)

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if contexto_tls:
            self.servidor.socket = contexto_tls.wrap_socket(self.servidor.socket, server_side=True)
        self.servidor.daemon_threads = True
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def cerrar(self):
        self.aprobacion.set()
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(2)


class TestPublicacionWifi(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="publicacion_wifi_")
        self.addCleanup(self.temporal.cleanup)
        self.montaje = self.temporal.name
        self.raiz = os.path.join(self.montaje, "LucieSinReglas")
        self.pendientes = os.path.join(self.raiz, "videos completos", "videos sin publicar")
        os.makedirs(self.pendientes)
        self.config = ConfiguracionBandeja(ruta_config=os.path.join(self.montaje, "no.json"),
                                          ruta_config_local=os.path.join(self.montaje, "no-local.json"))
        self.db = GestorBaseDatosBandeja(os.path.join(self.montaje, "db.sqlite"))
        self.pen = {"id": "pendrive-temporal", "conectado": True, "punto_montaje": self.montaje}
        parche = patch("bandeja.publicacion.detectar_pendrive", side_effect=lambda config: dict(self.pen))
        parche.start()
        self.addCleanup(parche.stop)
        self.receptor = ReceptorTemporal()
        self.addCleanup(self.receptor.cerrar)
        self.gestor = GestorPublicacion(self.config, self.db)
        self.dispositivo = self.gestor._guardar_dispositivo({"ip": "127.0.0.1", "port": self.receptor.servidor.server_port,
            "protocol": "http", "alias": "Celular temporal", "fingerprint": "celular-prueba"})
        self.video = self.crear("lucie/Cafe/Cafe.mp4")

    def crear(self, relativo, datos=b"video original para publicar"):
        ruta = os.path.join(self.pendientes, *relativo.split("/"))
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "xb") as archivo:
            archivo.write(datos)
        return ruta

    def plan(self):
        listado = self.gestor.listar()
        return self.gestor.simular([a["id"] for a in listado["archivos"]], self.dispositivo["id"])

    def esperar(self, identificador):
        limite = time.monotonic() + 8
        while time.monotonic() < limite:
            resultado = self.gestor.estado(identificador)
            if resultado["estado"] != "en_curso":
                return resultado
            time.sleep(0.01)
        self.fail("La transferencia temporal no terminó.")

    def test_ocupado_antes_de_preparar_no_cancela_sesion_ajena(self):
        self.receptor.preparacion = 409
        resultado = self.esperar(self.gestor.iniciar_envio(self.plan()["token"], True)["id"])
        self.assertEqual(resultado["codigo_http"], 409)
        self.assertEqual(resultado["etapa"], "preparacion")
        self.assertIsNone(resultado["cancelacion_confirmada"])
        self.assertEqual(self.receptor.cancelaciones, [])
        self.assertEqual(resultado["recibidos"], [])
        self.assertEqual(resultado["publicados"], [])
        self.assertTrue(os.path.isfile(self.video))

    def test_204_preparacion_no_cuenta_como_recibido(self):
        self.receptor.preparacion = 204
        resultado = self.esperar(self.gestor.iniciar_envio(self.plan()["token"], True)["id"])
        self.assertEqual(resultado["codigo_http"], 204)
        self.assertEqual(resultado["recibidos"], [])
        self.assertEqual(resultado["publicados"], [])
        self.assertTrue(os.path.isfile(self.video))

    def test_error_upload_cancela_solo_sesion_propia_y_permite_segundo_envio(self):
        self.receptor.recepcion = 409
        resultado = self.esperar(self.gestor.iniciar_envio(self.plan()["token"], True)["id"])
        self.assertEqual(resultado["codigo_http"], 409)
        self.assertTrue(resultado["cancelacion_confirmada"])
        self.assertEqual(self.receptor.cancelaciones, ["recepcion-temporal"])
        self.assertEqual(resultado["publicados"], [])
        self.receptor.recepcion = 200
        resultado = self.esperar(self.gestor.iniciar_envio(self.plan()["token"], True)["id"])
        self.assertEqual(resultado["estado"], "completado")

    def test_cancelacion_no_confirmada_visible_no_publica(self):
        self.receptor.recepcion = 422
        self.receptor.codigo_cancelacion = 500
        resultado = self.esperar(self.gestor.iniciar_envio(self.plan()["token"], True)["id"])
        self.assertFalse(resultado["cancelacion_confirmada"])
        self.assertEqual(resultado["publicados"], [])
        self.assertTrue(os.path.isfile(self.video))

    def test_cancelar_espera_interrumpe_conexion_sin_aceptacion(self):
        self.receptor.aprobacion.clear()
        trabajo = self.gestor.iniciar_envio(self.plan()["token"], True)
        self.assertTrue(self.receptor.solicitud.wait(3))
        inicio = time.monotonic()
        try:
            self.gestor.cancelar(trabajo["id"])
            resultado = self.esperar(trabajo["id"])
            self.assertLess(time.monotonic() - inicio, 2)
            self.assertEqual(resultado["estado"], "cancelado")
            self.assertEqual(resultado["recibidos"], [])
            self.assertEqual(resultado["publicados"], [])
        finally:
            self.receptor.aprobacion.set()

    def _receptor_https_temporal(self):
        openssl = shutil.which("openssl")
        if not openssl:
            candidato = os.path.join(os.environ.get("ProgramFiles", ""), "Git", "usr", "bin", "openssl.exe")
            if os.path.isfile(candidato):
                openssl = candidato
        if not openssl:
            self.skipTest("Falta OpenSSL para generar el certificado TLS exclusivamente temporal.")
        certificado = os.path.join(self.montaje, "certificado-temporal.pem")
        clave = os.path.join(self.montaje, "clave-temporal.pem")
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=localhost", "-keyout", clave, "-out", certificado],
                       cwd=self.montaje, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       check=True, timeout=15)
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexto.load_cert_chain(certificado, clave)
        receptor = ReceptorTemporal(contexto)
        self.addCleanup(receptor.cerrar)
        self.dispositivo = self.gestor.agregar_dispositivo("127.0.0.1", receptor.servidor.server_port)
        self.assertEqual(self.dispositivo["protocol"], "https")
        return receptor

    def test_envio_https_con_huella_confirmada_preserva_integridad(self):
        receptor = self._receptor_https_temporal()
        plan = self.plan()
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "completado", resultado)
        self.assertEqual(receptor.archivos[plan["archivos"][0]["id"]], b"video original para publicar")
        self.assertEqual(calcular_sha256(plan["archivos"][0]["destino"]), plan["archivos"][0]["sha256"])

    def test_cancelar_espera_https_no_aguarda_aceptacion_del_receptor(self):
        receptor = self._receptor_https_temporal()
        receptor.aprobacion.clear()
        trabajo = self.gestor.iniciar_envio(self.plan()["token"], True)
        self.assertTrue(receptor.solicitud.wait(3))
        inicio = time.monotonic()
        try:
            self.gestor.cancelar(trabajo["id"])
            resultado = self.esperar(trabajo["id"])
            self.assertLess(time.monotonic() - inicio, 2)
            self.assertEqual(resultado["estado"], "cancelado")
            self.assertEqual(resultado["recibidos"], [])
            self.assertEqual(resultado["publicados"], [])
            self.assertTrue(os.path.isfile(self.video))
        finally:
            receptor.aprobacion.set()

    def test_listar_simular_no_mueve_ni_crea_registros(self):
        plan = self.plan()
        self.assertTrue(os.path.isfile(self.video))
        self.assertFalse(os.path.exists(plan["archivos"][0]["destino"]))
        self.assertFalse(os.path.exists(os.path.join(self.raiz, ".lucie")))
        self.assertEqual(plan["archivos"][0]["sha256"], calcular_sha256(self.video))

    def test_inventario_separa_personajes_y_no_adivina_nombres_numericos(self):
        self.crear("roli/Escena/lucie_nombre_conflictivo.mp4")
        self.crear("Mailén/Escena/foto.jpg", b"foto temporal")
        self.crear("luciecafe.mp4")
        self.crear("1010(6).mp4")
        asociado = self.crear("1010(7).mp4")
        sesion = crear_sesion(self.db, ["roli/cap/clip.mp4"], "roli", "cap")
        self.db.actualizar_sesion_edicion(sesion["id"], video_completo_ruta=asociado)
        listado = {a["nombre"]: a for a in self.gestor.listar()["archivos"]}
        self.assertEqual(listado["Cafe.mp4"]["personaje"], "lucie")
        self.assertEqual(listado["lucie_nombre_conflictivo.mp4"]["personaje"], "roli")
        self.assertEqual(listado["foto.jpg"]["personaje"], "mailen")
        self.assertEqual(listado["foto.jpg"]["tipo"], "imagen")
        self.assertEqual(listado["luciecafe.mp4"]["personaje"], "lucie")
        self.assertEqual(listado["luciecafe.mp4"]["personaje_origen"], "nombre")
        self.assertEqual(listado["1010(6).mp4"]["personaje"], "sin_asignar")
        self.assertEqual(listado["1010(7).mp4"]["personaje"], "roli")
        self.assertEqual(listado["1010(7).mp4"]["personaje_origen"], "sesion")

    def test_inventario_y_preview_excluyen_capcut_crudos_y_completos_publicados(self):
        for carpeta in ("CapCut", "videos sin editar", "videos ya editados", "videos completos"):
            ruta = os.path.join(self.raiz, carpeta, "ajeno.mp4")
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "xb") as f:
                f.write(b"material ajeno a sin publicar")
        listado = self.gestor.listar()["archivos"]
        self.assertEqual(len(listado), 1)
        self.assertEqual(listado[0]["carpeta_relativa"], "lucie/Cafe")
        self.assertTrue(listado[0]["id_media"].startswith("publicacion:"))
        self.assertEqual(self.gestor.resolver_media(listado[0]["id"])[0], self.video)
        for ruta in ("../CapCut/ajeno.mp4", "videos completos/ajeno.mp4", "capcut:1"):
            with self.subTest(ruta=ruta), self.assertRaises(ValueError):
                self.gestor.resolver_media(ruta)

    def test_foto_enviada_se_archiva_y_preview_de_cola_deja_de_resolver(self):
        self.crear("mailen/Plaza/foto.png", b"foto temporal para enviar")
        plan = self.plan()
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "completado", resultado)
        self.assertEqual(len(resultado["publicados"]), 2)
        for archivo in plan["archivos"]:
            self.assertTrue(os.path.isfile(archivo["destino"]))
            with self.assertRaises(ValueError):
                self.gestor.resolver_media(archivo["id"])
            with open(archivo["destino"], "rb") as f:
                self.assertEqual(self.receptor.archivos[archivo["id"]], f.read())

    def test_transferencia_real_http_confirma_hash_archiva_y_deshace(self):
        sesion = crear_sesion(self.db, ["lucie/Cafe/clip.mp4"], "lucie", "Cafe")
        self.db.actualizar_sesion_edicion(sesion["id"], video_completo_ruta=self.video, estado="completado")
        exp_id = self.db.registrar_export_pendiente(os.path.join(self.montaje, "export.mp4"), "export.mp4", 1, 1,
                                                   sesion_id=sesion["id"], estado="copiado")
        plan = self.plan()
        trabajo = self.gestor.iniciar_envio(plan["token"], True)
        resultado = self.esperar(trabajo["id"])
        self.assertEqual(resultado["estado"], "completado", resultado)
        destino = plan["archivos"][0]["destino"]
        self.assertFalse(os.path.exists(self.video))
        self.assertTrue(os.path.isfile(destino))
        self.assertEqual(next(iter(self.receptor.archivos.values())), b"video original para publicar")
        self.assertEqual(calcular_sha256(destino), plan["archivos"][0]["sha256"])
        self.assertEqual(self.db.obtener_sesion_por_id(sesion["id"])["video_completo_ruta"], destino)
        self.assertEqual(self.db.obtener_exports_pendientes()[0]["ruta_destino"], destino)
        self.assertEqual(self.gestor.listar()["archivos"], [])
        self.assertEqual(resultado["carpetas_vacias_retiradas"], [os.path.dirname(self.video)])
        self.assertFalse(os.path.isdir(os.path.dirname(self.video)))
        self.assertTrue(os.path.isdir(os.path.dirname(os.path.dirname(self.video))))
        self.assertTrue(self.gestor.deshacer(resultado["publicados"][0]["id_operacion"])["exito"])
        self.assertTrue(os.path.isfile(self.video))
        self.assertFalse(os.path.exists(destino))
        self.assertEqual(self.db.obtener_sesion_por_id(sesion["id"])["video_completo_ruta"], self.video)
        self.assertEqual(self.gestor.listar()["historial"], [])

    def test_archivo_nuevo_durante_envio_impide_retirar_carpeta(self):
        plan = self.plan()
        nuevo = os.path.join(os.path.dirname(self.video), "nuevo.txt")
        enviar = self.gestor.cliente.enviar

        def agregar_y_enviar(*args, **kwargs):
            with open(nuevo, "xb") as archivo:
                archivo.write(b"conservar contenido nuevo")
            return enviar(*args, **kwargs)

        with patch.object(self.gestor.cliente, "enviar", side_effect=agregar_y_enviar):
            resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "completado", resultado)
        self.assertEqual(resultado["carpetas_vacias_retiradas"], [])
        with open(nuevo, "rb") as archivo:
            self.assertEqual(archivo.read(), b"conservar contenido nuevo")

    def test_aceptacion_parcial_envia_solo_archivos_aceptados(self):
        self.crear("roli/Otro/Otro.mp4")
        plan = self.plan()
        aceptado = plan["archivos"][1]
        rechazado = plan["archivos"][0]
        self.receptor.aceptar_ids = [aceptado["id"]]
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "error")
        self.assertEqual(len(resultado["publicados"]), 1)
        self.assertEqual(resultado["carpetas_vacias_retiradas"], [])
        self.assertTrue(os.path.isdir(os.path.dirname(aceptado["origen"])))
        self.assertTrue(os.path.isfile(aceptado["destino"]))
        self.assertTrue(os.path.isfile(rechazado["origen"]))
        self.assertFalse(os.path.exists(rechazado["destino"]))

    def test_rechazo_del_celular_conserva_video_sin_publicar(self):
        self.receptor.preparacion = 403
        plan = self.plan()
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "error")
        self.assertTrue(os.path.isfile(self.video))
        self.assertFalse(os.path.exists(plan["archivos"][0]["destino"]))
        self.assertEqual(self.gestor.listar()["historial"], [])

    def test_corte_de_conexion_conserva_video_sin_publicar(self):
        self.receptor.cortar_upload = True
        plan = self.plan()
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "error")
        self.assertTrue(os.path.isfile(self.video))
        self.assertEqual(resultado["publicados"], [])

    def test_historial_recuperable_si_falla_registro_despues_del_traslado(self):
        from bandeja.edicion import registrar_evento_manifiesto_edicion
        def registrar(raiz, evento):
            if evento["tipo_evento"] == "publicado_por_envio_wifi":
                raise OSError("fallo simulado de registro final")
            registrar_evento_manifiesto_edicion(raiz, evento)
        plan = self.plan()
        with patch("bandeja.publicacion.registrar_evento_manifiesto_edicion", side_effect=registrar):
            resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "error")
        historial = self.gestor.listar()["historial"]
        self.assertEqual(len(historial), 1)
        self.assertTrue(os.path.isfile(plan["archivos"][0]["destino"]))
        self.gestor.deshacer(historial[0]["id_operacion"])
        self.assertTrue(os.path.isfile(self.video))

    def test_rechazo_de_integridad_no_publica(self):
        self.receptor.recepcion = 422
        plan = self.plan()
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "error")
        self.assertEqual(resultado["publicados"], [])
        self.assertTrue(os.path.isfile(self.video))

    def test_cancelar_antes_de_aceptar_no_mueve_video(self):
        self.receptor.aprobacion.clear()
        plan = self.plan()
        trabajo = self.gestor.iniciar_envio(plan["token"], True)
        self.assertTrue(self.receptor.solicitud.wait(3))
        self.assertTrue(os.path.isfile(self.video))
        self.gestor.cancelar(trabajo["id"])
        self.receptor.aprobacion.set()
        resultado = self.esperar(trabajo["id"])
        self.assertEqual(resultado["estado"], "cancelado")
        self.assertTrue(os.path.isfile(self.video))
        self.assertEqual(self.receptor.archivos, {})

    def test_archivo_cambiado_tras_simular_no_se_envia(self):
        plan = self.plan()
        with open(self.video, "ab") as archivo:
            archivo.write(b"nuevo contenido")
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "error")
        self.assertEqual(self.receptor.archivos, {})
        self.assertTrue(os.path.isfile(self.video))

    def test_pendrive_distinto_no_se_envia(self):
        plan = self.plan()
        self.pen["id"] = "otro-pendrive"
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "error")
        self.assertEqual(self.receptor.archivos, {})
        self.assertTrue(os.path.isfile(self.video))

    def test_destino_ocupado_no_se_pisa(self):
        plan = self.plan()
        destino = plan["archivos"][0]["destino"]
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "xb") as archivo:
            archivo.write(b"otro video")
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "error")
        self.assertTrue(os.path.isfile(self.video))
        with open(destino, "rb") as archivo:
            self.assertEqual(archivo.read(), b"otro video")

    def test_plan_un_solo_uso_y_confirmacion_obligatoria(self):
        plan = self.plan()
        with self.assertRaises(ValueError):
            self.gestor.iniciar_envio(plan["token"], False)
        resultado = self.esperar(self.gestor.iniciar_envio(plan["token"], True)["id"])
        self.assertEqual(resultado["estado"], "completado")
        with self.assertRaises(ValueError):
            self.gestor.iniciar_envio(plan["token"], True)

    def test_rutas_escape_y_destinos_publicos_rechazados(self):
        for ruta in ("../fuera/video.mp4", "videos completos/../video.mp4", "C:/video.mp4", ".lucie/manifiesto.jsonl"):
            with self.subTest(ruta=ruta), self.assertRaises(ValueError):
                self.gestor._ruta(self.raiz, ruta)
        for ip in ("8.8.8.8", "0.0.0.0", "224.0.0.167", "example.com"):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                validar_destino(ip, 53317)

    def test_resguardo_sin_sesion_preserva_versions_y_undo_no_reenvia(self):
        origen = os.path.join(self.montaje, "1010(7).mp4")
        with open(origen, "xb") as archivo:
            archivo.write(b"primer export")
        st = os.stat(origen)
        exp1 = self.db.registrar_export_pendiente(origen, "1010(7).mp4", st.st_size, st.st_mtime)
        dato = next(e for e in self.db.obtener_exports_pendientes() if e["id"] == exp1)
        bitacora = os.path.join(self.montaje, "bitacora.jsonl")
        destino1 = copiar_export_sin_sesion_a_sin_publicar(dato, self.montaje, self.db, "LucieSinReglas", bitacora)
        with open(origen, "wb") as archivo:
            archivo.write(b"segundo export distinto")
        st = os.stat(origen)
        exp2 = self.db.registrar_export_pendiente(origen, "1010(7).mp4", st.st_size, st.st_mtime)
        dato = next(e for e in self.db.obtener_exports_pendientes() if e["id"] == exp2)
        destino2 = copiar_export_sin_sesion_a_sin_publicar(dato, self.montaje, self.db, "LucieSinReglas", bitacora)
        self.assertNotEqual(destino1, destino2)
        with open(destino1, "rb") as archivo:
            self.assertEqual(archivo.read(), b"primer export")
        self.assertTrue(os.path.isfile(origen))
        deshacer_copia_completo(destino2, self.montaje, self.db, "LucieSinReglas", bitacora)
        dato = next(e for e in self.db.obtener_exports_pendientes() if e["id"] == exp2)
        self.assertEqual(dato["estado"], "sin_asignar")
        self.assertTrue(dato["envio_automatico_bloqueado"])

    def test_probe_localsend_con_receptor_http_temporal(self):
        dispositivo = self.gestor.agregar_dispositivo("127.0.0.1", self.receptor.servidor.server_port)
        self.assertEqual(dispositivo["alias"], "Celular temporal")
        self.assertEqual(dispositivo["protocol"], "http")

    def test_conteos_de_completos_en_cola_sin_base_compartida(self):
        conteos = obtener_secciones_edicion(self.montaje, self.db)["conteos_capitulo"]
        self.assertEqual(conteos["Cafe"]["completos"], 1)
        self.assertNotIn("lucie", conteos)

    def test_resguardo_sin_sesion_respeta_operacion_wifi_en_curso(self):
        from bandeja.pendrive import operacion_pendrive_exclusiva
        st = os.stat(self.video)
        export_id = self.db.registrar_export_pendiente(self.video, "Cafe.mp4", st.st_size, st.st_mtime)
        export = next(e for e in self.db.obtener_exports_pendientes() if e["id"] == export_id)
        with operacion_pendrive_exclusiva(), self.assertRaises(ValueError):
            copiar_export_sin_sesion_a_sin_publicar(export, self.montaje, self.db, "LucieSinReglas",
                                                  os.path.join(self.montaje, "bitacora.jsonl"))
        self.assertEqual(self.db.obtener_exports_pendientes()[0]["estado"], "sin_asignar")
        self.assertTrue(os.path.isfile(self.video))

    def test_vigilante_resguarda_sin_sesion_solo_en_modo_automatico(self):
        from bandeja_descargas import crear_vigilante_capcut
        capcut = os.path.join(self.montaje, "CapCut")
        os.makedirs(capcut)
        self.config.carpeta_exportacion_capcut = capcut
        self.config.envio_exports_capcut = "manual"
        vigilante = crear_vigilante_capcut(self.config, self.db, os.path.join(self.montaje, "bitacora.jsonl"))
        vigilante.tomar_fotografia_inicial()
        origen = os.path.join(capcut, "exportNuevo.mp4")
        with open(origen, "xb") as f:
            f.write(b"nuevo export sin sesion")
        with patch("bandeja_descargas.detectar_pendrive", return_value=self.pen):
            for _ in range(4):
                vigilante.escanear()
            export = self.db.obtener_exports_pendientes()[0]
            self.assertEqual(export["estado"], "sin_asignar")
            self.assertIsNone(export["sesion_id"])
            self.assertFalse(os.path.exists(os.path.join(self.pendientes, "exportNuevo.mp4")))
            self.config.envio_exports_capcut = "automatico"
            vigilante.escanear()
        export = self.db.obtener_exports_pendientes()[0]
        self.assertEqual(export["estado"], "copiado")
        self.assertIsNone(export["sesion_id"])
        self.assertEqual(calcular_sha256(origen), calcular_sha256(export["ruta_destino"]))
        self.assertTrue(os.path.isfile(origen))


class TestDescubrimientoUdpLocalSend(unittest.TestCase):
    def test_respuesta_multicast_receptor_https_sin_registro_http(self):
        import socket
        class UdpTemporal:
            def __init__(self): self.pendiente = True; self.destinations = []; self.bound = None
            def setsockopt(self, *args): pass
            def bind(self, address): self.bound = address
            def settimeout(self, *args): pass
            def sendto(self, body, address): self.destinations.append(address)
            def close(self): pass
            def recvfrom(self, size):
                if self.pendiente:
                    self.pendiente = False
                    return json.dumps({'version':'2.0','alias':'Lucie Recibir','fingerprint':'identidad-temporal',
                                       'port':53318,'protocol':'https','announce':False}).encode(), ('127.0.0.1',53317)
                time.sleep(.02)
                raise socket.timeout()
        original = socket.socket
        udp = UdpTemporal()
        cliente = ClienteLocalSend()
        receptor = {'ip':'127.0.0.1','port':53318,'protocol':'https','alias':'Lucie Recibir','fingerprint':'verificada'}
        with patch('bandeja.localsend.socket.socket', side_effect=lambda family, kind, proto=0, *a, **k:
                   udp if kind == socket.SOCK_DGRAM else original(family,kind,proto,*a,**k)), \
             patch.object(cliente,'probar',return_value=receptor) as verificar:
            self.assertEqual(cliente.descubrir(.1),[receptor])
            verificar.assert_called_once_with('127.0.0.1',53318,'https')
            self.assertEqual(udp.bound, ('0.0.0.0', 0))
            self.assertIn(('224.0.0.167', 53319), udp.destinations)
            self.assertIn(('255.255.255.255', 53319), udp.destinations)

    def test_dos_receptores_en_misma_ip_se_conservan_por_puerto(self):
        import socket
        class UdpTemporal:
            def __init__(self): self.ports = iter([53318,53317])
            def setsockopt(self,*args): pass
            def bind(self,*args): pass
            def settimeout(self,*args): pass
            def sendto(self,*args): pass
            def close(self): pass
            def recvfrom(self,size):
                try: port=next(self.ports)
                except StopIteration:
                    time.sleep(.02)
                    raise socket.timeout()
                return json.dumps({'version':'2.0','fingerprint':'fixture-'+str(port),
                                   'port':port,'protocol':'https'}).encode(),('127.0.0.1',53319)
        original=socket.socket;udp=UdpTemporal();cliente=ClienteLocalSend()
        def verified(ip,port,protocol):
            return {'ip':ip,'port':port,'protocol':protocol,'alias':'fixture-'+str(port),'fingerprint':'fixture'}
        with patch('bandeja.localsend.socket.socket',side_effect=lambda family,kind,proto=0,*a,**k:
                   udp if kind==socket.SOCK_DGRAM else original(family,kind,proto,*a,**k)), \
             patch.object(cliente,'probar',side_effect=verified) as verify:
            devices=cliente.descubrir(.1)
            self.assertEqual({d['port'] for d in devices},{53317,53318})
            self.assertEqual(verify.call_count,2)


if __name__ == "__main__":
    unittest.main()
