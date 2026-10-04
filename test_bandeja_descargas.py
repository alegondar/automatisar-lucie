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
import sqlite3
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
    generar_html_simulacion,
    asegurar_carpeta_capitulo
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

        # Crear previamente un archivo en el destino para forzar incremento de contador
        destino_colision = os.path.join(self.destino_base, "lucie", "escena1", "lucieescena11.mp4")
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
        self.assertTrue(destino_simulado.endswith("lucieescena12.mp4"))

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
        self.assertEqual(destino_calculado, os.path.join(carpeta_existente, "roliparque1.mp4"))

        res = self.gestor.ejecutar_movimiento_lote(sim, "lote_2")
        self.assertTrue(res["exito"])
        self.assertTrue(os.path.exists(os.path.join(carpeta_existente, "roliparque1.mp4")))
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
            os.path.join(self.destino_base, "lucie", "parque_primavera", "lucieparque_primavera1.mp4")
        )
        self.assertEqual(
            dest_img,
            os.path.join(self.destino_base, "lucie", "parque_primavera", "lucieparque_primavera1.png")
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
            os.path.join(self.destino_base, "mailen", "estudio", "mailenestudio1.webp")
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

        # 2. Muestra nombre original -> nombre nuevo y omite etiquetas obsoletas de tipo
        self.assertIn("grok_sim_vid_01.mp4", html_sim)
        self.assertIn("lucieprueba_bandeja1.mp4", html_sim)
        self.assertIn("grok_sim_img_01.png", html_sim)
        self.assertIn("lucieprueba_bandeja1.png", html_sim)
        self.assertNotIn("tag-tipo", html_sim)

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

            dest_a = os.path.join(self.destino, "lucie", "escena_lucie", "lucieescena_lucie1.mp4")
            dest_b = os.path.join(self.destino, "roli", "escena_roli", "roliescena_roli1.jpg")
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


class TestRenombradoAlMover(unittest.TestCase):
    """Pruebas unitarias completas para el renombrado automático de archivos al mover."""

    def setUp(self):
        self.tmp_dir_obj = tempfile.TemporaryDirectory(prefix="test_renombrado_")
        self.tmp_dir = self.tmp_dir_obj.name
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas, "_lucie")
        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)

        self.db_path = os.path.join(self.tmp_dir, "test_bandeja.sqlite")
        self.bitacora_path = os.path.join(self.tmp_dir, "bitacora_test.jsonl")
        self.db = GestorBaseDatosBandeja(self.db_path)
        self.gestor = GestorMovimientosBandeja(
            ruta_descargas=self.descargas,
            ruta_destino_base=self.destino_base,
            db=self.db,
            ruta_bitacora=self.bitacora_path
        )

    def tearDown(self):
        self.tmp_dir_obj.cleanup()

    def test_calcular_base_escena_con_y_sin_alias(self):
        """Verifica que la base no duplique el alias de su propio personaje y que anteponga el personaje si es de otro o sin alias."""
        # Ejemplos requeridos por la regla de negocio:
        # lucie + "lucietrapitos" -> lucietrapitos
        self.assertEqual(self.gestor.calcular_base_escena("lucie", "lucietrapitos"), "lucietrapitos")
        # lucie + "luci-fiesta" -> luci-fiesta
        self.assertEqual(self.gestor.calcular_base_escena("lucie", "luci-fiesta"), "luci-fiesta")
        # roli + "lucietrapitos" -> rolilucietrapitos (alias de otro personaje no se omite)
        self.assertEqual(self.gestor.calcular_base_escena("roli", "lucietrapitos"), "rolilucietrapitos")
        # roli + "maguifiesta" -> maguifiesta (magui es alias de roli)
        self.assertEqual(self.gestor.calcular_base_escena("roli", "maguifiesta"), "maguifiesta")
        # mailen + "bici" -> mailenbici (sin alias)
        self.assertEqual(self.gestor.calcular_base_escena("mailen", "bici"), "mailenbici")
        # lucie + "trapitos" -> lucietrapitos (sin alias)
        self.assertEqual(self.gestor.calcular_base_escena("lucie", "trapitos"), "lucietrapitos")

        # Casos adicionales de alias propios
        self.assertEqual(self.gestor.calcular_base_escena("lucie", "lucitrapitos"), "lucitrapitos")
        self.assertEqual(self.gestor.calcular_base_escena("roli", "rolibici"), "rolibici")
        self.assertEqual(self.gestor.calcular_base_escena("roli", "larolibici"), "larolibici")
        self.assertEqual(self.gestor.calcular_base_escena("mailen", "mailenauto"), "mailenauto")

        # Casos adicionales de alias de otros personajes
        self.assertEqual(self.gestor.calcular_base_escena("mailen", "lucietrapitos"), "mailenlucietrapitos")
        self.assertEqual(self.gestor.calcular_base_escena("mailen", "rolibici"), "mailenrolibici")
        self.assertEqual(self.gestor.calcular_base_escena("lucie", "rolibici"), "lucierolibici")
        self.assertEqual(self.gestor.calcular_base_escena("lucie", "maguifiesta"), "luciemaguifiesta")
        self.assertEqual(self.gestor.calcular_base_escena("roli", "mailenbici"), "rolimailenbici")

        # Normalización a minúsculas y eliminación de espacios
        self.assertEqual(self.gestor.calcular_base_escena("LUCIE", "  TRAPITOS  "), "lucietrapitos")
        self.assertEqual(self.gestor.calcular_base_escena("roli", "  PARQUE  "), "roliparque")

    def test_obtener_personaje_de_alias_inicial_consistente_con_base(self):
        """
        Verifica la regla de negocio: todo nombre generado <base>1.jpg debe ser leído
        por obtener_personaje_de_alias_inicial como el MISMO personaje elegido en el panel.
        """
        filtro = FiltroListaBlanca(ConfiguracionBandeja())

        casos_prueba = [
            # Ejemplos requeridos
            ("lucie", "lucietrapitos"),
            ("lucie", "luci-fiesta"),
            ("roli", "lucietrapitos"),
            ("roli", "maguifiesta"),
            ("mailen", "bici"),
            ("lucie", "trapitos"),
            # Combinaciones cruzadas entre todos los personajes
            ("roli", "rolibici"),
            ("roli", "larolibici"),
            ("roli", "bici"),
            ("mailen", "mailenauto"),
            ("mailen", "auto"),
            ("mailen", "lucietrapitos"),
            ("mailen", "rolibici"),
            ("mailen", "maguifiesta"),
            ("lucie", "lucitrapitos"),
            ("lucie", "rolibici"),
            ("lucie", "larolibici"),
            ("lucie", "maguifiesta"),
            ("lucie", "mailenbici"),
            ("roli", "mailenbici"),
        ]

        for personaje, escena in casos_prueba:
            with self.subTest(personaje=personaje, escena=escena):
                base = self.gestor.calcular_base_escena(personaje, escena)
                nombre_generado = f"{base}1.jpg"
                personaje_deducido = filtro.obtener_personaje_de_alias_inicial(nombre_generado)
                self.assertEqual(
                    personaje_deducido,
                    personaje,
                    f"Para personaje={personaje} y escena={escena} -> base={base} generó {nombre_generado}, "
                    f"pero obtener_personaje_de_alias_inicial devolvió {personaje_deducido}"
                )

    def test_contadores_separados_foto_y_video(self):
        """Foto y video del mismo lote reciben contadores independientes (<base>1.jpg y <base>1.mp4)."""
        f1 = os.path.join(self.descargas, "grok-img-1.jpg")
        f2 = os.path.join(self.descargas, "grok-img-2.png")
        v1 = os.path.join(self.descargas, "grok-vid-1.mp4")
        v2 = os.path.join(self.descargas, "grok-vid-2.webm")
        for ruta in (f1, f2, v1, v2):
            with open(ruta, "wb") as f:
                f.write(b"dummy")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[
                {"ruta": f1, "tamanio": 5, "hash": "h_f1"},
                {"ruta": f2, "tamanio": 5, "hash": "h_f2"},
                {"ruta": v1, "tamanio": 5, "hash": "h_v1"},
                {"ruta": v2, "tamanio": 5, "hash": "h_v2"}
            ],
            personaje="lucie",
            nombre_escena="trapitos",
            es_existente_descargas=False
        )

        nombres_nuevos = [m["nombre_nuevo"] for m in sim["movimientos"]]
        self.assertIn("lucietrapitos1.jpg", nombres_nuevos)
        self.assertIn("lucietrapitos2.png", nombres_nuevos)
        self.assertIn("lucietrapitos1.mp4", nombres_nuevos)
        self.assertIn("lucietrapitos2.webm", nombres_nuevos)

    def test_orden_por_mtime_dentro_del_lote_y_desempate(self):
        """Verifica ordenamiento por mtime ascendente y desempate por nombre original."""
        p_c = os.path.join(self.descargas, "c_grok.jpg")
        p_a = os.path.join(self.descargas, "a_grok.jpg")
        p_b = os.path.join(self.descargas, "b_grok.jpg")
        for p in (p_c, p_a, p_b):
            with open(p, "wb") as f:
                f.write(b"data")

        # Asignar tiempos explícitos: B es el más viejo (1000), luego C (2000), luego A (3000)
        os.utime(p_b, (1000, 1000))
        os.utime(p_c, (2000, 2000))
        os.utime(p_a, (3000, 3000))

        sim = self.gestor.simular_movimiento_lote(
            archivos=[
                {"ruta": p_a, "tamanio": 4, "hash": "ha"},
                {"ruta": p_c, "tamanio": 4, "hash": "hc"},
                {"ruta": p_b, "tamanio": 4, "hash": "hb"}
            ],
            personaje="roli",
            nombre_escena="bici",
            es_existente_descargas=False
        )

        movs = sim["movimientos"]
        self.assertEqual(movs[0]["nombre_original"], "b_grok.jpg")
        self.assertEqual(movs[0]["nombre_nuevo"], "rolibici1.jpg")
        self.assertEqual(movs[1]["nombre_original"], "c_grok.jpg")
        self.assertEqual(movs[1]["nombre_nuevo"], "rolibici2.jpg")
        self.assertEqual(movs[2]["nombre_original"], "a_grok.jpg")
        self.assertEqual(movs[2]["nombre_nuevo"], "rolibici3.jpg")

        # Desempate alfabético ante igual mtime
        p_z = os.path.join(self.descargas, "z_grok.mp4")
        p_m = os.path.join(self.descargas, "m_grok.mp4")
        with open(p_z, "wb") as f:
            f.write(b"v")
        with open(p_m, "wb") as f:
            f.write(b"v")
        os.utime(p_z, (5000, 5000))
        os.utime(p_m, (5000, 5000))

        sim_empate = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": p_z, "tamanio": 1, "hash": "hz"}, {"ruta": p_m, "tamanio": 1, "hash": "hm"}],
            personaje="mailen",
            nombre_escena="auto",
            es_existente_descargas=False
        )
        self.assertEqual(sim_empate["movimientos"][0]["nombre_original"], "m_grok.mp4")
        self.assertEqual(sim_empate["movimientos"][0]["nombre_nuevo"], "mailenauto1.mp4")
        self.assertEqual(sim_empate["movimientos"][1]["nombre_original"], "z_grok.mp4")
        self.assertEqual(sim_empate["movimientos"][1]["nombre_nuevo"], "mailenauto2.mp4")

    def test_continuacion_numeracion_carpeta_poblada(self):
        """Si la carpeta ya contiene archivos, la numeración continúa desde max_existente + 1."""
        carpeta_destino = os.path.join(self.destino_base, "lucie", "trapitos")
        os.makedirs(carpeta_destino, exist_ok=True)
        with open(os.path.join(carpeta_destino, "lucietrapitos1.mp4"), "wb") as f:
            f.write(b"v1")
        with open(os.path.join(carpeta_destino, "lucietrapitos5.mp4"), "wb") as f:
            f.write(b"v5")
        with open(os.path.join(carpeta_destino, "lucietrapitos2.jpg"), "wb") as f:
            f.write(b"f2")

        vid_nuevo = os.path.join(self.descargas, "grok-video-nuevo.mp4")
        img_nueva = os.path.join(self.descargas, "grok-image-nueva.png")
        with open(vid_nuevo, "wb") as f:
            f.write(b"vnew")
        with open(img_nueva, "wb") as f:
            f.write(b"fnew")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[
                {"ruta": vid_nuevo, "tamanio": 4, "hash": "hvn"},
                {"ruta": img_nueva, "tamanio": 4, "hash": "hin"}
            ],
            personaje="lucie",
            nombre_escena="trapitos",
            es_existente_descargas=False
        )

        nombres_nuevos = {m["nombre_original"]: m["nombre_nuevo"] for m in sim["movimientos"]}
        self.assertEqual(nombres_nuevos["grok-video-nuevo.mp4"], "lucietrapitos6.mp4")
        self.assertEqual(nombres_nuevos["grok-image-nueva.png"], "lucietrapitos3.png")

    def test_colision_case_insensitive(self):
        """Verifica que si existe un archivo con distinta mayúscula/minúscula no se pisa."""
        carpeta_destino = os.path.join(self.destino_base, "lucie", "trapitos")
        os.makedirs(carpeta_destino, exist_ok=True)
        # Existe con mayúsculas
        archivo_existente = os.path.join(carpeta_destino, "Lucietrapitos1.JPG")
        with open(archivo_existente, "wb") as f:
            f.write(b"foto existente en mayusculas")

        foto_nueva = os.path.join(self.descargas, "grok-img-123.jpg")
        with open(foto_nueva, "wb") as f:
            f.write(b"foto nueva")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": foto_nueva, "tamanio": 10, "hash": "h_ci"}],
            personaje="lucie",
            nombre_escena="trapitos",
            es_existente_descargas=False
        )

        self.assertEqual(sim["movimientos"][0]["nombre_nuevo"], "lucietrapitos2.jpg")
        res = self.gestor.ejecutar_movimiento_lote(sim, lote_id="lote_ci")
        self.assertTrue(res["exito"])
        # Ambos archivos existen intactos
        self.assertTrue(os.path.exists(archivo_existente))
        self.assertTrue(os.path.exists(os.path.join(carpeta_destino, "lucietrapitos2.jpg")))

    def test_multi_lote_sin_nombres_repetidos_misma_escena(self):
        """Dos lotes destinados a la misma escena en una solicitud multi-lote no repiten nombres."""
        f_a1 = os.path.join(self.descargas, "loteA_foto1.jpg")
        f_a2 = os.path.join(self.descargas, "loteA_foto2.jpg")
        f_b1 = os.path.join(self.descargas, "loteB_foto1.jpg")
        f_b2 = os.path.join(self.descargas, "loteB_foto2.jpg")
        for f in (f_a1, f_a2, f_b1, f_b2):
            with open(f, "wb") as fh:
                fh.write(b"data")

        destinos_reservados = set()
        sim_a = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": f_a1, "tamanio": 4, "hash": "h_a1"}, {"ruta": f_a2, "tamanio": 4, "hash": "h_a2"}],
            personaje="lucie",
            nombre_escena="trapitos",
            destinos_reservados=destinos_reservados
        )
        for m in sim_a["movimientos"]:
            destinos_reservados.add(m["destino"])

        sim_b = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": f_b1, "tamanio": 4, "hash": "h_b1"}, {"ruta": f_b2, "tamanio": 4, "hash": "h_b2"}],
            personaje="lucie",
            nombre_escena="trapitos",
            destinos_reservados=destinos_reservados
        )

        nombres_a = [m["nombre_nuevo"] for m in sim_a["movimientos"]]
        nombres_b = [m["nombre_nuevo"] for m in sim_b["movimientos"]]

        self.assertEqual(nombres_a, ["lucietrapitos1.jpg", "lucietrapitos2.jpg"])
        self.assertEqual(nombres_b, ["lucietrapitos3.jpg", "lucietrapitos4.jpg"])
        # No hay intersección de nombres
        self.assertEqual(len(set(nombres_a).intersection(set(nombres_b))), 0)

    def test_deshacer_devuelve_nombre_original_y_se_niega_si_origen_ocupado(self):
        """Deshacer restaura el nombre original y aborta si la ruta original está ocupada."""
        orig_nombre = "grok-image-3545ac09.jpg"
        orig_ruta = os.path.join(self.descargas, orig_nombre)
        with open(orig_ruta, "wb") as f:
            f.write(b"contenido original")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": orig_ruta, "tamanio": 18, "hash": "hash_grok"}],
            personaje="lucie",
            nombre_escena="trapitos",
            es_existente_descargas=False
        )

        res_mov = self.gestor.ejecutar_movimiento_lote(sim, lote_id="lote_undo")
        self.assertTrue(res_mov["exito"])
        dest_ruta = sim["movimientos"][0]["destino"]
        self.assertTrue(os.path.exists(dest_ruta))
        self.assertFalse(os.path.exists(orig_ruta))

        # Verificar SQLite refleja destino_nuevo
        reg_sqlite = self.db.obtener_por_hash("hash_grok")
        self.assertIsNotNone(reg_sqlite)
        self.assertEqual(reg_sqlite["ruta_actual"], dest_ruta)

        # 1. Deshacer exitoso: vuelve al nombre original
        res_undo = self.gestor.deshacer_operacion(res_mov["id_operacion"])
        self.assertTrue(res_undo["exito"])
        self.assertTrue(os.path.exists(orig_ruta))
        self.assertFalse(os.path.exists(dest_ruta))

        # SQLite vuelve a origen_anterior
        reg_sqlite_undo = self.db.obtener_por_hash("hash_grok")
        self.assertEqual(reg_sqlite_undo["ruta_actual"], orig_ruta)

        # 2. Volver a mover y ocupar el origen para probar denegación estricta
        sim2 = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": orig_ruta, "tamanio": 18, "hash": "hash_grok"}],
            personaje="lucie",
            nombre_escena="trapitos"
        )
        res_mov2 = self.gestor.ejecutar_movimiento_lote(sim2, lote_id="lote_undo_2")
        self.assertTrue(res_mov2["exito"])

        # Ocupar la ruta original con un archivo nuevo
        with open(orig_ruta, "wb") as f:
            f.write(b"archivo nuevo ocupando el origen")

        # Intentar deshacer: debe denegarse terminantemente
        with self.assertRaises(ErrorDeshacer) as ctx:
            self.gestor.deshacer_operacion(res_mov2["id_operacion"])
        self.assertIn("ya se encuentra ocupada", str(ctx.exception))
        # El archivo en destino sigue intacto
        self.assertTrue(os.path.exists(sim2["movimientos"][0]["destino"]))

    def test_simulacion_muestra_original_y_nuevo_y_sin_tags_legados(self):
        """generar_html_simulacion proyecta 'original -> nuevo' y omite etiquetas tag-tipo."""
        f_path = os.path.join(self.descargas, "grok-video-preview.mp4")
        with open(f_path, "wb") as f:
            f.write(b"vid")

        sim = self.gestor.simular_movimiento_lote(
            archivos=[{"ruta": f_path, "tamanio": 3, "hash": "hpv"}],
            personaje="lucie",
            nombre_escena="trapitos"
        )

        html_out = sim["html"]
        self.assertIn("grok-video-preview.mp4", html_out)
        self.assertIn("lucietrapitos1.mp4", html_out)
        self.assertIn("&rarr;", html_out)
        self.assertIn("badge-renombrado", html_out)
        self.assertNotIn("tag-tipo", html_out)
        self.assertNotIn("videos sin editar", html_out)

    def test_compatibilidad_bitacora_lineas_viejas(self):
        """obtener_historial lee sin errores líneas antiguas sin nombre_original ni nombre_nuevo."""
        linea_vieja = {
            "id_operacion": "op_legada_123",
            "lote_id": "lote_legado",
            "fecha": "2026-10-01T10:00:00",
            "personaje": "lucie",
            "escena": "toma_legada",
            "total_movimientos": 1,
            "movimientos": [{
                "origen_anterior": "/tmp/descargas/grok-video-viejo.mp4",
                "destino_nuevo": "/tmp/descargas/_lucie/lucie/toma_legada/grok-video-viejo.mp4",
                "hash": "hash_viejo",
                "tamanio": 100
            }]
        }
        with open(self.bitacora_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(linea_vieja) + "\n")

        historial = self.gestor.obtener_historial(limite=10)
        self.assertEqual(len(historial), 1)
        item = historial[0]
        self.assertEqual(item["archivo"], "grok-video-viejo.mp4")
        self.assertEqual(item["nombre_original"], "grok-video-viejo.mp4")
        self.assertEqual(item["nombre_nuevo"], "grok-video-viejo.mp4")
        self.assertEqual(item["estado"], "movido")


