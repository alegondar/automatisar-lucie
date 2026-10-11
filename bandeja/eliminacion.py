"""Única excepción de borrado: selección manual confirmada desde el dashboard.

Nunca se invoca desde vigilantes ni tareas automáticas. Los planes son privados
del servidor, de un solo uso y caducan a los cinco minutos.
"""
import json
import os
import secrets
import stat
import threading
import time

from bandeja.config import calcular_sha256
from bandeja.pendrive import detectar_pendrive, operacion_pendrive_exclusiva

EXTENSIONES_PREVIA = {
    '.mp4': 'video', '.mov': 'video', '.webm': 'video', '.m4v': 'video',
    '.mkv': 'video', '.avi': 'video', '.jpg': 'imagen', '.jpeg': 'imagen',
    '.png': 'imagen', '.webp': 'imagen', '.gif': 'imagen', '.bmp': 'imagen',
    '.mp3': 'audio',
}


class GestorEliminacionPendrive:
    def __init__(self, config):
        self.config = config
        self._planes = {}
        self._lock = threading.RLock()

    def _identidad(self):
        pen = detectar_pendrive(self.config)
        if not pen:
            raise ValueError("No hay un pendrive vinculado conectado.")
        montaje = os.path.abspath(pen['punto_montaje'])
        nombre = self.config.carpeta_raiz_pendrive
        if not nombre or os.path.basename(nombre) != nombre or nombre in ('.', '..'):
            raise ValueError("Raíz del pendrive inválida.")
        raiz = os.path.join(montaje, nombre)
        self._sin_enlaces(raiz)
        st = os.stat(raiz)
        return (pen['id'], montaje, raiz, st.st_dev, st.st_ino)

    @staticmethod
    def _sin_enlaces(ruta):
        actual = os.path.abspath(ruta)
        while True:
            if os.path.islink(actual) or (hasattr(os.path, 'isjunction') and os.path.isjunction(actual)):
                raise ValueError("No se permite eliminar a través de enlaces o junctions.")
            padre = os.path.dirname(actual)
            if padre == actual:
                break
            actual = padre

    def _ruta(self, raiz, relativa):
        if not isinstance(relativa, str) or not relativa or '\\' in relativa or ':' in relativa:
            raise ValueError("Ruta relativa inválida.")
        partes = relativa.split('/')
        if any(p in ('', '.', '..') or p.startswith('.') for p in partes):
            raise ValueError("La raíz y los metadatos están protegidos.")
        ruta = os.path.join(raiz, *partes)
        self._sin_enlaces(ruta)
        if os.path.commonpath([os.path.realpath(raiz), os.path.realpath(ruta)]) != os.path.realpath(raiz):
            raise ValueError("Ruta fuera del pendrive.")
        return ruta

    def _inventario(self, raiz, seleccion):
        entradas = {}

        def visitar(rel):
            ruta = self._ruta(raiz, rel)
            st = os.lstat(ruta)
            if stat.S_ISREG(st.st_mode):
                entradas[rel] = {'ruta': rel, 'tipo': 'archivo', 'tamano': st.st_size,
                                 'sha256': calcular_sha256(ruta), 'mtime_ns': st.st_mtime_ns,
                                 'dev': st.st_dev, 'ino': st.st_ino}
            elif stat.S_ISDIR(st.st_mode):
                entradas[rel] = {'ruta': rel, 'tipo': 'carpeta', 'tamano': 0,
                                 'dev': st.st_dev, 'ino': st.st_ino}
                for nombre in sorted(os.listdir(ruta)):
                    visitar(rel + '/' + nombre)
            else:
                raise ValueError("Solo se pueden seleccionar archivos y carpetas regulares.")

        for rel in seleccion:
            visitar(rel)
        return sorted(entradas.values(), key=lambda e: e['ruta'])

    def listar(self):
        with self._lock:
            identidad = self._identidad()
            raiz = identidad[2]
            entradas = []
            for base, dirs, archivos in os.walk(raiz, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and
                                  not os.path.islink(os.path.join(base, d)) and
                                  not (hasattr(os.path, 'isjunction') and os.path.isjunction(os.path.join(base, d))))
                for nombre in dirs + sorted(archivos):
                    if nombre.startswith('.'):
                        continue
                    formato = EXTENSIONES_PREVIA.get(os.path.splitext(nombre)[1].lower())
                    if nombre not in dirs and not formato:
                        continue
                    ruta = os.path.join(base, nombre)
                    rel = os.path.relpath(ruta, raiz).replace(os.sep, '/')
                    try:
                        self._ruta(raiz, rel)
                        st = os.lstat(ruta)
                        if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                            continue
                        if stat.S_ISREG(st.st_mode) and not formato:
                            continue
                        entradas.append({'ruta': rel, 'tipo': 'carpeta' if stat.S_ISDIR(st.st_mode) else 'archivo',
                                         'formato': formato if stat.S_ISREG(st.st_mode) else None,
                                         'tamano': st.st_size if stat.S_ISREG(st.st_mode) else 0})
                    except (ValueError, OSError):
                        continue
            return {'pendrive_id': identidad[0], 'ruta_proyecto': raiz, 'entradas': entradas}

    def simular(self, seleccion):
        if not isinstance(seleccion, list) or not seleccion or len(seleccion) > 1000:
            raise ValueError("Seleccioná entre 1 y 1000 archivos o carpetas.")
        if any(not isinstance(r, str) for r in seleccion):
            raise ValueError("Selección inválida.")
        with self._lock:
            identidad = self._identidad()
            entradas = self._inventario(identidad[2], seleccion)
            ahora = time.monotonic()
            self._planes = {k: v for k, v in self._planes.items() if v['vence'] > ahora}
            if len(self._planes) >= 128:
                raise ValueError("Demasiadas simulaciones pendientes. Esperá cinco minutos.")
            token = secrets.token_urlsafe(32)
            self._planes[token] = {'identidad': identidad, 'seleccion': list(seleccion),
                                   'entradas': entradas, 'vence': ahora + 300}
            return {'token': token, 'entradas': entradas, 'pendrive_id': identidad[0],
                    'total_bytes': sum(e['tamano'] for e in entradas), 'irreversible': True}

    @staticmethod
    def _registrar(raiz, evento):
        meta = os.path.join(raiz, '.lucie')
        GestorEliminacionPendrive._sin_enlaces(meta)
        os.makedirs(meta, exist_ok=True)
        ruta = os.path.join(meta, 'eliminaciones.jsonl')
        GestorEliminacionPendrive._sin_enlaces(ruta)
        with open(ruta, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(evento, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def ejecutar(self, token, confirmacion):
        if confirmacion != 'ELIMINAR':
            raise ValueError("Escribí ELIMINAR para confirmar el borrado permanente.")
        if not isinstance(token, str):
            raise ValueError("Simulación inválida.")
        with self._lock, operacion_pendrive_exclusiva():
            plan = self._planes.pop(token, None)
            if not plan or time.monotonic() >= plan['vence']:
                raise ValueError("La simulación venció o ya fue utilizada. Simulá nuevamente.")
            if self._identidad() != plan['identidad']:
                raise ValueError("Cambió el pendrive. Simulá nuevamente.")
            raiz = plan['identidad'][2]
            if self._inventario(raiz, plan['seleccion']) != plan['entradas']:
                raise ValueError("Cambió el contenido desde la simulación. No se eliminó nada.")
            eliminados, errores = [], []
            # Hijos primero; rmdir nunca borra contenido añadido después de simular.
            entradas = sorted(plan['entradas'], key=lambda e: (e['ruta'].count('/'), e['ruta']), reverse=True)
            self._registrar(raiz, {'evento': 'eliminacion_manual_confirmada', 'token': token,
                                   'pendrive_id': plan['identidad'][0], 'entradas': plan['entradas'],
                                   'fecha': time.time()})
            for entrada in entradas:
                rel = entrada['ruta']
                try:
                    if self._identidad() != plan['identidad']:
                        raise ValueError("El pendrive cambió durante la eliminación.")
                    ruta = self._ruta(raiz, rel)
                    st = os.lstat(ruta)
                    if (st.st_dev, st.st_ino) != (entrada['dev'], entrada['ino']):
                        raise ValueError("El elemento fue reemplazado.")
                    if entrada['tipo'] == 'archivo':
                        if st.st_size != entrada['tamano'] or calcular_sha256(ruta) != entrada['sha256']:
                            raise ValueError("El archivo cambió durante la eliminación.")
                        os.unlink(ruta)
                    else:
                        os.rmdir(ruta)
                    eliminados.append(rel)
                    self._registrar(raiz, {'evento': 'elemento_eliminado_manualmente', 'ruta': rel,
                                           'token': token, 'fecha': time.time()})
                except (OSError, ValueError) as e:
                    errores.append({'ruta': rel, 'error': str(e)})
                    self._registrar(raiz, {'evento': 'eliminacion_manual_interrumpida', 'token': token,
                                           'eliminados': eliminados, 'errores': errores, 'fecha': time.time()})
                    break
            return {'exito': not errores, 'eliminados': eliminados, 'errores': errores,
                    'irreversible': True}
