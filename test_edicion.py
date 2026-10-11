#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_edicion.py

Pruebas unitarias para el gestor de sesiones de edición, transiciones en pendrive
y copia segura de exports de CapCut (bandeja/edicion.py).
Cumple con la hermeticidad de pruebas y las 7 Reglas de Oro.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from bandeja.config import ConfiguracionBandeja, calcular_sha256
from bandeja.db import GestorBaseDatosBandeja
from bandeja.edicion import (
    calcular_nombre_defecto,
    obtener_secciones_edicion,
    crear_sesion,
    cancelar_sesion,
    finalizar_edicion_crudos,
    deshacer_finalizar_edicion,
    copiar_export_a_videos_completos,
    deshacer_copia_completo,
    vincular_nuevo_export,
    procesar_exports_pendientes_copia,
)


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestEdicionCapCut(unittest.TestCase):
    """Suite de pruebas unitarias para el ciclo de posproducción con CapCut."""

    def setUp(self):
        self.tmp_dir_obj = tempfile.TemporaryDirectory(prefix="test_edicion_")
        self.tmp_dir = self.tmp_dir_obj.name
        self.addCleanup(self.tmp_dir_obj.cleanup)

        # Base de datos temporal
        self.db_path = os.path.join(self.tmp_dir, "test_bandeja.db")
        self.db = GestorBaseDatosBandeja(self.db_path)

        # Pendrive simulado
        self.pendrive_montaje = os.path.join(self.tmp_dir, "pendrive_simulado")
        self.carpeta_raiz = "LucieSinReglas"
        self.pendrive_raiz = os.path.join(self.pendrive_montaje, self.carpeta_raiz)
        os.makedirs(self.pendrive_raiz, exist_ok=True)

        # Bitácora temporal
        self.bitacora_path = os.path.join(self.tmp_dir, "bitacora_test.jsonl")

    def _crear_clip_crudo(self, personaje: str, capitulo: str, nombre_clip: str, contenido: bytes = b"clip_datos") -> str:
        dir_clip = os.path.join(self.pendrive_raiz, "videos sin editar", personaje, capitulo)
        os.makedirs(dir_clip, exist_ok=True)
        ruta_abs = os.path.join(dir_clip, nombre_clip)
        with open(ruta_abs, "wb") as f:
            f.write(contenido)
        return ruta_abs

    def test_calculo_nombre_defecto(self):
        """Verifica la lógica de nombrado para capítulos y clips individuales."""
        # Varios clips -> <capítulo>videocompleto.mp4
        nombre_var = calcular_nombre_defecto(["clip1.mp4", "clip2.mp4"], "capitulo_01")
        self.assertEqual(nombre_var, "capitulo_01videocompleto.mp4")

        # Un solo clip -> <clip>videocompleto.mp4
        nombre_uno = calcular_nombre_defecto(["escena_lucie.mp4"], "capitulo_01")
        self.assertEqual(nombre_uno, "escena_lucievideocompleto.mp4")

        # Nombres con caracteres especiales o espacios
        nombre_esp = calcular_nombre_defecto(["clip 01 (toma 2).mp4"], "capítulo 01!")
        self.assertEqual(nombre_esp, "clip01(toma2)videocompleto.mp4")

    def test_creacion_y_cancelacion_sesiones(self):
        """Verifica la creación y cancelación de sesiones sin alterar archivos en disco."""
        ruta_clip = self._crear_clip_crudo("lucie", "cap01", "clip1.mp4", b"datos")
        rel_clip = "lucie/cap01/clip1.mp4"

        sesion = crear_sesion(
            db=self.db,
            clips=[rel_clip],
            personaje="lucie",
            capitulo="cap01",
        )
        self.assertEqual(sesion["estado"], "en_edicion")
        self.assertEqual(sesion["nombre_final_defecto"], "clip1videocompleto.mp4")
        self.assertTrue(os.path.isfile(ruta_clip))

        # Cancelar sesión
        cancelada = cancelar_sesion(self.db, sesion["id"])
        self.assertTrue(cancelada)

        sesion_actualizada = self.db.obtener_sesion_por_id(sesion["id"])
        self.assertEqual(sesion_actualizada["estado"], "cancelado")
        # El archivo físico permanece intacto
        self.assertTrue(os.path.isfile(ruta_clip))

    def test_inspeccion_tres_secciones_y_contadores(self):
        """Verifica que obtener_secciones_edicion categorice correctamente los archivos."""
        self._crear_clip_crudo("lucie", "cap01", "clip1.mp4", b"datos1")
        self._crear_clip_crudo("lucie", "cap01", "clip2.mp4", b"datos2")
        self._crear_clip_crudo("lucie", "cap02", "clip3.mp4", b"datos3")

        # Crear sesión con clip1
        crear_sesion(
            db=self.db,
            clips=["lucie/cap01/clip1.mp4"],
            personaje="lucie",
            capitulo="cap01",
        )

        secciones = obtener_secciones_edicion(
            self.pendrive_montaje,
            self.db,
            self.carpeta_raiz,
        )

        # 'para_editar' debe contener clip2 y clip3, pero no clip1 (que está en edición)
        nombres_para_editar = [c["nombre"] for c in secciones["para_editar"]]
        self.assertNotIn("clip1.mp4", nombres_para_editar)
        self.assertIn("clip2.mp4", nombres_para_editar)
        self.assertIn("clip3.mp4", nombres_para_editar)

        # 'en_edicion' tiene 1 sesión activa
        self.assertEqual(len(secciones["en_edicion"]), 1)
        self.assertEqual(secciones["en_edicion"][0]["clips"], ["lucie/cap01/clip1.mp4"])

        # 'conteos_capitulo' refleja los estados
        conteos = secciones["conteos_capitulo"]
        self.assertEqual(conteos["cap01"]["sin_editar"], 1)
        self.assertEqual(conteos["cap01"]["en_edicion"], 1)
        self.assertEqual(conteos["cap02"]["sin_editar"], 1)

    def test_finalizar_edicion_crudos_y_deshacer(self):
        """Verifica la transición de crudos a 'videos ya editados' y su reversión."""
        self._crear_clip_crudo("lucie", "cap01", "toma1.mp4", b"datos_toma1")
        rel_clip = "lucie/cap01/toma1.mp4"

        sesion = crear_sesion(self.db, [rel_clip], "lucie", "cap01")

        # 1. Finalizar edición
        res_fin = finalizar_edicion_crudos(
            db=self.db,
            sesion_id=sesion["id"],
            pendrive_montaje=self.pendrive_montaje,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertTrue(res_fin["exito"])
        self.assertEqual(len(res_fin["movidos"]), 1)

        # Comprobar que se movió en disco
        ruta_orig = os.path.join(self.pendrive_raiz, "videos sin editar", "lucie", "cap01", "toma1.mp4")
        ruta_dest = os.path.join(self.pendrive_raiz, "videos ya editados", "lucie", "cap01", "toma1.mp4")
        self.assertFalse(os.path.exists(ruta_orig))
        self.assertTrue(os.path.exists(ruta_dest))

        # Manifiesto y bitácora registrados
        manif_path = os.path.join(self.pendrive_raiz, ".lucie", "manifiesto.jsonl")
        self.assertTrue(os.path.exists(manif_path))
        with open(manif_path, "r", encoding="utf-8") as f:
            lineas = f.readlines()
        self.assertEqual(len(lineas), 1)
        self.assertIn('"tipo_evento": "editado"', lineas[0])

        # 2. Deshacer
        res_desh = deshacer_finalizar_edicion(
            db=self.db,
            sesion_id=sesion["id"],
            pendrive_montaje=self.pendrive_montaje,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertTrue(res_desh["exito"])
        self.assertEqual(len(res_desh["revertidos"]), 1)
        # Comprobar retorno
        self.assertTrue(os.path.exists(ruta_orig))
        self.assertFalse(os.path.exists(ruta_dest))

    def test_conflicto_destino_ocupado_con_distinto_hash(self):
        """Si el destino en 'videos ya editados' existe con distinto hash, no se pisa."""
        self._crear_clip_crudo("lucie", "cap01", "conflicto.mp4", b"contenido_nuevo")
        # Crear en destino un archivo con contenido diferente
        dest_existente = os.path.join(self.pendrive_raiz, "videos ya editados", "lucie", "cap01", "conflicto.mp4")
        os.makedirs(os.path.dirname(dest_existente), exist_ok=True)
        with open(dest_existente, "wb") as f:
            f.write(b"contenido_distinto_preexistente")

        sesion = crear_sesion(self.db, ["lucie/cap01/conflicto.mp4"], "lucie", "cap01")

        res_fin = finalizar_edicion_crudos(
            db=self.db,
            sesion_id=sesion["id"],
            pendrive_montaje=self.pendrive_montaje,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertFalse(res_fin["exito"])
        self.assertEqual(len(res_fin["conflictos"]), 1)
        # El archivo existente en destino NO fue modificado ni borrado
        with open(dest_existente, "rb") as f:
            self.assertEqual(f.read(), b"contenido_distinto_preexistente")

    def test_copia_segura_a_videos_completos_y_deshacer(self):
        """Verifica la copia atómica de export a 'videos completos', verificación sha256 y deshacer."""
        # Crear export simulado en carpeta de CapCut
        capcut_dir = os.path.join(self.tmp_dir, "capcut_exports")
        os.makedirs(capcut_dir, exist_ok=True)
        export_file = os.path.join(capcut_dir, "0818(15).mp4")
        with open(export_file, "wb") as f:
            f.write(b"video_remasterizado_final_capcut")

        sesion = crear_sesion(self.db, ["lucie/cap01/clip1.mp4"], "lucie", "cap01", "cap01videocompleto")

        res_copia = copiar_export_a_videos_completos(
            ruta_origen=export_file,
            sesion=sesion,
            pendrive_montaje=self.pendrive_montaje,
            db=self.db,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertTrue(res_copia["exito"])
        dest_final = res_copia["destino"]
        self.assertTrue(os.path.isfile(dest_final))
        # El hash obtenido coincide con el origen
        self.assertEqual(calcular_sha256(export_file), res_copia["sha256"])

        # Intentar volver a copiar al mismo destino -> FileExistsError (Regla de Oro #1)
        with self.assertRaises(FileExistsError):
            copiar_export_a_videos_completos(
                ruta_origen=export_file,
                sesion=sesion,
                pendrive_montaje=self.pendrive_montaje,
                db=self.db,
                carpeta_raiz=self.carpeta_raiz,
                ruta_bitacora=self.bitacora_path,
            )

        # Deshacer: mueve a _revertidos sin borrar
        res_desh = deshacer_copia_completo(
            video_completo_ruta=dest_final,
            pendrive_montaje=self.pendrive_montaje,
            db=self.db,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertTrue(res_desh["exito"])
        self.assertFalse(os.path.exists(dest_final))
        self.assertTrue(os.path.isfile(res_desh["ruta_revertida"]))
        self.assertIn("_revertidos", res_desh["ruta_revertida"])

    def test_vinculacion_determinista_y_cola_offline(self):
        """Verifica la lógica determinista: 1 sesión -> auto-copia/cola, 0 o >1 sesiones -> sin asignar."""
        capcut_dir = os.path.join(self.tmp_dir, "capcut_exports")
        os.makedirs(capcut_dir, exist_ok=True)
        export_file = os.path.join(capcut_dir, "0818(16).mp4")
        with open(export_file, "wb") as f:
            f.write(b"video_export_offline")

        export_info = {
            "ruta_absoluta": export_file,
            "nombre": "0818(16).mp4",
            "tamano": len(b"video_export_offline"),
            "mtime": 123456.0,
        }

        # Caso 1: 0 sesiones activas -> sin asignar
        res0 = vincular_nuevo_export(
            export_info=export_info,
            pendrive_montaje=self.pendrive_montaje,
            db=self.db,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertFalse(res0["vinculado"])
        self.assertEqual(res0["modo"], "sin_asignar")

        # Caso 2: Exactamente 1 sesión, pero pendrive desconectado (None) -> encolado offline
        s1 = crear_sesion(self.db, ["lucie/cap01/c1.mp4"], "lucie", "cap01")
        res1 = vincular_nuevo_export(
            export_info=export_info,
            pendrive_montaje=None,
            db=self.db,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertTrue(res1["vinculado"])
        self.assertEqual(res1["modo"], "encolado_offline")

        # Al conectar pendrive, procesar cola offline
        res_cola = procesar_exports_pendientes_copia(
            pendrive_montaje=self.pendrive_montaje,
            db=self.db,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertEqual(len(res_cola), 1)
        self.assertTrue(res_cola[0]["exito"])

        # Caso 3: Dos sesiones activas simultáneamente -> sin asignar
        s2 = crear_sesion(self.db, ["lucie/cap02/c2.mp4"], "lucie", "cap02")
        s3 = crear_sesion(self.db, ["lucie/cap03/c3.mp4"], "lucie", "cap03")
        export_file2 = os.path.join(capcut_dir, "0818(17).mp4")
        with open(export_file2, "wb") as f:
            f.write(b"video_export_dos_sesiones")
        export_info2 = {
            "ruta_absoluta": export_file2,
            "nombre": "0818(17).mp4",
            "tamano": len(b"video_export_dos_sesiones"),
            "mtime": 123457.0,
        }
        res2 = vincular_nuevo_export(
            export_info=export_info2,
            pendrive_montaje=self.pendrive_montaje,
            db=self.db,
            carpeta_raiz=self.carpeta_raiz,
            ruta_bitacora=self.bitacora_path,
        )
        self.assertFalse(res2["vinculado"])
        self.assertEqual(res2["modo"], "sin_asignar")

    def test_obtener_secciones_edicion_con_vigilante_registra_media(self):
        """Verifica que obtener_secciones_edicion asigne id_media a los clips cuando vigilante está presente."""
        self._crear_clip_crudo("lucie", "cap01", "clip_vigilante.mp4", b"datos_media")

        class VigilanteMock:
            def __init__(self):
                self.registros = {}

            def registrar_ruta_media(self, ruta_completa: str) -> str:
                import hashlib
                h = hashlib.sha256(ruta_completa.encode("utf-8")).hexdigest()[:16]
                self.registros[h] = ruta_completa
                return h

        mock_v = VigilanteMock()
        secciones = obtener_secciones_edicion(
            self.pendrive_montaje,
            self.db,
            self.carpeta_raiz,
            vigilante=mock_v,
        )

        clips_para_editar = [c for c in secciones["para_editar"] if c["nombre"] == "clip_vigilante.mp4"]
        self.assertEqual(len(clips_para_editar), 1)
        clip = clips_para_editar[0]
        self.assertIn("id_media", clip)
        self.assertIn(clip["id_media"], mock_v.registros)
        self.assertTrue(os.path.isfile(mock_v.registros[clip["id_media"]]))


if __name__ == "__main__":
    unittest.main()
