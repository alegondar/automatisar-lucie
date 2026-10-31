# Personajes

## Purpose

Mantener un catálogo de protagonistas consistente en la clasificación, el dashboard y todo el circuito de archivos, desde el capítulo hasta su publicación y reversión.

## ADDED Requirements

### Requirement: Luna disponible en todo el circuito
El sistema SHALL aceptar `luna` y mostrar Luna junto a Lucie, Roli y Mailen en creación de capítulos, clasificación manual, edición, exports sin sesión, filtros y asignaciones de publicación. Los personajes existentes SHALL conservar su comportamiento.

#### Scenario: Crear y cerrar un capítulo de Luna
- **WHEN** el usuario elige Luna e inicia un capítulo con título válido
- **THEN** la API lo acepta, crea su carpeta fechada en la sala de espera bajo `luna` y permite foco, cierre, reapertura y descarte con las mismas reglas vigentes.

#### Scenario: Filtrar y asignar material a Luna
- **WHEN** el usuario selecciona Luna en publicación o asigna un export sin sesión con título y personaje explícitos
- **THEN** el panel y la API reconocen Luna, conservan las revisiones y confirmaciones exigidas y separan su material del resto.

### Requirement: Clasificación de nombres de Luna
El sistema SHALL reconocer `luna` como alias inicial de nombres de archivo y carpeta según las reglas vigentes. Un nombre numérico SHALL seguir requiriendo asignación explícita cuando no haya sesión inequívoca; una mención posterior a Luna SHALL NOT reemplazar el personaje identificado por el prefijo inicial.

#### Scenario: Prefijo explícito
- **WHEN** se clasifica `lunapaseo.mp4` sin capítulo en foco
- **THEN** se reconoce Luna y se conserva el mecanismo vigente de escena y renombrado.

#### Scenario: Mención de otro personaje
- **WHEN** se clasifica un nombre con prefijo Lucie o Roli y una mención posterior a Luna
- **THEN** se conserva el personaje del prefijo inicial.

### Requirement: Rutas y seguridad equivalentes para Luna
Las operaciones de Luna SHALL usar las estructuras mensuales y nombres vigentes de videos sin editar, imágenes, audios, ya editados, completos sin publicar y publicados. SHALL conservar simulación, confirmación, colisiones, SHA-256, registros y Deshacer. Incorporar Luna SHALL NOT migrar, renombrar ni mover material histórico automáticamente.

#### Scenario: Envío de material mixto al pendrive
- **WHEN** se confirma el plan de un capítulo de Luna con video, imagen y MP3
- **THEN** se guardan bajo sus categorías, `luna`, mes y capítulo; se verifica la integridad y Deshacer restaura los orígenes registrados sin sobrescribir.

#### Scenario: Edición y publicación
- **WHEN** se finaliza una edición de Luna y se confirma la recepción íntegra de su completo en el celular
- **THEN** se mantienen los formatos vigentes de Ya editados y completos, archivando el completo en Publicados bajo Luna y permitiendo su reversión con las rutas registradas.
