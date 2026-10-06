# Proposal: lista-envio-pendrive-por-carpetas

## Why

En la pestaña "Pendrive" del panel de control, la sección "Capítulos listos para enviar al pendrive" muestra el mensaje "No hay archivos en la sala de espera listos para transferir" a pesar de que en disco existen múltiples carpetas y capítulos con material en `~/Descargas/_lucie/lucie/` (como `lucie-maicalloalshop`, `lucie-invitaCafe`, `luciemeando`, `lucietrapitos`, `oloraculo` e `imagenes`). 

El diagnóstico técnico reveló que la consulta actual condiciona la visibilidad de los capítulos a la presencia física de un pendrive vinculado conectado (`detectar_pendrive`), omitiendo el escaneo cuando no hay unidad y no soportando el descubrimiento recursivo ni la selección granular por carpetas heterogéneas (sueltas, heredadas, cerradas o en foco). Es imperativo que el usuario pueda visualizar siempre la totalidad de las carpetas de la sala de espera en disco, inspeccionar su contenido con la vista previa existente, y seleccionar exactamente cuáles carpetas enviar al pendrive en un solo plan unificado con simulación obligatoria.

## What Changes

- **Escaneo exhaustivo en disco independiente del pendrive y de la base**: Escaneo recursivo de `~/Descargas/_lucie/<personaje>/<carpeta>` que lista todas las carpetas presentes en el sistema de archivos (excluyendo carpetas internas del sistema `_enviados`, `_revertidos`, `_descartados`, `_a_revisar`), funcione o no la base de datos y esté o no conectado un pendrive.
- **Tipificación y desglose completo por carpeta**: Cada fila expone personaje, nombre de carpeta, tipo (`Capítulo en foco`, `Capítulo abierto`, `Capítulo cerrado`, `Escena suelta`, `Carpeta heredada`), cantidad de fotos, cantidad de videos, peso total formateado, y fecha del archivo más reciente. Incluye en los conteos archivos en subcarpetas `fotos/` y `videos/` así como archivos sueltos en la raíz de cada carpeta.
- **Detección y tratamiento de Carpetas Heredadas**: Las carpetas heredadas (como `imagenes`) se identifican con una insignia y aviso explicativo; su contenido se audita y muestra para decisión del usuario, sin ocultarse ni enviarse automáticamente.
- **Archivos no multimedia y enrutamiento en raíz**: Advertencia visible para archivos no multimedia. Los archivos multimedia sueltos en la raíz de la carpeta se contabilizan y se enrutan automáticamente por tipo al enviar (videos a `videos sin editar` o `videos`, fotos a `imagenes` o `fotos`).
- **Inspección de archivos y vista previa**: Cada fila incluye un desplegable "Ver archivos" que lista los archivos de la carpeta (nombre, tamaño, tipo) y permite abrir la vista previa interactiva (lightbox de fotos y videos) ya existente en el panel.
- **Selección granular y envío en lote**: Checkbox por carpeta, botones "Seleccionar todas", "Ninguna", botón individual "Enviar esta carpeta" y botón global "Enviar seleccionadas (N)". El envío de una o varias carpetas seleccionadas genera un único plan de envío con simulación previa obligatoria y confirmación explícita.
- **Detección y desglose de archivos ya enviados**: Cuando el pendrive está conectado y vinculado, calcula por carpeta cuántos archivos ya existen en el manifiesto (`sha256`) y cuántos restan por enviar, calculando hashes de forma asíncrona/no bloqueante.
- **Habilitación condicional según pendrive**: Si el pendrive no está disponible o no está vinculado, la lista de carpetas permanece completamente visible e interactiva para consulta/selección, pero los botones de acción de envío se deshabilitan indicando claramente el motivo.
- **Distinción de 4 estados en la sección "Unidad Pendrive"**:
  1. *Sin unidad*: Ningún medio de almacenamiento conectado.
  2. *Unidad conectada sin vincular*: Detecta la unidad física y muestra etiqueta, punto de montaje, sistema de archivos, espacio libre y un botón destacado "Vincular pendrive".
  3. *Conectado y vinculado*: Pendrive con marcador `.lucie_pendrive.json` reconocido y listo.
  4. *Sin respuesta*: Detección con timeout que evita bloqueos del panel.
- **Persistencia de selecciones en el refresco automático**: Las tildes marcadas por el usuario se conservan durante el redibujado periódico del panel.

## Capabilities

### New Capabilities
- `envio-pendrive-carpetas`: Catálogo exhaustivo de carpetas de la sala de espera en disco, tipificación de contenidos (capítulos y heredadas), selección granular en lote y despacho unificado hacia el pendrive con simulación obligatoria.

### Modified Capabilities
<!-- No requirement changes to existing specs -->

## Impact

- **Backend**:
  - `bandeja/pendrive.py`: Desacoplar el escaneo de carpetas en `_leer_estado_pendrive_raw` y `obtener_estado_pendrive` de la presencia del pendrive. Agregar función de escaneo recursivo exhaustivo con clasificación por tipo contra `db` o heurística de carpetas heredadas. Soporte para simular envío de listas heterogéneas de carpetas arbitrarias.
  - `bandeja/servidor.py`: Rutas `/api/pendrive/estado` y `/api/pendrive/envio-simular` actualizadas para manejar listas de carpetas seleccionadas de la sala de espera.
- **Frontend**:
  - `bandeja/web/panel.html`, `bandeja/web/panel.css`, `bandeja/web/panel.js`: Nueva tabla enriquecida de carpetas de sala de espera con controles de selección masiva, desplegables "Ver archivos", badges de tipo, estados detallados de la unidad y persistencia de checkboxes entre sondeos.
- **Base de Datos y Seguridad**:
  - Consulta de solo lectura del estado de capítulos (`bandeja_capitulos`).
  - Totalmente compatible con la Regla de Oro: 0 primitivas destructivas, simulación previa obligatoria y 0 infracciones en el test AST anti-borrado.
