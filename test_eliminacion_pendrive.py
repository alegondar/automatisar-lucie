"""Regresiones del borrado manual: todas las operaciones usan temporales."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.eliminacion import GestorEliminacionPendrive
from bandeja.servidor import crear_servidor
from bandeja.pendrive import operacion_pendrive_exclusiva
from seguridad_anti_borrado import analizar_ast_codigo


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestEliminacionManual(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='eliminacion_manual_')
        self.addCleanup(self.tmp.cleanup)
        self.montaje = Path(self.tmp.name)
        self.raiz = self.montaje / 'LucieSinReglas'
        self.raiz.mkdir()
        self.id = str(uuid.uuid4())
        self.marcador = self.montaje / '.lucie_pendrive.json'
        self.marcador.write_text(json.dumps({'id': self.id, 'creado': '2026-10-11T12:00:00', 'version': 1}))
        self.config = ConfiguracionBandeja(ruta_config=str(self.montaje / 'no-config.json'),
                                          ruta_config_local=str(self.montaje / 'no-local.json'))
        self.config.rutas_candidatas_pendrive = [str(self.montaje)]
        self.gestor = GestorEliminacionPendrive(self.config)
        self.clip = self.crear('videos sin editar/lucie/cap (01)/0818(15).mp4')
        self.otro = self.crear('videos completos/lucie/conservar/final.mp4')
        self.manifiesto = self.crear('.lucie/manifiesto.jsonl', b'{"evento":"previo"}\n')
        self.manifiesto_inicial = self.manifiesto.read_bytes()

    def crear(self, rel, contenido=b'contenido original'):
        p = self.raiz / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('xb') as f:
            f.write(contenido)
        return p

    def test_simular_y_listar_no_alteran_datos(self):
        antes = self.clip.read_bytes()
        listado = self.gestor.listar()
        self.assertEqual(listado['ruta_proyecto'], str(self.raiz))
        self.assertTrue(all(e['tipo'] in ('carpeta', 'archivo') for e in listado['entradas']))
        self.assertIn('videos sin editar/lucie/cap (01)/0818(15).mp4',
                      [e['ruta'] for e in listado['entradas']])
        self.assertNotIn('.lucie/manifiesto.jsonl', [e['ruta'] for e in listado['entradas']])
        plan = self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        self.assertEqual(len(plan['entradas']), 2)
        self.assertEqual(plan['total_bytes'], len(antes))
        self.assertEqual(self.clip.read_bytes(), antes)
        self.assertEqual(self.manifiesto.read_bytes(), self.manifiesto_inicial)
        self.assertFalse((self.raiz / '.lucie/eliminaciones.jsonl').exists())

    def test_borra_solo_seleccion_y_registra_sin_tocar_manifiesto(self):
        plan = self.gestor.simular(['videos sin editar/lucie/cap (01)',
                                    'videos sin editar/lucie/cap (01)/0818(15).mp4'])
        resultado = self.gestor.ejecutar(plan['token'], 'ELIMINAR')
        self.assertTrue(resultado['exito'])
        self.assertEqual(len(resultado['eliminados']), 2)
        self.assertFalse(self.clip.parent.exists())
        self.assertTrue(self.otro.exists())
        self.assertTrue(self.raiz.exists())
        self.assertTrue(self.marcador.exists())
        self.assertEqual(self.manifiesto.read_bytes(), self.manifiesto_inicial)
        eventos = [json.loads(l) for l in (self.raiz / '.lucie/eliminaciones.jsonl').read_text().splitlines()]
        self.assertEqual(eventos[0]['evento'], 'eliminacion_manual_confirmada')
        self.assertEqual(len(eventos), 3)
        with self.assertRaises(ValueError):
            self.gestor.ejecutar(plan['token'], 'ELIMINAR')

    def test_listado_multimedia_filtra_otros_archivos(self):
        self.crear('imagenes/lucie/cap/foto.JPG')
        self.crear('audios/lucie/cap/voz.MP3')
        self.crear('imagenes/lucie/cap/notas.txt')
        entradas = {e['ruta']: e for e in self.gestor.listar()['entradas']}
        self.assertEqual(entradas['imagenes/lucie/cap/foto.JPG']['formato'], 'imagen')
        self.assertEqual(entradas['audios/lucie/cap/voz.MP3']['formato'], 'audio')
        self.assertEqual(entradas['videos sin editar/lucie/cap (01)/0818(15).mp4']['formato'], 'video')
        self.assertNotIn('imagenes/lucie/cap/notas.txt', entradas)

    def test_eliminar_archivos_individuales_preserva_carpeta_y_resto(self):
        rutas = ['videos sin editar/lucie/cap (01)/otro.mp4',
                 'videos sin editar/lucie/cap (01)/foto.png',
                 'videos sin editar/lucie/cap (01)/voz.mp3']
        archivos = [self.crear(r) for r in rutas]
        plan = self.gestor.simular(rutas)
        self.assertEqual({e['ruta'] for e in plan['entradas']}, set(rutas))
        resultado = self.gestor.ejecutar(plan['token'], 'ELIMINAR')
        self.assertTrue(resultado['exito'])
        self.assertEqual(set(resultado['eliminados']), set(rutas))
        self.assertTrue(all(not p.exists() for p in archivos))
        self.assertTrue(self.clip.parent.is_dir())
        self.assertEqual(self.clip.read_bytes(), b'contenido original')
        self.assertTrue(self.otro.exists())
        self.assertEqual(self.manifiesto.read_bytes(), self.manifiesto_inicial)

    def test_confirmacion_y_token_obligatorios(self):
        plan = self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        for valor in [True, '', None, 'eliminar']:
            with self.assertRaises(ValueError):
                self.gestor.ejecutar(plan['token'], valor)
        with self.assertRaises(ValueError):
            self.gestor.ejecutar('inventado', 'ELIMINAR')
        self.assertTrue(self.clip.exists())

    def test_rechaza_raiz_metadatos_y_escapes(self):
        for ruta in ['', '.', '..', '../fuera', '/absoluta', 'C:/archivo',
                     '.lucie', '.lucie/manifiesto.jsonl', 'videos sin editar/../.lucie',
                     'videos sin editar\\lucie', 'videos sin editar//lucie']:
            with self.subTest(ruta=ruta), self.assertRaises((ValueError, OSError)):
                self.gestor.simular([ruta])
        self.assertTrue(self.clip.exists())

    def test_mutacion_mismo_tamano_y_mtime_aborta(self):
        plan = self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        st = self.clip.stat()
        self.clip.write_bytes(b'x' * st.st_size)
        os.utime(self.clip, ns=(st.st_atime_ns, st.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'contenido'):
            self.gestor.ejecutar(plan['token'], 'ELIMINAR')
        self.assertTrue(self.clip.exists())

    def test_archivo_nuevo_en_carpeta_aborta(self):
        plan = self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        nuevo = self.crear('videos sin editar/lucie/cap (01)/nuevo.mp3')
        with self.assertRaises(ValueError):
            self.gestor.ejecutar(plan['token'], 'ELIMINAR')
        self.assertTrue(nuevo.exists())
        self.assertTrue(self.clip.exists())

    def test_pendrive_cambiado_o_desconectado_aborta(self):
        plan = self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        datos = json.loads(self.marcador.read_text())
        datos['id'] = str(uuid.uuid4())
        self.marcador.write_text(json.dumps(datos))
        with self.assertRaises(ValueError):
            self.gestor.ejecutar(plan['token'], 'ELIMINAR')
        self.config.rutas_candidatas_pendrive = [str(self.montaje / 'ausente')]
        with self.assertRaises(ValueError):
            self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        self.assertTrue(self.clip.exists())

    def test_plan_caducado_aborta(self):
        with patch('bandeja.eliminacion.time.monotonic', return_value=100):
            plan = self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        with patch('bandeja.eliminacion.time.monotonic', return_value=401), self.assertRaises(ValueError):
            self.gestor.ejecutar(plan['token'], 'ELIMINAR')
        self.assertTrue(self.clip.exists())

    def test_operacion_concurrente_impide_borrado_y_no_consume_plan(self):
        plan = self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        with operacion_pendrive_exclusiva(), self.assertRaisesRegex(ValueError, 'operación en curso'):
            self.gestor.ejecutar(plan['token'], 'ELIMINAR')
        self.assertTrue(self.clip.exists())
        self.assertTrue(self.gestor.ejecutar(plan['token'], 'ELIMINAR')['exito'])

    def test_enlaces_rechazados(self):
        enlace = self.raiz / 'enlace'
        try:
            enlace.symlink_to(self.clip)
        except OSError:
            self.skipTest('El host no permite crear enlaces simbólicos sin privilegios.')
        with self.assertRaises(ValueError):
            self.gestor.simular(['enlace'])
        self.assertTrue(self.clip.exists())

    def test_error_de_borrado_se_registra(self):
        plan = self.gestor.simular(['videos sin editar/lucie/cap (01)'])
        with patch('bandeja.eliminacion.os.unlink', side_effect=PermissionError('archivo en uso')):
            res = self.gestor.ejecutar(plan['token'], 'ELIMINAR')
        self.assertFalse(res['exito'])
        self.assertEqual(res['eliminados'], [])
        self.assertEqual(len(res['errores']), 1)
        self.assertTrue(self.clip.exists())
        eventos = (self.raiz / '.lucie/eliminaciones.jsonl').read_text()
        self.assertIn('eliminacion_manual_interrumpida', eventos)

    def test_api_csrf_simulacion_y_confirmacion(self):
        self.config.puerto_servidor = 0
        servidor = crear_servidor(self.config, Mock(), Mock(), Mock(), Mock(), token_csrf='csrf-test')
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(hilo.join, 2)
        self.addCleanup(servidor.shutdown)
        def request(ruta, body=None, token='csrf-test'):
            con = http.client.HTTPConnection('127.0.0.1', self.config.puerto_servidor, timeout=5)
            try:
                con.request('GET' if body is None else 'POST', ruta,
                            body=None if body is None else json.dumps(body),
                            headers={'Content-Type': 'application/json', 'X-CSRF-Token': token})
                res = con.getresponse()
                return res.status, json.loads(res.read())
            finally:
                con.close()
        ruta = 'videos sin editar/lucie/cap (01)/0818(15).mp4'
        status, _ = request('/api/pendrive/eliminacion-simular', {'seleccion': [ruta]}, token='')
        self.assertEqual(status, 403)
        status, plan = request('/api/pendrive/eliminacion-simular', {'seleccion': [ruta]})
        self.assertEqual(status, 200)
        self.assertTrue(self.clip.exists())
        status, _ = request('/api/pendrive/eliminar', {'token': plan['token'], 'confirmacion': ''})
        self.assertEqual(status, 409)
        status, res = request('/api/pendrive/eliminar', {'token': plan['token'], 'confirmacion': 'ELIMINAR'})
        self.assertEqual(status, 200)
        self.assertTrue(res['exito'])
        self.assertFalse(self.clip.exists())

    def test_ast_excepcion_no_habilita_otras_funciones_ni_primitivas(self):
        ruta = 'bandeja/eliminacion.py'
        autorizado = 'class GestorEliminacionPendrive:\n def ejecutar(self):\n  os.unlink(ruta)\n  os.rmdir(ruta)\n'
        self.assertEqual(analizar_ast_codigo(autorizado, ruta), [])
        self.assertTrue(analizar_ast_codigo(autorizado, 'bandeja/vigilante.py'))
        self.assertTrue(analizar_ast_codigo(autorizado.replace('ejecutar', 'automatico'), ruta))
        self.assertTrue(analizar_ast_codigo(autorizado.replace('os.unlink(ruta)', 'shutil.rmtree(ruta)'), ruta))
        self.assertTrue(analizar_ast_codigo(autorizado + '\nos.unlink(ruta)\n', ruta))


if __name__ == '__main__':
    unittest.main()
