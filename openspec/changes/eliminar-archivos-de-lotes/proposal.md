## Why

Quien revisa Lotes detectados o Sin identificar necesita eliminar una foto o un video local que ya no quiere conservar.

## What Changes

- Cada foto o video de Lotes detectados y Sin identificar ofrece «Eliminar del disco».
- Una ventana muestra la ruta y pregunta si se confirma el borrado permanente, con «Sí» y «No».
- Las Reglas de Oro admiten esta segunda excepción manual con simulación previa, registro y auditoría AST.

## Capabilities

### New Capabilities

- `eliminacion-local-de-lotes`: Borrado individual y permanente de fotos y videos de Lotes detectados y Sin identificar.

### Modified Capabilities

- `eliminacion-manual-y-audio`: Excepción AST acotada para la nueva operación local.

## Impact

Dashboard, rutas POST del servidor, vigilante, gestor de eliminación, documentación y pruebas herméticas.
