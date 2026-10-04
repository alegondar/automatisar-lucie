# Spec Delta

## Purpose

Proporciona sincronización periódica reactiva del panel web mediante versionado liviano, preservando el estado de interacción del usuario, pausando el sondeo ante inactividad o modales, y garantizando una detección veloz y trazable de archivos en la bandeja de descargas.

## ADDED Requirements

### Requirement: Endpoint de versionado de estado (/api/estado-version)
El sistema SHALL proveer un endpoint HTTP `GET /api/estado-version` que devuelva un token hash o contador representativo de todos los elementos que afectan la vista del panel: lotes principales, lotes anteriores, conteo de archivos sin identificar, capítulos abiertos, cerrados y descartados, capítulo en foco, balance de pendientes y movidos, y alertas. Si ninguno de estos datos cambió, el token devuelto SHALL ser idéntico. El endpoint SHALL validar la cabecera Host y SHALL rechazar solicitudes POST con código 405.

#### Scenario: Token cambia al ingresar nuevo archivo
- **WHEN** un nuevo archivo multimedia o lote ingresa a la bandeja de descargas
- **THEN** la respuesta de `GET /api/estado-version` contiene un token diferente al anterior

#### Scenario: Token permanece idéntico si nada cambia
- **WHEN** se consulta repetidamente `GET /api/estado-version` sin modificaciones en la base ni en el directorio
- **THEN** el token devuelto es exactamente el mismo

#### Scenario: Validación de Host y rechazo de POST
- **WHEN** un cliente envía una petición con cabecera `Host` no autorizada o utiliza el método `POST`
- **THEN** el servidor responde con error 403 Forbidden o 405 Method Not Allowed respectivamente

### Requirement: Sondeo periódico en cliente con pausas inteligentes
La interfaz web SHALL consultar periódicamente `/api/estado-version` según el intervalo definido en `config_bandeja.json` bajo la clave `"refresco_panel_segundos"` (por defecto 4 segundos; 0 para desactivar). El cliente SHALL suspender las consultas periódicas mientras la pestaña se encuentre oculta (`document.hidden` verdadero) o mientras exista un cuadro modal abierto. Al volver a estar visible la pestaña (`visibilitychange`), el cliente SHALL ejecutar una consulta de actualización inmediata.

#### Scenario: Consulta periódica activa
- **WHEN** la pestaña se encuentra visible y no hay modales abiertos
- **THEN** el cliente consulta `/api/estado-version` cada 4 segundos sin reescanear el DOM a menos que el token cambie

#### Scenario: Pausa por pestaña oculta y reanudación
- **WHEN** la pestaña pasa a segundo plano (`document.hidden = true`)
- **THEN** no se realizan consultas de sondeo hasta que la pestaña vuelve al frente (`visibilitychange`), momento en el que se ejecuta una consulta inmediata

#### Scenario: Pausa durante modales abiertos
- **WHEN** el modal de simulación de movimiento, descartar capítulo o terminar capítulo está visible
- **THEN** el sondeo automático se pausa para evitar interferir con la decisión del usuario

### Requirement: Preservación del estado de interacción del usuario
Al redibujar los componentes de la vista tras detectar un cambio en el token de versión, el cliente SHALL conservar intactos: los checkboxes tildados o destildados de archivos preexistentes, el texto escrito en campos de escena nueva, las opciones elegidas en selectores desplegables de personaje y escena, el estado abierto o cerrado del elemento `<details id="details-anteriores">`, la pestaña activa seleccionada y la posición vertical del scroll. Los archivos recién arribados SHALL adoptar su selección predeterminada.

#### Scenario: Conservación de formularios y selecciones
- **WHEN** el usuario ha destildado un archivo existente, modificado un dropdown o escrito en un input de escena y se produce un refresco
- **THEN** los valores ingresados y el estado de selección de los archivos previos se mantienen sin pérdidas

#### Scenario: Actualización incremental en edición activa
- **WHEN** el usuario mantiene el foco o texto sin enviar en algún campo de edición de un lote
- **THEN** los nuevos lotes se insertan de manera incremental sin destruir ni reinicializar los controles del lote en edición

### Requirement: Indicadores de nuevos lotes y resiliencia de conexión
Cuando se reciban lotes nuevos mientras la pestaña esté en segundo plano, el sistema SHALL anteponer el prefijo `(N)` al título de la página (ej. `(1) Bandeja de Descargas`) y retirarlo al recuperar el foco. El panel SHALL mostrar un aviso discreto temporal indicando "Llegaron N archivo(s) nuevo(s)". Si el servidor no responde, el cliente SHALL mostrar una advertencia "Sin conexión con la bandeja" y reintentar con retroceso exponencial sin apilar peticiones.

#### Scenario: Notificación en título de pestaña
- **WHEN** entran nuevos lotes con la pestaña oculta
- **THEN** el título de la ventana se actualiza a `(N) Bandeja de Descargas` y vuelve al título normal al enfocar la pestaña

#### Scenario: Manejo de desconexión y reconexión
- **WHEN** el servidor deja de responder
- **THEN** se muestra el indicador "Sin conexión con la bandeja", se espacian los reintentos progresivamente y se recargan los datos automáticamente al restablecer el enlace

### Requirement: Detección veloz y trazabilidad con marcas de tiempo
El subsistema de vigilancia SHALL registrar eventos estructurados en el ciclo de vida de los archivos (`[DETECTADO]`, `[ESTABLE]`, `[REGISTRADO]`) con marcas de tiempo explícitas. Archivos completos y estables SHALL quedar registrados en la base de datos en menos de 10 segundos desde el fin de su escritura. Los archivos con extensiones temporales de descarga (`.crdownload`, `.part`, `.tmp`) SHALL ser ignorados de inmediato sin generar lotes.

#### Scenario: Archivo temporal no genera lote
- **WHEN** un archivo `.crdownload` o `.tmp` se crea o modifica en Descargas
- **THEN** el sistema lo ignora de inmediato y no genera ningún lote ni registro preliminar

#### Scenario: Archivo completo registrado rápidamente con trazabilidad
- **WHEN** un archivo multimedia finaliza su descarga en Descargas
- **THEN** pasa la validación de estabilidad en ~5 segundos y queda registrado en la base de datos con timestamps detallados en menos de 10 segundos
