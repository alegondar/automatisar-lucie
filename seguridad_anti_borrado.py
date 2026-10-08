#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seguridad_anti_borrado.py

Analizador estático de código basado en AST (Abstract Syntax Tree) que hace
cumplir la Regla de Oro #1 y #7 del proyecto:
PROHIBICIÓN ABSOLUTA DE BORRADO Y PISADO CIEGO.

Detecta y prohíbe las siguientes 11 primitivas:
1. os.remove
2. os.unlink
3. os.rmdir
4. os.removedirs
5. Path.unlink
6. Path.rmdir
7. shutil.rmtree
8. shutil.move (copia y borra al cruzar filesystems)
9. os.replace (pisa el destino sin avisar)
10. send2trash
11. subprocess / os.system con comandos que contengan rm o rmdir
"""

import ast
import os
import re
from typing import List, Tuple, Dict, Any


PRIMITIVAS_PROHIBIDAS_ATTR = {
    # (módulo/objeto, atributo) -> nombre amigable
    ("os", "remove"): "os.remove",
    ("os", "unlink"): "os.unlink",
    ("os", "rmdir"): "os.rmdir",
    ("os", "removedirs"): "os.removedirs",
    ("os", "replace"): "os.replace",
    ("shutil", "rmtree"): "shutil.rmtree",
    ("shutil", "move"): "shutil.move",
}

METODOS_PATH_PROHIBIDOS = {
    "unlink": "Path.unlink",
    "rmdir": "Path.rmdir",
}

FUNCIONES_DIRECTAS_PROHIBIDAS = {
    "send2trash": "send2trash",
    "remove": "remove",
    "unlink": "unlink",
    "rmdir": "rmdir",
    "removedirs": "removedirs",
    "rmtree": "rmtree",
    "replace": "replace",
}


class ViolacionAntiBorrado:
    def __init__(self, archivo: str, linea: int, columna: int, primitiva: str, detalle: str):
        self.archivo = archivo
        self.linea = linea
        self.columna = columna
        self.primitiva = primitiva
        self.detalle = detalle

    def __repr__(self):
        return f"[{self.archivo}:{self.linea}:{self.columna}] Infracción Regla de Oro: {self.primitiva} - {self.detalle}"


class AnalizadorASTAntiBorrado(ast.NodeVisitor):
    def __init__(self, nombre_archivo: str = "<codigo>"):
        self.nombre_archivo = nombre_archivo
        self.infracciones: List[ViolacionAntiBorrado] = []

    def visit_Call(self, node: ast.Call):
        func = node.func
        # Caso 1: llamada a método o atributo obj.attr(...) ej: os.remove(...) o p.unlink(...)
        if isinstance(func, ast.Attribute):
            attr_name = func.attr
            
            # Obtener nombre del objeto base si es un Identificador simple
            if isinstance(func.value, ast.Name):
                obj_name = func.value.id
                par = (obj_name, attr_name)
                if par in PRIMITIVAS_PROHIBIDAS_ATTR:
                    self.infracciones.append(ViolacionAntiBorrado(
                        self.nombre_archivo, node.lineno, node.col_offset,
                        PRIMITIVAS_PROHIBIDAS_ATTR[par],
                        f"Llamada prohibida a {PRIMITIVAS_PROHIBIDAS_ATTR[par]}()"
                    ))
                elif obj_name == "os" and attr_name in ("system", "popen"):
                    self._verificar_comando_shell(node)

            # Métodos de objetos Path (ej: Path(...).unlink(), archivo_path.unlink(), etc.)
            if attr_name in METODOS_PATH_PROHIBIDOS:
                self.infracciones.append(ViolacionAntiBorrado(
                    self.nombre_archivo, node.lineno, node.col_offset,
                    METODOS_PATH_PROHIBIDOS[attr_name],
                    f"Llamada prohibida al método destructivo .{attr_name}()"
                ))

            # Caso subprocess.run(["rm", ...]) o subprocess.call(...)
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                self._verificar_comando_subprocess(node)

        # Caso 2: llamada directa importada ej: from os import remove; remove(...) o send2trash(...)
        elif isinstance(func, ast.Name):
            func_name = func.id
            if func_name in FUNCIONES_DIRECTAS_PROHIBIDAS:
                self.infracciones.append(ViolacionAntiBorrado(
                    self.nombre_archivo, node.lineno, node.col_offset,
                    func_name,
                    f"Invocación directa prohibida de {func_name}()"
                ))

        self.generic_visit(node)

    def _verificar_comando_shell(self, node: ast.Call):
        """Verifica cadenas pasadas a os.system o os.popen que ejecuten rm o rmdir."""
        if node.args:
            primer_arg = node.args[0]
            if isinstance(primer_arg, ast.Constant) and isinstance(primer_arg.value, str):
                cmd = primer_arg.value
                if re.search(r'\b(rm|rmdir)\b', cmd):
                    self.infracciones.append(ViolacionAntiBorrado(
                        self.nombre_archivo, node.lineno, node.col_offset,
                        "os.system(rm)",
                        f"Ejecución de comando shell de borrado: '{cmd}'"
                    ))

    def _verificar_comando_subprocess(self, node: ast.Call):
        """Verifica comandos de subprocess que llamen a rm o rmdir."""
        if node.args:
            arg0 = node.args[0]
            # Si es lista: ["rm", "-rf", ...]
            if isinstance(arg0, ast.List):
                for elem in arg0.elts:
                    if isinstance(elem, ast.Constant) and isinstance(elem.value, str):
                        if elem.value in ("rm", "rmdir") or re.search(r'\b(rm|rmdir)\b', elem.value):
                            self.infracciones.append(ViolacionAntiBorrado(
                                self.nombre_archivo, node.lineno, node.col_offset,
                                "subprocess(rm)",
                                f"Invocación de subprocess con comando de borrado: {elem.value}"
                            ))
                            break
            # Si es string directo: "rm -rf ..."
            elif isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                if re.search(r'\b(rm|rmdir)\b', arg0.value):
                    self.infracciones.append(ViolacionAntiBorrado(
                        self.nombre_archivo, node.lineno, node.col_offset,
                        "subprocess(rm)",
                        f"Invocación de subprocess con comando de borrado: '{arg0.value}'"
                    ))


def analizar_ast_codigo(codigo_fuente: str, nombre_archivo: str = "<codigo>") -> List[ViolacionAntiBorrado]:
    """Analiza una cadena de código Python y retorna la lista de violaciones anti-borrado."""
    try:
        arbol = ast.parse(codigo_fuente, filename=nombre_archivo)
    except SyntaxError as e:
        return [ViolacionAntiBorrado(nombre_archivo, e.lineno or 0, e.offset or 0, "SyntaxError", str(e))]
    
    analizador = AnalizadorASTAntiBorrado(nombre_archivo=nombre_archivo)
    analizador.visit(arbol)
    return analizador.infracciones


def analizar_ast_archivo(ruta_archivo: str) -> List[ViolacionAntiBorrado]:
    """Lee un archivo Python y busca llamadas a primitivas de borrado prohibidas."""
    with open(ruta_archivo, "r", encoding="utf-8", newline="\n") as f:
        contenido = f.read()
    return analizar_ast_codigo(contenido, nombre_archivo=ruta_archivo)


def descubrir_archivos_operativos(directorio_raiz: str) -> List[str]:
    """
    Descubre automáticamente todos los archivos .py operativos del proyecto:
    1. Archivos .py en la raíz del proyecto (excluyendo aquellos que comiencen con 'test_').
    2. Archivos .py dentro del paquete 'bandeja/' (recursivamente).
    Omite carpetas del sistema, entornos virtuales, tests y temporales.
    Retorna una lista ordenada de rutas absolutas sin duplicados.
    """
    raiz_abs = os.path.abspath(directorio_raiz)
    carpetas_ignoradas = {".git", "__pycache__", ".cache", ".agents", "venv", ".venv", "node_modules", "frontend", ".golden_ref"}
    archivos_operativos = set()

    # 1. Archivos en la raíz
    try:
        entradas_raiz = os.listdir(raiz_abs)
    except OSError:
        entradas_raiz = []

    for entrada in entradas_raiz:
        ruta = os.path.join(raiz_abs, entrada)
        if os.path.isfile(ruta) and entrada.endswith(".py") and not entrada.startswith("test_"):
            archivos_operativos.add(ruta)

    # 2. Archivos dentro del paquete bandeja/
    dir_bandeja = os.path.join(raiz_abs, "bandeja")
    if os.path.isdir(dir_bandeja):
        for root, dirs, files in os.walk(dir_bandeja):
            dirs[:] = [d for d in dirs if d not in carpetas_ignoradas]
            for file in files:
                if file.endswith(".py") and not file.startswith("test_"):
                    archivos_operativos.add(os.path.join(root, file))

    return sorted(list(archivos_operativos))


def auditar_archivos_proyecto(directorio_raiz: str, archivos_a_incluir: List[str] = None) -> List[ViolacionAntiBorrado]:
    """
    Audita los archivos operativos del proyecto para verificar que no contengan
    ninguna operación de borrado ni pisado destructivo.
    Si no se especifican archivos_a_incluir, descubre y audita automáticamente
    todos los archivos operativos mediante descubrir_archivos_operativos().
    """
    todas_infracciones = []
    archivos = archivos_a_incluir if archivos_a_incluir is not None else descubrir_archivos_operativos(directorio_raiz)
    for arch in archivos:
        if arch.endswith(".py") and os.path.exists(arch):
            todas_infracciones.extend(analizar_ast_archivo(arch))
    return todas_infracciones


if __name__ == "__main__":
    import sys
    directorio = sys.argv[1] if len(sys.argv) > 1 else "."
    archivos = descubrir_archivos_operativos(directorio)
    print(f"[*] Auditando {len(archivos)} archivos operativos descubiertos:")
    for a in archivos:
        print(f"  - {os.path.relpath(a, directorio)}")
    violaciones = auditar_archivos_proyecto(directorio, archivos)
    if violaciones:
        print(f"[!] Se encontraron {len(violaciones)} infracciones anti-borrado:")
        for v in violaciones:
            print(f"    {v}")
        sys.exit(1)
    else:
        print("[+] 0 infracciones detectadas. Auditoría exitosa.")
        sys.exit(0)
