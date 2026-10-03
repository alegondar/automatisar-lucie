# Spec Delta

## Purpose

Proporciona una interfaz web local e interactiva de solo lectura para auditar el estado del inventario del pendrive y revisar en detalle las acciones del plan de limpieza sin alterar ningún archivo.

## ADDED Requirements

### Requirement: Servidor HTTP local y seguridad estricta de solo lectura
El sistema SHALL iniciar un servidor HTTP vinculado exclusivamente a la dirección local `127.0.0.1`, en un puerto configurable por línea de comandos cuyo valor predeterminado es `8765`, admitiendo únicamente peticiones HTTP `GET` y rechazando cualquier método de escritura o modificación.

#### Scenario: Petición GET válida
- **WHEN** un cliente HTTP envía una petición `GET` a una ruta válida del servidor
- **THEN** el servidor responde con código `200 OK` y el payload correspondiente en JSON o HTML/CSS/JS

#### Scenario: Rechazo de métodos no-GET
- **WHEN** un cliente HTTP envía una petición con método `POST`, `PUT`, `DELETE` o `PATCH`
- **THEN** el servidor rechaza inmediatamente la petición con código `405 Method Not Allowed` y no procesa ninguna acción

#### Scenario: Apertura de base de datos en solo lectura
- **WHEN** el servidor consulta la base de datos de caché SQLite
- **THEN** la conexión se realiza con flag de solo lectura (`mode=ro`) garantizando que no se puedan crear bloqueos de escritura ni modificar registros

### Requirement: Banner fijo de solo lectura y recarga de datos en memoria
La interfaz web SHALL mostrar un encabezado permanente que informe al usuario el carácter no destructivo de la herramienta, y proveer un mecanismo interactivo para refrescar los datos desde el disco sin alterar el pendrive.

#### Scenario: Visualización del banner permanente
- **WHEN** el usuario accede al dashboard en el navegador
- **THEN** visualiza un banner fijo en la parte superior con el texto exacto "SOLO LECTURA: este panel no modifica nada"

#### Scenario: Recarga de datos sin regeneración
- **WHEN** el usuario hace clic en el botón "Recargar datos"
- **THEN** el servidor vuelve a leer los archivos `informe_pendrive.json`, `plan_limpieza.json` y la caché SQLite en memoria sin disparar procesos generadores ni escribir en el disco

### Requirement: Vista de resumen general de métricas
El sistema SHALL exponer una vista de resumen con tarjetas informativas que muestren la capacidad global del pendrive, el espacio utilizado y disponible, el total de archivos relevados, la cantidad de duplicados detectados y el total de acciones del plan de limpieza desglosadas por tipo.

#### Scenario: Consulta del resumen general
- **WHEN** el usuario visualiza la pestaña de Resumen
- **THEN** se presentan tarjetas con capacidad total, espacio ocupado, espacio libre, cantidad de archivos analizados, conteo de duplicados y métricas de acciones del plan

### Requirement: Vista analítica por carpeta de primer nivel
El sistema SHALL presentar un desglose por cada carpeta del primer nivel del pendrive, mostrando el peso total acumulado y la cantidad de archivos divididos por categoría (video, foto, audio, documento, otro) mediante barras visuales comparativas.

#### Scenario: Desglose por carpeta y categoría
- **WHEN** el usuario selecciona la vista por carpetas de primer nivel
- **THEN** se muestran las carpetas con el tamaño total legible y barras porcentuales que representan el peso y conteo de cada categoría de archivo

### Requirement: Vista por personaje y estado de producción
El sistema SHALL clasificar los videos según el personaje identificado (`lucie`, `roli`, `mailen`) y su estado deducido de las carpetas ("videos sin editar", "videos ya editados", "videos completos", "videos sin publicar"), computando la cantidad de videos y la duración total en horas, minutos y segundos; aquellos no atribuibles pertenecerán a "sin clasificar".

#### Scenario: Agrupación de videos por personaje y estado
- **WHEN** se visualiza la sección de personajes y estado
- **THEN** se visualizan las tablas o tarjetas de `lucie`, `roli` y `mailen` con el número de videos y duración total por estado, junto con una sección para archivos sin clasificar

### Requirement: Vista detallada y filtrable de duplicados
El sistema SHALL listar todos los grupos de archivos duplicados con capacidades de filtrado por categoría (inter-carpeta, intra-carpeta, protegidas) y tamaño, mostrando todas las rutas de las copias, sus fechas de modificación y la acción propuesta.

#### Scenario: Filtrado de duplicados protegidos
- **WHEN** el usuario activa el filtro de duplicados en carpetas protegidas
- **THEN** la vista lista exclusivamente los grupos donde al menos una copia se encuentra en una carpeta protegida y muestra la recomendación de decisión manual

### Requirement: Vista del plan de limpieza con persistencia en cliente
El sistema SHALL mostrar la lista completa de acciones del plan de limpieza con filtros dinámicos (tipo de acción, personaje y tamaño), detallando origen, destino y motivo, permitiendo marcar casillas de "revisado" que se almacenan exclusivamente en el `localStorage` del navegador.

#### Scenario: Marcado de acción como revisada
- **WHEN** el usuario marca la casilla "revisado" en una acción del plan
- **THEN** el estado se almacena en el `localStorage` del navegador y no se envía ninguna petición de escritura al backend ni al pendrive

#### Scenario: Persistencia tras recargar la página
- **WHEN** el usuario recarga la página en su navegador
- **THEN** las casillas marcadas previamente como "revisado" conservan su estado a partir del almacenamiento local

### Requirement: Sección destacada de diferencias en carpetas laroli
El sistema SHALL exhibir una sección destacada que identifique y liste de forma explícita aquellos archivos que se encuentran presentes en una sola de las dos carpetas homónimas (`laroli` o `videos1/laroli`).

#### Scenario: Visualización de archivos disjuntos
- **WHEN** el usuario consulta la sección destacada de carpetas laroli
- **THEN** el dashboard exhibe la lista comparativa diferenciando qué archivos están solo en `laroli` y cuáles solo en `videos1/laroli`

### Requirement: Vista de archivos sueltos clasificados y sin clasificar
El sistema SHALL mostrar los archivos sueltos detectados dividiéndolos claramente entre aquellos clasificados por alias de personaje y aquellos que permanecen sin clasificar.

#### Scenario: Segmentación de archivos sueltos
- **WHEN** el usuario accede a la sección de archivos sueltos
- **THEN** se visualizan dos paneles o listas diferenciando los sueltos asignados a personajes mediante alias de aquellos que requieren revisión manual

### Requirement: Interfaz oscura autónoma y sin dependencias externas
El sistema SHALL suministrar una interfaz gráfica web diseñada con tema oscuro que funcione de manera completamente autónoma sin requerir conexión a internet ni descargar recursos de servidores externos o CDNs.

#### Scenario: Acceso offline al dashboard
- **WHEN** el usuario abre el dashboard sin conexión activa a internet
- **THEN** la página carga correctamente todos sus estilos, tipografías y scripts de visualización sin generar errores de red ni peticiones a dominios externos
