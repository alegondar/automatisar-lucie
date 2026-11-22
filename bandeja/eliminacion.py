"""Excepciones de borrado por selección manual confirmada desde el dashboard.

Nunca se invoca desde vigilantes ni tareas automáticas. Los planes son privados
del servidor, de un solo uso y caducan a los cinco minutos.
"""
import json
import os
import secrets
import sqlite3
import stat
import threading
import time

from bandeja.config import calcular_sha256
from bandeja.pendrive import detectar_pendrive, operacion_pendrive_exclusiva
from bandeja.plataforma import verificar_archivo_exclusivo

EXTENSIONES_PREVIA = {
    '.mp4': 'video', '.mov': 'video', '.webm': 'video', '.m4v': 'video',
    '.mkv': 'video', '.avi': 'video', '.jpg': 'imagen', '.jpeg': 'imagen',
    '.png': 'imagen', '.webp': 'imagen', '.gif': 'imagen', '.bmp': 'imagen',
    '.mp3': 'audio',
}


def _sin_enlaces(ruta):
    actual = os.path.abspath(ruta)
    while True:
        if os.path.islink(actual) or (hasattr(os.path, 'isjunction') and os.path.isjunction(actual)):
            raise ValueError("No se permite eliminar a través de enlaces o junctions.")
        padre = os.path.dirname(actual)
        if padre == actual:
            break
        actual = padre


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
        _sin_enlaces(raiz)
        st = os.stat(raiz)
        return (pen['id'], montaje, raiz, st.st_dev, st.st_ino)

    def _ruta(self, raiz, relativa):
        if not isinstance(relativa, str) or not relativa or '\\' in relativa or ':' in relativa:
            raise ValueError("Ruta relativa inválida.")
        partes = relativa.split('/')
        if any(p in ('', '.', '..') or p.startswith('.') for p in partes):
            raise ValueError("La raíz y los metadatos están protegidos.")
        ruta = os.path.join(raiz, *partes)
        _sin_enlaces(ruta)
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
        _sin_enlaces(meta)
        os.makedirs(meta, exist_ok=True)
        ruta = os.path.join(meta, 'eliminaciones.jsonl')
        _sin_enlaces(ruta)
        _anexar_registro(ruta, evento)

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


def _anexar_registro(ruta, evento):
    with open(ruta, 'a', encoding='utf-8', newline='\n') as archivo:
        archivo.write(json.dumps(evento, ensure_ascii=False) + '\n')
        archivo.flush()
        os.fsync(archivo.fileno())


