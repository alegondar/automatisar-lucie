## Context

Lotes detectados y Sin identificar ya publican un identificador multimedia y el hash del archivo que vio el vigilante. Los duplicados pueden carecer de ID SQLite propio.

## Goals / Non-Goals

Eliminar un solo archivo de Descargas por operación, desde su tarjeta o fila, conservando las demás selecciones y la bitácora. Se protegen carpetas, audio, enlaces y demás áreas del disco.

## Decisions

- Un diálogo nativo enfoca «No». La simulación muestra la ruta, registra la identidad y el SHA-256 en un plan del servidor y entrega un token de un solo uso con cinco minutos de vigencia.
- Al confirmar, se revalida el inventario y el archivo en Descargas. La operación local comparte la exclusión de movimientos, escribe la intención en la bitácora, elimina únicamente el archivo y registra el resultado. Se retira el archivo del inventario del vigilante. El plan conserva la vista de origen para invalidar la confirmación si el archivo deja de figurar en ella.
- La auditoría AST permite solo la llamada concreta necesaria en el método de ejecución. Se mantienen las guardas del flujo del pendrive.

## Risks / Trade-offs

- Un archivo reemplazado, movido, bloqueado o modificado requiere una nueva revisión. El borrado confirmado es irreversible.
