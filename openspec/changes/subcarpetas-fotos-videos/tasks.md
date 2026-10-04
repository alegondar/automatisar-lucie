# Tasks: Subcarpetas de Fotos y Videos por Capítulo y Renombrado Total

## 1. Configuración y parámetros base

- [x] 1.1 Añadir `"subcarpeta_fotos": "fotos"` y `"subcarpeta_videos": "videos"` a `config_bandeja.json` y actualizar `ConfiguracionBandeja` en `bandeja_descargas.py`.

## 2. Contadores recursivos, ruteo y renombrado total

- [x] 2.1 Actualizar `obtener_contadores_carpeta_destino` para buscar recursivamente el número más alto en raíz de escena y subcarpetas (`fotos/`, `videos/`, etc.) de manera case-insensitive.
- [x] 2.2 Actualizar `simular_movimiento_lote` para rutear fotos a `fotos/` y videos a `videos/` aplicando renombrado universal forzoso `<base><n>.<ext>` sin excepciones, y extensiones desconocidas a la raíz con advertencia y nombre original.
- [x] 2.3 Implementar creación perezosa de subcarpetas en `ejecutar_movimiento` (`os.makedirs` con exist_ok=True y confinamiento por realpath) justo antes de mover el primer archivo.
- [x] 2.4 Actualizar el modal de simulación en frontend y backend para mostrar la subcarpeta en la ruta relativa y alertar sobre archivos de extensión desconocida.

## 3. Compatibilidad, conteo recursivo y nombres reservados

- [x] 3.1 Excluir los nombres reservados `fotos` y `videos` de la detección de escenas en `VigilanteBandeja.escanear` y `FiltroListaBlanca.es_carpeta_escena_existente`.
- [x] 3.2 Actualizar `descartar_capitulo`, balance de pendientes/movidos y avisos de carpetas existentes para contar archivos de forma recursiva en todo el árbol.
- [x] 3.3 Garantizar que `deshacer_operacion` restaure el archivo original a su origen y deje subcarpetas destino vacías sin eliminarlas.

## 4. Pruebas y verificación integral

- [x] 4.1 Implementar casos de prueba en `test_bandeja_descargas.py` para ruteo por tipo, renombrado estricto, creación perezosa, numeración combinada, colisión case-insensitive, extensiones desconocidas, reversión sin borrado y exclusión de escenas reservadas.
- [x] 4.2 Ejecutar suite completa de pruebas unitarias y verificar 0 infracciones en la auditoría AST anti-borrado.
