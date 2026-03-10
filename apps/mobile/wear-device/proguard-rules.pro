# wear-device ProGuard rules
# Keep WearableListenerService for DataLayer callbacks
-keep class com.glycemicgpt.weardevice.data.GlycemicDataListenerService { *; }

# Keep complication data sources (instantiated by system)
-keep class com.glycemicgpt.weardevice.complications.** { *; }

# Keep Hilt-generated Application class
-keep class com.glycemicgpt.weardevice.GlycemicWearDeviceApp { *; }
