package com.luciesinreglas.recibir

import java.util.UUID
import java.util.concurrent.CountDownLatch

data class IncomingFile(val id: String, val name: String, val size: Long, val mime: String, val sha256: String?)
class ProtocolError(val status: Int, override val message: String) : Exception(message)
class ReceiveSession(val id: String, val remote: String, val sender: String, val files: List<IncomingFile>) {
    val tokens = files.associate { it.id to UUID.randomUUID().toString() }
    val decision = CountDownLatch(1)
    @Volatile var accepted = false
    @Volatile var cancelled = false
    val receiving = mutableSetOf<String>()
    val completed = mutableSetOf<String>()
    var lastActivity = System.nanoTime()
}

/** La reserva es única. Cancelar solo afecta el ID y la IP de nuestra sesión. */
class TransferState {
    private val retired = linkedMapOf<String, String>()
    private fun remember(s: ReceiveSession) {
        retired[s.id] = s.remote
        while (retired.size > 32) retired.remove(retired.keys.first())
    }
    @Volatile var session: ReceiveSession? = null
        private set
    @Synchronized fun offer(remote: String, sender: String, files: List<IncomingFile>): ReceiveSession {
        val previous = session
        if (previous != null && System.nanoTime() - previous.lastActivity > 120_000_000_000L && previous.receiving.isEmpty()) cancel()
        if (session != null) throw ProtocolError(409, "Hay una recepción en curso; aceptá, rechazá o cancelá desde el teléfono.")
        if (files.isEmpty() || files.size > 100 || files.map { it.id }.toSet().size != files.size) throw ProtocolError(400, "Lista de archivos inválida")
        files.forEach { validateFile(it) }
        return ReceiveSession(UUID.randomUUID().toString(), remote, sender.take(80), files).also { session = it }
    }
    @Synchronized fun decide(accepted: Boolean) {
        val s = session ?: return
        s.accepted = accepted
        s.lastActivity = System.nanoTime()
        s.decision.countDown()
        if (!accepted) cancel()
    }
    @Synchronized fun cancel() {
        session?.let { remember(it); it.cancelled = true; it.decision.countDown() }
        session = null
    }
    @Synchronized fun cancelOwned(id: String, remote: String): ReceiveSession? {
        val s = session
        if (s != null && s.id == id && s.remote == remote) {
            cancel()
            return s
        }
        if (retired[id] == remote) return null // Idempotente; no toca la sesión nueva.
        throw ProtocolError(403, "Sesión inválida")
    }
    @Synchronized fun owned(id: String, remote: String): ReceiveSession {
        val s = session ?: throw ProtocolError(403, "Sesión no disponible")
        if (s.id != id || s.remote != remote || s.cancelled) throw ProtocolError(403, "Sesión inválida")
        return s
    }
    @Synchronized fun beginFile(id: String, remote: String, fileId: String, token: String): Pair<ReceiveSession, IncomingFile> {
        val s = owned(id, remote)
        if (!s.accepted || s.tokens[fileId] != token) throw ProtocolError(403, "Archivo no autorizado")
        val f = s.files.find { it.id == fileId } ?: throw ProtocolError(400, "Archivo inválido")
        if (fileId in s.completed || !s.receiving.add(fileId)) throw ProtocolError(409, "Archivo ya recibido o en curso")
        s.lastActivity = System.nanoTime()
        return s to f
    }
    @Synchronized fun touch(s: ReceiveSession) { if (session === s) s.lastActivity = System.nanoTime() }
    @Synchronized fun complete(s: ReceiveSession, fileId: String) {
        if (session !== s || s.cancelled) throw ProtocolError(403, "Recepción cancelada")
        s.receiving.remove(fileId)
        s.completed.add(fileId)
        s.lastActivity = System.nanoTime()
        if (s.completed.size == s.files.size) { remember(s); session = null }
    }
    companion object {
        fun validateFile(f: IncomingFile) {
            if (f.id.isBlank() || f.id.length > 128 || f.name.isBlank() || f.name.length > 180 ||
                f.name.startsWith('.') || f.name.contains('/') || f.name.contains('\\') ||
                f.name.any { it.code < 32 } || f.size <= 0 ||
                (f.sha256 != null && !f.sha256.matches(Regex("[a-fA-F0-9]{64}")))) throw ProtocolError(400, "Metadatos inválidos")
            if (!(f.mime.startsWith("video/") || f.mime.startsWith("image/") || f.mime == "audio/mpeg")) throw ProtocolError(400, "Solo videos, imágenes y MP3")
        }
    }
}
