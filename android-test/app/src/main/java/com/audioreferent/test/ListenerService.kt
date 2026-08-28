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
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.RecognitionListener
import org.vosk.android.SpeechService
import java.io.BufferedInputStream
import java.io.File
import java.io.FileInputStream
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.zip.ZipInputStream

class ListenerService : Service(), RecognitionListener {

    private var model: Model? = null
    private var speechService: SpeechService? = null

    private val sampleRate = 16000.0f
    private val modelUrl = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"

    private val channelId = "audioreferent_listener"
    private val notificationId = 1

    // "Пульс": диагностика, живёт ли вообще процесс, когда окно закрыто —
    // независимо от того, распознаёт ли что-то Vosk. Если время в
    // уведомлении не двигается после закрытия окна, значит систма
    // останавливает процесс целиком, а не просто мешает микрофону.
    private var lastStatusText: String = "Запуск…"
    private val heartbeatHandler = Handler(Looper.getMainLooper())
    private val heartbeatIntervalMs = 10_000L
    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    private val heartbeatRunnable = object : Runnable {
        override fun run() {
            updateNotification(lastStatusText, null, includeHeartbeat = true)
            heartbeatHandler.postDelayed(this, heartbeatIntervalMs)
        }
    }

    override fun onCreate() {
        super.onCreate()
        isRunning = true
        ServiceState.setShouldRun(this, true)
        ServiceWatchdog.scheduleNextCheck(this)
        createNotificationChannel()
        startForeground(notificationId, buildNotification("Запуск…", heartbeat = true))
        heartbeatHandler.postDelayed(heartbeatRunnable, heartbeatIntervalMs)
        ensureModel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            ServiceState.setShouldRun(this, false)
            ServiceWatchdog.cancel(this)
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    // Штатное поведение Android — сервис НЕ должен останавливаться при
    // закрытии/свайпе приложения из списка задач (см. android:stopWithTask
    // в манифесте). Если производитель всё равно убивает процесс на этом
    // этапе, дело не в этом коллбэке, а в агрессивном энергосбережении
    // прошивки — см. подсказку в MainActivity про автозапуск/батарею.
    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
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

    // openIntent — резервный способ довести до конца действия, которые
    // открывают что-то на экране (браузер/приложение): прямой запуск из
    // фонового сервиса Android может молча заблокировать (background
    // activity launch restrictions), а нажатие на уведомление — это уже
    // настоящее действие пользователя, которое такими ограничениями не
    // блокируется никогда.
    private fun buildNotification(text: String, openIntent: Intent? = null, heartbeat: Boolean = false): Notification {
        val stopIntent = Intent(this, ListenerService::class.java).setAction(ACTION_STOP)
        val stopPendingIntent = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val fullText = if (heartbeat) "$text · пульс ${timeFormat.format(Date())}" else text
        val builder = Notification.Builder(this, channelId)
            .setContentTitle("Audioreferent — слушаю «${CommandRegistry.getWakeWord(this)}»")
            .setContentText(fullText)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .addAction(0, "Стоп", stopPendingIntent)

        if (openIntent != null) {
            val openPendingIntent = PendingIntent.getActivity(
                this, openIntent.hashCode(), openIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            builder.setContentIntent(openPendingIntent)
            builder.addAction(0, "Открыть", openPendingIntent)
        }

        return builder.build()
    }

    private fun updateNotification(text: String, openIntent: Intent? = null, includeHeartbeat: Boolean = false) {
        lastStatusText = text
        getSystemService(NotificationManager::class.java)
            .notify(notificationId, buildNotification(text, openIntent, heartbeat = includeHeartbeat))
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

    // Реагируем только на финальный результат (граница фразы по паузе),
    // чтобы команда не срабатывала по нескольку раз на одной фразе.
    // Партиалы (см. onPartialResult) только показываются в окне, если
    // оно сейчас открыто — на выполнение команд не влияют.
    private fun handleFinalUtterance(text: String) {
        if (text.isEmpty()) return

        val wakeWord = CommandRegistry.getWakeWord(this)
        if (!text.lowercase().contains(wakeWord)) {
            RecognitionState.setLast(this, text, "Слушаю…")
            updateNotification("Слушаю…")
            return
        }

        val match = CommandRegistry.match(this, text)
        if (match == null) {
            val status = "Услышала «$wakeWord», но не поняла команду"
            RecognitionState.setLast(this, text, status)
            updateNotification("$status: «$text»")
            return
        }

        try {
            val intent = Actions.buildActivityIntent(this, match)
            if (intent == null) {
                Actions.executeNonActivity(this, match)
                val status = "Выполняю: ${CommandRegistry.describe(match)}"
                RecognitionState.setLast(this, text, status)
                updateNotification(status)
            } else {
                // Пробуем открыть сразу — сработает, если фоновые
                // ограничения Android это позволяют в данный момент.
                // Кнопка/тап на уведомлении — гарантированный запасной путь
                // (см. buildNotification), поэтому не проверяем результат.
                try {
                    startActivity(intent)
                } catch (e: Exception) {
                    // не критично — есть кнопка на уведомлении
                }
                val status = "${CommandRegistry.describe(match)} — если не открылось само, нажмите на уведомление"
                RecognitionState.setLast(this, text, status)
                updateNotification(status, intent)
            }
        } catch (e: Exception) {
            val status = "Ошибка выполнения: ${e.message}"
            RecognitionState.setLast(this, text, status)
            updateNotification(status)
        }
    }

    override fun onPartialResult(hypothesis: String?) {
        val text = extractText(hypothesis, "partial")
        if (text.isNotEmpty()) {
            RecognitionState.setLast(this, text, "Слушаю…")
        }
    }

    override fun onResult(hypothesis: String?) {
        handleFinalUtterance(extractText(hypothesis, "text"))
    }

    override fun onFinalResult(hypothesis: String?) {
        handleFinalUtterance(extractText(hypothesis, "text"))
    }

    override fun onError(exception: Exception?) {
        RecognitionState.setLast(this, "", "Ошибка распознавания, перезапускаю: ${exception?.message}")
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
        isRunning = false
        heartbeatHandler.removeCallbacks(heartbeatRunnable)
        speechService?.stop()
        speechService?.shutdown()
        super.onDestroy()
    }

    companion object {
        const val ACTION_STOP = "com.audioreferent.test.ACTION_STOP"

        // Живёт только в рамках текущего процесса: если процесс убили,
        // при следующем запуске (в т.ч. новым процессом ради watchdog-
        // получателя) значение по умолчанию false — то есть "не запущен",
        // и это ровно то, что нужно определить WatchdogReceiver.
        @Volatile
        var isRunning: Boolean = false
    }
}
