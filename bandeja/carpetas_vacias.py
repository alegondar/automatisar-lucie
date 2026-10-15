"""Retira únicamente padres vacíos de archivos trasladados y registrados.

No recorre categorías ni elimina carpetas históricas o capítulos ajenos.
Las raíces, personajes y respaldos permanecen disponibles.
"""
import os

from bandeja.plataforma import esta_confinado_en_raiz


def _sin_enlaces(ruta):
    actual = os.path.abspath(ruta)
    while True:
        if os.path.islink(actual) or (hasattr(os.path, "isjunction") and os.path.isjunction(actual)):
            return False
        padre = os.path.dirname(actual)
        if padre == actual:
            return True
        actual = padre


def retirar_carpetas_vacias_traslado(raiz, origenes):
    """Usar solo después de verificar el traslado y escribir sus registros.

    rmdir comprueba la ausencia de contenido de forma atómica. Se detiene en
    personajes/categorías; no sigue enlaces ni toca archivos o ramas hermanas.
    """
    raiz = os.path.abspath(raiz)
    candidatas = set()
    for origen in origenes:
        if not isinstance(origen, str):
            continue
        origen = os.path.abspath(origen)
        if not esta_confinado_en_raiz(origen, raiz) or not _sin_enlaces(origen):
            continue
        partes = os.path.relpath(origen, raiz).split(os.sep)
        if any(p in ("", ".", "..") or p.startswith(("_", ".")) for p in partes):
            continue
        if partes[0] in ("videos sin editar", "videos ya editados", "audios"):
            protegidos = 2  # categoría/personaje
        elif len(partes) > 2 and partes[:2] in (
                ["videos completos", "videos sin publicar"],
                ["videos completos", "videosPublicados"]):
            protegidos = 3  # completos/cola/personaje
        else:
            continue
        # Solo los padres del archivo de esta operación, sin buscar otras ramas.
        for cantidad in range(len(partes) - 1, protegidos, -1):
            candidatas.add(os.path.join(raiz, *partes[:cantidad]))
    retiradas = []
    for ruta in sorted(candidatas, key=lambda p: (-len(p.split(os.sep)), p)):
        if not esta_confinado_en_raiz(ruta, raiz) or not _sin_enlaces(ruta):
            continue
        try:
            os.rmdir(ruta)
            retiradas.append(ruta)
        except OSError:
            # Un archivo nuevo, un bloqueo o cualquier error conserva la carpeta.
            pass
    return retiradas
