package com.luciesinreglas.recibir

import android.content.Context
import android.net.wifi.WifiManager
import android.os.Build
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.InputStream
import java.net.*
import java.nio.charset.StandardCharsets
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import javax.net.ssl.SSLServerSocket
import javax.net.ssl.SSLSocket

class ReceiverServer(private val context: Context, private val changed: (String) -> Unit) {
    companion object {
        const val RECEIVE_PORT = 53318
        const val DISCOVERY_PORT = 53319
    }
    @Volatile var pin: String? = null
    private val generation = java.util.concurrent.atomic.AtomicInteger()
    val state = TransferState()
    val sink = MediaSink(context)
    @Volatile var fingerprint = ""
        private set
    @Volatile var listening = false
        private set
    private var server: SSLServerSocket? = null
    private var multicast: MulticastSocket? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    private val connections = ConcurrentHashMap<Socket, Boolean>()
    private var workers = Executors.newFixedThreadPool(6)
    private var pendingSocket: Socket? = null
    private val uploadedSockets = ConcurrentHashMap<Socket, ReceiveSession>()
    @Volatile private var starting = false
    fun info() = JSONObject().put("alias", "Lucie Recibir · ${Build.MODEL}")
        .put("version", "2.0").put("deviceModel", Build.MODEL).put("deviceType", "mobile")
        .put("fingerprint", fingerprint).put("port", RECEIVE_PORT).put("protocol", "https").put("download", false)
    @Synchronized fun start() {
        if (listening || starting) return
        starting = true
        val epoch = generation.incrementAndGet()
        workers = Executors.newFixedThreadPool(6)
        Thread({
            try {
                val identity = Identity()
                fingerprint = identity.fingerprint
                synchronized(this) {
                    if (!starting || generation.get()!=epoch) return@Thread
                    server = (identity.context().serverSocketFactory.createServerSocket() as SSLServerSocket).apply {
                        reuseAddress = true; bind(InetSocketAddress(RECEIVE_PORT)); enabledProtocols = arrayOf("TLSv1.2", "TLSv1.3")
                    }
                    listening = true; starting = false
                }
                changed("Listo para recibir por Wi-Fi")
                startDiscovery(epoch)
                while (listening && generation.get()==epoch) {
                    val socket = server!!.accept() as SSLSocket
                    connections[socket] = true
                    if (connections.size > 8) { connections.remove(socket); socket.close(); continue }
                    workers.execute { serve(socket) }
                }
            } catch (_: Exception) {
                if (listening || starting) changed("No se pudo abrir el receptor en el puerto $RECEIVE_PORT. Detenelo y volvé a activarlo.")
            } finally { synchronized(this) { if(generation.get()==epoch){listening = false; starting = false} } }
        }, "LucieReceiver").start()
    }
    @Synchronized fun stop() {
        generation.incrementAndGet()
        starting = false; listening = false; state.cancel()
        runCatching { server?.close() }; server = null
        connections.keys.forEach { runCatching { it.close() } }; connections.clear()
        runCatching { multicast?.close() }; multicast = null
        multicastLock?.let { if (it.isHeld) it.release() }; multicastLock = null
        workers.shutdownNow()
    }
    fun decide(accepted: Boolean) { state.decide(accepted); changed(if (accepted) "Aceptado. Esperando archivos…" else "Solicitud rechazada. Listo para otro envío.") }
    fun cancelLocal() {
        val own = state.session
        state.cancel()
        pendingSocket?.let { runCatching { it.close() } }
        uploadedSockets.entries.filter { it.value === own }.forEach { runCatching { it.key.close() } }
        changed("Cancelado. Los parciales se conservan ocultos; podés recibir otro envío.")
    }
    private fun line(input: InputStream): String {
        val bytes = java.io.ByteArrayOutputStream()
        while (bytes.size() < 8192) {
            val c = input.read()
            if (c < 0) throw java.io.EOFException()
            if (c == 10) return bytes.toString("UTF-8").trimEnd('\r')
            bytes.write(c)
        }
        throw ProtocolError(400, "Cabecera demasiado larga")
    }
    private fun answer(socket: Socket, code: Int, data: JSONObject? = null) {
        val body = data?.toString()?.toByteArray(StandardCharsets.UTF_8) ?: ByteArray(0)
        val reason = when(code) {200->"OK";400->"Bad Request";403->"Forbidden";409->"Conflict";422->"Unprocessable Content";507->"Insufficient Storage";else->"Error"}
        socket.getOutputStream().apply {
            write("HTTP/1.1 $code $reason\r\nContent-Type: application/json\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray()); write(body); flush()
        }
    }
    private fun serve(socket: SSLSocket) {
        var ownSession: ReceiveSession? = null
        var incoming = false
        try {
            if (!socket.inetAddress.isSiteLocalAddress && !socket.inetAddress.isLoopbackAddress) throw ProtocolError(403, "Usá una red local")
            socket.soTimeout = 15_000; socket.startHandshake()
            val input = BufferedInputStream(socket.getInputStream())
            val request = line(input).split(' ')
            if (request.size != 3) throw ProtocolError(400, "Solicitud inválida")
            val uri = URI(request[1]); val headers = mutableMapOf<String,String>()
            var headerBytes = 0
            while (true) {
                val header = line(input); headerBytes += header.length
                if (headerBytes > 32_768) throw ProtocolError(400, "Cabeceras demasiado grandes")
                if (header.isEmpty()) break
                val colon = header.indexOf(':'); if (colon < 1) throw ProtocolError(400, "Cabecera inválida")
                val key = header.substring(0,colon).lowercase()
                if (key in headers) throw ProtocolError(400, "Cabecera repetida")
                headers[key] = header.substring(colon+1).trim()
            }
            if (headers.containsKey("transfer-encoding")) throw ProtocolError(400, "Se requiere Content-Length")
            val size = headers["content-length"]?.toLongOrNull() ?: 0L
            if (size < 0) throw ProtocolError(400, "Longitud inválida")
            val query = (uri.rawQuery ?: "").split('&').filter { it.contains('=') }.associate {
                val pieces=it.split('=',limit=2); URLDecoder.decode(pieces[0],"UTF-8") to URLDecoder.decode(pieces[1],"UTF-8")
            }
            val remote = socket.inetAddress.hostAddress ?: ""
            when {
                request[0] == "GET" && uri.path == "/api/localsend/v2/info" -> answer(socket, 200, info())
                request[0] == "POST" && uri.path == "/api/localsend/v2/register" -> {
                    if (size > 8192) throw ProtocolError(400,"Registro inválido")
                    readBody(input,size); answer(socket,200,info())
                }
                request[0] == "POST" && uri.path == "/api/localsend/v2/prepare-upload" -> {
                    val expected=pin
                    if(expected!=null && !java.security.MessageDigest.isEqual(expected.toByteArray(),(query["pin"] ?: "").toByteArray())) throw ProtocolError(401,"PIN requerido o inválido")
                    if (size !in 1..131072) throw ProtocolError(400,"Metadatos demasiado grandes")
                    val json = JSONObject(String(readBody(input,size),Charsets.UTF_8))
                    val entries = json.getJSONObject("files")
                    val files = entries.keys().asSequence().map { id ->
                        val f = entries.getJSONObject(id)
                        IncomingFile(id,f.getString("fileName"),f.getLong("size"),f.getString("fileType"),
                            if (f.isNull("sha256")) null else f.getString("sha256"))
                    }.toList()
                    val total = files.fold(0L) { sum, f -> if (f.size <= 0 || Long.MAX_VALUE-sum < f.size) throw ProtocolError(400,"Tamaño inválido") else sum+f.size }
                    sink.checkSpace(total)
                    val s = state.offer(remote,json.getJSONObject("info").optString("alias","Equipo"),files)
                    ownSession=s; pendingSocket=socket
                    changed("Solicitud de ${s.sender}. Revisá los archivos y elegí Aceptar o Rechazar.")
                    val until=System.nanoTime()+60_000_000_000L
                    // EOF antes de aceptar libera únicamente esta reserva propia.
                    socket.soTimeout=200
                    while (s.decision.count > 0 && !s.cancelled) {
                        if (System.nanoTime()>until) throw ProtocolError(403,"La aceptación venció")
                        try { if(input.read()<0) throw java.io.EOFException() else throw ProtocolError(400,"Datos inesperados") }
                        catch (_:SocketTimeoutException) { }
                    }
                    pendingSocket=null; socket.soTimeout=15_000
                    if (!s.accepted || s.cancelled) throw ProtocolError(403,"Recepción rechazada o cancelada")
                    answer(socket,200,JSONObject().put("sessionId",s.id).put("files",JSONObject(s.tokens)))
                    ownSession=null // La reserva ahora pertenece a las peticiones upload.
                }
                request[0] == "POST" && uri.path == "/api/localsend/v2/cancel" -> {
                    val own = state.cancelOwned(query["sessionId"] ?: "",remote)
                    if (own != null) uploadedSockets.entries.filter { it.value === own }.forEach { runCatching { it.key.close() } }
                    answer(socket,200); changed("Sesión cancelada. Listo para recibir de nuevo.")
                }
                request[0] == "POST" && uri.path == "/api/localsend/v2/upload" -> {
                    val (s,f)=state.beginFile(query["sessionId"] ?: "",remote,query["fileId"] ?: "",query["token"] ?: "")
                    ownSession=s; incoming=true; uploadedSockets[socket]=s
                    if (size != f.size) throw ProtocolError(400,"El tamaño no coincide")
                    var last=0L
                    sink.receive(f,input,{s.cancelled || !listening}) { count ->
                        state.touch(s)
                        if (System.nanoTime()-last>150_000_000L || count==f.size) { last=System.nanoTime(); changed("Recibiendo ${f.name}: ${count*100/f.size}%") }
                    }
                    state.complete(s,f.id)
                    answer(socket,200)
                    ownSession=null
                    changed(if (f.sha256 != null) "Recibido y verificado: ${f.name}. Disponible en la galería." else "Recibido: ${f.name}. Tamaño comprobado; el emisor no proporcionó SHA-256.")
                }
                else -> answer(socket,404)
            }
        } catch(e:Exception) {
            if (e !is ProtocolError) android.util.Log.w("LucieReceiver", "Recepción interrumpida (${e.javaClass.simpleName})")
            ownSession?.let { if(state.session === it) state.cancel() }
            val code=(e as? ProtocolError)?.status ?: 500
            if (!socket.isClosed) runCatching { answer(socket,code,JSONObject().put("message",(e as? ProtocolError)?.message ?: "Conexión interrumpida")) }
            if (ownSession!=null) changed(if(incoming) "Recepción interrumpida. Parcial preservado; podés recibir de nuevo." else "Solicitud cerrada. Listo para recibir de nuevo.")
        } finally {
            if(pendingSocket===socket) pendingSocket=null
            uploadedSockets.remove(socket);connections.remove(socket);runCatching { socket.close() }
        }
    }
    private fun readBody(input:InputStream,size:Long):ByteArray {
        val body=ByteArray(size.toInt());var position=0
        while(position<body.size){val n=input.read(body,position,body.size-position);if(n<0)throw java.io.EOFException();position+=n}
        return body
    }
    private fun startDiscovery(epoch: Int) {
        Thread({
            var udp: MulticastSocket? = null
            var lock: WifiManager.MulticastLock? = null
            try {
                val wifi=context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                val group=InetAddress.getByName("224.0.0.167")
                val socket: MulticastSocket
                synchronized(this) {
                    if (!listening || generation.get()!=epoch) return@Thread
                    lock=wifi.createMulticastLock("LucieDiscovery").apply { setReferenceCounted(false); acquire() }
                    multicastLock=lock
                    socket=MulticastSocket(null).also { udp=it }
                    socket.apply { reuseAddress=true;bind(InetSocketAddress(DISCOVERY_PORT));soTimeout=1000;joinGroup(group) }
                    multicast=socket
                }
                val announce=info().put("announce",true).toString().toByteArray()
                socket.send(DatagramPacket(announce,announce.size,group,DISCOVERY_PORT))
                while(listening && generation.get()==epoch){
                    val packet=DatagramPacket(ByteArray(8192),8192)
                    try{socket.receive(packet)}catch(_:SocketTimeoutException){continue}
                    val json=runCatching { JSONObject(String(packet.data,0,packet.length,Charsets.UTF_8)) }.getOrNull() ?: continue
                    if(!json.optBoolean("announce") || json.optString("fingerprint")==fingerprint)continue
                    if(!packet.address.isSiteLocalAddress && !packet.address.isLoopbackAddress)continue
                    val reply=info().put("announce",false).toString().toByteArray()
                    socket.send(DatagramPacket(reply,reply.size,packet.address,packet.port))
                }
            }catch(_:Exception){ /* La conexión por IP sigue disponible. */ }
            finally {
                synchronized(this) {
                    runCatching { udp?.close() }
                    lock?.let { if(it.isHeld) it.release() }
                    if(multicast===udp) multicast=null
                    if(multicastLock===lock) multicastLock=null
                }
            }
        },"LucieDiscovery").start()
    }
}
