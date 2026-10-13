package com.luciesinreglas.recibir

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.provider.MediaStore
import android.net.Uri
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayInputStream
import java.security.MessageDigest
import java.util.UUID

/** Solo crea medios sintéticos propios en el dispositivo de pruebas. No borra. */
@RunWith(AndroidJUnit4::class)
class MediaSinkAndroidTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val data get() = android.util.Base64.decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=",0)
    private fun file(bytes:ByteArray=data, hash:String?=digest(bytes)) = IncomingFile(UUID.randomUUID().toString(),"fixture-${UUID.randomUUID()}.png",bytes.size.toLong(),"image/png",hash)
    private fun digest(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
    private fun pending(uri:Uri)=context.contentResolver.query(uri,arrayOf(MediaStore.MediaColumns.IS_PENDING),null,null,null)!!.use{assertTrue(it.moveToFirst());it.getInt(0)}
    private fun retained(name:String):ByteArray {
        val row=java.io.File(context.filesDir,"recepciones.jsonl").readLines().map{JSONObject(it)}.last{it.getString("nombre")==name}
        return java.io.File(context.filesDir,"resguardos/${row.getString("resguardo")}").readBytes()
    }
    private fun journalUri(name:String):Uri {
        val row=java.io.File(context.filesDir,"recepciones.jsonl").readLines().map{JSONObject(it)}.last{it.getString("nombre")==name}
        assertEquals("parcial",row.getString("estado"))
        return Uri.parse(row.getString("uri"))
    }
    @Test fun publishOnlyAfterValidHashAndPreserveHomonyms() {
        val sink=MediaSink(context);val f=file()
        val first=sink.receive(f,ByteArrayInputStream(data),{false},{})
        assertEquals(0,pending(first.first));assertEquals(digest(data),first.second)
        assertArrayEquals(data,context.contentResolver.openInputStream(first.first)!!.use{it.readBytes()})
        assertArrayEquals(data,retained(f.name))
        val second=sink.receive(f,ByteArrayInputStream(data),{false},{})
        assertNotEquals(first.first,second.first)
        assertArrayEquals(data,context.contentResolver.openInputStream(first.first)!!.use{it.readBytes()})
    }
    @Test fun invalidHashKeepsPartialHidden() {
        val sink=MediaSink(context);val f=file(hash="0".repeat(64))
        try{sink.receive(f,ByteArrayInputStream(data),{false},{});fail("Hash inválido aceptado")}
        catch(e:ProtocolError){assertEquals(422,e.status)}
        val uri=journalUri(f.name);assertEquals(1,pending(uri))
        assertArrayEquals(data,context.contentResolver.openInputStream(uri)!!.use{it.readBytes()})
        assertArrayEquals(data,retained(f.name))
    }
    @Test fun cancellationPreservesWrittenBytesWithoutPublishing() {
        val bytes=ByteArray(128*1024){it.toByte()};val f=file(bytes);var cancelled=false
        try{MediaSink(context).receive(f,ByteArrayInputStream(bytes),{cancelled},{cancelled=true});fail("Cancelación ignorada")}
        catch(e:ProtocolError){assertEquals(409,e.status)}
        val uri=journalUri(f.name);assertEquals(1,pending(uri))
        assertArrayEquals(bytes.copyOfRange(0,64*1024),context.contentResolver.openInputStream(uri)!!.use{it.readBytes()})
        assertArrayEquals(bytes.copyOfRange(0,64*1024),retained(f.name))
    }
}
