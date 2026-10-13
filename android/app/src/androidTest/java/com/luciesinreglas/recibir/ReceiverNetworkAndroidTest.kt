package com.luciesinreglas.recibir

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.net.*
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.*

/** Puertos sintéticos en emulador: LocalSend ocupado no bloquea Lucie. */
@RunWith(AndroidJUnit4::class)
class ReceiverNetworkAndroidTest {
    @Test fun separatePortsAndUnicastDiscovery() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val receiver=ReceiverServer(context) {}
        ServerSocket(53317).use { legacyTcp ->
            DatagramSocket(53317).use { legacyUdp ->
                try {
                    receiver.start()
                    val until=System.nanoTime()+5_000_000_000L
                    while(!receiver.listening && System.nanoTime()<until) Thread.sleep(50)
                    assertTrue("Lucie no abrió mientras LocalSend ocupa sus puertos",receiver.listening)
                    assertFalse(legacyTcp.isClosed);assertFalse(legacyUdp.isClosed)
                    val trust=object:X509TrustManager {
                        override fun getAcceptedIssuers()=emptyArray<X509Certificate>()
                        override fun checkClientTrusted(chain:Array<X509Certificate>,auth:String) {}
                        override fun checkServerTrusted(chain:Array<X509Certificate>,auth:String) {}
                    }
                    val tls=SSLContext.getInstance("TLS").apply{init(null,arrayOf(trust),SecureRandom())}
                    (tls.socketFactory.createSocket("127.0.0.1",ReceiverServer.RECEIVE_PORT) as SSLSocket).use { socket ->
                        socket.soTimeout=3000
                        socket.outputStream.write("GET /api/localsend/v2/info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".toByteArray())
                        val response=socket.inputStream.bufferedReader().readText()
                        assertTrue(response.startsWith("HTTP/1.1 200"))
                        val info=JSONObject(response.substringAfter("\r\n\r\n"))
                        assertEquals(53318,info.getInt("port"));assertEquals("https",info.getString("protocol"))
                    }
                    DatagramSocket().use { probe ->
                        probe.soTimeout=300
                        val body=JSONObject().put("announce",true).put("fingerprint","synthetic-host").toString().toByteArray()
                        var found:JSONObject?=null
                        val deadline=System.nanoTime()+4_000_000_000L
                        while(found==null && System.nanoTime()<deadline) {
                            probe.send(DatagramPacket(body,body.size,InetAddress.getByName("127.0.0.1"),ReceiverServer.DISCOVERY_PORT))
                            val packet=DatagramPacket(ByteArray(8192),8192)
                            try { probe.receive(packet);found=JSONObject(String(packet.data,0,packet.length)) }
                            catch(_:SocketTimeoutException) {}
                        }
                        assertNotNull("Sin respuesta unicast al puerto efímero del dashboard",found)
                        assertEquals(53318,found!!.getInt("port"));assertFalse(found!!.getBoolean("announce"))
                        assertEquals(receiver.fingerprint,found!!.getString("fingerprint"))
                    }
                } finally { receiver.stop() }
            }
        }
    }
}
