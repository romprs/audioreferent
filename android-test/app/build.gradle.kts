plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.audioreferent.test"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.audioreferent.test"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1"

        // Ограничиваем ABI, чтобы не тащить в APK нативные библиотеки Vosk
        // под x86/x86_64 — тестовое устройство реальное, а не эмулятор.
        ndk {
            abiFilters += listOf("armeabi-v7a", "arm64-v8a")
        }
    }

    androidResources {
        // Модель Vosk лежит в assets несжатой — не даём AAPT пытаться её сжать
        noCompress += listOf("mdl", "fst", "ext", "int", "mat", "ie", "dubm", "conf")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Тот же движок, что и в основном проекте audioreferent для РЭД ОС —
    // офлайн, не зависит от системного сервиса распознавания речи.
    implementation("com.alphacephei:vosk-android:0.3.47")
}
