# Publicados por personaje

## Objetivo
Publicar en videos completos/videosPublicados/personaje; pendientes en videos
sin publicar; corregir clasificación manual y preparar reorganización histórica.

## Estado
- Auditoría del dashboard/API/estructura real solo lectura: realizada.
- Destinos nuevos, clasificación explícita sin adivinación: terminado.
- Reorganización manual, simulación, colisiones, registro y deshacer: terminado.
- Pruebas exclusivamente temporales; bandeja detenida antes de suite: terminado.
- Suite 381 OK/5, manifiesto pre/post 279/279, AST 0/25, JS/UI OK.
- Cambios físicos: grupo de tres movimientos elegido explícitamente por usuario,
  simulado y mostrado antes de aplicar; terminado con integridad/registro/deshacer.
- Commit/push nuevo lote: autorizado expresamente por el usuario el 2026-10-14;
  revisión final y auditorías correctas, pendiente ejecución y comprobación remota.

## Next Step
Crear el commit del lote revisado y subir feat/lucie-recibir a origin.

## Hallazgos
Raíz de completos: un publicado confirmado 1010(7).mp4 (usuario indica Roli),
dos carpetas históricas Lucie/Roli con dos videos cada una fuera de la cola.
Sin publicar: cuatro archivos sueltos, tres numéricos sin personaje conocido.
Personaje del archivo publicado no se registraba; publicar retiraba solo un nivel.
Conservar capítulos/fechas por defecto, pendiente preferencia del usuario.