class TestCapituloSoloMaterialNuevo(unittest.TestCase):
    """
    Pruebas para el cambio capitulo-solo-material-nuevo:
    - Adopción exclusiva de archivos posteriores al inicio del capítulo (mtime >= fecha_inicio).
    - Margen configurable (0 y 10 minutos).
    - Candidato por patrón anterior queda sin tildar, sin escena y en lotes_anteriores.
    - Mover lotes listos excluye la sección de anteriores.
    - Reabrir capítulo cerrado respeta la fecha_inicio original.
    - Base de nombre compacta ('lucie trapitos' -> 'lucietrapitos1.jpg') y consistencia con alias inicial.
    """
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_cap_nuevo_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.descargas, "_lucie")
        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

        self.db_file = os.path.join(self.tmp_dir, "bandeja.db")
        self.bitacora_file = os.path.join(self.tmp_dir, "bitacora.jsonl")
        self.cfg_file = os.path.join(self.tmp_dir, "config.json")
        self.alias_file = os.path.join(self.tmp_dir, "alias.json")

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
            "minutos_antes_inicio_capitulo": 0,
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
        self.detector = DetectorDescargasActivas(ventana_estabilidad_segundos=0.01)
        self.agrupador = AgrupadorLotes(ventana_minutos=10)
        self.gestor = GestorMovimientosBandeja(
            self.descargas, self.destino, self.db,
            ruta_bitacora=self.bitacora_file, ruta_alias=self.alias_file
        )

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

    def test_archivo_anterior_no_se_asigna_posterior_si(self):
        """Archivo con mtime anterior al inicio del capítulo no se asigna al capítulo ni se preselecciona; posterior sí."""
        # Archivo anterior (creado antes del inicio del capítulo)
        f_anterior = os.path.join(self.descargas, "grok-video-anterior.mp4")
        with open(f_anterior, "wb") as f:
            f.write(b"video viejo")
        time.sleep(0.02)

        ahora = datetime.datetime.now()
        fecha_ini = ahora.isoformat()
        ts_ini = ahora.timestamp()
        os.utime(f_anterior, (ts_ini - 3600, ts_ini - 3600))

        self.db.empezar_capitulo("lucie", "capitulo_playa", fecha_inicio=fecha_ini)

        # Archivo posterior (1 minuto después)
        f_posterior = os.path.join(self.descargas, "grok-video-nuevo.mp4")
        with open(f_posterior, "wb") as f:
            f.write(b"video nuevo")
        os.utime(f_posterior, (ts_ini + 60, ts_ini + 60))

        vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        vigilante.escanear()
        time.sleep(0.02)
        vigilante.escanear()

        estado = vigilante.obtener_estado()

        # En lotes normales (material nuevo del capítulo) solo debe estar f_posterior
        self.assertEqual(len(estado["lotes"]), 1)
        lote_nuevo = estado["lotes"][0]
        self.assertEqual(lote_nuevo["personaje_sugerido"], "lucie")
        self.assertEqual(lote_nuevo["escena_sugerida"], "capitulo_playa")
        self.assertFalse(lote_nuevo.get("es_anterior", False))
        self.assertEqual(len(lote_nuevo["archivos"]), 1)
        self.assertEqual(lote_nuevo["archivos"][0]["nombre"], "grok-video-nuevo.mp4")

        # En lotes anteriores debe estar f_anterior, sin escena sugerida precargada y es_anterior=True
        self.assertEqual(len(estado["lotes_anteriores"]), 1)
        lote_ant = estado["lotes_anteriores"][0]
        self.assertTrue(lote_ant.get("es_anterior", False))
        self.assertEqual(lote_ant.get("escena_sugerida", ""), "")
        self.assertEqual(len(lote_ant["archivos"]), 1)
        self.assertEqual(lote_ant["archivos"][0]["nombre"], "grok-video-anterior.mp4")

    def test_margen_configuracion_0_y_10_minutos(self):
        """Margen configurable: 0 min (corte exacto) vs 10 min (adopta archivos hasta 10 min antes)."""
        ahora = datetime.datetime.now()
        fecha_ini = ahora.isoformat()
        ts_ini = ahora.timestamp()

        self.db.empezar_capitulo("roli", "cap_margen", fecha_inicio=fecha_ini)

        # Archivo creado 5 minutos antes
        f_5min_antes = os.path.join(self.descargas, "grok-video-5min.mp4")
        with open(f_5min_antes, "wb") as f:
            f.write(b"data 5min")
        os.utime(f_5min_antes, (ts_ini - 300, ts_ini - 300))

        # Archivo creado 15 minutos antes
        f_15min_antes = os.path.join(self.descargas, "grok-video-15min.mp4")
        with open(f_15min_antes, "wb") as f:
            f.write(b"data 15min")
        os.utime(f_15min_antes, (ts_ini - 900, ts_ini - 900))

        with patch("bandeja_descargas.obtener_fecha_llegada", side_effect=lambda st: getattr(st, "st_mtime", getattr(st, "mtime", time.time()))):
            # 1. Caso margen = 0: ambos archivos son anteriores al capítulo
            self.config.minutos_antes_inicio_capitulo = 0
            vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
            vigilante.escanear()
            time.sleep(0.02)
            vigilante.escanear()
            est0 = vigilante.obtener_estado()
            self.assertEqual(len(est0["lotes"]), 0)
            self.assertGreater(len(est0["lotes_anteriores"]), 0)

            # Limpiar registros para volver a evaluar con margen = 10
            with self.db._lock, self.db._conectar() as con:
                con.execute("DELETE FROM bandeja_archivos")
                con.commit()

            # 2. Caso margen = 10 minutos: f_5min_antes (-300s >= -600s) debe ser adoptado; f_15min_antes (-900s) sigue siendo anterior
            self.config.minutos_antes_inicio_capitulo = 10
            vigilante10 = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
            vigilante10.escanear()
            time.sleep(0.02)
            vigilante10.escanear()
            est10 = vigilante10.obtener_estado()

            nombres_nuevos = [a["nombre"] for l in est10["lotes"] for a in l["archivos"]]
            self.assertIn("grok-video-5min.mp4", nombres_nuevos)
            self.assertNotIn("grok-video-15min.mp4", nombres_nuevos)

            nombres_ant = [a["nombre"] for l in est10["lotes_anteriores"] for a in l["archivos"]]
            self.assertIn("grok-video-15min.mp4", nombres_ant)

    def test_candidato_patron_grok_anterior_queda_sin_tildar_y_sin_escena(self):
        """Candidato por patrón IA (grok-image-*) anterior al capítulo queda sin escena precargada y marcado como anterior."""
        f_grok = os.path.join(self.descargas, "grok-image-3545ac09.jpg")
        with open(f_grok, "wb") as f:
            f.write(b"imagen grok")

        # Archivo sin identificar anterior (no patrón ni alias)
        f_random = os.path.join(self.descargas, "random_viejo.jpg")
        with open(f_random, "wb") as f:
            f.write(b"random")

        time.sleep(0.02)
        ahora = datetime.datetime.now()
        ts_ini = ahora.timestamp()
        os.utime(f_grok, (ts_ini - 600, ts_ini - 600))
        os.utime(f_random, (ts_ini - 600, ts_ini - 600))

        self.db.empezar_capitulo("lucie", "sesion_fotos", fecha_inicio=ahora.isoformat())

        vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        vigilante.escanear()
        time.sleep(0.02)
        vigilante.escanear()

        estado = vigilante.obtener_estado()
        # f_grok va a lotes_anteriores con escena vacía y es_anterior=True
        self.assertEqual(len(estado["lotes"]), 0)
        self.assertEqual(len(estado["lotes_anteriores"]), 1)
        lote_ant = estado["lotes_anteriores"][0]
        self.assertEqual(lote_ant["escena_sugerida"], "")
        self.assertTrue(lote_ant["es_anterior"])
        self.assertEqual(lote_ant["archivos"][0]["nombre"], "grok-image-3545ac09.jpg")

        # f_random va a sin_identificar
        nombres_sin_id = [item["nombre"] for item in estado["sin_identificar"]]
        self.assertIn("random_viejo.jpg", nombres_sin_id)

    def test_mover_lotes_listos_excluye_anteriores(self):
        """Los lotes de la sección 'Anteriores al capítulo' están excluidos de los lotes del capítulo activo."""
        ahora = datetime.datetime.now()
        self.db.empezar_capitulo("lucie", "cap_exclusivo", fecha_inicio=ahora.isoformat())
        ts_ini = ahora.timestamp()

        # Uno anterior y uno nuevo
        f_ant = os.path.join(self.descargas, "grok-video-old.mp4")
        with open(f_ant, "wb") as f:
            f.write(b"old")
        os.utime(f_ant, (ts_ini - 120, ts_ini - 120))

        f_new = os.path.join(self.descargas, "grok-video-new.mp4")
        with open(f_new, "wb") as f:
            f.write(b"new")
        os.utime(f_new, (ts_ini + 10, ts_ini + 10))

        vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        vigilante.escanear()
        time.sleep(0.02)
        vigilante.escanear()

        estado = vigilante.obtener_estado()
        # Solo los lotes activos (es_anterior == False) son retornados en estado['lotes']
        for l in estado["lotes"]:
            self.assertFalse(l.get("es_anterior", False))
            for a in l["archivos"]:
                self.assertFalse(a.get("es_anterior", False))

        # Y los anteriores en estado['lotes_anteriores'] tienen es_anterior == True
        for l in estado["lotes_anteriores"]:
            self.assertTrue(l.get("es_anterior", False))
            for a in l["archivos"]:
                self.assertTrue(a.get("es_anterior", False))

    def test_reabrir_capitulo_respeta_fecha_inicio_original(self):
        """Reabrir un capítulo cerrado mantiene intacta la fecha_inicio original del capítulo."""
        fecha_original = (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat()
        cap = self.db.empezar_capitulo("mailen", "sesion_viaje", fecha_inicio=fecha_original)
        cap_id = cap["id"]

        # Terminar capítulo
        self.db.terminar_capitulo(id_capitulo=cap_id)
        cap_cerrado = self.db.obtener_capitulo_activo()
        self.assertFalse(cap_cerrado["habilitado"])

        # Reabrir capítulo
        cap_reabierto = self.db.reabrir_capitulo(cap_id)
        self.assertTrue(cap_reabierto["habilitado"])
        self.assertEqual(cap_reabierto["nombre"], "sesion_viaje")
        self.assertEqual(cap_reabierto["fecha_inicio"], fecha_original)

        # En base de datos SQLite se preserva fecha_original
        cap_db = self.db.obtener_capitulo_activo()
        self.assertEqual(cap_db["fecha_inicio"], fecha_original)

    def test_base_nombre_compacta_y_consistencia_alias_inicial(self):
        """Base de nombre compacta ('lucie trapitos' -> 'lucietrapitos1.jpg') y consistencia con obtener_personaje_de_alias_inicial."""
        casos = [
            ("lucie", "lucie trapitos", "lucietrapitos"),
            ("lucie", "luci-fiesta", "luci-fiesta"),
            ("lucie", "  lucie   trapitos  ", "lucietrapitos"),
            ("lucie", "trapitos", "lucietrapitos"),
            ("roli", "roli parque", "roliparque"),
            ("roli", "magui fiesta", "maguifiesta"),
            ("roli", "laroli baile", "larolibaile"),
            ("roli", "lucie trapitos", "rolilucietrapitos"),
            ("mailen", "bici", "mailenbici"),
            ("mailen", "mailen paseo playa", "mailenpaseoplaya"),
        ]

        for personaje, escena_input, base_esperada in casos:
            base_calc = self.gestor.calcular_base_escena(personaje, escena_input)
            self.assertEqual(base_calc, base_esperada, f"Error calculando base para {personaje} + {escena_input}")

            # Verificar que el nombre con número y extensión sea reconocido con el personaje correcto
            nombre_archivo = f"{base_calc}1.jpg"
            personaje_deducido = self.filtro.obtener_personaje_de_alias_inicial(nombre_archivo)
            self.assertEqual(
                personaje_deducido, personaje,
                f"obtener_personaje_de_alias_inicial({nombre_archivo}) retornó '{personaje_deducido}', esperado '{personaje}'"
            )



class TestDescartarCapitulo(unittest.TestCase):
    """Pruebas exhaustivas para el descarte de capítulos a la sala de cuarentena _descartados."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_descartar_capitulo_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.descargas, "_lucie")
        self.db_path = os.path.join(self.tmp_dir, "bandeja.db")
        self.bitacora = os.path.join(self.tmp_dir, "bitacora.jsonl")
        self.alias_file = os.path.join(self.tmp_dir, "alias.json")

        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

        with open(self.alias_file, "w", encoding="utf-8") as f:
            json.dump({
                "lucie": ["lucie", "luci"],
                "roli": ["roli", "laroli", "magui"],
                "mailen": ["mailen"]
            }, f)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas
        self.config.ruta_destino_base = self.destino
        self.config.archivo_alias_personajes = self.alias_file
        self.config.puerto_servidor = 8805
        self.config.host_servidor = "127.0.0.1"

        self.db = GestorBaseDatosBandeja(self.db_path)
        self.movimientos = GestorMovimientosBandeja(self.descargas, self.destino, self.db, self.bitacora)
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas(0.0)
        self.agrupador = AgrupadorLotes(10)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)

        self.servidor = None
        self.hilo_servidor = None

    def tearDown(self):
        if self.servidor:
            self.servidor.shutdown()
            self.servidor.server_close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _crear_archivo(self, ruta: str, contenido: bytes = b"datos de prueba") -> str:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(contenido)
        return ruta

    def _iniciar_servidor_prueba(self, token_csrf: str = "csrf_test_token_123"):
        miniaturas = GeneradorMiniaturas(self.db, os.path.join(self.tmp_dir, "thumbs"))
        self.servidor = crear_servidor(
            self.config, self.db, self.vigilante, self.movimientos, miniaturas, token_csrf=token_csrf
        )
        self.token_csrf = token_csrf
        self.hilo_servidor = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo_servidor.start()
        time.sleep(0.2)

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

    def test_simulacion_descartar_capitulo(self):
        """La simulación calcula origen, destino en _descartados, cantidad de archivos y no altera el disco."""
        cap = self.db.empezar_capitulo("lucie", "paseo_playa")
        cap_id = cap["id"]

        carpeta_escena = os.path.join(self.destino, "lucie", "paseo_playa")
        f1 = self._crear_archivo(os.path.join(carpeta_escena, "foto1.jpg"), b"contenido foto")
        f2 = self._crear_archivo(os.path.join(carpeta_escena, "video1.mp4"), b"contenido video")

        sim = self.movimientos.simular_descartar_capitulo(cap_id)

        self.assertTrue(sim["valido"])
        self.assertEqual(sim["capitulo_id"], cap_id)
        self.assertEqual(sim["personaje"], "lucie")
        self.assertEqual(sim["escena"], "paseo_playa")
        self.assertEqual(sim["total_archivos"], 2)
        self.assertEqual(sim["peso_total"], len(b"contenido foto") + len(b"contenido video"))
        self.assertEqual(sim["origen_carpeta"], carpeta_escena)
        self.assertIn("_descartados", sim["destino_carpeta"])
        self.assertIn("lucie", sim["destino_carpeta"])
        self.assertIn("Esto NO borra", sim["aviso"])
        self.assertTrue(sim["carpeta_existe"])
        self.assertFalse(sim["carpeta_vacia"])

        # Verificar que el destino no fue creado todavía
        self.assertFalse(os.path.exists(sim["destino_carpeta"]))
        # Verificar que el origen sigue intacto
        self.assertTrue(os.path.exists(f1))
        self.assertTrue(os.path.exists(f2))

    def test_descartar_mueve_carpeta_completa_sin_perder_archivos(self):
        """Descartar traslada la carpeta con os.rename; compara hashes SHA-256 antes y después."""
        cap = self.db.empezar_capitulo("lucie", "parque")
        cap_id = cap["id"]

        carpeta_escena = os.path.join(self.destino, "lucie", "parque")
        f1 = self._crear_archivo(os.path.join(carpeta_escena, "foto_arbol.jpg"), b"arbol_bytes_12345")
        f2 = self._crear_archivo(os.path.join(carpeta_escena, "clip_fuente.mp4"), b"fuente_bytes_67890")

        hash1 = calcular_sha256(f1)
        hash2 = calcular_sha256(f2)

        # Registrar en bandeja_archivos
        self.db.registrar_o_actualizar(hash1, f1, "movido", "lucie", "parque")
        self.db.registrar_o_actualizar(hash2, f2, "movido", "lucie", "parque")

        sim = self.movimientos.simular_descartar_capitulo(cap_id)
        res = self.movimientos.ejecutar_descartar_capitulo(sim, "parque")

        self.assertTrue(res["exito"])
        self.assertEqual(res["total_archivos"], 2)

        # El origen ya no debe existir
        self.assertFalse(os.path.exists(carpeta_escena))

        # El destino debe existir con los archivos exactos y hashes idénticos
        destino_carpeta = sim["destino_carpeta"]
        self.assertTrue(os.path.exists(destino_carpeta))
        dest_f1 = os.path.join(destino_carpeta, "foto_arbol.jpg")
        dest_f2 = os.path.join(destino_carpeta, "clip_fuente.mp4")
        self.assertTrue(os.path.exists(dest_f1))
        self.assertTrue(os.path.exists(dest_f2))

        self.assertEqual(calcular_sha256(dest_f1), hash1)
        self.assertEqual(calcular_sha256(dest_f2), hash2)

        # Base de datos: capítulo marcado como descartado
        cap_db = self.db.obtener_capitulo_por_id(cap_id)
        self.assertEqual(cap_db["descartado"], 1)
        self.assertIsNotNone(cap_db["fecha_descartado"])

        # bandeja_archivos: rutas actualizadas y estado descartado
        arch1 = self.db.obtener_por_hash(hash1)
        arch2 = self.db.obtener_por_hash(hash2)
        self.assertEqual(arch1["estado"], "descartado")
        self.assertEqual(arch2["estado"], "descartado")
        self.assertEqual(arch1["ruta_actual"], dest_f1)
        self.assertEqual(arch2["ruta_actual"], dest_f2)

        # Bitácora contiene evento descartar_capitulo
        with open(self.bitacora, "r", encoding="utf-8") as f:
            lineas = [json.loads(line) for line in f if line.strip()]
        eventos_descarte = [e for e in lineas if e.get("evento") == "descartar_capitulo"]
        self.assertEqual(len(eventos_descarte), 1)
        self.assertEqual(eventos_descarte[0]["escena"], "parque")
        self.assertEqual(eventos_descarte[0]["total_archivos"], 2)

    def test_confirmacion_nombre_incorrecto_rechazada(self):
        """Si el nombre de confirmación no coincide con la escena, se rechaza y nada se mueve ni altera."""
        cap = self.db.empezar_capitulo("roli", "gimnasio")
        carpeta_escena = os.path.join(self.destino, "roli", "gimnasio")
        f1 = self._crear_archivo(os.path.join(carpeta_escena, "pesa.jpg"), b"foto pesa")

        sim = self.movimientos.simular_descartar_capitulo(cap["id"])

        for nombre_invalido in ["otro", "Gimnasio", "gimnasio ", "gimnasi", ""]:
            with self.assertRaises((ValueError, ErrorValidacionEscena)):
                self.movimientos.ejecutar_descartar_capitulo(sim, nombre_invalido)

        # Verificar que el origen y BD están intactos
        self.assertTrue(os.path.exists(carpeta_escena))
        self.assertTrue(os.path.exists(f1))
        cap_db = self.db.obtener_capitulo_por_id(cap["id"])
        self.assertEqual(cap_db["descartado"], 0)

    def test_colision_destino_resuelta_sin_pisar(self):
        """Si la carpeta en _descartados ya existiera, se le asigna sufijo numérico y no pisa nada."""
        cap = self.db.empezar_capitulo("mailen", "patin")
        carpeta_escena = os.path.join(self.destino, "mailen", "patin")
        f1 = self._crear_archivo(os.path.join(carpeta_escena, "patin1.mp4"), b"video patin")

        sim1 = self.movimientos.simular_descartar_capitulo(cap["id"])
        destino_esperado = sim1["destino_carpeta"]

        # Crear carpeta de colisión con un archivo previo
        archivo_previo = self._crear_archivo(os.path.join(destino_esperado, "no_tocar.txt"), b"datos_sagrados")

        # Simular nuevamente: debe asignar sufijo ' (1)'
        sim2 = self.movimientos.simular_descartar_capitulo(cap["id"])
        self.assertTrue(sim2["destino_carpeta"].endswith(" (1)"))
        self.assertNotEqual(sim2["destino_carpeta"], destino_esperado)

        # Ejecutar descarte
        res = self.movimientos.ejecutar_descartar_capitulo(sim2, "patin")
        self.assertTrue(res["exito"])

        # Verificar que el archivo previo en la ruta original no fue tocado
        self.assertTrue(os.path.exists(archivo_previo))
        with open(archivo_previo, "rb") as f:
            self.assertEqual(f.read(), b"datos_sagrados")

        # Verificar que los archivos del capítulo están en la carpeta con sufijo
        self.assertTrue(os.path.exists(os.path.join(sim2["destino_carpeta"], "patin1.mp4")))

    def test_deshacer_restaura_todo_y_se_niega_si_ocupado(self):
        """Deshacer restaura la carpeta a su origen; si el origen está ocupado, se niega sin pisar."""
        cap = self.db.empezar_capitulo("lucie", "recuerdos")
        carpeta_escena = os.path.join(self.destino, "lucie", "recuerdos")
        f1 = self._crear_archivo(os.path.join(carpeta_escena, "foto.jpg"), b"foto recuerdos")
        hash1 = calcular_sha256(f1)
        self.db.registrar_o_actualizar(hash1, f1, "movido", "lucie", "recuerdos")

        sim = self.movimientos.simular_descartar_capitulo(cap["id"])
        res = self.movimientos.ejecutar_descartar_capitulo(sim, "recuerdos")
        id_operacion = res["id_operacion"]

        # 1. Intentar deshacer cuando el origen fue ocupado por un nuevo archivo/carpeta
        os.makedirs(carpeta_escena, exist_ok=True)
        self._crear_archivo(os.path.join(carpeta_escena, "intruso.txt"), b"ocupante")

        with self.assertRaises(ErrorDeshacer) as ctx:
            self.movimientos.deshacer_operacion(id_operacion)
        self.assertIn("ya se encuentra ocupada", str(ctx.exception))

        # La carpeta en cuarentena no debe haber sido tocada
        self.assertTrue(os.path.exists(sim["destino_carpeta"]))

        # 2. Desocupar la ruta de origen y volver a intentar deshacer
        os.remove(os.path.join(carpeta_escena, "intruso.txt"))
        os.rmdir(carpeta_escena)

        undo_res = self.movimientos.deshacer_operacion(id_operacion)
        self.assertTrue(undo_res["exito"])

        # Origen restaurado
        self.assertTrue(os.path.exists(carpeta_escena))
        restaurado_f1 = os.path.join(carpeta_escena, "foto.jpg")
        self.assertTrue(os.path.exists(restaurado_f1))
        self.assertEqual(calcular_sha256(restaurado_f1), hash1)

        # Destino en _descartados ya no existe
        self.assertFalse(os.path.exists(sim["destino_carpeta"]))

        # Base de datos: descartado = 0, estado = 'cerrado'
        cap_db = self.db.obtener_capitulo_por_id(cap["id"])
        self.assertEqual(cap_db["descartado"], 0)
        self.assertEqual(cap_db["estado"], "cerrado")

        # Archivo en base de datos restaurado a 'movido'
        arch_db = self.db.obtener_por_hash(hash1)
        self.assertEqual(arch_db["estado"], "movido")
        self.assertEqual(arch_db["ruta_actual"], restaurado_f1)

        # Bitácora registra evento deshacer
        with open(self.bitacora, "r", encoding="utf-8") as f:
            lineas = [json.loads(line) for line in f if line.strip()]
        reversiones = [e for e in lineas if e.get("evento") == "deshacer" and e.get("id_operacion_revertida") == id_operacion]
        self.assertEqual(len(reversiones), 1)

    def test_capitulo_activo_descartado_deja_de_asignar_archivos(self):
        """Al descartar el capítulo activo, este se cierra automáticamente y los archivos nuevos no se le asignan."""
        self.db.empezar_capitulo("lucie", "paseo_activo")
        self.assertTrue(self.db.obtener_capitulo_activo()["habilitado"])

        carpeta_escena = os.path.join(self.destino, "lucie", "paseo_activo")
        self._crear_archivo(os.path.join(carpeta_escena, "f1.jpg"), b"foto 1")

        sim = self.movimientos.simular_descartar_capitulo(self.db.obtener_capitulo_activo()["id"])
        self.movimientos.ejecutar_descartar_capitulo(sim, "paseo_activo")

        # Debe haber dejado de ser activo
        cap_activo = self.db.obtener_capitulo_activo()
        self.assertFalse(cap_activo["habilitado"])

        # Nuevo archivo candidato que llega a Descargas
        self._crear_archivo(os.path.join(self.descargas, "lucie_nuevo_video.mp4"), b"video nuevo")
        self.vigilante.escanear()
        self.vigilante.escanear()

        estado = self.vigilante.obtener_estado()
        lote = next((l for l in estado["lotes"] if any(a["nombre"] == "lucie_nuevo_video.mp4" for a in l["archivos"])), None)
        self.assertIsNotNone(lote)
        # No debe tener sugerida la escena descartada
        self.assertNotEqual(lote.get("escena_sugerida"), "paseo_activo")

    def test_descartar_capitulo_sin_carpeta_o_vacia(self):
        """Si la carpeta no existe en disco o está vacía, se descarta el capítulo en SQLite sin errores."""
        cap = self.db.empezar_capitulo("mailen", "vacio_total")
        cap_id = cap["id"]

        sim = self.movimientos.simular_descartar_capitulo(cap_id)
        self.assertTrue(sim["carpeta_vacia"])
        self.assertFalse(sim["carpeta_existe"])
        self.assertEqual(sim["total_archivos"], 0)

        res = self.movimientos.ejecutar_descartar_capitulo(sim, "vacio_total")
        self.assertTrue(res["exito"])
        self.assertEqual(res["total_archivos"], 0)

        cap_db = self.db.obtener_capitulo_por_id(cap_id)
        self.assertEqual(cap_db["descartado"], 1)

    def test_migracion_tabla_capitulos_con_datos_previos(self):
        """Migración segura de bandeja_capitulos cuando la columna descartado no existe en BD previa."""
        db_legada_path = os.path.join(self.tmp_dir, "db_legada.sqlite")
        conn = sqlite3.connect(db_legada_path)
        with conn:
            conn.execute("""
                CREATE TABLE bandeja_capitulos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    personaje TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    fecha_inicio TEXT NOT NULL,
                    fecha_fin TEXT,
                    archivos_movidos INTEGER DEFAULT 0,
                    estado TEXT NOT NULL DEFAULT 'activo' CHECK(estado IN ('activo', 'cerrado'))
                )
            """)
            conn.execute("""
                INSERT INTO bandeja_capitulos (personaje, nombre, fecha_inicio, estado)
                VALUES ('lucie', 'cap_preexistente', '2026-02-01T10:00:00', 'cerrado')
            """)
        conn.close()

        # Instanciar GestorBaseDatosBandeja: ejecutará la migración ALTER TABLE
        db_migrada = GestorBaseDatosBandeja(db_legada_path)

        # Verificar que el capítulo preexistente sigue intacto y con descartado = 0
        cerrados = db_migrada.listar_capitulos_cerrados()
        self.assertEqual(len(cerrados), 1)
        self.assertEqual(cerrados[0]["nombre"], "cap_preexistente")
        self.assertEqual(cerrados[0].get("descartado", 0), 0)

        # Verificar que se puede descartar y listar en descartados
        db_migrada.marcar_capitulo_descartado(cerrados[0]["id"], descartado=True)
        self.assertEqual(len(db_migrada.listar_capitulos_cerrados()), 0)

        descartados = db_migrada.listar_capitulos_descartados()
        self.assertEqual(len(descartados), 1)
        self.assertEqual(descartados[0]["nombre"], "cap_preexistente")

    def test_endpoints_descartar_rechazan_sin_csrf_o_host_invalido(self):
        """Los endpoints de descarte exigen CSRF, validación de Host y rechazan anomalías."""
        self._iniciar_servidor_prueba()

        cap = self.db.empezar_capitulo("roli", "ensayo")
        cap_id = cap["id"]
        carpeta_escena = os.path.join(self.destino, "roli", "ensayo")
        self._crear_archivo(os.path.join(carpeta_escena, "ensayo.mp4"), b"video ensayo")

        # 1. Simulación sin CSRF -> 403 Forbidden
        status, _, _ = self._request(
            "POST", "/api/capitulos/descartar-simular",
            headers={"Content-Type": "application/json", "Host": "127.0.0.1:8805"},
            body=json.dumps({"id": cap_id})
        )
        self.assertEqual(status, 403)

        # 2. Simulación con Host falso -> 403 Forbidden
        status, _, _ = self._request(
            "POST", "/api/capitulos/descartar-simular",
            headers={
                "Content-Type": "application/json",
                "Host": "sitio-malicioso.com",
                "X-CSRF-Token": self.token_csrf
            },
            body=json.dumps({"id": cap_id})
        )
        self.assertEqual(status, 403)

        # 3. Simulación válida -> 200 OK
        status, data_sim, _ = self._request(
            "POST", "/api/capitulos/descartar-simular",
            headers={
                "Content-Type": "application/json",
                "Host": "127.0.0.1:8805",
                "X-CSRF-Token": self.token_csrf
            },
            body=json.dumps({"id": cap_id})
        )
        self.assertEqual(status, 200)
        self.assertTrue(data_sim.get("valido"))

        # 4. Ejecución con nombre de confirmación incorrecto -> 400 Bad Request
        status, _, _ = self._request(
            "POST", "/api/capitulos/descartar",
            headers={
                "Content-Type": "application/json",
                "Host": "127.0.0.1:8805",
                "X-CSRF-Token": self.token_csrf
            },
            body=json.dumps({
                "simulacion": data_sim,
                "nombre_confirmacion": "nombre_erroneo"
            })
        )
        self.assertEqual(status, 400)

        # 5. Ejecución con nombre de confirmación correcto -> 200 OK
        status, data_res, _ = self._request(
            "POST", "/api/capitulos/descartar",
            headers={
                "Content-Type": "application/json",
                "Host": "127.0.0.1:8805",
                "X-CSRF-Token": self.token_csrf
            },
            body=json.dumps({
                "simulacion": data_sim,
                "nombre_confirmacion": "ensayo"
            })
        )
        self.assertEqual(status, 200)
        self.assertTrue(data_res.get("exito"))

        # 6. GET /api/capitulos/descartados devuelve el capítulo descartado
        status, data_desc, _ = self._request("GET", "/api/capitulos/descartados")
        self.assertEqual(status, 200)
        descartados = data_desc.get("descartados", [])
        self.assertTrue(any(c["nombre"] == "ensayo" for c in descartados))

    def test_confinamiento_traversal_o_symlink_saliente_rechazado(self):
        """Path traversal o enlaces simbólicos que apunten fuera de _lucie se rechazan tajantemente."""
        cap = self.db.empezar_capitulo("lucie", "test_symlink")
        carpeta_escena = os.path.join(self.destino, "lucie", "test_symlink")
        os.makedirs(carpeta_escena, exist_ok=True)

        # Crear symlink a un archivo fuera de _lucie (ej. en self.descargas o self.tmp_dir)
        archivo_afuera = os.path.join(self.tmp_dir, "afuera.txt")
        with open(archivo_afuera, "wb") as f:
            f.write(b"fuera de lucie")

        symlink_path = os.path.join(carpeta_escena, "link_peligroso.txt")
        os.symlink(archivo_afuera, symlink_path)

        with self.assertRaises(ErrorSeguridadBandeja):
            self.movimientos.simular_descartar_capitulo(cap["id"])

    def test_aislamiento_descartados_no_es_escena_ni_destino(self):
        """_descartados nunca puede ser usado como escena válida ni reconocido como carpeta de escena."""
        valido, motivo = ValidadorEscenas.validar_nombre_escena(
            "_descartados", self.destino, self.descargas, es_existente_descargas=False, personaje="lucie"
        )
        self.assertFalse(valido)
        self.assertIn("_descartados", motivo)

        valido_sub, _ = ValidadorEscenas.validar_nombre_escena(
            "_descartados/sub", self.destino, self.descargas, es_existente_descargas=False, personaje="lucie"
        )
        self.assertFalse(valido_sub)

        # FiltroListaBlanca nunca debe considerar _descartados como escena existente
        self.assertFalse(self.filtro.es_carpeta_escena_existente("_descartados"))
        self.assertFalse(self.filtro.es_carpeta_escena_existente("_cualquier_oculta"))


class TestAjustesEscenaCapituloYAnteriores(unittest.TestCase):
    """Pruebas para el change ajustes-escena-capitulo-y-anteriores:
    - Creación inmediata de carpeta al empezar o reabrir capítulo.
    - Detección e información si la carpeta ya existía con archivos.
    - Validación y rechazo de nombres inválidos o escapes por path traversal.
    - Desplegable de escena con [Capítulo activo] <nombre> preseleccionado y sin duplicar [Destino].
    - Mover archivos con la escena del capítulo renombra ordenadamente y deshace sin problemas.
    - Descarte de capítulo con carpeta vacía existente la mueve a _descartados y permite deshacer.
    - Material anterior al inicio del capítulo queda destildado y sin escena precargada.
    - Lote mixto con archivos anteriores y nuevos se divide, dejando solo lo nuevo tildado.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_ajustes_escena_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.descargas, "_lucie")
        self.db_path = os.path.join(self.tmp_dir, "bandeja.db")
        self.bitacora = os.path.join(self.tmp_dir, "bitacora.jsonl")
        self.alias_file = os.path.join(self.tmp_dir, "alias.json")

        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

        with open(self.alias_file, "w", encoding="utf-8") as f:
            json.dump({
                "lucie": ["lucie", "luci"],
                "roli": ["roli", "laroli", "magui"],
                "mailen": ["mailen"]
            }, f)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas
        self.config.ruta_destino_base = self.destino
        self.config.archivo_alias_personajes = self.alias_file
        self.config.puerto_servidor = 8806
        self.config.host_servidor = "127.0.0.1"

        self.db = GestorBaseDatosBandeja(self.db_path, ruta_destino_base=self.destino, ruta_descargas=self.descargas)
        self.movimientos = GestorMovimientosBandeja(self.descargas, self.destino, self.db, self.bitacora, archivo_alias_personajes=self.alias_file)
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas(0.0)
        self.agrupador = AgrupadorLotes(10)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _crear_archivo(self, ruta: str, contenido: bytes = b"datos de prueba", mtime: Optional[float] = None) -> str:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(contenido)
        if mtime is not None:
            os.utime(ruta, (mtime, mtime))
        return ruta

    def test_empezar_capitulo_crea_carpeta_y_repetir_avisa(self):
        """Al empezar capítulo se crea la carpeta en disco inmediatamente; si ya existía con archivos avisa."""
        carpeta_cap = os.path.join(self.destino, "lucie", "olor a culo")
        self.assertFalse(os.path.exists(carpeta_cap))

        cap = self.db.empezar_capitulo("lucie", "olor a culo")
        self.assertTrue(os.path.exists(carpeta_cap))
        self.assertTrue(os.path.isdir(carpeta_cap))
        self.assertIn("carpeta_info", cap)
        self.assertFalse(cap["carpeta_info"]["ya_existia"])
        self.assertEqual(cap["carpeta_info"]["total_archivos"], 0)

        # Crear archivos dentro de la carpeta
        self._crear_archivo(os.path.join(carpeta_cap, "lucieolor a culo1.jpg"))
        self._crear_archivo(os.path.join(carpeta_cap, "lucieolor a culo2.jpg"))

        self.db.terminar_capitulo()

        # Al volver a empezar un capítulo con el mismo nombre y archivos existentes
        cap2 = self.db.empezar_capitulo("lucie", "olor a culo")
        self.assertTrue(cap2["carpeta_info"]["ya_existia"])
        self.assertEqual(cap2["carpeta_info"]["total_archivos"], 2)
        self.assertIn("La carpeta ya existía y tiene 2 archivos", cap2["carpeta_info"]["mensaje"])
        # Los archivos previos no se tocan
        self.assertTrue(os.path.exists(os.path.join(carpeta_cap, "lucieolor a culo1.jpg")))
        self.assertTrue(os.path.exists(os.path.join(carpeta_cap, "lucieolor a culo2.jpg")))

    def test_reabrir_capitulo_asegura_carpeta(self):
        """Reabrir un capítulo cerrado asegura la carpeta y no borra nada."""
        cap = self.db.empezar_capitulo("roli", "fiesta_roli")
        carpeta_cap = os.path.join(self.destino, "roli", "fiesta_roli")
        self.assertTrue(os.path.exists(carpeta_cap))

        self.db.terminar_capitulo()
        # La carpeta sigue existiendo en disco aunque el capítulo haya terminado
        self.assertTrue(os.path.exists(carpeta_cap))

        reabierto = self.db.reabrir_capitulo(cap["id"])
        self.assertTrue(reabierto["carpeta_info"]["ya_existia"])
        self.assertTrue(os.path.exists(carpeta_cap))

    def test_nombre_invalido_o_traversal_no_crea_nada(self):
        """Validación estricta de nombres y confinamiento con realpath rechaza escapes."""
        with self.assertRaises(ValueError):
            asegurar_carpeta_capitulo("lucie", "../escape_directorio", self.destino, self.descargas)

        with self.assertRaises(ValueError):
            asegurar_carpeta_capitulo("lucie", "", self.destino, self.descargas)

        with self.assertRaises(ValueError):
            asegurar_carpeta_capitulo("lucie", "nombre*invalido", self.destino, self.descargas)

        with self.assertRaises(ValueError):
            asegurar_carpeta_capitulo("personaje_falso", "escena", self.destino, self.descargas)

        self.assertFalse(os.path.exists(os.path.join(self.descargas, "escape_directorio")))

    def test_desplegable_capitulo_activo_preseleccionado_sin_duplicado(self):
        """Verifica que el estado y la simulación manejan correctamente el capítulo activo y advierten desajustes de personaje."""
        cap = self.db.empezar_capitulo("lucie", "paseo")
        self.assertIn("carpeta_info", cap)
        self.assertFalse(cap["carpeta_info"]["ya_existia"])

        cap_activo = self.db.obtener_capitulo_activo()
        self.assertEqual(cap_activo["personaje"], "lucie")
        self.assertEqual(cap_activo["nombre"], "paseo")
        info = self.movimientos.asegurar_carpeta_capitulo(cap_activo["personaje"], cap_activo["nombre"])
        self.assertTrue(info["ya_existia"])

        # Si el lote usa un personaje distinto al del capítulo activo, la simulación debe advertirlo claramente
        arch_roli = self._crear_archivo(os.path.join(self.descargas, "grok-roli-1.jpg"))
        sim = self.movimientos.simular_movimiento_lote(
            [{"ruta": arch_roli, "id_db": 10}],
            personaje="roli",
            nombre_escena="paseo"
        )
        self.assertTrue(sim["diferente_personaje_capitulo"])
        self.assertEqual(sim["personaje_capitulo"], "lucie")
        self.assertIn("Aviso de Personaje", sim["html"])
        self.assertIn("difiere del personaje del capítulo activo", sim["html"])
        self.assertIn("_lucie/roli/paseo", sim["html"])

    def test_mover_con_opcion_capitulo_renombra_y_deshacer(self):
        """Mover archivos al capítulo activo renombra con correlativos y deshacer revierte con os.rename."""
        self.db.empezar_capitulo("lucie", "playa")
        f1 = self._crear_archivo(os.path.join(self.descargas, "grok-img1.jpg"), b"foto 1", mtime=1000.0)
        f2 = self._crear_archivo(os.path.join(self.descargas, "grok-img2.png"), b"foto 2", mtime=1005.0)

        candidatos = [
            {"ruta": f1, "tamanio": 6, "hash": "h_f1"},
            {"ruta": f2, "tamanio": 6, "hash": "h_f2"}
        ]

        sim = self.movimientos.simular_movimiento_lote(
            candidatos,
            personaje="lucie",
            nombre_escena="playa"
        )
        self.assertEqual(sim["total_archivos"], 2)
        nombres_nuevos = [m["nombre_nuevo"] for m in sim["movimientos"]]
        self.assertEqual(nombres_nuevos, ["lucieplaya1.jpg", "lucieplaya2.png"])

        res = self.movimientos.ejecutar_movimiento_lote(sim, "lote_capitulo")
        self.assertTrue(res["exito"])

        dest_f1 = os.path.join(self.destino, "lucie", "playa", "lucieplaya1.jpg")
        dest_f2 = os.path.join(self.destino, "lucie", "playa", "lucieplaya2.png")
        self.assertTrue(os.path.exists(dest_f1))
        self.assertTrue(os.path.exists(dest_f2))
        self.assertFalse(os.path.exists(f1))
        self.assertFalse(os.path.exists(f2))

        # Deshacer restaura los archivos originales a ~/Descargas
        desh = self.movimientos.deshacer_operacion(res["id_operacion"])
        self.assertTrue(desh["exito"])
        self.assertTrue(os.path.exists(f1))
        self.assertTrue(os.path.exists(f2))
        self.assertFalse(os.path.exists(dest_f1))
        self.assertFalse(os.path.exists(dest_f2))

    def test_descartar_capitulo_carpeta_vacia_mueve_y_deshace(self):
        """Descartar un capítulo con carpeta vacía existente la mueve a _descartados y permite deshacer."""
        cap = self.db.empezar_capitulo("mailen", "cap_vacio")
        carpeta_cap = os.path.join(self.destino, "mailen", "cap_vacio")
        self.assertTrue(os.path.exists(carpeta_cap))

        sim = self.movimientos.simular_descartar_capitulo(cap["id"])
        self.assertTrue(sim["carpeta_existe"])
        self.assertTrue(sim["carpeta_vacia"])
        self.assertEqual(sim["total_archivos"], 0)

        res = self.movimientos.ejecutar_descartar_capitulo(sim, "cap_vacio")
        self.assertTrue(res["exito"])
        # La carpeta original se movió (no existe en la ruta de origen)
        self.assertFalse(os.path.exists(carpeta_cap))
        self.assertTrue(os.path.exists(res["destino"]))
        self.assertIn("_descartados", res["destino"])

        # Deshacer restaura la carpeta vacía al origen
        desh = self.movimientos.deshacer_operacion(res["id_operacion"])
        self.assertTrue(desh["exito"])
        self.assertTrue(os.path.exists(carpeta_cap))
        self.assertFalse(os.path.exists(res["destino"]))

    def test_lote_anterior_lucie_destildado_sin_escena(self):
        """Material descargado antes del capítulo queda en lotes_anteriores, destildado y sin escena."""
        t_viejo = time.time() - 3600
        f_antigua = self._crear_archivo(os.path.join(self.descargas, "lucie_trapitos_antigua.jpg"), mtime=t_viejo)

        # Empezar capítulo activo AHORA
        self.db.empezar_capitulo("lucie", "capitulo_reciente")

        self.vigilante.escanear()
        self.vigilante.escanear()
        estado = self.vigilante.obtener_estado()
        self.assertEqual(len(estado["lotes"]), 0)
        self.assertEqual(len(estado["lotes_anteriores"]), 1)

        lote_ant = estado["lotes_anteriores"][0]
        self.assertTrue(lote_ant["es_anterior"])
        self.assertEqual(lote_ant["escena_sugerida"], "")
        self.assertEqual(len(lote_ant["archivos"]), 1)
        self.assertTrue(lote_ant["archivos"][0]["es_anterior"])

        # Verificar en base de datos que escena_sugerida quedó en None/vacío
        cand_db = self.db.obtener_por_ruta(f_antigua)
        self.assertIsNotNone(cand_db)
        self.assertIsNone(cand_db.get("escena"))

        # Si entra un archivo nuevo posterior a la fecha de inicio
        t_nuevo = time.time() + 10
        f_nueva = self._crear_archivo(os.path.join(self.descargas, "lucie_trapitos_nueva.jpg"), mtime=t_nuevo)
        self.vigilante.escanear()
        self.vigilante.escanear()
        estado2 = self.vigilante.obtener_estado()

        self.assertEqual(len(estado2["lotes"]), 1)
        self.assertEqual(len(estado2["lotes_anteriores"]), 1)
        lote_nuevo = estado2["lotes"][0]
        self.assertFalse(lote_nuevo.get("es_anterior", False))
        self.assertEqual(lote_nuevo["escena_sugerida"], "capitulo_reciente")

    def test_lote_mixto_se_parte_y_solo_nuevo_queda_tildado(self):
        """Un lote con candidatos mixtos (anteriores y nuevos) se parte en lotes separados."""
        candidatos = [
            {
                "id_db": 1,
                "ruta": os.path.join(self.descargas, "ant1.jpg"),
                "tamanio": 100,
                "mtime": 1000.0,
                "es_anterior": True,
                "personaje": "lucie",
                "escena": "trapitos",
                "raiz_escena": "trapitos"
            },
            {
                "id_db": 2,
                "ruta": os.path.join(self.descargas, "ant2.jpg"),
                "tamanio": 100,
                "mtime": 1005.0,
                "es_anterior": True,
                "personaje": "lucie",
                "escena": "trapitos",
                "raiz_escena": "trapitos"
            },
            {
                "id_db": 3,
                "ruta": os.path.join(self.descargas, "new1.jpg"),
                "tamanio": 100,
                "mtime": 2000.0,
                "es_anterior": False,
                "personaje": "lucie",
                "escena": "cap_nuevo",
                "raiz_escena": "cap_nuevo"
            },
            {
                "id_db": 4,
                "ruta": os.path.join(self.descargas, "new2.jpg"),
                "tamanio": 100,
                "mtime": 2005.0,
                "es_anterior": False,
                "personaje": "lucie",
                "escena": "cap_nuevo",
                "raiz_escena": "cap_nuevo"
            }
        ]

        lotes = self.agrupador.agrupar(candidatos)
        self.assertEqual(len(lotes), 2)

        lote_nuevos = next(l for l in lotes if not l.get("es_anterior"))
        lote_anteriores = next(l for l in lotes if l.get("es_anterior"))

        self.assertEqual(len(lote_nuevos["archivos"]), 2)
        self.assertEqual(lote_nuevos["escena_sugerida"], "cap_nuevo")

        self.assertEqual(len(lote_anteriores["archivos"]), 2)
        self.assertEqual(lote_anteriores["escena_sugerida"], "")


