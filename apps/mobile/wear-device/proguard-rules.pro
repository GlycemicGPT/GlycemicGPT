# wear-device ProGuard rules
# Keep WearableListenerService for DataLayer callbacks
-keep class com.glycemicgpt.weardevice.data.GlycemicDataListenerService { *; }

# Keep complication data sources (instantiated by system)
-keep class com.glycemicgpt.weardevice.complications.** { *; }

# Keep Hilt-generated Application class
-keep class com.glycemicgpt.weardevice.GlycemicWearDeviceApp { *; }

# Keep Watch Face Push receive service (instantiated by system)
-keep class com.glycemicgpt.weardevice.push.WatchFaceReceiveService { *; }

# DWF Validator -- AAR ships no consumer ProGuard rules; keep public API + factory
-keep class com.google.android.wearable.watchface.validator.client.** { *; }
