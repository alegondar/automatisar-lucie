# Tasks: control-montaje-pendrive

## 1. Detección nativa de particiones removibles y diagnóstico

- [x] 1.1 Implementar en `bandeja/plataforma.py` la función `detectar_particiones_removibles_linux` que inspecciona `/sys/block/*/removable` (=1), particiones en `/sys/class/block`, etiquetas por `/dev/disk/by-label` y puntos de montaje vía `/proc/self/mountinfo` (reconociendo montajes FUSE), sin invocar subprocess; verificar con pruebas unitarias simulando sysfs y procfs
- [x] 1.2 Implementar en `bandeja/plataforma.py` la resolución de disco padre (`obtener_disco_padre_particion`) e inspección no destructiva de procesos ocupantes (`listar_procesos_ocupando_montaje`) leyendo `/proc/*/cwd` y `/proc/*/fd` del usuario; verificar con pruebas unitarias
- [x] 1.3 Extender `obtener_estado_pendrive` y `detectar_pendrive` en `bandeja/pendrive.py` para soportar los 5 estados (`sin_unidad`, `detectada_sin_montar`, `conectada_sin_vincular`, `vinculado_listo`, `sin_respuesta`), ordenando por preferencia de etiqueta `MIUNIDAD` y generando el diagnóstico detallado para "¿Por qué no veo mi pendrive?"; verificar con pruebas unitarias

## 2. Lógica de control de montaje, precondiciones y bitácora

- [x] 2.1 Implementar en `bandeja/pendrive.py` la función `montar_unidad_pendrive(dispositivo)` que valida el dispositivo contra la lista blanca de particiones removibles detectadas e invoca `udisksctl mount -b <dispositivo>` usando `subprocess.run` seguro (sin shell, sin sudo, con timeout), registrando el evento en la bitácora local; verificar con pruebas unitarias
- [x] 2.2 Implementar en `bandeja/pendrive.py` la función `desmontar_unidad_pendrive(dispositivo, expulsar=False)` que valida precondiciones (rechazo si hay transferencia, deshacer o `.part` activo), ejecuta `os.sync()`, invoca `udisksctl unmount -b <dispositivo>`, ejecuta `udisksctl power-off -b <disco_padre>` si `expulsar=True` tras el éxito, e inspecciona procesos en caso de error busy, silenciando temporalmente la unidad retirada y registrando en bitácora; verificar con pruebas unitarias
- [x] 2.3 Exponer en `bandeja/servidor.py` los endpoints `POST /api/pendrive/montar`, `POST /api/pendrive/desmontar` y `POST /api/pendrive/expulsar` con validación estricta de cabecera Host, Content-Type JSON y protección CSRF, devolviendo comando manual sugerido ante fallos; verificar con pruebas unitarias HTTP

## 3. Interfaz de usuario (SPA): Tarjetas de estado, selector y modales de confirmación

- [x] 3.1 Actualizar `bandeja/web/panel.html` y `bandeja/web/panel.css` con la interfaz para el estado `detectada_sin_montar`, selector de unidad si hay múltiples removibles, botones "Montar unidad", "Desmontar", "Desmontar y expulsar", modal de confirmación con comando visual y botón "Copiar", y bloque colapsable "¿Por qué no veo mi pendrive?"
- [x] 3.2 Implementar en `bandeja/web/panel.js` el renderizado reactivo de los 5 estados, diálogo de confirmación previo a la ejecución, gestión de errores con comando manual alternativo, desactivación de botones durante transferencias activas y omisión de controles de montaje si la plataforma reportada es Windows
- [x] 3.3 Integrar en `bandeja/web/panel.js` el silenciamiento local del banner reactivo tras desmontaje o expulsión manual hasta nueva reconexión física

## 4. Pruebas integrales, suite completa y auditoría AST anti-borrado

- [x] 4.1 Añadir en `test_envio_pendrive.py` y `test_bandeja_descargas.py` la suite de pruebas unitarias simulando sysfs/procfs (/sys, by-label, mountinfo), rechazo de dispositivos fuera de la lista blanca, bloqueo por transferencias activas, diagnóstico de procesos ocupantes, secuencia de power-off y omisión en Windows
- [x] 4.2 Ajustar `seguridad_anti_borrado.py` para permitir explícitamente `udisksctl` con verbos `mount`, `unmount` y `power-off`, verificar 0 infracciones en los 15 archivos operativos y correr el 100% de la suite de pruebas en verde
