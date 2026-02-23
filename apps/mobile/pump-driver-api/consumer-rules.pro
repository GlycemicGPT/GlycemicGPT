# Consumer ProGuard rules for :pump-driver-api
# This module exposes interfaces and data classes used by consumer modules.
# No special keep rules needed -- module classes are accessed programmatically,
# not via reflection-based serialization. If Gson/Moshi serialization is added
# later, add appropriate -keep rules for affected classes.
