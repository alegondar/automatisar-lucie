#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_capcut.py

Pruebas unitarias para el vigilante pasivo de CapCut (bandeja/capcut.py).
Verifica:
1. Fotografía inicial en arranque: archivos preexistentes ignorados de por vida.
2. Detección no invasiva de nuevos exports (.mp4, .mov) sueltos y en subcarpetas (profundidad <= 3).
3. Descarte de archivos que excedan profundidad 3.
4. Omisión estricta de extensiones temporales (.tmp, .part, .crdownload, .tmp.mp4) y archivos ocultos.
5. Omisión de extensiones no multimedia (.txt, .json, etc.).
6. Ventana de estabilidad de tamaño (sondeos consecutivos requeridos).
7. Espera ante archivos bloqueados o en escritura exclusiva activa.
8. Invocación segura de callback de nuevos exports.
"""

import os
import tempfile
import time
import unittest
from unittest.mock import patch

from bandeja.capcut import VigilanteCapCut


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestVigilanteCapCut(unittest.TestCase):
    """Pruebas unitarias para VigilanteCapCut."""

    def setUp(self):
        self.tmp_dir_obj = tempfile.TemporaryDirectory(prefix="test_capcut_")
        self.tmp_dir = self.tmp_dir_obj.name
        self.addCleanup(self.tmp_dir_obj.cleanup)

    def _crear_archivo(self, ruta_relativa: str, contenido: bytes = b"contenido de video de prueba") -> str:
        ruta_abs = os.path.join(self.tmp_dir, ruta_relativa)
        os.makedirs(os.path.dirname(ruta_abs), exist_ok=True)
        with open(ruta_abs, "wb") as f:
            f.write(contenido)
        return ruta_abs

    def test_reexport_mismo_nombre_detectado_con_estabilidad(self):
        ruta = self._crear_archivo("1010(7).mp4", b"historico")
        vigilante = VigilanteCapCut(self.tmp_dir, sondeos_estabilidad=2)
        vigilante.tomar_fotografia_inicial()
        self.assertEqual(vigilante.escanear(), [])
        self._crear_archivo("1010(7).mp4", b"nuevo export de roli")
        self.assertEqual(vigilante.escanear(), [])
        self.assertEqual(len(vigilante.escanear()), 1)
        self.assertEqual(vigilante.escanear(), [])
        self._crear_archivo("1010(7).mp4", b"tercer export reemplazado")
        self.assertEqual(vigilante.escanear(), [])
        self.assertEqual(len(vigilante.escanear()), 1)

    def test_reexport_registrado_mientras_estaba_apagado(self):
        ruta = self._crear_archivo("1010(7).mp4", b"export actual")
        vigilante = VigilanteCapCut(self.tmp_dir, sondeos_estabilidad=1,
            exports_registrados=[{"ruta_origen": ruta, "tamano": 9999, "mtime": 1.0}])
        self.assertEqual(vigilante.escanear(), [])
        self.assertEqual(len(vigilante.escanear()), 1)

    def test_callback_fallido_se_reintenta_sin_perder_el_export(self):
        from unittest.mock import Mock
        callback = Mock(side_effect=[RuntimeError("base temporalmente ocupada"), None])
        vigilante = VigilanteCapCut(self.tmp_dir, sondeos_estabilidad=1, callback_nuevo_export=callback)
        vigilante.tomar_fotografia_inicial()
        self._crear_archivo("nuevo.mp4")
        self.assertEqual(len(vigilante.escanear()), 1)
        self.assertEqual(len(vigilante.escanear()), 1)
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(vigilante.escanear(), [])

    def test_fotografia_inicial_ignora_archivos_preexistentes(self):
        """Verifica que los archivos presentes al arrancar son ignorados permanentemente."""
        # Crear archivos históricos simulando ~45 exports viejos
        self._crear_archivo("0818(01).mp4", b"viejo1")
        self._crear_archivo("0818(02).mov", b"viejo2")
        self._crear_archivo(os.path.join("Subcarpeta1", "viejo3.mp4"), b"viejo3")

        vigilante = VigilanteCapCut(
            ruta_capcut=self.tmp_dir,
            sondeos_estabilidad=1,
        )
        conteo = vigilante.tomar_fotografia_inicial()
        self.assertEqual(conteo, 3)

        # Primer escaneo: nada nuevo
        nuevos = vigilante.escanear()
        self.assertEqual(len(nuevos), 0)

        # Crear nuevo archivo
        self._crear_archivo("0818(03).mp4", b"nuevo_video_capcut")
        nuevos = vigilante.escanear()
        self.assertEqual(len(nuevos), 1)
        self.assertEqual(nuevos[0]["nombre"], "0818(03).mp4")
        self.assertEqual(nuevos[0]["carpeta_relativa"], "")

        # Segundo escaneo: ya fue detectado, no se repite
        nuevos2 = vigilante.escanear()
        self.assertEqual(len(nuevos2), 0)

    def test_deteccion_en_subcarpetas_hasta_profundidad_3(self):
        """Detecta exports en subcarpetas hasta profundidad 3, ignora más profundos."""
        vigilante = VigilanteCapCut(
            ruta_capcut=self.tmp_dir,
            sondeos_estabilidad=1,
        )
        vigilante.tomar_fotografia_inicial()

        # Profundidad 1 (subcarpeta directa)
        self._crear_archivo(os.path.join("P1", "export1.mp4"), b"datos1")
        # Profundidad 2
        self._crear_archivo(os.path.join("P1", "P2", "export2.mp4"), b"datos2")
        # Profundidad 3
        self._crear_archivo(os.path.join("P1", "P2", "P3", "export3.mp4"), b"datos3")
        # Profundidad 4 (debe ser ignorado por exceder límite de 3)
        self._crear_archivo(os.path.join("P1", "P2", "P3", "P4", "export4.mp4"), b"datos4")

        nuevos = vigilante.escanear()
        nombres = {n["nombre"] for n in nuevos}
        self.assertIn("export1.mp4", nombres)
        self.assertIn("export2.mp4", nombres)
        self.assertIn("export3.mp4", nombres)
        self.assertNotIn("export4.mp4", nombres)

    def test_ignora_extensiones_temporales_y_ocultos(self):
        """Verifica que archivos temporales u ocultos no son detectados como exports."""
        vigilante = VigilanteCapCut(
            ruta_capcut=self.tmp_dir,
            sondeos_estabilidad=1,
            extensiones_temporales=[".tmp", ".part", ".crdownload", ".tmp.mp4"],
        )
        vigilante.tomar_fotografia_inicial()

        self._crear_archivo("video.tmp", b"temp")
        self._crear_archivo("video.part", b"part")
        self._crear_archivo("video.crdownload", b"crdownload")
        self._crear_archivo("video.tmp.mp4", b"tmp_mp4")
        self._crear_archivo(".oculto.mp4", b"oculto")
        self._crear_archivo("~temporal.mp4", b"temporal")
        self._crear_archivo("informe.txt", b"texto")
        self._crear_archivo("proyecto.capcut", b"proyecto")

        nuevos = vigilante.escanear()
        self.assertEqual(len(nuevos), 0)

    def test_ventana_estabilidad_tamano(self):
        """Requiere N sondeos consecutivos con tamaño inmutable antes de emitir el export."""
        vigilante = VigilanteCapCut(
            ruta_capcut=self.tmp_dir,
            sondeos_estabilidad=3,
        )
        vigilante.tomar_fotografia_inicial()

        ruta_vid = self._crear_archivo("render.mp4", b"tamano_inicial")

        # Sondeo 1: detectado por primera vez (conteo = 1)
        self.assertEqual(len(vigilante.escanear()), 0)

        # Modificamos tamaño (simula render en curso)
        with open(ruta_vid, "wb") as f:
            f.write(b"tamano_crecido_durante_exportacion")

        # Sondeo 2: tamaño cambió, conteo se reinicia a 1
        self.assertEqual(len(vigilante.escanear()), 0)

        # Sondeo 3: sin cambios (conteo = 2)
        self.assertEqual(len(vigilante.escanear()), 0)

        # Sondeo 4: sin cambios (conteo = 3 -> alcanza estabilidad)
        nuevos = vigilante.escanear()
        self.assertEqual(len(nuevos), 1)
        self.assertEqual(nuevos[0]["nombre"], "render.mp4")

    def test_espera_ante_archivo_bloqueado(self):
        """Si verificar_archivo_exclusivo retorna False, no lo emite hasta que se desbloquee."""
        vigilante = VigilanteCapCut(
            ruta_capcut=self.tmp_dir,
            sondeos_estabilidad=1,
        )
        vigilante.tomar_fotografia_inicial()
        self._crear_archivo("bloqueado.mp4", b"datos_bloqueados")

        # Simular que el archivo está siendo escrito por CapCut (bloqueado)
        with patch("bandeja.capcut.verificar_archivo_exclusivo", return_value=False):
            nuevos = vigilante.escanear()
            self.assertEqual(len(nuevos), 0)

        # Al liberarse, el escaneo lo reporta
        with patch("bandeja.capcut.verificar_archivo_exclusivo", return_value=True):
            nuevos = vigilante.escanear()
            self.assertEqual(len(nuevos), 1)
            self.assertEqual(nuevos[0]["nombre"], "bloqueado.mp4")

    def test_callback_nuevo_export(self):
        """Verifica que el callback se ejecuta al detectar un export estabilizado."""
        llamadas = []

        def callback_prueba(info):
            llamadas.append(info)

        vigilante = VigilanteCapCut(
            ruta_capcut=self.tmp_dir,
            sondeos_estabilidad=1,
            callback_nuevo_export=callback_prueba,
        )
        vigilante.tomar_fotografia_inicial()

        self._crear_archivo("evento.mp4", b"datos")
        nuevos = vigilante.escanear()
        self.assertEqual(len(nuevos), 1)
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(llamadas[0]["nombre"], "evento.mp4")

    def test_carpeta_inexistente_no_genera_excepcion(self):
        """Si la carpeta de CapCut no existe, el escaneo no arroja error y retorna vacío."""
        ruta_inexistente = os.path.join(self.tmp_dir, "no_existe")
        vigilante = VigilanteCapCut(
            ruta_capcut=ruta_inexistente,
            sondeos_estabilidad=1,
        )
        self.assertEqual(vigilante.tomar_fotografia_inicial(), 0)
        self.assertEqual(vigilante.escanear(), [])

    @unittest.skipUnless(os.name == "nt", "Requiere la semantica de comparticion de archivos de Windows")
    def test_export_en_subcarpeta_espera_cierre_del_escritor(self):
        vigilante = VigilanteCapCut(ruta_capcut=self.tmp_dir, sondeos_estabilidad=1)
        self.assertEqual(vigilante.tomar_fotografia_inicial(), 0)
        ruta = os.path.join(self.tmp_dir, "Proyecto (01)", "Exports", "0818(15).mp4")
        os.makedirs(os.path.dirname(ruta))
        contenido = b"export temporal de CapCut"
        with open(ruta, "xb") as escritor:
            escritor.write(contenido)
            escritor.flush()
            self.assertEqual(vigilante.escanear(), [], "No debe emitir un export abierto para escritura")
        nuevos = vigilante.escanear()
        self.assertEqual(len(nuevos), 1)
        self.assertEqual(nuevos[0]["nombre"], "0818(15).mp4")
        self.assertEqual(nuevos[0]["ruta_absoluta"], ruta)
        self.assertEqual(nuevos[0]["carpeta_relativa"], os.path.join("Proyecto (01)", "Exports"))
        self.assertEqual(nuevos[0]["tamano"], len(contenido))
        self.assertEqual(vigilante.escanear(), [])
        with open(ruta, "rb") as lector:
            self.assertEqual(lector.read(), contenido)

    def test_vigilante_capcut_nombres_con_parentesis_y_subcarpetas(self):
        """Ejercita el vigilante con nombres de export estilo CapCut '0818(15).mp4' y subcarpetas anidadas."""
        vigilante = VigilanteCapCut(
            ruta_capcut=self.tmp_dir,
            sondeos_estabilidad=1,
        )
        vigilante.tomar_fotografia_inicial()

        # Archivo con paréntesis en la raíz
        self._crear_archivo("0818(15).mp4", b"video raiz 15")
        # Archivo con paréntesis en subcarpeta
        self._crear_archivo(os.path.join("Proyecto (01)", "0818(16).mp4"), b"video subcarpeta 16")
        # Archivo con paréntesis en subcarpeta de profundidad 2
        self._crear_archivo(os.path.join("Proyecto (01)", "Exportados", "0818(17).mov"), b"video subcarpeta 17")

        nuevos = vigilante.escanear()
        self.assertEqual(len(nuevos), 3)

        nombres = {n["nombre"] for n in nuevos}
        self.assertEqual(nombres, {"0818(15).mp4", "0818(16).mp4", "0818(17).mov"})

        por_nombre = {n["nombre"]: n for n in nuevos}
        self.assertEqual(por_nombre["0818(15).mp4"]["carpeta_relativa"], "")
        self.assertEqual(por_nombre["0818(16).mp4"]["carpeta_relativa"], "Proyecto (01)")
        self.assertEqual(
            por_nombre["0818(17).mov"]["carpeta_relativa"],
            os.path.join("Proyecto (01)", "Exportados"),
        )

        # En segundo escaneo no debe volver a detectarlos
        nuevos_reintento = vigilante.escanear()
        self.assertEqual(len(nuevos_reintento), 0)


if __name__ == "__main__":
    unittest.main()
