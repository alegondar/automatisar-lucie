# Tasks: preseleccion-reciente-y-seleccion-global

## 1. Configuración y corte de material reciente

- [x] 1.1 Actualizar el valor predeterminado de `horas_material_reciente` a 168 en `bandeja/config.py` y `config_bandeja.json`, asegurando que 0 deshabilita el corte; verificar mediante pruebas unitarias de configuración
- [x] 1.2 Ajustar `VigilanteBandeja.escanear` en `bandeja/vigilante.py` para bifurcar el corte temporal: en modo respaldo usar `horas_material_reciente` sobre `obtener_fecha_llegada` enviando material antiguo a `candidatos_anteriores`, y con capítulo en foco mantener exclusivamente el corte por `fecha_inicio`; verificar con tests unitarios
- [x] 1.3 Asegurar que `AgrupadorLotes.agrupar` en `bandeja/lotes.py` mantenga la partición estricta de lotes mixtos y deje los lotes anteriores sin escena sugerida; verificar con tests de partición mixta

## 2. Detección no bloqueante de duplicados

- [x] 2.1 Implementar en `VigilanteBandeja.escanear` la detección de duplicados por SHA-256 contra archivos listados, archivos previamente movidos en `bandeja_archivos` y manifiesto del pendrive, inyectando metadatos `duplicado` en cada archivo; verificar con tests unitarios
- [x] 2.2 Propagar la información de duplicados a través de `AgrupadorLotes` hacia las respuestas de `/api/lotes`, asegurando que el cómputo en segundo plano no bloquee el panel ni el servidor web; verificar respuesta JSON de la API

## 3. Interfaz de usuario (botones globales, anteriores, escenas y duplicados)

- [x] 3.1 Agregar en `bandeja/web/panel.html` los botones "Seleccionar todo", "Ninguno" y el contador `X archivos seleccionados de Y` en la cabecera de lotes principales, junto a "Mover lotes listos"; verificar estructura en HTML
- [x] 3.2 Implementar en `bandeja/web/panel.js` las funciones `seleccionarTodoGlobal(marcar)` y `actualizarConteoGlobalSeleccion()`, sincronizando checkboxes individuales, checkbox maestro y contadores por lote sin afectar `sec-lotes-anteriores`; verificar con prueba Node.js
- [x] 3.3 Modificar `validarInputEscena` en `bandeja/web/panel.js` para diferir el mensaje de escena vacía hasta el evento `blur` o intento de mover el lote; verificar en el DOM servido
- [x] 3.4 Actualizar el renderizado de archivos en `bandeja/web/panel.js` y estilos en `bandeja/web/panel.css` para presentar la insignia "Duplicado", la referencia de coincidencia y desmarcar su checkbox por defecto; verificar en el DOM servido
- [x] 3.5 Actualizar el encabezado y detalles de la sección "Anteriores" en `bandeja/web/panel.js` para mostrar `Material de más de N horas: revisá antes de mover` cuando no hay capítulo en foco; verificar renderizado

## 4. Pruebas unitarias, auditoría AST y verificación integral

- [x] 4.1 Agregar pruebas unitarias en `test_bandeja_descargas.py` para todos los nuevos requerimientos: corte reciente vs anterior a 10 días, `horas_material_reciente = 0`, partición de lote mixto, exclusión de anteriores en "Mover lotes listos", botones globales y contadores, validación diferida de escena vacía, insignia de duplicados y preservación del corte con capítulo en foco; verificar paso de los nuevos tests
- [x] 4.2 Ejecutar la auditoría AST `python3 seguridad_anti_borrado.py` verificando 0 infracciones en todos los módulos operativos y correr la suite completa asegurando 100% de tests en verde
