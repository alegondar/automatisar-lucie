# Tasks: Adopción Exclusiva de Material Nuevo por Capítulo y Base de Nombre Compacta

- [x] 1. Configuración y Parámetros
  - [x] 1.1 Incorporar `"minutos_antes_inicio_capitulo": 0` en `config_bandeja.json`.
  - [x] 1.2 Mapear el atributo `minutos_antes_inicio_capitulo` en la clase `ConfiguracionBandeja` de `bandeja_descargas.py`.

- [x] 2. Lógica de Escaneo y Segregación Temporal
  - [x] 2.1 Calcular `ts_corte_capitulo` en `VigilanteBandeja.escanear` aplicando el margen configurado sobre `fecha_inicio`.
  - [x] 2.2 Evaluar `mtime` de cada archivo respecto al corte y marcar `es_anterior`.
  - [x] 2.3 Mantener archivos anteriores en modo de respaldo: sin asignación forzada al capítulo, sin preselección y con escena vacía.
  - [x] 2.4 Agrupar candidatos anteriores en `lotes_anteriores` con `es_anterior = True` y prefijo identificador `ant_`.
  - [x] 2.5 Retornar `lotes_anteriores` en el estado del vigilante y en el endpoint `/api/lotes`.

- [x] 3. Persistencia y Reapertura de Capítulos
  - [x] 3.1 Sincronizar `guardar_capitulo_activo` con la tabla `bandeja_capitulos` para registrar la fecha de inicio de forma inmediata.
  - [x] 3.2 Asegurar que `reabrir_capitulo` preserve la `fecha_inicio` original del capítulo para mantener el umbral cronológico.

- [x] 4. Renombrado Compacto de Archivos
  - [x] 4.1 Modificar `calcular_base_escena` para suprimir espacios internos mediante expresión regular (`\s+`).
  - [x] 4.2 Preservar el nombre de carpeta tal como fue ingresado por el usuario en la sala de espera.
  - [x] 4.3 Garantizar que el nombre compacto resultante sea correctamente reconocido por `obtener_personaje_de_alias_inicial`.

- [x] 5. Interfaz de Usuario y Controles del Panel
  - [x] 5.1 Agregar contenedor colapsable `<details id="details-anteriores">` en la plantilla HTML para "Anteriores al capítulo".
  - [x] 5.2 Implementar `renderLotesAnteriores()` en el script del panel con casillas destildadas y campos de escena vacíos.
  - [x] 5.3 Modificar `simularMoverLotesListos()` para ignorar estrictamente los lotes marcados como anteriores.
  - [x] 5.4 Permitir el movimiento manual de lotes anteriores individuales mediante `iniciarMover` identificando el prefijo `ant_`.

- [x] 6. Pruebas y Validación
  - [x] 6.1 Crear clase `TestCapituloSoloMaterialNuevo` en `test_bandeja_descargas.py`.
  - [x] 6.2 Probar adopción exclusiva de archivos posteriores y exclusión de anteriores.
  - [x] 6.3 Probar margen configurable de 0 y 10 minutos.
  - [x] 6.4 Probar candidato por patrón (Grok) anterior sin tildar y sin escena sugerida.
  - [x] 6.5 Probar que "Mover lotes listos" excluye lotes anteriores.
  - [x] 6.6 Probar que la reapertura de capítulos preserva la `fecha_inicio` histórica.
  - [x] 6.7 Probar cálculo de base compacta y consistencia con `obtener_personaje_de_alias_inicial`.
  - [x] 6.8 Ejecutar suite completa de pruebas unitarias (`test_*.py`) con 100% de éxito.
  - [x] 6.9 Ejecutar auditoría estática AST anti-borrado verificando 0 infracciones.
