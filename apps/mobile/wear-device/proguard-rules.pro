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

# TwelveMonkeys ImageIO (transitive via webpdecoder)
# These reference javax.imageio SPI classes not available in Android SDK.
-dontwarn javax.imageio.**
-dontwarn com.twelvemonkeys.imageio.**
-dontwarn com.twelvemonkeys.common.**

# AutoValue annotation processor references (javax.lang.model is from tools.jar)
-dontwarn javax.lang.model.**
-dontwarn javax.annotation.processing.**

# DOM/XML/XPath references from transitive dependencies
-dontwarn org.w3c.dom.DOMImplementationSourceList
-dontwarn org.xml.sax.driver
-dontwarn org.eclipse.wst.**
-dontwarn org.apache.xerces.**
