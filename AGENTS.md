# Guía para próximas sesiones

Leer primero [ESTADO_ACTUAL.md](ESTADO_ACTUAL.md), [README.md](README.md)
y, en Windows, [README_WINDOWS.md](README_WINDOWS.md).
La constitución del sistema son las siete Reglas de Oro de
[openspec/config.yaml](openspec/config.yaml); siguen obligatorias.

- No borrar ni sobrescribir material. Toda copia debe respetar colisiones,
  comprobar integridad y permitir deshacer sin eliminar archivos.
- Pruebas exclusivamente en directorios temporales. No tocar Descargas reales,
  la carpeta real de CapCut ni el pendrive. Para la suite, la única lectura
  real autorizada del pendrive es contar las líneas de su manifiesto antes y
  después; si cambian, detenerse y avisar.
- No iniciar la bandeja real para probar: sus vigilantes pueden copiar material.
- Conservar la guardia hermética y todas las aserciones. Saltar pruebas solo
  por una capacidad realmente ausente y documentar el motivo.
- Preservar Linux al corregir Windows; no afirmar validación de un SO no ejecutado.
- No modificar `master` en esta línea de trabajo. Usar una rama de trabajo y
  subirla cuando el usuario lo autorice; no versionar bases, configuraciones
  locales, exports, logs ni informes generados.

La estructura final de salidas es `<categoria>/<personaje>/<nombre - mes - año>/`
con videos directamente dentro, sin semana ni subcarpetas de capítulo.
CapCut conserva sus originales. Ver el mapa de módulos, API, estados, modo manual,
reintentos, reversión y validaciones en `ESTADO_ACTUAL.md`.
