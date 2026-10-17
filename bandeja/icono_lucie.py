"""Marca de Lucie dibujada con geometría: L blanca, violeta y un destello rosa.

Se rasteriza al tamaño del icono sin fuentes, imágenes externas ni dependencias.
"""
import math
import struct


def _rectangulo_redondeado(x, y, izquierda, arriba, derecha, abajo, radio):
    dx = max(izquierda + radio - x, 0, x - derecha + radio)
    dy = max(arriba + radio - y, 0, y - abajo + radio)
    return dx * dx + dy * dy <= radio * radio


def pixeles_icono(tamano=32):
    """RGBA con bordes transparentes y antialiasing; coordenadas de diseño 32×32."""
    if not 16 <= tamano <= 256:
        raise ValueError("El tamaño del icono debe estar entre 16 y 256.")
    resultado = bytearray()
    muestras = 4
    for fila in range(tamano):
        for columna in range(tamano):
            rojo = verde = azul = cubiertos = 0
            for sy in range(muestras):
                for sx in range(muestras):
                    x = (columna + (sx + 0.5) / muestras) * 32 / tamano
                    y = (fila + (sy + 0.5) / muestras) * 32 / tamano
                    if not _rectangulo_redondeado(x, y, 1, 1, 31, 31, 8):
                        continue
                    mezcla = (x + y) / 64
                    color = (int(167 - 76 * mezcla), int(104 - 55 * mezcla), int(255 - 43 * mezcla))
                    if not _rectangulo_redondeado(x, y, 1.7, 1.7, 30.3, 30.3, 7.3):
                        color = (189, 147, 255)
                    # L dibujada con dos trazos gruesos, legible aun a 16 px.
                    if (_rectangulo_redondeado(x, y, 8, 7, 13.5, 25, 1.5)
                            or _rectangulo_redondeado(x, y, 8, 19.5, 24, 25, 1.5)):
                        color = (255, 255, 255)
                    # Estrella de cuatro puntas en la esquina superior derecha.
                    if math.sqrt(abs(x - 23) / 4.5) + math.sqrt(abs(y - 9) / 4.5) <= 1:
                        color = (255, 205, 240)
                    rojo += color[0]
                    verde += color[1]
                    azul += color[2]
                    cubiertos += 1
            if cubiertos:
                resultado.extend((rojo // cubiertos, verde // cubiertos, azul // cubiertos,
                                  round(255 * cubiertos / (muestras * muestras))))
            else:
                resultado.extend((0, 0, 0, 0))
    return bytes(resultado)


def recurso_icono(tamano=32):
    """DIB de icono Windows a 32 bits con máscara AND, en orden BGRA inferior primero."""
    rgba = pixeles_icono(tamano)
    bitmap = bytearray()
    mascara = bytearray()
    paso_mascara = ((tamano + 31) // 32) * 4
    for fila in reversed(range(tamano)):
        bits = bytearray(paso_mascara)
        for columna in range(tamano):
            indice = (fila * tamano + columna) * 4
            r, g, b, a = rgba[indice:indice + 4]
            bitmap.extend((b, g, r, a))
            if a == 0:
                bits[columna // 8] |= 0x80 >> (columna % 8)
        mascara.extend(bits)
    cabecera = struct.pack("<IiiHHIIiiII", 40, tamano, tamano * 2, 1, 32, 0,
                           len(bitmap) + len(mascara), 0, 0, 0, 0)
    return cabecera + bitmap + mascara
