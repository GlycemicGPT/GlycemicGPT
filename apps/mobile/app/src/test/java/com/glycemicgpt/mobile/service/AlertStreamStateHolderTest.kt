package com.glycemicgpt.mobile.service

import org.junit.Assert.assertEquals
import org.junit.Test

class AlertStreamStateHolderTest {

    @Test
    fun `initial state is DISCONNECTED`() {
        assertEquals(AlertStreamState.DISCONNECTED, AlertStreamStateHolder().state.value)
    }

    @Test
    fun `stream opening flips to CONNECTED`() {
        val holder = AlertStreamStateHolder()

        holder.onStreamOpened()

        assertEquals(AlertStreamState.CONNECTED, holder.state.value)
    }

    @Test
    fun `stream failure flips to RECONNECTING`() {
        val holder = AlertStreamStateHolder()
        holder.onStreamOpened()

        holder.onStreamRetrying()

        assertEquals(AlertStreamState.RECONNECTING, holder.state.value)
    }

    @Test
    fun `stream stop flips to DISCONNECTED`() {
        val holder = AlertStreamStateHolder()
        holder.onStreamOpened()

        holder.onStreamStopped()

        assertEquals(AlertStreamState.DISCONNECTED, holder.state.value)
    }

    @Test
    fun `recovery after retrying returns to CONNECTED`() {
        val holder = AlertStreamStateHolder()

        holder.onStreamOpened()
        holder.onStreamRetrying()
        holder.onStreamOpened()

        assertEquals(AlertStreamState.CONNECTED, holder.state.value)
    }
}
