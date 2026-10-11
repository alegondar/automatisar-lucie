#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_compatibilidad_windows.py

Suite de pruebas para compatibilidad multiplataforma y emulación de Windows 10/11:
1. Confinamiento case-insensitive y canónico (esta_confinado_en_raiz)
2. Ruta en otra unidad o ruta UNC externa rechazada
3. Nombres reservados de Windows (CON, PRN, etc.) y caracteres prohibidos
4. UTF-8 explícito en bitácora y manifiesto con acentos y emojis
5. Exclusividad de socket (SO_EXCLUSIVEADDRUSE en Windows)
6. Fecha de llegada efectiva con st_birthtime sin DeprecationWarning
7. Normalización de separadores '/' en rutas relativas de manifiesto y bitácora
8. Simulación de archivos bloqueados (PermissionError / WinError 32) en vigilante y movimientos
9. Tolerancia ante la ausencia de notify-send
10. Detección de pendrive en Windows con unidades simuladas
11. Tolerancia ante la ausencia de os.sync y rechazo de udisksctl en Windows
12. Servicio multimedia /api/media con Range HTTP y rutas compatibles
13. Autodetección de descargas por equipo y creación exclusiva 'xb' de config_bandeja.local.json
14. Decoradores unittest.skipUnless para ramas exclusivas de cada sistema operativo
"""

import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch

from bandeja.config import (
    ConfiguracionBandeja,
    NOMBRES_RESERVADOS_WINDOWS,
    CARACTERES_INVALIDOS_ESCENA,
)
from bandeja.clasificacion import ValidadorEscenas, FiltroListaBlanca
from bandeja.plataforma import (
    obtener_ruta_descargas_windows,
    obtener_ruta_descargas_defecto,
    esta_confinado_en_raiz,
    validar_longitud_ruta,
    obtener_sistema_archivos,
    obtener_sistema_archivos_windows,
    obtener_unidades_windows,
    notificar_escritorio,
    normalizar_ruta_relativa_posix,
    convertir_ruta_relativa_a_local,
    verificar_archivo_exclusivo,
)
from bandeja.lotes import (
    obtener_fecha_llegada,
    DetectorDescargasActivas,
    AgrupadorLotes,
)
from bandeja.movimientos import GestorMovimientosBandeja
from bandeja.pendrive import (
    detectar_pendrive,
    leer_manifiesto_pendrive,
    montar_unidad_pendrive,
    desmontar_unidad_pendrive,
)
from bandeja.servidor import (
    HandlerServidorBandeja,
    ServidorBandejaHTTPServer,
    crear_servidor,
    GeneradorMiniaturas,
)
from bandeja.db import GestorBaseDatosBandeja


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestConfiguracionLocalWindows(unittest.TestCase):
    """Pruebas de configuración por equipo y autodetección de descargas."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ruta_base = os.path.join(self.temp_dir.name, "config_bandeja.json")
        self.ruta_local = os.path.join(self.temp_dir.name, "config_bandeja.local.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_carga_config_base_sin_local(self):
        with open(self.ruta_base, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"puerto_servidor": 9000}, f)

        cfg = ConfiguracionBandeja(ruta_config=self.ruta_base, ruta_config_local=self.ruta_local)
        self.assertEqual(cfg.puerto_servidor, 9000)

    def test_config_local_sobrescribe_base(self):
        with open(self.ruta_base, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"puerto_servidor": 9000, "host_servidor": "127.0.0.1"}, f)
        with open(self.ruta_local, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"puerto_servidor": 9555}, f)

        cfg = ConfiguracionBandeja(ruta_config=self.ruta_base, ruta_config_local=self.ruta_local)
        self.assertEqual(cfg.puerto_servidor, 9555)
        self.assertEqual(cfg.host_servidor, "127.0.0.1")

    def test_ruta_descargas_auto_resuelve_descargas(self):
        with open(self.ruta_base, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"ruta_descargas": "auto"}, f)

        cfg = ConfiguracionBandeja(ruta_config=self.ruta_base, ruta_config_local=self.ruta_local)
        self.assertTrue(os.path.isabs(cfg.ruta_descargas))
        self.assertTrue(cfg.ruta_destino_base.startswith(cfg.ruta_descargas))

    def test_creacion_exclusiva_config_local_en_windows(self):
        with open(self.ruta_base, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"puerto_servidor": 8766}, f)

        with mock.patch("os.name", "nt"):
            cfg = ConfiguracionBandeja(ruta_config=self.ruta_base, ruta_config_local=self.ruta_local)
            self.assertTrue(os.path.exists(self.ruta_local))
            with open(self.ruta_local, "r", encoding="utf-8", newline="\n") as f:
                datos = json.load(f)
            self.assertEqual(datos.get("ruta_descargas"), "auto")

    def test_obtener_ruta_descargas_windows_fallback(self):
        with mock.patch.dict(os.environ, {"USERPROFILE": self.temp_dir.name}):
            with mock.patch("ctypes.windll", create=True, new=None):
                res = obtener_ruta_descargas_windows()
                esperada = os.path.join(self.temp_dir.name, "Downloads")
                self.assertEqual(res, esperada)


