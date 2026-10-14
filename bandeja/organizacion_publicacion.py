"""Reorganización manual de completos históricos, con simulación y reversión."""
import datetime
import hashlib
import json
import os
import secrets
import stat
import threading
import time
import uuid

from bandeja.config import calcular_sha256
from bandeja.edicion import registrar_evento_manifiesto_edicion
from bandeja.pendrive import operacion_pendrive_exclusiva
from bandeja.plataforma import mover_sin_sobrescribir
from bandeja.publicacion import CARPETA_PUBLICADOS, CARPETA_SIN_PUBLICAR, personaje_conocido


class GestorOrganizacionPublicacion:
    def __init__(self, publicacion):
        self.publicacion = publicacion
        self.planes = {}
        self.lock = threading.RLock()

    def candidatos(self, identidad):
        gestor = self.publicacion
        raiz = identidad[1]
        historial = gestor._historial(raiz, limite=None)
        base = gestor._ruta(raiz, "videos completos")
        candidatos = []
        if not os.path.isdir(base):
            return candidatos
        for nombre in sorted(os.listdir(base)):
            ruta = "videos completos/" + nombre
            try:
                origen = gestor._ruta(raiz, ruta)
                st = os.stat(origen)
            except (OSError, ValueError):
                continue
            personaje = personaje_conocido(nombre)
            if stat.S_ISDIR(st.st_mode) and personaje:
                # Un confirmado nunca vuelve a pendiente por mover su carpeta.
                if any(e["ruta_destino"].startswith(ruta + "/") for e in historial):
                    continue
                candidatos.append({"id": hashlib.sha256(ruta.encode()).hexdigest()[:32],
                    "ruta": ruta, "tipo": "carpeta_pendiente", "personaje": personaje})
            elif stat.S_ISREG(st.st_mode):
                evento = next((e for e in historial if e["ruta_destino"] == ruta), None)
                if evento:
                    candidatos.append({"id": hashlib.sha256(ruta.encode()).hexdigest()[:32],
                        "ruta": ruta, "tipo": "publicado", "personaje": personaje_conocido(evento.get("personaje")),
                        "publicacion": evento})
        return candidatos

    def _foto(self, raiz, relativa):
        gestor = self.publicacion
        origen = gestor._ruta(raiz, relativa)
        entradas = []
        def visitar(ruta, sufijo):
            segura = gestor._ruta(raiz, relativa + ("/" + sufijo if sufijo else ""))
            st = os.stat(segura)
            if not stat.S_ISREG(st.st_mode) and not stat.S_ISDIR(st.st_mode):
                raise ValueError("La organización solo admite archivos y carpetas normales.")
            es_archivo = stat.S_ISREG(st.st_mode)
            entradas.append({"relativa": sufijo, "archivo": es_archivo,
                "firma": [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns],
                "sha256": calcular_sha256(segura) if es_archivo else None})
            if not es_archivo:
                for nombre in sorted(os.listdir(segura)):
                    visitar(os.path.join(ruta, nombre), sufijo + "/" + nombre if sufijo else nombre)
        visitar(origen, "")
        return entradas

    def simular(self, seleccion):
        if not isinstance(seleccion, list) or not 1 <= len(seleccion) <= 100:
            raise ValueError("Elegí entre uno y cien elementos para organizar.")
        gestor = self.publicacion
        with operacion_pendrive_exclusiva(), self.lock:
            identidad = gestor._identidad()
            disponibles = {c["id"]: c for c in self.candidatos(identidad)}
            acciones = []
            vistos = set()
            for elegido in seleccion:
                if not isinstance(elegido, dict) or elegido.get("id") not in disponibles or elegido["id"] in vistos:
                    raise ValueError("Selección de organización inválida o repetida.")
                vistos.add(elegido["id"])
                candidato = disponibles[elegido["id"]]
                personaje = personaje_conocido(elegido.get("personaje") or candidato["personaje"])
                if not personaje or (candidato["tipo"] == "carpeta_pendiente" and personaje != candidato["personaje"]):
                    raise ValueError("Elegí el personaje correcto antes de organizar.")
                destino = "videos completos/" + (CARPETA_SIN_PUBLICAR if candidato["tipo"] == "carpeta_pendiente" else CARPETA_PUBLICADOS) + "/" + personaje
                if candidato["tipo"] == "publicado":
                    destino += "/" + candidato["ruta"].split("/")[-1]
                if os.path.lexists(gestor._ruta(identidad[1], destino)):
                    raise FileExistsError("El destino ya existe; no se fusiona ni sobrescribe: " + destino)
                foto = self._foto(identidad[1], candidato["ruta"])
                if candidato.get("publicacion") and foto[0]["sha256"] != candidato["publicacion"]["sha256"]:
                    raise ValueError("El publicado cambió desde su recepción; revisalo antes de organizar.")
                acciones.append({**candidato, "personaje": personaje, "destino": destino, "foto": foto,
                    "archivos": sum(e["archivo"] for e in foto),
                    "bytes": sum(e["firma"][2] for e in foto if e["archivo"])})
            token = secrets.token_urlsafe(32)
            self.planes = {k: v for k, v in self.planes.items() if v["vence"] > time.monotonic()}
            self.planes[token] = {"identidad": identidad, "acciones": acciones, "vence": time.monotonic() + 300}
            return {"token": token, "acciones": acciones, "total_bytes": sum(a["bytes"] for a in acciones)}

    def _validar(self, identidad, accion):
        gestor = self.publicacion
        if identidad != gestor._identidad():
            raise ValueError("Cambió el pendrive. Volvé a simular.")
        if os.path.lexists(gestor._ruta(identidad[1], accion["destino"])):
            raise FileExistsError("Destino ocupado; no se sobrescribe ni fusiona.")
        if self._foto(identidad[1], accion["ruta"]) != accion["foto"]:
            raise ValueError("Cambió el contenido del origen. Volvé a simular.")

    @staticmethod
    def _contenido(foto):
        # Los IDs de archivos pueden cambiar al volver a montar una unidad FAT.
        return [(e["relativa"], e["archivo"], e["firma"][2] if e["archivo"] else None, e["sha256"]) for e in foto]

    def _mover(self, identidad, accion, revierte=None):
        gestor = self.publicacion
        self._validar(identidad, accion)
        raiz = identidad[1]
        origen = gestor._ruta(raiz, accion["ruta"])
        destino = gestor._ruta(raiz, accion["destino"])
        registro = {"id_organizacion": str(uuid.uuid4()), "fecha": datetime.datetime.now().isoformat(),
                    "accion": accion, "revierte": revierte}
        registrar_evento_manifiesto_edicion(raiz, {**registro, "tipo_evento": "organizacion_preparada"})
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        mover_sin_sobrescribir(origen, destino)
        if self._contenido(self._foto(raiz, accion["destino"])) != self._contenido(accion["foto"]):
            raise ValueError("El traslado requiere revisión; se conserva todo el contenido.")
        for entrada in accion["foto"]:
            if entrada["archivo"]:
                sufijo = entrada["relativa"]
                # Los sufijos del manifiesto usan '/', pero SQLite registra
                # rutas nativas del equipo. Evitar separadores mezclados en Windows.
                partes = sufijo.split("/") if sufijo else []
                gestor._actualizar_rutas(os.path.join(origen, *partes),
                                        os.path.join(destino, *partes))
        publicacion = accion.get("publicacion")
        if publicacion:
            publicacion = {**publicacion, "ruta_destino": accion["destino"], "personaje": accion["personaje"]}
        registro["publicacion"] = publicacion
        registrar_evento_manifiesto_edicion(raiz, {**registro, "tipo_evento": "organizacion_completada"})
        return registro

    def ejecutar(self, token, confirmacion):
        if confirmacion is not True:
            raise ValueError("Revisá y confirmá la organización antes de ejecutar.")
        with self.lock:
            plan = self.planes.pop(token, None) if isinstance(token, str) else None
        if not plan or plan["vence"] < time.monotonic():
            raise ValueError("La simulación venció o ya se usó.")
        with operacion_pendrive_exclusiva():
            for accion in plan["acciones"]:
                self._validar(plan["identidad"], accion)
            completadas = []
            for accion in plan["acciones"]:
                try:
                    completadas.append(self._mover(plan["identidad"], accion))
                except (OSError, ValueError) as error:
                    return {"exito": False, "completadas": completadas, "error": str(error)}
            return {"exito": True, "completadas": completadas}

    def historial(self, raiz):
        # El manifiesto usa su ubicación protegida; nunca acepta una ruta del cliente.
        from bandeja.publicacion import sin_enlaces
        archivo = os.path.join(raiz, ".lucie", "manifiesto.jsonl")
        sin_enlaces(archivo)
        activos = {}
        preparados = {}
        if not os.path.isfile(archivo):
            return []
        with open(archivo, encoding="utf-8") as f:
            for linea in f:
                try: evento = json.loads(linea)
                except ValueError: continue
                if evento.get("tipo_evento") == "organizacion_preparada":
                    preparados[evento["id_organizacion"]] = evento
                elif evento.get("tipo_evento") == "organizacion_completada":
                    preparados.pop(evento["id_organizacion"], None)
                    if evento.get("revierte"):
                        activos.pop(evento["revierte"], None)
                    else:
                        activos[evento["id_organizacion"]] = evento
        for evento in preparados.values():
            recuperado = self.recuperar(raiz, evento)
            if recuperado:
                if recuperado.get("revierte"):
                    activos.pop(recuperado["revierte"], None)
                else:
                    activos[recuperado["id_organizacion"]] = recuperado
        return list(activos.values())[::-1]

    def recuperar(self, raiz, evento):
        accion = evento["accion"]
        try:
            if os.path.lexists(self.publicacion._ruta(raiz, accion["ruta"])):
                return None
            if self._contenido(self._foto(raiz, accion["destino"])) != self._contenido(accion["foto"]):
                return None
        except (OSError, ValueError):
            return None
        publicacion = accion.get("publicacion")
        if publicacion:
            publicacion = {**publicacion, "ruta_destino": accion["destino"], "personaje": accion["personaje"]}
        return {**evento, "publicacion": publicacion, "recuperado": True}

    def deshacer(self, identificador):
        with operacion_pendrive_exclusiva():
            identidad = self.publicacion._identidad()
            evento = next((e for e in self.historial(identidad[1]) if e["id_organizacion"] == identificador), None)
            if not evento:
                raise ValueError("Organización no encontrada o ya deshecha.")
            original = evento["accion"]
            inversa = {**original, "ruta": original["destino"], "destino": original["ruta"]}
            actual = self._foto(identidad[1], inversa["ruta"])
            if self._contenido(actual) != self._contenido(original["foto"]):
                raise ValueError("El contenido cambió; no se deshace automáticamente.")
            inversa["foto"] = actual
            registro = self._mover(identidad, inversa, revierte=identificador)
            return {"exito": True, "destino": registro["accion"]["destino"]}
