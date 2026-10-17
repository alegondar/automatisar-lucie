"""Entrada sin consola para pythonw.exe; mismo servicio y configuración del .bat."""
import os
import sys
import traceback


def main():
    if sys.platform != "win32":
        raise SystemExit("Este lanzador requiere Windows; usá bandeja_descargas.py en Linux.")
    # pythonw no ofrece stdout/stderr. Guardar diagnóstico fuera del repositorio,
    # en modo append, antes de importar el servicio o sus manejadores de logs.
    carpeta = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Lucie", "logs")
    os.makedirs(carpeta, exist_ok=True)
    ruta_log = os.path.join(carpeta, "bandeja_windows.log")
    salida_anterior, error_anterior = sys.stdout, sys.stderr
    argumentos_anteriores = sys.argv
    with open(ruta_log, "a", encoding="utf-8", buffering=1) as salida:
        sys.stdout = sys.stderr = salida
        try:
            os.chdir(os.path.dirname(os.path.abspath(__file__)))
            import bandeja_descargas
            sys.argv = [__file__, "--icono", *sys.argv[1:]]
            bandeja_descargas.main()
        except Exception:
            traceback.print_exc()
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                "No se pudo iniciar Lucie. El detalle está en:\n" + ruta_log,
                "Inicio de Lucie", 0x10)
            return 1
        finally:
            sys.stdout, sys.stderr = salida_anterior, error_anterior
            sys.argv = argumentos_anteriores
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
