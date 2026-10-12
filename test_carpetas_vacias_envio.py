"""Excepción de carpetas vacías: fixtures exclusivamente temporales."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bandeja.pendrive import _limpiar_carpetas_vacias_enviadas
from seguridad_anti_borrado import analizar_ast_codigo


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestCarpetasVaciasEnviadas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='carpetas_envio_')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / '_lucie'
        self.cap = self.base / 'lucie' / 'cap'
        (self.cap / 'videos').mkdir(parents=True)
        self.enviados = [{'personaje': 'lucie', 'capitulo': 'cap',
                         'ruta_origen_espera': str(self.cap / 'videos' / 'clip.mp4')}]

    def test_elimina_solo_capitulo_enviado_vacio_conserva_respaldo(self):
        otro = self.base / 'lucie' / 'otro'
        otro.mkdir()
        respaldo = self.base / '_enviados' / 'lucie' / 'cap' / 'video.mp4'
        respaldo.parent.mkdir(parents=True)
        respaldo.write_bytes(b'original')
        resultado = _limpiar_carpetas_vacias_enviadas(str(self.base), self.enviados)
        self.assertIn(str(self.cap), resultado)
        self.assertFalse(self.cap.exists())
        self.assertTrue(otro.is_dir())
        self.assertTrue((self.base / 'lucie').is_dir())
        self.assertEqual(respaldo.read_bytes(), b'original')

    def test_conserva_cualquier_archivo_incluso_oculto(self):
        archivo = self.cap / '.nota'
        archivo.write_bytes(b'conservar')
        _limpiar_carpetas_vacias_enviadas(str(self.base), self.enviados)
        self.assertTrue(self.cap.is_dir())
        self.assertEqual(archivo.read_bytes(), b'conservar')

    def test_sin_transferencias_no_elimina(self):
        self.assertEqual(_limpiar_carpetas_vacias_enviadas(str(self.base), []), [])
        self.assertTrue(self.cap.is_dir())

    def test_error_o_contenido_concurrente_conserva_directorio(self):
        with patch('bandeja.pendrive.os.rmdir', side_effect=OSError('ocupado')):
            self.assertEqual(_limpiar_carpetas_vacias_enviadas(str(self.base), self.enviados), [])
        self.assertTrue(self.cap.is_dir())

    def test_rechaza_escape_y_areas_de_respaldo(self):
        for r in [{'personaje': '..', 'capitulo': 'fuera'}, {'personaje': '_enviados', 'capitulo': 'lucie'}]:
            self.assertEqual(_limpiar_carpetas_vacias_enviadas(str(self.base), [r]), [])
        self.assertTrue(self.cap.is_dir())

    def test_no_limpia_capitulo_ajeno_al_origen_transferido(self):
        otro = self.base / 'lucie' / 'otro'
        otro.mkdir()
        registro = {**self.enviados[0], 'capitulo': 'otro'}
        self.assertEqual(_limpiar_carpetas_vacias_enviadas(str(self.base), [registro]), [])
        self.assertTrue(otro.is_dir())
        self.assertTrue(self.cap.is_dir())

    def test_ast_excepcion_solo_rmdir_en_funcion_autorizada(self):
        permitido = 'def _limpiar_carpetas_vacias_enviadas():\n    os.rmdir(ruta)\n'
        self.assertEqual(analizar_ast_codigo(permitido, 'bandeja/pendrive.py'), [])
        self.assertTrue(analizar_ast_codigo(permitido.replace('rmdir','unlink'), 'bandeja/pendrive.py'))
        self.assertTrue(analizar_ast_codigo(permitido.replace('_limpiar_carpetas_vacias_enviadas','otra'), 'bandeja/pendrive.py'))
        self.assertTrue(analizar_ast_codigo(permitido, 'otro.py'))


class TestNombresDocumentados(unittest.TestCase):
    def test_dias_y_semanas_del_mes_con_nombre_original(self):
        import datetime
        from bandeja.clasificacion import nombre_carpeta_documentado
        casos = [(1, "jueves", 1), (7, "miércoles", 1), (8, "jueves", 2),
                 (14, "miércoles", 2), (15, "jueves", 3), (21, "miércoles", 3),
                 (22, "jueves", 4), (28, "miércoles", 4), (29, "jueves", 5), (31, "sábado", 5)]
        for dia, nombre_dia, semana in casos:
            with self.subTest(dia=dia):
                self.assertEqual(nombre_carpeta_documentado("oloraculo", datetime.datetime(2026, 10, dia)),
                                 f"oloraculo - {nombre_dia} - semana {semana} - octubre - 2026")
        anterior = "oloraculo - lunes - semana 2 - octubre - 2026"
        self.assertEqual(nombre_carpeta_documentado(anterior, datetime.datetime(2027, 1, 1)), anterior)

    def test_simulacion_nueva_fechada_existente_preservada(self):
        from bandeja.config import ConfiguracionBandeja
        from bandeja.db import GestorBaseDatosBandeja
        from bandeja.movimientos import GestorMovimientosBandeja
        from bandeja.clasificacion import nombre_carpeta_documentado
        with tempfile.TemporaryDirectory(prefix="fecha_capitulo_") as tmp:
            desc = Path(tmp) / "descargas"; desc.mkdir()
            destino = desc / "_lucie"
            archivo = desc / "lucievideo.mp4"; archivo.write_bytes(b"video temporal")
            db = GestorBaseDatosBandeja(str(Path(tmp) / "memoria.sqlite"))
            mov = GestorMovimientosBandeja(str(desc), str(destino), db, str(Path(tmp) / "bit.jsonl"))
            sim = mov.simular_movimiento_lote([{"ruta": str(archivo)}], "lucie", "nuevo", documentar_fecha=True)
            self.assertEqual(sim["escena"], nombre_carpeta_documentado("nuevo"))
            self.assertIn(nombre_carpeta_documentado("nuevo"), sim["movimientos"][0]["destino"])
            (destino / "lucie" / "anterior").mkdir(parents=True)
            sim = mov.simular_movimiento_lote([{"ruta": str(archivo)}], "lucie", "anterior", documentar_fecha=True)
            self.assertEqual(sim["escena"], "anterior")