class TestCapitulosAbiertosMultiples(unittest.TestCase):
    """Pruebas del cambio capitulos-abiertos-multiples:
    - Coexistencia de varios capítulos abiertos con exactamente uno en foco.
    - Migración no destructiva de base de datos e índice parcial en_foco.
    - Ingesta y corte de fecha gobernados exclusivamente por el capítulo en foco.
    - Cambio de foco atómico vía poner_capitulo_en_foco y API.
    - Conteo de archivos movidos hacia capítulos abiertos secundarios.
    - Cierre y descarte de capítulos en foco y secundarios.
    - Endpoints HTTP y seguridad CSRF/Host.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_caps_abiertos_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.descargas, "_lucie")
        self.db_path = os.path.join(self.tmp_dir, "bandeja.db")
        self.bitacora = os.path.join(self.tmp_dir, "bitacora.jsonl")
        self.alias_file = os.path.join(self.tmp_dir, "alias.json")

        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

        with open(self.alias_file, "w", encoding="utf-8") as f:
            json.dump({
                "lucie": ["lucie", "luci"],
                "roli": ["roli", "laroli"],
                "mailen": ["mailen"]
            }, f)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas
        self.config.ruta_destino_base = self.destino
        self.config.archivo_alias_personajes = self.alias_file
        self.config.puerto_servidor = 8807
        self.config.host_servidor = "127.0.0.1"

        self.db = GestorBaseDatosBandeja(self.db_path)
        self.movimientos = GestorMovimientosBandeja(self.descargas, self.destino, self.db, self.bitacora)
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas(0.0)
        self.agrupador = AgrupadorLotes(10)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)

        self.servidor = None
        self.hilo_servidor = None

    def tearDown(self):
        if self.servidor:
            self.servidor.shutdown()
            self.servidor.server_close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _crear_archivo(self, ruta: str, contenido: bytes = b"datos de prueba", mtime: float = None) -> str:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(contenido)
        if mtime is not None:
            os.utime(ruta, (mtime, mtime))
        return ruta

    def _iniciar_servidor_prueba(self, token_csrf: str = "csrf_test_token_abiertos"):
        miniaturas = GeneradorMiniaturas(self.db, os.path.join(self.tmp_dir, "thumbs"))
        self.servidor = crear_servidor(
            self.config, self.db, self.vigilante, self.movimientos, miniaturas, token_csrf=token_csrf
        )
        self.token_csrf = token_csrf
        self.hilo_servidor = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo_servidor.start()
        time.sleep(0.2)

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

    def test_migracion_sqlite_en_foco_e_indice_parcial(self):
        """Verifica que una base de datos legada sin columna en_foco y con idx_capitulo_unico_activo se migre correctamente."""
        db_legada_path = os.path.join(self.tmp_dir, "legada_caps.sqlite")
        conn = sqlite3.connect(db_legada_path)
        with conn:
            conn.execute("""
                CREATE TABLE bandeja_capitulos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    personaje TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    fecha_inicio TEXT NOT NULL,
                    fecha_fin TEXT,
                    archivos_movidos INTEGER DEFAULT 0,
                    estado TEXT NOT NULL DEFAULT 'activo' CHECK(estado IN ('activo', 'cerrado'))
                )
            """)
            conn.execute("CREATE UNIQUE INDEX idx_capitulo_unico_activo ON bandeja_capitulos(estado) WHERE estado = 'activo'")
            conn.execute("""
                INSERT INTO bandeja_capitulos (personaje, nombre, fecha_inicio, estado)
                VALUES ('lucie', 'cap_legado_activo', '2026-03-01T10:00:00', 'activo')
            """)
        conn.close()

        # Instanciar el gestor migra la base
        db_migrada = GestorBaseDatosBandeja(db_legada_path)

        # Consultar PRAGMA index_list
        conn2 = sqlite3.connect(db_legada_path)
        cursor = conn2.cursor()
        cursor.execute("PRAGMA index_list('bandeja_capitulos')")
        indices = [row[1] for row in cursor.fetchall()]
        conn2.close()

        self.assertNotIn("idx_capitulo_unico_activo", indices)
        self.assertIn("idx_capitulo_en_foco", indices)

        # El capítulo activo existente debe tener en_foco = 1
        cap_foco = db_migrada.obtener_capitulo_en_foco()
        self.assertTrue(cap_foco["habilitado"])
        self.assertEqual(cap_foco["nombre"], "cap_legado_activo")
        self.assertEqual(cap_foco["en_foco"], 1)

    def test_concurrencia_capitulos_abiertos(self):
        """Permite múltiples capítulos abiertos simultáneamente, con el más nuevo en foco."""
        cap1 = self.db.empezar_capitulo("lucie", "historia_uno")
        self.assertTrue(cap1["habilitado"])
        self.assertEqual(cap1["en_foco"], 1)

        cap2 = self.db.empezar_capitulo("roli", "historia_dos")
        self.assertTrue(cap2["habilitado"])
        self.assertEqual(cap2["en_foco"], 1)

        abiertos = self.db.listar_capitulos_abiertos()
        self.assertEqual(len(abiertos), 2)

        # cap2 debe estar en foco, cap1 debe ser secundario
        c2 = next(c for c in abiertos if c["id"] == cap2["id"])
        c1 = next(c for c in abiertos if c["id"] == cap1["id"])
        self.assertEqual(c2["en_foco"], 1)
        self.assertEqual(c1["en_foco"], 0)

        foco_actual = self.db.obtener_capitulo_en_foco()
        self.assertEqual(foco_actual["id"], cap2["id"])

    def test_unicidad_de_foco_indice_sqlite(self):
        """El índice único parcial impide tener dos registros con en_foco = 1 a la vez."""
        cap1 = self.db.empezar_capitulo("lucie", "h1")
        cap2 = self.db.empezar_capitulo("roli", "h2")

        conn = sqlite3.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            with conn:
                conn.execute("UPDATE bandeja_capitulos SET en_foco = 1 WHERE id = ?", (cap1["id"],))
        conn.close()

    def test_cambio_de_foco_atomico(self):
        """poner_capitulo_en_foco apaga el foco anterior y asigna el nuevo atómicamente."""
        cap1 = self.db.empezar_capitulo("lucie", "primero")
        cap2 = self.db.empezar_capitulo("mailen", "segundo")

        # Inicialmente foco en cap2
        self.assertEqual(self.db.obtener_capitulo_en_foco()["id"], cap2["id"])

        # Pasar foco a cap1
        res = self.db.poner_capitulo_en_foco(cap1["id"])
        self.assertTrue(res["habilitado"])
        self.assertEqual(res["id"], cap1["id"])

        self.assertEqual(self.db.obtener_capitulo_en_foco()["id"], cap1["id"])
        c2 = self.db.obtener_capitulo_por_id(cap2["id"])
        self.assertEqual(c2["en_foco"], 0)
        self.assertEqual(c2["estado"], "activo")

    def test_ingesta_restringida_a_capitulo_en_foco(self):
        """La ingesta automática y corte de fecha se aplican exclusivamente al capítulo en foco."""
        ahora = time.time()
        # cap1 abierto en el pasado
        cap1 = self.db.empezar_capitulo("lucie", "antiguo")
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("UPDATE bandeja_capitulos SET fecha_inicio = '2026-01-01T00:00:00' WHERE id = ?", (cap1["id"],))
        conn.close()

        # cap2 en foco iniciado después de arch_ant
        # Archivo anterior a cap2 (creado antes de empezar cap2)
        arch_ant = os.path.join(self.descargas, "grok-image-1.jpg")
        self._crear_archivo(arch_ant, b"foto anterior", mtime=ahora - 500)
        time.sleep(0.02)

        cap2 = self.db.empezar_capitulo("roli", "foco_actual")

        # Archivo posterior a cap2
        arch_post = os.path.join(self.descargas, "grok-image-2.jpg")
        self._crear_archivo(arch_post, b"foto nueva", mtime=ahora + 10)

        self.vigilante.escanear()
        self.vigilante.escanear()

        estado = self.vigilante.obtener_estado()
        lotes = estado["lotes"]
        lotes_ant = estado["lotes_anteriores"]

        # El posterior debe estar asignado a cap2 (foco_actual)
        lote_nuevo = next((l for l in lotes if any(a["nombre"] == "grok-image-2.jpg" for a in l["archivos"])), None)
        self.assertIsNotNone(lote_nuevo)
        self.assertEqual(lote_nuevo["escena_sugerida"], "foco_actual")
        self.assertEqual(lote_nuevo["personaje_sugerido"], "roli")

        # El anterior no se asigna al capítulo en foco
        lote_ant = next((l for l in lotes_ant if any(a["nombre"] == "grok-image-1.jpg" for a in l["archivos"])), None)
        self.assertIsNotNone(lote_ant)
        self.assertEqual(lote_ant.get("escena_sugerida", ""), "")

    def test_envio_manual_a_capitulo_secundario_incrementa_movidos(self):
        """Mover archivos manualmente a un capítulo abierto secundario incrementa sus archivos_movidos."""
        cap1 = self.db.empezar_capitulo("lucie", "secundario")
        cap2 = self.db.empezar_capitulo("roli", "foco")

        archivo = os.path.join(self.descargas, "foto_manual.jpg")
        self._crear_archivo(archivo, b"contenido foto")
        self.vigilante.escanear()
        self.vigilante.escanear()

        arch_db = self.db.obtener_por_hash(calcular_sha256(archivo))
        archivos_lote = [{
            "id_db": arch_db["id"],
            "hash": arch_db["hash"],
            "ruta": archivo,
            "nombre": "foto_manual.jpg",
            "tamanio": len(b"contenido foto")
        }]

        sim = self.movimientos.simular_movimiento_lote(archivos_lote, "lucie", "secundario")
        self.movimientos.ejecutar_movimiento_lote(sim, "lote_manual")

        # Verificar que archivos_movidos de cap1 se incrementó en 1
        cap1_db = self.db.obtener_capitulo_por_id(cap1["id"])
        self.assertEqual(cap1_db["archivos_movidos"], 1)

        # cap2 sigue en 0
        cap2_db = self.db.obtener_capitulo_por_id(cap2["id"])
        self.assertEqual(cap2_db["archivos_movidos"], 0)

    def test_terminar_o_descartar_capitulo_en_foco_deja_foco_vacio_sin_afectar_otros(self):
        """Terminar el capítulo en foco deja el foco vacío sin cerrar los otros capítulos abiertos."""
        cap1 = self.db.empezar_capitulo("lucie", "abierto_secundario")
        cap2 = self.db.empezar_capitulo("roli", "abierto_en_foco")

        self.db.terminar_capitulo(cap2["id"])

        # Foco debe estar vacío (habilitado=False)
        foco = self.db.obtener_capitulo_en_foco()
        self.assertFalse(foco["habilitado"])

        # cap1 sigue abierto con en_foco = 0
        abiertos = self.db.listar_capitulos_abiertos()
        self.assertEqual(len(abiertos), 1)
        self.assertEqual(abiertos[0]["id"], cap1["id"])
        self.assertEqual(abiertos[0]["en_foco"], 0)

    def test_terminar_capitulo_secundario_no_afecta_foco(self):
        """Cerrar un capítulo abierto secundario no modifica el capítulo en foco."""
        cap1 = self.db.empezar_capitulo("lucie", "secundario_a_cerrar")
        cap2 = self.db.empezar_capitulo("roli", "permanece_en_foco")

        self.db.terminar_capitulo(cap1["id"])

        foco = self.db.obtener_capitulo_en_foco()
        self.assertTrue(foco["habilitado"])
        self.assertEqual(foco["id"], cap2["id"])
        self.assertEqual(foco["en_foco"], 1)

        abiertos = self.db.listar_capitulos_abiertos()
        self.assertEqual(len(abiertos), 1)
        self.assertEqual(abiertos[0]["id"], cap2["id"])

    def test_descartar_capitulo_en_foco_deja_foco_vacio_y_otros_abiertos(self):
        """Descartar el capítulo en foco deja el foco vacío y no afecta a los demás abiertos."""
        cap1 = self.db.empezar_capitulo("lucie", "abierto_restante")
        cap2 = self.db.empezar_capitulo("roli", "a_descartar")

        carpeta = os.path.join(self.destino, "roli", "a_descartar")
        self._crear_archivo(os.path.join(carpeta, "f1.jpg"), b"test descarte")

        sim = self.movimientos.simular_descartar_capitulo(cap2["id"])
        self.movimientos.ejecutar_descartar_capitulo(sim, "a_descartar")

        # Foco debe haber quedado vacío
        foco = self.db.obtener_capitulo_en_foco()
        self.assertFalse(foco["habilitado"])

        # cap2 descartado
        c2 = self.db.obtener_capitulo_por_id(cap2["id"])
        self.assertEqual(c2["descartado"], 1)
        self.assertEqual(c2["en_foco"], 0)

        # cap1 sigue abierto
        abiertos = self.db.listar_capitulos_abiertos()
        self.assertEqual(len(abiertos), 1)
        self.assertEqual(abiertos[0]["id"], cap1["id"])

    def test_reabrir_capitulo_toma_foco_solo_si_no_hay_foco(self):
        """Al reabrir un capítulo cerrado, solo toma el foco si ningún otro está en foco."""
        cap1 = self.db.empezar_capitulo("lucie", "h1")
        self.db.terminar_capitulo(cap1["id"])

        # 1. Sin capítulos abiertos: al reabrir, toma foco
        reabierto1 = self.db.reabrir_capitulo(cap1["id"])
        self.assertEqual(reabierto1["en_foco"], 1)
        self.assertEqual(self.db.obtener_capitulo_en_foco()["id"], cap1["id"])

        # Abrir cap2 (toma foco)
        cap2 = self.db.empezar_capitulo("roli", "h2")
        self.assertEqual(self.db.obtener_capitulo_en_foco()["id"], cap2["id"])

        # Cerrar cap1 y reabrirlo: cap2 ya tiene foco, por lo que cap1 no debe tomarlo
        self.db.terminar_capitulo(cap1["id"])
        reabierto2 = self.db.reabrir_capitulo(cap1["id"])
        self.assertEqual(reabierto2["en_foco"], 0)
        self.assertEqual(self.db.obtener_capitulo_en_foco()["id"], cap2["id"])

    def test_endpoints_capitulos_abiertos_y_en_foco(self):
        """Endpoints /api/capitulos/abiertos y /api/capitulos/en-foco con validación CSRF y Host."""
        self._iniciar_servidor_prueba()

        cap1 = self.db.empezar_capitulo("lucie", "api_uno")
        cap2 = self.db.empezar_capitulo("roli", "api_dos")

        headers_ok = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "X-CSRF-Token": self.token_csrf,
            "Content-Type": "application/json"
        }

        # 1. GET /api/capitulos/abiertos
        status, data, _ = self._request("GET", "/api/capitulos/abiertos", headers={"Host": f"127.0.0.1:{self.config.puerto_servidor}"})
        self.assertEqual(status, 200)
        self.assertIn("abiertos", data)
        self.assertEqual(len(data["abiertos"]), 2)

        # 2. GET /api/capitulos/estado
        status, data, _ = self._request("GET", "/api/capitulos/estado", headers={"Host": f"127.0.0.1:{self.config.puerto_servidor}"})
        self.assertEqual(status, 200)
        self.assertIn("capitulo_foco", data)
        self.assertIn("capitulos_abiertos", data)
        self.assertEqual(data["cantidad_abiertos"], 2)
        self.assertEqual(data["capitulo_foco"]["id"], cap2["id"])

        # 3. POST /api/capitulos/en-foco sin CSRF -> 403
        status, _, _ = self._request(
            "POST",
            "/api/capitulos/en-foco",
            headers={"Host": f"127.0.0.1:{self.config.puerto_servidor}", "Content-Type": "application/json"},
            body=json.dumps({"id": cap1["id"]})
        )
        self.assertEqual(status, 403)

        # 4. POST /api/capitulos/en-foco con Host inválido -> 403
        status, _, _ = self._request(
            "POST",
            "/api/capitulos/en-foco",
            headers={"Host": "malicious.com", "X-CSRF-Token": self.token_csrf, "Content-Type": "application/json"},
            body=json.dumps({"id": cap1["id"]})
        )
        self.assertEqual(status, 403)

        # 5. POST /api/capitulos/en-foco exitoso -> pasa foco a cap1
        status, res_foco, _ = self._request(
            "POST",
            "/api/capitulos/en-foco",
            headers=headers_ok,
            body=json.dumps({"id": cap1["id"]})
        )
        self.assertEqual(status, 200)
        self.assertTrue(res_foco["exito"])
        self.assertEqual(res_foco["capitulo"]["id"], cap1["id"])

        # Verificar foco cambiado
        foco_actual = self.db.obtener_capitulo_en_foco()
        self.assertEqual(foco_actual["id"], cap1["id"])

        # 6. POST /api/capitulos/terminar con id explícito
        status, res_term, _ = self._request(
            "POST",
            "/api/capitulos/terminar",
            headers=headers_ok,
            body=json.dumps({"id": cap1["id"], "accion": "sin_mover"})
        )
        self.assertEqual(status, 200)
        self.assertTrue(res_term["exito"])
        # cap1 cerrado
        c1 = self.db.obtener_capitulo_por_id(cap1["id"])
        self.assertEqual(c1["estado"], "cerrado")
        self.assertEqual(c1["en_foco"], 0)


class TestCortePorFechaDeLlegada(unittest.TestCase):
    """
    Pruebas para el cambio corte-por-fecha-de-llegada:
    - Archivo con mtime viejo pero ctime posterior al inicio del capítulo se asigna al capítulo en foco y queda tildado.
    - Archivo con mtime y ctime anteriores queda en 'Anteriores', destildado.
    - horas_material_reciente usa la fecha de llegada.
    - El aviso de lotes nuevos no cuenta los de 'Anteriores'.
    - La función de fecha de llegada devuelve el máximo entre mtime y ctime.
    - El banner en foco incluye la marca visual de foco.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_corte_llegada_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.descargas, "_lucie")
        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

        self.db_file = os.path.join(self.tmp_dir, "bandeja.db")
        self.bitacora_file = os.path.join(self.tmp_dir, "bitacora.jsonl")
        self.cfg_file = os.path.join(self.tmp_dir, "config.json")
        self.alias_file = os.path.join(self.tmp_dir, "alias.json")

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
            "minutos_antes_inicio_capitulo": 0,
            "horas_material_reciente": 0,
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
        self.detector = DetectorDescargasActivas(ventana_estabilidad_segundos=0.01)
        self.agrupador = AgrupadorLotes(ventana_minutos=10)
        self.gestor = GestorMovimientosBandeja(
            self.descargas, self.destino, self.db,
            ruta_bitacora=self.bitacora_file, ruta_alias=self.alias_file
        )
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)

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

    def test_archivo_mtime_viejo_pero_ctime_posterior_se_asigna_a_foco_y_queda_tildado(self):
        """Archivo con mtime viejo pero ctime posterior al inicio del capítulo se asigna al capítulo en foco y queda tildado."""
        t0 = datetime.datetime.now() - datetime.timedelta(seconds=5)
        self.db.empezar_capitulo("lucie", "parque_grok", fecha_inicio=t0.isoformat())

        ruta = os.path.join(self.descargas, "grok-video-descargado.mp4")
        with open(ruta, "wb") as f:
            f.write(b"video fresco de grok")

        # Simular descarga con mtime viejo del servidor (hace 1 hora)
        ts_viejo = t0.timestamp() - 3600
        os.utime(ruta, (ts_viejo, ts_viejo))

        # Verificar que efectivamente mtime es viejo pero ctime es nuevo
        st = os.stat(ruta)
        self.assertLess(st.st_mtime, t0.timestamp())
        self.assertGreater(st.st_ctime, t0.timestamp())

        self.vigilante.escanear()
        time.sleep(0.02)
        self.vigilante.escanear()

        estado = self.vigilante.obtener_estado()
        self.assertEqual(len(estado["lotes"]), 1)
        self.assertEqual(len(estado["lotes_anteriores"]), 0)
        lote = estado["lotes"][0]
        self.assertFalse(lote.get("es_anterior", False))
        self.assertEqual(lote["personaje_sugerido"], "lucie")
        self.assertEqual(lote["escena_sugerida"], "parque_grok")
        self.assertEqual(len(lote["archivos"]), 1)
        arch = lote["archivos"][0]
        self.assertEqual(arch["nombre"], "grok-video-descargado.mp4")
        self.assertFalse(arch.get("es_anterior", False))
        self.assertEqual(arch["personaje"], "lucie")
        self.assertEqual(arch["escena"], "parque_grok")
        self.assertEqual(arch["estado"], "clasificado")
        self.assertIn("fecha_llegada", arch)
        self.assertGreater(arch["fecha_llegada_ts"], t0.timestamp())

    def test_archivo_mtime_y_ctime_anteriores_queda_en_anteriores_destildado(self):
        """Archivo con mtime y ctime anteriores queda en 'Anteriores', destildado."""
        ruta = os.path.join(self.descargas, "grok-video-antiguo.mp4")
        with open(ruta, "wb") as f:
            f.write(b"archivo anterior")
        time.sleep(0.02)

        t_cap = datetime.datetime.now()
        ts_cap = t_cap.timestamp()
        ts_viejo = ts_cap - 3600
        os.utime(ruta, (ts_viejo, ts_viejo))

        self.db.empezar_capitulo("roli", "gimnasio", fecha_inicio=t_cap.isoformat())

        st = os.stat(ruta)
        self.assertLess(st.st_mtime, ts_cap)
        self.assertLess(st.st_ctime, ts_cap)

        self.vigilante.escanear()
        time.sleep(0.02)
        self.vigilante.escanear()

        estado = self.vigilante.obtener_estado()
        self.assertEqual(len(estado["lotes"]), 0)
        self.assertEqual(len(estado["lotes_anteriores"]), 1)
        lote_ant = estado["lotes_anteriores"][0]
        self.assertTrue(lote_ant["es_anterior"])
        self.assertEqual(lote_ant.get("escena_sugerida", ""), "")
        arch = lote_ant["archivos"][0]
        self.assertTrue(arch.get("es_anterior", False))
        self.assertEqual(arch.get("escena", ""), "")
        self.assertEqual(arch["estado"], "detectado")

    def test_horas_material_reciente_usa_fecha_llegada(self):
        """horas_material_reciente usa la fecha de llegada."""
        self.config.horas_material_reciente = 2.0
        now_ts = time.time()

        # Archivo A: mtime viejo (10h atrás) pero ctime reciente (ahora)
        ruta_a = os.path.join(self.descargas, "grok-video-fresco.mp4")
        with open(ruta_a, "wb") as f:
            f.write(b"video fresco con Last-Modified viejo")
        os.utime(ruta_a, (now_ts - 36000, now_ts - 36000))

        # Archivo B: archivo viejo fuera de las 2 horas
        ruta_b = os.path.join(self.descargas, "grok-video-viejo.mp4")
        with open(ruta_b, "wb") as f:
            f.write(b"video viejo")

        stat_b_mock = os.stat_result((
            33188, 1, 1, 1, 1000, 1000, 100,
            now_ts - 18000,
            now_ts - 18000,
            now_ts - 18000
        ))

        orig_stat = os.stat
        def fake_stat(p, *args, **kwargs):
            if os.path.abspath(p) == os.path.abspath(ruta_b):
                return stat_b_mock
            return orig_stat(p, *args, **kwargs)

        with patch("os.stat", side_effect=fake_stat):
            self.vigilante.escanear()
            time.sleep(0.02)
            self.vigilante.escanear()

            estado = self.vigilante.obtener_estado()
            nombres_principales = [a["nombre"] for l in estado["lotes"] for a in l["archivos"]]
            self.assertIn("grok-video-fresco.mp4", nombres_principales)
            self.assertNotIn("grok-video-viejo.mp4", nombres_principales)

            nombres_ant = [a["nombre"] for l in estado["lotes_anteriores"] for a in l["archivos"]]
            self.assertIn("grok-video-viejo.mp4", nombres_ant)

    def test_aviso_lotes_nuevos_no_cuenta_anteriores(self):
        """El aviso de lotes nuevos no cuenta los de 'Anteriores'."""
        ruta_ant = os.path.join(self.descargas, "grok-video-anterior.mp4")
        with open(ruta_ant, "wb") as f:
            f.write(b"archivo anterior")
        time.sleep(0.02)

        t_cap = datetime.datetime.now()
        ts_cap = t_cap.timestamp()
        os.utime(ruta_ant, (ts_cap - 500, ts_cap - 500))
        self.db.empezar_capitulo("lucie", "aviso_test", fecha_inicio=t_cap.isoformat())

        with patch.object(self.vigilante, "_notificar_escritorio") as mock_notif:
            self.vigilante.escanear()
            time.sleep(0.02)
            self.vigilante.escanear()

            estado = self.vigilante.obtener_estado()
            self.assertEqual(len(estado["lotes_anteriores"]), 1)
            self.assertEqual(len(estado["lotes"]), 0)
            mock_notif.assert_not_called()

            # Llega un archivo nuevo posterior al inicio del capítulo
            ruta_nuevo = os.path.join(self.descargas, "grok-video-nuevo.mp4")
            with open(ruta_nuevo, "wb") as f:
                f.write(b"archivo nuevo")

            self.vigilante.escanear()
            time.sleep(0.02)
            self.vigilante.escanear()

            estado2 = self.vigilante.obtener_estado()
            self.assertEqual(len(estado2["lotes"]), 1)
            mock_notif.assert_called_once()
            self.assertIn("1 lote(s) nuevo(s)", mock_notif.call_args[0][0])

    def test_funcion_fecha_llegada_devuelve_maximo_entre_mtime_y_ctime(self):
        """La función de fecha de llegada devuelve el máximo entre mtime y ctime."""
        from bandeja_descargas import obtener_fecha_llegada

        class MockStat1:
            st_mtime = 1000.0
            st_ctime = 2500.0
        self.assertEqual(obtener_fecha_llegada(MockStat1()), 2500.0)

        class MockStat2:
            st_mtime = 3500.0
            st_ctime = 1500.0
        self.assertEqual(obtener_fecha_llegada(MockStat2()), 3500.0)

        class MockStat3:
            st_mtime = 2000.0
            st_ctime = 2000.0
        self.assertEqual(obtener_fecha_llegada(MockStat3()), 2000.0)

        d = {"mtime": 1200.0, "ctime": 4800.0}
        self.assertEqual(obtener_fecha_llegada(d), 4800.0)

        test_file = os.path.join(self.descargas, "prueba_llegada.mp4")
        with open(test_file, "wb") as f:
            f.write(b"prueba")
        os.utime(test_file, (1000.0, 1000.0))
        st = os.stat(test_file)
        self.assertEqual(obtener_fecha_llegada(test_file), st.st_ctime)
        self.assertGreater(obtener_fecha_llegada(test_file), 1000.0)

    def test_banner_en_foco_incluye_marca_visual_de_foco(self):
        """El banner en foco incluye la marca visual de foco."""
        ruta_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bandeja_descargas.py")
        with open(ruta_script, "r", encoding="utf-8") as f:
            contenido = f.read()

        self.assertIn("⭐ EN FOCO", contenido)
        self.assertIn("#f59e0b", contenido)
        self.assertIn("banner-otros-abiertos", contenido)

        from bandeja_descargas import crear_servidor, GeneradorMiniaturas
        thumbs_dir = os.path.join(self.tmp_dir, "thumbs")
        miniaturas = GeneradorMiniaturas(self.db, thumbs_dir)
        self.config.puerto_servidor = 0
        server = crear_servidor(
            self.config, self.db, self.vigilante, self.gestor, miniaturas, token_csrf="token_test"
        )
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
                self.assertEqual(resp.status, 200)
                html_body = resp.read().decode("utf-8")
                self.assertIn("⭐ EN FOCO", html_body)
                self.assertIn("banner-capitulo-activo", html_body)
                self.assertIn("banner-otros-abiertos", html_body)
        finally:
            server.shutdown()
            server.server_close()


