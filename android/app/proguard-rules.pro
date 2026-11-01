# kotlinx.serialization: keep generated serializers of the backend JSON models (org.reelcheck.core).
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class org.reelcheck.core.** {
    *** Companion;
}
-keepclasseswithmembers class org.reelcheck.core.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class org.reelcheck.core.**$$serializer { *; }
# OkHttp ships its own rules; silence optional platform warnings.
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
