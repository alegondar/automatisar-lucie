# Tasks

## 1. Configuración y Mapeo de Alias

- [x] 1.1 Crear `alias-personajes.json` con las reglas de patrones para `roli*`, `laroli*`, `magui*` -> `roli`; `lucie*`, `luci*` -> `lucie`; y `mailen*` -> `mailen` (a confirmar), verificando su sintaxis JSON válida.
- [x] 1.2 Crear `config_limpieza.json` con exclusión por defecto de `_a_revisar`, `code` y carpetas de sistema, lista `carpetas_protegidas` (`laroli`, `videos1/laroli`), prioridad de duplicados (`videos completos`), desempate (`mas_reciente`), umbral de similitud (0.75), tolerancia de mtime (2.0s) y prefijo `_a_revisar/duplicados/`, verificando que cargue correctamente.

## 2. Lógica del Generador y Reglas de Negocio (Solo Simulación)

- [x] 2.1 Definir las estructuras de datos (`AccionPlan`, `HuellaPlan`, `ConfiguracionLimpieza`) e implementar la garantía estricta de solo lectura que rechace rutas de salida o temporales en el almacenamiento extraíble y valide en el generador que el destino propuesto no exista previamente en el inventario ni en el almacenamiento para no sugerir sobrescrituras.
- [x] 2.2 Implementar la gestión de duplicados exactos diferenciando: (a) duplicados con copia en `carpetas_protegidas`, donde si alguna copia reside en una carpeta protegida el grupo completo no genera ningún movimiento (`destino: null`) y se lista en "duplicados a decidir a mano" con todas sus rutas, tamaños y fechas; (b) duplicados intra-carpeta (misma carpeta de primer nivel), marcándolos como "duplicados a decidir a mano" sin propuesta de movimiento (`destino: null`); y (c) duplicados inter-carpeta sin copias protegidas, aplicando regla de conservación con prioridad `videos completos` y generando propuesta de traslado a `_a_revisar/duplicados/` para las copias restantes sin proponer jamás borrado.
- [x] 2.3 Implementar el análisis diferencial de carpetas sospechosas (similitud >= 75%): listar los archivos disjuntos (presentes en una y ausentes en la otra) con ruta, tamaño y fecha, asegurando la inclusión del par `laroli` vs `videos1/laroli` y verificando que no se propongan fusiones de carpetas completas.
- [x] 2.4 Implementar la clasificación de archivos sueltos usando `alias-personajes.json`, asignando destino propuesto para coincidencias y clasificando como "sin clasificar" (destino nulo) los archivos sin match.
- [x] 2.5 Implementar la detección de carpetas vacías como registros informativos en el plan sin acciones de eliminación.
- [x] 2.6 Implementar la huella de integridad en el plan y el validador pre-ejecución: recalcular el hash SHA-256 leyendo el archivo físico real en streaming en ese momento (sin utilizar la caché SQLite), verificar coincidencia exacta de tamaño y hash contra la huella, y aplicar tolerancia de 2s para mtime informativo.

## 3. Renderizado de Artefactos y CLI (Simulación Dry-Run)

- [x] 3.1 Implementar la exportación estructurada a `plan_limpieza.json` incluyendo metadatos, configuración con `_a_revisar` ignorado, huella y acciones desglosadas con origen y destino exactos sin modificar ningún archivo en la raíz analizada.
- [x] 3.2 Implementar el renderizado en Markdown a `plan_limpieza.md` con secciones legibles: resumen, duplicados a revisar en cuarentena, duplicados a decidir a mano (intra-carpeta con rutas, tamaños y fechas), diferencias en carpetas sospechosas, archivos sueltos clasificados y carpetas vacías.
- [x] 3.3 Implementar la interfaz de línea de comandos en `plan_limpieza.py` con argumentos `--raiz`, `--cache`, `--config`, `--salida-json`, `--salida-md` operando 100% en modo simulación (dry-run).

## 4. Pruebas Unitarias y Verificación

- [x] 4.1 Crear y actualizar `test_plan_limpieza.py` utilizando `unittest` y pendrive simulado en `/tmp`, cubriendo duplicados con copias en `carpetas_protegidas` (cero movimientos y registro a mano con rutas, tamaños y fechas), duplicados inter-carpeta vs intra-carpeta (a mano), carpetas sospechosas (>=75%), clasificación de sueltos, carpetas ignoradas (`_a_revisar`, `code`), huella con tolerancia FAT de 2s en mtime, y verificación de cero escrituras en la raíz simulada.
- [x] 4.2 Agregar test específico de validación de integridad: modificar el contenido de un archivo manteniendo exactamente su tamaño original y restaurando su mtime original con `os.utime`, comprobando que la validación recalcula el SHA-256 real sobre el disco y aborta la ejecución con error.
- [x] 4.3 Implementar analizador estático AST anti-borrado que detecte las 11 primitivas prohibidas: `os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `Path.unlink`, `Path.rmdir`, `shutil.rmtree`, `shutil.move`, `os.replace`, `send2trash`, y `subprocess`/`os.system` con `rm`.
- [x] 4.4 Implementar test que compruebe que el analizador AST detecta exitosamente cada una de las 11 primitivas prohibidas en fragmentos de código de prueba sintéticos.
- [x] 4.5 Ejecutar el analizador AST sobre todos los archivos `.py` del código operativo del repositorio y verificar que estén 100% libres de llamadas de borrado y pisado.
- [x] 4.6 Ejecutar la suite completa (`python3 -m unittest test_plan_limpieza.py`) y verificar que todos los casos de prueba pasen satisfactoriamente.
- [x] 4.7 Ejecutar `python3 plan_limpieza.py` sobre la unidad o su caché para generar `plan_limpieza.json` y `plan_limpieza.md`, confirmando que el par `laroli` vs `videos1/laroli`, la protección de duplicados en carpetas protegidas (249 acciones totales en simulación), la separación de duplicados intra/inter y la exclusión de `_a_revisar` se resuelvan según lo especificado.

## 5. Cierre y Control de Versiones

- [x] 5.1 Realizar commit en español en git con los nuevos archivos del plan de limpieza (`plan_limpieza.py`, `alias-personajes.json`, `config_limpieza.json`, tests y reportes generados) y realizar push si existe un remoto configurado.