class TestConfinamientoYValidacionRutas(unittest.TestCase):
    """Pruebas de confinamiento canónico, case-insensitive y nombres de archivo."""

    def test_confinamiento_normcase_mismo_directorio(self):
        # En Windows o bajo normcase, la mayúscula/minúscula no escapa del directorio
        with tempfile.TemporaryDirectory() as tmp:
            archivo = os.path.join(tmp, "SubCarpeta", "Archivo.mp4")
            raiz = os.path.join(tmp, "subcarpeta")
            # Simular normcase
            self.assertTrue(esta_confinado_en_raiz(archivo.lower(), raiz.lower()))

    def test_confinamiento_rechaza_otra_unidad_o_unc(self):
        # Letra de unidad distinta en POSIX o Windows se rechaza
        self.assertFalse(esta_confinado_en_raiz("D:\\descargas\\video.mp4", "C:\\descargas"))
        self.assertFalse(esta_confinado_en_raiz("\\\\servidor\\compartido\\video.mp4", "C:\\descargas"))
        # En Linux, un path Windows contra una raíz POSIX se rechaza
        self.assertFalse(esta_confinado_en_raiz("C:\\Windows\\System32", "/home/usuario/descargas"))

    def test_validar_longitud_max_path(self):
        ruta_corta = "C:\\descargas\\video.mp4"
        ruta_larga = "C:\\" + ("sub\\" * 70) + "video.mp4"
        self.assertTrue(validar_longitud_ruta(ruta_corta, max_longitud=260))
        self.assertFalse(validar_longitud_ruta(ruta_larga, max_longitud=260))

    def test_nombres_reservados_windows_rechazados(self):
        validador = ValidadorEscenas()
        base = "/tmp/base"
        for reservado in ["CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"]:
            valido, _ = validador.validar_nombre_escena(reservado, base, base)
            self.assertFalse(valido, f"El nombre reservado '{reservado}' debió ser rechazado.")
            valido_min, _ = validador.validar_nombre_escena(reservado.lower(), base, base)
            self.assertFalse(valido_min, f"El nombre reservado '{reservado.lower()}' debió ser rechazado.")

    def test_caracteres_invalidos_y_terminaciones_punto_espacio(self):
        validador = ValidadorEscenas()
        base = "/tmp/base"
        for invalido in ["escena<1>", 'escena"2"', "escena:3", "escena|4", "escena?5", "escena*6"]:
            valido, _ = validador.validar_nombre_escena(invalido, base, base)
            self.assertFalse(valido, f"El nombre '{invalido}' debió ser rechazado por caracteres inválidos.")

        for final_invalido in ["escena.", "escena ", "escena..", "escena   "]:
            valido, _ = validador.validar_nombre_escena(final_invalido, base, base)
            self.assertFalse(valido, f"El nombre '{final_invalido}' debió ser rechazado por terminar en punto o espacio.")

    def test_validador_escenas_exhaustivo_caracteres_control_y_reservados(self):
        validador = ValidadorEscenas()
        base = "/tmp/base"
        desc = "/tmp/desc"

        # 1. Caracteres prohibidos en todos los sistemas: < > : " / \ | ? *
        for car in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
            valido, msg = validador.validar_nombre_escena(f"escena{car}test", base, desc)
            self.assertFalse(valido, f"El caracter '{car}' debió ser rechazado.")

        # 2. Caracteres de control (0-31 y 127)
        for ctrl_code in [0, 1, 9, 10, 13, 27, 31, 127]:
            ctrl_char = chr(ctrl_code)
            valido, msg = validador.validar_nombre_escena(f"escena{ctrl_char}test", base, desc)
            self.assertFalse(valido, f"El caracter de control {ctrl_code} debió ser rechazado.")

        # 3. Nombres terminados en punto o espacio
        for sufijo in [".", " ", "..", "   ", " . "]:
            valido, msg = validador.validar_nombre_escena(f"escena{sufijo}", base, desc)
            self.assertFalse(valido, f"El sufijo '{sufijo}' debió ser rechazado.")

        # 4. Nombres reservados de Windows/exFAT y con extensiones
        for res in ["CON", "PRN", "AUX", "NUL", "COM1", "COM5", "COM9", "LPT1", "LPT9"]:
            valido, msg = validador.validar_nombre_escena(res, base, desc)
            self.assertFalse(valido, f"El nombre reservado '{res}' debió ser rechazado.")
            valido_ext, msg_ext = validador.validar_nombre_escena(f"{res}.mp4", base, desc)
            self.assertFalse(valido_ext, f"El nombre reservado con extensión '{res}.mp4' debió ser rechazado.")

    def test_normalizacion_ruta_relativa_simulada_con_backslashes(self):
        # Simula rutas con backslashes típicas de Windows y comprueba la normalización a '/'
        ruta_win = r"videos sin editar\lucie\capitulo_01\toma_01.mp4"
        norm = normalizar_ruta_relativa_posix(ruta_win)
        self.assertEqual(norm, "videos sin editar/lucie/capitulo_01/toma_01.mp4")
        self.assertNotIn("\\", norm)

        # Conversión segura a local según el SO
        local_p = convertir_ruta_relativa_a_local(norm)
        partes = ["videos sin editar", "lucie", "capitulo_01", "toma_01.mp4"]
        self.assertEqual(local_p, os.path.join(*partes))

        # Traversal relativo neutralizado
        ruta_traversal = r"..\..\videos\peligro.mp4"
        norm_traversal = normalizar_ruta_relativa_posix(ruta_traversal)
        local_traversal = convertir_ruta_relativa_a_local(norm_traversal)
        self.assertNotIn("..", local_traversal)

    def test_simular_descartar_capitulo_confinamiento(self):
        from bandeja.capitulos import simular_descartar_capitulo
        with tempfile.TemporaryDirectory() as tmp:
            dest_base = os.path.join(tmp, "descargas", "_lucie")
            desc = os.path.join(tmp, "descargas")
            os.makedirs(dest_base, exist_ok=True)
            db = GestorBaseDatosBandeja(os.path.join(tmp, "db.sqlite"))
            cap = db.empezar_capitulo("lucie", "capitulo_seguro")
            cap_id = cap["id"]

            carp_cap = os.path.join(dest_base, "lucie", "capitulo_seguro")
            os.makedirs(carp_cap, exist_ok=True)
            f_valido = os.path.join(carp_cap, "video.mp4")
            with open(f_valido, "wb") as f:
                f.write(b"video")

            res = simular_descartar_capitulo(db, dest_base, desc, cap_id)
            self.assertTrue(res["valido"])


