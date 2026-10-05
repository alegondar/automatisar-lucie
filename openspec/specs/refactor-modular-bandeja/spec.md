# refactor-modular-bandeja Specification

## Purpose
Define los contratos y garantías requeridas para la modularización de `bandeja_descargas.py` en el paquete `bandeja/` y activos `bandeja/web/`, asegurando descubrimiento estático AST exhaustivo, cero regresiones de comportamiento y compatibilidad total.

## Requirements

### Requirement: Descubrimiento y auditoría automática AST anti-borrado
El sistema de auditoría estática (`seguridad_anti_borrado.py`) SHALL descubrir y auditar automáticamente todos los archivos Python (`.py`) del paquete `bandeja/` y de la raíz del repositorio (excluyendo archivos de prueba `test_*.py`), verificando 0 infracciones de las 11 primitivas prohibidas de borrado y pisado.

#### Scenario: Descubrimiento exhaustivo de módulos
- **WHEN** se ejecuta la auditoría estática del proyecto
- **THEN** se analizan automáticamente todos los archivos `.py` en la raíz (no tests) y recursivamente dentro de `bandeja/`
- **AND** ningún archivo operativo nuevo queda fuera de la inspección

#### Scenario: Detección y falla ante archivos no auditados
- **WHEN** se ejecuta la prueba unitaria de cobertura de auditoría
- **THEN** el test verifica que el conjunto de archivos auditados cubra la totalidad de archivos operativos descubiertos
- **AND** falla explícitamente si se detecta un archivo `.py` operativo que no haya sido procesado por el analizador AST

#### Scenario: Cero infracciones en primitivas prohibidas
- **WHEN** el analizador AST inspecciona cualquier módulo del paquete `bandeja/` o de la raíz
- **THEN** se reportan exactamente 0 violaciones de `os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `Path.unlink`, `Path.rmdir`, `shutil.rmtree`, `shutil.move`, `os.replace`, `send2trash` o comandos shell/subprocess con `rm`

### Requirement: Punto de entrada compatible y preservación de interfaz
El script `bandeja_descargas.py` SHALL mantenerse en la raíz del repositorio como punto de entrada CLI y fachada de compatibilidad hacia atrás, delegando en los submódulos correspondientes del paquete `bandeja`.

#### Scenario: Ejecución de servidor vía CLI
- **WHEN** el usuario ejecuta `python3 bandeja_descargas.py` con sus argumentos habituales (`--puerto`, `--descargas`, `--destino`, `--solo-servidor`, `--sin-abrir-navegador`)
- **THEN** el comando arranca el demonio vigilante y el servidor web con exactamente los mismos parámetros y comportamiento observado previo al refactor

#### Scenario: Compatibilidad de importación
- **WHEN** módulos externos o pruebas importan clases o funciones públicas desde `bandeja_descargas` (e.g. `ConfiguracionBandeja`, `GestorBaseDatosBandeja`, `calcular_sha256`)
- **THEN** las importaciones se resuelven satisfactoriamente con la misma firma y tipo

### Requirement: Servicio seguro de activos web estáticos con lista blanca
El servidor HTTP (`bandeja/servidor.py`) SHALL servir los archivos estáticos de la interfaz web (`panel.html`, `panel.js`, `panel.css`) desde el directorio `bandeja/web/` únicamente mediante una lista blanca fija y explícita, rechazando cualquier intento de acceso a rutas arbitrarias.

#### Scenario: Entrega de archivos del panel web
- **WHEN** un cliente realiza peticiones GET a `/`, `/index.html`, `/panel.js` o `/panel.css`
- **THEN** el servidor responde con código 200, Content-Type adecuado y el contenido respectivo
- **AND** el token CSRF y variables de configuración requeridas se integran adecuadamente en la sesión

#### Scenario: Rechazo estricto de rutas fuera de la lista blanca
- **WHEN** un cliente realiza peticiones GET solicitando archivos no presentes en la lista blanca de activos (e.g. `/etc/passwd`, `/../config.json` o subarchivos arbitrarios)
- **THEN** el servidor deniega el acceso respondiendo con código 403 o 404
- **AND** en ningún caso se lee ni se expone contenido ajeno a la lista blanca autorizada

### Requirement: Límite de tamaño modular y separación de responsabilidades
Los módulos creados dentro del paquete `bandeja/` SHALL responder a responsabilidades cohesivas y acotadas, no debiendo superar ninguno de ellos aproximadamente 1.200 líneas de código.

#### Scenario: Verificación de longitud de módulos
- **WHEN** se inspecciona la cantidad de líneas de código de cada archivo `.py` en `bandeja/`
- **THEN** cada archivo individual (`config.py`, `db.py`, `clasificacion.py`, `lotes.py`, `movimientos.py`, `capitulos.py`, `pendrive.py`, `plataforma.py`, `vigilante.py`, `servidor.py`) cuenta con un recuento de líneas inferior a ~1.200 líneas

### Requirement: Preservación idéntica de la suite de pruebas y contratos HTTP
La modularización SHALL garantizar que la suite completa de pruebas unitarias continúe ejecutándose con 100% de éxito, manteniendo al menos los 161 tests existentes y preservando la equivalencia de respuestas JSON y HTML con las referencias guardadas (*golden*).

#### Scenario: Ejecución íntegra de la suite de tests
- **WHEN** se ejecuta `python3 -m unittest discover -s . -p "test_*.py"` tras la extracción de cada módulo
- **THEN** los 161 tests o más pasan satisfactoriamente sin fallas ni errores
- **AND** ninguna aserción existente en los archivos de test es debilitada o eliminada

#### Scenario: Equivalencia de respuestas con referencias previas
- **WHEN** se comparan las respuestas de endpoints clave (`/api/estado-version`, `/api/capitulos/estado`, `/api/pendrive/estado`, `/api/lotes`) antes y después del refactor
- **THEN** las estructuras de datos y semántica de las respuestas son funcionalmente idénticas a las referencias capturadas
