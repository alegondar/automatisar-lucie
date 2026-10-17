"""Descubrimiento: interfaces simuladas, sin sondear la red real como fixture."""
import ipaddress
import json
import socket
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bandeja.red_local import interfaces_locales, buscar_puerto_lucie
from bandeja.localsend import ClienteLocalSend


def setUpModule():
    import guardia_hermetica
    guardia_hermetica.activar_guardia()


class TestRedLocal(unittest.TestCase):
    def test_interfaces_windows_con_mascara_real_sin_apipa_ni_publicas(self):
        datos = [{'IPAddress': ip, 'PrefixLength': prefijo} for ip, prefijo in
                 [('192.168.4.15', 24), ('10.5.0.2', 16), ('169.254.1.1', 16), ('127.0.0.1', 8), ('8.8.8.8', 24)]]
        with patch('bandeja.red_local.sys.platform', 'win32'), \
             patch('bandeja.red_local.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(datos))) as ejecutar:
            self.assertEqual([str(i) for i in interfaces_locales()], ['192.168.4.15/24', '10.5.0.2/16'])
            self.assertIn('Get-NetIPAddress', ejecutar.call_args.args[0][-1])
            self.assertEqual(ejecutar.call_args.kwargs['timeout'], 8)

    def test_interfaces_linux_y_capacidad_ausente(self):
        datos = [{'addr_info': [{'family': 'inet', 'local': '192.168.8.2', 'prefixlen': 25}]}]
        with patch('bandeja.red_local.sys.platform', 'linux'), \
             patch('bandeja.red_local.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(datos))):
            self.assertEqual([str(i) for i in interfaces_locales()], ['192.168.8.2/25'])
        with patch('bandeja.red_local.subprocess.run', side_effect=FileNotFoundError):
            self.assertEqual(interfaces_locales(), [])

    def test_respaldo_solo_vecinos_puerto_lucie_sin_redes_externas(self):
        llamadas = []

        class Conexion:
            def __enter__(self): return self
            def __exit__(self, *args): pass

        def conectar(destino, timeout):
            llamadas.append((destino, timeout))
            if destino[0] == '10.2.3.70': return Conexion()
            raise OSError('No hay receptor')

        with patch('bandeja.red_local.socket.create_connection', side_effect=conectar):
            encontrados = buscar_puerto_lucie([ipaddress.ip_interface('10.2.3.25/16'), ipaddress.ip_interface('8.8.8.8/24')])
        self.assertEqual(encontrados, ['10.2.3.70'])
        self.assertEqual(len(llamadas), 253)
        self.assertTrue(all(ipaddress.ip_address(ip) in ipaddress.ip_network('10.2.3.0/24') and puerto == 53318
                            for (ip, puerto), _ in llamadas))
        self.assertTrue(all(espera == .22 for _, espera in llamadas))

    def test_multicast_por_interfaz_y_broadcast_dirigido_sin_localsend(self):
        destinos, opciones = [], []

        class Udp:
            def setsockopt(self, *args): opciones.append(args)
            def bind(self, *args): pass
            def settimeout(self, *args): pass
            def sendto(self, cuerpo, destino):
                destinos.append(destino)
                if destino[0] == '224.0.0.167': raise OSError('Multicast bloqueado')
            def recvfrom(self, *args): time.sleep(.02); raise socket.timeout()
            def close(self): pass

        cliente = ClienteLocalSend()
        receptor = {'ip': '192.168.4.70', 'port': 53318, 'protocol': 'https', 'alias': 'Lucie Recibir · fixture', 'fingerprint': 'verificada'}
        with patch('bandeja.localsend.interfaces_locales', return_value=[ipaddress.ip_interface('192.168.4.20/24')]), \
             patch('bandeja.localsend.socket.socket', return_value=Udp()), \
             patch('bandeja.localsend.ThreadingHTTPServer') as servidor, \
             patch('bandeja.localsend.buscar_puerto_lucie', return_value=['192.168.4.70']) as respaldo, \
             patch.object(cliente, 'probar', return_value=receptor) as verificar:
            self.assertEqual(cliente.descubrir(.1, receptor='lucie'), [receptor])
            servidor.assert_not_called()
            respaldo.assert_called_once()
            verificar.assert_called_once_with('192.168.4.70', 53318, 'https', timeout=1)
        self.assertIn(('192.168.4.255', 53319), destinos)
        self.assertTrue(all(puerto == 53319 for _, puerto in destinos))
        self.assertIn((socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('192.168.4.20')), opciones)

    def test_socket_udp_rechazado_no_anula_respaldo_ni_acepta_otra_app(self):
        cliente = ClienteLocalSend()
        otra_app = {'ip': '192.168.1.2', 'port': 53318, 'alias': 'LocalSend', 'protocol': 'https'}
        with patch('bandeja.localsend.interfaces_locales', return_value=[]), \
             patch('bandeja.localsend.socket.socket', side_effect=OSError('UDP no permitido')), \
             patch('bandeja.localsend.buscar_puerto_lucie', return_value=['192.168.1.2']), \
             patch.object(cliente, 'probar', return_value=otra_app):
            self.assertEqual(cliente.descubrir(.1, receptor='lucie'), [])


if __name__ == '__main__':
    unittest.main()
