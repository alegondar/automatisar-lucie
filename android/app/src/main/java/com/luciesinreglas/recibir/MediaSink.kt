package com.luciesinreglas.recibir

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.os.StatFs
import android.provider.MediaStore
import org.json.JSONObject
import java.io.InputStream
import java.io.FileOutputStream
import java.security.MessageDigest

/** Crea una fila nueva pendiente. Un fallo conserva el parcial oculto. */
class MediaSink(private val context: Context) {
    private val resolver get() = context.contentResolver
    fun checkSpace(size: Long) {
        val margin = 32L * 1024 * 1024
        if (size > (StatFs(Environment.getExternalStorageDirectory().path).availableBytes - margin) / 2 ||
            size > StatFs(context.filesDir.path).availableBytes - margin) throw ProtocolError(507, "No hay espacio suficiente para recepción y resguardo")
    }
    @Synchronized private fun reserve(f: IncomingFile): Uri {
        checkSpace(f.size)
        val collection: Uri
        val folder: String
        when {
            f.mime.startsWith("video/") -> { collection = MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY); folder = "Movies/LucieSinReglas/" }
            f.mime.startsWith("image/") -> { collection = MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY); folder = "Pictures/LucieSinReglas/" }
            else -> { collection = MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY); folder = "Music/LucieSinReglas/" }
        }
        var name = f.name
        var n = 1
        while (true) {
            val exists = resolver.query(collection, arrayOf(MediaStore.MediaColumns._ID),
                "${MediaStore.MediaColumns.DISPLAY_NAME}=? AND ${MediaStore.MediaColumns.RELATIVE_PATH}=?", arrayOf(name, folder), null)?.use { it.moveToFirst() } ?: false
            if (!exists) break
            val dot = f.name.lastIndexOf('.')
            name = if (dot > 0) "${f.name.substring(0,dot)} (${n++})${f.name.substring(dot)}" else "${f.name} (${n++})"
        }
        return resolver.insert(collection, ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name); put(MediaStore.MediaColumns.MIME_TYPE, f.mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, folder); put(MediaStore.MediaColumns.IS_PENDING, 1)
        }) ?: throw ProtocolError(500, "No se pudo reservar el archivo")
    }
    fun receive(f: IncomingFile, input: InputStream, cancelled: () -> Boolean, progress: (Long) -> Unit): Pair<Uri, String> {
        val uri = reserve(f)
        // MediaStore puede expirar pendientes. El resguardo privado no se limpia.
        val folder = java.io.File(context.filesDir, "resguardos").apply { mkdirs() }
        val backup = java.io.File.createTempFile("recepcion-", ".bin", folder)
        journal(f, "pendiente", uri, null, backup.name)
        val hash = MessageDigest.getInstance("SHA-256")
        try {
            val fd = resolver.openFileDescriptor(uri, "w") ?: throw ProtocolError(500, "No se pudo abrir el destino")
            fd.use { descriptor ->
                FileOutputStream(backup).use { retained ->
                try {
                  FileOutputStream(descriptor.fileDescriptor).use { output ->
                    var count = 0L
                    val buffer = ByteArray(64 * 1024)
                    while (count < f.size) {
                        if (cancelled()) throw ProtocolError(409, "Recepción cancelada")
                        val read = input.read(buffer, 0, minOf(buffer.size.toLong(), f.size-count).toInt())
                        if (read < 0) throw ProtocolError(400, "Recepción incompleta; parcial preservado")
                        retained.write(buffer, 0, read)
                        output.write(buffer, 0, read); hash.update(buffer, 0, read); count += read; progress(count)
                    }
                    output.flush(); descriptor.fileDescriptor.sync()
                  }
                } finally {
                    retained.flush(); retained.fd.sync()
                }
                }
            }
            val digest = hash.digest().joinToString("") { "%02x".format(it) }
            if (f.sha256 != null && !digest.equals(f.sha256, true)) throw ProtocolError(422, "El SHA-256 no coincide; parcial preservado")
            if (cancelled()) throw ProtocolError(409, "Recepción cancelada")
            if (resolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null) != 1) throw ProtocolError(500, "No se pudo publicar en la galería")
            journal(f, "recibido", uri, digest, backup.name)
            return uri to digest
        } catch (e: Exception) {
            journal(f, "parcial", uri, null, backup.name)
            throw e
        }
    }
    @Synchronized private fun journal(f: IncomingFile, state: String, uri: Uri, hash: String?, backup: String) {
        val entry = JSONObject().put("nombre", f.name).put("estado", state).put("uri", uri.toString())
            .put("bytes", f.size).put("fecha", System.currentTimeMillis()).put("sha256", hash ?: JSONObject.NULL)
            .put("resguardo", backup)
        FileOutputStream(java.io.File(context.filesDir, "recepciones.jsonl"), true).use {
            it.write((entry.toString()+"\n").toByteArray()); it.flush(); it.fd.sync()
        }
    }
    fun history(): List<String> {
        val file = java.io.File(context.filesDir, "recepciones.jsonl")
        if (!file.exists()) return emptyList()
        return file.useLines { lines -> lines.mapNotNull { runCatching { JSONObject(it) }.getOrNull() }
            .filter { it.optString("estado") != "pendiente" }.map { "${it.optString("estado")}: ${it.optString("nombre")}" }.toList().takeLast(20).reversed() }
    }
}
