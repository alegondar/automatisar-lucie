"""Renombrado sin sobrescritura: pruebas nativas y contrato POSIX simulado.

Los mocks del contrato POSIX no equivalen a ejecutar Linux. Las pruebas nativas
se ejecutan sobre el SO anfitrión y exclusivamente dentro de tempfile.
"""
import errno
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bandeja.plataforma import mover_sin_sobrescribir


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestTrasladoAtomico(unittest.TestCase):
    def test_traslado_nativo_con_nombres_unicode(self):
        with tempfile.TemporaryDirectory(prefix="traslado_atomico_") as carpeta:
            origen = os.path.join(carpeta, "edición de Mailén.webm")
            destino = os.path.join(carpeta, "publicado - canción.webm")
            with open(origen, "xb") as f:
                f.write(b"video temporal que debe conservarse integro")
            mover_sin_sobrescribir(origen, destino)
            self.assertFalse(os.path.exists(origen))
            with open(destino, "rb") as f:
                self.assertEqual(f.read(), b"video temporal que debe conservarse integro")

    def test_colision_nativa_preserva_ambos_archivos(self):
        with tempfile.TemporaryDirectory(prefix="colision_atomica_") as carpeta:
            origen, destino = (os.path.join(carpeta, n) for n in ("origen.mp4", "destino.mp4"))
            for ruta, datos in ((origen, b"nuevo"), (destino, b"anterior")):
                with open(ruta, "xb") as f:
                    f.write(datos)
            with self.assertRaises(FileExistsError):
                mover_sin_sobrescribir(origen, destino)
            for ruta, datos in ((origen, b"nuevo"), (destino, b"anterior")):
                with open(ruta, "rb") as f:
                    self.assertEqual(f.read(), datos)

    def test_contrato_renameat2_posix_simulado_usa_noreplace(self):
        funcion = Mock(return_value=0)
        with patch("bandeja.plataforma.os.name", "posix"), patch("bandeja.plataforma.ctypes.CDLL",
                return_value=SimpleNamespace(renameat2=funcion)) as cargar, patch("bandeja.plataforma.os.rename") as inseguro:
            mover_sin_sobrescribir("origen con acento é.mp4", "destino.mp4")
            cargar.assert_called_once_with(None, use_errno=True)
            funcion.assert_called_once_with(-100, os.fsencode("origen con acento é.mp4"), -100, os.fsencode("destino.mp4"), 1)
            inseguro.assert_not_called()

    def test_posix_simulado_sin_capacidad_o_con_colision_falla_sin_fallback(self):
        with patch("bandeja.plataforma.os.name", "posix"), patch("bandeja.plataforma.os.rename") as inseguro:
            with patch("bandeja.plataforma.ctypes.CDLL", return_value=SimpleNamespace()), self.assertRaises(OSError):
                mover_sin_sobrescribir("origen.mp4", "destino.mp4")
            for codigo in (errno.EEXIST, errno.ENOSYS, errno.EOPNOTSUPP):
                with self.subTest(errno=codigo), patch("bandeja.plataforma.ctypes.CDLL",
                        return_value=SimpleNamespace(renameat2=Mock(return_value=-1))), patch("bandeja.plataforma.ctypes.get_errno",
                        return_value=codigo), self.assertRaises(OSError) as capturado:
                    mover_sin_sobrescribir("origen.mp4", "destino.mp4")
                self.assertEqual(capturado.exception.errno, codigo)
            inseguro.assert_not_called()


if __name__ == "__main__":
    unittest.main()
