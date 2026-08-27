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

        // Модель не встроена в APK (см. MainActivity — качается при первом
        // запуске), поэтому единственное, что раздувает размер файла — это
        // нативные библиотеки Vosk. Ограничиваем одной ABI: тестовое
        // устройство реальное (arm64), а не эмулятор x86.
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
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
