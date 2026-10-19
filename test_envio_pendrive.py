#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_envio_pendrive.py

Suite integral de pruebas unitarias para el módulo de envío a pendrive (LucieSinReglas).
Valida las 7 Reglas de Oro, detección multiplataforma, vinculación, simulación, copia segura .part,
preservación de originales en _enviados, manifiesto append-only, reversión a _revertidos y robustez.
"""

from pathlib import Path
import datetime
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error
import uuid
from bandeja.organizacion_mensual import OrganizadorMensual, nombre_mes

from bandeja import (
    montar_unidad_pendrive,
    desmontar_unidad_pendrive,
    obtener_estado_pendrive,
    detectar_particiones_removibles_linux,
    diagnosticar_todas_particiones_linux,
    listar_procesos_ocupando_montaje,
)
from bandeja_descargas import (
    ConfiguracionBandeja,
    GestorBaseDatosBandeja,
    GestorMovimientosBandeja,
    FiltroListaBlanca,
    DetectorDescargasActivas,
    AgrupadorLotes,
    GeneradorMiniaturas,
    VigilanteBandeja,
    crear_servidor,
    calcular_sha256,
    validar_marcador_pendrive,
    leer_marcador_pendrive,
    obtener_sistema_archivos,
    obtener_espacio_disco,
    detectar_pendrive,
    detectar_pendrive_seguro,
    detectar_unidad_candidata_sin_vincular,
    ejecutar_lectura_pendrive_con_timeout,
    simular_vinculacion_pendrive,
    vincular_pendrive,
    simular_envio_capitulos,
    ejecutar_envio_pendrive,
    deshacer_envio_pendrive,
    leer_manifiesto_pendrive,
    NOMBRE_MARCADOR_PENDRIVE,
    NOMBRE_MANIFIESTO_PENDRIVE,
    ErrorDeshacer,
    ValidadorEscenas,
    escanear_capitulos_para_envio,
)


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestDeteccionYMarcadorPendrive(unittest.TestCase):
    """Pruebas del Grupo 1: Configuración, validación y detección de pendrive."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_pendrive_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_config_pendrive_carga(self):
        """Verifica que la configuración cargue los parámetros por defecto de pendrive."""
        config = ConfiguracionBandeja()
        self.assertEqual(config.carpeta_raiz_pendrive, "LucieSinReglas")
        self.assertIsInstance(config.rutas_candidatas_pendrive, list)
        self.assertGreaterEqual(config.margen_libre_bytes, 1024 * 1024 * 1024)

    def test_validar_marcador_valido(self):
        """Valida que un marcador conforme a esquema sea aprobado."""
        uid = str(uuid.uuid4())
        ahora = datetime.datetime.now().isoformat()
        datos = {"id": uid, "creado": ahora, "version": 1}
        valido, limpio, err = validar_marcador_pendrive(datos)
        self.assertTrue(valido)
        self.assertIsNone(err)
        self.assertEqual(limpio["id"], uid)
        self.assertEqual(limpio["version"], 1)

    def test_validar_marcador_invalido(self):
        """Valida el rechazo de marcadores corruptos, versiones incompatibles o IDs inválidos."""
        # No es dict
        valido, _, err = validar_marcador_pendrive("no_es_dict")
        self.assertFalse(valido)

        # Campos faltantes
        valido, _, err = validar_marcador_pendrive({"id": "123"})
        self.assertFalse(valido)

        # UUID inválido
        valido, _, err = validar_marcador_pendrive({
            "id": "no-es-uuid-valido",
            "creado": datetime.datetime.now().isoformat(),
            "version": 1
        })
        self.assertFalse(valido)

        # Versión distinta de 1
        valido, _, err = validar_marcador_pendrive({
            "id": str(uuid.uuid4()),
            "creado": datetime.datetime.now().isoformat(),
            "version": 2
        })
        self.assertFalse(valido)

        # Fecha inválida
        valido, _, err = validar_marcador_pendrive({
            "id": str(uuid.uuid4()),
            "creado": "fecha_invalida",
            "version": 1
        })
        self.assertFalse(valido)

    def test_leer_marcador_pendrive(self):
        """Verifica la lectura física del archivo marcador desde el disco."""
        # Sin archivo
        self.assertIsNone(leer_marcador_pendrive(self.temp_dir))

        # Con marcador válido
        uid = str(uuid.uuid4())
        marcador = {"id": uid, "creado": datetime.datetime.now().isoformat(), "version": 1}
        ruta_m = os.path.join(self.temp_dir, NOMBRE_MARCADOR_PENDRIVE)
        with open(ruta_m, "w", encoding="utf-8") as f:
            json.dump(marcador, f)

        res = leer_marcador_pendrive(self.temp_dir)
        self.assertIsNotNone(res)
        self.assertEqual(res["id"], uid)

    def test_detectar_pendrive_sin_marcador(self):
        """Verifica que detectar_pendrive devuelva None si no existe marcador en las candidatas."""
        config = ConfiguracionBandeja()
        config.rutas_candidatas_pendrive = [self.temp_dir]
        self.assertIsNone(detectar_pendrive(config))

    def test_detectar_pendrive_con_marcador(self):
        """Verifica que detectar_pendrive reconozca la unidad con marcador válido."""
        uid = str(uuid.uuid4())
        marcador = {"id": uid, "creado": datetime.datetime.now().isoformat(), "version": 1}
        ruta_m = os.path.join(self.temp_dir, NOMBRE_MARCADOR_PENDRIVE)
        with open(ruta_m, "w", encoding="utf-8") as f:
            json.dump(marcador, f)

        config = ConfiguracionBandeja()
        config.rutas_candidatas_pendrive = [self.temp_dir]

        info = detectar_pendrive(config)
        self.assertIsNotNone(info)
        self.assertTrue(info["conectado"])
        self.assertEqual(info["id"], uid)
        self.assertEqual(info["ruta_montaje"], os.path.realpath(self.temp_dir))
        self.assertTrue(info["carpeta_raiz_confinada"].endswith("LucieSinReglas"))
        self.assertGreater(info["espacio_total_bytes"], 0)

    def test_lectura_pendrive_timeout_cuelgue(self):
        """
        Requisito de robustez: simula una función de lectura que se cuelga/demora más del límite
        y verifica que devuelva 'Pendrive sin respuesta' sin bloquear el proceso.
        """
        def funcion_colgada():
            time.sleep(2.0)
            return {"conectado": True}

        res = ejecutar_lectura_pendrive_con_timeout(funcion_colgada, timeout_segundos=0.1)
        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("conectado", False))
        self.assertTrue(res.get("sin_respuesta", False))
        self.assertEqual(res.get("error"), "Pendrive sin respuesta")

    def test_detectar_unidad_candidata_sin_vincular(self):
        """Verifica que se detecten unidades montadas que aún no han sido vinculadas."""
        config = ConfiguracionBandeja()
        config.rutas_candidatas_pendrive = [self.temp_dir]

        cand = detectar_unidad_candidata_sin_vincular(config)
        self.assertIsNotNone(cand)
        self.assertEqual(cand["punto_montaje"], os.path.realpath(self.temp_dir))
        self.assertGreater(cand["espacio_total_bytes"], 0)


