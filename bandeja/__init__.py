#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paquete modular bandeja para el proyecto Lucie.

Organización segura de descargas hacia la jerarquía de personaje y escena,
cumpliendo estrictamente con las Reglas de Oro anti-borrado.
"""

from bandeja.plataforma import (
    notificar_escritorio,
    obtener_sistema_archivos,
    obtener_espacio_disco,
    buscar_puntos_montaje_candidatos,
    detectar_particiones_removibles_linux,
    diagnosticar_todas_particiones_linux,
    obtener_disco_padre_particion,
    listar_procesos_ocupando_montaje,
)

from bandeja.config import (
    RUTA_DESCARGAS_DEFECTO,
    RUTA_DESTINO_DEFECTO,
    CARPETA_RAIZ_PENDRIVE_DEFECTO,
    EXTENSIONES_MEDIA_DEFECTO,
    EXTENSIONES_IMAGENES_DEFECTO,
    EXTENSIONES_VIDEOS_DEFECTO,
    EXTENSIONES_TEMP_DEFECTO,
    NOMBRES_RESERVADOS_WINDOWS,
    CARACTERES_INVALIDOS_ESCENA,
    ErrorSeguridadBandeja,
    ErrorValidacionEscena,
    ErrorDeshacer,
    calcular_sha256,
    formatear_bytes,
    ConfiguracionBandeja,
)

from bandeja.db import GestorBaseDatosBandeja

from bandeja.clasificacion import (
    clasificar_familia_medio,
    FiltroListaBlanca,
    ValidadorEscenas,
    asegurar_carpeta_capitulo,
)

from bandeja.lotes import (
    obtener_fecha_llegada,
    DetectorDescargasActivas,
    AgrupadorLotes,
)

from bandeja.capitulos import (
    calcular_balance_capitulo,
    es_capitulo_olvidado,
    simular_descartar_capitulo,
    ejecutar_descartar_capitulo,
    revertir_descarte_capitulo,
)

from bandeja.movimientos import (
    generar_html_simulacion,
    GestorMovimientosBandeja,
)

from bandeja.pendrive import (
    NOMBRE_MARCADOR_PENDRIVE,
    NOMBRE_MANIFIESTO_PENDRIVE,
    validar_marcador_pendrive,
    leer_marcador_pendrive,
    detectar_pendrive,
    detectar_pendrive_seguro,
    detectar_unidad_candidata_sin_vincular,
    simular_vinculacion_pendrive,
    vincular_pendrive,
    leer_manifiesto_pendrive,
    escanear_capitulos_para_envio,
    escanear_sala_espera_carpetas,
    listar_archivos_part_huerfanos,
    obtener_estado_pendrive,
    simular_envio_capitulos,
    ejecutar_envio_pendrive,
    deshacer_envio_pendrive,
    montar_unidad_pendrive,
    desmontar_unidad_pendrive,
    ejecutar_lectura_pendrive_con_timeout,
)

from bandeja.vigilante import VigilanteBandeja

from bandeja.servidor import (
    GeneradorMiniaturas,
    HandlerServidorBandeja,
    crear_servidor,
)

__all__ = [
    # Plataforma
    "notificar_escritorio",
    "obtener_sistema_archivos",
    "obtener_espacio_disco",
    "buscar_puntos_montaje_candidatos",
    "detectar_particiones_removibles_linux",
    "diagnosticar_todas_particiones_linux",
    "obtener_disco_padre_particion",
    "listar_procesos_ocupando_montaje",
    # Configuración y constantes
    "RUTA_DESCARGAS_DEFECTO",
    "RUTA_DESTINO_DEFECTO",
    "CARPETA_RAIZ_PENDRIVE_DEFECTO",
    "EXTENSIONES_MEDIA_DEFECTO",
    "EXTENSIONES_IMAGENES_DEFECTO",
    "EXTENSIONES_VIDEOS_DEFECTO",
    "EXTENSIONES_TEMP_DEFECTO",
    "NOMBRES_RESERVADOS_WINDOWS",
    "CARACTERES_INVALIDOS_ESCENA",
    "ErrorSeguridadBandeja",
    "ErrorValidacionEscena",
    "ErrorDeshacer",
    "calcular_sha256",
    "formatear_bytes",
    "ConfiguracionBandeja",
    # DB
    "GestorBaseDatosBandeja",
    # Clasificación
    "clasificar_familia_medio",
    "FiltroListaBlanca",
    "ValidadorEscenas",
    "asegurar_carpeta_capitulo",
    # Lotes
    "obtener_fecha_llegada",
    "DetectorDescargasActivas",
    "AgrupadorLotes",
    # Capítulos
    "calcular_balance_capitulo",
    "es_capitulo_olvidado",
    "simular_descartar_capitulo",
    "ejecutar_descartar_capitulo",
    "revertir_descarte_capitulo",
    # Movimientos
    "generar_html_simulacion",
    "GestorMovimientosBandeja",
    # Pendrive
    "NOMBRE_MARCADOR_PENDRIVE",
    "NOMBRE_MANIFIESTO_PENDRIVE",
    "validar_marcador_pendrive",
    "leer_marcador_pendrive",
    "detectar_pendrive",
    "detectar_pendrive_seguro",
    "detectar_unidad_candidata_sin_vincular",
    "simular_vinculacion_pendrive",
    "vincular_pendrive",
    "leer_manifiesto_pendrive",
    "escanear_capitulos_para_envio",
    "escanear_sala_espera_carpetas",
    "listar_archivos_part_huerfanos",
    "obtener_estado_pendrive",
    "simular_envio_capitulos",
    "ejecutar_envio_pendrive",
    "deshacer_envio_pendrive",
    "montar_unidad_pendrive",
    "desmontar_unidad_pendrive",
    "ejecutar_lectura_pendrive_con_timeout",
    # Vigilante
    "VigilanteBandeja",
    # Servidor
    "GeneradorMiniaturas",
    "HandlerServidorBandeja",
    "crear_servidor",
]
