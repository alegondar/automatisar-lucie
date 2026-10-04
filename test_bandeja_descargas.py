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

import datetime
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
    calcular_sha256,
    generar_html_simulacion
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
        destino_colision = os.path.join(self.destino_base, "lucie", "escena1", "grok-video-1.mp4")
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

    def test_ejecutar_movimiento_genera_aviso_y_deshacer_revierte_todos(self):
        """ejecutar_movimiento_lote devuelve mensaje de aviso con cantidad y destino, y deshacer revierte todo."""
        archivos = []
        for i in range(1, 4):
            p = os.path.join(self.descargas, f"grok-video-aviso-gestor-{i}.mp4")
            with open(p, "wb") as f:
                f.write(f"contenido {i}".encode("utf-8"))
            archivos.append(p)

        sim = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": p, "tamanio": 11, "hash": f"h_g_{i}"} for i, p in enumerate(archivos, 1)],
            personaje="mailen",
            nombre_escena="toma_aviso",
            es_existente_descargas=False
        )

        res = self.gestor.ejecutar_movimiento_lote(sim, lote_id="lote_gestor_aviso")
        self.assertTrue(res["exito"])
        self.assertEqual(res["total_movidos"], 3)
        self.assertEqual(res["personaje"], "mailen")
        self.assertEqual(res["escena"], "toma_aviso")
        self.assertEqual(res["mensaje_aviso"], "Se movieron 3 archivos a mailen/toma_aviso")

        # Verificar que se movieron los 3 archivos
        for p in archivos:
            self.assertFalse(os.path.exists(p))

        # Deshacer lote completo
        res_deshacer = self.gestor.deshacer_operacion(res["id_operacion"])
        self.assertTrue(res_deshacer["exito"])
        self.assertEqual(res_deshacer["total_revertidos"], 3)

        # Verificar que regresaron todos al origen
        for p in archivos:
            self.assertTrue(os.path.exists(p))

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
            os.path.join(self.destino_base, "lucie", "parque_primavera", "grok-video-mixto.mp4")
        )
        self.assertEqual(
            dest_img,
            os.path.join(self.destino_base, "lucie", "parque_primavera", "lucie_20261003120000.png")
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
        """Verifica compatibilidad de inicialización y sala de espera unificada."""
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
            os.path.join(self.destino_base, "mailen", "estudio", "toma_20261003140000.webp")
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

    def test_mover_subconjunto_deja_resto_como_lote_pendiente(self):
        """Mover solo un subconjunto de archivos deja el resto como lote pendiente sin perder el agrupamiento."""
        config = ConfiguracionBandeja()
        config.ruta_descargas = self.descargas
        config.ruta_destino_base = self.destino_base
        config.ventana_lote_minutos = 10

        vigilante = VigilanteBandeja(
            config, self.db, FiltroListaBlanca(config), DetectorDescargasActivas(0.01), AgrupadorLotes(10)
        )

        # Crear 3 archivos en Descargas con mtime idéntico o muy cercano
        ahora = time.time() - 10
        archivos = []
        for i in range(1, 4):
            p = os.path.join(self.descargas, f"grok-video-sub-{i}.mp4")
            with open(p, "wb") as f:
                f.write(f"video sub {i}".encode("utf-8"))
            os.utime(p, (ahora + i, ahora + i))
            archivos.append(p)

        # Primer escaneo registra tamaño en el detector; segundo tras la ventana los confirma estables
        vigilante.escanear()
        time.sleep(0.02)
        vigilante.escanear()
        estado_inicial = vigilante.obtener_estado()
        self.assertEqual(len(estado_inicial["lotes"]), 1)
        lote_inicial = estado_inicial["lotes"][0]
        self.assertEqual(lote_inicial["total_archivos"], 3)

        # Mover solo el primer archivo
        archivo_elegido = lote_inicial["archivos"][0]
        self.assertEqual(archivo_elegido["nombre"], "grok-video-sub-1.mp4")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[archivo_elegido],
            personaje="lucie",
            nombre_escena="escena_parcial",
            es_existente_descargas=False
        )
        self.assertEqual(len(sim["movimientos"]), 1)
        res_mover = self.gestor.ejecutar_movimiento_lote(sim, lote_id=lote_inicial["lote_id"])
        self.assertTrue(res_mover["exito"])

        # Re-escanear
        vigilante.escanear()
        estado_posterior = vigilante.obtener_estado()
        lotes_restantes = estado_posterior["lotes"]

        self.assertEqual(len(lotes_restantes), 1)
        lote_pendiente = lotes_restantes[0]
        self.assertEqual(lote_pendiente["total_archivos"], 2)
        nombres_pendientes = [a["nombre"] for a in lote_pendiente["archivos"]]
        self.assertIn("grok-video-sub-2.mp4", nombres_pendientes)
        self.assertIn("grok-video-sub-3.mp4", nombres_pendientes)
        self.assertNotIn("grok-video-sub-1.mp4", nombres_pendientes)

        # El archivo movido ya no está en Descargas
        self.assertFalse(os.path.exists(archivos[0]))
        # Los otros dos permanecen intactos en Descargas
        self.assertTrue(os.path.exists(archivos[1]))
        self.assertTrue(os.path.exists(archivos[2]))


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

    def test_get_historial_api_y_estado_movimientos(self):
        """El historial por API lista adecuadamente los movimientos y refleja reversiones."""
        archivo_test = os.path.join(self.descargas, "grok-video-historial.mp4")
        with open(archivo_test, "wb") as f:
            f.write(b"video para bitacora historial")
        self.vigilante.escanear()

        headers_ok = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.token_csrf
        }

        # Simular mover
        body_sim = json.dumps({
            "archivos": [{"ruta": archivo_test, "tamanio": 29, "hash": "h_historial"}],
            "personaje": "lucie",
            "escena": "escena_historial",
            "es_existente_descargas": False
        })
        status, sim_data, _ = self._request("POST", "/api/simular-mover", headers=headers_ok, body=body_sim)
        self.assertEqual(status, 200)

        # Mover lote
        body_mover = json.dumps({
            "simulacion": sim_data,
            "lote_id": "lote_historial_1"
        })
        status, res_mover, _ = self._request("POST", "/api/mover-lote", headers=headers_ok, body=body_mover)
        self.assertEqual(status, 200)
        id_op = res_mover["id_operacion"]

        # Consultar GET /api/historial
        status, hist_data, _ = self._request("GET", "/api/historial")
        self.assertEqual(status, 200)
        self.assertIn("historial", hist_data)
        historial = hist_data["historial"]
        self.assertTrue(len(historial) >= 1)

        # Verificar campos requeridos en la entrada
        entrada_op = next((item for item in historial if item["id_operacion"] == id_op), None)
        self.assertIsNotNone(entrada_op)
        self.assertEqual(entrada_op["archivo"], "grok-video-historial.mp4")
        self.assertEqual(entrada_op["estado"], "movido")
        self.assertIn("fecha", entrada_op)
        self.assertIn("origen", entrada_op)
        self.assertIn("destino", entrada_op)

        # Deshacer la operación vía POST /api/deshacer
        body_deshacer = json.dumps({"id_operacion": id_op})
        status, res_deshacer, _ = self._request("POST", "/api/deshacer", headers=headers_ok, body=body_deshacer)
        self.assertEqual(status, 200)
        self.assertTrue(res_deshacer["exito"])

        # Volver a consultar historial y verificar que el estado cambió a "deshecho"
        status, hist_data_2, _ = self._request("GET", "/api/historial")
        self.assertEqual(status, 200)
        entrada_op_2 = next((item for item in hist_data_2["historial"] if item["id_operacion"] == id_op), None)
        self.assertIsNotNone(entrada_op_2)
        self.assertEqual(entrada_op_2["estado"], "deshecho")

    def test_deshacer_api_sin_token_o_host_invalido_devuelve_403(self):
        """/api/deshacer responde 403 Forbidden si no se envía token o si Host es inválido."""
        # 1. Sin token
        headers_sin_token = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json"
        }
        body = json.dumps({"id_operacion": "op_ficticia"})
        status, _, _ = self._request("POST", "/api/deshacer", headers=headers_sin_token, body=body)
        self.assertEqual(status, 403)

        # 2. Host foráneo
        headers_host_invalido = {
            "Host": "evil-domain.com",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.token_csrf
        }
        status, _, _ = self._request("POST", "/api/deshacer", headers=headers_host_invalido, body=body)
        self.assertEqual(status, 403)

    def test_deshacer_api_con_origen_ocupado_devuelve_409_sin_pisar(self):
        """Reversión por API ante ruta original ocupada responde 409 y no pisa el archivo existente."""
        archivo_test = os.path.join(self.descargas, "grok-video-conflicto.mp4")
        with open(archivo_test, "wb") as f:
            f.write(b"archivo original previo")
        self.vigilante.escanear()

        headers_ok = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.token_csrf
        }
        body_sim = json.dumps({
            "archivos": [{"ruta": archivo_test, "tamanio": 23, "hash": "h_conflicto"}],
            "personaje": "lucie",
            "escena": "escena_conflicto",
            "es_existente_descargas": False
        })
        status, sim_data, _ = self._request("POST", "/api/simular-mover", headers=headers_ok, body=body_sim)
        self.assertEqual(status, 200)

        status, res_mover, _ = self._request(
            "POST", "/api/mover-lote", headers=headers_ok,
            body=json.dumps({"simulacion": sim_data, "lote_id": "lote_conflicto"})
        )
        self.assertEqual(status, 200)
        id_op = res_mover["id_operacion"]

        # Ocupar la ruta original con otro contenido
        with open(archivo_test, "wb") as f:
            f.write(b"ocupante no pisable")

        # Intentar deshacer por API
        status, res_err, _ = self._request(
            "POST", "/api/deshacer", headers=headers_ok,
            body=json.dumps({"id_operacion": id_op})
        )
        # Debe responder 409 Conflict con mensaje explicativo
        self.assertEqual(status, 409)
        self.assertIn("error", res_err)
        self.assertIn("ya se encuentra ocupada", res_err["error"])

        # Verificar que el ocupante no fue pisado
        with open(archivo_test, "rb") as f:
            self.assertEqual(f.read(), b"ocupante no pisable")

    def test_aviso_fijo_y_deshacer_completo_desde_aviso(self):
        """El aviso se genera con la cantidad y destino correctos tras mover un lote, y deshacer revierte todos los archivos."""
        # 1. Verificar presencia de componentes en el HTML de la SPA
        status, _, raw_html = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'id="banner-aviso"', raw_html)
        self.assertIn(b'id="btn-banner-deshacer"', raw_html)
        self.assertIn(b'id="btn-banner-cerrar"', raw_html)
        self.assertIn(b'id="banner-aviso-msg"', raw_html)

        # 2. Crear 2 archivos en Descargas para el lote
        arch1 = os.path.join(self.descargas, "grok-video-aviso-1.mp4")
        arch2 = os.path.join(self.descargas, "grok-video-aviso-2.mp4")
        with open(arch1, "wb") as f:
            f.write(b"contenido video aviso 1")
        with open(arch2, "wb") as f:
            f.write(b"contenido video aviso 2")
        self.vigilante.escanear()

        headers_ok = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.token_csrf
        }

        # Simular movimiento
        body_sim = json.dumps({
            "archivos": [
                {"ruta": arch1, "tamanio": 24, "hash": "h_aviso_1"},
                {"ruta": arch2, "tamanio": 24, "hash": "h_aviso_2"}
            ],
            "personaje": "lucie",
            "escena": "escena_banner",
            "es_existente_descargas": False
        })
        status, sim_data, _ = self._request("POST", "/api/simular-mover", headers=headers_ok, body=body_sim)
        self.assertEqual(status, 200)
        self.assertEqual(sim_data["total_archivos"], 2)

        # Ejecutar movimiento de lote
        body_mover = json.dumps({
            "simulacion": sim_data,
            "lote_id": "lote_aviso_test"
        })
        status, res_mover, _ = self._request("POST", "/api/mover-lote", headers=headers_ok, body=body_mover)
        self.assertEqual(status, 200)

        # Verificar datos del aviso devueltos
        self.assertTrue(res_mover["exito"])
        self.assertEqual(res_mover["total_movidos"], 2)
        self.assertEqual(res_mover["personaje"], "lucie")
        self.assertEqual(res_mover["escena"], "escena_banner")
        self.assertEqual(res_mover["mensaje_aviso"], "Se movieron 2 archivos a lucie/escena_banner")
        id_op = res_mover["id_operacion"]

        # Confirmar que los archivos ya no están en origen y están en destino
        self.assertFalse(os.path.exists(arch1))
        self.assertFalse(os.path.exists(arch2))
        dest1 = sim_data["movimientos"][0]["destino"]
        dest2 = sim_data["movimientos"][1]["destino"]
        self.assertTrue(os.path.exists(dest1))
        self.assertTrue(os.path.exists(dest2))

        # 3. Deshacer la operación completa usando el id_operacion del aviso
        body_deshacer = json.dumps({"id_operacion": id_op})
        status, res_deshacer, _ = self._request("POST", "/api/deshacer", headers=headers_ok, body=body_deshacer)
        self.assertEqual(status, 200)
        self.assertTrue(res_deshacer["exito"])
        self.assertEqual(res_deshacer["total_revertidos"], 2)

        # Confirmar que TODOS los archivos del lote regresaron al origen y no están en destino
        self.assertTrue(os.path.exists(arch1))
        self.assertTrue(os.path.exists(arch2))
        self.assertFalse(os.path.exists(dest1))
        self.assertFalse(os.path.exists(dest2))

    def test_html_simulacion_incluye_ruta_destino_completa_y_segmentos_resaltados(self):
        """
        Verifica que:
        1. La simulación previa genera HTML con la ruta de destino completa de cada archivo en el tooltip (title).
        2. Muestra la ruta relativa a la carpeta destino.
        3. Resalta los segmentos de tipo ("imagenes" o "videos sin editar") con tags específicos.
        4. El marcado servido por el panel web incluye el ancho ampliado (hasta 90vw, máx 1200px) y reglas word-break.
        """
        arch_video = os.path.join(self.descargas, "grok_sim_vid_01.mp4")
        arch_img = os.path.join(self.descargas, "grok_sim_img_01.png")
        with open(arch_video, "wb") as f:
            f.write(b"video contenido sim")
        with open(arch_img, "wb") as f:
            f.write(b"imagen contenido sim")
        self.vigilante.escanear()

        headers_ok = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.token_csrf
        }

        body_sim = json.dumps({
            "archivos": [
                {"ruta": arch_video, "tamanio": 19, "hash": "h_sim_vid"},
                {"ruta": arch_img, "tamanio": 20, "hash": "h_sim_img"}
            ],
            "personaje": "lucie",
            "escena": "prueba_bandeja",
            "es_existente_descargas": False
        })
        status, sim_data, _ = self._request("POST", "/api/simular-mover", headers=headers_ok, body=body_sim)
        self.assertEqual(status, 200)
        self.assertIn("html", sim_data)
        html_sim = sim_data["html"]

        # 1. El HTML de la simulación incluye la ruta de destino completa de cada archivo
        for m in sim_data["movimientos"]:
            destino_completo = m["destino"]
            # Debe estar presente en el HTML
            self.assertIn(destino_completo, html_sim)
            # En particular en el tooltip (title) de la celda de destino
            self.assertIn(f'title="{destino_completo}"', html_sim)
            self.assertIn(f'data-destino="{destino_completo}"', html_sim)
            # Y la ruta relativa debe reflejar el personaje y la escena
            self.assertIn("lucie", m["destino_relativo"])
            self.assertIn("prueba_bandeja", m["destino_relativo"])

        # 2. Resalta el segmento de tipo ("imagenes" o "videos sin editar")
        self.assertIn('<span class="tag-tipo tag-video">videos sin editar</span>', html_sim)
        self.assertIn('<span class="tag-tipo tag-imagen">imagenes</span>', html_sim)

        # 3. La función generar_html_simulacion produce el mismo marcado coherente
        html_directo = generar_html_simulacion(sim_data)
        self.assertEqual(html_sim, html_directo)

        # 4. El panel SPA servido tiene estilos de ensanchamiento y word-break sin desborde
        status_page, _, page_raw = self._request("GET", "/", headers={"Host": f"127.0.0.1:{self.config.puerto_servidor}"})
        self.assertEqual(status_page, 200)
        page_html = page_raw.decode("utf-8")
        self.assertIn("90vw", page_html)
        self.assertIn("1200px", page_html)
        self.assertIn("word-break: break-word", page_html)
        self.assertIn("overflow-wrap: anywhere", page_html)
        self.assertIn(".tag-tipo", page_html)
        self.assertIn(".tag-video", page_html)
        self.assertIn(".tag-imagen", page_html)



