# Tasks

## 1. Configuración, Lista Blanca y Base de Datos SQLite

- [x] 1.1 Crear `config_bandeja.json` con los patrones de candidatos ("grok-video-*", Nano Banana regex, Flow editable), extensiones de media, rutas y ventanas temporales, verificando su carga con prueba unitaria.
- [x] 1.2 Actualizar `.gitignore` para ignorar archivos `.jsonl` de bitácoras y registros de movimientos, verificando que `git status` no los rastree.
- [x] 1.3 Implementar la capa SQLite en `bandeja_descargas.py` para crear la tabla `bandeja_archivos` (id INTEGER PK, hash TEXT UNIQUE, ruta_actual TEXT, estado TEXT, personaje TEXT, escena TEXT, fecha TEXT) y registrar decisiones de archivos sin patrón, verificando su funcionamiento con tests unitarios.
- [x] 1.4 Implementar `FiltroListaBlanca` en `bandeja_descargas.py` para admitir exclusivamente extensiones multimedia autorizadas y patrones coincidentes, verificando que archivos fuera de la lista blanca (.pdf, .zip, etc.) se descarten sin ser leídos ni hasheados.

## 2. Detección, Estabilidad de Descargas, Agrupación y Validación de Escenas

- [x] 2.1 Implementar `DetectorDescargasActivas` para descartar archivos `.crdownload`, `.part`, `.tmp` y archivos con mutaciones de tamaño en los últimos 5 segundos, verificando la detección de archivos inestables con pruebas unitarias.
- [x] 2.2 Implementar `AgrupadorLotes` para agrupar candidatos estables por cercanía de `mtime` dentro de la ventana configurable de 10 minutos, verificando la partición de lotes con tests unitarios.
- [x] 2.3 Implementar la detección de escenas existentes a partir de carpetas de primer nivel con alias en `~/Descargas` y subcarpetas ya existentes en el destino, verificando que se listen como opciones sin moverlas.
- [x] 2.4 Implementar `ValidadorEscenas` para validar y rechazar nombres con "/", "\", "..", caracteres de control, caracteres inválidos en Windows/exFAT (< > : " | ? *), terminación en punto o espacio, nombres reservados (CON, PRN, AUX, NUL, COM1-9, LPT1-9) o de más de 100 caracteres, y verificar con realpath que el destino final resida dentro de `<destino>`, verificando con tests unitarios.
- [x] 2.5 Implementar la rutina de vigilancia periódica (polling) e integración con `notify-send` si está disponible en el sistema, verificando el flujo de notificación con mocks en tests unitarios.

## 3. Movimiento Seguro, Bitácora y Reversibilidad

- [x] 3.1 Implementar `GestorMovimientosBandeja` con confinamiento estricto de rutas a `~/Descargas` mediante `os.path.realpath`, verificando el rechazo de rutas externas con tests unitarios.
- [x] 3.2 Implementar la simulación previa y resolución de destino según tipo de archivo: videos a '<destino>/<personaje>/videos sin editar/<escena>/' e imágenes a '<destino>/<personaje>/<carpeta_imagenes>/<escena>/' (con 'carpeta_imagenes' configurable en config_bandeja.json, por defecto 'imagenes'), repartiendo lotes mixtos y aplicando sufijos numéricos correlativos ante colisiones.
- [x] 3.3 Implementar la ejecución de movimientos exclusivamente con `os.rename` y el asentamiento en la bitácora `.jsonl`, verificando que el archivo se reubique sin duplicar ni borrar.
- [x] 3.4 Implementar la función de deshacer (undo) con `os.rename`, verificando que si la ruta original ya está ocupada se rechace la operación con mensaje explicativo, sin pisar ni sufijar jamás.

## 4. Servidor HTTP Local, Seguridad CSRF y Panel Web Interactivo

