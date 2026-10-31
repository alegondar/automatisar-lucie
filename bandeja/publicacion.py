"""Cola de videos sin publicar y envío explícito por Wi-Fi con reversión.

El usuario define una recepción LocalSend confirmada como señal de publicación.
No consulta Instagram ni afirma haber comprobado una publicación en una red.
"""
import datetime
import hashlib
import json
import os
import secrets
import stat
import threading
import time
import unicodedata
import uuid

from bandeja.config import calcular_sha256
from bandeja.carpetas_vacias import retirar_carpetas_vacias_traslado
from bandeja.localsend import ClienteLocalSend, PUERTO_LUCIE, tipo_receptor, validar_receptor
from bandeja.pendrive import detectar_pendrive, operacion_pendrive_exclusiva
from bandeja.edicion import registrar_evento_manifiesto_edicion
from bandeja.plataforma import mover_sin_sobrescribir

CARPETA_SIN_PUBLICAR = "videos sin publicar"
CARPETA_PUBLICADOS = "videosPublicados"
from bandeja.organizacion_mensual import es_carpeta_mes, mes_del_nombre, nombre_mes, resolver_relativa
EXTENSIONES_IMAGEN = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
EXTENSIONES_VIDEO = (".mp4", ".mov", ".webm", ".mkv")


def personaje_conocido(nombre):
    texto = "".join(c for c in unicodedata.normalize("NFD", str(nombre).casefold())
                    if not unicodedata.combining(c)).strip()
    return {"lucie": "lucie", "roli": "roli", "magui": "roli", "magui la roli": "roli",
            "mailen": "mailen", "luna": "luna"}.get(texto)


def sin_enlaces(ruta):
    actual = os.path.abspath(ruta)
    while True:
        if os.path.islink(actual) or (hasattr(os.path, "isjunction") and os.path.isjunction(actual)):
            raise ValueError("No se admiten enlaces o junctions en las rutas de publicación.")
        padre = os.path.dirname(actual)
        if padre == actual:
            return
        actual = padre