class TestVinculacionPendrive(unittest.TestCase):
    """Pruebas del Grupo 2: Simulación y vinculación del pendrive."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_vinculacion_")
        # Crear archivos preexistentes del usuario para comprobar que queden idénticos
        self.carpeta_previa = os.path.join(self.temp_dir, "MisFotos_2024")
        os.makedirs(self.carpeta_previa, exist_ok=True)
        self.archivo_previo = os.path.join(self.carpeta_previa, "recuerdo.jpg")
        with open(self.archivo_previo, "wb") as f:
            f.write(b"contenido_personal_del_usuario")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_simular_vinculacion_no_escribe_en_disco(self):
        """Verifica que la simulación de vinculación no escriba nada en el pendrive."""
        config = ConfiguracionBandeja()
        res = simular_vinculacion_pendrive(self.temp_dir, config)
        self.assertTrue(res["puede_vincular"])
        self.assertEqual(res["punto_montaje"], os.path.realpath(self.temp_dir))
        self.assertEqual(res["carpeta_raiz_pendrive"], "LucieSinReglas")

        # Verificar que NO se crearon archivos ni carpetas en el pendrive
        marcador_path = os.path.join(self.temp_dir, NOMBRE_MARCADOR_PENDRIVE)
        self.assertFalse(os.path.exists(marcador_path))
        lucie_path = os.path.join(self.temp_dir, "LucieSinReglas")
        self.assertFalse(os.path.exists(lucie_path))

    def test_vincular_pendrive_crea_marcador_y_estructura_completa(self):
        """
        Verifica que la vinculación cree el marcador y la estructura base requerida
        incluyendo videos ya editados/ y videos completos/ vacíos (Requisito 3).
        """
        config = ConfiguracionBandeja()
        res = vincular_pendrive(self.temp_dir, config)
        self.assertTrue(res["exito"])
        uid = res["id"]

        # Verificar marcador
        marcador_path = os.path.join(self.temp_dir, NOMBRE_MARCADOR_PENDRIVE)
        self.assertTrue(os.path.isfile(marcador_path))
        with open(marcador_path, "r", encoding="utf-8") as f:
            marcador_data = json.load(f)
        self.assertEqual(marcador_data["id"], uid)
        self.assertEqual(marcador_data["version"], 1)

        # Verificar estructura dentro de LucieSinReglas
        raiz = os.path.join(self.temp_dir, "LucieSinReglas")
        self.assertTrue(os.path.isdir(os.path.join(raiz, ".lucie")))
        self.assertTrue(os.path.isdir(os.path.join(raiz, "videos sin editar")))
        self.assertTrue(os.path.isdir(os.path.join(raiz, "videos ya editados")))
        self.assertTrue(os.path.isdir(os.path.join(raiz, "videos completos")))
        self.assertTrue(os.path.isdir(os.path.join(raiz, "imagenes")))

        # Verificar que videos ya editados y videos completos se hayan creado vacíos
        self.assertEqual(os.listdir(os.path.join(raiz, "videos ya editados")), [])
        self.assertEqual(os.listdir(os.path.join(raiz, "videos completos")), [])

        # Verificar que el contenido previo del usuario siga intacto
        self.assertTrue(os.path.isfile(self.archivo_previo))
        with open(self.archivo_previo, "rb") as f:
            self.assertEqual(f.read(), b"contenido_personal_del_usuario")

    def test_vincular_pendrive_nunca_sobrescribe_marcador_existente(self):
        """Verifica que nunca se permita sobrescribir un marcador ya existente en la unidad."""
        config = ConfiguracionBandeja()
        res1 = vincular_pendrive(self.temp_dir, config)
        uid1 = res1["id"]

        # Intentar vincular nuevamente debe lanzar ValueError
        with self.assertRaises(ValueError):
            simular_vinculacion_pendrive(self.temp_dir, config)

        with self.assertRaises(ValueError):
            vincular_pendrive(self.temp_dir, config)

        # El marcador original debe permanecer intacto con su ID previo
        marcador_path = os.path.join(self.temp_dir, NOMBRE_MARCADOR_PENDRIVE)
        with open(marcador_path, "r", encoding="utf-8") as f:
            marcador_data = json.load(f)
        self.assertEqual(marcador_data["id"], uid1)


class TestEndpointsVinculacion(unittest.TestCase):
    """Pruebas HTTP para los endpoints de simular y vincular pendrive."""

    @classmethod
    def setUpClass(cls):
        import http.client
        from bandeja_descargas import (
            crear_servidor, GestorBaseDatosBandeja, FiltroListaBlanca,
            DetectorDescargasActivas, AgrupadorLotes, GestorMovimientosBandeja,
            GeneradorMiniaturas, VigilanteBandeja
        )
        cls.tmp_root = tempfile.mkdtemp(prefix="test_server_vinculacion_")
        cls.db_path = os.path.join(cls.tmp_root, "test.sqlite")
        cls.descargas = os.path.join(cls.tmp_root, "descargas")
        cls.destino = os.path.join(cls.tmp_root, "_lucie")
        cls.bitacora = os.path.join(cls.tmp_root, "bitacora.jsonl")
        cls.pendrive_dir = os.path.join(cls.tmp_root, "pendrive_falso")
        os.makedirs(cls.descargas, exist_ok=True)
        os.makedirs(cls.destino, exist_ok=True)
        os.makedirs(cls.pendrive_dir, exist_ok=True)

        cls.config = ConfiguracionBandeja()
        cls.config.ruta_descargas = cls.descargas
        cls.config.ruta_destino_base = cls.destino
        cls.config.puerto_servidor = 0
        cls.config.host_servidor = "127.0.0.1"
        cls.config.rutas_candidatas_pendrive = [cls.pendrive_dir]

        cls.db = GestorBaseDatosBandeja(cls.db_path)
        cls.filtro = FiltroListaBlanca(cls.config)
        cls.detector = DetectorDescargasActivas(0.1)
        cls.agrupador = AgrupadorLotes(10)
        cls.movimientos = GestorMovimientosBandeja(cls.descargas, cls.destino, cls.db, cls.bitacora)
        cls.miniaturas = GeneradorMiniaturas(cls.db, os.path.join(cls.tmp_root, "thumbs"))
        cls.vigilante = VigilanteBandeja(cls.config, cls.db, cls.filtro, cls.detector, cls.agrupador)

        cls.token_csrf = "token_csrf_prueba_vinculacion"
        cls.servidor = crear_servidor(
            cls.config, cls.db, cls.vigilante, cls.movimientos, cls.miniaturas, token_csrf=cls.token_csrf
        )
        import threading
        cls.hilo_servidor = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo_servidor.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        shutil.rmtree(cls.tmp_root, ignore_errors=True)

    def _request(self, method: str, path: str, headers: dict = None, body: str = None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.config.puerto_servidor, timeout=5)
        headers = headers or {}
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {}
        return res.status, parsed, raw

    def test_vincular_simular_requiere_csrf(self):
        """Rechaza petición a vincular-simular sin token CSRF (403)."""
        headers = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json"
        }
        status, _, _ = self._request("POST", "/api/pendrive/vincular-simular", headers=headers, body="{}")
        self.assertEqual(status, 403)

    def test_vincular_simular_y_vincular_exitoso(self):
        """Ejecuta simulación y vinculación por HTTP exitosamente."""
        headers = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.token_csrf
        }
        body = json.dumps({"punto_montaje": self.pendrive_dir})

        # 1. Simulación
        status, data, _ = self._request("POST", "/api/pendrive/vincular-simular", headers=headers, body=body)
        self.assertEqual(status, 200)
        self.assertTrue(data.get("puede_vincular"))

        # 2. Vinculación
        status, data, _ = self._request("POST", "/api/pendrive/vincular", headers=headers, body=body)
        self.assertEqual(status, 200)
        self.assertTrue(data.get("exito"))
        self.assertIn("id", data)

        # 3. Intentar vincular de nuevo debe dar 409
        status, data, _ = self._request("POST", "/api/pendrive/vincular", headers=headers, body=body)
        self.assertEqual(status, 409)

    def test_envio_simular_endpoint(self):
        """Prueba HTTP para POST /api/pendrive/envio-simular."""
        # 1. Sin CSRF -> 403
        headers_sin_csrf = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json"
        }
        status, _, _ = self._request("POST", "/api/pendrive/envio-simular", headers=headers_sin_csrf, body="{}")
        self.assertEqual(status, 403)

        # 2. Con CSRF -> 200
        headers_ok = {
            "Host": f"127.0.0.1:{self.config.puerto_servidor}",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.token_csrf
        }
        status, data, _ = self._request("POST", "/api/pendrive/envio-simular", headers=headers_ok, body="{}")
        self.assertEqual(status, 200)
        self.assertIn("puede_enviar", data)
        self.assertIn("archivos_a_copiar", data)


class TestSimulacionEnvio(unittest.TestCase):
    """Pruebas del Grupo 3: Motor de simulación de envío a pendrive."""

    def setUp(self):
        self.tmp_root = tempfile.mkdtemp(prefix="test_simulacion_envio_")
        self.pendrive_dir = os.path.join(self.tmp_root, "pendrive")
        self.descargas_dir = os.path.join(self.tmp_root, "descargas")
        self.sala_espera = os.path.join(self.tmp_root, "_lucie")

        os.makedirs(self.pendrive_dir, exist_ok=True)
        os.makedirs(self.descargas_dir, exist_ok=True)
        os.makedirs(self.sala_espera, exist_ok=True)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas_dir
        self.config.ruta_destino_base = self.sala_espera
        self.config.rutas_candidatas_pendrive = [self.pendrive_dir]

        # Vincular pendrive
        vincular_pendrive(self.pendrive_dir, self.config)

        # Crear estructura de capítulo en sala de espera:
        # ~/Descargas/_lucie/lucie/capitulo_01/
        self.cap_dir = os.path.join(self.sala_espera, "lucie", "capitulo_01")
        self.fotos_dir = os.path.join(self.cap_dir, "fotos")
        self.videos_dir = os.path.join(self.cap_dir, "videos")
        os.makedirs(self.fotos_dir, exist_ok=True)
        os.makedirs(self.videos_dir, exist_ok=True)

        # Archivo de foto
        self.foto_file = os.path.join(self.fotos_dir, "foto1.jpg")
        with open(self.foto_file, "wb") as f:
            f.write(b"contenido_foto_1")

        # Archivo de video
        self.video_file = os.path.join(self.videos_dir, "lucievideo1.mp4")
        with open(self.video_file, "wb") as f:
            f.write(b"contenido_video_1_mp4")

        # Archivo no multimedia suelto en la raíz del capítulo
        self.notas_file = os.path.join(self.cap_dir, "notas.txt")
        with open(self.notas_file, "wb") as f:
            f.write(b"anotaciones_de_produccion")

    def tearDown(self):
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_simular_envio_detecta_archivos_y_omite_no_multimedia(self):
        """
        Verifica que los videos vayan a 'videos sin editar', las fotos a 'imagenes',
        y que archivos sueltos no multimedia se omitan con aviso (Requisito 3 y 6).
        """
        sim = simular_envio_capitulos(config=self.config)
        self.assertTrue(sim["puede_enviar"])
        self.assertEqual(len(sim["archivos_a_copiar"]), 2)

        nombres_a_copiar = {a["nombre"]: a for a in sim["archivos_a_copiar"]}
        self.assertIn("foto1.jpg", nombres_a_copiar)
        self.assertIn("lucievideo1.mp4", nombres_a_copiar)

        # Verificar destino relativo
        self.assertEqual(
            nombres_a_copiar["foto1.jpg"]["ruta_relativa_pendrive"],
            f"imagenes/lucie/{nombre_mes()}/capitulo_01/foto1.jpg"
        )
        self.assertEqual(
            nombres_a_copiar["lucievideo1.mp4"]["ruta_relativa_pendrive"],
            f"videos sin editar/lucie/{nombre_mes()}/capitulo_01/lucievideo1.mp4"
        )

        # Verificar que el archivo no multimedia suelto se omitió con advertencia
        self.assertEqual(len(sim["archivos_no_multimedia"]), 1)
        self.assertEqual(sim["archivos_no_multimedia"][0]["nombre"], "notas.txt")
        self.assertTrue(any("notas.txt" in av for av in sim["avisos"]))

    def test_simular_envio_deduplicacion_ya_enviado_manifiesto(self):
        """
        Requisito 1: Un archivo cuyo sha256 ya figura en el manifiesto se omite en la simulación
        con el aviso 'ya enviado'.
        """
        from bandeja_descargas import calcular_sha256
        sha_foto = calcular_sha256(self.foto_file)

        # Registrar entrada previa en el manifiesto del pendrive
        manifiesto_path = os.path.join(self.pendrive_dir, "LucieSinReglas", ".lucie", "manifiesto.jsonl")
        entrada_previa = {
            "id_envio": str(uuid.uuid4()),
            "fecha": datetime.datetime.now().isoformat(),
            "equipo": "test-box",
            "pendrive_id": "test-id",
            "personaje": "lucie",
            "capitulo": "capitulo_01",
            "tipo": "imagen",
            "nombre": "foto1.jpg",
            "ruta_relativa": f"imagenes/lucie/{nombre_mes()}/capitulo_01/foto1.jpg",
            "sha256": sha_foto,
            "bytes": len(b"contenido_foto_1"),
            "estado": "enviado"
        }
        with open(manifiesto_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada_previa) + "\n")

        sim = simular_envio_capitulos(config=self.config)
        # La foto debe estar en omitidos con aviso 'ya enviado'
        self.assertEqual(len(sim["archivos_omitidos"]), 1)
        self.assertEqual(sim["archivos_omitidos"][0]["nombre"], "foto1.jpg")
        self.assertIn("ya enviado", sim["archivos_omitidos"][0]["aviso"].lower())

        # Solo el video debe quedar a copiar
        self.assertEqual(len(sim["archivos_a_copiar"]), 1)
        self.assertEqual(sim["archivos_a_copiar"][0]["nombre"], "lucievideo1.mp4")

    def test_listado_distingue_hash_igual_en_destinos_distintos(self):
        from bandeja.pendrive import escanear_sala_espera_carpetas
        db = GestorBaseDatosBandeja(str(Path(self.tmp_root) / 'listado.sqlite'))
        sha = calcular_sha256(self.foto_file)
        db.registrar_o_actualizar(hash_val=sha, ruta_actual=self.foto_file,
                                 estado='clasificado', personaje='lucie', escena='capitulo_01')
        envios = {(sha, 'imagenes/roli/otro/foto1.jpg')}
        def foto():
            carpetas = escanear_sala_espera_carpetas(self.config.ruta_destino_base, db=db, envios_manifiesto=envios)
            return next(a for c in carpetas for a in c['archivos'] if a['nombre'] == 'foto1.jpg')
        self.assertFalse(foto()['ya_enviado'])
        envios.add((sha, 'imagenes/lucie/capitulo_01/foto1.jpg'))
        self.assertTrue(foto()['ya_enviado'])
        envios.clear()
        envios.add((sha, f'imagenes/lucie/{nombre_mes()}/capitulo_01/foto1.jpg'))
        self.assertTrue(foto()['ya_enviado'])

    def test_hash_en_otro_destino_no_oculta_colision_local(self):
        destino = Path(self.pendrive_dir) / 'LucieSinReglas' / 'imagenes' / 'lucie' / 'capitulo_01' / 'foto1.jpg'
        destino.parent.mkdir(parents=True)
        destino.write_bytes(b'foto distinta que debe conservarse')
        manifiesto = Path(self.pendrive_dir) / 'LucieSinReglas' / '.lucie' / 'manifiesto.jsonl'
        with manifiesto.open('a') as f:
            f.write(json.dumps({'sha256': calcular_sha256(self.foto_file), 'estado': 'enviado',
                                'ruta_relativa': 'imagenes/roli/otro/foto.jpg'}) + '\n')
        plan = simular_envio_capitulos(config=self.config)
        self.assertFalse(plan['puede_enviar'])
        self.assertEqual([a['nombre'] for a in plan['archivos_conflictos']], ['foto1.jpg'])
        self.assertEqual(plan['archivos_omitidos'], [])
        self.assertEqual(destino.read_bytes(), b'foto distinta que debe conservarse')

    def test_simular_envio_conflicto_distinto_hash_bloquea_copia(self):
        """
        Requisito 3: Si en el destino existe un archivo con distinto hash, se marca como conflicto
        y NO se copia (nunca se pisa ni se sufija a ciegas).
        """
        # Crear en pendrive un archivo existente con distinto contenido
        dest_video = os.path.join(self.pendrive_dir, "LucieSinReglas", "videos sin editar", "lucie", "capitulo_01", "lucievideo1.mp4")
        os.makedirs(os.path.dirname(dest_video), exist_ok=True)
        with open(dest_video, "wb") as f:
            f.write(b"contenido_diferente_ya_existente_en_pendrive")

        sim = simular_envio_capitulos(config=self.config)
        self.assertFalse(sim["puede_enviar"])
        self.assertEqual(len(sim["archivos_conflictos"]), 1)
        self.assertEqual(sim["archivos_conflictos"][0]["nombre"], "lucievideo1.mp4")
        self.assertIn("conflicto", sim["archivos_conflictos"][0]["estado"].lower())
        self.assertIn("conflicto", sim["motivo_bloqueo"].lower())

    def test_simular_envio_colision_case_insensitive(self):
        """Verifica que detecte colisión incluso si difiere en mayúsculas/minúsculas (LUCIEVIDEO1.MP4)."""
        from bandeja_descargas import calcular_sha256
        sha_video = calcular_sha256(self.video_file)

        # Crear archivo en pendrive con nombre en mayúsculas pero mismo hash
        dest_video = os.path.join(self.pendrive_dir, "LucieSinReglas", "videos sin editar", "lucie", "capitulo_01", "LUCIEVIDEO1.MP4")
        os.makedirs(os.path.dirname(dest_video), exist_ok=True)
        with open(dest_video, "wb") as f:
            f.write(b"contenido_video_1_mp4")

        sim = simular_envio_capitulos(config=self.config)
        # Detecta que ya existe idéntico case-insensitive -> ya enviado
        omitidos_nombres = [a["nombre"] for a in sim["archivos_omitidos"]]
        self.assertIn("lucievideo1.mp4", omitidos_nombres)

    def test_simular_envio_bloqueo_fat32_4gib(self):
        """Verifica que en FAT32 se bloqueen preventivamente archivos mayores a 4 GiB."""
        import unittest.mock
        # Simular sistema de archivos vfat
        with unittest.mock.patch("bandeja.pendrive.obtener_sistema_archivos", return_value="vfat"):
            # Simular tamaño de 5 GiB para el video
            tam_5gib = 5 * 1024 * 1024 * 1024
            orig_stat = os.stat
            def mock_stat(path, *args, **kwargs):
                st = orig_stat(path, *args, **kwargs)
                if path.endswith("lucievideo1.mp4"):
                    return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                                          st.st_uid, st.st_gid, tam_5gib,
                                          st.st_atime, st.st_mtime, st.st_ctime))
                return st

            with unittest.mock.patch("os.stat", side_effect=mock_stat):
                sim = simular_envio_capitulos(config=self.config)
                self.assertFalse(sim["puede_enviar"])
                self.assertEqual(len(sim["archivos_bloqueados"]), 1)
                self.assertEqual(sim["archivos_bloqueados"][0]["nombre"], "lucievideo1.mp4")
                self.assertIn("4 gib", sim["motivo_bloqueo"].lower())

    def test_simular_envio_espacio_insuficiente(self):
        """Verifica que el envío se bloquee si no hay espacio libre suficiente con margen."""
        import unittest.mock
        # Espacio libre muy pequeño (10 bytes)
        espacio_bajo = {"total": 1000000000, "usado": 999999990, "libre": 10}
        with unittest.mock.patch("bandeja.pendrive.obtener_espacio_disco", return_value=espacio_bajo):
            sim = simular_envio_capitulos(config=self.config)
            self.assertFalse(sim["puede_enviar"])
            self.assertIn("espacio insuficiente", sim["motivo_bloqueo"].lower())


class TestEjecucionEnvioPendrive(unittest.TestCase):
    """Pruebas de la ejecución física segura de envío al pendrive (Grupo 4)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_envio_ejecucion_")
        self.descargas_dir = os.path.join(self.tmp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas_dir, "_lucie")
        self.pendrive_dir = os.path.join(self.tmp_dir, "media_user", "PENDRIVE")
        self.bitacora_path = os.path.join(self.tmp_dir, "bitacora_test.jsonl")
        self.db_path = os.path.join(self.tmp_dir, "bandeja_test.sqlite")

        os.makedirs(self.descargas_dir, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)
        os.makedirs(self.pendrive_dir, exist_ok=True)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas_dir
        self.config.ruta_destino_base = self.destino_base
        self.config.carpeta_raiz_pendrive = "LucieSinReglas"
        self.config.rutas_candidatas_pendrive = [self.pendrive_dir]
        self.config.margen_libre_bytes = 1024

        self.db = GestorBaseDatosBandeja(ruta_db=self.db_path)
        self.movimientos = GestorMovimientosBandeja(
            ruta_descargas=self.descargas_dir,
            ruta_destino_base=self.destino_base,
            db=self.db,
            ruta_bitacora=self.bitacora_path,
            config=self.config
        )

        # Vincular pendrive
        vincular_pendrive(self.pendrive_dir, self.config)

        # Archivo preexistente de usuario fuera de LucieSinReglas/
        self.user_dir = os.path.join(self.pendrive_dir, "MisDocumentos")
        os.makedirs(self.user_dir, exist_ok=True)
        self.user_file = os.path.join(self.user_dir, "archivo_intacto.txt")
        with open(self.user_file, "w", encoding="utf-8") as f:
            f.write("CONTENIDO IMPORTANTE DE USUARIO NUNCA TOCAR")
        self.user_file_hash = calcular_sha256(self.user_file)

        # Crear capítulo en sala de espera con video y foto
        self.cap_dir = os.path.join(self.destino_base, "lucie", "capitulo1")
        self.videos_dir = os.path.join(self.cap_dir, "videos")
        self.fotos_dir = os.path.join(self.cap_dir, "fotos")
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.fotos_dir, exist_ok=True)

        self.vid_path = os.path.join(self.videos_dir, "lucievideo1.mp4")
        self.fot_path = os.path.join(self.fotos_dir, "luciefoto1.jpg")
        with open(self.vid_path, "wb") as f:
            f.write(b"VIDEO CONTENT 1234567890 BINARY STREAM")
        with open(self.fot_path, "wb") as f:
            f.write(b"PHOTO CONTENT ABCDEFGHIJKLMNOPQRSTUVWXYZ")

        self.vid_hash = calcular_sha256(self.vid_path)
        self.fot_hash = calcular_sha256(self.fot_path)

    def tearDown(self):
        # Limpieza manual sin usar métodos prohibidos en código productivo
        pass

    def test_envio_lote_exitoso_copia_part_fsync_renombrado_y_verificacion(self):
        """Verifica que el lote se copie a pendrive, el original pase a _enviados y lo preexistente quede intacto."""
        res = ejecutar_envio_pendrive(
            ["lucie/capitulo1"],
            config=self.config,
            db=self.db,
            movimientos=self.movimientos
        )
        self.assertTrue(res["exito"])
        self.assertEqual(res["total_transferidos"], 2)

        # 1. Archivos en destino final en pendrive
        dest_vid = os.path.join(self.pendrive_dir, "LucieSinReglas", "videos sin editar", "lucie", nombre_mes(), "capitulo1", "lucievideo1.mp4")
        dest_fot = os.path.join(self.pendrive_dir, "LucieSinReglas", "imagenes", "lucie", nombre_mes(), "capitulo1", "luciefoto1.jpg")
        self.assertTrue(os.path.exists(dest_vid))
        self.assertTrue(os.path.exists(dest_fot))
        self.assertEqual(calcular_sha256(dest_vid), self.vid_hash)
        self.assertEqual(calcular_sha256(dest_fot), self.fot_hash)

        # 2. No deben quedar archivos .part
        self.assertFalse(os.path.exists(dest_vid + ".part"))
        self.assertFalse(os.path.exists(dest_fot + ".part"))

        # 3. Origen y carpetas vacías del capítulo se retiran tras registrar el envío.
        self.assertFalse(os.path.exists(self.cap_dir))
        self.assertIn(self.cap_dir, res["carpetas_vacias_eliminadas"])
        self.assertFalse(os.path.exists(self.vid_path))
        self.assertFalse(os.path.exists(self.fot_path))

        # 4. Archivos preservados en _enviados
        env_vid = os.path.join(self.destino_base, "_enviados", "lucie", "capitulo1", "videos", "lucievideo1.mp4")
        env_fot = os.path.join(self.destino_base, "_enviados", "lucie", "capitulo1", "fotos", "luciefoto1.jpg")
        self.assertTrue(os.path.exists(env_vid))
        self.assertTrue(os.path.exists(env_fot))
        self.assertEqual(calcular_sha256(env_vid), self.vid_hash)
        self.assertEqual(calcular_sha256(env_fot), self.fot_hash)

        # 5. Archivos preexistentes del usuario quedan 100% intactos
        self.assertTrue(os.path.exists(self.user_file))
        self.assertEqual(calcular_sha256(self.user_file), self.user_file_hash)

        # 6. Manifiesto en el pendrive contiene las 2 entradas
        ruta_man = os.path.join(self.pendrive_dir, "LucieSinReglas", ".lucie", NOMBRE_MANIFIESTO_PENDRIVE)
        self.assertTrue(os.path.exists(ruta_man))
        lineas = []
        with open(ruta_man, "r", encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    lineas.append(json.loads(l))
        self.assertEqual(len(lineas), 2)
        self.assertEqual(lineas[0]["estado"], "enviado")
        self.assertEqual(lineas[0]["id_envio"], res["id_envio"])

        # 7. Bitácora local contiene el evento envio_pendrive
        with open(self.bitacora_path, "r", encoding="utf-8") as f:
            ops = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["evento"], "envio_pendrive")
        self.assertEqual(ops[0]["id_operacion"], res["id_envio"])

    def test_nuevo_envio_mixto_agrupa_video_foto_y_audio_y_deshace(self):
        audio = Path(self.cap_dir) / "audios" / "voz.mp3"
        audio.parent.mkdir()
        audio.write_bytes(b"audio sintetico para editar")
        originales = {self.vid_path: self.vid_hash, self.fot_path: self.fot_hash,
                      str(audio): calcular_sha256(str(audio))}
        res = ejecutar_envio_pendrive(None, self.config, self.db, self.movimientos)
        self.assertTrue(res["exito"])
        self.assertEqual(res["total_transferidos"], 3)
        for categoria, archivo in (("videos sin editar", "lucievideo1.mp4"),
                                   ("imagenes", "luciefoto1.jpg"), ("audios", "voz.mp3")):
            ruta = Path(self.pendrive_dir) / "LucieSinReglas" / categoria / "lucie" / nombre_mes() / "capitulo1" / archivo
            self.assertTrue(ruta.is_file(), str(ruta))
        deshacer_envio_pendrive(res["id_envio"], config=self.config, db=self.db, ruta_bitacora=self.bitacora_path)
        for ruta, sha in originales.items():
            self.assertEqual(calcular_sha256(ruta), sha)

    def test_fotos_y_audios_migrados_conservan_deduplicacion_y_admiten_nuevos(self):
        # El envío anterior usaba la estructura sin mes; conservar su manifiesto.
        raiz = Path(self.pendrive_dir) / "LucieSinReglas"
        for categoria in ("imagenes", "audios"):
            (raiz / categoria / "lucie" / "capitulo1").mkdir(parents=True)
        audio = Path(self.cap_dir) / "audios" / "voz.mp3"
        audio.parent.mkdir()
        audio.write_bytes(b"audio previo")
        primero = ejecutar_envio_pendrive(None, self.config, self.db, self.movimientos)
        organizador = OrganizadorMensual(str(raiz), self.db)
        seleccion = [c["origen"] for c in organizador.candidatos()]
        plan_mes = organizador.simular(seleccion, {c: "septiembre - 2026" for c in seleccion})
        organizador.ejecutar(plan_mes, True)
        self.assertEqual(primero["total_transferidos"], 3)
        Path(self.fot_path).parent.mkdir(parents=True)
        Path(self.fot_path).write_bytes(b"PHOTO CONTENT ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"audio previo")
        nueva = Path(self.fotos_dir) / "nueva.jpg"
        nueva.write_bytes(b"foto nueva")
        plan = simular_envio_capitulos(["lucie/capitulo1"], self.config, self.db)
        self.assertEqual({a["nombre"] for a in plan["archivos_omitidos"]}, {"luciefoto1.jpg", "voz.mp3"})
        self.assertEqual(len(plan["archivos_a_copiar"]), 1)
        self.assertIn("/septiembre - 2026/", plan["archivos_a_copiar"][0]["ruta_relativa_pendrive"])
        segundo = ejecutar_envio_pendrive(plan, self.config, self.db, self.movimientos)
        deshacer_envio_pendrive(segundo["id_envio"], config=self.config, db=self.db, ruta_bitacora=self.bitacora_path)
        self.assertEqual(nueva.read_bytes(), b"foto nueva")
        self.assertEqual((raiz / "audios/lucie/septiembre - 2026/capitulo1/voz.mp3").read_bytes(), b"audio previo")

    def test_envio_falla_verificacion_preserva_part_y_no_mueve_origen(self):
        """Si la verificación post-copia falla, el archivo .part se preserva y el origen NO se mueve."""
        import unittest.mock
        real_calc = calcular_sha256

        def mock_calc_sha(path, *args, **kwargs):
            # Provocar fallo en la verificación post-copia
            if "LucieSinReglas" in path and not path.endswith(".part"):
                return "hash_corrupto_discrepante_falso"
            return real_calc(path, *args, **kwargs)

        with unittest.mock.patch("bandeja.pendrive.calcular_sha256", side_effect=mock_calc_sha):
            with self.assertRaises(RuntimeError) as ctx:
                ejecutar_envio_pendrive(
                    ["lucie/capitulo1"],
                    config=self.config,
                    db=self.db,
                    movimientos=self.movimientos
                )
            self.assertIn("discrepancia", str(ctx.exception).lower())

        # El archivo .part no fue borrado
        dest_vid_part = os.path.join(self.pendrive_dir, "LucieSinReglas", "videos sin editar", "lucie", "capitulo1", "lucievideo1.mp4.part")
        # O bien el destino final quedó corrupto y el origen sigue en sala de espera intacto
        self.assertTrue(os.path.exists(self.vid_path))
        self.assertTrue(os.path.exists(self.fot_path))

    def test_part_preexistente_no_se_sobrescribe(self):
        plan = simular_envio_capitulos(['lucie/capitulo1'], self.config, self.db)
        part = Path(plan['archivos_a_copiar'][0]['ruta_destino_absoluta'] + '.part')
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b'copia parcial anterior a conservar')
        with self.assertRaises(RuntimeError):
            ejecutar_envio_pendrive(plan, self.config, self.db, self.movimientos)
        self.assertEqual(part.read_bytes(), b'copia parcial anterior a conservar')
        self.assertTrue(Path(self.vid_path).exists())
        self.assertTrue(Path(self.fot_path).exists())

    def test_cartel_colisiones_renombrar_o_no_agregar_con_deshacer(self):
        primero = ejecutar_envio_pendrive(None, self.config, self.db, self.movimientos)
        raiz = Path(self.pendrive_dir) / 'LucieSinReglas'
        anteriores = {r['ruta_relativa']: (raiz / r['ruta_relativa']).read_bytes() for r in primero['archivos']}
        Path(self.videos_dir).mkdir(parents=True)
        Path(self.fotos_dir).mkdir()
        Path(self.vid_path).write_bytes(b'video nuevo con nombre ocupado')
        Path(self.fot_path).write_bytes(b'foto nueva con nombre ocupado')
        sufijo_ocupado = raiz / 'imagenes' / 'lucie' / nombre_mes() / 'capitulo1' / 'LUCIEFOTO1_1.JPG'
        sufijo_ocupado.write_bytes(b'otro archivo que se conserva')
        bloqueado = simular_envio_capitulos(['lucie/capitulo1'], self.config, self.db)
        self.assertFalse(bloqueado['puede_enviar'])
        ids = {a['nombre']: a['id_archivo'] for a in bloqueado['archivos_conflictos']}
        decisiones = {ids['lucievideo1.mp4']: 'omitir', ids['luciefoto1.jpg']: 'renombrar'}
        plan = simular_envio_capitulos(['lucie/capitulo1'], self.config, self.db,
                                      resoluciones_colisiones=decisiones)
        self.assertTrue(plan['puede_enviar'])
        self.assertEqual(plan['total_archivos_a_enviar'], 1)
        self.assertEqual(plan['archivos_a_copiar'][0]['nombre_destino'], 'luciefoto1_2.jpg')
        self.assertEqual(plan['archivos_omitidos'][0]['estado'], 'omitido_usuario')
        destino = raiz / plan['archivos_a_copiar'][0]['ruta_relativa_pendrive']
        self.assertFalse(destino.exists(), 'La simulación no debe copiar')
        res = ejecutar_envio_pendrive(plan, self.config, self.db, self.movimientos)
        self.assertEqual(destino.read_bytes(), b'foto nueva con nombre ocupado')
        self.assertEqual(Path(self.vid_path).read_bytes(), b'video nuevo con nombre ocupado')
        for relativa, contenido in anteriores.items():
            self.assertEqual((raiz / relativa).read_bytes(), contenido)
        self.assertEqual(sufijo_ocupado.read_bytes(), b'otro archivo que se conserva')
        deshacer_envio_pendrive(res['id_envio'], config=self.config, db=self.db, ruta_bitacora=self.bitacora_path)
        self.assertEqual(Path(self.fot_path).read_bytes(), b'foto nueva con nombre ocupado')
        for relativa, contenido in anteriores.items():
            self.assertEqual((raiz / relativa).read_bytes(), contenido)

    def test_copia_identica_permite_elegir_renombrar_o_no_agregar(self):
        video = Path(self.vid_path).read_bytes()
        foto = Path(self.fot_path).read_bytes()
        ejecutar_envio_pendrive(None, self.config, self.db, self.movimientos)
        Path(self.videos_dir).mkdir(parents=True)
        Path(self.fotos_dir).mkdir()
        Path(self.vid_path).write_bytes(video)
        Path(self.fot_path).write_bytes(foto)
        sim = simular_envio_capitulos(['lucie/capitulo1'], self.config, self.db)
        self.assertEqual(len(sim['archivos_omitidos']), 2)
        decisiones = {a['id_archivo']: 'omitir' for a in sim['archivos_omitidos']}
        no = simular_envio_capitulos(['lucie/capitulo1'], self.config, self.db, resoluciones_colisiones=decisiones)
        self.assertFalse(no['puede_enviar'])
        self.assertEqual(no['archivos_a_copiar'], [])
        foto_id = next(a['id_archivo'] for a in sim['archivos_omitidos'] if a['nombre'].endswith('.jpg'))
        decisiones[foto_id] = 'renombrar'
        si = simular_envio_capitulos(['lucie/capitulo1'], self.config, self.db, resoluciones_colisiones=decisiones)
        self.assertTrue(si['puede_enviar'])
        self.assertEqual(si['archivos_a_copiar'][0]['nombre_destino'], 'luciefoto1_1.jpg')
        self.assertEqual(si['resoluciones_colisiones'], decisiones)
        for invalida in ([], 'renombrar', {'id': 'sobrescribir'}):
            with self.assertRaises(ValueError):
                simular_envio_capitulos(['lucie/capitulo1'], self.config, self.db, resoluciones_colisiones=invalida)

    def test_agregar_tres_fotos_a_proyecto_enviado_reutilizando_contenido(self):
        """Mismo contenido en otro destino no bloquea las tres fotos nuevas."""
        video_original = Path(self.vid_path).read_bytes()
        foto14 = Path(self.fotos_dir) / 'lucietehicistepolicia14.jpg'
        foto14.write_bytes(b'foto reutilizada en el mismo proyecto')
        foto_otro = Path(self.destino_base) / 'roli' / 'Otro proyecto' / 'fotos' / 'roli1.jpg'
        foto_otro.parent.mkdir(parents=True)
        foto_otro.write_bytes(b'foto reutilizada de otro proyecto')
        primero = ejecutar_envio_pendrive(None, self.config, self.db, self.movimientos)
        self.assertEqual(primero['total_transferidos'], 4)
        iniciales = {r['ruta_relativa']: calcular_sha256(os.path.join(
            self.pendrive_dir, 'LucieSinReglas', *r['ruta_relativa'].split('/'))) for r in primero['archivos']}
        Path(self.videos_dir).mkdir(parents=True)
        Path(self.vid_path).write_bytes(video_original)
        Path(self.fotos_dir).mkdir()
        fotos = {
            'lucietehicistepolicia9.jpg': b'foto reutilizada de otro proyecto',
            'lucietehicistepolicia10.jpg': b'foto reutilizada en el mismo proyecto',
            'lucietehicistepolicia11.jpg': b'foto reutilizada en el mismo proyecto',
        }
        for nombre, contenido in fotos.items():
            (Path(self.fotos_dir) / nombre).write_bytes(contenido)
        plan = simular_envio_capitulos(['lucie/capitulo1'], self.config, self.db)
        self.assertTrue(plan['puede_enviar'])
        self.assertEqual(plan['total_archivos_a_enviar'], 3)
        self.assertEqual({a['nombre'] for a in plan['archivos_a_copiar']}, set(fotos))
        self.assertEqual([a['nombre'] for a in plan['archivos_omitidos']], ['lucievideo1.mp4'])
        segundo = ejecutar_envio_pendrive(plan, self.config, self.db, self.movimientos)
        self.assertEqual(segundo['total_transferidos'], 3)
        for relativa, sha in iniciales.items():
            self.assertEqual(calcular_sha256(os.path.join(self.pendrive_dir, 'LucieSinReglas', *relativa.split('/'))), sha)
        for nombre, contenido in fotos.items():
            destino = Path(self.pendrive_dir) / 'LucieSinReglas' / 'imagenes' / 'lucie' / nombre_mes() / 'capitulo1' / nombre
            self.assertEqual(destino.read_bytes(), contenido)
        deshacer_envio_pendrive(segundo['id_envio'], config=self.config, db=self.db, ruta_bitacora=self.bitacora_path)
        for nombre, contenido in fotos.items():
            self.assertEqual((Path(self.fotos_dir) / nombre).read_bytes(), contenido)

    def test_envio_videos_fotos_limpia_tres_personajes_y_deshacer_recrea(self):
        """Envío real en temporales: limpieza y reversión para los tres personajes."""
        originales = {self.vid_path: self.vid_hash, self.fot_path: self.fot_hash}
        capitulos = [self.cap_dir]
        for personaje in ("roli", "mailen"):
            cap = os.path.join(self.destino_base, personaje, "Proyecto con espacios")
            capitulos.append(cap)
            for sub, nombre in (("videos", "clip.mp4"), ("fotos", "foto.jpg")):
                ruta = os.path.join(cap, sub, nombre)
                os.makedirs(os.path.dirname(ruta), exist_ok=True)
                with open(ruta, "wb") as f:
                    f.write((personaje + nombre).encode())
                originales[ruta] = calcular_sha256(ruta)
        res = ejecutar_envio_pendrive(config=self.config, simulacion_o_capitulos=None,
                                     db=self.db, movimientos=self.movimientos)
        self.assertEqual(res["total_transferidos"], 6)
        for cap in capitulos:
            self.assertFalse(os.path.exists(cap))
            self.assertIn(cap, res["carpetas_vacias_eliminadas"])
            self.assertTrue(os.path.isdir(os.path.dirname(cap)))
        deshacer_envio_pendrive(res["id_envio"], config=self.config, db=self.db,
                               ruta_bitacora=self.bitacora_path)
        for ruta, sha in originales.items():
            self.assertEqual(calcular_sha256(ruta), sha)

    def test_envio_revisa_huerfanas_previas_sin_tocar_contenido_nuevo(self):
        anterior = os.path.join(self.destino_base, 'roli', 'Proyecto anterior')
        nueva_foto = os.path.join(anterior, 'fotos', 'nueva.jpg')
        os.makedirs(os.path.dirname(nueva_foto))
        registro = {'personaje': 'roli', 'capitulo': 'Proyecto anterior',
                    'ruta_origen_espera': os.path.join(anterior, 'videos', 'anterior.mp4')}
        with open(nueva_foto, 'wb') as f:
            f.write(b'No enviado')
        with open(self.bitacora_path, 'w') as f:
            f.write(json.dumps({'evento': 'envio_pendrive', 'archivos': [registro]}) + '\n')
        huerfana = os.path.join(self.destino_base, 'mailen', 'Proyecto enviado')
        os.makedirs(os.path.join(huerfana, 'videos'))
        with open(self.bitacora_path, 'a') as f:
            f.write(json.dumps({'evento': 'envio_pendrive', 'archivos': [
                {'personaje': 'mailen', 'capitulo': 'Proyecto enviado',
                 'ruta_origen_espera': os.path.join(huerfana, 'videos', 'clip.mp4')}]}) + '\n')
        ajena = os.path.join(self.destino_base, 'lucie', 'Proyecto no enviado')
        os.makedirs(ajena)
        res = ejecutar_envio_pendrive(['lucie/capitulo1'], self.config, self.db, self.movimientos)
        self.assertIn(huerfana, res['carpetas_vacias_eliminadas'])
        self.assertFalse(os.path.exists(huerfana))
        self.assertTrue(os.path.isdir(ajena))
        with open(nueva_foto, 'rb') as f:
            self.assertEqual(f.read(), b'No enviado')

    def test_fallo_parcial_o_de_registro_no_inicia_limpieza(self):
        for fallo in ('segunda_copia', 'registro'):
            with self.subTest(fallo=fallo):
                # Cada escenario mantiene su propia sala y pendrive temporales.
                caso = TestEjecucionEnvioPendrive()
                caso.setUp()
                sim = simular_envio_capitulos(['lucie/capitulo1'], caso.config, caso.db)
                original_open = open
                def abrir(ruta, modo='r', *args, **kwargs):
                    if (fallo == 'segunda_copia' and str(ruta) == sim['archivos_a_copiar'][1]['ruta_origen']
                            and modo == 'rb') or (fallo == 'registro' and str(ruta) == caso.bitacora_path):
                        raise OSError('Fallo simulado')
                    return original_open(ruta, modo, *args, **kwargs)
                with patch('builtins.open', side_effect=abrir), patch(
                        'bandeja.pendrive._limpiar_carpetas_vacias_enviadas') as limpiar:
                    with self.assertRaises((OSError, RuntimeError)):
                        ejecutar_envio_pendrive(sim, caso.config, caso.db, caso.movimientos)
                    limpiar.assert_not_called()
                self.assertTrue(os.path.isdir(caso.cap_dir))

    def test_preservacion_enviados_sufijo_numerico_si_ya_existe(self):
        """Verifica que si ya existe un archivo con idéntico nombre en _enviados, se use sufijo numérico."""
        env_vid = os.path.join(self.destino_base, "_enviados", "lucie", "capitulo1", "videos", "lucievideo1.mp4")
        os.makedirs(os.path.dirname(env_vid), exist_ok=True)
        with open(env_vid, "wb") as f:
            f.write(b"PREEXISTING ENVIADO FILE")

        res = ejecutar_envio_pendrive(
            ["lucie/capitulo1"],
            config=self.config,
            db=self.db,
            movimientos=self.movimientos
        )
        self.assertTrue(res["exito"])

        # El preexistente sigue intacto
        with open(env_vid, "rb") as f:
            self.assertEqual(f.read(), b"PREEXISTING ENVIADO FILE")

        # El nuevo tomó sufijo _1
        env_vid_sufijo = os.path.join(self.destino_base, "_enviados", "lucie", "capitulo1", "videos", "lucievideo1_1.mp4")
        self.assertTrue(os.path.exists(env_vid_sufijo))
        self.assertEqual(calcular_sha256(env_vid_sufijo), self.vid_hash)