- [x] 4.1 Implementar la generación del token anti-CSRF aleatorio al iniciar el servidor e inyección en la SPA, y el middleware de seguridad que valida cabecera `X-CSRF-Token`, `Content-Type: application/json` y `Host: 127.0.0.1:<puerto>` en todos los endpoints POST, respondiendo 403 Forbidden ante cualquier fallo.
- [x] 4.2 Implementar el endpoint seguro `/api/miniatura` que recibe exclusivamente el `id` numérico de un archivo registrado en la base SQLite (nunca una ruta) e invoca `ffmpeg` con `subprocess.run`, sin `shell=True` y con `--` antes del nombre de archivo.
- [x] 4.3 Implementar los endpoints REST en `bandeja_descargas.py` (`/api/lotes`, `/api/sin-identificar`, `/api/escenas`, `/api/personajes`, `/api/clasificar-sin-identificar`, `/api/simular-mover`, `/api/mover-lote`, `/api/deshacer`), verificando sus respuestas en JSON y códigos de estado.
- [x] 4.4 Desarrollar la interfaz web SPA en tema oscuro con lista de lotes, miniaturas seguras, selectores de personaje y escena (existente o nueva con validación visual), preselección del último personaje utilizado, modal de simulación previa, botón "Mover lote" y pestaña "Sin identificar".

## 5. Pruebas Unitarias Iniciales y Auditoría AST

- [x] 5.1 Crear en `test_bandeja_descargas.py` pruebas unitarias en `/tmp` para la validación exhaustiva de nombres de escena (caracteres prohibidos, nombres reservados Windows, trailing dot/space, longitud > 100 y realpath confinada).
- [x] 5.2 Crear en `test_bandeja_descargas.py` pruebas para la protección anti-CSRF, validación de cabeceras Host y Content-Type, verificando que solicitudes POST sin token o con Host foráneo respondan 403 Forbidden.
- [x] 5.3 Crear en `test_bandeja_descargas.py` pruebas para `/api/miniatura` asegurando que rechace rutas directas, solo acepte IDs registrados y construya el comando de `ffmpeg` seguro con `--` y sin shell.
- [x] 5.4 Crear en `test_bandeja_descargas.py` pruebas para el enrutamiento según tipo de archivo (videos a 'videos sin editar', imágenes a 'carpeta_imagenes' configurable, partición en lote mixto) y escenas existentes en Descargas.
- [x] 5.5 Crear en `test_bandeja_descargas.py` pruebas para la función de deshacer, confirmando que si la ruta original está ocupada se rechaza con error claro, sin pisar ni sufijar jamás.
- [x] 5.6 Crear en `test_bandeja_descargas.py` pruebas para la lista blanca, estabilidad de descargas (5s) y agrupación temporal de lotes.
- [x] 5.7 Integrar `bandeja_descargas.py` en la auditoría estática AST anti-borrado de `seguridad_anti_borrado.py`, verificando que mantenga 0 violaciones de las 11 primitivas prohibidas.
- [x] 5.8 Ejecutar la suite completa de pruebas del proyecto (`test_plan_limpieza.py`, `test_inventario.py`, `test_bandeja_descargas.py`) asegurando que pasen al 100%.

## 6. Selección Granular de Archivos por Lote y Retención de Pendientes

- [x] 6.1 Incorporar en la SPA casillas de verificación individuales para cada archivo en la cuadrícula de lotes (marcadas por defecto), tooltip de metadatos (nombre completo y fecha/hora exacta al pasar el cursor) y botones "Seleccionar todos" y "Ninguno", verificando su comportamiento en el navegador.
- [x] 6.2 Actualizar dinámicamente el botón de acción a "Mover seleccionados (N)", deshabilitándolo con `disabled=true` cuando N = 0, y verificando que el modal de simulación previa reciba y muestre exclusivamente los archivos marcados con origen y destino exactos.
- [x] 6.3 Ajustar la lógica del servidor y re-escaneo para que los archivos no seleccionados del lote permanezcan en `~/Descargas` y se muestren como lote pendiente conservando su ventana temporal y agrupación, verificando con prueba unitaria en `/tmp`.

## 7. Pestaña Historial y Acciones de Reversión Visibles

- [x] 7.1 Implementar en `HandlerServidorBandeja` el endpoint `GET /api/historial` para leer y procesar las últimas 50 entradas de `bitacora_bandeja.jsonl`, entregando fecha, archivo, origen anterior, destino nuevo y estado ("movido" o "deshecho"), verificando la respuesta JSON con test unitario.
- [x] 7.2 Crear en la barra de navegación la pestaña "Historial" y renderizar una tabla reactiva con los últimos 50 movimientos, integrando un botón individual "Deshacer" en cada fila activa que invoque `/api/deshacer` enviando el token anti-CSRF, verificando la reversión en interfaz.
- [x] 7.3 Implementar el botón "Deshacer último lote" en la cabecera de la pestaña Historial para revertir en un solo paso la última operación realizada, verificando la reversión en la bitácora.
- [x] 7.4 Asegurar que si la ruta original está ocupada, la SPA capture la respuesta HTTP 409 y presente el mensaje de negativa descriptivo devuelto por el servidor ("No se puede deshacer: la ruta original ... ya se encuentra ocupada"), verificando con test unitario.

