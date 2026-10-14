# Continuar el proyecto en Kali Linux

La versión con Lucie Recibir está en **`feat/lucie-recibir`**, continuación de
`actualizacion-completa-host`. No descargar
`master` esperando encontrar estos cambios. Leer primero [AGENTS.md](AGENTS.md),
[ESTADO_ACTUAL.md](ESTADO_ACTUAL.md) y [README.md](README.md).

## Obtener el código

Para una instalación nueva, con acceso autenticado al repositorio privado:

```bash
git clone --branch feat/lucie-recibir --single-branch https://github.com/alegondar/automatisar-lucie.git
cd automatisar-lucie
git status --short --branch
```

Si ya existe una copia en Kali, revisar sus cambios locales y remotos con el agente
antes de integrar la rama. No descartar modificaciones ni hacer reset, checkout
forzado o pull a ciegas. La revisión inicial mediante fetch y la confirmación de
integración están descritas en AGENTS.md. Continuar en una rama de trabajo.

## Configuración de cada equipo

El programa utiliza la biblioteca estándar de Python; no necesita pip ni LocalSend
en la PC. Node solo se utiliza para comprobar JavaScript durante el desarrollo.
El receptor del celular puede ser [Lucie Recibir](android/README.md), Android 10
o posterior, o LocalSend. Mantenerlo abierto en la misma red Wi-Fi. El APK propio
se compila por separado; Android SDK y Artemis son herramientas de desarrollo,
no dependencias del programa de PC.

Cada equipo conserva su propia base SQLite y configuración local. No copiar
desde Windows bases, logs, cachés ni `config_bandeja.local.json`. Si se configura
un directorio de exports en Kali, debe ser una ruta local de ese equipo; no usar
una ruta de unidad Windows. El vigilante de exports solo funciona si existe
la carpeta configurada y recibe archivos nuevos o nuevas versiones detectables.

Conectar/montar el pendrive y usar su marcador de vinculación existente. Las rutas
se obtienen del punto de montaje detectado, no de una letra fija como `E:`. El
material y el manifiesto del pendrive pueden compartirse; las bases de cada PC
no se sincronizan. Las carpetas históricas no se reorganizan automáticamente.

## Cambios incluidos

- Nuevas carpetas de ya editados: `videoyaeditado_<nombre>_semana_<del mes>_<mes>_<año>`.
- Los nuevos completos se resguardan en `videos completos/videos sin publicar`.
- Galería con vistas previas de videos/fotos, carpetas visibles y filtros por
  Lucie, Roli, Mailen y Sin asignar. Selección limitada a los archivos visibles.
- Emisor LocalSend integrado, revisión previa, progreso, recepción confirmada,
  archivo en `videosPublicados/<personaje>`, organización manual de históricos
  y Deshacer. Los originales de CapCut se conservan.

El código de estos flujos es común a Linux y Windows. Windows utiliza renombrado
sin reemplazar destinos; Linux utiliza `renameat2(RENAME_NOREPLACE)`. Si el sistema
no ofrece esa operación o el sistema de archivos no la admite, se informa el fallo
y se conservan los archivos: no se usa una alternativa que pudiera sobrescribir.
La suite incluye un traslado y una colisión nativos en temporales para verificar
esta capacidad al ejecutarse en Kali. La revisión del contrato POSIX mediante
mocks en Windows no demuestra ejecución Linux.

La apertura del Explorador y el lanzador Chrome `.bat` son funciones Windows.
En Kali se inicia la bandeja con Python y se abre su URL en el navegador local.
Las vistas previas dependen de los códecs que admita ese navegador. Si la red
bloquea multicast, conectar el receptor por su IP desde el dashboard.

## Validar en Kali antes de trabajar con material real

Detener la bandeja antes de validar. Todas las pruebas utilizan temporales y
la guardia hermética; no iniciar el programa real como prueba. Si el pendrive está
conectado, contar en solo lectura las líneas de su `.lucie/manifiesto.jsonl` antes
y después de la suite. Si cambia, detenerse y avisar. El recuento debe usar el punto
de montaje real encontrado en ese equipo, sin copiar una ruta personal al repo.

```bash
python3 -m unittest discover -s . -p 'test_*.py'
python3 seguridad_anti_borrado.py .
node --check bandeja/web/panel.js
node --check bandeja/web/wifi.js
node test_publicacion_ui.js
python3 auditar_repo.py --historial
```

Guardar logs en el temporal del sistema, no en el repositorio. No desactivar
la guardia ni quitar aserciones para hacer pasar pruebas. Los saltos deben
corresponder a capacidades realmente ausentes, con su motivo. Una vez completada
la validación, registrar SO, Python, resultados, omisiones y recuentos en
ESTADO_ACTUAL.md. Luego, para uso real:

```bash
python3 bandeja_descargas.py
```

Abrir `http://127.0.0.1:8766` y recargar con Ctrl+F5. El pendrive y la galería se
leen desde el equipo que ejecuta la bandeja; no se debe iniciar otra instancia
en Windows operando simultáneamente sobre ese mismo material.

## Punto de partida para la próxima sesión

Revisar primero rama, guías, git status y novedades de GitHub. La base
`actualizacion-completa-host` ya se validó en Kali (361 tests); la continuación
`feat/lucie-recibir` añade el emisor corregido y APK Android, con 367 tests Kali
y pruebas nativas/emulador. El usuario autorizó publicar esta continuación;
comprobar su referencia remota antes de actualizar otro equipo. Falta validar
transferencias Wi-Fi en el Motorola físico y Windows
nativo de este lote. Ver ESTADO_ACTUAL.md, [Publicación Wi-Fi](docs/publicacion-wifi.md)
y [Android](android/README.md).

Al terminar un nuevo lote de cambios, el agente debe preguntar por iniciativa
propia si se hace commit y push; solo publicar con confirmación, según AGENTS.md.
