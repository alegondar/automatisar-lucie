# Diseño del dashboard de Lucie Sin Reglas

## Propósito

Una mesa de producción local para revisar descargas, trabajar con capítulos,
organizar la edición y enviar material al celular. La pregunta principal de
Lotes detectados es «¿qué material llegó y a qué capítulo pertenece?».
Edición sigue el paso de crudos a sesión y video final; Enviar al celular sigue
archivos, destino y revisión. Cada vista mantiene sus controles y sus datos reales.

## Dirección visual

Taste `true-black-flat`, semilla 1306357286: superficies por luminosidad,
navegación discreta y acción principal por inversión. El gesto propio de Lucie
es el recorrido Material → Producción → Archivo, con los tres personajes juntos
en el pie de navegación. El monograma L con flecha conserva la identidad del panel.

Se adapta el negro a carbón #101011 y el acento a un cian moderado #72c9c3,
relacionado con la identidad anterior. Se conservan fuentes locales por el uso
sin conexión: Segoe UI, Liberation Sans y Arial, con cifras tabulares. No cargar
fuentes remotas ni agregar dependencias para mostrar el dashboard.

## Colores

- Fondo: #101011.
- Panel: #1a1a1c; superficie interior: #242426.
- Texto: #f3f3f4; secundario: #b4b4b8.
- Separación: #343437; contornos de controles: #59595f.
- Acento y foco: #72c9c3, reservado para selección y estado.
- Error: #f08d9b; confirmar eliminación: #873546 con texto blanco.
- Acción principal: fondo #f3f3f4 y texto #101011.

Los estados se expresan también con palabras. No depender solo del color.
Las acciones históricas conservan las distinciones semánticas de advertencia,
éxito y peligro; no confundir Descartar con Eliminar permanentemente.

## Tipografía y componentes

Título de vista de 22–28 px, semibold; encabezados de panel de 16–18 px;
texto y controles de 14 px; información secundaria de 12 px.
Una sola familia sans serif, y monospace únicamente para rutas e identificadores.

Paneles planos con radio de 16 px, sin sombras. Superficies interiores de 8 px.
Botones de al menos 44 px, primarios invertidos y secundarios con contorno.
Campos con etiqueta visible, fondo oscuro, borde perceptible y foco exterior.
Sombras reservadas para diálogos y otras superficies flotantes.

## Distribución y adaptación

Navegación lateral de 232 px, reducida a 210 px en pantallas intermedias.
A 1440 px: 232 + 32 + 1144 + 32 = 1440. Contenido fluido y márgenes iguales.
Debajo de 768 px, menú nativo desplegable y una sola columna con márgenes de
16 px. El menú se cierra al elegir una vista y el foco pasa al contenido.
El contador de capítulos es parte del botón y no un destino separado.

Cada vista tiene un h1 propio y una descripción breve. La acción Actualizar
vista está siempre disponible. Los estados vacíos explican cómo llegará el
material; nunca se completan con números, métricas o archivos inventados.

## Interacción y límites

Movimiento solo como respuesta a interacción; respetar reducción de movimiento.
Enlace Saltar al contenido y estado de navegación accesible con aria-current.
Mantener selección, simulación, confirmación, colisiones, integridad y Deshacer.
El diseño no inicia envíos, movimientos, búsquedas de red ni borrados.
No cambiar formatos de carpetas, rutas históricas ni decisiones de publicación.
