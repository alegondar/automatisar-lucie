# Design

## Context

Ver proposal.md. El backend usa Python y el dashboard HTML/CSS/JS sin framework. `mailen` aparece en listas independientes de `clasificacion`, `servidor`, `vigilante`, `edicion`, `publicacion`, `organizacion_mensual`, los aliases de `movimientos` y tres superficies web. La SQLite guarda personaje como texto; no requiere migración. La propuesta histórica `dashboard-revision` se conserva intacta.

## Goals / Non-Goals

**Goals:** extender el catálogo de forma coherente sin cambiar contratos de movimiento ni estructuras históricas. Cobertura funcional de Luna y regresión de los otros personajes.

**Non-Goals:** rediseñar el dashboard, generalizar la administración dinámica de personajes, reclasificar archivos anteriores ni modificar el receptor Android.

## Decisions

- Mantener el patrón existente y extender explícitamente los catálogos con `luna` y etiqueta Luna. Un registro dinámico o un nuevo endpoint de configuración ampliaría el alcance sin ser necesario para este personaje.
- Usar solo el alias literal `luna`, sin inventar apodos. Agregarlo a `alias-personajes.json` y a los valores de respaldo, para que también funcione con configuraciones antiguas de pruebas. Revisar por separado carpeta y prefijo, evitando que Luna caiga en el retorno por defecto Lucie.
- Actualizar filtros, selects estáticos y selects creados por JS; añadir las validaciones de API y edición antes de comprobar el recorrido. Conservar el protocolo y los tokens de un uso.
- Reutilizar el guardado parametrizado por personaje y los nombres fechados/mensuales actuales. Agregar Luna al organizador mensual y al descubrimiento de escenas sin ejecutar organización alguna.

## Risks / Trade-offs

- Catálogos independientes pueden quedar incompletos → buscar todas las referencias a los tres personajes y comprobar API, clasificación, edición, publicación y UI con Luna.
- Nombres que mencionan varios personajes pueden confundirse → probar prioridad del alias inicial y no inferir personajes de nombres numéricos.
- Pruebas activas junto a vigilantes reales pueden modificar material → cerrar normalmente Lucie antes de la suite, fixtures exclusivamente temporales y contar solo las líneas del manifiesto real antes/después si está montado.

## Migration Plan

No hay migración de datos ni material. Tras validar, actualizar documentación y pedir autorización de commit/push para este lote. Para cargar el catálogo del backend será necesario reiniciar normalmente Lucie; la UI requiere Ctrl+F5. Una reversión de código conserva registros/rutas históricos; no deberá operar nuevas sesiones de Luna con una versión que no la reconozca.