class TestCodificacionYNormalizacionNFC(unittest.TestCase):
    """Pruebas de codificación UTF-8, saltos de línea LF y normalización Unicode NFC."""

    def test_persistencia_bitacora_con_tildes_y_emojis(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_bit = os.path.join(tmp, "bitacora.jsonl")
            evento = {
                "evento": "clasificar",
                "capitulo": "escena_niños_y_acción_🎬",
                "archivo": "clip_canción.mp4"
            }
            with open(ruta_bit, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(evento, ensure_ascii=False) + "\n")

            with open(ruta_bit, "r", encoding="utf-8", newline="\n") as f:
                linea = f.readline().strip()
                datos = json.loads(linea)

            self.assertEqual(datos["capitulo"], "escena_niños_y_acción_🎬")
            self.assertEqual(datos["archivo"], "clip_canción.mp4")

    def test_normalizacion_nfc_en_validador_escenas(self):
        import unicodedata
        # 'niño' en NFD (n + i + n + ~ + o) vs NFC (n + i + ñ + o)
        nombre_nfd = unicodedata.normalize("NFD", "niño_baile")
        nombre_nfc = unicodedata.normalize("NFC", "niño_baile")
        self.assertNotEqual(len(nombre_nfd), len(nombre_nfc))

        validador = ValidadorEscenas()
        valido, _ = validador.validar_nombre_escena(nombre_nfd, "/tmp/base", "/tmp/base")
        self.assertTrue(valido)


class TestFechasYArchivosBloqueados(unittest.TestCase):
    """Pruebas de st_birthtime vs st_ctime y tolerancia a archivos bloqueados."""

    def test_obtener_fecha_llegada_con_st_birthtime(self):
        class StatMock:
            st_mtime = 1700000000.0
            st_birthtime = 1700005000.0
            # st_ctime intencionalmente ausente o deprecado

        st = StatMock()
        fecha = obtener_fecha_llegada(st)
        self.assertEqual(fecha, 1700005000.0)

    def test_detector_estabilidad_captura_permission_error(self):
        detector = DetectorDescargasActivas()
        with patch("os.stat", side_effect=PermissionError(13, "Permission denied (locked)")):
            es_estable = detector.es_archivo_estable("/ruta/archivo_descargandose.mp4")
            self.assertFalse(es_estable)

    def test_movimiento_reporta_archivo_en_uso_sin_tirar_proceso(self):
        with tempfile.TemporaryDirectory() as tmp:
            desc = os.path.join(tmp, "desc")
            dest = os.path.join(desc, "_lucie")
            os.makedirs(desc, exist_ok=True)
            os.makedirs(dest, exist_ok=True)
            f_orig = os.path.join(desc, "archivo.mp4")
            with open(f_orig, "wb") as f:
                f.write(b"video_bytes")

            db = GestorBaseDatosBandeja(os.path.join(tmp, "db.sqlite"))
            gestor = GestorMovimientosBandeja(desc, dest, db, ruta_bitacora=os.path.join(tmp, "bitacora.jsonl"))

            sim = gestor.simular_movimiento_lote(
                [{"ruta": f_orig, "tamanio": 11, "mtime": 1000.0, "fecha": "2026-10-08", "tipo": "video"}],
                "lucie", "escena1"
            )
            with patch("os.rename", side_effect=PermissionError(13, "The process cannot access the file")):
                res = gestor.ejecutar_movimiento_lote(sim, "lote_1")
                self.assertEqual(res["total_movidos"], 0)
                self.assertEqual(len(res["archivos_en_uso"]), 1)
                self.assertIn("en uso", res.get("mensaje_aviso", "").lower())


class TestPlataformaYDeteccionPendriveWindows(unittest.TestCase):
    """Pruebas de detección de pendrive con ctypes en Windows y tolerancia POSIX."""

    def test_notificar_escritorio_sin_notify_send_no_falla(self):
        with patch("shutil.which", return_value=None):
            # No debe lanzar ninguna excepción
            notificar_escritorio("Titulo", "Mensaje")

    def test_desmontar_unidad_en_windows_retorna_no_soportado(self):
        with patch("os.name", "nt"):
            res = desmontar_unidad_pendrive("E:")
            self.assertFalse(res["exito"])
            self.assertTrue(res["no_soportado"])

    def test_montar_unidad_en_windows_retorna_no_soportado(self):
        with patch("os.name", "nt"):
            res = montar_unidad_pendrive("E:")
            self.assertFalse(res["exito"])
            self.assertTrue(res["no_soportado"])

    def test_desmontar_unidad_sin_os_sync_no_lanza_attribute_error(self):
        with patch("os.name", "posix"):
            with patch("bandeja.pendrive.detectar_particiones_removibles_linux", return_value=[{"dispositivo": "/dev/sdb1", "nodo": "sdb1", "punto_montaje": "/media/usb"}]):
                with patch("subprocess.run") as mock_subp:
                    mock_subp.return_value = MagicMock(returncode=0, stdout="Unmounted")
                    # Simular entorno sin os.sync
                    with patch.object(os, "sync", create=False) if hasattr(os, "sync") else mock.MagicMock():
                        if hasattr(os, "sync"):
                            delattr(os, "sync")
                        try:
                            res = desmontar_unidad_pendrive("/dev/sdb1")
                            self.assertTrue(res["exito"])
                        finally:
                            # Restaurar si existía
                            pass

    def test_detectar_pendrive_en_windows_con_unidades_mock(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Crear estructura de pendrive simulada
            marcador_data = {
                "id": "12345678-1234-4234-8234-123456789abc",
                "creado": "2026-10-08T00:00:00",
                "version": 1
            }
            with open(os.path.join(tmp, ".lucie_pendrive.json"), "w", encoding="utf-8", newline="\n") as f:
                json.dump(marcador_data, f)

            unidades_mock = [{"letra": "E", "unidad": tmp, "tipo": "removible", "tipo_codigo": 2}]

            with patch("bandeja.plataforma.obtener_unidades_windows", return_value=unidades_mock):
                with patch("bandeja.pendrive.obtener_sistema_archivos", return_value="exfat"):
                    with patch("os.name", "nt"):
                        pen = detectar_pendrive()
                        self.assertIsNotNone(pen)
                        self.assertEqual(pen["id"], "12345678-1234-4234-8234-123456789abc")
                        self.assertEqual(pen["sistema_archivos"], "exfat")


class TestServidorHTTPYExclusividad(unittest.TestCase):
    """Pruebas de socket exclusivo y servicio multimedia."""

    def test_servidor_exclusividad_bind_en_windows(self):
        # Verificar que en Windows se aplica SO_EXCLUSIVEADDRUSE
        with patch("os.name", "nt"):
            server = ServidorBandejaHTTPServer.__new__(ServidorBandejaHTTPServer)
            server.socket = MagicMock()
            server.server_address = ("127.0.0.1", 8766)
            with patch("socket.socket.setsockopt") as mock_opt:
                with patch("http.server.ThreadingHTTPServer.server_bind"):
                    server.server_bind()
                    self.assertFalse(server.allow_reuse_address)
                    self.assertTrue(server.socket.setsockopt.called)

    def test_servicio_media_con_soporte_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_video = os.path.join(tmp, "video_test.mp4")
            with open(ruta_video, "wb") as f:
                f.write(b"0123456789ABCDEF")

            cfg = ConfiguracionBandeja()
            cfg.ruta_descargas = tmp
            cfg.ruta_destino_base = tmp
            cfg.puerto_servidor = 0

            class MockVig:
                def resolver_ruta_media(self, m_id):
                    return ruta_video if m_id == "v1" else None

            class CustomHandler(HandlerServidorBandeja):
                pass

            CustomHandler.config = cfg
            CustomHandler.db = None
            CustomHandler.movimientos = None
            CustomHandler.vigilante = MockVig()
            CustomHandler.miniaturas = None
            CustomHandler.token_csrf = "csrf_test"

            srv = ServidorBandejaHTTPServer(("127.0.0.1", 0), CustomHandler)
            puerto = srv.server_address[1]
            cfg.puerto_servidor = puerto

            hilo = threading.Thread(target=srv.serve_forever, daemon=True)
            hilo.start()

            try:
                conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=3.0)
                conn.request("GET", "/api/media?id=v1", headers={"Range": "bytes=0-3"})
                resp = conn.getresponse()
                cuerpo = resp.read()
                conn.close()

                self.assertEqual(resp.status, 206)
                self.assertEqual(cuerpo, b"0123")
                self.assertIn("bytes 0-3/16", resp.getheader("Content-Range", ""))
            finally:
                srv.shutdown()
                srv.server_close()

    def test_instancia_unica_linux_puerto_ocupado_sale_limpio(self):
        import io
        import bandeja_descargas

        # Ocupar un puerto temporal
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        puerto = sock.getsockname()[1]

        stdout_capturado = io.StringIO()
        stderr_capturado = io.StringIO()
        try:
            with patch("sys.argv", ["bandeja_descargas.py", "--puerto", str(puerto)]):
                with patch("sys.stdout", stdout_capturado):
                    with patch("sys.stderr", stderr_capturado):
                        with self.assertRaises(SystemExit) as cm:
                            bandeja_descargas.main()
                        self.assertEqual(cm.exception.code, 0)
            salida = stdout_capturado.getvalue()
            self.assertIn(f"Ya hay una bandeja corriendo en el puerto {puerto}", salida)
        finally:
            sock.close()

    def test_instancia_unica_windows_puerto_ocupado_sale_limpio(self):
        import io
        import bandeja_descargas

        stdout_capturado = io.StringIO()
        stderr_capturado = io.StringIO()
        with patch("bandeja_descargas.crear_servidor", side_effect=OSError(10048, "Only one usage of each socket address is normally permitted")):
            with patch("sys.argv", ["bandeja_descargas.py", "--puerto", "8766"]):
                with patch("sys.stdout", stdout_capturado):
                    with patch("sys.stderr", stderr_capturado):
                        with self.assertRaises(SystemExit) as cm:
                            bandeja_descargas.main()
                        self.assertEqual(cm.exception.code, 0)
            salida = stdout_capturado.getvalue()
            self.assertIn("Ya hay una bandeja corriendo en el puerto 8766", salida)



class TestPlataformaExclusivaSO(unittest.TestCase):
    """Pruebas condicionadas con unittest.skipUnless para ramas exclusivas de cada SO."""

    @unittest.skipUnless(os.name == "nt", "Prueba exclusiva para entorno Windows nativo")
    def test_nativa_windows_socket_exclusive(self):
        # Se ejecuta únicamente si el host real es Windows
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        so_excl = getattr(socket, "SO_EXCLUSIVEADDRUSE", -5)
        sock.setsockopt(socket.SOL_SOCKET, so_excl, 1)
        sock.bind(("127.0.0.1", 0))
        sock.close()

    @unittest.skipUnless(os.name == "nt", "Prueba exclusiva para entorno Windows nativo")
    def test_verificar_archivo_exclusivo_windows(self):
        """Verifica que verificar_archivo_exclusivo detecte archivo en uso mientras otro manejador lo tiene abierto para escritura."""
        import msvcrt

        with tempfile.TemporaryDirectory() as tmp_dir:
            ruta = os.path.join(tmp_dir, "archivo_test_exclusivo.mp4")
            with open(ruta, "wb") as f:
                f.write(b"datos de prueba para bloqueo exclusivo")

            h = open(ruta, "r+b")
            try:
                msvcrt.locking(h.fileno(), msvcrt.LK_NBLCK, 1)
                self.assertFalse(
                    verificar_archivo_exclusivo(ruta),
                    f"El archivo '{ruta}' debe indicar 'en uso' (False) mientras otro manejador lo tiene abierto para escritura",
                )
            finally:
                try:
                    msvcrt.locking(h.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
                h.close()

            self.assertTrue(
                verificar_archivo_exclusivo(ruta),
                f"El archivo '{ruta}' debe indicar libre (True) una vez que el manejador se cierra",
            )

    @unittest.skipUnless(os.name == "posix", "Prueba exclusiva para entorno Linux / POSIX")
    def test_nativa_linux_proc_mounts_existencia(self):
        # Se ejecuta únicamente si el host real es Linux / POSIX
        self.assertTrue(os.path.exists("/proc/mounts") or os.path.exists("/proc"))


if __name__ == "__main__":
    unittest.main()