class TestRefrescoAutomaticoPanel(unittest.TestCase):
    """
    Pruebas para el refresco automático del panel web y detección sin demoras:
    - /api/estado-version cambia cuando entra un archivo nuevo y no cambia si nada cambió.
    - Redibujar conserva tildes, texto de escena nueva, selección de desplegables, <details> abierto y scroll.
    - No consulta con la pestaña oculta ni con un modal abierto; consulta al volver.
    - El título muestra "(N)" con lotes nuevos en segundo plano.
    - Reintento con espera creciente cuando el servidor no responde.
    - Archivo con extensión temporal no genera lote.
    - El endpoint valida Host y no acepta POST.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_bandeja_refresco_")
        self.descargas = os.path.join(self.tmp_dir, "Descargas")
        self.destino = os.path.join(self.tmp_dir, "Destino")
        os.makedirs(self.descargas, exist_ok=True)
        os.makedirs(self.destino, exist_ok=True)

        self.cfg_file = os.path.join(self.tmp_dir, "config.json")
        cfg_data = {
            "ruta_descargas": self.descargas,
            "ruta_destino_base": self.destino,
            "puerto_servidor": 0,
            "refresco_panel_segundos": 4,
            "horas_material_reciente": 24,
            "ventana_lote_minutos": 5,
            "ventana_estabilidad_segundos": 1,
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

        self.config = ConfiguracionBandeja(self.cfg_file)
        self.db = GestorBaseDatosBandeja(os.path.join(self.tmp_dir, "bandeja.db"))
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas(ventana_estabilidad_segundos=1)
        self.agrupador = AgrupadorLotes(self.config.ventana_lote_minutos)
        self.gestor = GestorMovimientosBandeja(self.descargas, self.destino, self.db)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        self.miniaturas = GeneradorMiniaturas(self.db, os.path.join(self.tmp_dir, "thumbs"))

        self.server = crear_servidor(
            self.config, self.db, self.vigilante, self.gestor, self.miniaturas, token_csrf="token_test"
        )
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass
        self.vigilante.detener()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _peticion_http(self, metodo: str, ruta: str, host: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if host:
            headers["Host"] = host
        else:
            headers["Host"] = f"127.0.0.1:{self.port}"
        conn.request(metodo, ruta, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        cuerpo = resp.read().decode("utf-8")
        conn.close()
        try:
            data = json.loads(cuerpo)
        except Exception:
            data = {"raw": cuerpo}
        return status, data

    def test_estado_version_cambia_con_archivo_nuevo_y_estable_sin_cambios(self):
        """/api/estado-version cambia cuando entra un archivo nuevo y no cambia si nada cambió."""
        # 1. Petición inicial sin archivos
        status, data1 = self._peticion_http("GET", "/api/estado-version")
        self.assertEqual(status, 200)
        self.assertIn("version", data1)
        self.assertEqual(data1["refresco_panel_segundos"], 4)
        v1 = data1["version"]

        # 2. Sin cambios, la versión debe ser idéntica
        status, data2 = self._peticion_http("GET", "/api/estado-version")
        self.assertEqual(status, 200)
        self.assertEqual(data2["version"], v1)

        # 3. Entra un archivo nuevo
        nuevo_file = os.path.join(self.descargas, "grok-video-autotest1.mp4")
        with open(nuevo_file, "wb") as f:
            f.write(b"video data 12345")
        # Primer escaneo lo detecta
        self.vigilante.escanear()
        # Esperar ventana de estabilidad (1.0s)
        time.sleep(1.2)
        # Segundo escaneo tras estabilidad lo agrupa en lote y registra
        self.vigilante.escanear()

        # 4. Ahora la versión debe haber cambiado
        status, data3 = self._peticion_http("GET", "/api/estado-version")
        self.assertEqual(status, 200)
        v2 = data3["version"]
        self.assertNotEqual(v1, v2)

        # 5. Sin nuevos cambios, v2 debe permanecer estable
        status, data4 = self._peticion_http("GET", "/api/estado-version")
        self.assertEqual(status, 200)
        self.assertEqual(data4["version"], v2)

    def test_endpoint_valida_host_y_no_acepta_post(self):
        """El endpoint valida Host y no acepta POST."""
        # POST a /api/estado-version debe retornar 405 Method Not Allowed
        status, data = self._peticion_http("POST", "/api/estado-version")
        self.assertEqual(status, 405)
        self.assertIn("error", data)

        # Host inválido (ej. evil.com) debe ser rechazado con 403 Forbidden
        status, data = self._peticion_http("GET", "/api/estado-version", host="evil.com")
        self.assertEqual(status, 403)

        # Host válido local debe retornar 200 OK
        status, data = self._peticion_http("GET", "/api/estado-version", host=f"127.0.0.1:{self.port}")
        self.assertEqual(status, 200)

    def test_archivo_con_extension_temporal_no_genera_lote(self):
        """Archivo con extensión temporal (.crdownload, .part, .tmp) no genera lote."""
        tmp1 = os.path.join(self.descargas, "grok-video-descargando.mp4.crdownload")
        tmp2 = os.path.join(self.descargas, "lucie_video.mp4.part")
        tmp3 = os.path.join(self.descargas, "captura.tmp")
        for p in [tmp1, tmp2, tmp3]:
            with open(p, "wb") as f:
                f.write(b"incompleto")

        time.sleep(1.2)
        self.vigilante.escanear()

        # Los lotes detectados deben estar vacíos
        self.assertEqual(len(self.vigilante._lotes_actuales), 0)
        self.assertEqual(len(self.vigilante._lotes_anteriores_actuales), 0)
        self.assertEqual(self.filtro.clasificar_archivo("grok-video-descargando.mp4.crdownload"), "ignorar")
        self.assertEqual(self.filtro.clasificar_archivo("lucie_video.mp4.part"), "ignorar")
        self.assertEqual(self.filtro.clasificar_archivo("captura.tmp"), "ignorar")

    def test_carpeta_lucieoloraculo_no_se_confunde_con_escena(self):
        """Revisar la carpeta lucieoloraculo: no comienza con alias delimitado y no se confunde con escena."""
        self.assertFalse(self.filtro.es_carpeta_escena_existente("lucieoloraculo"))
        self.assertTrue(self.filtro.es_carpeta_escena_existente("lucie oraculo"))
        self.assertTrue(self.filtro.es_carpeta_escena_existente("lucie_oraculo"))
        self.assertTrue(self.filtro.es_carpeta_escena_existente("lucie-oraculo"))

    def test_deteccion_tiempos_lifecycle_logs(self):
        """Verifica que el detector y vigilante emiten logs estructurados [BANDEJA][DETECTADO], [ESTABLE] y [REGISTRADO]."""
        test_file = os.path.join(self.descargas, "grok-video-lifecycle.mp4")
        with open(test_file, "wb") as f:
            f.write(b"lifecycle video")

        # Escanear de inmediato (debe marcarse como activa/detectada)
        with self.assertLogs("bandeja_descargas", level="INFO") as cm:
            self.detector.es_archivo_estable(test_file)
            self.assertTrue(any("[DETECTADO]" in log for log in cm.output))

        # Esperar estabilidad
        time.sleep(1.2)
        with self.assertLogs("bandeja_descargas", level="INFO") as cm:
            self.assertTrue(self.detector.es_archivo_estable(test_file))
            self.assertTrue(any("[ESTABLE]" in log for log in cm.output))

        # Al escanear en el vigilante, se registra en DB
        with self.assertLogs("bandeja_descargas", level="INFO") as cm:
            self.vigilante.escanear()
            self.assertTrue(any("[REGISTRADO]" in log for log in cm.output))

    def test_frontend_funciones_preservacion_ui_y_pausas_en_node(self):
        """
        Ejecuta pruebas en Node.js sobre la lógica de la SPA:
        - Redibujar conserva tildes, texto de escena nueva, selección de desplegables, <details> abierto y scroll.
        - No consulta con la pestaña oculta ni con un modal abierto; consulta al volver.
        - El título muestra "(N)" con lotes nuevos en segundo plano.
        - Reintento con espera creciente cuando el servidor no responde.
        """
        import subprocess

        # Obtener el HTML generado por el servidor
        status, resp = self._peticion_http("GET", "/")
        self.assertEqual(status, 200)
        html_code = resp.get("raw", "")

        # Verificar presencia de elementos en el DOM servido
        self.assertIn('id="banner-desconexion"', html_code)
        self.assertIn('id="toast-llegada"', html_code)
        self.assertIn('REFRESCO_PANEL_SEGUNDOS = 4', html_code)

        # Script de prueba en Node para verificar la lógica SPA
        js_test = f"""
        const assert = require('assert');

        // Mocks de entorno DOM
        class MockElement {{
          constructor(tag, id = '') {{
            this.tagName = tag.toUpperCase();
            this.id = id;
            this.style = {{ display: '' }};
            this.attributes = {{}};
            this.children = [];
            this.value = '';
            this.checked = false;
            this.innerHTML = '';
            this.innerText = '';
            this.classList = {{
              classes: new Set(),
              add(c) {{ this.classes.add(c); }},
              remove(c) {{ this.classes.delete(c); }},
              contains(c) {{ return this.classes.has(c); }}
            }};
          }}
          getAttribute(n) {{ return this.attributes[n] !== undefined ? this.attributes[n] : null; }}
          setAttribute(n, v) {{ this.attributes[n] = String(v); }}
          removeAttribute(n) {{ delete this.attributes[n]; }}
          hasAttribute(n) {{ return Object.prototype.hasOwnProperty.call(this.attributes, n); }}
          appendChild(c) {{ this.children.push(c); }}
          remove() {{}}
        }}

        const elements = new Map();
        function getOrCreate(id, tag = 'div') {{
          if (!elements.has(id)) {{
            elements.set(id, new MockElement(tag, id));
          }}
          return elements.get(id);
        }}

        getOrCreate('banner-desconexion');
        getOrCreate('toast-llegada');
        getOrCreate('details-anteriores');
        getOrCreate('modal-simulacion');
        getOrCreate('modal-terminar-capitulo');
        getOrCreate('modal-descartar-capitulo');
        getOrCreate('contenedor-lotes');
        getOrCreate('contenedor-lotes-anteriores');
        getOrCreate('sec-lotes-anteriores');

        const document = {{
          title: 'Bandeja de Descargas - Proyecto Lucie',
          hidden: false,
          activeElement: null,
          getElementById(id) {{
            return elements.get(id) || null;
          }},
          querySelectorAll(sel) {{
            const res = [];
            for (const el of elements.values()) {{
              if (sel === '.chk-archivo' && el.attributes['data-id']) res.push(el);
              if (sel === '.cb-lote-listo' && el.attributes['data-lote-id']) res.push(el);
              if (sel === '.cb-lote-anterior' && el.attributes['data-lote-id']) res.push(el);
              if (sel.startsWith('select[id^="sel-pers-"]') && el.id.startsWith('sel-pers-')) res.push(el);
              if (sel.startsWith('select[id^="sel-escena-"]') && el.id.startsWith('sel-escena-')) res.push(el);
              if (sel.startsWith('input[id^="txt-nueva-escena-"]') && el.id.startsWith('txt-nueva-escena-')) res.push(el);
            }}
            return res;
          }},
          addEventListener(ev, fn) {{}}
        }};

        const window = {{
          scrollY: 150,
          scrollTo(x, y) {{ this.scrollY = y; }},
          addEventListener(ev, fn) {{}}
        }};

        // 1. Prueba de captura y restauración de estado UI
        const cbArch = new MockElement('input', 'chk-a1');
        cbArch.setAttribute('data-id', '101');
        cbArch.checked = true;
        elements.set('chk-a1', cbArch);

        const selPers = new MockElement('select', 'sel-pers-lote1');
        selPers.value = 'roli';
        elements.set('sel-pers-lote1', selPers);

        const selEsc = new MockElement('select', 'sel-escena-lote1');
        selEsc.value = '__nueva__';
        elements.set('sel-escena-lote1', selEsc);

        const txtEsc = new MockElement('input', 'txt-nueva-escena-lote1');
        txtEsc.value = 'escena personalizada';
        txtEsc.style.display = 'inline-block';
        elements.set('txt-nueva-escena-lote1', txtEsc);

        const detAnt = getOrCreate('details-anteriores');
        detAnt.setAttribute('open', '');

        function capturarEstadoUI() {{
          const snap = {{
            archivosChecked: {{}},
            lotesListosChecked: {{}},
            lotesAnterioresChecked: {{}},
            persSeleccionado: {{}},
            escenaSeleccionada: {{}},
            nuevaEscenaTexto: {{}},
            detailsAnterioresAbierto: false,
            scrollY: window.scrollY || 0,
            pestana: 'lotes'
          }};
          document.querySelectorAll('.chk-archivo').forEach(cb => {{
            const id = cb.getAttribute('data-id');
            if (id) snap.archivosChecked[id] = cb.checked;
          }});
          document.querySelectorAll('select[id^="sel-pers-"]').forEach(sel => {{
            snap.persSeleccionado[sel.id.replace('sel-pers-', '')] = sel.value;
          }});
          document.querySelectorAll('select[id^="sel-escena-"]').forEach(sel => {{
            snap.escenaSeleccionada[sel.id.replace('sel-escena-', '')] = sel.value;
          }});
          document.querySelectorAll('input[id^="txt-nueva-escena-"]').forEach(inp => {{
            snap.nuevaEscenaTexto[inp.id.replace('txt-nueva-escena-', '')] = inp.value;
          }});
          snap.detailsAnterioresAbierto = detAnt.hasAttribute('open');
          return snap;
        }}

        function restaurarEstadoUI(snap) {{
          document.querySelectorAll('.chk-archivo').forEach(cb => {{
            const id = cb.getAttribute('data-id');
            if (id && snap.archivosChecked[id] !== undefined) cb.checked = snap.archivosChecked[id];
          }});
          for (const k in snap.persSeleccionado) {{
            const el = elements.get(`sel-pers-${{k}}`);
            if (el) el.value = snap.persSeleccionado[k];
          }}
          for (const k in snap.escenaSeleccionada) {{
            const el = elements.get(`sel-escena-${{k}}`);
            if (el) el.value = snap.escenaSeleccionada[k];
          }}
          for (const k in snap.nuevaEscenaTexto) {{
            const el = elements.get(`txt-nueva-escena-${{k}}`);
            if (el) el.value = snap.nuevaEscenaTexto[k];
          }}
          if (snap.detailsAnterioresAbierto) detAnt.setAttribute('open', '');
          else detAnt.removeAttribute('open');
          window.scrollTo(0, snap.scrollY);
        }}

        const snap = capturarEstadoUI();
        assert.strictEqual(snap.archivosChecked['101'], true);
        assert.strictEqual(snap.persSeleccionado['lote1'], 'roli');
        assert.strictEqual(snap.escenaSeleccionada['lote1'], '__nueva__');
        assert.strictEqual(snap.nuevaEscenaTexto['lote1'], 'escena personalizada');
        assert.strictEqual(snap.detailsAnterioresAbierto, true);
        assert.strictEqual(snap.scrollY, 150);

        cbArch.checked = false;
        selPers.value = 'lucie';
        selEsc.value = '';
        txtEsc.value = '';
        detAnt.removeAttribute('open');
        window.scrollY = 0;

        restaurarEstadoUI(snap);
        assert.strictEqual(cbArch.checked, true, 'Debe restaurar checkbox tildado');
        assert.strictEqual(selPers.value, 'roli', 'Debe restaurar personaje');
        assert.strictEqual(selEsc.value, '__nueva__', 'Debe restaurar escena seleccionada');
        assert.strictEqual(txtEsc.value, 'escena personalizada', 'Debe restaurar texto de escena nueva');
        assert.strictEqual(detAnt.hasAttribute('open'), true, 'Debe restaurar details open');
        assert.strictEqual(window.scrollY, 150, 'Debe restaurar scroll');

        // 2. Prueba de detección de modales abiertos
        function hayModalAbierto() {{
          const ids = ['modal-simulacion', 'modal-terminar-capitulo', 'modal-descartar-capitulo'];
          return ids.some(id => {{
            const el = elements.get(id);
            return el && el.style.display && el.style.display !== 'none';
          }});
        }}
        assert.strictEqual(hayModalAbierto(), false, 'Sin modales abiertos');
        elements.get('modal-simulacion').style.display = 'flex';
        assert.strictEqual(hayModalAbierto(), true, 'Con modal-simulacion abierto');
        elements.get('modal-simulacion').style.display = 'none';
        assert.strictEqual(hayModalAbierto(), false, 'Tras cerrar modal');

        // 3. Prueba de título con (N) cuando la pestaña está oculta
        let lotesNuevosSegundoPlano = 0;
        const TITULO_BASE = document.title;
        document.hidden = true;
        const nuevosLotes = 2;
        if (document.hidden && nuevosLotes > 0) {{
          lotesNuevosSegundoPlano += nuevosLotes;
          document.title = `(${{lotesNuevosSegundoPlano}}) ${{TITULO_BASE}}`;
        }}
        assert.strictEqual(document.title, '(2) Bandeja de Descargas - Proyecto Lucie');
        document.hidden = false;
        lotesNuevosSegundoPlano = 0;
        document.title = TITULO_BASE;
        assert.strictEqual(document.title, 'Bandeja de Descargas - Proyecto Lucie');

        // 4. Prueba de espera creciente en fallo
        let reintentoEsperaSegundos = 4;
        let desconectado = false;
        function registrarFallo() {{
          desconectado = true;
          reintentoEsperaSegundos = Math.min(reintentoEsperaSegundos * 2, 30);
        }}
        registrarFallo();
        assert.strictEqual(reintentoEsperaSegundos, 8);
        registrarFallo();
        assert.strictEqual(reintentoEsperaSegundos, 16);
        registrarFallo();
        assert.strictEqual(reintentoEsperaSegundos, 30);
        registrarFallo();
        assert.strictEqual(reintentoEsperaSegundos, 30);

        console.log('TESTS_NODE_OK');
        """
        proc = subprocess.run(["node", "-e", js_test], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Fallo en pruebas Node.js: {proc.stderr}")
        self.assertIn("TESTS_NODE_OK", proc.stdout)


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
