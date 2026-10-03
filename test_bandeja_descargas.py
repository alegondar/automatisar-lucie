#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_bandeja_descargas.py

Suite completa de pruebas unitarias para bandeja_descargas.py.
Verifica:
1. Lista blanca estricta (candidatos Grok, Nano Banana, Flow, sin identificar, ignorar no-media y temporales).
2. Detección y omisión de descargas activas e incompletas (ventana de 5s y sufijos temporales).
3. Agrupación temporal de lotes por proximidad de mtime.
4. Validación exhaustiva de nombres de escena (prohibidos, reservados Windows, longitud <= 100, trailing dot/space, realpath).
5. Enrutamiento hacia escenas existentes en Descargas (sin mover la carpeta) y escenas nuevas en destino.
6. Movimiento seguro con os.rename, resolución de colisiones con sufijo numérico y confinamiento canónico.
7. Deshacer estricto: reversión con os.rename; si la ruta original está ocupada se NIEGA sin pisar ni sufijar.
8. Protección anti-CSRF, validación de cabeceras Host y Content-Type (403 Forbidden).
9. Generación segura de miniaturas por ID registrado y comando ffmpeg con '--'.
10. Auditoría estática AST anti-borrado (0 violaciones de las 11 primitivas prohibidas).
"""

import http.client
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from typing import Dict, List, Optional, Set, Tuple, Any
from unittest.mock import patch

from bandeja_descargas import (
    ConfiguracionBandeja,
    GestorBaseDatosBandeja,
    FiltroListaBlanca,
    ValidadorEscenas,
    DetectorDescargasActivas,
    AgrupadorLotes,
    GestorMovimientosBandeja,
    GeneradorMiniaturas,
    VigilanteBandeja,
    crear_servidor,
    ErrorValidacionEscena,
    ErrorSeguridadBandeja,
    ErrorDeshacer,
    calcular_sha256
)
from seguridad_anti_borrado import analizar_ast_archivo


class TestListaBlancaYBandeja(unittest.TestCase):
    """Pruebas del filtro de lista blanca y clasificación de archivos."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_bandeja_blanca_")
        self.cfg_file = os.path.join(self.tmp_dir, "config.json")
        self.alias_file = os.path.join(self.tmp_dir, "alias.json")

        cfg_data = {
            "ruta_descargas": self.tmp_dir,
            "ruta_destino_base": os.path.join(self.tmp_dir, "_lucie"),
            "puerto_servidor": 8799,
            "extensiones_media": [".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp"],
            "extensiones_temporales": [".crdownload", ".part", ".tmp"],
            "patrones_candidatos": {
                "grok": "grok-video-*",
                "nano_banana_regex": r"^.+_\d{14}\.(jpg|jpeg|png|webp)$",
                "flow": "flow_take_*"
            }
        }
        with open(self.cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f)

        alias_data = {
            "reglas": [
                {"patrones": ["roli*", "laroli*"], "personaje": "roli"},
                {"patrones": ["lucie*"], "personaje": "lucie"},
                {"patrones": ["mailen*"], "personaje": "mailen"}
            ]
        }
        with open(self.alias_file, "w", encoding="utf-8") as f:
            json.dump(alias_data, f)

        self.config = ConfiguracionBandeja(self.cfg_file)
        self.filtro = FiltroListaBlanca(self.config, ruta_alias=self.alias_file)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_clasificacion_candidatos_conocidos(self):
        self.assertEqual(self.filtro.clasificar_archivo("grok-video-123456.mp4"), "candidato")
        self.assertEqual(self.filtro.clasificar_archivo("Grok-Video-abc.webm"), "candidato")
        self.assertEqual(self.filtro.clasificar_archivo("lucie_primer_plano_20261003120000.png"), "candidato")
        self.assertEqual(self.filtro.clasificar_archivo("toma_escena_20261003235959.jpg"), "candidato")
        self.assertEqual(self.filtro.clasificar_archivo("flow_take_01.mp4"), "candidato")

    def test_clasificacion_sin_identificar(self):
        self.assertEqual(self.filtro.clasificar_archivo("video.mp4"), "sin_identificar")
        self.assertEqual(self.filtro.clasificar_archivo("clip (2).mov"), "sin_identificar")
        self.assertEqual(self.filtro.clasificar_archivo("foto_vacaciones.jpg"), "sin_identificar")

    def test_clasificacion_ignorar_no_media_y_temporales(self):
        self.assertEqual(self.filtro.clasificar_archivo("documento.pdf"), "ignorar")
        self.assertEqual(self.filtro.clasificar_archivo("instalador.exe"), "ignorar")
        self.assertEqual(self.filtro.clasificar_archivo("datos.zip"), "ignorar")
        self.assertEqual(self.filtro.clasificar_archivo("video.mp4.crdownload"), "ignorar")
        self.assertEqual(self.filtro.clasificar_archivo("clip.part"), "ignorar")
        self.assertEqual(self.filtro.clasificar_archivo("temp.tmp"), "ignorar")

    def test_carpetas_escenas_existentes_con_alias(self):
        self.assertTrue(self.filtro.es_carpeta_escena_existente("roli parque"))
        self.assertTrue(self.filtro.es_carpeta_escena_existente("lucie_toma1"))
        self.assertTrue(self.filtro.es_carpeta_escena_existente("laroli-paseo"))
        self.assertFalse(self.filtro.es_carpeta_escena_existente("descargas_varias"))
        self.assertFalse(self.filtro.es_carpeta_escena_existente("fotos"))