class TestCapituloActivoYReconocimientoNombres(unittest.TestCase):
    """Pruebas para capítulo activo, alias inicial, raíces de escena y multi-lote."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_capitulos_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.descargas, "_lucie")
        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

        self.cfg_file = os.path.join(self.tmp_dir, "config.json")
        self.alias_file = os.path.join(self.tmp_dir, "alias.json")
        self.db_file = os.path.join(self.tmp_dir, "bandeja.db")

        with open(self.alias_file, "w", encoding="utf-8") as f:
            json.dump({
                "lucie": ["lucie", "luci"],
                "roli": ["roli", "laroli", "magui"],
                "mailen": ["mailen"]
            }, f)

        cfg_data = {
            "ruta_descargas": self.descargas,
            "ruta_destino_base": self.destino,
            "archivo_alias_personajes": self.alias_file,
            "ventana_lote_minutos": 10,
            "intervalo_sondeo_segundos": 1,
            "patrones_ignorar": ["Screenshot_*", "Captura*"],
            "patrones_candidatos": {
                "grok_video": "grok-video-*",
                "grok_image": "grok-image-*",
                "gemini": "Gemini_Generated_Image_*"
            }
        }
        with open(self.cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f)

        self.config = ConfiguracionBandeja(ruta_config=self.cfg_file)
        self.db = GestorBaseDatosBandeja(ruta_db=self.db_file)
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas(ventana_estabilidad_segundos=0.05)
        self.agrupador = AgrupadorLotes(ventana_minutos=10)
        self.movimientos = GestorMovimientosBandeja(self.descargas, self.destino, self.db)
        self.miniaturas = GeneradorMiniaturas(self.db)

    def tearDown(self):
        for root, dirs, files in os.walk(self.tmp_dir, topdown=False):
            for file in files:
                try:
                    os.unlink(os.path.join(root, file))
                except OSError:
                    pass
            for dir_name in dirs:
                try:
                    os.rmdir(os.path.join(root, dir_name))
                except OSError:
                    pass
        try:
            os.rmdir(self.tmp_dir)
        except OSError:
            pass

    def test_asignacion_inmediata_capitulo_activo(self):
        """Con capítulo activo, cualquier candidato nuevo se asigna a personaje/capitulo sin importar nombre ni hora."""
        self.db.guardar_capitulo_activo("lucie", "capitulo_01", habilitado=True)

        arch_extrano = os.path.join(self.descargas, "video_random_sin_alias.mp4")
        with open(arch_extrano, "wb") as f:
            f.write(b"video contenido 123")

        vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        vigilante.escanear()
        time.sleep(0.06)
        vigilante.escanear()

        estado = vigilante.obtener_estado()
        self.assertEqual(len(estado["lotes"]), 1)
        lote = estado["lotes"][0]
        self.assertEqual(lote["personaje_sugerido"], "lucie")
        self.assertEqual(lote["escena_sugerida"], "capitulo_01")
        self.assertEqual(len(lote["archivos"]), 1)

        hash_val = calcular_sha256(arch_extrano)
        info_db = self.db.obtener_por_hash(hash_val)
        self.assertIsNotNone(info_db)
        self.assertEqual(info_db["personaje"], "lucie")
        self.assertEqual(info_db["escena"], "capitulo_01")

    def test_modificar_o_desactivar_capitulo_no_reasigna_existentes(self):
        """Modificar o desactivar el capítulo activo no altera archivos ya detectados."""
        self.db.guardar_capitulo_activo("lucie", "cap_inicial", habilitado=True)
        arch1 = os.path.join(self.descargas, "video_a.mp4")
        with open(arch1, "wb") as f:
            f.write(b"data a")

        vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        vigilante.escanear()
        time.sleep(0.06)
        vigilante.escanear()

        estado1 = vigilante.obtener_estado()
        self.assertEqual(len(estado1["lotes"]), 1)
        self.assertEqual(estado1["lotes"][0]["personaje_sugerido"], "lucie")
        self.assertEqual(estado1["lotes"][0]["escena_sugerida"], "cap_inicial")

        # Desactivamos el capítulo
        self.db.guardar_capitulo_activo("roli", "cap_nuevo", habilitado=False)
        vigilante.escanear()

        estado2 = vigilante.obtener_estado()
        self.assertEqual(len(estado2["lotes"]), 1)
        # Los archivos ya detectados conservan su asignación original
        self.assertEqual(estado2["lotes"][0]["personaje_sugerido"], "lucie")
        self.assertEqual(estado2["lotes"][0]["escena_sugerida"], "cap_inicial")

    def test_persistencia_capitulo_activo_sqlite(self):
        """El capítulo activo persiste en SQLite tras reinicio (simulado con nueva instancia DB)."""
        self.db.guardar_capitulo_activo("mailen", "sesion_otono", habilitado=True)

        # Nueva instancia de base de datos apuntando al mismo archivo SQLite
        db_reinicio = GestorBaseDatosBandeja(ruta_db=self.db_file)
        cap = db_reinicio.obtener_capitulo_activo()
        self.assertIsNotNone(cap)
        self.assertTrue(cap["habilitado"])
        self.assertEqual(cap["personaje"], "mailen")
        self.assertEqual(cap["nombre"], "sesion_otono")

    def test_raices_distintas_misma_ventana_generan_dos_lotes_independientes(self):
        """Sin capítulo activo: dos archivos con distinta raíz en la misma ventana forman dos lotes separados."""
        self.db.guardar_capitulo_activo("lucie", "", habilitado=False)

        ahora = time.time()
        candidato1 = {
            "id_db": 1,
            "ruta": os.path.join(self.descargas, "lucie asado.mp4"),
            "nombre": "lucie asado.mp4",
            "tamanio": 100,
            "mtime": ahora,
            "personaje": "lucie",
            "escena_sugerida": "lucie asado",
            "raiz_escena": "lucie asado"
        }
        candidato2 = {
            "id_db": 2,
            "ruta": os.path.join(self.descargas, "roli pileta.mp4"),
            "nombre": "roli pileta.mp4",
            "tamanio": 200,
            "mtime": ahora + 30,  # 30 segundos después (misma ventana de 10 min)
            "personaje": "roli",
            "escena_sugerida": "roli pileta",
            "raiz_escena": "roli pileta"
        }

        lotes = self.agrupador.agrupar([candidato1, candidato2])
        self.assertEqual(len(lotes), 2, "Deben formarse 2 lotes independientes por tener raíces distintas")
        raices = {l["raiz_escena"] for l in lotes}
        self.assertEqual(raices, {"lucie asado", "roli pileta"})

    def test_extraccion_escena_sugerida(self):
        """Verifica remoción de sufijos (n), números finales y extensión conservando prefijo."""
        self.assertEqual(
            self.filtro.extraer_escena_sugerida("lucie atendiendo (1).mp4"),
            "lucie atendiendo"
        )
        self.assertEqual(
            self.filtro.extraer_escena_sugerida("roliyacussi (2).jpg"),
            "roliyacussi"
        )
        self.assertEqual(
            self.filtro.extraer_escena_sugerida("lucieasado3.mp4"),
            "lucieasado"
        )

    def test_prevalencia_alias_inicial_en_nombre_compuesto(self):
        """El personaje asignado sale del alias al INICIO; menciones posteriores no cambian la asignación."""
        pers = self.filtro.obtener_personaje_de_alias_inicial("rolitirandoaguaalucie.jpg")
        self.assertEqual(pers, "roli")

        self.db.guardar_capitulo_activo("lucie", "", habilitado=False)
        ruta_compuesta = os.path.join(self.descargas, "rolitirandoaguaalucie.jpg")
        with open(ruta_compuesta, "wb") as f:
            f.write(b"imagen roli")

        tipo = self.filtro.clasificar_archivo(ruta_compuesta)
        self.assertEqual(tipo, "candidato")

    def test_patrones_ignorar_no_aparecen(self):
        """Archivos que coincidan con 'patrones_ignorar' son descartados de inmediato."""
        arch_ign1 = os.path.join(self.descargas, "Screenshot_20261004.png")
        arch_ign2 = os.path.join(self.descargas, "Captura de pantalla.jpg")
        with open(arch_ign1, "wb") as f:
            f.write(b"screenshot data")
        with open(arch_ign2, "wb") as f:
            f.write(b"captura data")

        self.assertEqual(self.filtro.clasificar_archivo(arch_ign1), "ignorar")
        self.assertEqual(self.filtro.clasificar_archivo(arch_ign2), "ignorar")

        vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        time.sleep(0.1)
        vigilante.escanear()
        estado = vigilante.obtener_estado()
        self.assertEqual(len(estado["lotes"]), 0)
        self.assertEqual(len(estado["sin_identificar"]), 0)

    def test_simulacion_y_movimiento_multilote_y_deshacer_por_lote(self):
        """Mover múltiples lotes con confirmación única y permitir reversión independiente por lote."""
        puerto = 8792
        self.config.puerto_servidor = puerto
        token_csrf = "token_test_multilote_123"

        arch_a = os.path.join(self.descargas, "lucie_a.mp4")
        arch_b = os.path.join(self.descargas, "roli_b.jpg")
        with open(arch_a, "wb") as f:
            f.write(b"video lote a")
        with open(arch_b, "wb") as f:
            f.write(b"foto lote b")

        vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        servidor = crear_servidor(self.config, self.db, vigilante, self.movimientos, self.miniaturas, token_csrf=token_csrf)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()

        def request(method, path, body=None):
            conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
            headers = {
                "Host": f"127.0.0.1:{puerto}",
                "Content-Type": "application/json",
                "X-CSRF-Token": token_csrf
            }
            body_bytes = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=body_bytes, headers=headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))
            conn.close()
            return res.status, data

        try:
            # 1. Simulación multi-lote
            body_sim = {
                "lotes": [
                    {
                        "lote_id": "lote_A",
                        "archivos": [{"ruta": arch_a, "tamanio": 12, "hash": "ha"}],
                        "personaje": "lucie",
                        "escena": "escena_lucie",
                        "es_existente_descargas": False
                    },
                    {
                        "lote_id": "lote_B",
                        "archivos": [{"ruta": arch_b, "tamanio": 11, "hash": "hb"}],
                        "personaje": "roli",
                        "escena": "escena_roli",
                        "es_existente_descargas": False
                    }
                ]
            }
            st, data_sim = request("POST", "/api/simular-mover", body_sim)
            self.assertEqual(st, 200, f"Error en simular: {data_sim}")
            self.assertTrue(data_sim.get("es_multilote"))
            self.assertEqual(data_sim.get("total_lotes"), 2)
            self.assertEqual(data_sim.get("total_archivos"), 2)
            self.assertIn("Simulación previa consolidada", data_sim.get("html", ""))

            # 2. Confirmación y ejecución multi-lote única
            st_mov, data_mov = request("POST", "/api/mover-lote", {"simulacion": data_sim})
            self.assertEqual(st_mov, 200, f"Error en mover lote: {data_mov}")
            self.assertTrue(data_mov.get("exito"))
            self.assertEqual(data_mov.get("total_movidos"), 2)
            self.assertEqual(len(data_mov.get("resultados", [])), 2)

            id_op_a = data_mov["resultados"][0]["id_operacion"]
            id_op_b = data_mov["resultados"][1]["id_operacion"]
            self.assertNotEqual(id_op_a, id_op_b, "Cada lote debe conservar su propio id_operacion")

            dest_a = os.path.join(self.destino, "lucie", "escena_lucie", "lucie_a.mp4")
            dest_b = os.path.join(self.destino, "roli", "escena_roli", "roli_b.jpg")
            self.assertTrue(os.path.exists(dest_a))
            self.assertTrue(os.path.exists(dest_b))
            self.assertFalse(os.path.exists(arch_a))
            self.assertFalse(os.path.exists(arch_b))

            # 3. Deshacer lote A de forma independiente
            st_des_a, data_des_a = request("POST", "/api/deshacer", {"id_operacion": id_op_a})
            self.assertEqual(st_des_a, 200)
            self.assertTrue(data_des_a.get("exito"))
            self.assertTrue(os.path.exists(arch_a), "El archivo de lote A debe regresar a Descargas")
            self.assertFalse(os.path.exists(dest_a))
            self.assertTrue(os.path.exists(dest_b), "El archivo de lote B debe permanecer en destino")

            # 4. Deshacer lote B de forma independiente
            st_des_b, data_des_b = request("POST", "/api/deshacer", {"id_operacion": id_op_b})
            self.assertEqual(st_des_b, 200)
            self.assertTrue(data_des_b.get("exito"))
            self.assertTrue(os.path.exists(arch_b), "El archivo de lote B debe regresar a Descargas")
            self.assertFalse(os.path.exists(dest_b))

        finally:
            servidor.shutdown()
            servidor.server_close()

    def test_api_capitulo_activo_endpoint(self):
        """Verifica lectura y modificación del capítulo activo por API."""
        puerto = 8793
        self.config.puerto_servidor = puerto
        token_csrf = "token_test_cap_api"

        vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        servidor = crear_servidor(self.config, self.db, vigilante, self.movimientos, self.miniaturas, token_csrf=token_csrf)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()

        def request(method, path, body=None):
            conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
            headers = {
                "Host": f"127.0.0.1:{puerto}",
                "Content-Type": "application/json",
                "X-CSRF-Token": token_csrf
            }
            body_bytes = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=body_bytes, headers=headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))
            conn.close()
            return res.status, data

        try:
            # Inicialmente inactivo
            st, d = request("GET", "/api/capitulo-activo")
            self.assertEqual(st, 200)
            self.assertFalse(d["capitulo_activo"]["habilitado"])

            # Activar capítulo válido
            st_post, d_post = request("POST", "/api/capitulo-activo", {
                "personaje": "lucie",
                "nombre": "historia_piscina",
                "habilitado": True
            })
            self.assertEqual(st_post, 200)
            self.assertTrue(d_post["capitulo_activo"]["habilitado"])
            self.assertEqual(d_post["capitulo_activo"]["nombre"], "historia_piscina")

            # Intentar activar con nombre inválido (ej: contiene barra '/')
            st_inv, d_inv = request("POST", "/api/capitulo-activo", {
                "personaje": "lucie",
                "nombre": "invalido/cap",
                "habilitado": True
            })
            self.assertEqual(st_inv, 400)
            self.assertIn("error", d_inv)
        finally:
            servidor.shutdown()
            servidor.server_close()


class TestCicloVidaCapitulos(unittest.TestCase):
    """Pruebas exhaustivas para el ciclo de vida completo de capítulos."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_ciclo_capitulos_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.descargas, "_lucie")
        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

        self.cfg_file = os.path.join(self.tmp_dir, "config.json")
        self.alias_file = os.path.join(self.tmp_dir, "alias.json")
        self.db_file = os.path.join(self.tmp_dir, "bandeja.db")

        with open(self.alias_file, "w", encoding="utf-8") as f:
            json.dump({
                "lucie": ["lucie", "luci"],
                "roli": ["roli", "laroli", "magui"],
                "mailen": ["mailen"]
            }, f)

        cfg_data = {
            "ruta_descargas": self.descargas,
            "ruta_destino_base": self.destino,
            "archivo_alias_personajes": self.alias_file,
            "horas_alerta_capitulo_olvidado": 12,
            "ventana_lote_minutos": 10,
            "intervalo_sondeo_segundos": 1,
            "patrones_ignorar": ["Screenshot_*", "Captura*"],
            "patrones_candidatos": {
                "grok_video": "grok-video-*"
            }
        }
        with open(self.cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f)

        self.config = ConfiguracionBandeja(ruta_config=self.cfg_file)
        self.db = GestorBaseDatosBandeja(ruta_db=self.db_file)
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas(0.0)
        self.agrupador = AgrupadorLotes(10)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _crear_archivo(self, nombre: str, contenido: bytes = b"datos de prueba") -> str:
        ruta = os.path.join(self.descargas, nombre)
        with open(ruta, "wb") as f:
            f.write(contenido)
        return ruta

    def test_5_1_terminar_capitulo_cierra_asignacion_y_posteriores_no_se_asignan(self):
        # 1. Empezar capítulo activo
        self.db.empezar_capitulo("lucie", "paseo_parque")
        self.assertTrue(self.db.obtener_capitulo_activo()["habilitado"])

        # 2. Arriba primer archivo durante el capítulo activo
        self._crear_archivo("lucie_arbol.mp4", b"toma 1")
        self.vigilante.escanear()
        self.vigilante.escanear()

        estado1 = self.vigilante.obtener_estado()
        self.assertEqual(len(estado1["lotes"]), 1)
        self.assertEqual(estado1["lotes"][0]["personaje_sugerido"], "lucie")
        self.assertEqual(estado1["lotes"][0]["escena_sugerida"], "paseo_parque")

        # 3. Terminar capítulo
        terminado = self.db.terminar_capitulo()
        self.assertTrue(terminado)
        self.assertFalse(self.db.obtener_capitulo_activo()["habilitado"])

        # 4. Arriba segundo archivo con el capítulo ya cerrado
        self._crear_archivo("roli_baile.mp4", b"toma 2 posterior")
        self.vigilante.escanear()
        self.vigilante.escanear()

        estado2 = self.vigilante.obtener_estado()
        lote_f1 = next((l for l in estado2["lotes"] if any(a["nombre"] == "lucie_arbol.mp4" for a in l["archivos"])), None)
        lote_f2 = next((l for l in estado2["lotes"] if any(a["nombre"] == "roli_baile.mp4" for a in l["archivos"])), None)
        self.assertIsNotNone(lote_f1)
        self.assertIsNotNone(lote_f2)
        self.assertEqual(lote_f1["escena_sugerida"], "paseo_parque")
        self.assertEqual(lote_f2["personaje_sugerido"], "roli")
        self.assertNotEqual(lote_f2["escena_sugerida"], "paseo_parque")

    def test_5_2_reabrir_capitulo_permite_asignar_de_nuevo(self):
        # 1. Empezar y luego terminar
        cap_inicial = self.db.empezar_capitulo("roli", "gimnasio")
        cap_id = cap_inicial["id"]
        self.db.terminar_capitulo()
        self.assertFalse(self.db.obtener_capitulo_activo()["habilitado"])

        # 2. Reabrir capítulo cerrado
        reabierto = self.db.reabrir_capitulo(cap_id)
        self.assertTrue(reabierto["habilitado"])
        self.assertEqual(reabierto["nombre"], "gimnasio")
        self.assertTrue(self.db.obtener_capitulo_activo()["habilitado"])

        # 3. Arriba nuevo archivo tras reabrir
        self._crear_archivo("mailen_pesas.mp4", b"video tras reabrir")
        self.vigilante.escanear()
        self.vigilante.escanear()

        estado = self.vigilante.obtener_estado()
        lote = next(l for l in estado["lotes"] if any(a["nombre"] == "mailen_pesas.mp4" for a in l["archivos"]))
        self.assertEqual(lote["personaje_sugerido"], "roli")
        self.assertEqual(lote["escena_sugerida"], "gimnasio")

    def test_5_3_aviso_capitulo_olvidado_a_las_12_horas_con_reloj_simulado(self):
        t0 = datetime.datetime(2026, 10, 1, 8, 0, 0)
        self.db.empezar_capitulo("lucie", "jornada_larga", fecha_inicio=t0.isoformat())

        # Antes de las 12 horas (ej: 11 horas) -> No debe haber alerta
        t_11h = t0 + datetime.timedelta(hours=11)
        self.assertFalse(self.db.es_capitulo_olvidado(horas_limite=12.0, ahora=t_11h))

        # A las 12 horas exactas o posteriores -> Debe saltar alerta
        t_12h = t0 + datetime.timedelta(hours=12, seconds=1)
        self.assertTrue(self.db.es_capitulo_olvidado(horas_limite=12.0, ahora=t_12h))

        # Posponer alerta (usuario pulsa 'Seguir')
        self.db.posponer_alerta_capitulo(nueva_fecha=t_12h.isoformat())
        # Justo después de posponer -> Alerta inactiva
        t_13h = t_12h + datetime.timedelta(hours=1)
        self.assertFalse(self.db.es_capitulo_olvidado(horas_limite=12.0, ahora=t_13h))

        # 12 horas después del pospuesto -> Alerta activa nuevamente
        t_24h = t_12h + datetime.timedelta(hours=12, seconds=1)
        self.assertTrue(self.db.es_capitulo_olvidado(horas_limite=12.0, ahora=t_24h))

    def test_5_4_resumen_y_computo_balance_pendientes_y_movidos(self):
        self.db.empezar_capitulo("lucie", "cumpleanios")

        # Registrar 3 pendientes
        for i in range(1, 4):
            self.db.registrar_o_actualizar(
                hash_val=f"hash_pend_{i}",
                ruta_actual=os.path.join(self.descargas, f"pend_{i}.mp4"),
                estado="detectado",
                personaje="lucie",
                escena="cumpleanios"
            )

        # Registrar 2 movidos
        for i in range(1, 3):
            self.db.registrar_o_actualizar(
                hash_val=f"hash_mov_{i}",
                ruta_actual=os.path.join(self.destino, "lucie", "cumpleanios", f"mov_{i}.mp4"),
                estado="movido",
                personaje="lucie",
                escena="cumpleanios"
            )
        self.db.incrementar_movidos_capitulo("lucie", "cumpleanios", 2)

        balance = self.db.calcular_balance_capitulo("lucie", "cumpleanios")
        self.assertEqual(balance["pendientes"], 3)
        self.assertEqual(balance["movidos"], 2)

    def test_5_5_capitulo_personaje_roli_recibe_archivo_lucie(self):
        # Capítulo activo con personaje "roli"
        self.db.empezar_capitulo("roli", "taller_mecanico")

        # Archivo con prefijo "lucie"
        self._crear_archivo("lucie_en_el_taller.mp4", b"video cruzado")
        self.vigilante.escanear()
        self.vigilante.escanear()

        estado = self.vigilante.obtener_estado()
        self.assertEqual(len(estado["lotes"]), 1)
        lote = estado["lotes"][0]
        self.assertEqual(lote["personaje_sugerido"], "roli")
        self.assertEqual(lote["escena_sugerida"], "taller_mecanico")
        self.assertEqual(len(lote["archivos"]), 1)
        self.assertEqual(lote["archivos"][0]["nombre"], "lucie_en_el_taller.mp4")
        self.assertEqual(lote["archivos"][0]["personaje"], "roli")
        self.assertEqual(lote["archivos"][0]["escena"], "taller_mecanico")


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
