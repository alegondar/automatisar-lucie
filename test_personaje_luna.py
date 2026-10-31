"""Luna usa los mismos contratos; todas las operaciones son temporales."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from bandeja.clasificacion import FiltroListaBlanca, asegurar_carpeta_capitulo
from bandeja.config import ConfiguracionBandeja
from bandeja.db import GestorBaseDatosBandeja
from bandeja.movimientos import GestorMovimientosBandeja


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestPersonajeLuna(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="luna_")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.desc = self.base / "Descargas"
        self.desc.mkdir()
        self.dest = self.desc / "_lucie"
        self.config = ConfiguracionBandeja(str(self.base / "config-ausente.json"), str(self.base / "local-ausente.json"))
        self.config.ruta_descargas = str(self.desc)
        self.config.ruta_destino_base = str(self.dest)
        self.db = GestorBaseDatosBandeja(str(self.base / "memoria.sqlite"))
        self.mov = GestorMovimientosBandeja(str(self.desc), str(self.dest), self.db,
                                          ruta_bitacora=str(self.base / "bitacora.jsonl"))

    def test_aliases_y_nombres_preservan_personaje_inicial(self):
        for archivo_alias in [str(self.base / "alias-ausente.json"), "alias-personajes.json"]:
            filtro = FiltroListaBlanca(self.config, archivo_alias)
            for nombre, esperado in [("Luna paseo.mp4", "luna"), ("lunaconlucie.jpg", "luna"),
                                     ("lucieconluna.mp4", "lucie"), ("roliconluna.mp3", "roli"),
                                     ("mailenconluna.webp", "mailen"), ("1010(5).mp4", None)]:
                with self.subTest(alias=archivo_alias, nombre=nombre):
                    self.assertEqual(filtro.obtener_personaje_de_alias_inicial(nombre), esperado)
            self.assertTrue(filtro.es_carpeta_escena_existente("Luna con Lucie"))
            self.assertEqual(filtro.obtener_personaje_de_carpeta_escena("Luna con Lucie"), "luna")
            self.assertEqual(filtro.obtener_personaje_de_carpeta_escena("Roli con Luna"), "roli")
            self.assertEqual(self.mov.calcular_base_escena("luna", "Luna paseo"), "lunapaseo")
            self.assertEqual(self.mov.calcular_base_escena("luna", "Lucie paseo"), "lunaluciepaseo")
        with self.assertRaises(ValueError):
            asegurar_carpeta_capitulo("desconocido", "Paseo", str(self.dest), str(self.desc))
        with open("alias-personajes.json", encoding="utf-8") as f:
            reglas = json.load(f)["reglas"]
        self.assertIn({"patrones": ["luna*"], "personaje": "luna", "destino_carpeta": "luna",
                       "requiere_confirmacion": False}, reglas)

    def test_selectores_estaticos_incluyen_luna(self):
        from html.parser import HTMLParser
        class Selectores(HTMLParser):
            def __init__(self):
                super().__init__()
                self.actual = None
                self.opciones = {}
            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == "select":
                    self.actual = a.get("id")
                    self.opciones[self.actual] = []
                elif tag == "option" and self.actual:
                    self.opciones[self.actual].append(a.get("value"))
            def handle_endtag(self, tag):
                if tag == "select":
                    self.actual = None
        html = Path("bandeja/web/panel.html").read_text()
        parser = Selectores()
        parser.feed(html)
        personajes = [opciones for opciones in parser.opciones.values() if "mailen" in opciones]
        self.assertEqual(len(personajes), 3)
        for opciones in personajes:
            self.assertIn("luna", opciones)
            self.assertEqual(len(opciones), len(set(opciones)))

    def test_envio_mixto_mensual_y_deshacer(self):
        from bandeja.config import calcular_sha256
        from bandeja.pendrive import simular_envio_capitulos, ejecutar_envio_pendrive, deshacer_envio_pendrive
        montaje = self.base / "pendrive"
        montaje.mkdir()
        raiz = montaje / "LucieSinReglas"
        raiz.mkdir()
        (montaje / ".lucie_pendrive.json").write_text(json.dumps({"id": "79a37814-00bd-42b3-bae2-89e7efcb0d6d", "creado": "2026-10-31T12:00:00", "version": 1}))
        self.config.rutas_candidatas_pendrive = [str(montaje)]
        self.config.margen_libre_bytes = 0
        cap = "Paseo - sábado - semana 5 - octubre - 2026"
        entradas = []
        for nombre in ["luna1.mp4", "luna2.jpg", "luna3.mp3"]:
            archivo = self.desc / nombre
            archivo.write_bytes(("contenido " + nombre).encode())
            entradas.append({"ruta": str(archivo), "tamanio": archivo.stat().st_size,
                             "hash": calcular_sha256(str(archivo))})
        plan_sala = self.mov.simular_movimiento_lote(entradas, "luna", cap)
        self.assertTrue(self.mov.ejecutar_movimiento_lote(plan_sala, "luna-mixto")["exito"])
        hashes = {Path(a["destino"]): calcular_sha256(a["destino"]) for a in plan_sala["movimientos"]}
        plan = simular_envio_capitulos(None, self.config, self.db, carpetas=["luna/" + cap])
        self.assertIn("a_copiar_cantidad", plan["totales"], plan)
        self.assertEqual(plan["totales"]["a_copiar_cantidad"], 3)
        self.assertTrue(all(p.exists() for p in hashes))
        resultado = ejecutar_envio_pendrive(plan, self.config, self.db, self.mov)
        self.assertTrue(resultado["exito"], resultado)
        for categoria, extension in [("videos sin editar", ".mp4"), ("imagenes", ".jpg"), ("audios", ".mp3")]:
            carpeta = raiz / categoria / "luna" / "octubre - 2026" / cap
            archivos = list(carpeta.glob("*" + extension))
            self.assertEqual(len(archivos), 1)
            self.assertIn(calcular_sha256(str(archivos[0])), hashes.values())
        inverso = deshacer_envio_pendrive(resultado["id_envio"], config=self.config, db=self.db, ruta_bitacora=self.mov.ruta_bitacora)
        self.assertTrue(inverso["exito"], inverso)
        for archivo, sha in hashes.items():
            self.assertEqual(calcular_sha256(str(archivo)), sha)