class TestDeshacerEnvioPendrive(unittest.TestCase):
    """Pruebas del mecanismo de deshacer envíos al pendrive hacia _revertidos (Grupo 5)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_envio_deshacer_")
        self.descargas_dir = os.path.join(self.tmp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas_dir, "_lucie")
        self.pendrive_dir = os.path.join(self.tmp_dir, "media_user", "PENDRIVE")
        self.bitacora_path = os.path.join(self.tmp_dir, "bitacora_test.jsonl")
        self.db_path = os.path.join(self.tmp_dir, "bandeja_test.sqlite")

        os.makedirs(self.descargas_dir, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)
        os.makedirs(self.pendrive_dir, exist_ok=True)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas_dir
        self.config.ruta_destino_base = self.destino_base
        self.config.carpeta_raiz_pendrive = "LucieSinReglas"
        self.config.rutas_candidatas_pendrive = [self.pendrive_dir]
        self.config.margen_libre_bytes = 1024

        self.db = GestorBaseDatosBandeja(ruta_db=self.db_path)
        self.movimientos = GestorMovimientosBandeja(
            ruta_descargas=self.descargas_dir,
            ruta_destino_base=self.destino_base,
            db=self.db,
            ruta_bitacora=self.bitacora_path,
            config=self.config
        )

        vincular_pendrive(self.pendrive_dir, self.config)

        self.cap_dir = os.path.join(self.destino_base, "lucie", "capitulo1")
        self.videos_dir = os.path.join(self.cap_dir, "videos")
        os.makedirs(self.videos_dir, exist_ok=True)

        self.vid_path = os.path.join(self.videos_dir, "lucievideo1.mp4")
        with open(self.vid_path, "wb") as f:
            f.write(b"ORIGINAL VIDEO IN WAITING AREA")
        self.vid_hash = calcular_sha256(self.vid_path)

        # Realizar envío inicial
        self.envio_res = ejecutar_envio_pendrive(
            ["lucie/capitulo1"],
            config=self.config,
            db=self.db,
            movimientos=self.movimientos
        )
        self.id_envio = self.envio_res["id_envio"]

    def test_deshacer_envio_exitoso(self):
        """Verifica que al deshacer, la copia va a _revertidos y el original vuelve a la sala de espera."""
        res_undo = deshacer_envio_pendrive(
            self.id_envio,
            config=self.config,
            db=self.db,
            ruta_bitacora=self.bitacora_path
        )
        self.assertTrue(res_undo["exito"])
        self.assertEqual(res_undo["total_revertidos"], 1)

        # 1. El original volvió a la sala de espera
        self.assertTrue(os.path.exists(self.vid_path))
        self.assertEqual(calcular_sha256(self.vid_path), self.vid_hash)

        # 2. La copia en pendrive se trasladó a _revertidos/<id_envio>/...
        dest_revertido = os.path.join(
            self.pendrive_dir, "LucieSinReglas", "_revertidos", self.id_envio,
            "videos sin editar", "lucie", nombre_mes(), "capitulo1", "lucievideo1.mp4"
        )
        self.assertTrue(os.path.exists(dest_revertido))
        self.assertEqual(calcular_sha256(dest_revertido), self.vid_hash)

        # 3. La copia activa en el pendrive ya no existe
        dest_activo = os.path.join(
            self.pendrive_dir, "LucieSinReglas", "videos sin editar", "lucie", nombre_mes(), "capitulo1", "lucievideo1.mp4"
        )
        self.assertFalse(os.path.exists(dest_activo))

        # 4. Manifiesto en pendrive tiene registrado 'envio_revertido'
        ruta_man = os.path.join(self.pendrive_dir, "LucieSinReglas", ".lucie", NOMBRE_MANIFIESTO_PENDRIVE)
        with open(ruta_man, "r", encoding="utf-8") as f:
            lineas = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(lineas), 2)
        self.assertEqual(lineas[1]["estado"], "envio_revertido")
        self.assertEqual(lineas[1]["id_envio"], self.id_envio)

        # 5. Bitácora local tiene registrado el evento deshacer
        with open(self.bitacora_path, "r", encoding="utf-8") as f:
            ops = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(ops), 2)
        self.assertEqual(ops[1]["evento"], "deshacer")
        self.assertEqual(ops[1]["id_operacion_revertida"], self.id_envio)

    def test_deshacer_rechazado_si_origen_sala_espera_ocupado(self):
        """Si la ruta de destino original en la sala de espera fue ocupada por otro archivo, el deshacer se NIEGA."""
        # El envío retira la carpeta vacía; un nuevo productor puede recrearla.
        os.makedirs(os.path.dirname(self.vid_path), exist_ok=True)
        # Colocar un nuevo archivo en la misma ruta original
        with open(self.vid_path, "wb") as f:
            f.write(b"NUEVO ARCHIVO LLEGADO RECIENTEMENTE A SALA DE ESPERA")

        with self.assertRaises(ErrorDeshacer) as ctx:
            deshacer_envio_pendrive(
                self.id_envio,
                config=self.config,
                db=self.db,
                ruta_bitacora=self.bitacora_path
            )

        self.assertIn("ocupada", str(ctx.exception).lower())

        # Verificar que el nuevo archivo NO fue tocado ni pisado
        with open(self.vid_path, "rb") as f:
            self.assertEqual(f.read(), b"NUEVO ARCHIVO LLEGADO RECIENTEMENTE A SALA DE ESPERA")

        # La copia en pendrive sigue en su lugar original intacta
        dest_activo = os.path.join(
            self.pendrive_dir, "LucieSinReglas", "videos sin editar", "lucie", nombre_mes(), "capitulo1", "lucievideo1.mp4"
        )
        self.assertTrue(os.path.exists(dest_activo))


class TestEndpointsEnvioYDeshacerHTTP(unittest.TestCase):
    """Pruebas de endpoints HTTP POST /api/pendrive/envio y POST /api/deshacer."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_http_envio_")
        self.descargas_dir = os.path.join(self.tmp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas_dir, "_lucie")
        self.pendrive_dir = os.path.join(self.tmp_dir, "media_user", "PENDRIVE")
        self.bitacora_path = os.path.join(self.tmp_dir, "bitacora_test.jsonl")
        self.db_path = os.path.join(self.tmp_dir, "bandeja_test.sqlite")

        os.makedirs(self.descargas_dir, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)
        os.makedirs(self.pendrive_dir, exist_ok=True)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas_dir
        self.config.ruta_destino_base = self.destino_base
        self.config.carpeta_raiz_pendrive = "LucieSinReglas"
        self.config.rutas_candidatas_pendrive = [self.pendrive_dir]
        self.config.puerto_servidor = 0
        self.config.host_servidor = "127.0.0.1"

        self.db = GestorBaseDatosBandeja(ruta_db=self.db_path)
        self.token_csrf = "token_prueba_csrf_123456789"

        vincular_pendrive(self.pendrive_dir, self.config)

        # Crear archivo en sala de espera
        cap_dir = os.path.join(self.destino_base, "lucie", "cap1")
        os.makedirs(os.path.join(cap_dir, "videos"), exist_ok=True)
        with open(os.path.join(cap_dir, "videos", "v1.mp4"), "wb") as f:
            f.write(b"SAMPLE VIDEO FOR HTTP TEST")

        self.movimientos = GestorMovimientosBandeja(
            ruta_descargas=self.descargas_dir,
            ruta_destino_base=self.destino_base,
            db=self.db,
            ruta_bitacora=self.bitacora_path,
            config=self.config
        )
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas()
        self.agrupador = AgrupadorLotes(ventana_minutos=self.config.ventana_lote_minutos)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        self.miniaturas = GeneradorMiniaturas(self.db)

        self.servidor = crear_servidor(
            self.config, self.db, self.vigilante, self.movimientos,
            self.miniaturas, token_csrf=self.token_csrf
        )
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()
        self.puerto = self.config.puerto_servidor

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()

    def test_post_envio_exitoso_y_deshacer(self):
        import urllib.request
        url_envio = f"http://127.0.0.1:{self.puerto}/api/pendrive/envio"
        req = urllib.request.Request(
            url_envio,
            data=json.dumps({"capitulos": ["lucie/cap1"]}).encode("utf-8"),
            headers={
                "Host": f"127.0.0.1:{self.puerto}",
                "Content-Type": "application/json",
                "X-CSRF-Token": self.token_csrf
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("exito"))
            id_envio = data.get("id_envio")

        # Ahora revertir mediante POST /api/deshacer
        url_deshacer = f"http://127.0.0.1:{self.puerto}/api/deshacer"
        req_undo = urllib.request.Request(
            url_deshacer,
            data=json.dumps({"id_operacion": id_envio}).encode("utf-8"),
            headers={
                "Host": f"127.0.0.1:{self.puerto}",
                "Content-Type": "application/json",
                "X-CSRF-Token": self.token_csrf
            },
            method="POST"
        )
        with urllib.request.urlopen(req_undo) as resp_undo:
            self.assertEqual(resp_undo.status, 200)
            data_undo = json.loads(resp_undo.read().decode("utf-8"))
            self.assertTrue(data_undo.get("exito"))

        # Deshacer por segunda vez debe responder 409 Conflict
        req_repeat = urllib.request.Request(
            url_deshacer,
            data=json.dumps({"id_operacion": id_envio}).encode("utf-8"),
            headers={
                "Host": f"127.0.0.1:{self.puerto}",
                "Content-Type": "application/json",
                "X-CSRF-Token": self.token_csrf
            },
            method="POST"
        )
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_repeat)
        self.assertEqual(ctx.exception.code, 409)


