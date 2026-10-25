"""Icono GTK3 para la bandeja X11 de Kali/XFCE; sin vigilantes propios."""
import errno
import logging
import os
import stat
import sys
import threading

logger = logging.getLogger("bandeja_descargas")


class IconoLinux:
    """Misma interfaz que IconoWindows. GTK se usa únicamente desde su hilo."""

    def __init__(self, puerto, abrir, ruta_lock=None):
        if not sys.platform.startswith("linux"):
            raise OSError("Este icono requiere Linux.")
        self.abrir = abrir
        self.al_salir = None
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        base = runtime or os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "lucie")
        self.ruta_lock = ruta_lock or os.path.join(base, f"lucie-icono-{puerto}.lock")
        self._archivo_lock = None
        self._hilo = None
        self._listo = threading.Event()
        self._detener_solicitado = threading.Event()
        self._abriendo = threading.Lock()
        self._error = None
        self._gtk = self._glib = self._icono = self._menu = None

    def adquirir_instancia(self):
        import fcntl
        if self._archivo_lock is not None:
            return True
        base = os.path.dirname(self.ruta_lock)
        os.makedirs(base, mode=0o700, exist_ok=True)
        info = os.stat(base, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise OSError("La carpeta de bloqueo del icono no es privada del usuario.")
        fd = os.open(self.ruta_lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise OSError("Archivo de bloqueo del icono inválido.")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            if error.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        self._archivo_lock = fd
        return True

    def iniciar(self):
        if self._hilo is not None:
            raise OSError("El icono ya fue iniciado.")
        self._hilo = threading.Thread(target=self._ejecutar, name="IconoLucieLinux", daemon=True)
        self._hilo.start()
        if not self._listo.wait(10):
            raise OSError("GTK no respondió al crear el icono de Lucie.")
        if self._error:
            raise OSError("No se pudo crear el icono de Lucie: " + str(self._error))

    def esperar(self):
        if self._hilo:
            self._hilo.join()

    def detener(self):
        self._detener_solicitado.set()
        if self._glib and self._hilo and self._hilo.is_alive():
            self._glib.idle_add(self._cerrar)
        if self._hilo and self._hilo is not threading.current_thread():
            self._hilo.join(timeout=10)
        if self._archivo_lock is not None and (not self._hilo or not self._hilo.is_alive()):
            os.close(self._archivo_lock)
            self._archivo_lock = None
        # El archivo de lock queda vacío: no se borra ni se cambia su inode.

    def _abrir_panel(self, *_):
        if not self._abriendo.acquire(blocking=False):
            return

        def abrir():
            try:
                self.abrir()
            except Exception:
                logger.exception("No se pudo abrir el panel desde el icono.")
            finally:
                self._abriendo.release()
        threading.Thread(target=abrir, name="AbrirPanelDesdeIcono", daemon=True).start()

    def _cerrar(self):
        if self._icono:
            self._icono.set_visible(False)
        if self._gtk.main_level():
            self._gtk.main_quit()
        return False

    def _salir(self, *_):
        self._cerrar()
        if self.al_salir:
            threading.Thread(target=self.al_salir, name="DetenerLucieDesdeIcono", daemon=True).start()

    def _mostrar_menu(self, icono, boton, momento):
        self._menu.popup(None, None, self._gtk.StatusIcon.position_menu, icono, boton, momento)

    def _ejecutar(self):
        try:
            if not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
                raise OSError("El icono requiere sesión gráfica X11 con bandeja (Kali/XFCE).")
            try:
                import gi
                gi.require_version("Gtk", "3.0")
                from gi.repository import Gtk, GLib, GdkPixbuf
            except (ImportError, ValueError) as error:
                raise OSError("Instalá python3-gi y gir1.2-gtk-3.0 para usar el icono Linux.") from error
            self._gtk, self._glib = Gtk, GLib
            if not Gtk.init_check([])[0]:
                raise OSError("No se pudo conectar con la sesión gráfica X11.")
            from bandeja.icono_lucie import pixeles_icono
            pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(pixeles_icono(32)),
                GdkPixbuf.Colorspace.RGB, True, 8, 32, 32, 128)
            self._icono = Gtk.StatusIcon.new_from_pixbuf(pixbuf)
            self._icono.set_name("lucie-bandeja")
            self._icono.set_title("Lucie")
            self._icono.set_tooltip_text("Lucie - Clic para abrir el panel")
            self._icono.connect("activate", self._abrir_panel)
            self._icono.connect("popup-menu", self._mostrar_menu)
            self._menu = Gtk.Menu()
            abrir = Gtk.MenuItem(label="Abrir panel de Lucie")
            salir = Gtk.MenuItem(label="Salir de Lucie" if self.al_salir else "Cerrar icono")
            abrir.connect("activate", self._abrir_panel)
            salir.connect("activate", self._salir)
            self._menu.append(abrir)
            self._menu.append(salir)
            self._menu.show_all()
            self._icono.set_visible(True)
            self._listo.set()
            if not self._detener_solicitado.is_set():
                Gtk.main()
        except Exception as error:
            self._error = error
            self._listo.set()
        finally:
            if self._icono:
                self._icono.set_visible(False)
            if self._menu:
                self._menu.destroy()
