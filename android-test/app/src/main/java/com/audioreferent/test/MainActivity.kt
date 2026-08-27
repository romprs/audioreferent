package com.audioreferent.test

// Тест офлайн-распознавания русской речи движком Vosk (тем же, что и в
// основном проекте audioreferent для РЭД ОС), встроенным прямо в APK.
// Нужен, потому что на тестовом устройстве нет системного сервиса
// android.speech.SpeechRecognizer — Vosk работает сам по себе, без него.

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
import org.vosk.android.StorageService

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
            unpackModel()
        }
    }

    private fun unpackModel() {
        statusText.text = "Распаковываю модель распознавания…"
        StorageService.unpack(this, "model-ru", "model",
            { unpackedModel ->
                model = unpackedModel
                statusText.text = "Готово. Нажмите «Старт» и произнесите: «Вика, открой браузер»"
                startButton.isEnabled = true
            },
            { exception ->
                statusText.text = "Не удалось распаковать модель: ${exception.message}"
            }
        )
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

    private fun showText(text: String) {
        if (text.isEmpty()) return
        resultText.text = text
        val wakeWordFound = text.lowercase().contains(wakeWord)
        statusText.text = if (wakeWordFound) "Ключевое слово «$wakeWord» обнаружено!" else "Слушаю…"
        statusText.setTextColor(if (wakeWordFound) Color.parseColor("#2e7d32") else Color.DKGRAY)
    }

    // Vosk слушает непрерывно: onResult приходит на каждой границе фразы
    // (по паузе), сервис не останавливается сам — это удобно для проверки
    // нескольких команд подряд без повторного нажатия "Старт".
    override fun onPartialResult(hypothesis: String?) {
        showText(extractText(hypothesis, "partial"))
    }

    override fun onResult(hypothesis: String?) {
        showText(extractText(hypothesis, "text"))
    }

    override fun onFinalResult(hypothesis: String?) {
        showText(extractText(hypothesis, "text"))
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
                unpackModel()
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
