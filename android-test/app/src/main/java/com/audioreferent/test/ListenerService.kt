package com.audioreferent.test

// Вся логика распознавания живёт здесь, а не в Activity — это то, что
// делает прослушивание фоновым: сервис продолжает работать (и, если
// нужно, выполнять команды), даже когда приложение закрыто. Статус виден
// через постоянное уведомление (обязательное требование Android для
// foreground-сервисов), там же кнопка "Стоп".

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
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

class ListenerService : Service(), RecognitionListener {

    private var model: Model? = null
    private var speechService: SpeechService? = null

    private val sampleRate = 16000.0f
    private val modelUrl = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"

    private val channelId = "audioreferent_listener"
    private val notificationId = 1

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(notificationId, buildNotification("Запуск…"))
        ensureModel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId, "Голосовой помощник", NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        val stopIntent = Intent(this, ListenerService::class.java).setAction(ACTION_STOP)
        val stopPendingIntent = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return Notification.Builder(this, channelId)
            .setContentTitle("Audioreferent — слушаю «${CommandRegistry.getWakeWord(this)}»")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .addAction(0, "Стоп", stopPendingIntent)
            .build()
    }

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java).notify(notificationId, buildNotification(text))
    }

    private fun ensureModel() {
        val modelDir = File(filesDir, "model-ru")
        if (File(modelDir, "conf/model.conf").exists()) {
            loadModel(modelDir)
            return
        }
        updateNotification("Скачиваю модель распознавания (~45 МБ, один раз)…")
        Thread {
            try {
                downloadAndUnpackModel(modelDir)
                loadModel(modelDir)
            } catch (e: Exception) {
                updateNotification("Ошибка загрузки модели: ${e.message}")
            }
        }.start()
    }

    private fun downloadAndUnpackModel(targetDir: File) {
        val tmpZip = File(cacheDir, "model.zip")
        URL(modelUrl).openStream().use { input ->
            tmpZip.outputStream().use { output -> input.copyTo(output) }
        }

        updateNotification("Распаковываю модель…")
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

        val unzippedModelDir = extractDir.listFiles()?.firstOrNull { it.isDirectory }
            ?: throw IllegalStateException("Не найдена папка модели после распаковки")
        targetDir.deleteRecursively()
        unzippedModelDir.copyRecursively(targetDir, overwrite = true)
        extractDir.deleteRecursively()
    }

    private fun loadModel(modelDir: File) {
        try {
            model = Model(modelDir.absolutePath)
            startListening()
        } catch (e: Exception) {
            updateNotification("Не удалось загрузить модель: ${e.message}")
        }
    }

    private fun startListening() {
        val currentModel = model ?: return
        if (speechService != null) return
        try {
            val recognizer = Recognizer(currentModel, sampleRate)
            val service = SpeechService(recognizer, sampleRate)
            speechService = service
            service.startListening(this)
            updateNotification("Слушаю…")
        } catch (e: Exception) {
            updateNotification("Ошибка запуска распознавания: ${e.message}")
        }
    }

    private fun restartListening() {
        speechService?.stop()
        speechService?.shutdown()
        speechService = null
        startListening()
    }

    private fun extractText(hypothesis: String?, key: String): String {
        if (hypothesis.isNullOrEmpty()) return ""
        return try {
            JSONObject(hypothesis).optString(key, "")
        } catch (e: Exception) {
            ""
        }
    }

    // Как и в MainActivity раньше: реагируем только на финальный результат
    // (граница фразы по паузе), чтобы команда не срабатывала по нескольку
    // раз на одной фразе. Партиалы для фонового режима не нужны — их не с
    // чем показывать без экрана.
    private fun handleFinalUtterance(text: String) {
        if (text.isEmpty()) return

        val wakeWord = CommandRegistry.getWakeWord(this)
        if (!text.lowercase().contains(wakeWord)) {
            updateNotification("Слушаю…")
            return
        }

        val match = CommandRegistry.match(this, text)
        if (match == null) {
            updateNotification("Услышала «$wakeWord», но не поняла команду: «$text»")
            return
        }

        updateNotification("Выполняю: ${CommandRegistry.describe(match)}")
        try {
            Actions.execute(this, match)
        } catch (e: Exception) {
            updateNotification("Ошибка выполнения: ${e.message}")
        }
    }

    override fun onPartialResult(hypothesis: String?) {}

    override fun onResult(hypothesis: String?) {
        handleFinalUtterance(extractText(hypothesis, "text"))
    }

    override fun onFinalResult(hypothesis: String?) {
        handleFinalUtterance(extractText(hypothesis, "text"))
    }

    override fun onError(exception: Exception?) {
        updateNotification("Ошибка распознавания, перезапускаю: ${exception?.message}")
        restartListening()
    }

    override fun onTimeout() {
        // SpeechService останавливается сам после долгой тишины — просто
        // запускаем заново, чтобы прослушивание было действительно
        // непрерывным, а не разовым.
        restartListening()
    }

    override fun onDestroy() {
        speechService?.stop()
        speechService?.shutdown()
        super.onDestroy()
    }

    companion object {
        const val ACTION_STOP = "com.audioreferent.test.ACTION_STOP"
    }
}
