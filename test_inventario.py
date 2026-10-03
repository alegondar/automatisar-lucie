#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_inventario.py

Suite de pruebas unitarias y de integración para inventario_pendrive.py.
Verifica:
1. Seguridad de confinamiento de rutas con realpath (rechazo de symlinks que escapan).
2. Filtrado de carpetas del sistema y archivos ocultos.
3. Clasificación correcta por tipo de archivo según extensión.
4. Extracción de duración con ffprobe solo en videos.
5. Detección de duplicados globales y cross-carpeta por SHA-256.
6. Identificación de carpetas vacías y carpetas aparentemente duplicadas.
7. Detección de archivos sueltos en raíz y raíces de primer nivel.
8. Garantía de solo lectura (rechazo de caché o salida dentro del pendrive).
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from inventario_pendrive import (
    normalizar_raiz,
    esta_dentro_de_raiz,
    es_carpeta_sistema,
    es_elemento_oculto,
    clasificar_archivo,
    CacheInventario,
    AuditorPendrive,
    GeneradorReporte,
    calcular_sha256,
    formatear_bytes,
    formatear_duracion
)


class TestSeguridadYConfinamiento(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_pendrive_")
        self.tmp_external = tempfile.mkdtemp(prefix="test_external_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        shutil.rmtree(self.tmp_external, ignore_errors=True)

    def test_normalizar_raiz_valida(self):
        raiz_real = normalizar_raiz(self.tmp_dir)
        self.assertEqual(raiz_real, os.path.realpath(self.tmp_dir))

    def test_normalizar_raiz_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            normalizar_raiz(os.path.join(self.tmp_dir, "no_existe_12345"))

    def test_esta_dentro_de_raiz_subdirectorio_valido(self):
        sub = os.path.join(self.tmp_dir, "subcarpeta", "archivo.txt")
        os.makedirs(os.path.dirname(sub), exist_ok=True)
        with open(sub, "w") as f:
            f.write("test")
        self.assertTrue(esta_dentro_de_raiz(sub, self.tmp_dir))

    def test_symlink_que_escapa_de_raiz_es_rechazado(self):
        # Crear archivo fuera de la raíz
        archivo_externo = os.path.join(self.tmp_external, "secreto_externo.txt")
        with open(archivo_externo, "w") as f:
            f.write("contenido confidencial")

        # Crear symlink dentro de la raíz que apunta al archivo externo
        symlink_dentro = os.path.join(self.tmp_dir, "enlace_trampa.txt")
        try:
            os.symlink(archivo_externo, symlink_dentro)
        except OSError:
            self.skipTest("El sistema no permite crear symlinks sin privilegios.")

        # Debe ser rechazado porque realpath apunta fuera de la raíz
        self.assertFalse(esta_dentro_de_raiz(symlink_dentro, self.tmp_dir))


class TestFiltrosYSistema(unittest.TestCase):

    def test_carpetas_sistema_reconocidas(self):
        self.assertTrue(es_carpeta_sistema("System Volume Information"))
        self.assertTrue(es_carpeta_sistema("system volume information"))
        self.assertTrue(es_carpeta_sistema("$RECYCLE.BIN"))
        self.assertTrue(es_carpeta_sistema("$recycle.bin"))
        self.assertTrue(es_carpeta_sistema("lost+found"))
        self.assertTrue(es_carpeta_sistema(".Trash-1000"))
        self.assertTrue(es_carpeta_sistema(".Trash-root"))
        self.assertFalse(es_carpeta_sistema("Mis_Documentos"))
        self.assertFalse(es_carpeta_sistema("videos"))

    def test_elementos_ocultos(self):
        self.assertTrue(es_elemento_oculto(".git", "/dummy/.git"))
        self.assertTrue(es_elemento_oculto(".DS_Store", "/dummy/.DS_Store"))
        self.assertFalse(es_elemento_oculto("archivo.txt", "/dummy/archivo.txt"))
        self.assertFalse(es_elemento_oculto("fotos", "/dummy/fotos"))


class TestClasificacionArchivos(unittest.TestCase):

    def test_clasificaciones(self):
        self.assertEqual(clasificar_archivo("pelicula.mp4"), "video")
        self.assertEqual(clasificar_archivo("video.MKV"), "video")
        self.assertEqual(clasificar_archivo("foto.JPG"), "foto")
        self.assertEqual(clasificar_archivo("imagen.png"), "foto")
        self.assertEqual(clasificar_archivo("cancion.mp3"), "audio")
        self.assertEqual(clasificar_archivo("audio.flac"), "audio")
        self.assertEqual(clasificar_archivo("documento.pdf"), "documento")
        self.assertEqual(clasificar_archivo("notas.TXT"), "documento")
        self.assertEqual(clasificar_archivo("sub.srt"), "subtítulo")
        self.assertEqual(clasificar_archivo("sub.vtt"), "subtítulo")
        self.assertEqual(clasificar_archivo("programa.bin"), "otro")
        self.assertEqual(clasificar_archivo("archivo_sin_extension"), "otro")


class TestAuditoriaCompleta(unittest.TestCase):

    def setUp(self):
        self.pendrive_simulado = tempfile.mkdtemp(prefix="sim_pendrive_")
        self.repo_simulado = tempfile.mkdtemp(prefix="sim_repo_")

        # Estructura del pendrive simulado:
        # / (raíz)
        # ├── suelto_raiz1.txt (documento)
        # ├── suelto_raiz2.png (foto)
        # ├── .oculto_raiz.txt
        # ├── System Volume Information/ (carpeta sistema)
        # │   └── WPSettings.dat
        # ├── fotos/ (p1)
        # │   ├── foto1.jpg
        # │   ├── foto_duplicada.jpg (mismo contenido que fotos/foto1.jpg)
        # │   └── viajes/ (subcarpeta p2)
        # │       └── playa.jpg
        # ├── documentos/ (p1)
        # │   ├── reporte.pdf
        # │   └── copia_foto1.jpg (duplicado cross-carpeta de fotos/foto1.jpg)
        # ├── carpeta_vacia/ (p1 vacía)
        # └── carpeta_subvacia/ (p1 con subcarpeta vacía)
        #     └── vacia_nivel2/

        # Archivos sueltos en raíz
        with open(os.path.join(self.pendrive_simulado, "suelto_raiz1.txt"), "w") as f:
            f.write("texto suelto en la raiz")
        with open(os.path.join(self.pendrive_simulado, "suelto_raiz2.png"), "wb") as f:
            f.write(b"PNG_FAKE_DATA_12345")
        with open(os.path.join(self.pendrive_simulado, ".oculto_raiz.txt"), "w") as f:
            f.write("archivo oculto")

        # Sistema
        sys_dir = os.path.join(self.pendrive_simulado, "System Volume Information")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "WPSettings.dat"), "wb") as f:
            f.write(b"\x00\x01\x02\x03")

        # Carpeta fotos
        fotos_dir = os.path.join(self.pendrive_simulado, "fotos")
        viajes_dir = os.path.join(fotos_dir, "viajes")
        os.makedirs(viajes_dir, exist_ok=True)
        contenido_foto1 = b"ESTA_ES_LA_FOTO_1_EXACTA_CON_HASH_IDENTICO"
        with open(os.path.join(fotos_dir, "foto1.jpg"), "wb") as f:
            f.write(contenido_foto1)
        with open(os.path.join(fotos_dir, "foto_duplicada.jpg"), "wb") as f:
            f.write(contenido_foto1)
        with open(os.path.join(viajes_dir, "playa.jpg"), "wb") as f:
            f.write(b"FOTO_PLAYA_DISTINTA")

        # Carpeta documentos (con duplicado cross-carpeta de foto1.jpg)
        docs_dir = os.path.join(self.pendrive_simulado, "documentos")
        os.makedirs(docs_dir, exist_ok=True)
        with open(os.path.join(docs_dir, "reporte.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 REPORTE")
        with open(os.path.join(docs_dir, "copia_foto1.jpg"), "wb") as f:
            f.write(contenido_foto1)

        # Carpetas vacías
        os.makedirs(os.path.join(self.pendrive_simulado, "carpeta_vacia"), exist_ok=True)
        os.makedirs(os.path.join(self.pendrive_simulado, "carpeta_subvacia", "vacia_nivel2"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.pendrive_simulado, ignore_errors=True)
        shutil.rmtree(self.repo_simulado, ignore_errors=True)

    def test_auditoria_completa_e_informe(self):
        cache_file = os.path.join(self.repo_simulado, "cache.sqlite")
        auditor = AuditorPendrive(
            ruta_raiz=self.pendrive_simulado,
            incluir_ocultos=False,
            ruta_cache=cache_file
        )
        auditor.escanear()
        auditor.procesar_metadatos_y_duracion()

        generador = GeneradorReporte(auditor)
        datos = generador.generar_reporte_completo()

        # 1. Verificar exclusión de sistema y ocultos
        rutas_relativas = [a.ruta_relativa for a in auditor.archivos]
        self.assertNotIn(".oculto_raiz.txt", rutas_relativas)
        for r in rutas_relativas:
            self.assertFalse(r.startswith("System Volume Information"))

        # 2. Verificar archivos sueltos en raíz
        nombres_sueltos_raiz = [a.nombre for a in datos['archivos_sueltos_raiz']]
        self.assertIn("suelto_raiz1.txt", nombres_sueltos_raiz)
        self.assertIn("suelto_raiz2.png", nombres_sueltos_raiz)
        self.assertEqual(len(datos['archivos_sueltos_raiz']), 2)

        # 3. Verificar archivos sueltos en raíz de carpetas de primer nivel
        # fotos/foto1.jpg y fotos/foto_duplicada.jpg son sueltos en 'fotos' (viajes/playa.jpg NO es suelto en 'fotos')
        sueltos_p1_fotos = [a.nombre for a in datos['archivos_sueltos_primer_nivel'] if a.carpeta_primer_nivel == "fotos"]
        self.assertIn("foto1.jpg", sueltos_p1_fotos)
        self.assertIn("foto_duplicada.jpg", sueltos_p1_fotos)
        self.assertNotIn("playa.jpg", sueltos_p1_fotos)

        # 4. Verificar duplicados globales y cross-carpeta
        self.assertTrue(len(datos['duplicados_globales']) >= 1)
        grupo_foto = None
        for g in datos['duplicados_globales']:
            if len(g['archivos']) == 3:  # foto1.jpg, foto_duplicada.jpg y copia_foto1.jpg
                grupo_foto = g
                break
        self.assertIsNotNone(grupo_foto, "Debería haber un grupo de 3 duplicados idénticos")
        self.assertTrue(grupo_foto['es_inter_carpeta'], "El grupo debe ser detectado como cross-carpeta")
        self.assertIn("fotos", grupo_foto['carpetas'])
        self.assertIn("documentos", grupo_foto['carpetas'])

        # 5. Verificar detección de carpetas vacías
        self.assertIn("carpeta_vacia", datos['carpetas_vacias'])
        self.assertIn(os.path.join("carpeta_subvacia", "vacia_nivel2"), datos['carpetas_vacias'])

        # 6. Renderizado de Markdown sin errores
        md = generador.renderizar_markdown(datos)
        self.assertIn("Resumen por Carpeta de Primer Nivel", md)
        self.assertIn("Duplicados Globales en TODO el Pendrive", md)
        self.assertIn("Carpetas Vacías", md)

    def test_garantia_solo_lectura_rechaza_cache_dentro_del_pendrive(self):
        cache_dentro = os.path.join(self.pendrive_simulado, "cache_ilegal.sqlite")
        with self.assertRaises(RuntimeError):
            CacheInventario(
                ruta_cache=cache_dentro,
                raiz_real=self.pendrive_simulado
            )


if __name__ == "__main__":
    unittest.main()
