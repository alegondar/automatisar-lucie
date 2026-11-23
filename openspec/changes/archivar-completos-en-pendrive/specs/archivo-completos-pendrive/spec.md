## ADDED Requirements

### Requirement: Archivo de videos completos elegido desde la cola
El dashboard SHALL ofrecer guardar en el pendrive o enviar al celular después de que el usuario seleccione videos en la cola. El archivo local SHALL mostrar origen y destino para confirmar, sin requerir un receptor.

#### Scenario: Guardar sin celular
- **WHEN** el usuario confirma un plan vigente para archivos seleccionados y sin conflictos
- **THEN** los videos elegidos pasan a `videos completos/videos archivados` por personaje y mes, desaparecen de la cola y quedan disponibles para volver a Sin publicar desde el historial.

#### Scenario: Enviar al celular
- **WHEN** el usuario elige Wi-Fi y el receptor confirma la recepción íntegra
- **THEN** los recibidos pasan a `videos completos/videosPublicados`.

#### Scenario: Plan vencido, contenido cambiado o destino ocupado
- **WHEN** el usuario confirma un plan vencido o un plan cuyas condiciones ya no se cumplen
- **THEN** el sistema rechaza el archivo local sin sobrescribir material.
