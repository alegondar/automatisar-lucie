# Proposal

## Why

Luna se suma como protagonista y necesita el mismo circuito completo que Lucie, Roli y Mailen. Agregarla solo al selector no funciona: hay listas cerradas que rechazan el personaje o lo confunden con Lucie en clasificación, edición y publicación.

## What Changes

- Agregar `luna` / Luna en los selectores de capítulos, clasificación manual, exports sin sesión, filtro y asignación de envío Wi-Fi.
- Admitir Luna en API, alias, validaciones, descubrimiento de escenas y organización mensual.
- Conservar el circuito de capítulos, sala de espera, pendrive, edición, completos, publicación y reversión, con rutas por categoría/Luna/mes/capítulo y las excepciones vigentes de completos y ya editados.
- Probar el recorrido con videos, imágenes y MP3, sin migrar ni renombrar material histórico ni usar archivos reales como fixtures.

## Capabilities

### New Capabilities

- `personajes`: catálogo de protagonistas reconocido de forma consistente por clasificación, dashboard, guardado y publicación; incluye Luna con las mismas reglas de operación.

### Modified Capabilities

Ninguna. Las specs principales existentes cubren modularización y eliminación/audio; no definen un catálogo de personajes.

## Impact

`alias-personajes.json`; `bandeja/clasificacion.py`, `movimientos.py`, `servidor.py`, `vigilante.py`, `edicion.py`, `publicacion.py`, `organizacion_mensual.py`; `bandeja/web/panel.html`, `panel.js`, `wifi.js`; pruebas y documentación de uso. Sin nuevas dependencias, cambios de esquema SQLite ni cambios de protocolo Android. Se conserva la propuesta histórica `dashboard-revision` sin editarla ni archivarla.
