package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.domain.plugin.events.PluginEvent
import com.glycemicgpt.mobile.domain.plugin.events.PluginEventBus
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.filterIsInstance
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.reflect.KClass

/**
 * Platform-owned implementation of [PluginEventBus].
 *
 * Validates that plugins do not publish platform-only events.
 * Platform code uses [publishPlatform] to bypass this check.
 */
@Singleton
class PluginEventBusImpl @Inject constructor() : PluginEventBus {

    private val _events = MutableSharedFlow<PluginEvent>(
        extraBufferCapacity = 256,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )

    val events = _events.asSharedFlow()

    override fun publish(event: PluginEvent) {
        if (event::class in PluginEvent.PLATFORM_ONLY) {
            Timber.w(
                "Plugin %s attempted to publish platform-only event %s -- blocked",
                event.pluginId,
                event.javaClass.simpleName,
            )
            return
        }
        if (!_events.tryEmit(event)) {
            Timber.w("Event bus buffer full, dropping event: %s", event.javaClass.simpleName)
        }
    }

    /**
     * Publish a platform-only event. Restricted to the :app module via
     * `internal` visibility -- plugins (in separate Gradle modules) cannot call this.
     */
    internal fun publishPlatform(event: PluginEvent) {
        if (!_events.tryEmit(event)) {
            Timber.w("Event bus buffer full, dropping platform event: %s", event.javaClass.simpleName)
        }
    }

    @Suppress("UNCHECKED_CAST")
    override fun <T : PluginEvent> subscribe(eventType: KClass<T>): Flow<T> =
        events.filterIsInstance(eventType)
}
