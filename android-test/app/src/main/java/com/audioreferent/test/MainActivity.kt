package com.audioreferent.test

// Диагностическое приложение: проверяет, справляется ли системный сервис
// распознавания речи Android (android.speech.SpeechRecognizer) с русской
// речью, и повторяет ту же идею нечёткого текстового срабатывания на
// активационное слово "вика", что и в основном проекте audioreferent для
// РЭД ОС (там это Vosk + сравнение по Левенштейну, здесь — упрощённая
// проверка через substring, этого достаточно для быстрого теста движка).

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.widget.Button
import android.widget.TextView

class MainActivity : Activity() {

    private var speechRecognizer: SpeechRecognizer? = null
    private lateinit var statusText: TextView
    private lateinit var resultText: TextView
    private lateinit var startButton: Button
    private lateinit var stopButton: Button

    private val wakeWord = "вика"
    private val micRequestCode = 100

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        resultText = findViewById(R.id.resultText)
        startButton = findViewById(R.id.startButton)
        stopButton = findViewById(R.id.stopButton)
        stopButton.isEnabled = false

        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            statusText.text = "На этом устройстве нет доступного сервиса распознавания речи"
            startButton.isEnabled = false
            return
        }

        val recognizer = SpeechRecognizer.createSpeechRecognizer(this)
        recognizer.setRecognitionListener(buildListener())
        speechRecognizer = recognizer

        startButton.setOnClickListener { onStartClicked() }
        stopButton.setOnClickListener { stopListening() }
    }

    private fun buildListener(): RecognitionListener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {
            statusText.text = "Слушаю…"
            statusText.setTextColor(Color.DKGRAY)
        }

        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {}

        override fun onError(error: Int) {
            statusText.text = "Ошибка: ${describeError(error)}"
            statusText.setTextColor(Color.RED)
            listeningFinished()
        }

        override fun onResults(results: Bundle?) {
            val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
            showResult(text)
            listeningFinished()
        }

        override fun onPartialResults(partialResults: Bundle?) {
            val text = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
            if (text.isNotEmpty()) showResult(text)
        }

        override fun onEvent(eventType: Int, params: Bundle?) {}
    }

    private fun showResult(text: String) {
        resultText.text = text.ifEmpty { "—" }
        val wakeWordFound = text.lowercase().contains(wakeWord)
        statusText.text = if (wakeWordFound) "Ключевое слово «$wakeWord» обнаружено!" else "Готово"
        statusText.setTextColor(if (wakeWordFound) Color.parseColor("#2e7d32") else Color.DKGRAY)
    }

    private fun listeningFinished() {
        startButton.isEnabled = true
        stopButton.isEnabled = false
    }

    private fun onStartClicked() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), micRequestCode)
            return
        }
        startListening()
    }

    private fun startListening() {
        resultText.text = "—"
        statusText.text = "Запуск распознавания…"
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        }
        speechRecognizer?.startListening(intent)
        startButton.isEnabled = false
        stopButton.isEnabled = true
    }

    private fun stopListening() {
        speechRecognizer?.stopListening()
        listeningFinished()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == micRequestCode) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                startListening()
            } else {
                statusText.text = "Нет разрешения на использование микрофона"
            }
        }
    }

    private fun describeError(error: Int): String = when (error) {
        SpeechRecognizer.ERROR_NETWORK -> "нет сети"
        SpeechRecognizer.ERROR_NO_MATCH -> "речь не распознана"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "тишина, таймаут"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "распознаватель занят"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "нет разрешений"
        SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED -> "язык не поддерживается"
        SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE -> "язык недоступен"
        else -> "код $error"
    }

    override fun onDestroy() {
        super.onDestroy()
        speechRecognizer?.destroy()
    }
}
