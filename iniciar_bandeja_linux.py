"""Entrada XDG sin terminal: fija el directorio y conserva diagnóstico append-only."""
import contextlib
import os
import sys
import traceback


def main():
    if not sys.platform.startswith("linux"):
        raise SystemExit("Este lanzador requiere Linux.")
    estado = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    carpeta = os.path.join(estado, "lucie", "logs")
    os.makedirs(carpeta, mode=0o700, exist_ok=True)
    ruta_log = os.path.join(carpeta, "bandeja_linux.log")
    anteriores = sys.argv
    cwd = os.getcwd()
    with open(ruta_log, "a", encoding="utf-8", buffering=1) as salida:
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            try:
                os.chdir(os.path.dirname(os.path.abspath(__file__)))
                import bandeja_descargas
                sys.argv = [__file__, "--icono", *anteriores[1:]]
                bandeja_descargas.main()
            except Exception:
                traceback.print_exc()
                return 1
            finally:
                sys.argv = anteriores
                os.chdir(cwd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
