"""Interfaces IPv4 locales y búsqueda acotada del receptor de Lucie."""
import concurrent.futures
import ipaddress
import json
import logging
import socket
import subprocess
import sys

logger = logging.getLogger(__name__)
REDES_PRIVADAS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def interfaces_locales():
    """Lee IP y máscara vigentes; no conserva una IP anterior ni cambia la red."""
    if sys.platform == "win32":
        comando = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                   "Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred | "
                   "Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress"]
    else:
        comando = ["ip", "-j", "-4", "address", "show", "up"]
    try:
        opciones = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {}
        salida = subprocess.run(comando, capture_output=True, text=True, timeout=8, check=True, **opciones)
        datos = json.loads(salida.stdout or "[]")
        if isinstance(datos, dict):
            datos = [datos]
        direcciones = []
        if sys.platform == "win32":
            direcciones = [(d["IPAddress"], d["PrefixLength"]) for d in datos]
        else:
            direcciones = [(a["local"], a["prefixlen"]) for d in datos for a in d.get("addr_info", []) if a.get("family") == "inet"]
        resultado = []
        for ip, prefijo in direcciones:
            interfaz = ipaddress.ip_interface(f"{ip}/{int(prefijo)}")
            if interfaz.version == 4 and any(interfaz.ip in red for red in REDES_PRIVADAS):
                if interfaz not in resultado:
                    resultado.append(interfaz)
        return resultado[:4]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        logger.warning("No se pudieron consultar las interfaces locales: %s", type(error).__name__)
        return []


def buscar_puerto_lucie(interfaces, puerto=53318):
    """Respaldo sin UDP: como máximo 254 vecinos por interfaz y solo el puerto Lucie."""
    candidatos = set()
    propios = {i.ip for i in interfaces}
    for interfaz in interfaces[:4]:
        if not any(interfaz.ip in red for red in REDES_PRIVADAS):
            continue
        # En redes mayores se limita al bloque /24 de esta PC, sin recorrer /16.
        red = interfaz.network if interfaz.network.prefixlen >= 24 else ipaddress.ip_network(f"{interfaz.ip}/24", strict=False)
        candidatos.update(str(ip) for ip in red.hosts() if ip not in propios)

    def comprobar(ip):
        try:
            with socket.create_connection((ip, puerto), timeout=0.22):
                return ip
        except OSError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as grupo:
        return [ip for ip in grupo.map(comprobar, sorted(candidatos)) if ip][:32]
