package com.audioreferent.test

// Экран запускает/останавливает фоновый сервис (ListenerService) и
// содержит настройки: активационное слово и список команд (JSON).
// Правки сохраняются в SharedPreferences и подхватываются сервисом на
// лету — перезапускать сервис не нужно.

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.method.ScrollingMovementMethod
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {

    private lateinit var statusText: TextView
    private lateinit var resultText: TextView
    private lateinit var startButton: Button
    private lateinit var stopButton: Button
    private lateinit var wakeWordInput: EditText
    private lateinit var commandsInput: EditText
    private lateinit var saveButton: Button
    private lateinit var resetButton: Button
    private lateinit var listAppsButton: Button

    private val permissionRequestCode = 100

    // Пока окно открыто — раз в секунду подтягиваем последний распознанный
    // текст и статус из RecognitionState (их пишет фоновый сервис).
    private val pollHandler = Handler(Looper.getMainLooper())
    private val pollIntervalMs = 1000L
    private val pollRunnable = object : Runnable {
        override fun run() {
            val text = RecognitionState.getLastText(this@MainActivity)
            val status = RecognitionState.getLastStatus(this@MainActivity)
            resultText.text = text.ifEmpty { "—" }
            if (status.isNotEmpty()) statusText.text = status
            pollHandler.postDelayed(this, pollIntervalMs)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        resultText = findViewById(R.id.resultText)
        startButton = findViewById(R.id.startButton)
        stopButton = findViewById(R.id.stopButton)
        wakeWordInput = findViewById(R.id.wakeWordInput)
        commandsInput = findViewById(R.id.commandsInput)
        saveButton = findViewById(R.id.saveButton)
        resetButton = findViewById(R.id.resetButton)
        listAppsButton = findViewById(R.id.listAppsButton)

        wakeWordInput.setText(CommandRegistry.getWakeWord(this))
        commandsInput.setText(CommandRegistry.getCommandsJson(this))

        startButton.setOnClickListener { requestPermissionsAndStart() }
        stopButton.setOnClickListener {
            ServiceState.setShouldRun(this, false)
            ServiceWatchdog.cancel(this)
            stopService(Intent(this, ListenerService::class.java))
            statusText.text = "Остановлено"
        }
        saveButton.setOnClickListener { saveSettings() }
        resetButton.setOnClickListener { resetSettings() }
        listAppsButton.setOnClickListener { showInstalledApps() }
    }

    // Список установленных приложений (название + имя пакета), чтобы было
    // откуда взять значение для "package" в команде LAUNCH_APP или
    // "browser" в OPEN_BROWSER/OPEN_URL/SEARCH — угадать имя пакета иначе
    // неоткуда. Текст выделяемый, чтобы можно было скопировать нужную строку.
    private fun showInstalledApps() {
        val pm = packageManager
        val launcherIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(launcherIntent, 0)
            .map { it.loadLabel(pm).toString() to it.activityInfo.packageName }
            .distinctBy { it.second }
            .sortedBy { it.first.lowercase() }

        val text = apps.joinToString("\n") { (label, pkg) -> "$label\n$pkg\n" }

        val textView = TextView(this).apply {
            setText(text)
            setPadding(32, 32, 32, 32)
            setTextIsSelectable(true)
            movementMethod = ScrollingMovementMethod()
        }

        AlertDialog.Builder(this)
            .setTitle("Установленные приложения (${apps.size})")
            .setView(textView)
            .setPositiveButton("Закрыть", null)
            .show()
    }

    private fun saveSettings() {
        val word = wakeWordInput.text.toString().trim()
        if (word.isEmpty()) {
            Toast.makeText(this, "Активационное слово не может быть пустым", Toast.LENGTH_SHORT).show()
            return
        }
        try {
            CommandRegistry.setCommandsJson(this, commandsInput.text.toString())
        } catch (e: Exception) {
            Toast.makeText(this, "Ошибка в JSON команд: ${e.message}", Toast.LENGTH_LONG).show()
            return
        }
        CommandRegistry.setWakeWord(this, word)
        Toast.makeText(this, "Настройки сохранены", Toast.LENGTH_SHORT).show()
    }

    private fun resetSettings() {
        wakeWordInput.setText(CommandRegistry.DEFAULT_WAKE_WORD)
        commandsInput.setText(CommandRegistry.defaultCommandsJson())
        CommandRegistry.setWakeWord(this, CommandRegistry.DEFAULT_WAKE_WORD)
        CommandRegistry.setCommandsJson(this, CommandRegistry.defaultCommandsJson())
        Toast.makeText(this, "Восстановлены значения по умолчанию", Toast.LENGTH_SHORT).show()
    }

    private fun requestPermissionsAndStart() {
        val needed = mutableListOf<String>()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.RECORD_AUDIO)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            needed.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (needed.isNotEmpty()) {
            requestPermissions(needed.toTypedArray(), permissionRequestCode)
            return
        }
        startListenerService()
    }

    private fun startListenerService() {
        val intent = Intent(this, ListenerService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        requestIgnoreBatteryOptimizations()
        statusText.text = "Сервис запущен. Приложение можно закрыть — состояние смотрите в уведомлении.\n\n" +
            "Если после закрытия приложения оно перестаёт слушать — это, скорее всего, " +
            "агрессивное энергосбережение прошивки (типично для Huawei/HarmonyOS-устройств), " +
            "а не баг: откройте настройки телефона → Батарея/Приложения → найдите " +
            "«Audioreferent Test» → отключите оптимизацию батареи и включите автозапуск/" +
            "работу в фоне вручную."
    }

    // Стандартный Android-механизм для приложений, которым нужно продолжать
    // работу в фоне (навигаторы, плееры, ассистенты). На агрессивных
    // прошивках (Huawei/HarmonyOS) может не помочь полностью — там обычно
    // есть ещё отдельный экран "Автозапуск"/"Защищённые приложения",
    // который системным API не открывается, только вручную.
    private fun requestIgnoreBatteryOptimizations() {
        try {
            val powerManager = getSystemService(POWER_SERVICE) as PowerManager
            if (!powerManager.isIgnoringBatteryOptimizations(packageName)) {
                val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:$packageName")
                }
                startActivity(intent)
            }
        } catch (e: Exception) {
            // Не критично: часть прошивок (в т.ч. компатибилити-слои не
            // на базе AOSP) может не поддерживать этот экран вообще.
        }
    }

    override fun onResume() {
        super.onResume()
        pollHandler.post(pollRunnable)
    }

    override fun onPause() {
        super.onPause()
        pollHandler.removeCallbacks(pollRunnable)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == permissionRequestCode) {
            if (grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
                startListenerService()
            } else {
                statusText.text = "Нужны разрешения на микрофон и уведомления"
            }
        }
    }
}
