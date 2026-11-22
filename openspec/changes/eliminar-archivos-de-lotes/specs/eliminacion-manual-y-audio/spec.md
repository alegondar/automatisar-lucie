## MODIFIED Requirements

### Requirement: Excepción AST acotada

El analizador SHALL admitir las llamadas `os.unlink(ruta)` y `os.rmdir(ruta)` dentro de `GestorEliminacionPendrive.ejecutar` y únicamente `os.unlink(ruta)` dentro de `GestorEliminacionLocal.ejecutar` en `bandeja/eliminacion.py`. Se conservan las excepciones documentadas de limpieza de padres vacíos. Otras primitivas y ámbitos SHALL permanecer prohibidos.

#### Scenario: Borrado fuera del gestor local autorizado

- WHEN el analizador encuentra un borrado de archivo fuera de los métodos autorizados, o un borrado de directorio en el gestor local
- THEN lo reporta como infracción.
