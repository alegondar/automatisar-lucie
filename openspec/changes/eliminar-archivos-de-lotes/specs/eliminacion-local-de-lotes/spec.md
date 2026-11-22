## ADDED Requirements

### Requirement: Eliminación individual confirmada de archivos locales

El dashboard SHALL ofrecer la acción «Eliminar del disco» para una foto o video de Lotes detectados o Sin identificar. El servidor SHALL generar un plan privado y temporal para el archivo identificado en el inventario de la vista de origen y mostrar su ruta. El diálogo SHALL ofrecer «Sí» y «No» e indicar que se elimina permanentemente del dashboard y del disco.

#### Scenario: Cancelar la confirmación

- WHEN el usuario pulsa «No» o cierra la ventana sin elegir «Sí»
- THEN el archivo y su tarjeta o fila se conservan.

#### Scenario: Confirmar el archivo revisado

- WHEN el usuario pulsa «Sí» y el plan, la ruta, la identidad y el contenido siguen vigentes
- THEN el servidor registra la operación, elimina solo el archivo revisado y lo retira de su vista.

#### Scenario: Archivo incompatible o cambiado

- WHEN no coincide el inventario, el token venció o fue utilizado, el archivo cambió, está bloqueado o la ruta es un enlace o sale de Descargas
- THEN la ejecución se rechaza y se informa el motivo sin eliminar el archivo.
