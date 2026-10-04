# Spec Delta: Corte por Fecha de Llegada

## Purpose

Permite determinar con precisión la frescura del material multimedia ingresado a la bandeja de descargas evaluando la fecha de llegada efectiva mediante el máximo entre mtime y ctime, evitando falsos positivos de material viejo por timestamps de servidor en navegadores web.

## ADDED Requirements

### Requirement: Función unificada de fecha de llegada
El sistema SHALL proveer una única función de fecha de llegada efectiva que calcule el valor máximo entre `st_mtime` y `st_ctime` del archivo (`max(st_mtime, st_ctime)`).

#### Scenario: Archivo con mtime viejo y ctime reciente
- **WHEN** un archivo posee un timestamp de modificación `st_mtime` antiguo (ej. preservado por el navegador desde el servidor) pero su `st_ctime` local corresponde al momento de la descarga o creación en disco
- **THEN** la función devuelve el valor correspondiente a `st_ctime`.

#### Scenario: Archivo con ambos timestamps anteriores
- **WHEN** un archivo posee tanto `st_mtime` como `st_ctime` anteriores a una fecha de referencia
- **THEN** la función devuelve el valor máximo entre ambos.

### Requirement: Asignación y partición de material reciente vs anteriores por fecha de llegada
El sistema SHALL utilizar la fecha de llegada efectiva en todos los cortes temporales de discriminación entre material reciente y anterior, incluyendo la asignación automática al capítulo en foco y la sección "Anteriores".

#### Scenario: Archivo con mtime viejo pero ctime posterior al inicio del capítulo
- **WHEN** un archivo arriba con `mtime` anterior al inicio del capítulo en foco pero con `ctime` posterior al inicio del capítulo
- **THEN** el archivo es asignado al capítulo en foco, preseleccionado (tildado) en la lista principal de lotes y provisto de personaje y escena sugeridos.

#### Scenario: Archivo con mtime y ctime anteriores al inicio del capítulo
- **WHEN** un archivo arriba con `mtime` y `ctime` anteriores al inicio del capítulo en foco
- **THEN** el archivo queda clasificado en la sección "Anteriores al capítulo", destildado y sin escena precargada.

### Requirement: Corte por horas de material reciente
El sistema SHALL evaluar el umbral de antigüedad configurable `horas_material_reciente` basándose en la fecha de llegada efectiva del archivo.

#### Scenario: Archivo con mtime viejo y ctime reciente bajo límite de horas
- **WHEN** se encuentra configurado un límite en `horas_material_reciente` y un archivo tiene `mtime` anterior al límite pero `ctime` reciente dentro de la ventana de horas
- **THEN** el archivo es considerado material reciente y no es relegado a "Anteriores".

#### Scenario: Archivo con fecha de llegada fuera del límite de horas
- **WHEN** un archivo posee tanto `mtime` como `ctime` anteriores a la ventana definida por `horas_material_reciente`
- **THEN** el archivo es considerado material anterior.

### Requirement: Notificación de lotes nuevos exclusiva para lista principal
El sistema SHALL contabilizar y disparar la notificación de nuevos lotes listos para ordenar exclusivamente a partir de los lotes incorporados a la lista principal, excluyendo los lotes de la sección "Anteriores".

#### Scenario: Detección de lotes exclusivamente anteriores no dispara aviso
- **WHEN** el escaneo detecta únicamente archivos que se clasifican en la sección "Anteriores al capítulo"
- **THEN** no se emite ninguna notificación de escritorio sobre nuevos lotes listos para ordenar ni se incrementa el contador de lotes principales.

#### Scenario: Detección de lotes principales incrementa conteo y notifica
- **WHEN** el escaneo detecta uno o más lotes nuevos destinados a la lista principal
- **THEN** el sistema emite la notificación indicando la cantidad de lotes nuevos listos para ordenar.

### Requirement: Exposición de fecha de llegada en metadata e interfaz
El sistema SHALL exponer la fecha de llegada efectiva en la estructura de datos del archivo y mostrarla en la tarjeta o tooltip del elemento visual en la interfaz de usuario.

#### Scenario: Visualización de fecha de llegada en tooltip
- **WHEN** el usuario inspecciona un archivo en la grilla de un lote
- **THEN** el tooltip o tarjeta del archivo muestra la fecha de llegada efectiva utilizada por el sistema.

### Requirement: Distintivo visual del banner en foco
El banner superior del capítulo en foco SHALL presentar el mismo distintivo visual amarillo con estrella (`⭐ EN FOCO`) que utiliza la tabla de Capítulos Abiertos, manteniendo el aviso de cantidad de capítulos abiertos secundarios `(+N abierto(s))`.

#### Scenario: Banner en foco incluye la marca visual de foco
- **WHEN** existe un capítulo abierto establecido en foco
- **THEN** el banner superior exhibe el badge con `⭐ EN FOCO` con fondo amarillo y el texto de otros abiertos cuando corresponde.
