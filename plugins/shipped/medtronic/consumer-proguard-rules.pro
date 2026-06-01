# medtronic-pump-driver consumer ProGuard rules
# Applied automatically to consuming modules (e.g., :app) during R8/ProGuard.

# BouncyCastle AES-CMAC: keep only the classes used by the vendored SAKE crypto
# (org.openminimed.sake.crypto.AesCmac).
-keep class org.bouncycastle.crypto.macs.CMac { *; }
-keep class org.bouncycastle.crypto.engines.AESEngine { *; }
-keep class org.bouncycastle.crypto.params.KeyParameter { *; }
-dontwarn org.bouncycastle.**
