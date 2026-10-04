# Tasks

## 1. Configuración y Normalización de Base

- [x] 1.1 Eliminar la clave obsoleta `carpeta_imagenes` de `config_bandeja.json` y del cargador de `ConfiguracionBandeja` en `bandeja_descargas.py`, verificando con grep que no queden referencias activas.
- [x] 1.2 Implementar en `GestorMovimientosBandeja` la función de cálculo de base de nombre de escena (`calcular_base_escena`), reconociendo alias conocidos sin duplicar el prefijo, y verificar con pruebas unitarias en `test_bandeja_descargas.py`.

## 2. Lógica de Renombrado, Contadores y Prevención de Colisiones

- [x] 2.1 Implementar la clasificación de familias de medio (`FOTO` vs `VIDEO`) e inspección case-insensitive del directorio destino para obtener el contador inicial (`max_existente + 1`), y verificar con pruebas unitarias en `test_bandeja_descargas.py`.
- [x] 2.2 Integrar el ordenamiento cronológico por `mtime` (desempate por nombre original) y la asignación de `<base><número>.<ext>` en `simular_movimiento_lote`, garantizando unicidad en movimientos multi-lote, y verificar con pruebas unitarias en `test_bandeja_descargas.py`.
- [x] 2.3 Actualizar `ejecutar_movimiento_lote` para realizar el renombrado atómico con `os.rename(origen, destino_nuevo)` verificando inexistencia previa en destino, y verificar con pruebas de ejecución en `test_bandeja_descargas.py`.

## 3. UI de Simulación y Visualización

- [x] 3.1 Actualizar `generar_html_simulacion` para mostrar `nombre_original -> nombre_nuevo` con tooltip de ruta absoluta y eliminar etiquetas legadas de tipo (`imagenes`, `videos sin editar`), verificando con pruebas unitarias sobre el HTML generado en `test_bandeja_descargas.py`.

## 4. Bitácora, Reversibilidad y Compatibilidad

- [x] 4.1 Registrar `nombre_original` y `nombre_nuevo` en `bitacora_bandeja.jsonl` dentro de `ejecutar_movimiento_lote`, actualizando `bandeja_archivos.ruta_actual` en SQLite, y verificar con pruebas unitarias en `test_bandeja_descargas.py`.
- [x] 4.2 Actualizar `deshacer_operacion` y `obtener_historial` para revertir al nombre original, rechazar reversión si el origen está ocupado y mantener retrocompatibilidad con líneas de bitácora previas, y verificar con pruebas unitarias en `test_bandeja_descargas.py`.

## 5. Verificación Integral del Sistema y Cierre

- [x] 5.1 Ejecutar la suite completa de pruebas unitarias (`python3 -m unittest discover -s . -p "test_*.py"`) y verificar 0 fallos.
- [x] 5.2 Ejecutar la auditoría estática anti-borrado (`seguridad_anti_borrado.py`) y confirmar 0 infracciones detectadas en todo el proyecto.