class GestorEliminacionLocal:
    """Elimina un archivo de Descargas de Lotes detectados o Sin identificar."""

    def __init__(self, config, vigilante, movimientos):
        self.config = config
        self.vigilante = vigilante
        self.movimientos = movimientos
        self._planes = {}
        self._lock = threading.Lock()

    def _archivo_del_inventario(self, id_media, sha256, origen):
        if not isinstance(id_media, str) or not isinstance(sha256, str):
            raise ValueError("Identificación de archivo inválida.")
        if origen not in ('lotes', 'sin-identificar'):
            raise ValueError("Vista de origen inválida.")
        estado = self.vigilante.obtener_estado()
        archivos = estado['sin_identificar'] if origen == 'sin-identificar' else (
            archivo for lote in estado['lotes'] + estado['lotes_anteriores'] for archivo in lote['archivos']
        )
        for archivo in archivos:
            if archivo.get('id_media') == id_media and archivo.get('hash') == sha256:
                return archivo
        raise ValueError("El archivo cambió o ya no figura en esta vista. Actualizá el panel.")

    def _identidad(self, ruta):
        raiz = os.path.abspath(self.config.ruta_descargas)
        if (os.path.normcase(os.path.dirname(ruta)) != os.path.normcase(raiz)
                or os.path.basename(ruta).startswith('.')
                or EXTENSIONES_PREVIA.get(os.path.splitext(ruta)[1].lower()) not in ('imagen', 'video')):
            raise ValueError("Solo se pueden eliminar fotos y videos de la carpeta Descargas.")
        _sin_enlaces(ruta)
        directorio = os.stat(raiz)
        archivo = os.lstat(ruta)
        if (not stat.S_ISREG(archivo.st_mode)
                or getattr(archivo, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or archivo.st_dev != directorio.st_dev
                or os.path.ismount(ruta)):
            raise ValueError("El elemento no es un archivo regular de Descargas.")
        return (directorio.st_dev, directorio.st_ino, archivo.st_ino, archivo.st_size,
                archivo.st_mtime_ns, archivo.st_ctime_ns)

    def _verificar(self, ruta, identidad, sha256):
        if (self._identidad(ruta) != identidad or calcular_sha256(ruta) != sha256
                or self._identidad(ruta) != identidad):
            raise ValueError("El archivo cambió desde la revisión. No se eliminó.")
        if not verificar_archivo_exclusivo(ruta):
            raise ValueError("El archivo está en uso o no se puede abrir. Cerralo y volvé a revisar.")

    def simular(self, id_media, sha256, origen='lotes'):
        archivo = self._archivo_del_inventario(id_media, sha256, origen)
        ruta = os.path.abspath(archivo['ruta'])
        identidad = self._identidad(ruta)
        self._verificar(ruta, identidad, sha256)
        with self._lock:
            ahora = time.monotonic()
            self._planes = {k: v for k, v in self._planes.items() if v['vence'] > ahora}
            if len(self._planes) >= 128:
                raise ValueError("Demasiadas revisiones pendientes. Intentá nuevamente en unos minutos.")
            token = secrets.token_urlsafe(32)
            self._planes[token] = {'id_media': id_media, 'sha256': sha256, 'ruta': ruta, 'origen': origen,
                                   'identidad': identidad, 'vence': ahora + 300}
        return {'token': token, 'ruta': ruta}

    def ejecutar(self, token, confirmado):
        if confirmado is not True or not isinstance(token, str):
            raise ValueError("Elegí Sí en la ventana para confirmar la eliminación.")
        with self._lock:
            plan = self._planes.pop(token, None)
        if not plan or time.monotonic() >= plan['vence']:
            raise ValueError("La revisión venció o ya fue utilizada. Volvé a revisar el archivo.")

        ruta = plan['ruta']
        sha256 = plan['sha256']
        with self.vigilante.bloqueo_escaneo, self.movimientos.bloqueo_archivos_locales:
            archivo = self._archivo_del_inventario(plan['id_media'], sha256, plan['origen'])
            if os.path.abspath(archivo['ruta']) != ruta:
                raise ValueError("El archivo cambió de ubicación. No se eliminó.")
            identidad = plan['identidad']
            self._verificar(ruta, identidad, sha256)
            bitacora = self.movimientos.ruta_bitacora
            _sin_enlaces(bitacora)
            registro = {'evento': 'eliminacion_local_confirmada', 'operacion': secrets.token_hex(16),
                        'ruta': ruta, 'sha256': sha256, 'fecha': time.time()}
            _anexar_registro(bitacora, registro)
            try:
                if self._identidad(ruta) != identidad:
                    raise ValueError("El archivo cambió desde la revisión. No se eliminó.")
                os.unlink(ruta)
            except (OSError, ValueError):
                _anexar_registro(bitacora, {**registro, 'evento': 'eliminacion_local_fallida'})
                raise

            self.vigilante.retirar_archivo_eliminado(ruta, plan['id_media'])
            respuesta = {'exito': True, 'ruta': ruta, 'avisos': []}
            try:
                _anexar_registro(bitacora, {**registro, 'evento': 'archivo_local_eliminado'})
            except OSError:
                respuesta['avisos'].append("El archivo se eliminó pero no se pudo registrar el resultado en la bitácora.")
            try:
                self.movimientos.db.registrar_eliminacion_local(archivo['ruta'], sha256)
            except sqlite3.Error:
                respuesta['avisos'].append("El archivo se eliminó pero no se pudo actualizar el registro de archivos pendientes.")
        return respuesta
