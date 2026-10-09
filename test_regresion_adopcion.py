#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_regresion_adopcion.py

Test de regresión para el bug de "Del Proyecto" en archivos sin identificar:
Reproduce que un archivo sin patrón conocido que llegó antes del inicio del capítulo en foco
(o antes del corte temporal de material reciente) estaba desapareciendo por completo de todos los
listados al hacer clic en "Del Proyecto", en vez de ser adoptado en la sección PRINCIPAL de Lotes Detectados.
"""

import http.client
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from typing import Tuple

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.clasificacion import FiltroListaBlanca
from bandeja.lotes import DetectorDescargasActivas, AgrupadorLotes
from bandeja.movimientos import GestorMovimientosBandeja
from bandeja.servidor import crear_servidor, GeneradorMiniaturas
from bandeja.vigilante import VigilanteBandeja


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestRegresionAdopcionDelProyecto(unittest.TestCase):
    """Verifica que 'Del Proyecto' incorpore el archivo en la sección principal de Lotes Detectados."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.tmp_dir, "_lucie")
        self.thumbs = os.path.join(self.tmp_dir, "thumbs")
        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)
        os.makedirs(self.thumbs, exist_ok=True)

        self.db_path = os.path.join(self.tmp_dir, "bandeja_test.db")
        self.bitacora_path = os.path.join(self.tmp_dir, "bitacora_test.jsonl")

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas
        self.config.ruta_destino_base = self.destino
        self.config.puerto_servidor = 0
        self.config.host_servidor = "127.0.0.1"
        self.config.rutas_candidatas_pendrive = [self.tmp_dir]
        self.config.horas_material_reciente = 168.0

        self.db = GestorBaseDatosBandeja(self.db_path, self.destino)
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas(0.01)
        self.agrupador = AgrupadorLotes(10)
        self.movimientos = GestorMovimientosBandeja(self.descargas, self.destino, self.db, self.bitacora_path)
        self.miniaturas = GeneradorMiniaturas(self.db, self.thumbs)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)

        self.token_csrf = "csrf_token_test_12345"
        self.servidor = crear_servidor(
            self.config, self.db, self.vigilante, self.movimientos, self.miniaturas, token_csrf=self.token_csrf
        )
        self.hilo_servidor = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo_servidor.start()
        time.sleep(0.1)

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _request(self, method: str, path: str, body: dict = None) -> Tuple[int, dict]:
        conn = http.client.HTTPConnection(self.config.host_servidor, self.config.puerto_servidor, timeout=5)
        headers = {
            "Host": f"{self.config.host_servidor}:{self.config.puerto_servidor}",
        }
        body_bytes = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            headers["X-CSRF-Token"] = self.token_csrf
            body_bytes = json.dumps(body or {}).encode("utf-8")
        conn.request(method, path, body=body_bytes, headers=headers)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {}
        return res.status, parsed

    def test_del_proyecto_adopta_archivo_en_lotes_principales(self):
        """
        Reproduce el bug:
        1. Se inicia un capítulo en foco ('lucie-canio') con timestamp T.
        2. Un archivo sin alias ('Man_smells_pole_on_bus_20261006062714.mp4') llegó antes de T (es_anterior).
        3. Inicialmente aparece en 'Sin Identificar'.
        4. Al hacer POST /api/clasificar-sin-identificar con es_proyecto=True,
           el archivo DEBE aparecer en la sección principal de Lotes Detectados
           con adoptado_a_mano=True, y salir de Sin Identificar.
        """
        nombre_arch = "Man_smells_pole_on_bus_20261006062714.mp4"
        ruta_arch = os.path.join(self.descargas, nombre_arch)
        with open(ruta_arch, "wb") as f:
            f.write(b"video_data_dummy_content_1234567890")

        # El capítulo lucie-canio se inició DESPUÉS de que el archivo llegó a Descargas
        t_cap = time.time() + 300
        self.db.empezar_capitulo(
            "lucie", "canio",
            fecha_inicio=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t_cap))
        )

        # Escaneo inicial con espera de estabilidad
        self.vigilante.escanear()
        time.sleep(0.05)
        self.vigilante.escanear()

        # 1. Verificar que inicialmente está en sin-identificar
        status, data_sin_id = self._request("GET", "/api/sin-identificar")
        self.assertEqual(status, 200)
        sin_id_nombres = [a["nombre"] for a in data_sin_id.get("sin_identificar", [])]
        self.assertIn(nombre_arch, sin_id_nombres, "El archivo debe estar inicialmente en Sin Identificar")

        hash_arch = calcular_sha256(ruta_arch)

        # 2. El usuario presiona 'Del Proyecto'
        status, res_post = self._request("POST", "/api/clasificar-sin-identificar", {
            "hash": hash_arch,
            "ruta": ruta_arch,
            "es_proyecto": True
        })
        self.assertEqual(status, 200)
        self.assertTrue(res_post.get("exito"))

        # 3. Comprobar que salió de sin-identificar
        status, data_sin_id_post = self._request("GET", "/api/sin-identificar")
        self.assertEqual(status, 200)
        sin_id_nombres_post = [a["nombre"] for a in data_sin_id_post.get("sin_identificar", [])]
        self.assertNotIn(nombre_arch, sin_id_nombres_post, "El archivo NO debe seguir en Sin Identificar tras adoptarlo")

        # 4. Comprobar que APARECE en la sección PRINCIPAL de Lotes Detectados (NO en Anteriores)
        status, data_lotes = self._request("GET", "/api/lotes")
        self.assertEqual(status, 200)
        lotes_principales = data_lotes.get("lotes", [])
        lotes_anteriores = data_lotes.get("lotes_anteriores", [])

        archivos_en_principales = []
        for l in lotes_principales:
            for a in l.get("archivos", []):
                archivos_en_principales.append(a)

        archivos_en_anteriores = []
        for l in lotes_anteriores:
            for a in l.get("archivos", []):
                archivos_en_anteriores.append(a)

        nombres_principales = [a["nombre"] for a in archivos_en_principales]
        nombres_anteriores = [a["nombre"] for a in archivos_en_anteriores]

        self.assertNotIn(nombre_arch, nombres_anteriores, "El archivo adoptado NO debe ir a Anteriores")
        self.assertIn(nombre_arch, nombres_principales, "El archivo adoptado DEBE aparecer en Lotes Principales")

        # Verificar atributos de adopción manual
        arch_adoptado = next(a for a in archivos_en_principales if a["nombre"] == nombre_arch)
        self.assertTrue(arch_adoptado.get("adoptado_a_mano"), "El archivo debe tener bandera adoptado_a_mano=True")

    def test_deshacer_adopcion_devuelve_archivo_a_sin_identificar(self):
        """Verifica que deshacer la adopción retire el archivo de lotes y lo devuelva a Sin Identificar."""
        t_cap = time.time() + 300
        self.db.empezar_capitulo("lucie", "canio", fecha_inicio=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t_cap)))
        nombre_arch = "video_para_deshacer_12345.mp4"
        ruta_arch = os.path.join(self.descargas, nombre_arch)
        with open(ruta_arch, "wb") as f:
            f.write(b"dummy_content_for_undo_test")

        self.vigilante.escanear()
        time.sleep(0.05)
        self.vigilante.escanear()

        hash_arch = calcular_sha256(ruta_arch)

        # 1. Adoptar
        self._request("POST", "/api/clasificar-sin-identificar", {"hash": hash_arch, "ruta": ruta_arch, "es_proyecto": True})

        # 2. Deshacer adopción
        status, res_undo = self._request("POST", "/api/deshacer-clasificar-sin-identificar", {
            "hash": hash_arch,
            "ruta": ruta_arch
        })
        self.assertEqual(status, 200)
        self.assertTrue(res_undo.get("exito"))

        # 3. Comprobar que volvió a sin-identificar
        _, data_sin_id = self._request("GET", "/api/sin-identificar")
        sin_id_nombres = [a["nombre"] for a in data_sin_id.get("sin_identificar", [])]
        self.assertIn(nombre_arch, sin_id_nombres, "El archivo debe reaparecer en Sin Identificar tras deshacer")

        # 4. Comprobar que ya no figura en lotes principales
        _, data_lotes = self._request("GET", "/api/lotes")
        archs_lotes = [a["nombre"] for l in data_lotes.get("lotes", []) for a in l.get("archivos", [])]
        self.assertNotIn(nombre_arch, archs_lotes, "El archivo debe salir de los lotes al deshacer")

    def test_ignorar_y_deshacer_ignorar(self):
        """Verifica que ignorar oculte el archivo y que deshacer lo reincorpore a Sin Identificar."""
        nombre_arch = "spam_clip_a_ignorar.mp4"
        ruta_arch = os.path.join(self.descargas, nombre_arch)
        with open(ruta_arch, "wb") as f:
            f.write(b"spam_content_to_ignore")

        self.vigilante.escanear()
        time.sleep(0.05)
        self.vigilante.escanear()

        hash_arch = calcular_sha256(ruta_arch)

        # 1. Ignorar
        status, res_post = self._request("POST", "/api/clasificar-sin-identificar", {
            "hash": hash_arch,
            "ruta": ruta_arch,
            "es_proyecto": False
        })
        self.assertEqual(status, 200)

        # Verificar que no está en sin-identificar ni en lotes
        _, data_sin_id = self._request("GET", "/api/sin-identificar")
        self.assertNotIn(nombre_arch, [a["nombre"] for a in data_sin_id.get("sin_identificar", [])])

        # 2. Deshacer ignorar
        status, res_undo = self._request("POST", "/api/deshacer-clasificar-sin-identificar", {
            "hash": hash_arch,
            "ruta": ruta_arch
        })
        self.assertEqual(status, 200)

        # Verificar que regresó a sin-identificar
        _, data_sin_id_post = self._request("GET", "/api/sin-identificar")
        self.assertIn(nombre_arch, [a["nombre"] for a in data_sin_id_post.get("sin_identificar", [])])

    def test_sqlite_wal_lectura_concurrente_mientras_se_escribe(self):
        """Verifica que un lector externo SQLite no reciba 'database is locked' mientras se escribe intensamente."""
        import sqlite3

        detener_hilos = threading.Event()
        errores_lector = []

        def lector_externo():
            con = sqlite3.connect(self.db_path, timeout=5.0)
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA busy_timeout=5000;")
            try:
                while not detener_hilos.is_set():
                    cur = con.cursor()
                    cur.execute("SELECT count(*) FROM bandeja_archivos")
                    _ = cur.fetchone()
                    time.sleep(0.005)
            except Exception as e:
                errores_lector.append(e)
            finally:
                con.close()

        hilo_lector = threading.Thread(target=lector_externo)
        hilo_lector.start()

        try:
            # Escrituras concurrentes en la base
            for i in range(25):
                h = f"hash_prueba_wal_{i:04d}"
                r = f"/ruta/prueba/wal_{i}.mp4"
                self.db.registrar_o_actualizar(h, r, "detectado")
                time.sleep(0.005)
        finally:
            detener_hilos.set()
            hilo_lector.join(timeout=3.0)

        self.assertEqual(errores_lector, [], f"Hubo errores en el lector concurrente: {errores_lector}")


if __name__ == "__main__":
    unittest.main()
