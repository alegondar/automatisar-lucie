"""Inicio XDG por usuario: simular primero, crear exclusivamente, no pisar accesos."""
import argparse
import json
import os
from pathlib import Path
import sys


def _valor(texto):
    texto = str(texto)
    if any(ord(c) < 32 for c in texto):
        raise ValueError("La ruta contiene caracteres de control.")
    return texto.replace("\\", "\\\\")


def _argumento(texto):
    # Primero quoting de Exec, después escape de string Desktop Entry.
    texto = str(texto).replace("%", "%%")
    for caracter in ("\\", '"', "`", "$"):
        texto = texto.replace(caracter, "\\" + caracter)
    return _valor('"' + texto + '"')


def simular(carpeta_inicio=None, python=None, proyecto=None):
    if not sys.platform.startswith("linux"):
        raise ValueError("El inicio XDG requiere Linux.")
    proyecto = Path(proyecto or Path(__file__).resolve().parent).absolute()
    programa = Path(python or sys.executable).absolute()
    lanzador = proyecto / "iniciar_bandeja_linux.py"
    carpeta = Path(carpeta_inicio or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart").absolute()
    if not programa.is_file() or not os.access(programa, os.X_OK):
        raise ValueError("No se encontró un Python ejecutable.")
    if not lanzador.is_file():
        raise ValueError("Falta iniciar_bandeja_linux.py en el proyecto.")
    destino = carpeta / "org.lucie.Bandeja.desktop"
    contenido = ("[Desktop Entry]\nType=Application\nVersion=1.0\nName=Lucie\n"
        "Comment=Inicio automático de Lucie e icono junto al reloj\n"
        f"Exec={_argumento(programa)} {_argumento(lanzador)} --sin-navegador\n"
        f"Path={_valor(proyecto)}\nTerminal=false\nStartupNotify=false\n"
        "Icon=applications-multimedia\n")
    if carpeta.is_symlink() or destino.is_symlink():
        raise ValueError("El acceso de Inicio no puede ser un enlace simbólico.")
    existe = destino.exists()
    if existe and (not destino.is_file() or destino.read_text(encoding="utf-8") != contenido):
        raise FileExistsError("Ya existe un acceso Lucie distinto; se conserva sin sobrescribir.")
    return {"destino": str(destino), "programa": str(programa), "lanzador": str(lanzador),
            "contenido": contenido, "ya_instalado": existe,
            "aviso": "Arranque al entrar a la sesión gráfica X11; no abre navegador ni terminal."}


def instalar(plan):
    # Revalidar lo simulado y reservar el destino de forma exclusiva.
    destino = Path(plan["destino"])
    actual = simular(destino.parent, plan["programa"], Path(plan["lanzador"]).parent)
    if actual != plan:
        raise ValueError("Cambió el acceso desde la simulación. Volvé a simular.")
    if plan["ya_instalado"]:
        return False
    destino.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with destino.open("x", encoding="utf-8") as archivo:
        archivo.write(plan["contenido"])
        archivo.flush()
        os.fsync(archivo.fileno())
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instalar", action="store_true", help="Habilitar después de revisar la simulación")
    parser.add_argument("--carpeta-inicio", help="Destino alternativo, por ejemplo para pruebas temporales")
    parser.add_argument("--python", help="Python con GTK3 disponible")
    args = parser.parse_args()
    try:
        plan = simular(args.carpeta_inicio, args.python)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.instalar:
            print("Inicio habilitado." if instalar(plan) else "Ya estaba instalado; no se modificó.")
        else:
            print("Simulación. Para habilitarlo, ejecutar con --instalar.")
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
