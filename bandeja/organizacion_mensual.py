"""Carpetas mensuales y resolución de rutas históricas reorganizadas con registro."""
import datetime
import json
import os
import re
import hashlib
import stat
import uuid

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")
_MES = "|".join(MESES)


def nombre_mes(fecha=None):
    fecha = fecha or datetime.datetime.now()
    return f"{MESES[fecha.month - 1]} - {fecha.year}"


def es_carpeta_mes(nombre):
    return bool(re.fullmatch(rf"(?:{_MES}) - [0-9]{{4}}", nombre))


def mes_del_nombre(nombre):
    resultado = re.search(rf"(?:^|[ _-])({_MES})[ _-]+([0-9]{{4}})$", nombre, re.IGNORECASE)
    return f"{resultado[1].lower()} - {resultado[2]}" if resultado else None


def partes_capitulo(partes):
    """Personaje, nombre del capítulo e índice; admite estructura antigua y mensual."""
    indice = 2 if len(partes) > 2 and es_carpeta_mes(partes[1]) else 1
    return (partes[0] if partes else "general",
            partes[indice] if len(partes) > indice + 1 else "sin_capitulo", indice)


def carpeta_capitulo(raiz, categoria, personaje, capitulo, fecha=None):
    """Nuevos destinos mensuales; continuar un destino antiguo no lo migra."""
    antigua = os.path.join(raiz, categoria, personaje, capitulo)
    resuelta = resolver_ruta(raiz, antigua)
    if resuelta != antigua:
        return resuelta
    if os.path.isdir(antigua):
        return antigua
    return os.path.join(raiz, categoria, personaje, mes_del_nombre(capitulo) or nombre_mes(fecha), capitulo)


def resolver_relativa(raiz, relativa):
    """Aplica únicamente traslados de prefijos registrados, también al deshacer."""
    relativa = relativa.replace("\\", "/")
    archivo = os.path.join(raiz, ".lucie", "manifiesto.jsonl")
    if not os.path.isfile(archivo):
        return relativa
    with open(archivo, encoding="utf-8") as entrada:
        for linea in entrada:
            try:
                evento = json.loads(linea)
            except ValueError:
                continue
            if not isinstance(evento, dict) or evento.get("tipo_evento") != "organizacion_mensual_completada":
                continue
            origen, destino = evento.get("origen"), evento.get("destino")
            if not isinstance(origen, str) or not isinstance(destino, str):
                continue
            if relativa == origen or relativa.startswith(origen + "/"):
                relativa = destino + relativa[len(origen):]
    return relativa


def resolver_ruta(raiz, ruta):
    from bandeja.plataforma import esta_confinado_en_raiz
    if not esta_confinado_en_raiz(ruta, raiz):
        raise ValueError("Ruta histórica fuera del pendrive.")
    relativa = resolver_relativa(raiz, os.path.relpath(ruta, raiz))
    resuelta = os.path.join(raiz, *relativa.split("/"))
    if not esta_confinado_en_raiz(resuelta, raiz):
        raise ValueError("El registro mensual apunta fuera del pendrive.")
    return resuelta