## 8. Validación Anticipada y Mensajes en Línea para Nuevas Escenas

- [x] 8.1 Implementar en la SPA la validación en tiempo real del campo `txt-nueva-escena-${loteId}` ante el evento input y al pulsar el botón de mover, mostrando un contenedor de error debajo del campo si está vacío o si contiene caracteres prohibidos o reservados.
- [x] 8.2 Bloquear la apertura del modal de simulación previa si el nombre de escena es inválido o está vacío, verificando que no se emita la petición a `/api/simular-mover` hasta que el nombre sea corregido.

## 9. Pruebas Unitarias de Regresión y Auditoría AST

- [x] 9.1 Agregar en `test_bandeja_descargas.py` la prueba unitaria que verifique que mover un subconjunto de archivos de un lote deja el resto en la bandeja como lote pendiente sin perder su agrupación.
- [x] 9.2 Agregar en `test_bandeja_descargas.py` la prueba unitaria del endpoint `GET /api/historial` comprobando que liste adecuadamente los últimos movimientos registrados en la bitácora `.jsonl`.
- [x] 9.3 Agregar en `test_bandeja_descargas.py` la prueba que verifique que `/api/deshacer` responda 403 Forbidden si no se envía el token anti-CSRF o si el header Host no es local.
- [x] 9.4 Agregar en `test_bandeja_descargas.py` la prueba de negativa de deshacer cuando la ruta original se encuentra ocupada, validando que no se sobrescriba ni se muten archivos.
- [x] 9.5 Ejecutar `seguridad_anti_borrado.py` verificando que el total de violaciones de primitivas destructivas en el repositorio permanezca estrictamente en 0.
- [x] 9.6 Ejecutar la suite completa de pruebas unitarias (`python3 -m unittest discover -s . -p "test_*.py"`) confirmando el 100% de éxito.

## 10. Aviso Fijo Superior tras Mover Lote y Deshacer Inmediato

- [x] 10.1 Actualizar `ejecutar_movimiento_lote` en `bandeja_descargas.py` para devolver `personaje`, `escena` y `total_movidos` en el resultado JSON de `/api/mover-lote`.
- [x] 10.2 Añadir en la SPA el componente de aviso fijo superior `#banner-aviso` con estilos CSS, texto `"Se movieron N archivos a <personaje>/<escena>"`, botón "Deshacer" con token anti-CSRF y botón de cierre "×".
- [x] 10.3 Gestionar la persistencia del aviso (visible hasta cierre manual o reemplazo por un nuevo lote) y el ocultamiento tras reversión exitosa, manteniendo la disponibilidad en la pestaña Historial.
- [x] 10.4 Agregar en `test_bandeja_descargas.py` las pruebas unitarias que verifiquen la generación del aviso con la cantidad correcta de archivos y destino tras mover un lote, y la reversión completa de todos los archivos al deshacer desde el aviso.
- [x] 10.5 Verificar que la auditoría AST anti-borrado (`seguridad_anti_borrado.py`) mantenga 0 violaciones y que toda la suite de pruebas unitarias pase al 100%.

## 11. Modal de Simulación Ampliado, Rutas Relativas y Resaltado de Segmentos

- [x] 11.1 Ensanchar el modal de simulación previa en la SPA hasta 90% del ancho de pantalla (90vw, máximo 1200px) y altura máxima de 85vh con desplazamiento vertical.
- [x] 11.2 Configurar el ajuste de texto en celdas de rutas mediante `word-break: break-word` y `overflow-wrap: anywhere` para evitar desbordes y barras de desplazamiento horizontal.
- [x] 11.3 Mostrar el destino relativo a la carpeta destino base (`<personaje>/<subcarpeta_tipo>/<escena>/<archivo>`) y conservar la ruta absoluta completa en el atributo `title` (tooltip) y `data-destino`.
- [x] 11.4 Resaltar visualmente con etiquetas estilizadas (`tag-tipo`, `tag-video`, `tag-imagen`) los segmentos de tipo ("imagenes" o "videos sin editar") en la columna de destino.
- [x] 11.5 Implementar `generar_html_simulacion` en el servidor con renderizado seguro y fallback reactivo en el cliente.
- [x] 11.6 Añadir pruebas unitarias en `test_bandeja_descargas.py` que comprueben la inclusión de la ruta completa en el tooltip del HTML de simulación, las rutas relativas y el resaltado de tipo.
- [x] 11.7 Verificar la auditoría AST anti-borrado (0 violaciones) y la ejecución exitosa de toda la suite de pruebas del proyecto.