class GestorPublicacion:
    def __init__(self, config, db, cliente=None):
        self.config = config
        self.db = db
        self.cliente = cliente or ClienteLocalSend()
        self._planes = {}
        self._planes_resguardo = {}
        self._dispositivos = {}
        self._trabajos = {}
        self._cancelaciones = {}
        self._lock = threading.RLock()
        from bandeja.organizacion_publicacion import GestorOrganizacionPublicacion
        self.organizacion = GestorOrganizacionPublicacion(self)

    def _identidad(self):
        pen = detectar_pendrive(self.config)
        if not pen or not pen.get("conectado"):
            raise ValueError("Conectá el pendrive vinculado para enviar videos.")
        montaje = pen.get("punto_montaje") or pen.get("ruta_montaje")
        nombre = self.config.carpeta_raiz_pendrive
        if not nombre or os.path.basename(nombre) != nombre or nombre in (".", ".."):
            raise ValueError("Raíz del pendrive inválida.")
        raiz = os.path.abspath(os.path.join(montaje, nombre))
        sin_enlaces(raiz)
        st = os.stat(raiz)
        return (pen["id"], raiz, st.st_dev, st.st_ino)

    @staticmethod
    def _ruta(raiz, relativa):
        if not isinstance(relativa, str) or not relativa or "\\" in relativa or ":" in relativa:
            raise ValueError("Ruta de publicación inválida.")
        partes = relativa.split("/")
        if any(p in ("", ".", "..") or p.startswith(".") for p in partes):
            raise ValueError("Ruta de publicación inválida.")
        ruta = os.path.join(raiz, *partes)
        sin_enlaces(ruta)
        if os.path.commonpath([os.path.realpath(raiz), os.path.realpath(ruta)]) != os.path.realpath(raiz):
            raise ValueError("Ruta fuera del pendrive.")
        return ruta

    def _inventario(self, identidad):
        raiz = identidad[1]
        base = self._ruta(raiz, "videos completos/" + CARPETA_SIN_PUBLICAR)
        archivos = {}
        if not os.path.isdir(base):
            return archivos
        personajes_por_ruta = {}
        sesiones = {s["id"]: s for s in self.db.obtener_sesiones_edicion()}
        for sesion in sesiones.values():
            if sesion.get("video_completo_ruta"):
                personajes_por_ruta[os.path.normcase(os.path.abspath(sesion["video_completo_ruta"]))] = personaje_conocido(sesion["personaje"])
        for export in self.db.obtener_exports_pendientes():
            sesion = sesiones.get(export.get("sesion_id"))
            if sesion and export.get("ruta_destino"):
                personajes_por_ruta[os.path.normcase(os.path.abspath(export["ruta_destino"]))] = personaje_conocido(sesion["personaje"])
        for carpeta, dirs, nombres in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(carpeta, d))
                       and not (hasattr(os.path, "isjunction") and os.path.isjunction(os.path.join(carpeta, d)))]
            for nombre in sorted(nombres):
                if not nombre.lower().endswith(EXTENSIONES_VIDEO + EXTENSIONES_IMAGEN):
                    continue
                ruta = os.path.join(carpeta, nombre)
                relativa = os.path.relpath(ruta, raiz).replace(os.sep, "/")
                try:
                    ruta = self._ruta(raiz, relativa)
                    st = os.stat(ruta)
                except (OSError, ValueError):
                    continue
                if not stat.S_ISREG(st.st_mode) or st.st_size <= 0:
                    continue
                identificador = hashlib.sha256(relativa.encode()).hexdigest()[:32]
                en_cola = os.path.relpath(ruta, base).replace(os.sep, "/")
                partes = en_cola.split("/")
                personaje = personaje_conocido(partes[0]) if len(partes) > 1 else None
                criterio = "carpeta" if personaje else None
                if not personaje:
                    personaje = personajes_por_ruta.get(os.path.normcase(os.path.abspath(ruta)))
                    criterio = "sesion" if personaje else None
                if not personaje:
                    # Una pista explícita en el nombre sirve para el filtro;
                    # no asigna una sesión ni mueve o renombra material.
                    nombre_base = unicodedata.normalize("NFD", nombre.casefold())
                    nombre_base = "".join(c for c in nombre_base if not unicodedata.combining(c))
                    for prefijo in ("lucie", "roli", "mailen", "luna", "magui"):
                        if nombre_base.startswith(prefijo):
                            personaje = personaje_conocido(prefijo)
                            criterio = "nombre"
                            break
                archivos[identificador] = {"id": identificador, "nombre": nombre, "ruta": relativa,
                                           "tamano": st.st_size, "mtime": st.st_mtime,
                                           "personaje": personaje or "sin_asignar", "personaje_origen": criterio,
                                           "carpeta_relativa": "/".join(partes[:-1]) or "Sin publicar (raíz)",
                                           "tipo": "imagen" if nombre.lower().endswith(EXTENSIONES_IMAGEN) else "video",
                                           "id_media": "publicacion:" + identificador}
        return archivos

    def resolver_media(self, identificador):
        """Resuelve solo IDs opacos del inventario vigente de la cola del pendrive."""
        if not isinstance(identificador, str):
            raise ValueError("Identificador de vista previa inválido.")
        identidad = self._identidad()
        entrada = self._inventario(identidad).get(identificador)
        if not entrada:
            raise ValueError("El archivo ya no está en Videos sin publicar. Actualizá la lista.")
        return self._ruta(identidad[1], entrada["ruta"]), identidad[1]

    def _historial(self, raiz, limite=30):
        ruta = os.path.join(raiz, ".lucie", "manifiesto.jsonl")
        sin_enlaces(ruta)
        publicados = {}
        preparados = {}
        if not os.path.isfile(ruta):
            return []
        with open(ruta, "r", encoding="utf-8") as archivo:
            for linea in archivo:
                try:
                    evento = json.loads(linea)
                except ValueError:
                    continue
                if evento.get("tipo_evento") in ("recepcion_wifi_confirmada", "publicado_por_envio_wifi"):
                    publicados[evento["id_operacion"]] = evento
                elif evento.get("tipo_evento") == "deshacer_publicacion_wifi":
                    publicados.pop(evento.get("id_operacion"), None)
                elif evento.get("tipo_evento") == "organizacion_completada":
                    preparados.pop(evento.get("id_organizacion"), None)
                    publicacion = evento.get("publicacion")
                    if publicacion and publicacion.get("id_operacion") in publicados:
                        publicados[publicacion["id_operacion"]] = publicacion
                elif evento.get("tipo_evento") == "organizacion_preparada":
                    preparados[evento["id_organizacion"]] = evento
        for evento in preparados.values():
            recuperado = self.organizacion.recuperar(raiz, evento)
            publicacion = recuperado.get("publicacion") if recuperado else None
            if publicacion and publicacion.get("id_operacion") in publicados:
                publicados[publicacion["id_operacion"]] = publicacion
        eventos = []
        for evento in list(publicados.values())[::-1]:
            evento = {**evento, "ruta_destino": resolver_relativa(raiz, evento["ruta_destino"]),
                      "ruta_origen": resolver_relativa(raiz, evento["ruta_origen"])}
            if evento["tipo_evento"] == "recepcion_wifi_confirmada":
                # Recuperar el historial si el proceso paró entre el renombrado
                # y el último registro. No mueve ni modifica archivos al listar.
                try:
                    origen = self._ruta(raiz, evento["ruta_origen"])
                    destino = self._ruta(raiz, evento["ruta_destino"])
                    if os.path.exists(origen) or calcular_sha256(destino) != evento["sha256"]:
                        continue
                except (OSError, ValueError):
                    continue
            eventos.append(evento)
        return eventos[:limite] if limite is not None else eventos

    def listar(self):
        try:
            identidad = self._identidad()
        except (ValueError, OSError) as e:
            return {"conectado": False, "archivos": [], "historial": [], "mensaje": str(e)}
        return {"conectado": True, "archivos": list(self._inventario(identidad).values()),
                "historial": self._historial(identidad[1]),
                "organizacion_pendiente": self.organizacion.candidatos(identidad),
                "organizaciones": self.organizacion.historial(identidad[1]),
                "carpeta": os.path.join(identidad[1], "videos completos", CARPETA_SIN_PUBLICAR)}

    def _guardar_dispositivo(self, dispositivo):
        dispositivo = {**dispositivo, "receptor": tipo_receptor(dispositivo)}
        identificador = hashlib.sha256(json.dumps(dispositivo, sort_keys=True).encode()).hexdigest()[:24]
        with self._lock:
            self._dispositivos[identificador] = dict(dispositivo)
        return {"id": identificador, **dispositivo}

    def _export_sin_sesion(self, export_id):
        if type(export_id) is not int:
            raise ValueError("Export inválido.")
        export = next((e for e in self.db.obtener_exports_pendientes() if e["id"] == export_id), None)
        if not export or export.get("sesion_id") or export["estado"] != "sin_asignar":
            raise ValueError("Export sin sesión no encontrado o ya guardado.")
        origen = export["ruta_origen"]
        sin_enlaces(origen)
        capcut = os.path.realpath(self.config.obtener_carpeta_exportacion_capcut())
        if os.path.commonpath([capcut, os.path.realpath(origen)]) != capcut:
            raise ValueError("El export está fuera de la carpeta de CapCut.")
        return export

    def simular_resguardo(self, export_id, titulo, personaje):
        from bandeja.edicion import simular_resguardo_export
        identidad = self._identidad()
        export = self._export_sin_sesion(export_id)
        plan = simular_resguardo_export(export, os.path.dirname(identidad[1]),
                                       self.config.carpeta_raiz_pendrive, titulo, personaje)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._planes_resguardo = {k: v for k, v in self._planes_resguardo.items() if v["vence"] > time.monotonic()}
            self._planes_resguardo[token] = {"identidad": identidad, "export_id": export_id,
                                            "plan": plan, "vence": time.monotonic() + 300}
        return {"token": token, **plan}

    def resguardar(self, token, confirmacion, ruta_bitacora):
        from bandeja.edicion import _resguardar_export_sin_sesion
        if confirmacion is not True or not isinstance(token, str):
            raise ValueError("Confirmá primero el plan de resguardo.")
        with operacion_pendrive_exclusiva():
            with self._lock:
                revision = self._planes_resguardo.pop(token, None)
            if not revision or revision["vence"] < time.monotonic():
                raise ValueError("El plan venció o ya se utilizó. Revisá nuevamente.")
            if self._identidad() != revision["identidad"]:
                raise ValueError("Cambió el pendrive desde la revisión.")
            export = self._export_sin_sesion(revision["export_id"])
            destino = _resguardar_export_sin_sesion(export, os.path.dirname(revision["identidad"][1]),
                self.db, self.config.carpeta_raiz_pendrive, ruta_bitacora, plan=revision["plan"])
            return {"exito": True, "destino": destino}

    def buscar_dispositivos(self, receptor=None):
        validar_receptor(receptor)
        return [self._guardar_dispositivo(d) for d in self.cliente.descubrir(receptor=receptor)
                if receptor is None or tipo_receptor(d) == receptor]

    def agregar_dispositivo(self, ip, puerto=PUERTO_LUCIE, receptor=None):
        validar_receptor(receptor)
        dispositivo = self.cliente.probar(ip, puerto)
        if receptor is not None and tipo_receptor(dispositivo) != receptor:
            raise ValueError("En esa dirección responde otra app. Elegí la app correcta antes de conectar.")
        return self._guardar_dispositivo(dispositivo)

    def simular(self, seleccion, dispositivo_id, personajes=None, receptor=None):
        validar_receptor(receptor)
        if not isinstance(seleccion, list) or not seleccion or len(seleccion) > 50 or any(not isinstance(i, str) for i in seleccion):
            raise ValueError("Elegí entre uno y cincuenta videos.")
        if not isinstance(dispositivo_id, str):
            raise ValueError("Elegí un dispositivo válido.")
        personajes = {} if personajes is None else personajes
        if not isinstance(personajes, dict) or not set(personajes).issubset(seleccion):
            raise ValueError("Asignación de personajes inválida.")
        with self._lock:
            dispositivo = self._dispositivos.get(dispositivo_id)
        if not dispositivo:
            raise ValueError("Buscá y elegí el celular antes de preparar el envío.")
        if receptor is not None and tipo_receptor(dispositivo) != receptor:
            raise ValueError("El receptor no corresponde a la app elegida. Buscá nuevamente el celular.")
        identidad = self._identidad()
        inventario = self._inventario(identidad)
        archivos = []
        destinos = set()
        for identificador in dict.fromkeys(seleccion):
            entrada = inventario.get(identificador)
            if not entrada:
                raise ValueError("Un video seleccionado ya no está en Videos sin publicar.")
            personaje = personaje_conocido(personajes.get(identificador, entrada["personaje"]))
            if not personaje:
                raise ValueError("Elegí Lucie, Roli, Mailen o Luna para " + entrada["nombre"] + " antes de enviar.")
            if entrada["personaje"] != "sin_asignar" and personaje != entrada["personaje"]:
                raise ValueError("La asignación contradice el personaje de la carpeta o sesión.")
            origen = self._ruta(identidad[1], entrada["ruta"])
            relativa = entrada["ruta"].removeprefix("videos completos/" + CARPETA_SIN_PUBLICAR + "/")
            partes = relativa.split("/")
            if len(partes) > 1 and personaje_conocido(partes[0]):
                partes = partes[1:]
            if partes and partes[0] == "sin asignar":
                partes = partes[1:]
            if partes and not es_carpeta_mes(partes[0]):
                partes.insert(0, mes_del_nombre(partes[0]) or nombre_mes(datetime.datetime.fromtimestamp(entrada["mtime"])))
            destino_rel = "videos completos/" + CARPETA_PUBLICADOS + "/" + personaje + "/" + "/".join(partes)
            destino = self._ruta(identidad[1], destino_rel)
            if destino_rel in destinos or os.path.lexists(destino):
                raise FileExistsError("Ya existe el destino de publicación: " + destino_rel + ". No se sobrescribe.")
            destinos.add(destino_rel)
            st = os.stat(origen)
            archivos.append({**entrada, "personaje": personaje, "origen": origen, "destino": destino, "destino_rel": destino_rel,
                             "sha256": calcular_sha256(origen), "firma": (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)})
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._planes = {k: v for k, v in self._planes.items() if v["vence"] > time.monotonic()}
            self._planes[token] = {"identidad": identidad, "dispositivo": dict(dispositivo), "dispositivo_id": dispositivo_id, "archivos": archivos,
                                   "vence": time.monotonic() + 300}
        return {"token": token, "dispositivo": dispositivo, "archivos": archivos,
                "total_bytes": sum(a["tamano"] for a in archivos),
                "aviso": "Tras la recepción, pasan a videos completos/videosPublicados separados por personaje. Esto no verifica Instagram."}

    def _validar_archivo(self, plan, archivo):
        if self._identidad() != plan["identidad"]:
            raise ValueError("Cambió o se desconectó el pendrive. El video no se moverá.")
        sin_enlaces(os.path.join(plan["identidad"][1], ".lucie", "manifiesto.jsonl"))
        ruta = self._ruta(plan["identidad"][1], archivo["ruta"])
        destino = self._ruta(plan["identidad"][1], archivo["destino_rel"])
        st = os.stat(ruta)
        if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != tuple(archivo["firma"]) or calcular_sha256(ruta) != archivo["sha256"]:
            raise ValueError("El video cambió desde la simulación. No se publica.")
        if os.path.exists(destino):
            raise FileExistsError("Se ocupó el destino de publicación. No se sobrescribe.")

    def _actualizar_rutas(self, origen, destino):
        sesiones = []
        for sesion in self.db.obtener_sesiones_edicion():
            if sesion.get("video_completo_ruta") == origen:
                self.db.actualizar_sesion_edicion(sesion["id"], video_completo_ruta=destino)
                sesiones.append(sesion["id"])
        for export in self.db.obtener_exports_pendientes():
            if export.get("ruta_destino") == origen or export.get("sesion_id") in sesiones:
                self.db.actualizar_export_pendiente(export["id"], ruta_destino=destino)

    def iniciar_envio(self, token, confirmacion, pin=""):
        if confirmacion is not True:
            raise ValueError("Confirmá el plan de envío antes de continuar.")
        if not isinstance(token, str) or not isinstance(pin, str) or len(pin) > 32:
            raise ValueError("Datos de envío inválidos.")
        with self._lock:
            if any(t["estado"] == "en_curso" for t in self._trabajos.values()):
                raise ValueError("Ya hay un envío Wi-Fi en curso.")
            plan = self._planes.pop(token, None)
            if not plan or plan["vence"] < time.monotonic():
                raise ValueError("El plan venció o ya se utilizó. Prepará un nuevo envío.")
            identificador = str(uuid.uuid4())
            self._trabajos[identificador] = {"id": identificador, "estado": "en_curso", "fase": "preparando", "mensaje": "Preparando envío",
                                            "dispositivo": {"id": plan["dispositivo_id"], **plan["dispositivo"]},
                                            "bytes_enviados": 0, "total_bytes": sum(a["tamano"] for a in plan["archivos"]),
                                            "publicados": [], "recibidos": [], "error": None}
            self._trabajos[identificador]["carpetas_vacias_retiradas"] = []
            self._cancelaciones[identificador] = threading.Event()
        threading.Thread(target=self._enviar, args=(identificador, plan, pin), daemon=True,
                         name="LucieEnvioWifi").start()
        return {"id": identificador}

    def estado(self, identificador):
        if not isinstance(identificador, str):
            raise ValueError("Envío inválido.")
        with self._lock:
            if identificador not in self._trabajos:
                raise ValueError("Envío no encontrado.")
            return json.loads(json.dumps(self._trabajos[identificador]))

    def cancelar(self, identificador):
        if not isinstance(identificador, str):
            raise ValueError("Envío inválido.")
        with self._lock:
            if identificador not in self._cancelaciones:
                raise ValueError("Envío no encontrado.")
            self._cancelaciones[identificador].set()
        return self.estado(identificador)

    def _enviar(self, identificador, plan, pin):
        raiz = plan["identidad"][1]
        cancelacion = self._cancelaciones[identificador]

        def progreso(cantidad, mensaje):
            with self._lock:
                self._trabajos[identificador]["bytes_enviados"] += cantidad
                self._trabajos[identificador]["mensaje"] = mensaje
                self._trabajos[identificador]["fase"] = "esperando_aceptacion" if mensaje.startswith("Esperando") else "enviando"

        def recibido(archivo):
            self._validar_archivo(plan, archivo)
            id_operacion = str(uuid.uuid4())
            evento = {"id_evento": str(uuid.uuid4()), "id_operacion": id_operacion,
                      "fecha": datetime.datetime.now().isoformat(), "ruta_origen": archivo["ruta"],
                      "ruta_destino": archivo["destino_rel"], "sha256": archivo["sha256"],
                      "bytes": archivo["tamano"], "personaje": archivo["personaje"], "dispositivo": plan["dispositivo"]["alias"]}
            registrar_evento_manifiesto_edicion(raiz, {**evento, "tipo_evento": "recepcion_wifi_confirmada"})
            with self._lock:
                self._trabajos[identificador]["recibidos"].append(archivo["nombre"])
                self._trabajos[identificador]["fase"] = "recibido"
            os.makedirs(os.path.dirname(archivo["destino"]), exist_ok=True)
            mover_sin_sobrescribir(archivo["origen"], archivo["destino"])
            registrar_evento_manifiesto_edicion(raiz, {**evento, "tipo_evento": "publicado_por_envio_wifi"})
            self._actualizar_rutas(archivo["origen"], archivo["destino"])
            with self._lock:
                self._trabajos[identificador]["publicados"].append(evento)
                self._trabajos[identificador]["fase"] = "archivado"

        try:
            with operacion_pendrive_exclusiva():
                for archivo in plan["archivos"]:
                    self._validar_archivo(plan, archivo)
                registrar_evento_manifiesto_edicion(raiz, {"id_evento": str(uuid.uuid4()),
                    "tipo_evento": "envio_wifi_iniciado", "fecha": datetime.datetime.now().isoformat(),
                    "id_envio": identificador, "dispositivo": plan["dispositivo"]["alias"],
                    "archivos": [{"ruta": a["ruta"], "sha256": a["sha256"]} for a in plan["archivos"]]})
                self.cliente.enviar(plan["dispositivo"], plan["archivos"], recibido, progreso, cancelacion, pin)
                with self._lock:
                    completo = len(self._trabajos[identificador]["publicados"]) == len(plan["archivos"])
                if completo:
                    retiradas = retirar_carpetas_vacias_traslado(raiz, [a["origen"] for a in plan["archivos"]])
                    with self._lock:
                        self._trabajos[identificador]["carpetas_vacias_retiradas"] = retiradas
            with self._lock:
                if len(self._trabajos[identificador]["publicados"]) != len(plan["archivos"]):
                    raise ValueError("No se confirmó la recepción y archivo de todos los videos.")
                self._trabajos[identificador].update(estado="completado", fase="archivado", mensaje="Recibido en el celular y archivado en Videos completos")
        except Exception as error:
            with self._lock:
                self._trabajos[identificador].update(estado="cancelado" if cancelacion.is_set() else "error",
                                                    mensaje="El envío no se completó", fase="cancelado" if cancelacion.is_set() else "error", error=str(error),
                                                    etapa=getattr(error, "etapa", "archivo"),
                                                    codigo_http=getattr(error, "codigo_http", None),
                                                    cancelacion_confirmada=getattr(error, "cancelacion_confirmada", None))

    def deshacer(self, id_operacion):
        with operacion_pendrive_exclusiva():
            identidad = self._identidad()
            evento = next((e for e in self._historial(identidad[1], limite=None) if e["id_operacion"] == id_operacion), None)
            if not evento:
                raise ValueError("Publicación no encontrada o ya deshecha.")
            origen = self._ruta(identidad[1], evento["ruta_destino"])
            destino = self._ruta(identidad[1], evento["ruta_origen"])
            if os.path.exists(destino):
                raise FileExistsError("La ruta de retorno está ocupada. No se sobrescribe.")
            if calcular_sha256(origen) != evento["sha256"]:
                raise ValueError("El video publicado cambió; no se revierte automáticamente.")
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            mover_sin_sobrescribir(origen, destino)
            registrar_evento_manifiesto_edicion(identidad[1], {"id_evento": str(uuid.uuid4()),
                "tipo_evento": "deshacer_publicacion_wifi", "id_operacion": id_operacion,
                "fecha": datetime.datetime.now().isoformat(), "ruta_destino": evento["ruta_origen"]})
            self._actualizar_rutas(origen, destino)
            return {"exito": True, "destino": destino}
