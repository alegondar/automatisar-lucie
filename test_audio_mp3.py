"""MP3: detección, adopción, lotes y envío con datos exclusivamente temporales."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from bandeja.clasificacion import FiltroListaBlanca
from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.lotes import AgrupadorLotes, DetectorDescargasActivas
from bandeja.movimientos import GestorMovimientosBandeja
from bandeja.organizacion_mensual import nombre_mes
from bandeja.pendrive import escanear_sala_espera_carpetas, simular_envio_capitulos, ejecutar_envio_pendrive
from bandeja.vigilante import VigilanteBandeja


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestAudioMP3(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='audio_mp3_')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.desc = self.base / 'Descargas'
        self.desc.mkdir()
        self.dest = self.desc / '_lucie'
        self.config = ConfiguracionBandeja(ruta_config=str(self.base / 'config-ausente.json'),
                                          ruta_config_local=str(self.base / 'local-ausente.json'))
        self.config.ruta_descargas = str(self.desc)
        self.config.ruta_destino_base = str(self.dest)
        self.config.rutas_candidatas_pendrive = [str(self.base / 'pendrive')]
        self.db = GestorBaseDatosBandeja(str(self.base / 'db.sqlite'))
        self.filtro = FiltroListaBlanca(self.config, ruta_alias=str(self.base / 'alias-ausente.json'))
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro,
                                          DetectorDescargasActivas(0), AgrupadorLotes())
        self.mov = GestorMovimientosBandeja(str(self.desc), str(self.dest), self.db,
                                           ruta_bitacora=str(self.base / 'bitacora.jsonl'))

    def test_mp3_con_alias_se_detecta_en_lotes(self):
        audio = self.desc / 'lucie_dialogo.MP3'
        audio.write_bytes(b'mp3 de prueba')
        self.assertEqual(self.filtro.clasificar_archivo(audio.name), 'candidato')
        self.vigilante.escanear()
        self.vigilante.escanear()
        archivos = [a for l in self.vigilante.obtener_estado()['lotes'] for a in l['archivos']]
        self.assertIn(audio.name, [a['nombre'] for a in archivos])
        self.assertEqual(audio.read_bytes(), b'mp3 de prueba')

    def test_mp3_sin_alias_se_puede_adoptar_a_lotes(self):
        audio = self.desc / 'musica.mp3'
        audio.write_bytes(b'musica de prueba')
        self.assertEqual(self.filtro.clasificar_archivo(audio.name), 'sin_identificar')
        self.vigilante.escanear()
        self.vigilante.escanear()
        self.assertIn(audio.name, [a['nombre'] for a in self.vigilante.obtener_estado()['sin_identificar']])
        self.db.guardar_decision_sin_identificar(calcular_sha256(str(audio)), str(audio), True)
        self.vigilante.escanear()
        archivos = [a for l in self.vigilante.obtener_estado()['lotes'] for a in l['archivos']]
        self.assertIn(audio.name, [a['nombre'] for a in archivos])

    def test_traslado_y_envio_mp3_preservan_contenido_y_no_pisan(self):
        audio = self.desc / 'lucie_dialogo.mp3'
        audio.write_bytes(b'audio original')
        carpeta = self.dest / 'lucie' / 'dialogo' / 'audios'
        carpeta.mkdir(parents=True)
        previo = carpeta / audio.name
        previo.write_bytes(b'audio existente')
        sim = self.mov.simular_movimiento_lote([{'ruta': str(audio), 'tamanio': audio.stat().st_size,
                                                 'hash': calcular_sha256(str(audio))}], 'lucie', 'dialogo')
        mov = sim['movimientos'][0]
        self.assertEqual(mov['subcarpeta_tipo'], 'audios')
        self.assertEqual(mov['nombre_nuevo'], 'lucie_dialogo (1).mp3')
        self.assertFalse(mov['es_otro_tipo'])
        res = self.mov.ejecutar_movimiento_lote(sim, 'lote-audio')
        self.assertTrue(res['exito'])
        self.assertEqual(previo.read_bytes(), b'audio existente')
        self.assertEqual(Path(mov['destino']).read_bytes(), b'audio original')
        montaje = self.base / 'pendrive'
        montaje.mkdir()
        (montaje / 'LucieSinReglas').mkdir()
        (montaje / '.lucie_pendrive.json').write_text(json.dumps({
            'id': str(uuid.uuid4()), 'creado': '2026-10-11T12:00:00', 'version': 1}))
        listado = escanear_sala_espera_carpetas(str(self.dest), self.db)
        self.assertEqual({a['tipo'] for a in listado[0]['archivos']}, {'audio'})
        envio = simular_envio_capitulos(None, self.config, self.db, carpetas=['lucie/dialogo'])
        self.assertEqual(envio['totales']['no_multimedia'], 0)
        self.assertEqual(envio['totales']['a_copiar_cantidad'], 2)
        resultado = ejecutar_envio_pendrive(envio, self.config, self.db, self.mov)
        self.assertTrue(resultado['exito'])
        final = montaje / 'LucieSinReglas' / 'audios' / 'lucie' / nombre_mes() / 'dialogo' / 'lucie_dialogo (1).mp3'
        self.assertEqual(final.read_bytes(), b'audio original')


if __name__ == '__main__':
    unittest.main()
