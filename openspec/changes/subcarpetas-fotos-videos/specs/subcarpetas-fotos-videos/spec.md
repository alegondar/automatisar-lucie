# Spec Delta: Subcarpetas de Fotos y Videos por Capítulo y Renombrado Total

## Purpose

Organizar automáticamente los archivos clasificados dentro de cada escena en subcarpetas dedicadas por tipo multimedia (`fotos/` y `videos/`), forzando un renombrado uniforme sin excepciones y manteniendo numeración continua acumulada sin colisiones.

## ADDED Requirements

### Requirement: Organizacion en subcarpetas fotos y videos por tipo multimedia
El sistema SHALL clasificar los archivos multimedia por su extensión y asignar como ruta de destino una subcarpeta específica (`fotos/` para imágenes y `videos/` para videos) dentro del directorio de la escena correspondiente.

#### Scenario: Foto asignada a subcarpeta fotos
- **WHEN** el usuario clasifica un archivo de imagen (`.jpg`, `.jpeg`, `.png`, `.webp`)
- **THEN** el sistema asigna como destino `<carpeta_escena>/fotos/<base><n>.<ext>`

#### Scenario: Video asignado a subcarpeta videos
- **WHEN** el usuario clasifica un archivo de video (`.mp4`, `.mov`, `.webm`)
- **THEN** el sistema asigna como destino `<carpeta_escena>/videos/<base><n>.<ext>`

### Requirement: Creacion perezosa y confinada de subcarpetas
El sistema SHALL NO crear subcarpetas vacías por adelantado. Las subcarpetas `fotos/` o `videos/` SHALL crearse únicamente al momento de hacer efectivo el movimiento del primer archivo de ese tipo, asegurando que la ruta destino quede estrictamente confinada dentro del directorio base configurado.

#### Scenario: Subcarpeta no existe antes del primer movimiento
- **WHEN** una escena nueva no contiene archivos de video
- **THEN** la subcarpeta `videos/` no existe en el sistema de archivos

#### Scenario: Creacion al mover el primer archivo
- **WHEN** se ejecuta el movimiento confirmado del primer video hacia una escena
- **THEN** el sistema crea la subcarpeta `videos/` y aloja allí el archivo

### Requirement: Renombrado total obligatorio de archivos multimedia
El sistema SHALL renombrar absolutamente todos los archivos multimedia movidos al formato estandarizado `<base><n>.<ext>`, eliminando cualquier excepción que preserve nombres personalizados anteriores.

#### Scenario: Archivo con nombre personalizado
- **WHEN** se mueve un archivo con nombre previo personalizado como `lucierascadapatalon.mp4` para el personaje `lucie` y escena `patalon`
- **THEN** el sistema renombra el archivo a `luciepatalon1.mp4` sin conservar el nombre original

### Requirement: Numeracion continua multi-nivel sin colisiones
El contador incremental para cada familia SHALL calcularse buscando el número más alto existente en la subcarpeta del tipo, en la raíz del directorio de la escena (archivos sueltos históricos) y en cualquier otra subcarpeta, aplicando comparaciones insensibles a mayúsculas y minúsculas.

#### Scenario: Existencia previa en raíz y subcarpeta
- **WHEN** la raíz de la escena contiene `luciepatalon1.png` y la subcarpeta `fotos/` contiene `luciepatalon2.png`
- **THEN** la siguiente foto movida se numera como `luciepatalon3.png`

#### Scenario: Resolucion de colision imprevista
- **WHEN** el destino propuesto ya existe físicamente en el sistema de archivos
- **THEN** el sistema añade un sufijo de seguridad `" (1)"` antes de la extensión para evitar cualquier pisado

### Requirement: Tratamiento de archivos con extensiones no multimedia
Archivos con extensiones distintas a las configuradas para fotos y videos SHALL NO descartarse ni moverse a ciegas. El sistema SHALL mostrar una advertencia en la simulación previa y, si se confirma la acción, ubicarlos en la raíz de la carpeta de la escena conservando su nombre original sin sobreescritura.

#### Scenario: Archivo con extension desconocida en simulacion
- **WHEN** se simula el movimiento de un archivo `notas.txt`
- **THEN** la simulación muestra una advertencia explícita y propone como destino `<carpeta_escena>/notas.txt`

#### Scenario: Ejecucion de movimiento para extension desconocida
- **WHEN** el usuario confirma el movimiento de `notas.txt`
- **THEN** el archivo se mueve a la raíz de la escena preservando su nombre original `notas.txt`

### Requirement: Simulacion detallada con rutas relativas y advertencias
La interfaz de simulación SHALL presentar para cada archivo el nombre original, el nombre nuevo normalizado y la ruta de destino relativa completa incluyendo la subcarpeta correspondiente.

#### Scenario: Visualizacion de ruta con subcarpeta
- **WHEN** se genera la simulación para un lote con fotos y videos
- **THEN** la vista previa muestra rutas relativas del tipo `<personaje> / <escena> / videos / <archivo>` y `<personaje> / <escena> / fotos / <archivo>`

### Requirement: Bitacora y operacion de deshacer no destructiva
El sistema SHALL registrar en la base de datos y bitácora el nombre original, nombre nuevo y ruta completa final con subcarpeta. La operación de deshacer SHALL restaurar el archivo a su origen verificando que no esté ocupado, y si una subcarpeta queda vacía tras deshacer, SHALL NO ser eliminada.

#### Scenario: Deshacer con restauracion exacta
- **WHEN** el usuario revoca un movimiento realizado
- **THEN** el archivo vuelve a su ubicación y nombre original, y la subcarpeta destino permanece intacta aún si queda vacía

### Requirement: Descarte de capitulo y balance recursivo
Las operaciones de descarte de capítulo, balance de "Pendientes" y "Movidos", "Terminar capítulo" y aviso de carpeta existente SHALL contabilizar archivos e inspeccionar árboles de carpetas de forma recursiva (raíz más subcarpetas).

#### Scenario: Descarte de carpeta con subcarpetas
- **WHEN** se descarta un capítulo cuya carpeta contiene subcarpetas `fotos/` y `videos/`
- **THEN** el sistema traslada el árbol completo hacia `_descartados`, verificando recursivamente los hashes de todos los archivos antes y después

#### Scenario: Conteo de archivos para aviso de carpeta existente
- **WHEN** se consulta el conteo de una escena que tiene 2 archivos en la raíz y 3 en `fotos/`
- **THEN** el sistema informa que la carpeta ya contiene 5 archivos

### Requirement: Exclusion de nombres reservados de carpetas en escenas
Los nombres de carpetas utilizados para subcarpetas de tipos multimedia (`fotos` y `videos`) SHALL ser excluidos de cualquier detección de capítulos o escenas existentes, impidiendo que aparezcan como opciones seleccionables en los menús desplegables del panel.

#### Scenario: Escaneo de escenas ignora fotos y videos
- **WHEN** el vigilante o la interfaz lista las escenas existentes de un personaje
- **THEN** las carpetas `fotos` y `videos` no son ofrecidas como escenas
