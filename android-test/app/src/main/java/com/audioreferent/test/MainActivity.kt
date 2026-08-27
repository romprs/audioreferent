package com.audioreferent.test

// Тест офлайн-распознавания русской речи движком Vosk (тем же, что и в
// основном проекте audioreferent для РЭД ОС), встроенным прямо в APK.
// Нужен, потому что на тестовом устройстве нет системного сервиса
// android.speech.SpeechRecognizer — Vosk работает сам по себе, без него.
//
// Модель НЕ зашита в APK (это раздувало файл до 100+ МБ) — при первом
// запуске приложение само скачивает её и распаковывает во внутреннее
// хранилище. Интернет нужен только один раз, дальше распознавание полностью
// офлайн, как и задумано для основного проекта.

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.RecognitionListener
import org.vosk.android.SpeechService
import java.io.BufferedInputStream
import java.io.File
import java.io.FileInputStream
import java.net.URL
import java.util.zip.ZipInputStream

class MainActivity : Activity(), RecognitionListener {

    private lateinit var statusText: TextView
    private lateinit var resultText: TextView
    private lateinit var startButton: Button
    private lateinit var stopButton: Button

    private var model: Model? = null
    private var speechService: SpeechService? = null

    private val wakeWord = "вика"
    private val micRequestCode = 100
    private val sampleRate = 16000.0f
    private val modelUrl = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        resultText = findViewById(R.id.resultText)
        startButton = findViewById(R.id.startButton)
        stopButton = findViewById(R.id.stopButton)
        startButton.isEnabled = false
        stopButton.isEnabled = false

        startButton.setOnClickListener { startListening() }
        stopButton.setOnClickListener { stopListening() }

        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), micRequestCode)
        } else {
            ensureModel()
        }
    }

    private fun ensureModel() {
        val modelDir = File(filesDir, "model-ru")
        if (File(modelDir, "conf/model.conf").exists()) {
            loadModel(modelDir)
            return
        }
        statusText.text = "Скачиваю модель распознавания (~45 МБ, один раз)…"
        Thread {
            try {
                downloadAndUnpackModel(modelDir)
                runOnUiThread { loadModel(modelDir) }
            } catch (e: Exception) {
                runOnUiThread { statusText.text = "Не удалось скачать модель: ${e.message}" }
            }
        }.start()
    }

    private fun downloadAndUnpackModel(targetDir: File) {
        val tmpZip = File(cacheDir, "model.zip")
        URL(modelUrl).openStream().use { input ->
            tmpZip.outputStream().use { output -> input.copyTo(output) }
        }

        runOnUiThread { statusText.text = "Распаковываю модель…" }
        val extractDir = File(cacheDir, "model-extract")
        extractDir.deleteRecursively()
        extractDir.mkdirs()
        ZipInputStream(BufferedInputStream(FileInputStream(tmpZip))).use { zis ->
            var entry = zis.nextEntry
            while (entry != null) {
                val outFile = File(extractDir, entry.name)
                if (entry.isDirectory) {
                    outFile.mkdirs()
                } else {
                    outFile.parentFile?.mkdirs()
                    outFile.outputStream().use { zis.copyTo(it) }
                }
                entry = zis.nextEntry
            }
        }
        tmpZip.delete()

        // Архив распаковывается в подпапку вида vosk-model-small-ru-0.22
        val unzippedModelDir = extractDir.listFiles()?.firstOrNull { it.isDirectory }
            ?: throw IllegalStateException("Не найдена папка модели после распаковки")
        targetDir.deleteRecursively()
        unzippedModelDir.copyRecursively(targetDir, overwrite = true)
        extractDir.deleteRecursively()
    }

    private fun loadModel(modelDir: File) {
        try {
            model = Model(modelDir.absolutePath)
            statusText.text = "Готово. Нажмите «Старт» и произнесите: «Вика, открой браузер»"
            startButton.isEnabled = true
        } catch (e: Exception) {
            statusText.text = "Не удалось загрузить модель: ${e.message}"
        }
    }

    private fun startListening() {
        val currentModel = model ?: return
        if (speechService != null) return
        try {
            resultText.text = "—"
            val recognizer = Recognizer(currentModel, sampleRate)
            val service = SpeechService(recognizer, sampleRate)
            speechService = service
            service.startListening(this)
            statusText.text = "Слушаю…"
            statusText.setTextColor(Color.DKGRAY)
            startButton.isEnabled = false
            stopButton.isEnabled = true
        } catch (e: Exception) {
            statusText.text = "Ошибка запуска: ${e.message}"
        }
    }

    private fun stopListening() {
        speechService?.stop()
        speechService?.shutdown()
        listeningFinished()
    }

    private fun listeningFinished() {
        speechService = null
        startButton.isEnabled = true
        stopButton.isEnabled = false
    }

    private fun extractText(hypothesis: String?, key: String): String {
        if (hypothesis.isNullOrEmpty()) return ""
        return try {
            JSONObject(hypothesis).optString(key, "")
        } catch (e: Exception) {
            ""
        }
    }

    // Финальный результат (граница фразы по паузе) — единственное место, где
    // проверяем активационное слово и пытаемся выполнить команду. Партиалы
    // используются только для отображения текста вживую, без действий —
    // иначе одна и та же команда сработала бы по нескольку раз за фразу.
    private fun handleFinalUtterance(text: String) {
        if (text.isEmpty()) return
        resultText.text = text

        if (!text.lowercase().contains(wakeWord)) {
            statusText.text = "Слушаю…"
            statusText.setTextColor(Color.DKGRAY)
            return
        }

        val match = CommandRegistry.match(text)
        if (match == null) {
            statusText.text = "Ключевое слово услышано, но команда не распознана"
            statusText.setTextColor(Color.parseColor("#f9a825"))
            return
        }

        statusText.text = "Выполняю: ${CommandRegistry.describe(match)}"
        statusText.setTextColor(Color.parseColor("#2e7d32"))
        try {
            Actions.execute(this, match)
        } catch (e: Exception) {
            statusText.text = "Ошибка выполнения: ${e.message}"
            statusText.setTextColor(Color.RED)
        }
    }

    // Vosk слушает непрерывно: onResult приходит на каждой границе фразы
    // (по паузе), сервис не останавливается сам — это удобно для проверки
    // нескольких команд подряд без повторного нажатия "Старт".
    override fun onPartialResult(hypothesis: String?) {
        val text = extractText(hypothesis, "partial")
        if (text.isNotEmpty()) resultText.text = text
    }

    override fun onResult(hypothesis: String?) {
        handleFinalUtterance(extractText(hypothesis, "text"))
    }

    override fun onFinalResult(hypothesis: String?) {
        handleFinalUtterance(extractText(hypothesis, "text"))
        listeningFinished()
    }

    override fun onError(exception: Exception?) {
        statusText.text = "Ошибка распознавания: ${exception?.message}"
        statusText.setTextColor(Color.RED)
        listeningFinished()
    }

    override fun onTimeout() {
        statusText.text = "Тишина, таймаут"
        listeningFinished()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == micRequestCode) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                ensureModel()
            } else {
                statusText.text = "Нет разрешения на использование микрофона"
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        speechService?.stop()
        speechService?.shutdown()
    }
}
