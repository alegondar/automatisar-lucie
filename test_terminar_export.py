"""Regresiones del cierre de edición con exports exclusivamente temporales."""
import datetime
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.edicion import (crear_sesion, finalizar_edicion_crudos, revisar_export_terminado,
                            obtener_secciones_edicion, deshacer_copia_completo)
from bandeja_descargas import crear_vigilante_capcut


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestTerminarExport(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="terminar_export_")
        self.addCleanup(temporal.cleanup)
        self.base = temporal.name
        self.montaje = os.path.join(self.base, "pendrive")
        self.raiz = os.path.join(self.montaje, "LucieSinReglas")
        self.capcut = os.path.join(self.base, "CapCut")
        os.makedirs(self.capcut)
        self.config = ConfiguracionBandeja(ruta_config=os.path.join(self.base, "no.json"),
                                          ruta_config_local=os.path.join(self.base, "no-local.json"))
        self.config.carpeta_exportacion_capcut = self.capcut
        self.db = GestorBaseDatosBandeja(os.path.join(self.base, "db.sqlite"))
        self.bitacora = os.path.join(self.base, "bitacora.jsonl")
        self.inicio = datetime.datetime.now() - datetime.timedelta(minutes=5)
        self.sesion = self.crear_sesion("Cafe", self.inicio)
        self.pen = patch("bandeja_descargas.detectar_pendrive",
                         return_value={"conectado": True, "punto_montaje": self.montaje})
        self.pen.start()
        self.addCleanup(self.pen.stop)

    def crear_sesion(self, nombre, inicio):
        rel = f"lucie/{nombre}/clip.mp4"
        ruta = os.path.join(self.raiz, "videos sin editar", *rel.split("/"))
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "xb") as archivo:
            archivo.write(b"clip original")
        sesion = crear_sesion(self.db, [rel], "lucie", nombre, nombre)
        self.db.actualizar_sesion_edicion(sesion["id"], fecha_creacion=inicio.isoformat())
        return self.db.obtener_sesion_por_id(sesion["id"])

    def export(self, nombre="1014.mp4", fecha=None, registrar=True, **campos):
        ruta = os.path.join(self.capcut, nombre)
        with open(ruta, "xb") as archivo:
            archivo.write(b"video final distinto de los clips")
        ts = (fecha or (self.inicio + datetime.timedelta(minutes=1))).timestamp()
        os.utime(ruta, (ts, ts))
        st = os.stat(ruta)
        if registrar:
            identificador = self.db.registrar_export_pendiente(ruta, nombre, st.st_size, st.st_mtime)
            if campos:
                self.db.actualizar_export_pendiente(identificador, **campos)
        return ruta

    def terminar(self, sesion=None):
        sesion = sesion or self.sesion
        resultado = finalizar_edicion_crudos(self.db, sesion["id"], self.montaje, "LucieSinReglas", self.bitacora)
        self.assertTrue(resultado["exito"], resultado)
        return self.db.obtener_sesion_por_id(sesion["id"])

    def revisar(self, automatico=True):
        return revisar_export_terminado(self.db, self.sesion["id"], self.montaje,
                                        "LucieSinReglas", self.bitacora, automatico, self.capcut)

    def test_export_registrado_se_copia_al_terminar_y_no_duplica(self):
        origen = self.export()
        self.terminar()
        resultado = self.revisar()
        self.assertEqual(resultado["modo"], "copiado", resultado)
        self.assertIn(os.path.join("videos completos", "videos sin publicar", "lucie"), resultado["destino"])
        self.assertEqual(calcular_sha256(origen), calcular_sha256(resultado["destino"]))
        self.assertTrue(os.path.isfile(origen))
        self.assertEqual(self.revisar()["destino"], resultado["destino"])
        self.assertEqual(self.db.obtener_exports_pendientes()[0]["estado"], "copiado")
        self.assertEqual(obtener_secciones_edicion(self.montaje, self.db)["sesiones_esperando_export"], [])

    def test_export_preexistente_de_sesion_se_recupera_tras_reinicio(self):
        origen = self.export(registrar=False)
        historico = self.export("antiguo.mp4", self.inicio - datetime.timedelta(days=1), registrar=False)
        self.terminar()
        vigilante = crear_vigilante_capcut(self.config, self.db, self.bitacora)
        vigilante.tomar_fotografia_inicial()
        for _ in range(5):
            vigilante.escanear()
        sesion = self.db.obtener_sesion_por_id(self.sesion["id"])
        self.assertEqual(calcular_sha256(origen), calcular_sha256(sesion["video_completo_ruta"]))
        self.assertTrue(os.path.isfile(historico))
        self.assertEqual(len(self.db.obtener_exports_pendientes()), 1)

    def test_export_en_escritura_no_se_copia_hasta_quedar_libre(self):
        origen = self.export(registrar=False)
        self.terminar()
        vigilante = crear_vigilante_capcut(self.config, self.db, self.bitacora)
        vigilante.tomar_fotografia_inicial()
        with patch("bandeja.capcut.verificar_archivo_exclusivo", return_value=False):
            for _ in range(5):
                vigilante.escanear()
        self.assertIsNone(self.db.obtener_sesion_por_id(self.sesion["id"])["video_completo_ruta"])
        self.assertEqual(self.db.obtener_exports_pendientes(), [])
        vigilante.escanear()
        self.assertEqual(calcular_sha256(origen), calcular_sha256(self.db.obtener_sesion_por_id(self.sesion["id"])["video_completo_ruta"]))

    def test_dos_exports_no_se_eligen_y_se_ofrecen_para_asignacion_manual(self):
        self.export("uno.mp4", registrar=False)
        self.export("dos.mp4", registrar=False)
        self.terminar()
        vigilante = crear_vigilante_capcut(self.config, self.db, self.bitacora)
        vigilante.tomar_fotografia_inicial()
        for _ in range(5):
            vigilante.escanear()
        exports = self.db.obtener_exports_pendientes()
        self.assertEqual(len(exports), 2)
        self.assertTrue(all(e["sesion_id"] is None and e["estado"] == "sin_asignar"
                            and e["envio_automatico_bloqueado"] for e in exports))
        self.assertIsNone(self.db.obtener_sesion_por_id(self.sesion["id"])["video_completo_ruta"])
        self.assertFalse(os.path.exists(os.path.join(self.raiz, "videos completos")))

    def test_sesion_antigua_pendiente_no_impide_recuperar_sesion_confirmada(self):
        antigua = self.crear_sesion("Antigua", self.inicio - datetime.timedelta(days=2))
        self.terminar(antigua)
        self.db.actualizar_sesion_edicion(antigua["id"], fecha_cierre=(self.inicio - datetime.timedelta(days=1)).isoformat())
        origen = self.export(registrar=False)
        self.terminar()
        vigilante = crear_vigilante_capcut(self.config, self.db, self.bitacora)
        vigilante.tomar_fotografia_inicial()
        for _ in range(5):
            vigilante.escanear()
        self.assertEqual(calcular_sha256(origen), calcular_sha256(self.db.obtener_sesion_por_id(self.sesion["id"])["video_completo_ruta"]))
        self.assertIsNone(self.db.obtener_sesion_por_id(antigua["id"])["export_asociado"])

    def test_modo_manual_y_deshacer_no_se_reenvian_automaticamente(self):
        origen = self.export(sesion_id=self.sesion["id"])
        self.terminar()
        self.assertEqual(self.revisar(automatico=False)["modo"], "esperando_envio")
        self.assertFalse(os.path.exists(os.path.join(self.raiz, "videos completos")))
        resultado = self.revisar()
        deshacer_copia_completo(resultado["destino"], self.montaje, self.db, "LucieSinReglas", self.bitacora)
        vigilante = crear_vigilante_capcut(self.config, self.db, self.bitacora)
        vigilante.tomar_fotografia_inicial()
        for _ in range(5):
            vigilante.escanear()
        self.assertFalse(os.path.exists(resultado["destino"]))
        self.assertTrue(os.path.isfile(origen))
        self.assertTrue(self.db.obtener_exports_pendientes()[0]["envio_automatico_bloqueado"])

    def test_sin_export_y_ventanas_superpuestas_no_adivina(self):
        self.terminar()
        self.assertEqual(self.revisar()["modo"], "esperando_export")
        self.assertEqual(len(obtener_secciones_edicion(self.montaje, self.db)["sesiones_esperando_export"]), 1)
        self.crear_sesion("Otra", self.inicio)
        self.export()
        self.assertEqual(self.revisar()["modo"], "ambiguo")
        self.assertIsNone(self.db.obtener_sesion_por_id(self.sesion["id"])["export_asociado"])

    def test_error_copia_queda_visible_y_encolado(self):
        self.export(sesion_id=self.sesion["id"])
        self.terminar()
        with patch("bandeja.edicion.copiar_export_a_videos_completos", side_effect=OSError("sin espacio")):
            resultado = self.revisar()
        self.assertEqual(resultado["modo"], "error")
        self.assertIn("sin espacio", resultado["mensaje"])
        exp = self.db.obtener_exports_pendientes()[0]
        self.assertEqual(exp["estado"], "pendiente_copia")
        self.assertEqual(exp["error"], "sin espacio")

    def test_export_asociado_fuera_de_capcut_no_se_copia(self):
        origen = os.path.join(self.base, "ajeno.mp4")
        with open(origen, "xb") as archivo:
            archivo.write(b"material ajeno")
        st = os.stat(origen)
        self.db.registrar_export_pendiente(origen, "ajeno.mp4", st.st_size, st.st_mtime, sesion_id=self.sesion["id"])
        self.terminar()
        self.assertEqual(self.revisar()["modo"], "error")
        self.assertIsNone(self.db.obtener_sesion_por_id(self.sesion["id"])["video_completo_ruta"])
        with open(origen, "rb") as archivo:
            self.assertEqual(archivo.read(), b"material ajeno")

    def test_modo_manual_no_importa_preexistentes_al_reiniciar(self):
        origen = self.export(registrar=False)
        self.terminar()
        self.config.envio_exports_capcut = "manual"
        vigilante = crear_vigilante_capcut(self.config, self.db, self.bitacora)
        vigilante.tomar_fotografia_inicial()
        for _ in range(5):
            vigilante.escanear()
        self.assertEqual(self.db.obtener_exports_pendientes(), [])
        self.assertIsNone(self.db.obtener_sesion_por_id(self.sesion["id"])["video_completo_ruta"])
        self.assertTrue(os.path.isfile(origen))

    def test_sesion_anterior_sin_solicitud_no_importa_exports_historicos(self):
        origen = self.export(registrar=False)
        self.terminar()
        self.db.actualizar_sesion_edicion(self.sesion["id"], revision_export_solicitada=0)
        vigilante = crear_vigilante_capcut(self.config, self.db, self.bitacora)
        vigilante.tomar_fotografia_inicial()
        for _ in range(5):
            vigilante.escanear()
        self.assertEqual(self.db.obtener_exports_pendientes(), [])
        self.assertIsNone(self.db.obtener_sesion_por_id(self.sesion["id"])["video_completo_ruta"])
        self.assertTrue(os.path.isfile(origen))

    def test_migracion_conserva_sesion_anterior_sin_autorizar_revision(self):
        ruta = os.path.join(self.base, "anterior.sqlite")
        with closing(sqlite3.connect(ruta)) as con:
            con.execute("CREATE TABLE sesiones_edicion (id INTEGER PRIMARY KEY, identificador TEXT, nombre TEXT, nombre_final_defecto TEXT, personaje TEXT, capitulo TEXT, estado TEXT, clips_json TEXT, export_asociado TEXT, video_completo_ruta TEXT, fecha_creacion TEXT, fecha_cierre TEXT)")
            con.execute("INSERT INTO sesiones_edicion VALUES (42, 'sesion-previa', 'Anterior', 'Anterior.mp4', 'lucie', 'Anterior', 'editado', '[]', NULL, NULL, ?, ?)",
                        (self.inicio.isoformat(), datetime.datetime.now().isoformat()))
            con.commit()
        db = GestorBaseDatosBandeja(ruta)
        sesion = db.obtener_sesion_por_id(42)
        self.assertEqual(sesion["nombre"], "Anterior")
        self.assertEqual(sesion["estado"], "editado")
        self.assertEqual(sesion["clips"], [])
        self.assertEqual(sesion["revision_export_solicitada"], 0)
        self.assertEqual(GestorBaseDatosBandeja(ruta).obtener_sesion_por_id(42), sesion)
