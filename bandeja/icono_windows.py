"""Icono nativo de Windows y exclusión de instancias; no accede a material."""
import ctypes
from ctypes import wintypes as w
import logging
import sys
import threading
import uuid

logger = logging.getLogger("bandeja_descargas")
WM_ICONO = 0x8001
WM_DETENER_ICONO = 0x8002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205


class IconoWindows:
    """Un icono por puerto/sesión de Windows, con bucle de mensajes propio."""

    def __init__(self, puerto, abrir):
        if sys.platform != "win32":
            raise OSError("El icono junto al reloj requiere Windows.")
        self.abrir = abrir
        self.al_salir = None
        self.hwnd = None
        self._mutex = None
        self._hicon = None
        self._hilo = None
        self._listo = threading.Event()
        self._error = None
        self._abriendo = threading.Lock()
        self._detener_solicitado = threading.Event()
        self._nombre_mutex = f"Local\\LucieBandejaIcono-{puerto}"
        self._clase = "LucieIcono-" + uuid.uuid4().hex
        self._configurar_api()

    def _configurar_api(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._proc_tipo = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class ClaseVentana(ctypes.Structure):
            _fields_ = [("cbSize", w.UINT), ("style", w.UINT), ("lpfnWndProc", self._proc_tipo),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE),
                        ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                        ("lpszClassName", w.LPCWSTR), ("hIconSm", w.HICON)]

        class DatosIcono(ctypes.Structure):
            _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT),
                        ("uFlags", w.UINT), ("uCallbackMessage", w.UINT), ("hIcon", w.HICON),
                        ("szTip", w.WCHAR * 128), ("dwState", w.DWORD), ("dwStateMask", w.DWORD),
                        ("szInfo", w.WCHAR * 256), ("uVersion", w.UINT),
                        ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON)]

        self._ClaseVentana = ClaseVentana
        self._DatosIcono = DatosIcono
        firmas = [
            (self.kernel.GetModuleHandleW, [w.LPCWSTR], w.HMODULE),
            (self.kernel.CreateMutexW, [ctypes.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE),
            (self.kernel.CloseHandle, [w.HANDLE], w.BOOL),
            (self.user.RegisterClassExW, [ctypes.POINTER(ClaseVentana)], w.ATOM),
            (self.user.UnregisterClassW, [w.LPCWSTR, w.HINSTANCE], w.BOOL),
            (self.user.CreateWindowExW, [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p], w.HWND),
            (self.user.DefWindowProcW, [w.HWND, w.UINT, w.WPARAM, w.LPARAM], ctypes.c_ssize_t),
            (self.user.CreateIconFromResourceEx, [ctypes.c_void_p, w.DWORD, w.BOOL, w.DWORD,
                                                ctypes.c_int, ctypes.c_int, w.UINT], w.HICON),
            (self.user.DestroyIcon, [w.HICON], w.BOOL),
            (self.user.RegisterWindowMessageW, [w.LPCWSTR], w.UINT),
            (self.user.GetMessageW, [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT], w.BOOL),
            (self.user.TranslateMessage, [ctypes.POINTER(w.MSG)], w.BOOL),
            (self.user.DispatchMessageW, [ctypes.POINTER(w.MSG)], ctypes.c_ssize_t),
            (self.user.PostMessageW, [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
            (self.user.PostQuitMessage, [ctypes.c_int], None),
            (self.user.DestroyWindow, [w.HWND], w.BOOL),
            (self.user.CreatePopupMenu, [], w.HMENU),
            (self.user.AppendMenuW, [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR], w.BOOL),
            (self.user.GetCursorPos, [ctypes.POINTER(w.POINT)], w.BOOL),
            (self.user.SetForegroundWindow, [w.HWND], w.BOOL),
            (self.user.TrackPopupMenu, [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, w.HWND, ctypes.c_void_p], w.UINT),
            (self.user.DestroyMenu, [w.HMENU], w.BOOL),
            (self.shell.Shell_NotifyIconW, [w.DWORD, ctypes.POINTER(DatosIcono)], w.BOOL),
        ]
        for funcion, argumentos, retorno in firmas:
            funcion.argtypes = argumentos
            funcion.restype = retorno

    def adquirir_instancia(self):
        """Mutex del icono, independiente del socket exclusivo del servidor."""
        if self._mutex:
            return True
        manejador = self.kernel.CreateMutexW(None, False, self._nombre_mutex)
        error = ctypes.get_last_error()
        if not manejador:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            self.kernel.CloseHandle(manejador)
            return False
        self._mutex = manejador
        return True

    def iniciar(self):
        self._hilo = threading.Thread(target=self._ejecutar, name="IconoLucieWindows", daemon=True)
        self._hilo.start()
        if not self._listo.wait(10):
            raise OSError("Windows no respondió al crear el icono de Lucie.")
        if self._error:
            raise OSError("No se pudo crear el icono de Lucie: " + str(self._error))

    def esperar(self):
        if self._hilo:
            self._hilo.join()

    def detener(self):
        self._detener_solicitado.set()
        if self.hwnd:
            self.user.PostMessageW(self.hwnd, WM_DETENER_ICONO, 0, 0)
        if self._hilo and self._hilo is not threading.current_thread():
            self._hilo.join(timeout=10)
        if self._mutex:
            self.kernel.CloseHandle(self._mutex)
            self._mutex = None

    def _abrir_panel(self):
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

    def _menu(self):
        menu = self.user.CreatePopupMenu()
        if not menu:
            return
        try:
            self.user.AppendMenuW(menu, 0, 1, "Abrir panel de Lucie")
            self.user.AppendMenuW(menu, 0, 2, "Salir de Lucie" if self.al_salir else "Cerrar icono")
            punto = w.POINT()
            self.user.GetCursorPos(ctypes.byref(punto))
            self.user.SetForegroundWindow(self.hwnd)
            elegido = self.user.TrackPopupMenu(menu, 0x0102, punto.x, punto.y, 0, self.hwnd, None)
            self.user.PostMessageW(self.hwnd, 0, 0, 0)
            if elegido:
                self.user.PostMessageW(self.hwnd, WM_COMMAND, elegido, 0)
        finally:
            self.user.DestroyMenu(menu)

    def _notificar(self, operacion):
        if not self._hicon and operacion != 2:
            from bandeja.icono_lucie import recurso_icono
            recurso = recurso_icono()
            buffer = ctypes.create_string_buffer(recurso)
            self._hicon = self.user.CreateIconFromResourceEx(buffer, len(recurso), True, 0x00030000, 32, 32, 0)
            if not self._hicon:
                raise ctypes.WinError(ctypes.get_last_error())
        datos = self._DatosIcono()
        datos.cbSize = ctypes.sizeof(datos)
        datos.hWnd, datos.uID = self.hwnd, 1
        datos.uFlags, datos.uCallbackMessage = 7, WM_ICONO  # mensaje, icono, tooltip
        datos.hIcon = self._hicon
        datos.szTip = "Lucie - Clic para abrir el panel"
        return bool(self.shell.Shell_NotifyIconW(operacion, ctypes.byref(datos)))

    def _mensaje(self, hwnd, mensaje, wp, lp):
        try:
            if mensaje == WM_ICONO:
                if lp == WM_LBUTTONUP:
                    self._abrir_panel()
                elif lp == WM_RBUTTONUP:
                    self._menu()
                return 0
            if mensaje == WM_COMMAND:
                if wp & 0xffff == 1:
                    self._abrir_panel()
                elif wp & 0xffff == 2:
                    self.user.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return 0
            if mensaje in (WM_CLOSE, WM_DETENER_ICONO):
                self._notificar(2)  # NIM_DELETE retira solo el icono de la interfaz.
                self.user.DestroyWindow(hwnd)
                if mensaje == WM_CLOSE and self.al_salir:
                    threading.Thread(target=self.al_salir, name="DetenerLucieDesdeIcono", daemon=True).start()
                return 0
            if mensaje == 2:  # WM_DESTROY
                self.hwnd = None
                self.user.PostQuitMessage(0)
                return 0
            if mensaje == self._taskbar_creada:
                if not self._notificar(0):
                    logger.warning("Windows todavía no permitió restaurar el icono de Lucie.")
                return 0
        except Exception:
            logger.exception("Error en el icono de Lucie.")
        return self.user.DefWindowProcW(hwnd, mensaje, wp, lp)

    def _ejecutar(self):
        registrado = False
        instancia = self.kernel.GetModuleHandleW(None)
        try:
            self._taskbar_creada = self.user.RegisterWindowMessageW("TaskbarCreated")
            if not self._taskbar_creada:
                raise ctypes.WinError(ctypes.get_last_error())
            self._proc = self._proc_tipo(self._mensaje)  # Mantener vivo el callback ctypes.
            clase = self._ClaseVentana()
            clase.cbSize = ctypes.sizeof(clase)
            clase.lpfnWndProc, clase.hInstance, clase.lpszClassName = self._proc, instancia, self._clase
            if not self.user.RegisterClassExW(ctypes.byref(clase)):
                raise ctypes.WinError(ctypes.get_last_error())
            registrado = True
            # Ventana oculta normal: recibe TaskbarCreated cuando reinicia Explorer.
            self.hwnd = self.user.CreateWindowExW(0x80, self._clase, "Lucie", 0,
                                                  0, 0, 0, 0, None, None, instancia, None)
            if not self.hwnd or not self._notificar(0):
                raise OSError("Windows rechazó la ventana o el icono de notificación.")
            self._listo.set()
            if self._detener_solicitado.is_set():
                return
            mensaje = w.MSG()
            while True:
                estado = self.user.GetMessageW(ctypes.byref(mensaje), None, 0, 0)
                if estado == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if not estado:
                    break
                self.user.TranslateMessage(ctypes.byref(mensaje))
                self.user.DispatchMessageW(ctypes.byref(mensaje))
        except Exception as error:
            self._error = error
            logger.exception("Falló el icono de Windows.")
        finally:
            if self.hwnd:
                self._notificar(2)
                self.user.DestroyWindow(self.hwnd)
                self.hwnd = None
            if registrado:
                self.user.UnregisterClassW(self._clase, instancia)
            if self._hicon:
                self.user.DestroyIcon(self._hicon)
                self._hicon = None
            self._listo.set()