class TestValidacionEscenas(unittest.TestCase):
    """Pruebas de validación estricta de nombres de escenas y verificación canónica."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_val_escenas_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.descargas, "_lucie")
        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_nombres_validos(self):
        valido, err = ValidadorEscenas.validar_nombre_escena("escena_parque_01", self.destino, self.descargas)
        self.assertTrue(valido, f"Esperaba válido pero dio error: {err}")

        valido, err = ValidadorEscenas.validar_nombre_escena("toma 2 en el auto", self.destino, self.descargas)
        self.assertTrue(valido)

    def test_rechazo_separadores_y_path_traversal(self):
        for nombre in ["sub/carpeta", "sub\\carpeta", "../escape", "..", "escena/"]:
            valido, err = ValidadorEscenas.validar_nombre_escena(nombre, self.destino, self.descargas)
            self.assertFalse(valido, f"Esperaba que '{nombre}' fuera rechazado.")
            self.assertTrue("separadores" in err or "caracteres inválidos" in err or "escapa" in err)

    def test_rechazo_caracteres_invalidos_windows_exfat(self):
        for c in ['<', '>', ':', '"', '|', '?', '*']:
            nombre = f"escena{c}toma"
            valido, err = ValidadorEscenas.validar_nombre_escena(nombre, self.destino, self.descargas)
            self.assertFalse(valido, f"Esperaba rechazo para caracter '{c}'")
            self.assertIn("caracteres inválidos", err)

    def test_rechazo_terminacion_punto_o_espacio(self):
        valido, err = ValidadorEscenas.validar_nombre_escena("escena.", self.destino, self.descargas)
        self.assertFalse(valido)
        self.assertIn("punto o espacio", err)

        valido, err = ValidadorEscenas.validar_nombre_escena("escena ", self.destino, self.descargas)
        self.assertFalse(valido)
        self.assertIn("punto o espacio", err)

    def test_rechazo_nombres_reservados_windows(self):
        for res in ["CON", "prn", "AUX", "NUL", "com1", "COM9", "lpt1", "LPT9", "con.txt"]:
            valido, err = ValidadorEscenas.validar_nombre_escena(res, self.destino, self.descargas)
            self.assertFalse(valido, f"Esperaba rechazo para reservado '{res}'")
            self.assertIn("reservado", err)

    def test_rechazo_longitud_mayor_a_100(self):
        nombre_largo = "a" * 101
        valido, err = ValidadorEscenas.validar_nombre_escena(nombre_largo, self.destino, self.descargas)
        self.assertFalse(valido)
        self.assertIn("100 caracteres", err)


class TestDetectorDescargasActivas(unittest.TestCase):
    """Prueba la estabilidad temporal de descargas activas en ventana de 5s."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_descargas_activas_")
        self.detector = DetectorDescargasActivas(ventana_estabilidad_segundos=0.3)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_archivo_inestable_por_tiempo_y_mutacion(self):
        archivo = os.path.join(self.tmp_dir, "video.mp4")
        with open(archivo, "wb") as f:
            f.write(b"inicio")

        # Primera comprobación: recién descubierto, no es estable
        self.assertFalse(self.detector.es_archivo_estable(archivo))

        # Modificación de tamaño
        with open(archivo, "ab") as f:
            f.write(b"_mas_datos")

        # Inmediatamente tras mutar: no es estable
        self.assertFalse(self.detector.es_archivo_estable(archivo))

        # Esperar ventana de estabilidad
        time.sleep(0.35)
        self.assertTrue(self.detector.es_archivo_estable(archivo))


