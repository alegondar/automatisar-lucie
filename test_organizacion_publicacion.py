"""Publicados/personajes y reorganización: solo material sintético temporal."""
import os
import tempfile
import unittest
from unittest.mock import patch

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.edicion import crear_sesion, registrar_evento_manifiesto_edicion, obtener_secciones_edicion
from bandeja.publicacion import GestorPublicacion


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestOrganizacionPublicacion(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="organizar_publicacion_")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.raiz = os.path.join(self.tmp, "LucieSinReglas")
        os.makedirs(self.raiz)
        cfg = ConfiguracionBandeja(os.path.join(self.tmp, "cfg.json"), os.path.join(self.tmp, "local.json"))
        self.db = GestorBaseDatosBandeja(os.path.join(self.tmp, "memoria.sqlite"))
        parche = patch("bandeja.publicacion.detectar_pendrive", return_value={"id": "sintetico", "conectado": True, "punto_montaje": self.tmp})
        parche.start(); self.addCleanup(parche.stop)
        self.gestor = GestorPublicacion(cfg, self.db)
        self.org = self.gestor.organizacion
        self.dispositivo = self.gestor._guardar_dispositivo({"ip": "127.0.0.1", "port": 12345, "protocol": "http", "alias": "sintetico"})

    def crear(self, relativo, datos=b"bytes sinteticos"):
        ruta = os.path.join(self.raiz, *relativo.split("/"))
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "xb") as f: f.write(datos)
        return ruta

    def antiguos(self):
        self.lucie = self.crear("videos completos/lucie/Capitulo - lunes - semana 2 - octubre - 2026/a.mp4")
        self.roli = self.crear("videos completos/roli/Cancion/b.mp4")
        self.publicado = self.crear("videos completos/1010(7).mp4", b"publicado confirmado")
        self.evento = {"id_operacion": "publicacion-anterior", "ruta_origen": "videos completos/videos sin publicar/1010(7).mp4",
                       "ruta_destino": "videos completos/1010(7).mp4", "sha256": calcular_sha256(self.publicado),
                       "bytes": os.path.getsize(self.publicado), "dispositivo": "sintetico", "fecha": "2026-10-13",
                       "tipo_evento": "publicado_por_envio_wifi"}
        registrar_evento_manifiesto_edicion(self.raiz, self.evento)
        candidatos = self.gestor.listar()["organizacion_pendiente"]
        return self.org.simular([{"id": c["id"], "personaje": c["personaje"] or "roli"} for c in candidatos])

    def test_destinos_por_personaje_conservan_capitulos_y_nombres(self):
        for personaje in ("lucie", "roli", "mailen"):
            self.crear("videos completos/videos sin publicar/" + personaje + "/Capitulo - lunes - semana 2 - octubre - 2026/video.mp4")
        archivos = self.gestor.listar()["archivos"]
        plan = self.gestor.simular([a["id"] for a in archivos], self.dispositivo["id"])
        for a in plan["archivos"]:
            self.assertEqual(a["destino_rel"], "videos completos/videosPublicados/" + a["personaje"] + "/Capitulo - lunes - semana 2 - octubre - 2026/video.mp4")
            self.assertTrue(os.path.isfile(a["origen"]))
            self.assertFalse(os.path.exists(a["destino"]))

    def test_numerico_exige_eleccion_y_no_adivina_personaje(self):
        ruta = self.crear("videos completos/videos sin publicar/1010(7).mp4")
        a = self.gestor.listar()["archivos"][0]
        self.assertEqual(a["personaje"], "sin_asignar")
        with self.assertRaises(ValueError): self.gestor.simular([a["id"]], self.dispositivo["id"])
        plan = self.gestor.simular([a["id"]], self.dispositivo["id"], {a["id"]: "roli"})
        self.assertEqual(plan["archivos"][0]["destino_rel"], "videos completos/videosPublicados/roli/1010(7).mp4")
        self.assertTrue(os.path.isfile(ruta))
        for valor in ("../../afuera", "sin_asignar", 1):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                self.gestor.simular([a["id"]], self.dispositivo["id"], {a["id"]: valor})

    def test_simulacion_no_mueve_y_confirmacion_es_obligatoria(self):
        plan = self.antiguos()
        self.assertEqual(len(plan["acciones"]), 3)
        self.assertTrue(all(os.path.exists(os.path.join(self.raiz, a["ruta"])) for a in plan["acciones"]))
        with self.assertRaises(ValueError): self.org.ejecutar(plan["token"], False)
        self.assertTrue(os.path.isfile(self.publicado))

    def test_organiza_actualiza_db_historial_y_deshace_sin_borrar(self):
        plan = self.antiguos()
        sesion = crear_sesion(self.db, ["lucie/cap/clip.mp4"], "lucie", "Capitulo")
        self.db.actualizar_sesion_edicion(sesion["id"], video_completo_ruta=self.lucie)
        export_id = self.db.registrar_export_pendiente(os.path.join(self.tmp, "export.mp4"), "a.mp4", 1, 1, sesion_id=sesion["id"], estado="copiado")
        self.db.actualizar_export_pendiente(export_id, ruta_destino=self.lucie)
        resultado = self.org.ejecutar(plan["token"], True)
        self.assertTrue(resultado["exito"], resultado)
        nuevo = self.lucie.replace("videos completos" + os.sep, "videos completos" + os.sep + "videos sin publicar" + os.sep, 1)
        self.assertEqual(self.db.obtener_sesion_por_id(sesion["id"])["video_completo_ruta"], nuevo)
        self.assertEqual(self.db.obtener_exports_pendientes()[0]["ruta_destino"], nuevo)
        self.assertEqual(len(self.gestor.listar()["archivos"]), 2)
        publicado = self.gestor.listar()["historial"][0]
        self.assertEqual(publicado["ruta_destino"], "videos completos/videosPublicados/roli/1010(7).mp4")
        self.assertEqual(calcular_sha256(os.path.join(self.raiz, publicado["ruta_destino"])), self.evento["sha256"])
        for movimiento in resultado["completadas"]:
            self.org.deshacer(movimiento["id_organizacion"])
        self.assertTrue(os.path.isfile(self.publicado))
        self.assertTrue(os.path.isfile(self.lucie)); self.assertTrue(os.path.isfile(self.roli))
        self.assertEqual(self.gestor.listar()["organizaciones"], [])
        self.assertEqual(self.gestor.listar()["historial"][0]["ruta_destino"], self.evento["ruta_destino"])
        self.assertEqual(self.db.obtener_sesion_por_id(sesion["id"])["video_completo_ruta"], self.lucie)

    def test_deshacer_publicacion_funciona_despues_de_reorganizar(self):
        plan = self.antiguos(); self.assertTrue(self.org.ejecutar(plan["token"], True)["exito"])
        self.gestor.deshacer("publicacion-anterior")
        self.assertTrue(os.path.isfile(os.path.join(self.raiz, self.evento["ruta_origen"])))
        self.assertEqual(self.gestor.listar()["historial"], [])

    def test_colision_prevalida_todo_y_no_fusiona_carpetas(self):
        plan = self.antiguos()
        ajeno = self.crear("videos completos/videos sin publicar/roli/nuevo.mp4", b"ajeno")
        with self.assertRaises(FileExistsError): self.org.ejecutar(plan["token"], True)
        self.assertTrue(os.path.isfile(self.lucie)); self.assertTrue(os.path.isfile(self.roli)); self.assertTrue(os.path.isfile(self.publicado))
        with open(ajeno, "rb") as f: self.assertEqual(f.read(), b"ajeno")

    def test_cambio_tras_simular_bloquea_todos_los_traslados(self):
        plan = self.antiguos()
        with open(self.roli, "ab") as f: f.write(b"nuevos bytes")
        with self.assertRaises(ValueError): self.org.ejecutar(plan["token"], True)
        self.assertTrue(os.path.isfile(self.lucie)); self.assertTrue(os.path.isfile(self.publicado))

    def test_deshacer_rechaza_contenido_nuevo_sin_quitarlo(self):
        plan = self.antiguos(); result = self.org.ejecutar(plan["token"], True)
        carpeta = next(e for e in result["completadas"] if e["accion"]["ruta"].endswith("/lucie"))
        nuevo = self.crear(carpeta["accion"]["destino"] + "/nuevo.mp4", b"nuevo")
        with self.assertRaises(ValueError): self.org.deshacer(carpeta["id_organizacion"])
        self.assertTrue(os.path.isfile(nuevo))

    def test_fallo_de_registro_final_es_recuperable_y_reversible(self):
        plan = self.antiguos()
        seleccion = [a for a in plan["acciones"] if a["tipo"] == "publicado"]
        self.org.planes[plan["token"]]["acciones"] = seleccion
        def registro(raiz, evento):
            if evento["tipo_evento"] == "organizacion_completada": raise OSError("registro final interrumpido")
            registrar_evento_manifiesto_edicion(raiz, evento)
        with patch("bandeja.organizacion_publicacion.registrar_evento_manifiesto_edicion", side_effect=registro):
            result = self.org.ejecutar(plan["token"], True)
        self.assertFalse(result["exito"])
        lista = self.gestor.listar()
        self.assertTrue(lista["organizaciones"][0]["recuperado"])
        self.assertEqual(lista["historial"][0]["ruta_destino"], seleccion[0]["destino"])
        self.org.deshacer(lista["organizaciones"][0]["id_organizacion"])
        self.assertTrue(os.path.isfile(self.publicado))

    def test_enlace_no_se_atraviesa_y_publicados_no_vuelven_a_pendientes(self):
        plan = self.antiguos()
        destino = os.path.join(os.path.dirname(self.lucie), "enlace.mp4")
        try: os.symlink(self.roli, destino)
        except (OSError, NotImplementedError): self.skipTest("El SO no permite crear symlinks en este temporal.")
        with self.assertRaises(ValueError): self.org.ejecutar(plan["token"], True)
        self.assertTrue(os.path.islink(destino)); self.assertTrue(os.path.isfile(self.roli))
        registrar_evento_manifiesto_edicion(self.raiz, {**self.evento, "id_operacion": "otra", "ruta_destino": "videos completos/roli/Cancion/b.mp4"})
        self.assertFalse(any(c["ruta"] == "videos completos/roli" for c in self.org.candidatos(self.gestor._identidad())))

    def test_conteos_quitan_nivel_publicados_sin_cambiar_capitulo(self):
        self.crear("videos completos/videosPublicados/roli/Cancion/video.mp4")
        conteos = obtener_secciones_edicion(self.tmp, self.db)["conteos_capitulo"]
        self.assertEqual(conteos["Cancion"]["completos"], 1)
        self.assertNotIn("roli", conteos)

    def test_deshacer_con_ids_de_archivo_distintos_y_hash_igual(self):
        plan = self.antiguos(); result = self.org.ejecutar(plan["token"], True)
        original = self.org._foto
        def otro_montaje(raiz, ruta):
            foto = original(raiz, ruta)
            for e in foto: e["firma"][0] += 100; e["firma"][1] += 100
            return foto
        with patch.object(self.org, "_foto", side_effect=otro_montaje):
            for movimiento in result["completadas"]:
                self.org.deshacer(movimiento["id_organizacion"])
        self.assertTrue(os.path.isfile(self.publicado)); self.assertTrue(os.path.isfile(self.roli))

    def test_api_organizacion_exige_csrf_y_confirmacion_y_permite_deshacer(self):
        import http.client
        import json
        import threading
        from types import SimpleNamespace
        from bandeja.servidor import crear_servidor
        self.antiguos()
        self.gestor.config.puerto_servidor = 0
        server = crear_servidor(self.gestor.config, self.db, SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), token_csrf="sintetico")
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        def post(path, body, token=True):
            con = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            headers = {"Content-Type": "application/json"}
            if token: headers["X-CSRF-Token"] = "sintetico"
            try:
                con.request("POST", "/api/publicacion/" + path, json.dumps(body), headers)
                response = con.getresponse(); return response.status, json.loads(response.read())
            finally: con.close()
        try:
            api = server.RequestHandlerClass.publicacion
            candidatos = api.listar()["organizacion_pendiente"]
            seleccion = [{"id": c["id"], "personaje": c["personaje"] or "roli"} for c in candidatos]
            self.assertEqual(post("organizar-simular", {"seleccion": seleccion}, False)[0], 403)
            status, plan = post("organizar-simular", {"seleccion": seleccion}); self.assertEqual(status, 200)
            self.assertEqual(post("organizar", {"token": plan["token"], "confirmacion": False})[0], 409)
            self.assertTrue(os.path.isfile(self.publicado))
            status, result = post("organizar", {"token": plan["token"], "confirmacion": True})
            self.assertEqual(status, 200); self.assertTrue(result["exito"])
            for traslado in result["completadas"]:
                self.assertEqual(post("deshacer-organizacion", {"id_organizacion": traslado["id_organizacion"]})[0], 200)
            self.assertTrue(os.path.isfile(self.publicado))
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
