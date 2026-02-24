package com.glycemicgpt.mobile.domain.plugin.events

import kotlinx.coroutines.flow.Flow
import kotlin.reflect.KClass

/**
 * Cross-plugin event bus enabling calibration workflows and data sharing
 * between plugins without direct coupling.
 */
interface PluginEventBus {
    /** Publish an event. Plugins must not publish platform-only events. */
    fun publish(event: PluginEvent)

    /** Subscribe to events of a specific type. */
    fun <T : PluginEvent> subscribe(eventType: KClass<T>): Flow<T>
}

/** Convenience: subscribe to events using reified type parameter. */
inline fun <reified T : PluginEvent> PluginEventBus.subscribe(): Flow<T> =
    subscribe(T::class)