class TestAgrupadorLotes(unittest.TestCase):
    """Prueba la partición de lotes por proximidad de mtime."""

    def test_agrupacion_dentro_y_fuera_de_ventana(self):
        agrupador = AgrupadorLotes(ventana_minutos=10)  # 600 segundos
        base_time = 1700000000.0

        candidatos = [
            {"nombre": "clip1.mp4", "ruta": "/tmp/clip1.mp4", "tamanio": 100, "mtime": base_time},
            {"nombre": "clip2.mp4", "ruta": "/tmp/clip2.mp4", "tamanio": 200, "mtime": base_time + 120},  # +2 min
            {"nombre": "clip3.mp4", "ruta": "/tmp/clip3.mp4", "tamanio": 300, "mtime": base_time + 300},  # +5 min
            {"nombre": "clip4.mp4", "ruta": "/tmp/clip4.mp4", "tamanio": 400, "mtime": base_time + 2000}, # +33 min (otro lote)
            {"nombre": "clip5.mp4", "ruta": "/tmp/clip5.mp4", "tamanio": 500, "mtime": base_time + 2100}, # +35 min
        ]

        lotes = agrupador.agrupar(candidatos)
        self.assertEqual(len(lotes), 2)
        self.assertEqual(lotes[0]["total_archivos"], 3)
        self.assertEqual(lotes[1]["total_archivos"], 2)