## 12. Capítulo Activo, Modo Respaldo por Alias Inicial, Mover Lotes Listos y Sala de Espera

- [ ] 12.1 Configuración y filtros: incorporar en `config_bandeja.json` y `ConfiguracionBandeja` la lista editable `"patrones_ignorar": ["Screenshot_*", "Captura*"]`, y agregar a los patrones candidatos del proyecto `"grok-video-*"`, `"grok-image-*"`, `"Gemini_Generated_Image_*"` y el patrón de 14 dígitos (Nano Banana). Comprobar que los archivos ignorados no aparezcan en la bandeja ni en "Sin identificar".
- [ ] 12.2 Persistencia de capítulo activo en base de datos: agregar en `GestorBaseDatosBandeja` los métodos para almacenar y consultar el estado del capítulo activo (`capitulo_activo_personaje`, `capitulo_activo_nombre`, `capitulo_activo_habilitado`) en `bandeja_estado`, garantizando que persista tras reiniciar el servidor.
- [ ] 12.3 Asignación automática por capítulo activo: actualizar `VigilanteBandeja` para que, mientras exista un capítulo activo, todo nuevo archivo candidato detectado se registre en SQLite asignado inmediatamente a `<personaje>/<capítulo>`, sin importar su nombre ni fecha, y asegurar que modificar o desactivar el capítulo no reasigne archivos previamente detectados.
- [ ] 12.4 Modo de respaldo por alias al inicio: en `FiltroListaBlanca`, deducir el personaje estrictamente del alias al INICIO del nombre (`lucie`, `luci`, `roli`, `laroli`, `magui`, `mailen`), verificando que menciones posteriores de otros personajes en el nombre (como en `"rolitirandoaguaalucie.jpg"`) no alteren el personaje inicial (`"roli"`).
- [ ] 12.5 Extracción de escena sugerida y agrupación por raíz: implementar la función de normalización del nombre (removiendo extensión, sufijo `" (n)"` de Chrome y números finales, conservando el prefijo) y actualizar `AgrupadorLotes` para agrupar primero por raíz compartida, aplicando la ventana de 10 minutos solo a archivos sin raíz reconocible y nunca juntando en un lote raíces distintas.
- [ ] 12.6 Sala de espera unificada sin subcarpetas de tipo: actualizar `GestorMovimientosBandeja` para trasladar videos e imágenes juntos directamente a `<destino>/<personaje>/<capítulo>/` sin crear subcarpetas `"videos sin editar"` ni `"imagenes"`, preservando el enrutamiento de escenas existentes en Descargas y validando nombres de capítulo.
- [ ] 12.7 Interfaz de usuario (panel SPA): agregar banner permanente con selector de personaje, campo "Capítulo actual", botones Activar y Desactivar, presentación de lotes con personaje y escena precompletados y editables, y botón "Mover lotes listos" que abre una única simulación de todos los lotes tildados con confirmación única, manteniendo el registro y la reversión independiente por lote.
- [ ] 12.8 Endpoints HTTP en `bandeja_descargas.py`: implementar `GET /api/capitulo-activo`, `POST /api/capitulo-activo`, y adaptar `/api/simular-mover` y `/api/mover-lote` para admitir operaciones multi-lote con token anti-CSRF.
- [ ] 12.9 Suite de pruebas unitarias en `test_bandeja_descargas.py`: implementar las pruebas de: asignación con capítulo activo sin importar nombre ni hora, no reasignación al cambiar capítulo, persistencia de capítulo activo al reiniciar servidor, separación en lotes distintos para raíces diferentes dentro de la ventana temporal, sugerencia de escena para `"lucie atendiendo (1).mp4"`, asignación de `"rolitirandoaguaalucie.jpg"` a `roli`, confirmación única de múltiples lotes, reversión por lote con deshacer, omisión de archivos ignorados, y 0 violaciones en la auditoría estática AST anti-borrado.


