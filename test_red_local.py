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
        self.assertEqual(len(llamadas), 505)  # Un éxito y dos intentos por vecino sin receptor.
        self.assertTrue(all(ipaddress.ip_address(ip) in ipaddress.ip_network('10.2.3.0/24') and puerto == 53318
                            for (ip, puerto), _ in llamadas))
        self.assertTrue(all(espera == .6 for _, espera in llamadas))

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
            verificar.assert_called_once_with('192.168.4.70', 53318, 'https', timeout=3)
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

    def test_respaldo_recupera_primer_paquete_perdido_en_una_busqueda(self):
        intentos = {}

        class Conexion:
            def __enter__(self): return self
            def __exit__(self, *args): pass

        def conectar(destino, timeout):
            ip, puerto = destino
            self.assertEqual(puerto, 53318)
            intentos[ip] = intentos.get(ip, 0) + 1
            if ip == '192.168.4.6' and intentos[ip] == 2 and timeout >= .5:
                return Conexion()
            raise socket.timeout('Primer paquete sin respuesta')

        with patch('bandeja.red_local.socket.create_connection', side_effect=conectar):
            encontrados = buscar_puerto_lucie([ipaddress.ip_interface('192.168.4.1/29')])
        self.assertEqual(encontrados, ['192.168.4.6'])
        self.assertEqual(set(intentos), {'192.168.4.2', '192.168.4.3', '192.168.4.4', '192.168.4.5', '192.168.4.6'})
        self.assertTrue(all(cantidad == 2 for cantidad in intentos.values()))

    def test_un_clic_recupera_anuncio_tardio_y_primer_fallo_https(self):
        cliente = ClienteLocalSend()
        reloj = [0.0]
        anuncios = []
        receptor = {'ip': '192.168.4.70', 'port': 53318, 'protocol': 'https',
                    'alias': 'Lucie Recibir · temporal', 'fingerprint': 'verificada'}

        class Udp:
            entregado = False
            def setsockopt(self, *args): pass
            def bind(self, *args): pass
            def settimeout(self, *args): pass
            def sendto(self, cuerpo, destino): anuncios.append((reloj[0], destino))
            def close(self): pass
            def recvfrom(self, *args):
                reloj[0] += .1
                if reloj[0] >= 4 and not self.entregado:
                    self.entregado = True
                    return json.dumps({'version': '2.0', 'port': 53318, 'protocol': 'https',
                                       'fingerprint': 'anuncio'}).encode(), ('192.168.4.70', 53319)
                raise socket.timeout()

        with patch('bandeja.localsend.interfaces_locales', return_value=[ipaddress.ip_interface('192.168.4.20/24')]), \
             patch('bandeja.localsend.socket.socket', return_value=Udp()), \
             patch('bandeja.localsend.time.monotonic', side_effect=lambda: reloj[0]), \
             patch('bandeja.localsend.ThreadingHTTPServer') as servidor, \
             patch('bandeja.localsend.buscar_puerto_lucie') as respaldo, \
             patch.object(cliente, 'probar', side_effect=[ValueError('TLS todavía no listo'), receptor]) as verificar:
            self.assertEqual(cliente.descubrir(receptor='lucie'), [receptor])
        servidor.assert_not_called()
        respaldo.assert_not_called()
        self.assertEqual(verificar.call_count, 2)
        self.assertTrue(all(c.args == ('192.168.4.70', 53318, 'https') and c.kwargs == {'timeout': 3}
                            for c in verificar.call_args_list))
        self.assertTrue(any(instante > 3 for instante, _ in anuncios))
        self.assertTrue(all(puerto == 53319 for _, (_, puerto) in anuncios))
        self.assertLessEqual(reloj[0], 6.2)

    def test_respaldo_reintenta_https_pero_no_sustituye_por_localsend(self):
        cliente = ClienteLocalSend()
        otra_app = {'ip': '192.168.1.2', 'port': 53318, 'alias': 'LocalSend', 'protocol': 'https'}
        with patch('bandeja.localsend.interfaces_locales', return_value=[]), \
             patch('bandeja.localsend.socket.socket', side_effect=OSError('UDP bloqueado')), \
             patch('bandeja.localsend.buscar_puerto_lucie', return_value=['192.168.1.2']), \
             patch.object(cliente, 'probar', side_effect=[ValueError('Primer intento falló'), otra_app]) as verificar:
            self.assertEqual(cliente.descubrir(.1, receptor='lucie'), [])
        self.assertEqual(verificar.call_count, 2)

    def test_un_clic_repite_busqueda_vacia_y_recupera_receptor_que_arranca_tarde(self):
        cliente = ClienteLocalSend()
        reloj = [0.0]
        sockets = []
        receptor = {'ip': '192.168.4.70', 'port': 53318, 'protocol': 'https',
                    'alias': 'Lucie Recibir · temporal', 'fingerprint': 'verificada'}

        class Udp:
            entregado = False
            cerrado = False
            def setsockopt(self, *args): pass
            def bind(self, *args): pass
            def settimeout(self, *args): pass
            def sendto(self, *args): pass
            def close(self): self.cerrado = True
            def recvfrom(self, *args):
                reloj[0] += .1
                if reloj[0] > 7 and not self.entregado:
                    self.entregado = True
                    return json.dumps({'version': '2.0', 'port': 53318, 'protocol': 'https',
                                       'fingerprint': 'anuncio'}).encode(), ('192.168.4.70', 53319)
                raise socket.timeout()

        def crear_udp(*args):
            udp = Udp()
            sockets.append(udp)
            return udp

        with patch('bandeja.localsend.interfaces_locales', return_value=[]) as interfaces, \
             patch('bandeja.localsend.socket.socket', side_effect=crear_udp), \
             patch('bandeja.localsend.time.monotonic', side_effect=lambda: reloj[0]), \
             patch('bandeja.localsend.buscar_puerto_lucie', return_value=[]) as respaldo, \
             patch.object(cliente, 'probar', return_value=receptor) as verificar:
            self.assertEqual(cliente.descubrir(receptor='lucie'), [receptor])
        self.assertEqual(len(sockets), 2)
        self.assertTrue(all(udp.cerrado for udp in sockets))
        self.assertEqual(interfaces.call_count, 2, 'La repetición consulta interfaces vigentes, no una IP recordada.')
        respaldo.assert_called_once()
        verificar.assert_called_once_with('192.168.4.70', 53318, 'https', timeout=3)
        self.assertLessEqual(reloj[0], 12.4)

    def test_repeticion_de_busqueda_es_acotada_y_no_cambia_de_app(self):
        cliente = ClienteLocalSend()
        with patch.object(cliente, '_descubrir_intento', return_value=[]) as intento:
            self.assertEqual(cliente.descubrir(receptor='lucie'), [])
            self.assertEqual(intento.call_args_list, [unittest.mock.call(6, 'lucie')] * 2)
            intento.reset_mock()
            self.assertEqual(cliente.descubrir(receptor='localsend'), [])
            intento.assert_called_once_with(3, 'localsend')
            intento.reset_mock()
            self.assertEqual(cliente.descubrir(.1, receptor='lucie'), [])
            intento.assert_called_once_with(.1, 'lucie')


if __name__ == '__main__':
    unittest.main()
