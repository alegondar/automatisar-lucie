# Tasks

## 1. Función Unificada de Fecha de Llegada y Configuración

- [x] 1.1 Definir la función unificada `obtener_fecha_llegada` en `bandeja_descargas.py` que calcule `max(st_mtime, st_ctime)` para objetos `os.stat_result`, rutas de archivo o diccionarios y verificar su comportamiento.
- [x] 1.2 Agregar soporte para `horas_material_reciente` en `ConfiguracionBandeja` y `config_bandeja.json`.

## 2. Cortes Temporales y Notificaciones en VigilanteBandeja

- [x] 2.1 Reemplazar el corte de fecha en `VigilanteBandeja.escanear` para usar `fecha_llegada` en la comparación con el inicio del capítulo en foco y en la evaluación de `horas_material_reciente`.
- [x] 2.2 Exponer `fecha_llegada` en la metadata de cada archivo en `item_info` y propagarla en los lotes.
- [x] 2.3 Restringir la notificación de escritorio (`_notificar_escritorio`) para que compute únicamente los lotes que van a la lista principal (`lotes_principales`), excluyendo "Anteriores".
- [x] 2.4 Asegurar que la ordenación para agrupar y numerar al renombrar preserve estrictamente el orden por `mtime`.

## 3. Interfaz de Usuario: Tooltips y Banner ⭐ EN FOCO

- [x] 3.1 Mostrar la fecha de llegada en el tooltip (`title`) y tarjeta del archivo en la interfaz web de la bandeja.
- [x] 3.2 Actualizar el banner del capítulo en foco y la clase `.badge-capitulo-activo` con el estilo amarillo y marca visual `⭐ EN FOCO`, conservando el aviso `(+N abierto(s))`.

## 4. Pruebas Unitarias y Auditoría AST

- [x] 4.1 Implementar tests unitarios para `obtener_fecha_llegada` verificando que retorne `max(mtime, ctime)`.
- [x] 4.2 Implementar test: archivo con `mtime` viejo pero `ctime` posterior al inicio del capítulo se asigna al capítulo en foco y queda tildado.
- [x] 4.3 Implementar test: archivo con `mtime` y `ctime` anteriores queda en "Anteriores", destildado.
- [x] 4.4 Implementar test: `horas_material_reciente` usa la fecha de llegada efectiva.
- [x] 4.5 Implementar test: el aviso de nuevos lotes no cuenta los de "Anteriores".
- [x] 4.6 Implementar test: el banner en foco incluye la marca visual `⭐ EN FOCO`.
- [x] 4.7 Ejecutar suite completa y verificar 0 infracciones en el test AST anti-borrado.
