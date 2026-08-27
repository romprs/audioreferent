package com.audioreferent.test

// Экран запускает/останавливает фоновый сервис (ListenerService) и
// содержит настройки: активационное слово и список команд (JSON).
// Правки сохраняются в SharedPreferences и подхватываются сервисом на
// лету — перезапускать сервис не нужно.

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {

    private lateinit var statusText: TextView
    private lateinit var startButton: Button
    private lateinit var stopButton: Button
    private lateinit var wakeWordInput: EditText
    private lateinit var commandsInput: EditText
    private lateinit var saveButton: Button
    private lateinit var resetButton: Button

    private val permissionRequestCode = 100

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        startButton = findViewById(R.id.startButton)
        stopButton = findViewById(R.id.stopButton)
        wakeWordInput = findViewById(R.id.wakeWordInput)
        commandsInput = findViewById(R.id.commandsInput)
        saveButton = findViewById(R.id.saveButton)
        resetButton = findViewById(R.id.resetButton)

        wakeWordInput.setText(CommandRegistry.getWakeWord(this))
        commandsInput.setText(CommandRegistry.getCommandsJson(this))

        startButton.setOnClickListener { requestPermissionsAndStart() }
        stopButton.setOnClickListener {
            stopService(Intent(this, ListenerService::class.java))
            statusText.text = "Остановлено"
        }
        saveButton.setOnClickListener { saveSettings() }
        resetButton.setOnClickListener { resetSettings() }
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
        statusText.text = "Сервис запущен. Приложение можно закрыть — состояние смотрите в уведомлении."
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
