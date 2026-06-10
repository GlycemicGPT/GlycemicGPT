package com.glycemicgpt.mobile.presentation.pairing

import android.content.Context
import com.glycemicgpt.mobile.data.local.PumpCredentialStore
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredPump
import com.glycemicgpt.mobile.domain.plugin.PairingFault
import com.glycemicgpt.mobile.domain.plugin.PairingProfile
import com.glycemicgpt.mobile.domain.plugin.PairingStyle
import com.glycemicgpt.mobile.domain.pump.PumpConnectionManager
import com.glycemicgpt.mobile.domain.pump.PumpScanner
import com.glycemicgpt.mobile.service.PumpConnectionService
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkObject
import io.mockk.unmockkAll
import io.mockk.verify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PairingViewModelTest {

    private val testDispatcher = UnconfinedTestDispatcher()

    private val connectionStateFlow = MutableStateFlow(ConnectionState.DISCONNECTED)
    private val pairingProfileFlow = MutableStateFlow(PairingProfile())
    private val pairingFaultFlow = MutableStateFlow<PairingFault?>(null)

    private val scanner: PumpScanner = mockk(relaxed = true)
    private val connectionManager: PumpConnectionManager = mockk(relaxed = true) {
        every { connectionState } returns connectionStateFlow
        every { pairingProfile } returns pairingProfileFlow
        every { pairingFault } returns pairingFaultFlow
    }
    private val credentialStore: PumpCredentialStore = mockk(relaxed = true)
    private val context: Context = mockk(relaxed = true)

    private fun viewModel() =
        PairingViewModel(scanner, connectionManager, credentialStore, context)

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        // PumpConnectionService.start/stop construct Android Intents; stub them out.
        mockkObject(PumpConnectionService.Companion)
        every { PumpConnectionService.start(any()) } returns Unit
        every { PumpConnectionService.stop(any()) } returns Unit
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        unmockkAll()
    }

    @Test
    fun `exposes the active plugin pairing profile`() {
        pairingProfileFlow.value =
            PairingProfile(PairingStyle.ADVERTISE_AND_WAIT, "Mobile 000001")

        val vm = viewModel()

        assertEquals(PairingStyle.ADVERTISE_AND_WAIT, vm.pairingProfile.value.style)
        assertEquals("Mobile 000001", vm.pairingProfile.value.advertisedName)
    }

    @Test
    fun `exposes the active plugin pairing fault`() {
        val vm = viewModel()
        assertEquals(null, vm.pairingFault.value)

        pairingFaultFlow.value = PairingFault.PERIPHERAL_UNSUPPORTED

        assertEquals(PairingFault.PERIPHERAL_UNSUPPORTED, vm.pairingFault.value)
    }

    @Test
    fun `startAdvertising advertises without starting the foreground service`() {
        // A flow that never completes keeps advertising "live" so isAdvertising stays true. The service
        // must NOT start on the tap -- only once a session forms (a start-then-stop on instant-fail
        // crashes with ForegroundServiceDidNotStartInTime).
        every { scanner.scan() } returns MutableSharedFlow<DiscoveredPump>()

        val vm = viewModel()
        vm.startAdvertising()

        assertTrue(vm.isAdvertising.value)
        verify { scanner.scan() }
        verify(exactly = 0) { PumpConnectionService.start(any()) }
    }

    @Test
    fun `advertising that ends without a session never touches the service`() {
        // A device that can't advertise closes the scan flow immediately (PERIPHERAL_UNSUPPORTED).
        // Because the service was never started, there is nothing to stop -- and crucially no
        // start-then-stop race.
        every { scanner.scan() } returns emptyFlow()
        connectionStateFlow.value = ConnectionState.DISCONNECTED

        val vm = viewModel()
        vm.startAdvertising()

        assertFalse(vm.isAdvertising.value)
        verify(exactly = 0) { PumpConnectionService.start(any()) }
        verify(exactly = 0) { PumpConnectionService.stop(any()) }
    }

    @Test
    fun `service starts once a pump session forms`() {
        every { scanner.scan() } returns MutableSharedFlow<DiscoveredPump>()

        val vm = viewModel()
        vm.startAdvertising()
        verify(exactly = 0) { PumpConnectionService.start(any()) }

        // The pump connected and the handshake is running -- polling must be ready and survive
        // navigation, so the service starts now.
        connectionStateFlow.value = ConnectionState.AUTHENTICATING

        verify { PumpConnectionService.start(any()) }
    }

    @Test
    fun `stopAdvertising cancels advertising without touching the service`() {
        every { scanner.scan() } returns MutableSharedFlow<DiscoveredPump>()
        connectionStateFlow.value = ConnectionState.DISCONNECTED

        val vm = viewModel()
        vm.startAdvertising()
        vm.stopAdvertising()

        assertFalse(vm.isAdvertising.value)
        verify(exactly = 0) { PumpConnectionService.stop(any()) }
    }
}
