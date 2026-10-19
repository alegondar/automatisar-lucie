"""Organización mensual con capítulos sintéticos y registros temporales."""
import datetime
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from bandeja.config import calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.edicion import (crear_sesion, finalizar_edicion_crudos, deshacer_finalizar_edicion,
                            obtener_carpeta_edicion, obtener_secciones_edicion,
                            registrar_evento_manifiesto_edicion)
from bandeja.organizacion_mensual import (OrganizadorMensual, nombre_mes, mes_del_nombre,
                                         partes_capitulo, resolver_ruta)
from bandeja.publicacion import GestorPublicacion


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestOrganizacionMensual(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="meses_")
        self.addCleanup(temporal.cleanup)
        self.tmp = temporal.name
        self.raiz = os.path.join(self.tmp, "LucieSinReglas")
        os.makedirs(self.raiz)
        with open(os.path.join(self.tmp, ".lucie_pendrive.json"), "x") as f:
            json.dump({"id": "sintetico", "version": 1}, f)
        self.db = GestorBaseDatosBandeja(os.path.join(self.tmp, "memoria.sqlite"))
        self.org = OrganizadorMensual(self.raiz, self.db)
        self.bitacora = os.path.join(self.tmp, "bitacora.jsonl")
        self.cap = "Café y canción - jueves - semana 3 - octubre - 2026"

    def crear(self, relativa, contenido=b"video sintetico"):
        ruta = os.path.join(self.raiz, *relativa.split("/"))
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "xb") as f: f.write(contenido)
        return ruta

    def test_nombres_mensuales_y_capitulos_anteriores(self):
        for n, mes in ((1, "enero"), (10, "octubre"), (12, "diciembre")):
            self.assertEqual(nombre_mes(datetime.datetime(2027, n, 1)), f"{mes} - 2027")
        self.assertEqual(mes_del_nombre(self.cap), "octubre - 2026")
        self.assertEqual(mes_del_nombre("videoyaeditado_Café_semana_3_noviembre_2026"), "noviembre - 2026")
        self.assertIsNone(mes_del_nombre("1010(7)"))
        self.assertEqual(partes_capitulo(["lucie", "octubre - 2026", self.cap, "uno.mp4"]), ("lucie", self.cap, 2))
        self.assertEqual(partes_capitulo(["lucie", self.cap, "uno.mp4"]), ("lucie", self.cap, 1))

    def test_simular_no_mueve_y_ejecutar_exige_confirmacion(self):
        original = self.crear("videos sin editar/lucie/" + self.cap + "/uno.mp4")
        plan = self.org.simular()
        self.assertEqual(len(plan["acciones"]), 1)
        destino = os.path.join(self.raiz, *plan["acciones"][0]["destino"].split("/"))
        self.assertTrue(os.path.isfile(original))
        self.assertFalse(os.path.exists(destino))
        with self.assertRaises(ValueError): self.org.ejecutar(plan)
        self.assertTrue(os.path.isfile(original))

    def test_categorias_y_colas_conservan_personajes_nombres_y_hashes(self):
        for base in self.org.BASES:
            for personaje in ("lucie", "roli", "mailen"):
                self.crear(base + "/" + personaje + "/" + self.cap + "/uno.mp4")
        plan = self.org.simular()
        self.assertEqual(len(plan["acciones"]), 21)
        self.org.ejecutar(plan, True)
        for a in plan["acciones"]:
            destino = os.path.join(self.raiz, *a["destino"].split("/"))
            self.assertEqual(os.path.basename(destino), self.cap)
            self.assertEqual(os.path.basename(os.path.dirname(destino)), "octubre - 2026")
            self.assertEqual(calcular_sha256(os.path.join(destino, "uno.mp4")), a["foto"][1]["sha256"])
            self.assertFalse(os.path.exists(os.path.join(self.raiz, *a["origen"].split("/"))))
        self.assertEqual(self.org.ejecutar(plan, True), [])
        self.assertEqual(self.org.candidatos(), [])

    def test_seleccion_no_mueve_otras_carpetas(self):
        uno = "videos sin editar/lucie/" + self.cap
        otro = "videos ya editados/roli/" + self.cap
        self.crear(uno + "/uno.mp4"); ajeno = self.crear(otro + "/otro.mp4")
        plan = self.org.simular([uno])
        self.org.ejecutar(plan, True)
        self.assertTrue(os.path.isfile(ajeno))
        self.assertEqual(len(self.org.candidatos()), 1)

    def test_sin_fecha_exige_mes_y_no_usa_mtime(self):
        carpeta = "videos sin editar/lucie/Sin fecha"
        original = self.crear(carpeta + "/uno.mp4")
        self.assertEqual(self.org.simular()["sin_fecha"], [carpeta])
        self.assertEqual(self.org.simular()["acciones"], [])
        with self.assertRaises(ValueError): self.org.simular([carpeta])
        plan = self.org.simular([carpeta], {carpeta: "enero - 2027"})
        self.assertIn("/enero - 2027/", plan["acciones"][0]["destino"])
        self.assertTrue(os.path.isfile(original))

    def test_mes_de_registro_inequivoco_y_ambiguo(self):
        carpeta = "videos ya editados/lucie/Capitulo antiguo"
        self.crear(carpeta + "/uno.mp4")
        registrar_evento_manifiesto_edicion(self.raiz, {"ruta_destino": carpeta + "/uno.mp4", "fecha": "2026-09-18T10:00:00"})
        self.assertIn("/septiembre - 2026/", self.org.simular()["acciones"][0]["destino"])
        registrar_evento_manifiesto_edicion(self.raiz, {"ruta_destino": carpeta + "/otro.mp4", "fecha": "2026-10-18T10:00:00"})
        self.assertEqual(self.org.simular()["sin_fecha"], [carpeta])

    def test_colision_no_fusiona_ni_sobrescribe(self):
        carpeta = "videos sin editar/lucie/" + self.cap
        original = self.crear(carpeta + "/uno.mp4")
        plan = self.org.simular()
        ocupado = self.crear(plan["acciones"][0]["destino"] + "/anterior.mp4", b"anterior")
        with self.assertRaises(FileExistsError): self.org.ejecutar(plan, True)
        with self.assertRaises(FileExistsError): self.org.simular()
        self.assertTrue(os.path.isfile(original))
        with open(ocupado, "rb") as f: self.assertEqual(f.read(), b"anterior")

    def test_archivo_nuevo_o_cambiado_bloquea_todo_el_plan(self):
        a = "videos sin editar/lucie/" + self.cap
        b = "videos ya editados/roli/" + self.cap
        primero = self.crear(a + "/uno.mp4")
        self.crear(b + "/dos.mp4")
        plan = self.org.simular()
        self.crear(b + "/nuevo.txt", b"contenido nuevo")
        with self.assertRaises(ValueError): self.org.ejecutar(plan, True)
        self.assertTrue(os.path.isfile(primero))

    def test_original_en_uso_no_se_fuerza_ni_mueve(self):
        original = self.crear("videos sin editar/lucie/" + self.cap + "/uno.mp4")
        plan = self.org.simular()
        with patch("bandeja.plataforma.verificar_archivo_exclusivo", return_value=False):
            with self.assertRaises(ValueError): self.org.ejecutar(plan, True)
        self.assertTrue(os.path.isfile(original))

    def test_identidad_distinta_y_destino_fuera_del_plan_rechazados(self):
        original = self.crear("videos sin editar/lucie/" + self.cap + "/uno.mp4")
        plan = self.org.simular()
        plan["acciones"][0]["destino"] = "_enviados/otra"
        with self.assertRaises(ValueError): self.org.ejecutar(plan, True)
        plan = self.org.simular()
        with open(os.path.join(self.tmp, ".lucie_pendrive.json"), "w") as f: f.write("otro pendrive")
        with self.assertRaises(ValueError): self.org.ejecutar(plan, True)
        self.assertTrue(os.path.isfile(original))

    def test_deshacer_registrado_conserva_contenido_y_rutas_resueltas(self):
        original = self.crear("videos sin editar/lucie/" + self.cap + "/uno.mp4")
        plan = self.org.simular()
        a = self.org.ejecutar(plan, True)[0]
        nueva = resolver_ruta(self.raiz, original)
        self.assertTrue(os.path.isfile(nueva))
        self.assertNotEqual(nueva, original)
        self.org.ejecutar(self.org.simular_deshacer(a["id"]), True)
        self.assertTrue(os.path.isfile(original))
        self.assertEqual(resolver_ruta(self.raiz, original), original)

    def test_deshacer_rechaza_origen_ocupado_o_contenido_agregado(self):
        original = self.crear("videos sin editar/lucie/" + self.cap + "/uno.mp4")
        a = self.org.ejecutar(self.org.simular(), True)[0]
        self.crear(a["origen"] + "/ajeno.txt")
        with self.assertRaises(FileExistsError): self.org.simular_deshacer(a["id"])
        self.assertTrue(os.path.isfile(resolver_ruta(self.raiz, original)))

    def test_recuperacion_despues_de_mover_antes_de_registrar(self):
        original = self.crear("videos sin editar/lucie/" + self.cap + "/uno.mp4")
        plan = self.org.simular()
        from bandeja.edicion import registrar_evento_manifiesto_edicion as registrar
        def fallar(raiz, evento):
            if evento["tipo_evento"] == "organizacion_mensual_completada": raise OSError("registro interrumpido")
            registrar(raiz, evento)
        with patch("bandeja.edicion.registrar_evento_manifiesto_edicion", side_effect=fallar):
            with self.assertRaises(OSError): self.org.ejecutar(plan, True)
        self.assertFalse(os.path.exists(original))
        self.assertEqual(len(self.org.ejecutar(plan, True)), 1)
        self.assertTrue(os.path.isfile(resolver_ruta(self.raiz, original)))

    def test_sesion_anterior_sigue_editando_finaliza_y_deshace_tras_organizar(self):
        clip = "lucie/" + self.cap + "/uno.mp4"
        original = self.crear("videos sin editar/" + clip)
        sesion = crear_sesion(self.db, [clip], "lucie", self.cap, "Café")
        self.org.ejecutar(self.org.simular(), True)
        carpeta = obtener_carpeta_edicion(sesion, self.tmp)
        self.assertIn("octubre - 2026", carpeta)
        self.assertEqual(obtener_secciones_edicion(self.tmp, self.db)["para_editar"], [])
        args = (self.db, sesion["id"], self.tmp, "LucieSinReglas", self.bitacora)
        resultado = finalizar_edicion_crudos(*args)
        self.assertTrue(resultado["exito"], resultado)
        self.assertTrue(deshacer_finalizar_edicion(*args)["exito"])
        self.assertTrue(os.path.isfile(resolver_ruta(self.raiz, original)))

    def test_historial_wifi_y_cache_apuntan_a_rutas_mensuales(self):
        relativa = "videos completos/videosPublicados/lucie/" + self.cap + "/Café.mp4"
        original = self.crear(relativa)
        sesion = crear_sesion(self.db, ["lucie/" + self.cap + "/uno.mp4"], "lucie", self.cap)
        self.db.actualizar_sesion_edicion(sesion["id"], estado="completado", video_completo_ruta=original)
        registrar_evento_manifiesto_edicion(self.raiz, {"tipo_evento": "publicado_por_envio_wifi", "id_operacion": "envio",
            "ruta_origen": "videos completos/videos sin publicar/lucie/" + self.cap + "/Café.mp4", "ruta_destino": relativa,
            "sha256": calcular_sha256(original), "personaje": "lucie"})
        self.org.ejecutar(self.org.simular(), True)
        actual = self.db.obtener_sesion_por_id(sesion["id"])["video_completo_ruta"]
        self.assertTrue(os.path.isfile(actual))
        self.assertEqual(actual, resolver_ruta(self.raiz, original))
        gestor = GestorPublicacion(None, self.db)
        self.assertIn("/octubre - 2026/", gestor._historial(self.raiz)[0]["ruta_destino"])
        st = os.stat(self.raiz)
        with patch.object(gestor, "_identidad", return_value=("sintetico", self.raiz, st.st_dev, st.st_ino)):
            deshecho = gestor.deshacer("envio")
        self.assertTrue(deshecho["exito"])
        self.assertTrue(os.path.isfile(deshecho["destino"]))
        self.assertEqual(self.db.obtener_sesion_por_id(sesion["id"])["video_completo_ruta"], deshecho["destino"])
        self.assertEqual(gestor._historial(self.raiz), [])

    def test_audio_de_sesion_antigua_se_abre_finaliza_y_deshace_tras_organizar(self):
        clip = "audios/roli/" + self.cap + "/canción.MP3"
        original = self.crear(clip, b"audio sintetico")
        sesion = crear_sesion(self.db, [clip], "roli", self.cap, "Canción")
        self.org.ejecutar(self.org.simular(), True)
        actual = resolver_ruta(self.raiz, original)
        self.assertEqual(obtener_carpeta_edicion(sesion, self.tmp), os.path.dirname(actual))
        self.assertEqual(obtener_secciones_edicion(self.tmp, self.db)["para_editar"], [])
        args = (self.db, sesion["id"], self.tmp, "LucieSinReglas", self.bitacora)
        resultado = finalizar_edicion_crudos(*args)
        self.assertTrue(resultado["exito"], resultado)
        self.assertEqual(len(resultado["movidos"]), 1)
        self.assertFalse(os.path.exists(actual))
        self.assertTrue(deshacer_finalizar_edicion(*args)["exito"])
        with open(actual, "rb") as f:
            self.assertEqual(f.read(), b"audio sintetico")

    def test_imagen_y_audio_sin_sesion_se_listan_y_revierten_por_mes(self):
        imagen = self.crear("imagenes/lucie/" + self.cap + "/foto.jpg", b"foto sintetica")
        audio = self.crear("audios/lucie/" + self.cap + "/voz.mp3", b"voz sintetica")
        plan = self.org.simular()
        self.assertEqual(len(plan["acciones"]), 2)
        self.org.ejecutar(plan, True)
        entrada = obtener_secciones_edicion(self.tmp, self.db)["para_editar"][0]
        self.assertEqual(entrada["capitulo"], self.cap)
        self.assertEqual(entrada["ruta_relativa"], "audios/lucie/octubre - 2026/" + self.cap + "/voz.mp3")
        self.assertTrue(os.path.isfile(resolver_ruta(self.raiz, imagen)))
        for accion in plan["acciones"]:
            self.org.ejecutar(self.org.simular_deshacer(accion["id"]), True)
        self.assertEqual(resolver_ruta(self.raiz, imagen), imagen)
        self.assertEqual(resolver_ruta(self.raiz, audio), audio)
        self.assertTrue(os.path.isfile(imagen))
        self.assertTrue(os.path.isfile(audio))

    def test_no_sigue_enlaces_a_capitulos_externos(self):
        afuera = os.path.join(self.tmp, "afuera")
        os.makedirs(afuera)
        padre = os.path.join(self.raiz, "videos sin editar", "lucie")
        os.makedirs(padre)
        try: os.symlink(afuera, os.path.join(padre, self.cap), target_is_directory=True)
        except OSError as e: self.skipTest(f"Capacidad de symlinks ausente: {e}")
        self.assertEqual(self.org.candidatos(), [])
