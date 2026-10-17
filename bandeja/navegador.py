"""Apertura del dashboard en Chrome, sin iniciar otra bandeja ni usar shell."""
import http.client
import logging
import os
import shutil
import subprocess
import sys
import time

logger = logging.getLogger("bandeja_descargas")


def localizar_chrome():
    if sys.platform == "win32":
        for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(variable)
            if base:
                ruta = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
                if os.path.isfile(ruta):
                    return ruta
        # Instalaciones con ruta propia registradas por Chrome en Windows.
        import winreg
        for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(raiz, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as clave:
                    ruta, _ = winreg.QueryValueEx(clave, "")
                if isinstance(ruta, str) and os.path.isfile(ruta):
                    return ruta
            except OSError:
                continue
    for comando in ("google-chrome", "google-chrome-stable", "chrome", "chrome.exe"):
        ruta = shutil.which(comando)
        if ruta:
            return ruta
    return None


def dashboard_disponible(puerto, timeout=0.5):
    """Comprueba la identidad del panel sin abrir Chrome ni tocar la base local."""
    conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=timeout)
    try:
        conexion.request("GET", "/panel.html")
        respuesta = conexion.getresponse()
        html = respuesta.read(131072)
        return respuesta.status == 200 and b"<title>Lucie Sin Reglas" in html and b'src="/panel.js"' in html
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conexion.close()


def abrir_dashboard_chrome(puerto, espera=5):
    """Espera respuesta del panel local y lanza Chrome; un fallo no corta la bandeja."""
    if type(puerto) is not int or not 1 <= puerto <= 65535:
        raise ValueError("Puerto del dashboard inválido.")
    url = f"http://127.0.0.1:{puerto}/"
    chrome = localizar_chrome()
    if not chrome:
        logger.warning("No se encontró Google Chrome instalado. El panel está disponible en %s", url)
        return False
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        listo = dashboard_disponible(puerto, timeout=min(0.5, max(0.01, limite - time.monotonic())))
        if listo:
            try:
                subprocess.Popen([chrome, "--new-tab", url], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info("Abriendo el dashboard en Google Chrome: %s", url)
                return True
            except OSError as error:
                logger.warning("No se pudo abrir Chrome: %s. Panel disponible en %s", error, url)
                return False
        time.sleep(min(0.1, max(0, limite - time.monotonic())))
    logger.warning("El dashboard no respondió a tiempo para abrir Chrome: %s", url)
    return False