class OrganizadorMensual:
    """Migración seleccionada, simulada y reversible; nunca se ejecuta al arrancar."""
    BASES = ("videos sin editar", "videos ya editados", "videos completos",
             "videos completos/videos sin publicar", "videos completos/videosPublicados",
             "imagenes", "audios")
    PERSONAJES = ("lucie", "roli", "mailen", "luna", "general", "sin asignar")

    def __init__(self, raiz, db=None):
        self.raiz = os.path.abspath(raiz)
        self.db = db

    def _ruta(self, relativa):
        from bandeja.carpetas_vacias import _sin_enlaces
        from bandeja.plataforma import esta_confinado_en_raiz
        if not isinstance(relativa, str) or any(p in ("", ".", "..") for p in relativa.replace("\\", "/").split("/")):
            raise ValueError("Ruta mensual inválida.")
        ruta = os.path.join(self.raiz, *relativa.replace("\\", "/").split("/"))
        if not esta_confinado_en_raiz(ruta, self.raiz) or not _sin_enlaces(ruta):
            raise ValueError("La organización no admite enlaces ni rutas fuera del pendrive.")
        return ruta

    def _identidad(self):
        from bandeja.carpetas_vacias import _sin_enlaces
        marcador = os.path.join(os.path.dirname(self.raiz), ".lucie_pendrive.json")
        if not _sin_enlaces(self.raiz) or not _sin_enlaces(marcador):
            raise ValueError("No se permiten enlaces en el pendrive.")
        with open(marcador, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _eventos(self):
        archivo = self._ruta(".lucie/manifiesto.jsonl")
        if not os.path.isfile(archivo):
            return []
        with open(archivo, encoding="utf-8") as entrada:
            eventos = []
            for linea in entrada:
                try: evento = json.loads(linea)
                except ValueError: continue
                if isinstance(evento, dict): eventos.append(evento)
            return eventos

    def candidatos(self):
        eventos = self._eventos()
        candidatos = []
        for base in self.BASES:
            for personaje in self.PERSONAJES:
                prefijo = base + "/" + personaje
                ruta = self._ruta(prefijo)
                if not os.path.isdir(ruta): continue
                for capitulo in sorted(os.listdir(ruta)):
                    if capitulo.startswith(("_", ".")) or es_carpeta_mes(capitulo): continue
                    relativa = prefijo + "/" + capitulo
                    try:
                        if not os.path.isdir(self._ruta(relativa)): continue
                    except ValueError:
                        continue
                    mes = mes_del_nombre(capitulo)
                    criterio = "nombre" if mes else "registro"
                    if not mes:
                        fechas = []
                        for e in eventos:
                            referencias = [e.get(c, "") for c in ("ruta_destino", "ruta_relativa")]
                            if any(isinstance(r, str) and r.startswith(relativa + "/") for r in referencias):
                                try: fechas.append(datetime.datetime.fromisoformat(e["fecha"]))
                                except (ValueError, KeyError, TypeError): pass
                        if self.db is not None:
                            for sesion in self.db.obtener_sesiones_edicion():
                                if sesion.get("personaje") == personaje and sesion.get("capitulo") == capitulo:
                                    try: fechas.append(datetime.datetime.fromisoformat(sesion["fecha_creacion"]))
                                    except (ValueError, KeyError, TypeError): pass
                        meses = {nombre_mes(f) for f in fechas}
                        if len(meses) == 1: mes = meses.pop()
                    candidatos.append({"origen": relativa, "mes": mes, "criterio": criterio if mes else "requiere elección",
                                       "destino": prefijo + "/" + mes + "/" + capitulo if mes else None})
        return candidatos

    def _foto(self, relativa):
        from bandeja.config import calcular_sha256
        origen = self._ruta(relativa)
        entradas = []
        def visitar(ruta, sufijo):
            segura = self._ruta(relativa + ("/" + sufijo if sufijo else ""))
            st = os.stat(segura)
            if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                raise ValueError("Solo se admiten archivos y directorios normales.")
            archivo = stat.S_ISREG(st.st_mode)
            entradas.append({"ruta": sufijo, "archivo": archivo,
                "firma": [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns],
                "sha256": calcular_sha256(segura) if archivo else None})
            if not archivo:
                for nombre in sorted(os.listdir(segura)):
                    visitar(os.path.join(ruta, nombre), sufijo + "/" + nombre if sufijo else nombre)
        visitar(origen, "")
        return entradas

    @staticmethod
    def _contenido(foto):
        return [(e["ruta"], e["archivo"], e["firma"][2] if e["archivo"] else None, e["sha256"]) for e in foto]

    def simular(self, seleccion=None, meses=None):
        meses = meses or {}
        candidatos = self.candidatos()
        disponibles = {c["origen"]: c for c in candidatos}
        elegidos = seleccion if seleccion is not None else [c["origen"] for c in candidatos if c["mes"]]
        if not isinstance(elegidos, list) or len(set(elegidos)) != len(elegidos):
            raise ValueError("Selección mensual inválida o repetida.")
        acciones = []
        for origen in elegidos:
            if origen not in disponibles: raise ValueError("La carpeta ya no está disponible para organizar.")
            c = disponibles[origen]
            mes = meses.get(origen, c["mes"])
            if not mes or not es_carpeta_mes(mes): raise ValueError("Elegí el mes y año de la carpeta sin fecha.")
            padre, nombre = origen.rsplit("/", 1)
            destino = padre + "/" + mes + "/" + nombre
            if os.path.lexists(self._ruta(destino)): raise FileExistsError("Destino ocupado; no se fusiona: " + destino)
            acciones.append({"id": str(uuid.uuid4()), "origen": origen, "destino": destino, "foto": self._foto(origen)})
        return {"version": 1, "raiz": self.raiz, "identidad": self._identidad(), "acciones": acciones,
                "sin_fecha": [c["origen"] for c in candidatos if not c["mes"] and c["origen"] not in elegidos]}

    def _actualizar_db(self, origen, destino):
        if self.db is None: return
        def cambiar(ruta):
            if isinstance(ruta, str) and (ruta == origen or ruta.startswith(origen + os.sep)):
                return destino + ruta[len(origen):]
            return ruta
        for sesion in self.db.obtener_sesiones_edicion():
            nueva = cambiar(sesion.get("video_completo_ruta"))
            if nueva != sesion.get("video_completo_ruta"):
                self.db.actualizar_sesion_edicion(sesion["id"], video_completo_ruta=nueva)
        for export in self.db.obtener_exports_pendientes():
            nueva = cambiar(export.get("ruta_destino"))
            if nueva != export.get("ruta_destino"):
                self.db.actualizar_export_pendiente(export["id"], ruta_destino=nueva)
        with self.db._lock, self.db._conectar() as con:
            for fila in con.execute("SELECT id, ruta_actual FROM bandeja_archivos").fetchall():
                nueva = cambiar(fila["ruta_actual"])
                if nueva != fila["ruta_actual"]:
                    con.execute("UPDATE bandeja_archivos SET ruta_actual=? WHERE id=?", (nueva, fila["id"]))
            con.commit()

    def ejecutar(self, plan, confirmacion=False):
        from bandeja.edicion import _lock_crudos_edicion, registrar_evento_manifiesto_edicion
        from bandeja.pendrive import operacion_pendrive_exclusiva
        from bandeja.plataforma import mover_sin_sobrescribir, verificar_archivo_exclusivo
        if confirmacion is not True: raise ValueError("Revisá el plan y confirmá antes de organizar.")
        if plan.get("version") != 1 or plan.get("raiz") != self.raiz or plan.get("identidad") != self._identidad():
            raise ValueError("El plan pertenece a otro pendrive o cambió su identidad.")
        with _lock_crudos_edicion, operacion_pendrive_exclusiva():
            eventos = self._eventos()
            terminadas = {e.get("id") for e in eventos if e.get("tipo_evento") == "organizacion_mensual_completada"}
            preparadas = {e.get("id"): e for e in eventos if e.get("tipo_evento") == "organizacion_mensual_preparada"}
            if not isinstance(plan.get("acciones"), list): raise ValueError("Plan mensual inválido.")
            vistos = set()
            for a in plan["acciones"]:
                if not isinstance(a, dict) or not isinstance(a.get("id"), str) or a["id"] in vistos:
                    raise ValueError("Acción mensual inválida o repetida.")
                vistos.add(a["id"])
                if a.get("revierte"):
                    previa = next((e for e in eventos if e.get("id") == a["revierte"] and e.get("tipo_evento") == "organizacion_mensual_completada"), None)
                    if not previa or (a["origen"], a["destino"]) != (previa["destino"], previa["origen"]):
                        raise ValueError("La reversión no corresponde al registro original.")
                else:
                    padre, capitulo = a["origen"].rsplit("/", 1)
                    destino_padre, destino_capitulo = a["destino"].rsplit("/", 1)
                    raiz_mes, mes = destino_padre.rsplit("/", 1)
                    if (padre not in {b + "/" + p for b in self.BASES for p in self.PERSONAJES}
                            or es_carpeta_mes(capitulo) or capitulo.startswith(("_", "."))
                            or padre != raiz_mes or capitulo != destino_capitulo or not es_carpeta_mes(mes)):
                        raise ValueError("El plan solo puede agrupar capítulos por mes sin renombrarlos.")
                if a["id"] in terminadas: continue
                origen, destino = self._ruta(a["origen"]), self._ruta(a["destino"])
                if os.path.exists(origen):
                    if os.path.lexists(destino): raise FileExistsError("Destino ocupado; volvé a simular.")
                    if self._foto(a["origen"]) != a["foto"]: raise ValueError("El contenido cambió; volvé a simular.")
                    for archivo in a["foto"]:
                        if archivo["archivo"] and not verificar_archivo_exclusivo(os.path.join(origen, *archivo["ruta"].split("/"))):
                            raise ValueError("Un archivo está en uso. Cerrá el proyecto de CapCut antes de organizar.")
                else:
                    preparada = preparadas.get(a["id"])
                    if (not preparada or any(preparada.get(k) != a.get(k) for k in ("origen", "destino", "foto"))
                            or self._contenido(self._foto(a["destino"])) != self._contenido(a["foto"])):
                        raise ValueError("No se puede recuperar un traslado incompleto: revisá el contenido.")
            resultados = []
            for a in plan["acciones"]:
                if a["id"] in terminadas: continue
                origen, destino = self._ruta(a["origen"]), self._ruta(a["destino"])
                if os.path.exists(origen):
                    registrar_evento_manifiesto_edicion(self.raiz, {**a, "tipo_evento": "organizacion_mensual_preparada"})
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    mover_sin_sobrescribir(origen, destino)
                if self._contenido(self._foto(a["destino"])) != self._contenido(a["foto"]):
                    raise ValueError("El contenido requiere revisión; no se borra material.")
                self._actualizar_db(origen, destino)
                registrar_evento_manifiesto_edicion(self.raiz, {**a, "tipo_evento": "organizacion_mensual_completada",
                    "fecha": datetime.datetime.now().isoformat()})
                resultados.append(a)
            return resultados

    def simular_deshacer(self, identificador):
        evento = next((e for e in reversed(self._eventos()) if e.get("id") == identificador
                       and e.get("tipo_evento") == "organizacion_mensual_completada"), None)
        if not evento: raise ValueError("No se encontró la organización mensual.")
        if os.path.lexists(self._ruta(evento["origen"])): raise FileExistsError("El origen anterior está ocupado.")
        foto = self._foto(evento["destino"])
        if self._contenido(foto) != self._contenido(evento["foto"]):
            raise ValueError("El contenido cambió; no se deshace automáticamente.")
        return {"version": 1, "raiz": self.raiz, "identidad": self._identidad(), "acciones": [{
            "id": str(uuid.uuid4()), "revierte": identificador, "origen": evento["destino"],
            "destino": evento["origen"], "foto": foto}]}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Organizar capítulos por mes, con simulación y reversión.")
    parser.add_argument("--raiz", required=True, help="Carpeta LucieSinReglas del pendrive vinculado")
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--simular", action="store_true")
    modo.add_argument("--ejecutar", action="store_true")
    modo.add_argument("--deshacer", metavar="ID", help="Simular la reversión de una organización registrada")
    parser.add_argument("--salida", help="Archivo JSON nuevo donde guardar la simulación")
    parser.add_argument("--plan", help="Simulación revisada y aprobada")
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--db", default=".cache/inventario_pendrive_cache.sqlite")
    args = parser.parse_args()
    if args.ejecutar:
        if not args.plan or not args.confirmar:
            parser.error("Ejecutar exige --plan y --confirmar después de revisar la simulación.")
        from bandeja.db import GestorBaseDatosBandeja
        with open(args.plan, encoding="utf-8") as f: plan = json.load(f)
        resultado = OrganizadorMensual(args.raiz, GestorBaseDatosBandeja(args.db)).ejecutar(plan, True)
        print(f"Organizaciones completadas: {len(resultado)}")
        return
    if not args.salida: parser.error("La simulación requiere --salida; nunca sobrescribe un plan anterior.")
    consulta = None
    if os.path.isfile(args.db):
        import sqlite3
        import pathlib
        from types import SimpleNamespace
        # Simular no crea ni migra SQLite ni abre sus tablas para escritura.
        con = sqlite3.connect(pathlib.Path(args.db).resolve().as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try: sesiones = [dict(s) for s in con.execute("SELECT * FROM sesiones_edicion")]
        finally: con.close()
        consulta = SimpleNamespace(obtener_sesiones_edicion=lambda: sesiones)
    gestor = OrganizadorMensual(args.raiz, consulta)
    plan = gestor.simular_deshacer(args.deshacer) if args.deshacer else gestor.simular()
    with open(args.salida, "x", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"Simulación guardada: {len(plan['acciones'])} carpetas. No se movió material.")
    for origen in plan.get("sin_fecha", []): print("Requiere elegir mes y año:", origen)


if __name__ == "__main__":
    main()
