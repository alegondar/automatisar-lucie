#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_plan_limpieza.py

Suite exhaustiva de pruebas unitarias para plan_limpieza.py y seguridad_anti_borrado.py.
Verifica:
1. Seguridad de solo lectura (rechazo de escrituras dentro del pendrive).
2. Manejo de duplicados inter-carpeta (prioridad videos completos > resto, desempate mtime).
3. Manejo de duplicados intra-carpeta a decidir a mano (sin mover).
4. Diferencias en carpetas sospechosas (>=75% similitud, archivos disjuntos).
5. Clasificación de archivos sueltos por alias (roli, lucie, mailen a confirmar, sin clasificar).
6. Detección de carpetas vacías informativas.
7. Exclusión de carpetas ignoradas (_a_revisar, code, sistema).
8. Huella de integridad y validación pre-ejecución tolerante a FAT (2s mtime).
9. Test de mutación de contenido con mismo tamaño y mtime restaurado con os.utime (debe abortar).
10. Test del analizador AST anti-borrado verificando detección de las 11 primitivas prohibidas.
11. Verificación de código del proyecto 100% limpio de primitivas de borrado.
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime

from plan_limpieza import (
    GeneradorPlanLimpieza,
    ConfiguracionLimpieza,
    AccionPlan,
    cargar_configuracion,
    validar_huella_pre_ejecucion,
    ViolacionSoloLecturaError,
)
from seguridad_anti_borrado import (
    analizar_ast_codigo,
    analizar_ast_archivo,
    auditar_archivos_proyecto,
)


class TestSeguridadAntiBorradoAST(unittest.TestCase):
    """Pruebas del analizador estático AST para las 11 primitivas prohibidas (Reglas de Oro #1 y #7)."""

    def test_analizador_detecta_las_11_primitivas_prohibidas(self):
        casos = [
            ("os.remove('archivo.txt')", "os.remove"),
            ("os.unlink('archivo.txt')", "os.unlink"),
            ("os.rmdir('carpeta')", "os.rmdir"),
            ("os.removedirs('carpeta/sub')", "os.removedirs"),
            ("path_obj.unlink()", "Path.unlink"),
            ("path_obj.rmdir()", "Path.rmdir"),
            ("shutil.rmtree('directorio')", "shutil.rmtree"),
            ("shutil.move('origen', 'destino')", "shutil.move"),
            ("os.replace('origen', 'destino')", "os.replace"),
            ("send2trash('archivo.txt')", "send2trash"),
            ("os.system('rm -rf /tmp/test')", "os.system(rm)"),
            ("subprocess.run(['rm', '-f', 'algo.txt'])", "subprocess(rm)"),
        ]

        for codigo, nombre_esperado in casos:
            with self.subTest(codigo=codigo, esperada=nombre_esperado):
                violaciones = analizar_ast_codigo(codigo, nombre_archivo="test_sample.py")
                self.assertGreaterEqual(
                    len(violaciones), 1,
                    f"El analizador no detectó la primitiva prohibida en: '{codigo}'"
                )
                coincide = any(nombre_esperado in v.primitiva for v in violaciones)
                self.assertTrue(
                    coincide,
                    f"Esperaba detectar '{nombre_esperado}', pero obtuve: {[v.primitiva for v in violaciones]}"
                )

    def test_codigo_operativo_del_proyecto_esta_limpio_de_borrado(self):
        """Verifica que ningún archivo .py operativo del proyecto contenga llamadas de borrado."""
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        archivos_operativos = [
            os.path.join(repo_dir, "plan_limpieza.py"),
            os.path.join(repo_dir, "inventario_pendrive.py"),
            os.path.join(repo_dir, "seguridad_anti_borrado.py"),
        ]
        violaciones = auditar_archivos_proyecto(repo_dir, archivos_a_incluir=archivos_operativos)
        if violaciones:
            mensaje = "\n".join([str(v) for v in violaciones])
            self.fail(f"Se encontraron violaciones de la Regla de Oro anti-borrado en el código operativo:\n{mensaje}")


