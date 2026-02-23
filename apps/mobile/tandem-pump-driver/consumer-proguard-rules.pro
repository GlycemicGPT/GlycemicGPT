# tandem-pump-driver consumer ProGuard rules
# Applied automatically to consuming modules (e.g., :app) during R8/ProGuard.

# BouncyCastle EC-JPAKE: keep only the classes actually used by EcJpake.kt.
-keep class org.bouncycastle.jce.ECNamedCurveTable { *; }
-keep class org.bouncycastle.jce.spec.ECParameterSpec { *; }
-keep class org.bouncycastle.util.BigIntegers { *; }
# ECPoint and BigIntegers pull in internal helpers via reflection
-keep class org.bouncycastle.math.ec.** { *; }
-dontwarn org.bouncycastle.**