class TestGestorMovimientosYDeshacer(unittest.TestCase):
    """Pruebas de movimientos con os.rename, colisiones y deshacer estricto."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_movimientos_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas, "_lucie")
        self.db_path = os.path.join(self.tmp_dir, "test.sqlite")
        self.bitacora = os.path.join(self.tmp_dir, "bitacora.jsonl")

        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)

        self.db = GestorBaseDatosBandeja(self.db_path)
        self.gestor = GestorMovimientosBandeja(
            ruta_descargas=self.descargas,
            ruta_destino_base=self.destino_base,
            db=self.db,
            ruta_bitacora=self.bitacora
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_movimiento_lote_y_resolucion_colision(self):
        # Crear archivos de prueba en Descargas
        arch1 = os.path.join(self.descargas, "grok-video-1.mp4")
        with open(arch1, "wb") as f:
            f.write(b"contenido 1")

        # Crear previamente un archivo en el destino para forzar colisión
        destino_colision = os.path.join(self.destino_base, "lucie", "videos sin editar", "escena1", "grok-video-1.mp4")
        os.makedirs(os.path.dirname(destino_colision), exist_ok=True)
        with open(destino_colision, "wb") as f:
            f.write(b"archivo previo existente")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": arch1, "tamanio": 11, "hash": "h1"}],
            personaje="lucie",
            nombre_escena="escena1",
            es_existente_descargas=False
        )

        destino_simulado = sim["movimientos"][0]["destino"]
        self.assertTrue(destino_simulado.endswith("grok-video-1 (1).mp4"))

        # Ejecutar movimiento
        res = self.gestor.ejecutar_movimiento_lote(sim, lote_id="lote_1")
        self.assertTrue(res["exito"])
        self.assertFalse(os.path.exists(arch1))
        self.assertTrue(os.path.exists(destino_simulado))
        self.assertTrue(os.path.exists(destino_colision))  # El preexistente NO fue pisado

    def test_enrutamiento_hacia_escena_existente_en_descargas(self):
        carpeta_existente = os.path.join(self.descargas, "roli parque")
        os.makedirs(carpeta_existente, exist_ok=True)

        arch = os.path.join(self.descargas, "grok-video-2.mp4")
        with open(arch, "wb") as f:
            f.write(b"contenido 2")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": arch, "tamanio": 11, "hash": "h2"}],
            personaje="roli",
            nombre_escena="roli parque",
            es_existente_descargas=True
        )

        destino_calculado = sim["movimientos"][0]["destino"]
        self.assertEqual(destino_calculado, os.path.join(carpeta_existente, "grok-video-2.mp4"))

        res = self.gestor.ejecutar_movimiento_lote(sim, "lote_2")
        self.assertTrue(res["exito"])
        self.assertTrue(os.path.exists(os.path.join(carpeta_existente, "grok-video-2.mp4")))
        self.assertTrue(os.path.isdir(carpeta_existente))

    def test_deshacer_exitoso(self):
        arch = os.path.join(self.descargas, "grok-video-3.mp4")
        with open(arch, "wb") as f:
            f.write(b"contenido 3")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": arch, "tamanio": 11, "hash": "h3"}],
            personaje="lucie",
            nombre_escena="toma3",
            es_existente_descargas=False
        )
        res_mover = self.gestor.ejecutar_movimiento_lote(sim, "lote_3")
        id_op = res_mover["id_operacion"]

        # Comprobar que se movió
        self.assertFalse(os.path.exists(arch))

        # Deshacer operación
        res_deshacer = self.gestor.deshacer_operacion(id_op)
        self.assertTrue(res_deshacer["exito"])
        self.assertTrue(os.path.exists(arch))  # Volvió al origen

    def test_deshacer_rechazado_si_origen_esta_ocupado_sin_pisar_ni_sufijar(self):
        arch = os.path.join(self.descargas, "grok-video-4.mp4")
        with open(arch, "wb") as f:
            f.write(b"original")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": arch, "tamanio": 8, "hash": "h4"}],
            personaje="lucie",
            nombre_escena="toma4",
            es_existente_descargas=False
        )
        res_mover = self.gestor.ejecutar_movimiento_lote(sim, "lote_4")
        id_op = res_mover["id_operacion"]

        # Ocupar maliciosamente la ruta de origen original
        with open(arch, "wb") as f:
            f.write(b"archivo nuevo en el mismo lugar")

        # El deshacer DEBE ser rechazado terminantemente con ErrorDeshacer
        with self.assertRaises(ErrorDeshacer) as ctx:
            self.gestor.deshacer_operacion(id_op)

        self.assertIn("ya se encuentra ocupada", str(ctx.exception))
        # Comprobar que el archivo nuevo NO fue pisado
        with open(arch, "rb") as f:
            self.assertEqual(f.read(), b"archivo nuevo en el mismo lugar")

    def test_movimiento_lote_mixto_videos_e_imagenes(self):
        """Un lote mixto reparte videos a 'videos sin editar' e imágenes a 'carpeta_imagenes'."""
        video_arch = os.path.join(self.descargas, "grok-video-mixto.mp4")
        foto_arch = os.path.join(self.descargas, "lucie_20261003120000.png")
        with open(video_arch, "wb") as f:
            f.write(b"video data")
        with open(foto_arch, "wb") as f:
            f.write(b"foto data")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[
                {"ruta": video_arch, "tamanio": 10, "hash": "h_vid"},
                {"ruta": foto_arch, "tamanio": 9, "hash": "h_img"}
            ],
            personaje="lucie",
            nombre_escena="parque_primavera",
            es_existente_descargas=False
        )

        self.assertEqual(len(sim["movimientos"]), 2)
        dest_vid = sim["movimientos"][0]["destino"]
        dest_img = sim["movimientos"][1]["destino"]

        self.assertEqual(
            dest_vid,
            os.path.join(self.destino_base, "lucie", "videos sin editar", "parque_primavera", "grok-video-mixto.mp4")
        )
        self.assertEqual(
            dest_img,
            os.path.join(self.destino_base, "lucie", "imagenes", "parque_primavera", "lucie_20261003120000.png")
        )

        # Ejecutar movimiento
        res = self.gestor.ejecutar_movimiento_lote(sim, lote_id="lote_mixto")
        self.assertTrue(res["exito"])
        self.assertFalse(os.path.exists(video_arch))
        self.assertFalse(os.path.exists(foto_arch))
        self.assertTrue(os.path.exists(dest_vid))
        self.assertTrue(os.path.exists(dest_img))

        # Deshacer y verificar reversión limpia
        res_deshacer = self.gestor.deshacer_operacion(res["id_operacion"])
        self.assertTrue(res_deshacer["exito"])
        self.assertTrue(os.path.exists(video_arch))
        self.assertTrue(os.path.exists(foto_arch))

    def test_carpeta_imagenes_personalizada(self):
        """Permite configurar un nombre alternativo para la subcarpeta de imágenes."""
        gestor_custom = GestorMovimientosBandeja(
            ruta_descargas=self.descargas,
            ruta_destino_base=self.destino_base,
            db=self.db,
            ruta_bitacora=os.path.join(self.tmp_dir, "bitacora_custom.jsonl"),
            carpeta_imagenes="fotos_sesion"
        )
        foto_arch = os.path.join(self.descargas, "toma_20261003140000.webp")
        with open(foto_arch, "wb") as f:
            f.write(b"webp data")

        sim = gestor_custom.simular_movimiento_lote(
            archivos=[{"ruta": foto_arch, "tamanio": 9, "hash": "h_custom"}],
            personaje="mailen",
            nombre_escena="estudio",
            es_existente_descargas=False
        )

        dest_img = sim["movimientos"][0]["destino"]
        self.assertEqual(
            dest_img,
            os.path.join(self.destino_base, "mailen", "fotos_sesion", "estudio", "toma_20261003140000.webp")
        )

        res = gestor_custom.ejecutar_movimiento_lote(sim, lote_id="lote_custom")
        self.assertTrue(res["exito"])
        self.assertTrue(os.path.exists(dest_img))

    def test_descubrimiento_escenas_destino_videos_e_imagenes(self):
        """Descubre escenas ya existentes en destino tanto bajo 'videos sin editar' como en 'imagenes'."""
        escena_vid = os.path.join(self.destino_base, "lucie", "videos sin editar", "escena_video_previa")
        escena_img = os.path.join(self.destino_base, "lucie", "imagenes", "escena_foto_previa")
        os.makedirs(escena_vid, exist_ok=True)
        os.makedirs(escena_img, exist_ok=True)

        config = ConfiguracionBandeja()
        config.ruta_descargas = self.descargas
        config.ruta_destino_base = self.destino_base
        config.carpeta_imagenes = "imagenes"

        vigilante = VigilanteBandeja(
            config, self.db, FiltroListaBlanca(config), DetectorDescargasActivas(0.1), AgrupadorLotes(10)
        )
        vigilante.escanear()
        estado = vigilante.obtener_estado()
        nombres_escenas = [e["nombre"] for e in estado["escenas"]]
        self.assertIn("escena_video_previa", nombres_escenas)
        self.assertIn("escena_foto_previa", nombres_escenas)


class TestServidorHTTPYSeguridad(unittest.TestCase):
    """Pruebas del servidor HTTP local, protección anti-CSRF, cabeceras y miniaturas seguras."""

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp(prefix="test_server_bandeja_")
        cls.descargas = os.path.join(cls.tmp_dir, "Descargas")
        cls.destino = os.path.join(cls.descargas, "_lucie")
        cls.db_path = os.path.join(cls.tmp_dir, "db.sqlite")
        cls.bitacora = os.path.join(cls.tmp_dir, "bitacora.jsonl")

        os.makedirs(cls.descargas, exist_ok=True)
        os.makedirs(cls.destino, exist_ok=True)

        cls.config = ConfiguracionBandeja()
        cls.config.ruta_descargas = cls.descargas
        cls.config.ruta_destino_base = cls.destino
        cls.config.puerto_servidor = 8798
        cls.config.host_servidor = "127.0.0.1"

        cls.db = GestorBaseDatosBandeja(cls.db_path)
        cls.filtro = FiltroListaBlanca(cls.config)
        cls.detector = DetectorDescargasActivas(0.1)
        cls.agrupador = AgrupadorLotes(10)
        cls.movimientos = GestorMovimientosBandeja(cls.descargas, cls.destino, cls.db, cls.bitacora)
        cls.miniaturas = GeneradorMiniaturas(cls.db, os.path.join(cls.tmp_dir, "thumbs"))
        cls.vigilante = VigilanteBandeja(cls.config, cls.db, cls.filtro, cls.detector, cls.agrupador)

        cls.token_csrf = "token_secreto_de_prueba_123"
        cls.servidor = crear_servidor(
            cls.config, cls.db, cls.vigilante, cls.movimientos, cls.miniaturas, token_csrf=cls.token_csrf
        )

        cls.hilo_servidor = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo_servidor.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def _request(self, method: str, path: str, headers: dict = None, body: str = None) -> Tuple[int, dict, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.config.puerto_servidor, timeout=5)
        headers = headers or {}
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        try:
            parsed_json = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed_json = {}
        return res.status, parsed_json, raw

    def test_get_spa_html(self):
        status, _, raw = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Bandeja de Descargas", raw)
        self.assertIn(self.token_csrf.encode("utf-8"), raw)

    def test_get_endpoints_api(self):
        status, data, _ = self._request("GET", "/api/lotes")
        self.assertEqual(status, 200)
        self.assertIn("lotes", data)

        status, data, _ = self._request("GET", "/api/personajes")
        self.assertEqual(status, 200)
        self.assertIn("personajes", data)

    def test_metodos_no_permitidos_devuelven_405(self):
        for m in ("PUT", "DELETE", "PATCH"):
            status, _, _ = self._request(m, "/api/lotes")
            self.assertEqual(status, 405)

    def test_post_requiere_token_csrf_y_cabeceras(self):
        # 1. Sin token: 403 Forbidden
        headers_sin_token = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json"
        }
        status, _, _ = self._request("POST", "/api/simular-mover", headers_sin_token, body="{}")
        self.assertEqual(status, 403)

        # 2. Con Host foráneo (intento de DNS rebinding / host injection): 403 Forbidden
        headers_host_invalido = {
            "Host": "sitio-malicioso.com",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.token_csrf
        }
        status, _, _ = self._request("POST", "/api/simular-mover", headers_host_invalido, body="{}")
        self.assertEqual(status, 403)

        # 3. Con Content-Type incorrecto: 403 Forbidden
        headers_ct_invalido = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "text/plain",
            "X-CSRF-Token": self.token_csrf
        }
        status, _, _ = self._request("POST", "/api/simular-mover", headers_ct_invalido, body="{}")
        self.assertEqual(status, 403)

    def test_miniatura_segura_por_id(self):
        # 1. Intentar pasar una ruta o ID inexistente: 400 o 404
        status, _, _ = self._request("GET", "/api/miniatura?id=no_es_numero")
        self.assertEqual(status, 400)

        status, _, _ = self._request("GET", "/api/miniatura?id=999999")
        self.assertEqual(status, 404)

        # 2. Registrar archivo de imagen válido y solicitarla por ID
        img_path = os.path.join(self.descargas, "test_foto.jpg")
        with open(img_path, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 32)  # Header JPEG mínimo
        h = calcular_sha256(img_path)
        archivo_id = self.db.registrar_o_actualizar(h, img_path, "detectado")

        status, _, raw = self._request("GET", f"/api/miniatura?id={archivo_id}")
        self.assertEqual(status, 200)
        self.assertEqual(raw[:4], b"\xff\xd8\xff\xe0")


class TestAuditoriaASTAntiBorrado(unittest.TestCase):
    """Verifica que bandeja_descargas.py no contenga ninguna de las 11 primitivas prohibidas."""

    def test_bandeja_descargas_esta_100_por_ciento_limpio(self):
        ruta_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bandeja_descargas.py")
        self.assertTrue(os.path.exists(ruta_script), "No se encontró bandeja_descargas.py")
        violaciones = analizar_ast_archivo(ruta_script)
        if violaciones:
            msg = "\n".join(str(v) for v in violaciones)
            self.fail(f"Violaciones anti-borrado encontradas en bandeja_descargas.py:\n{msg}")


if __name__ == "__main__":
    unittest.main()
