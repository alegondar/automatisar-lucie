package com.luciesinreglas.recibir

import org.junit.Assert.*
import org.junit.Test

class TransferStateTest {
    private val video = IncomingFile("video1","clip.mp4",20,"video/mp4","a".repeat(64))
    @Test fun acceptsOnlyOwnerAndFreesAfterLastFile() {
        val state=TransferState();val s=state.offer("192.168.1.2","PC",listOf(video))
        assertFails(403){state.beginFile(s.id,s.remote,video.id,s.tokens.getValue(video.id))}
        state.decide(true)
        assertFails(403){state.beginFile(s.id,"192.168.1.3",video.id,s.tokens.getValue(video.id))}
        state.beginFile(s.id,s.remote,video.id,s.tokens.getValue(video.id))
        assertFails(409){state.beginFile(s.id,s.remote,video.id,s.tokens.getValue(video.id))}
        state.complete(s,video.id)
        assertNull(state.session)
        assertNotNull(state.offer(s.remote,"PC",listOf(video)))
    }
    @Test fun cancelDoesNotAffectAnotherOwnerAndNextTransferWorks() {
        val state=TransferState();val s=state.offer("192.168.1.2","PC",listOf(video))
        assertFails(409){state.offer("192.168.1.3","otro",listOf(video))}
        assertFails(403){state.cancelOwned("ajena",s.remote)}
        assertSame(s,state.session)
        state.cancelOwned(s.id,s.remote)
        assertTrue(s.cancelled)
        assertEquals(0L,s.decision.count)
        val next=state.offer(s.remote,"PC",listOf(video))
        state.cancelOwned(s.id,s.remote)
        assertSame(next,state.session)
    }
    @Test fun rejectsEscapesNegativeSizesAndInvalidHash() {
        for (bad in listOf(video.copy(name="../clip.mp4"),video.copy(name="a\\clip.mp4"),video.copy(size=-1),video.copy(sha256="incorrecto"))) {
            assertFails(400){TransferState().offer("192.168.1.2","PC",listOf(bad))}
        }
    }
    @Test fun localRejectReleasesPendingReservation() {
        val state=TransferState();val s=state.offer("192.168.1.2","PC",listOf(video))
        state.decide(false)
        assertNull(state.session);assertTrue(s.cancelled);assertEquals(0L,s.decision.count)
    }
    private fun assertFails(code:Int, action:()->Unit) {
        try {action();fail("Se esperaba rechazo HTTP $code")}
        catch(e:ProtocolError){assertEquals(code,e.status)}
    }
}
