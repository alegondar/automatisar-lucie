"""Limpieza limitada a padres vacíos de traslados registrados, en temporales."""
import os
import tempfile
import unittest
from unittest.mock import patch

from bandeja.carpetas_vacias import retirar_carpetas_vacias_traslado
from seguridad_anti_borrado import analizar_ast_codigo


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestCarpetasVacias(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="carpetas_vacias_")
        self.addCleanup(temporal.cleanup)
        self.raiz = temporal.name

    def origen(self, relativa):
        ruta = os.path.join(self.raiz, *relativa.split("/"))
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        return ruta

    def test_retira_solo_ancestros_conserva_personaje_y_capitulo_ajeno(self):
        origen = self.origen("videos sin editar/lucie/Cap/tomas/uno.mp4")
        ajena = self.origen("videos sin editar/lucie/Ajeno/dos.mp4")
        retiradas = retirar_carpetas_vacias_traslado(self.raiz, [origen])
        self.assertEqual(retiradas, [os.path.dirname(origen), os.path.dirname(os.path.dirname(origen))])
        self.assertTrue(os.path.isdir(os.path.dirname(ajena)))
        self.assertTrue(os.path.isdir(os.path.join(self.raiz, "videos sin editar", "lucie")))

    def test_contenido_nuevo_y_archivos_ocultos_se_conservan(self):
        origen = self.origen("videos ya editados/roli/Cap/uno.mp4")
        nuevo = os.path.join(os.path.dirname(origen), ".nuevo")
        with open(nuevo, "xb") as archivo:
            archivo.write(b"nuevo contenido")
        self.assertEqual(retirar_carpetas_vacias_traslado(self.raiz, [origen]), [])
        with open(nuevo, "rb") as archivo:
            self.assertEqual(archivo.read(), b"nuevo contenido")

    def test_resguardos_categorias_y_raices_no_se_retiraran(self):
        for relativa in ("_enviados/lucie/Cap/uno.mp4", "videos completos/lucie/Cap/uno.mp4",
                         "videos sin editar/lucie/uno.mp4", "videos completos/videos sin publicar/uno.mp4",
                         "videos completos/videos sin publicar/lucie/uno.mp4",
                         "videos sin editar/lucie/_resguardo/uno.mp4"):
            with self.subTest(relativa=relativa):
                origen = self.origen(relativa)
                self.assertEqual(retirar_carpetas_vacias_traslado(self.raiz, [origen]), [])
                self.assertTrue(os.path.isdir(os.path.dirname(origen)))

    def test_cola_retira_capitulo_conserva_personaje(self):
        origen = self.origen("videos completos/videos sin publicar/mailen/Cap/uno.mp4")
        self.assertEqual(retirar_carpetas_vacias_traslado(self.raiz, [origen]), [os.path.dirname(origen)])
        self.assertTrue(os.path.isdir(os.path.dirname(os.path.dirname(origen))))

    def test_error_y_junction_no_se_siguen(self):
        origen = self.origen("videos sin editar/roli/Cap/uno.mp4")
        with patch("bandeja.carpetas_vacias.os.rmdir", side_effect=PermissionError):
            self.assertEqual(retirar_carpetas_vacias_traslado(self.raiz, [origen]), [])
        with patch("bandeja.carpetas_vacias.os.path.isjunction", return_value=True, create=True), \
                patch("bandeja.carpetas_vacias.os.rmdir") as borrar:
            self.assertEqual(retirar_carpetas_vacias_traslado(self.raiz, [origen]), [])
            borrar.assert_not_called()
        self.assertTrue(os.path.isdir(os.path.dirname(origen)))

    def test_ast_admite_solo_rmdir_en_funcion_autorizada(self):
        permitido = "def retirar_carpetas_vacias_traslado(raiz, origenes):\n    os.rmdir(ruta)\n"
        self.assertEqual(analizar_ast_codigo(permitido, "bandeja/carpetas_vacias.py"), [])
        for codigo, archivo in ((permitido, "bandeja/otro.py"),
                                ("def otra():\n    os.rmdir(ruta)\n", "bandeja/carpetas_vacias.py"),
                                (permitido.replace("rmdir", "unlink"), "bandeja/carpetas_vacias.py")):
            with self.subTest(codigo=codigo, archivo=archivo):
                self.assertTrue(analizar_ast_codigo(codigo, archivo))