class TestPlanLimpiezaSimulacion(unittest.TestCase):
    """Pruebas del Generador de Plan de Limpieza sobre un pendrive simulado en /tmp."""

    def setUp(self):
        self.tmp_pendrive = tempfile.mkdtemp(prefix="sim_pendrive_limpieza_")
        self.tmp_repo = tempfile.mkdtemp(prefix="sim_repo_limpieza_")
        self.cache_sqlite = os.path.join(self.tmp_repo, "cache_test.sqlite")

        # Configuración simulada
        self.config = ConfiguracionLimpieza(
            carpetas_ignoradas=["_a_revisar", "code", "System Volume Information", "$RECYCLE.BIN"],
            umbral_similitud_carpetas=0.75,
            prefijo_destino_duplicados="_a_revisar/duplicados",
            prioridad_carpetas_duplicados=["videos completos"],
            criterio_desempate_duplicados="mas_reciente",
            tolerancia_mtime_segundos=2.0,
            reglas_alias=[
                {"patrones": ["roli*", "laroli*", "magui*"], "personaje": "roli", "destino_carpeta": "roli", "requiere_confirmacion": False},
                {"patrones": ["lucie*", "luci*"], "personaje": "lucie", "destino_carpeta": "lucie", "requiere_confirmacion": False},
                {"patrones": ["mailen*"], "personaje": "mailen", "destino_carpeta": "mailen", "requiere_confirmacion": True, "nota": "a confirmar"}
            ]
        )

        # -------------------------------------------------------------
        # Crear estructura simulada en el pendrive:
        # 1. Duplicado inter-carpeta:
        #    - videos completos/clip_promo.mp4 (prioritario)
        #    - videos1/clip_promo_copia.mp4 (secundario -> mover a _a_revisar/duplicados/...)
        # 2. Duplicado intra-carpeta:
        #    - videos completos/intro.mp4
        #    - videos completos/sub_sin_publicar/intro.mp4 (ambos en videos completos -> a mano)
        # 3. Carpetas sospechosas (>=75% similitud):
        #    - laroli/
        #    - videos1/laroli/
        # 4. Archivos sueltos:
        #    - roli_fiesta.mp4 (en raíz -> a roli/)
        #    - lucie_retrato.jpg (en raíz -> a lucie/)
        #    - mailen_saludo.mp4 (en raíz -> a mailen/ a confirmar)
        #    - desconocido_suelto.txt (en raíz -> sin clasificar)
        # 5. Carpeta ignorada:
        #    - code/script.py
        #    - _a_revisar/viejo_dup.mp4
        # 6. Carpeta vacía:
        #    - carpeta_vacia_test/
        # -------------------------------------------------------------

        # 1. Inter-carpeta
        dir_vc = os.path.join(self.tmp_pendrive, "videos completos")
        dir_v1 = os.path.join(self.tmp_pendrive, "videos1")
        os.makedirs(dir_vc, exist_ok=True)
        os.makedirs(dir_v1, exist_ok=True)

        contenido_promo = b"CONTENIDO_VIDEO_PROMO_EXACTO_12345"
        with open(os.path.join(dir_vc, "clip_promo.mp4"), "wb") as f:
            f.write(contenido_promo)
        with open(os.path.join(dir_v1, "clip_promo_copia.mp4"), "wb") as f:
            f.write(contenido_promo)

        # 2. Intra-carpeta
        dir_vc_sub = os.path.join(dir_vc, "sub_sin_publicar")
        os.makedirs(dir_vc_sub, exist_ok=True)
        contenido_intro = b"CONTENIDO_INTRO_CANAL_IDENTICO"
        with open(os.path.join(dir_vc, "intro.mp4"), "wb") as f:
            f.write(contenido_intro)
        with open(os.path.join(dir_vc_sub, "intro.mp4"), "wb") as f:
            f.write(contenido_intro)

        # 3. Carpetas sospechosas (laroli vs videos1/laroli)
        dir_laroli = os.path.join(self.tmp_pendrive, "laroli")
        dir_v1_laroli = os.path.join(dir_v1, "laroli")
        os.makedirs(dir_laroli, exist_ok=True)
        os.makedirs(dir_v1_laroli, exist_ok=True)

        # Archivos compartidos (80%)
        for i in range(4):
            datos = f"DATOS_COMPARTIDOS_LAROLI_{i}".encode("utf-8")
            with open(os.path.join(dir_laroli, f"comun_{i}.mp4"), "wb") as f:
                f.write(datos)
            with open(os.path.join(dir_v1_laroli, f"comun_{i}.mp4"), "wb") as f:
                f.write(datos)

        # Archivo exclusivo de laroli
        with open(os.path.join(dir_laroli, "exclusivo_laroli.mp4"), "wb") as f:
            f.write(b"SOLO_EN_LAROLI_ORIGINAL")

        # Archivo exclusivo de videos1/laroli
        with open(os.path.join(dir_v1_laroli, "exclusivo_v1_laroli.mp4"), "wb") as f:
            f.write(b"SOLO_EN_VIDEOS1_LAROLI")

        # 4. Archivos sueltos en raíz
        with open(os.path.join(self.tmp_pendrive, "roli_fiesta.mp4"), "wb") as f:
            f.write(b"VIDEO_ROLI_SUELTO")
        with open(os.path.join(self.tmp_pendrive, "lucie_retrato.jpg"), "wb") as f:
            f.write(b"FOTO_LUCIE_SUELTA")
        with open(os.path.join(self.tmp_pendrive, "mailen_saludo.mp4"), "wb") as f:
            f.write(b"VIDEO_MAILEN_SUELTO")
        with open(os.path.join(self.tmp_pendrive, "desconocido_suelto.txt"), "wb") as f:
            f.write(b"DOCUMENTO_DESCONOCIDO")

        # 5. Carpetas ignoradas
        dir_code = os.path.join(self.tmp_pendrive, "code")
        dir_cuarentena = os.path.join(self.tmp_pendrive, "_a_revisar")
        os.makedirs(dir_code, exist_ok=True)
        os.makedirs(dir_cuarentena, exist_ok=True)
        with open(os.path.join(dir_code, "script.py"), "w") as f:
            f.write("print('codigo ignorado')")
        with open(os.path.join(dir_cuarentena, "aislado.mp4"), "wb") as f:
            f.write(b"YA_EN_CUARENTENA")

        # 6. Carpeta vacía
        os.makedirs(os.path.join(self.tmp_pendrive, "carpeta_vacia_test"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp_pendrive, ignore_errors=True)
        shutil.rmtree(self.tmp_repo, ignore_errors=True)

    def test_garantia_seguridad_rechaza_salida_en_pendrive(self):
        """Verifica que intentar escribir el plan JSON dentro del pendrive lance excepción."""
        generador = GeneradorPlanLimpieza(
            ruta_raiz=self.tmp_pendrive,
            ruta_cache=self.cache_sqlite,
            config=self.config
        )
        ruta_ilegal = os.path.join(self.tmp_pendrive, "plan_ilegal.json")
        with self.assertRaises(ViolacionSoloLecturaError):
            generador.guardar_json(ruta_ilegal, {"test": 123})

    def test_generacion_plan_completo(self):
        """Genera el plan y verifica las 4 categorías, huella y exclusiones."""
        generador = GeneradorPlanLimpieza(
            ruta_raiz=self.tmp_pendrive,
            ruta_cache=self.cache_sqlite,
            config=self.config
        )
        plan = generador.generar_plan()

        # 1. Verificar exclusión de carpetas ignoradas (code, _a_revisar)
        orígenes = [a["origen"] for a in plan["acciones"]]
        for o in orígenes:
            self.assertFalse(o.startswith("code/"), f"Se encontró archivo de code: {o}")
            self.assertFalse(o.startswith("_a_revisar/"), f"Se encontró archivo de _a_revisar: {o}")

        # 2. Verificar duplicados inter-carpeta: videos completos/clip_promo.mp4 se conserva,
        #    videos1/clip_promo_copia.mp4 se propone mover a _a_revisar/duplicados/videos1/...
        mov_duplicados = [a for a in plan["acciones"] if a["tipo"] == "mover_duplicado"]
        self.assertEqual(len(mov_duplicados), 5)
        origenes_mov = [m["origen"] for m in mov_duplicados]
        self.assertIn("videos1/clip_promo_copia.mp4", origenes_mov)
        promo_action = [m for m in mov_duplicados if m["origen"] == "videos1/clip_promo_copia.mp4"][0]
        self.assertEqual(promo_action["destino"], "_a_revisar/duplicados/videos1/clip_promo_copia.mp4")
        self.assertIn("videos completos/clip_promo.mp4", promo_action["detalles"]["copia_conservada"])

        # 3. Verificar duplicados intra-carpeta a decidir a mano: intro.mp4
        intra_duplicados = [a for a in plan["acciones"] if a["tipo"] == "duplicado_intra_carpeta_manual"]
        self.assertEqual(len(intra_duplicados), 1)
        intra = intra_duplicados[0]
        self.assertIsNone(intra["destino"])
        self.assertIn("decidir a mano", intra["motivo"])
        rutas_intra = [c["ruta_relativa"] for c in intra["detalles"]["copias"]]
        self.assertIn("videos completos/intro.mp4", rutas_intra)
        self.assertIn("videos completos/sub_sin_publicar/intro.mp4", rutas_intra)

        # 4. Verificar carpetas sospechosas (laroli vs videos1/laroli)
        diferencias = [a for a in plan["acciones"] if a["tipo"] == "diferencia_carpeta_sospechosa"]
        self.assertEqual(len(diferencias), 2)
        orígenes_dif = [d["origen"] for d in diferencias]
        self.assertIn("laroli/exclusivo_laroli.mp4", orígenes_dif)
        self.assertIn("videos1/laroli/exclusivo_v1_laroli.mp4", orígenes_dif)
        for d in diferencias:
            self.assertIsNone(d["destino"])
            self.assertEqual(sorted(d["detalles"]["par"]), ["laroli", "videos1/laroli"])

        # 5. Verificar clasificación de sueltos por alias
        sueltos_mover = {a["origen"]: a for a in plan["acciones"] if a["tipo"] == "mover_suelto"}
        self.assertIn("roli_fiesta.mp4", sueltos_mover)
        self.assertEqual(sueltos_mover["roli_fiesta.mp4"]["destino"], "roli/roli_fiesta.mp4")
        
        self.assertIn("lucie_retrato.jpg", sueltos_mover)
        self.assertEqual(sueltos_mover["lucie_retrato.jpg"]["destino"], "lucie/lucie_retrato.jpg")

        self.assertIn("mailen_saludo.mp4", sueltos_mover)
        self.assertEqual(sueltos_mover["mailen_saludo.mp4"]["destino"], "mailen/mailen_saludo.mp4")
        self.assertTrue(sueltos_mover["mailen_saludo.mp4"]["detalles"]["requiere_confirmacion"])

        # Suelto sin clasificar
        sueltos_sin = [a for a in plan["acciones"] if a["tipo"] == "suelto_sin_clasificar"]
        origenes_sin = [a["origen"] for a in sueltos_sin]
        self.assertIn("desconocido_suelto.txt", origenes_sin)
        self.assertEqual(len(sueltos_sin), 4)
        for s in sueltos_sin:
            self.assertIsNone(s["destino"])

        # 6. Carpeta vacía
        vacias = [a for a in plan["acciones"] if a["tipo"] == "carpeta_vacia"]
        self.assertIn("carpeta_vacia_test", [v["origen"] for v in vacias])

        # 7. Renderizado Markdown y JSON
        json_path = os.path.join(self.tmp_repo, "plan_limpieza.json")
        md_path = os.path.join(self.tmp_repo, "plan_limpieza.md")
        generador.guardar_json(json_path, plan)
        md_text = generador.renderizar_markdown(plan)
        generador.guardar_markdown(md_path, md_text)

        self.assertTrue(os.path.exists(json_path))
        self.assertTrue(os.path.exists(md_path))
        self.assertIn("Plan de Limpieza del Pendrive (Modo Simulación)", md_text)
        self.assertIn("Duplicados Intra-Carpeta (A Decidir a Mano)", md_text)

        # 8. Validación de huella pre-ejecución exitosa
        valido, errores = validar_huella_pre_ejecucion(self.tmp_pendrive, plan)
        self.assertTrue(valido, f"La huella debería ser válida pero falló con: {errores}")

    def test_validacion_huella_aborta_si_se_modifica_contenido_con_mismo_tamanio_y_mtime(self):
        """
        Prueba crítica: Modificar el contenido de un archivo candidato a mover, preservando
        su tamaño exacto en bytes y restaurando su mtime original con os.utime.
        El validador pre-ejecución DEBE recalcular el SHA-256 leyendo el archivo físico real
        y abortar con error.
        """
        generador = GeneradorPlanLimpieza(
            ruta_raiz=self.tmp_pendrive,
            ruta_cache=self.cache_sqlite,
            config=self.config
        )
        plan = generador.generar_plan()

        # Localizar el archivo candidato a mover (videos1/clip_promo_copia.mp4)
        rel_path = "videos1/clip_promo_copia.mp4"
        abs_path = os.path.join(self.tmp_pendrive, rel_path)

        stat_original = os.stat(abs_path)
        tamanio_original = stat_original.st_size
        mtime_original = stat_original.st_mtime
        atime_original = stat_original.st_atime

        # Crear contenido mutado con la misma longitud exacta
        contenido_mutado = b"X" * tamanio_original
        with open(abs_path, "wb") as f:
            f.write(contenido_mutado)

        # Restaurar deliberadamente los timestamps originales con os.utime
        os.utime(abs_path, (atime_original, mtime_original))

        # Verificar que el tamaño y el mtime son idénticos
        stat_mutado = os.stat(abs_path)
        self.assertEqual(stat_mutado.st_size, tamanio_original)
        self.assertAlmostEqual(stat_mutado.st_mtime, mtime_original, delta=0.01)

        # Ejecutar la validación pre-ejecución
        valido, errores = validar_huella_pre_ejecucion(self.tmp_pendrive, plan)
        
        self.assertFalse(valido, "La validación pre-ejecución debió ABORTAR ante cambio de hash real")
        self.assertTrue(
            any("Discrepancia de hash SHA-256" in err for err in errores),
            f"Se esperaba error de discrepancia de hash SHA-256, se obtuvo: {errores}"
        )


if __name__ == "__main__":
    unittest.main()