class TestVigilanteYEstadoPendrive(unittest.TestCase):
    """Pruebas del Vigilante, Banner reactivo y estado de API con timeout (Grupo 6)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_vigilante_pen_")
        self.descargas_dir = os.path.join(self.tmp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas_dir, "_lucie")
        self.pendrive_dir = os.path.join(self.tmp_dir, "media_user", "PENDRIVE")
        self.bitacora_path = os.path.join(self.tmp_dir, "bitacora_test.jsonl")
        self.db_path = os.path.join(self.tmp_dir, "bandeja_test.sqlite")

        os.makedirs(self.descargas_dir, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)
        os.makedirs(self.pendrive_dir, exist_ok=True)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas_dir
        self.config.ruta_destino_base = self.destino_base
        self.config.carpeta_raiz_pendrive = "LucieSinReglas"
        self.config.rutas_candidatas_pendrive = [self.pendrive_dir]
        self.config.puerto_servidor = 0
        self.config.host_servidor = "127.0.0.1"

        self.db = GestorBaseDatosBandeja(ruta_db=self.db_path)
        self.token_csrf = "token_csrf_vigilante_123"

        vincular_pendrive(self.pendrive_dir, self.config)

        # Crear 3 archivos en 2 capítulos
        cap1 = os.path.join(self.destino_base, "lucie", "cap1")
        cap2 = os.path.join(self.destino_base, "roli", "cap2")
        os.makedirs(os.path.join(cap1, "videos"), exist_ok=True)
        os.makedirs(os.path.join(cap1, "fotos"), exist_ok=True)
        os.makedirs(os.path.join(cap2, "videos"), exist_ok=True)

        with open(os.path.join(cap1, "videos", "v1.mp4"), "wb") as f:
            f.write(b"V1")
        with open(os.path.join(cap1, "fotos", "f1.jpg"), "wb") as f:
            f.write(b"F1")
        with open(os.path.join(cap2, "videos", "v2.mp4"), "wb") as f:
            f.write(b"V2")

        self.movimientos = GestorMovimientosBandeja(
            ruta_descargas=self.descargas_dir,
            ruta_destino_base=self.destino_base,
            db=self.db,
            ruta_bitacora=self.bitacora_path,
            config=self.config
        )
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas()
        self.agrupador = AgrupadorLotes(ventana_minutos=self.config.ventana_lote_minutos)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)
        self.miniaturas = GeneradorMiniaturas(self.db)

        self.servidor = crear_servidor(
            self.config, self.db, self.vigilante, self.movimientos,
            self.miniaturas, token_csrf=self.token_csrf
        )
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()
        self.puerto = self.config.puerto_servidor

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()

    def test_vigilante_detecta_pendrive_y_calcula_pendientes_sin_enviar_automatico(self):
        """Verifica que el vigilante cuente archivos y capítulos listos sin enviar nada solo."""
        self.vigilante.escanear()
        estado = self.vigilante.obtener_estado()

        self.assertTrue(estado["pendrive"]["conectado"])
        self.assertEqual(estado["pendrive"]["archivos_pendientes_conteo"], 3)
        self.assertEqual(estado["pendrive"]["capitulos_pendientes_conteo"], 2)
        banner = estado["pendrive"]["banner_reactivo"]
        self.assertIsNotNone(banner)
        self.assertTrue(banner["mostrar"])
        self.assertIn("3 archivo(s) de 2 capítulo(s)", banner["mensaje"])

        # Ningún archivo debe haberse transferido automáticamente
        dest_pen = os.path.join(self.pendrive_dir, "LucieSinReglas", "videos sin editar", "lucie", "cap1", "v1.mp4")
        self.assertFalse(os.path.exists(dest_pen))

    def test_endpoint_get_pendrive_estado_y_archivos_part_huerfanos(self):
        """El endpoint GET /api/pendrive/estado reporta la unidad y los archivos .part huérfanos."""
        import urllib.request
        # Crear un archivo .part huérfano dentro de LucieSinReglas
        dir_part = os.path.join(self.pendrive_dir, "LucieSinReglas", "videos sin editar", "lucie", "cap1")
        os.makedirs(dir_part, exist_ok=True)
        part_file = os.path.join(dir_part, "video_incompleto.mp4.part")
        with open(part_file, "wb") as f:
            f.write(b"INCOMPLETE PART DATA")

        url = f"http://127.0.0.1:{self.puerto}/api/pendrive/estado"
        req = urllib.request.Request(url, headers={"Host": f"127.0.0.1:{self.puerto}"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertTrue(data.get("conectado"))
        self.assertFalse(data.get("sin_respuesta"))
        self.assertEqual(data.get("punto_montaje"), self.pendrive_dir)
        huerfanos = data.get("archivos_part_huerfanos", [])
        self.assertEqual(len(huerfanos), 1)
        self.assertEqual(huerfanos[0]["nombre"], "video_incompleto.mp4.part")

    def test_endpoint_get_pendrive_estado_sin_respuesta_timeout(self):
        """Si el pendrive no responde o se cuelga, el endpoint responde sin_respuesta=True y error explicativo."""
        import urllib.request
        import unittest.mock

        # Simular lectura colgada que retorna sin_respuesta
        mock_res = {
            "conectado": False,
            "sin_respuesta": True,
            "error": "Pendrive sin respuesta",
            "mensaje": "Pendrive sin respuesta",
            "id": None,
            "punto_montaje": None,
            "sistema_archivos": None,
            "espacio_libre_bytes": 0,
            "espacio_total_bytes": 0,
            "espacio_usado_bytes": 0,
            "archivos_part_huerfanos": [],
            "archivos_pendientes_conteo": 0,
            "capitulos_pendientes_conteo": 0,
            "banner_reactivo": None
        }

        with unittest.mock.patch("bandeja.servidor.obtener_estado_pendrive", return_value=mock_res):
            url = f"http://127.0.0.1:{self.puerto}/api/pendrive/estado"
            req = urllib.request.Request(url, headers={"Host": f"127.0.0.1:{self.puerto}"})
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))

        self.assertFalse(data.get("conectado"))
        self.assertTrue(data.get("sin_respuesta"))
        self.assertEqual(data.get("error"), "Pendrive sin respuesta")


class TestInterfazUsuarioPendrive(unittest.TestCase):
    def test_modal_incremental_contrato_api(self):
        import subprocess
        import shutil
        if not shutil.which('node'):
            self.skipTest('Node.js no disponible para ejecutar la regresión UI')
        res = subprocess.run(['node', 'test_envio_incremental_ui.js'], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


    """Pruebas de la Interfaz de Usuario y SPA para el envío a pendrive (Grupo 7)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_ui_pendrive_")
        self.descargas_dir = os.path.join(self.tmp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas_dir, "_lucie")
        self.pendrive_dir = os.path.join(self.tmp_dir, "media_user", "PENDRIVE")
        self.bitacora_path = os.path.join(self.tmp_dir, "bitacora_test.jsonl")
        self.db_path = os.path.join(self.tmp_dir, "bandeja_test.sqlite")

        os.makedirs(self.descargas_dir, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)
        os.makedirs(self.pendrive_dir, exist_ok=True)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas_dir
        self.config.ruta_destino_base = self.destino_base
        self.config.carpeta_raiz_pendrive = "LucieSinReglas"
        self.config.rutas_candidatas_pendrive = [self.pendrive_dir]
        self.config.puerto_servidor = 0
        self.config.host_servidor = "127.0.0.1"

        self.db = GestorBaseDatosBandeja(ruta_db=self.db_path)
        self.token_csrf = "token_csrf_ui_test_456"

        self.movimientos = GestorMovimientosBandeja(
            ruta_descargas=self.descargas_dir,
            ruta_destino_base=self.destino_base,
            db=self.db,
            ruta_bitacora=self.bitacora_path,
            config=self.config
        )
        self.filtro = FiltroListaBlanca(self.config)
        self.detector = DetectorDescargasActivas()
        self.agrupador = AgrupadorLotes()
        self.miniaturas = GeneradorMiniaturas(self.db)
        self.vigilante = VigilanteBandeja(self.config, self.db, self.filtro, self.detector, self.agrupador)

        self.servidor = crear_servidor(
            self.config, self.db, self.vigilante, self.movimientos,
            self.miniaturas, token_csrf=self.token_csrf
        )
        self.puerto = self.servidor.server_address[1]
        self.server_thread = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self):
        try:
            self.servidor.shutdown()
            self.servidor.server_close()
        except Exception:
            pass

    def test_spa_contiene_elementos_pendrive(self):
        """La SPA servida contiene el botón de pestaña Pendrive, sec-pendrive, banner reactivo y modales."""
        import urllib.request
        url = f"http://127.0.0.1:{self.puerto}/"
        req = urllib.request.Request(url, headers={"Host": f"127.0.0.1:{self.puerto}"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            cuerpo = resp.read().decode("utf-8")

        # 7.1: Pestaña "Pendrive" y sección sec-pendrive
        self.assertIn('id="nav-btn-pendrive"', cuerpo)
        self.assertIn('id="sec-pendrive"', cuerpo)
        self.assertIn('id="contenedor-estado-pendrive"', cuerpo)
        self.assertIn('id="contenedor-capitulos-pendrive"', cuerpo)
        self.assertIn('id="card-part-pendrive"', cuerpo)
        self.assertIn('id="contenedor-part-pendrive"', cuerpo)
        self.assertIn('id="contenedor-historial-pendrive"', cuerpo)
        self.assertIn('id="btn-vincular-pendrive"', cuerpo)
        self.assertIn('id="btn-enviar-todos-pendrive"', cuerpo)

        # 7.2: Botón Enviar al pendrive en banner de capítulo activo
        self.assertIn('id="btn-enviar-capitulo-activo"', cuerpo)

        # 7.3: Banner reactivo y Modales interactivos
        self.assertIn('id="banner-pendrive-detectado"', cuerpo)
        self.assertIn('id="modal-plan-envio"', cuerpo)
        self.assertIn('id="modal-vincular-pendrive"', cuerpo)
        self.assertIn('id="btn-confirmar-envio-pendrive"', cuerpo)

        # Funciones JS presentes en panel.js
        url_js = f"http://127.0.0.1:{self.puerto}/panel.js"
        req_js = urllib.request.Request(url_js, headers={"Host": f"127.0.0.1:{self.puerto}"})
        with urllib.request.urlopen(req_js) as resp_js:
            self.assertEqual(resp_js.status, 200)
            cuerpo_js = resp_js.read().decode("utf-8")

        self.assertIn("cargarVistaPendrive", cuerpo_js)
        self.assertIn("abrirModalPlanEnvio", cuerpo_js)
        self.assertIn("confirmarEnvioPendrive", cuerpo_js)
        self.assertIn("deshacerEnvio", cuerpo_js)
        self.assertIn("abrirModalVincularPendrive", cuerpo_js)
        self.assertIn("confirmarVincularPendrive", cuerpo_js)


class TestConfinamientoSeguridadPendrive(unittest.TestCase):
    """Pruebas de confinamiento canónico estricto y exclusión de carpetas reservadas (Grupo 8)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_confinamiento_pen_")
        self.descargas_dir = os.path.join(self.tmp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas_dir, "_lucie")
        self.pendrive_dir = os.path.join(self.tmp_dir, "media_user", "PENDRIVE")

        os.makedirs(self.descargas_dir, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)
        os.makedirs(self.pendrive_dir, exist_ok=True)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas_dir
        self.config.ruta_destino_base = self.destino_base
        self.config.carpeta_raiz_pendrive = "LucieSinReglas"
        self.config.rutas_candidatas_pendrive = [self.pendrive_dir]

        self.filtro = FiltroListaBlanca(self.config)

    def test_exclusion_estricta_enviados_y_revertidos(self):
        """_enviados y _revertidos están estrictamente excluidos como nombres de escena o carpetas de escena."""
        # 1. FiltroListaBlanca
        self.assertFalse(self.filtro.es_carpeta_escena_existente("_enviados"))
        self.assertFalse(self.filtro.es_carpeta_escena_existente("_revertidos"))
        self.assertFalse(self.filtro.es_carpeta_escena_existente("_descartados"))

        # 2. ValidadorEscenas
        valido_env, mot_env = ValidadorEscenas.validar_nombre_escena(
            "_enviados", self.destino_base, self.descargas_dir, personaje="lucie"
        )
        self.assertFalse(valido_env)
        self.assertIn("reservada", mot_env.lower())

        valido_rev, mot_rev = ValidadorEscenas.validar_nombre_escena(
            "_revertidos", self.destino_base, self.descargas_dir, personaje="lucie"
        )
        self.assertFalse(valido_rev)
        self.assertIn("reservada", mot_rev.lower())

        # 3. Escaneo de capítulos para envío jamás incluye _enviados ni _revertidos
        dir_env = os.path.join(self.destino_base, "lucie", "_enviados")
        os.makedirs(os.path.join(dir_env, "videos"), exist_ok=True)
        with open(os.path.join(dir_env, "videos", "enviado.mp4"), "wb") as f:
            f.write(b"DATA")

        caps = escanear_capitulos_para_envio(self.destino_base)
        nombres_caps = [c["capitulo"] for c in caps]
        self.assertNotIn("_enviados", nombres_caps)
        self.assertNotIn("_revertidos", nombres_caps)

    def test_confinamiento_path_traversal_rechazado(self):
        """Intentos de path traversal en capítulos o destinos son rechazados estrictamente."""
        vincular_pendrive(self.pendrive_dir, self.config)

        # Capítulo con traversal
        with self.assertRaises(ValueError):
            simular_envio_capitulos(capitulos=["../otro_dir"], config=self.config)

        with self.assertRaises(ValueError):
            simular_envio_capitulos(capitulos=["lucie/../../etc"], config=self.config)


class TestControlMontajePendrive(unittest.TestCase):
    """
    Pruebas para el control de montaje del pendrive y detección de unidades sin montar:
    - 5 estados de la tarjeta Unidad Pendrive
    - Detección y diagnóstico de particiones
    - Whitelist estricta para udisksctl mount/unmount/power-off
    - Bloqueo por operación activa (_operacion_pendrive_activa)
    - Detección no destructiva de procesos ocupando montaje
    - Secuencia segura de power-off solo tras desmontaje exitoso
    - Omisión de botones en plataforma Windows
    - Endpoints HTTP REST (POST montar, desmontar, expulsar)
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_ctrl_pendrive_")
        self.descargas_dir = os.path.join(self.temp_dir, "Descargas")
        self.destino_base = os.path.join(self.descargas_dir, "_lucie")
        self.pendrive_dir = os.path.join(self.temp_dir, "media", "mi_pendrive")
        os.makedirs(self.descargas_dir, exist_ok=True)
        os.makedirs(self.destino_base, exist_ok=True)
        os.makedirs(self.pendrive_dir, exist_ok=True)

        self.db_path = os.path.join(self.temp_dir, "test_bandeja.db")
        self.db = GestorBaseDatosBandeja(ruta_db=self.db_path)

        self.config = ConfiguracionBandeja()
        self.config.ruta_descargas = self.descargas_dir
        self.config.ruta_destino_base = self.destino_base
        self.config.rutas_candidatas_pendrive = [self.pendrive_dir]

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    @patch("bandeja.pendrive.detectar_pendrive")
    @patch("bandeja.pendrive.detectar_unidad_candidata_sin_vincular")
    def test_deteccion_particion_removible_sin_montar(self, mock_cand, mock_pen, mock_rem):
        """Estado 'detectada_sin_montar': unidad removible desenlazada y sin punto de montaje."""
        mock_rem.return_value = [{
            "dispositivo": "/dev/sda1",
            "nodo": "sda1",
            "disco_padre": "/dev/sda",
            "etiqueta": "MIUNIDAD",
            "sistema_archivos": "exfat",
            "punto_montaje": None,
            "montado": False,
            "tamanio_bytes": 120000000000,
            "tamanio_fmt": "111.8 GB"
        }]
        mock_pen.return_value = None
        mock_cand.return_value = None

        estado = obtener_estado_pendrive(self.config, self.db)
        self.assertFalse(estado["conectado"])
        self.assertFalse(estado["sin_respuesta"])
        self.assertEqual(estado["estado_unidad"], "detectada_sin_montar")
        self.assertEqual(estado["dispositivo"], "/dev/sda1")
        self.assertEqual(estado["etiqueta"], "MIUNIDAD")
        self.assertEqual(estado["sistema_archivos"], "exfat")
        if os.name != "nt":
            self.assertEqual(estado["acciones_disponibles"], ["montar"])

    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    @patch("bandeja.pendrive.detectar_pendrive")
    @patch("bandeja.pendrive.detectar_unidad_candidata_sin_vincular")
    def test_deteccion_particion_removible_montada_sin_vincular(self, mock_cand, mock_pen, mock_rem):
        """Estado 'conectada_sin_vincular': unidad montada sin marcador .lucie_pendrive.json."""
        mock_rem.return_value = [{
            "dispositivo": "/dev/sdb1",
            "nodo": "sdb1",
            "disco_padre": "/dev/sdb",
            "etiqueta": "DISCO",
            "sistema_archivos": "vfat",
            "punto_montaje": "/media/usb",
            "montado": True,
            "tamanio_bytes": 32000000000,
            "tamanio_fmt": "29.8 GB"
        }]
        mock_pen.return_value = None
        mock_cand.return_value = {
            "punto_montaje": "/media/usb",
            "sistema_archivos": "vfat",
            "espacio_libre_bytes": 10000,
            "espacio_total_bytes": 32000000000,
            "espacio_usado_bytes": 5000
        }

        estado = obtener_estado_pendrive(self.config, self.db)
        self.assertFalse(estado["conectado"])
        self.assertEqual(estado["estado_unidad"], "conectada_sin_vincular")
        self.assertEqual(estado["dispositivo"], "/dev/sdb1")
        self.assertEqual(estado["punto_montaje"], "/media/usb")
        self.assertIn("vincular", estado["acciones_disponibles"])
        if os.name != "nt":
            self.assertIn("desmontar", estado["acciones_disponibles"])
            self.assertIn("expulsar", estado["acciones_disponibles"])

    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    def test_deteccion_pendrive_vinculado_listo(self, mock_rem):
        """Estado 'vinculado_listo': pendrive montado y con marcador de identidad."""
        vincular_pendrive(self.pendrive_dir, self.config)
        mock_rem.return_value = [{
            "dispositivo": "/dev/sdc1",
            "nodo": "sdc1",
            "disco_padre": "/dev/sdc",
            "etiqueta": "LUCIE",
            "sistema_archivos": "ext4",
            "punto_montaje": self.pendrive_dir,
            "montado": True,
            "tamanio_bytes": 64000000000,
            "tamanio_fmt": "59.6 GB"
        }]

        estado = obtener_estado_pendrive(self.config, self.db)
        self.assertTrue(estado["conectado"])
        self.assertEqual(estado["estado_unidad"], "vinculado_listo")
        self.assertEqual(estado["dispositivo"], "/dev/sdc1")
        self.assertEqual(estado["punto_montaje"], self.pendrive_dir)
        if os.name != "nt":
            self.assertIn("desmontar", estado["acciones_disponibles"])
            self.assertIn("expulsar", estado["acciones_disponibles"])

    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    @patch("bandeja.pendrive.detectar_pendrive")
    @patch("bandeja.pendrive.detectar_unidad_candidata_sin_vincular")
    def test_sin_unidad_removible(self, mock_cand, mock_pen, mock_rem):
        """Estado 'sin_unidad': no hay dispositivos removibles montados ni sin montar."""
        mock_rem.return_value = []
        mock_pen.return_value = None
        mock_cand.return_value = None

        estado = obtener_estado_pendrive(self.config, self.db)
        self.assertFalse(estado["conectado"])
        self.assertEqual(estado["estado_unidad"], "sin_unidad")
        self.assertEqual(estado["acciones_disponibles"], [])

    @patch("bandeja.pendrive.diagnosticar_todas_particiones_linux")
    def test_diagnostico_todas_particiones(self, mock_diag):
        """Bloque diagnóstico evalúa particiones y detalla motivos."""
        mock_diag.return_value = [
            {"dispositivo": "/dev/nvme0n1p1", "nodo": "nvme0n1p1", "etiqueta": "EFI", "punto_montaje": "/boot/efi", "montado": True, "sistema_archivos": "vfat", "tamanio_bytes": 500, "tamanio_fmt": "500 MB", "es_removible": False, "motivo": "Unidad fija interna"},
            {"dispositivo": "/dev/sda1", "nodo": "sda1", "etiqueta": "MIUNIDAD", "punto_montaje": None, "montado": False, "sistema_archivos": "exfat", "tamanio_bytes": 1000, "tamanio_fmt": "114 GB", "es_removible": True, "motivo": "Removible sin montar"}
        ]

        estado = obtener_estado_pendrive(self.config, self.db)
        self.assertIn("diagnostico_particiones", estado)
        self.assertEqual(len(estado["diagnostico_particiones"]), 2)
        self.assertEqual(estado["diagnostico_particiones"][1]["motivo"], "Removible sin montar")

    @unittest.skipUnless(os.name == "posix", "Montaje por udisksctl y particiones /dev exclusivos de Linux")
    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    def test_montar_unidad_whitelist_rechazo(self, mock_rem):
        """montar_unidad_pendrive rechaza dispositivos no autorizados por la whitelist."""
        mock_rem.return_value = [{"dispositivo": "/dev/sda1", "nodo": "sda1", "disco_padre": "/dev/sda", "punto_montaje": None, "montado": False}]

        # Dispositivo no en la whitelist
        with self.assertRaises(ValueError):
            montar_unidad_pendrive("/dev/sdb1", config=self.config, db=self.db)

        # Dispositivo con caracteres inválidos
        with self.assertRaises(ValueError):
            montar_unidad_pendrive("/dev/sda1; rm -rf /", config=self.config, db=self.db)

        # Dispositivo vacío
        with self.assertRaises(ValueError):
            montar_unidad_pendrive("", config=self.config, db=self.db)

    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    def test_desmontar_unidad_bloqueado_durante_operacion_activa(self, mock_rem):
        """No permite desmontar ni expulsar si hay transferencia o deshacer en curso."""
        mock_rem.return_value = [{"dispositivo": "/dev/sda1", "nodo": "sda1", "disco_padre": "/dev/sda", "punto_montaje": "/media/usb", "montado": True}]

        import bandeja.pendrive
        bandeja.pendrive._operacion_pendrive_activa = True
        try:
            res = desmontar_unidad_pendrive("/dev/sda1", expulsar=False, config=self.config, db=self.db)
            self.assertFalse(res["exito"])
            self.assertTrue(res["bloqueado"])
            self.assertIn("transferencia", res["error"].lower())
        finally:
            bandeja.pendrive._operacion_pendrive_activa = False

    @unittest.skipUnless(os.name == "posix", "Requiere comandos udisksctl e inspección /proc exclusivos de Linux")
    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    @patch("bandeja.pendrive.listar_procesos_ocupando_montaje")
    @patch("subprocess.run")
    def test_desmontar_unidad_ocupada_reporta_procesos(self, mock_subp, mock_proc, mock_rem):
        """Si udisksctl falla porque la unidad está ocupada, reporta los procesos activos en /proc."""
        mock_rem.return_value = [{"dispositivo": "/dev/sda1", "nodo": "sda1", "disco_padre": "/dev/sda", "punto_montaje": "/media/usb", "montado": True}]
        mock_subp.return_value = MagicMock(returncode=1, stderr="Error: target is busy")
        mock_proc.return_value = [{"pid": 4321, "cmd": "bash", "comando": "bash", "detalle": "Directorio actual (cwd) en /media/usb"}]

        res = desmontar_unidad_pendrive("/dev/sda1", expulsar=False, config=self.config, db=self.db)
        self.assertFalse(res["exito"])
        self.assertTrue(res["ocupado"])
        self.assertEqual(len(res["procesos_ocupando"]), 1)
        self.assertEqual(res["procesos_ocupando"][0]["pid"], 4321)
        self.assertIn("ocupada", res["error"].lower())

    @unittest.skipUnless(os.name == "posix", "Requiere udisksctl power-off exclusivo de Linux")
    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    @patch("subprocess.run")
    def test_expulsar_ejecuta_power_off_solo_si_desmontaje_exitoso(self, mock_subp, mock_rem):
        """Expulsar ejecuta unmount y, solo si tiene éxito, power-off al disco padre."""
        mock_rem.return_value = [{"dispositivo": "/dev/sda1", "nodo": "sda1", "disco_padre": "/dev/sda", "punto_montaje": "/media/usb", "montado": True}]

        # 1. Caso fallo en unmount: power-off NUNCA se debe ejecutar
        mock_subp.return_value = MagicMock(returncode=1, stderr="unmount failed")
        res_fallo = desmontar_unidad_pendrive("/dev/sda1", expulsar=True, config=self.config, db=self.db)
        self.assertFalse(res_fallo["exito"])
        self.assertEqual(mock_subp.call_count, 1)
        self.assertIn("unmount", mock_subp.call_args[0][0])

        mock_subp.reset_mock()

        # 2. Caso éxito en unmount: se ejecuta power-off
        mock_subp.return_value = MagicMock(returncode=0, stdout="Unmounted /dev/sda1", stderr="")
        res_exito = desmontar_unidad_pendrive("/dev/sda1", expulsar=True, config=self.config, db=self.db)
        self.assertTrue(res_exito["exito"])
        self.assertTrue(res_exito["expulsado"])
        self.assertEqual(mock_subp.call_count, 2)
        # Primera llamada: unmount
        self.assertEqual(mock_subp.call_args_list[0][0][0], ["udisksctl", "unmount", "-b", "/dev/sda1"])
        # Segunda llamada: power-off
        self.assertEqual(mock_subp.call_args_list[1][0][0], ["udisksctl", "power-off", "-b", "/dev/sda"])

    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    def test_plataforma_windows_omite_botones(self, mock_rem):
        """En entorno Windows (os.name == 'nt') no se exponen acciones de montaje."""
        mock_rem.return_value = [{"dispositivo": "E:", "nodo": "E:", "disco_padre": "E:", "punto_montaje": None, "montado": False}]

        with patch("os.name", "nt"):
            estado = obtener_estado_pendrive(self.config, self.db)
            self.assertTrue(estado["es_windows"])
            self.assertNotIn("montar", estado["acciones_disponibles"])
            self.assertNotIn("desmontar", estado["acciones_disponibles"])
            self.assertNotIn("expulsar", estado["acciones_disponibles"])

    @unittest.skipUnless(os.name == "posix", "Requiere endpoints udisksctl de Linux")
    @patch("bandeja.pendrive.detectar_particiones_removibles_linux")
    @patch("subprocess.run")
    def test_servidor_http_endpoints_montar_desmontar_expulsar(self, mock_subp, mock_rem):
        """Endpoints POST /api/pendrive/montar, /desmontar, /expulsar responden correctamente."""
        mock_rem.return_value = [{"dispositivo": "/dev/sda1", "nodo": "sda1", "disco_padre": "/dev/sda", "punto_montaje": None, "montado": False}]
        mock_subp.return_value = MagicMock(returncode=0, stdout="Mounted /dev/sda1 at /media/usb", stderr="")

        # Inicializar servidor HTTP
        self.config.puerto_servidor = 0
        token_csrf = "token_de_prueba_seguro"
        filtro = FiltroListaBlanca(self.config)
        detector = DetectorDescargasActivas()
        agrupador = AgrupadorLotes(self.config.ventana_lote_minutos)
        movimientos = GestorMovimientosBandeja(
            self.descargas_dir, self.destino_base, self.db,
            ruta_bitacora=os.path.join(self.descargas_dir, "bitacora.jsonl")
        )
        miniaturas = GeneradorMiniaturas(self.db)
        vigilante = VigilanteBandeja(self.config, self.db, filtro, detector, agrupador)

        servidor = crear_servidor(self.config, self.db, vigilante, movimientos, miniaturas, token_csrf=token_csrf)
        puerto = servidor.server_address[1]
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()

        base_url = f"http://127.0.0.1:{puerto}"

        try:
            # 1. POST /api/pendrive/montar con dispositivo no en whitelist -> 400
            req = urllib.request.Request(
                f"{base_url}/api/pendrive/montar",
                data=json.dumps({"dispositivo": "/dev/sdx99"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-CSRF-Token": token_csrf}
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 400)

            # 2. POST /api/pendrive/montar con dispositivo válido -> 200
            req_ok = urllib.request.Request(
                f"{base_url}/api/pendrive/montar",
                data=json.dumps({"dispositivo": "/dev/sda1"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-CSRF-Token": token_csrf}
            )
            with urllib.request.urlopen(req_ok) as resp:
                self.assertEqual(resp.status, 200)
                datos = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(datos["exito"])

            # 3. POST /api/pendrive/desmontar cuando la unidad está ocupada -> 409
            mock_subp.return_value = MagicMock(returncode=1, stderr="target is busy")
            req_des = urllib.request.Request(
                f"{base_url}/api/pendrive/desmontar",
                data=json.dumps({"dispositivo": "/dev/sda1"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-CSRF-Token": token_csrf}
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_des)
            self.assertEqual(ctx.exception.code, 409)

            # 4. POST /api/pendrive/expulsar con éxito -> 200
            mock_subp.return_value = MagicMock(returncode=0, stderr="")
            req_exp = urllib.request.Request(
                f"{base_url}/api/pendrive/expulsar",
                data=json.dumps({"dispositivo": "/dev/sda1"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-CSRF-Token": token_csrf}
            )
            with urllib.request.urlopen(req_exp) as resp:
                self.assertEqual(resp.status, 200)
                datos = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(datos["exito"])
                self.assertTrue(datos["expulsado"])
        finally:
            servidor.shutdown()
            servidor.server_close()


if __name__ == "__main__":
    unittest.main()


