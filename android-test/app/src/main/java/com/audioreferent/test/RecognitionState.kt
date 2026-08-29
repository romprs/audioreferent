package com.audioreferent.test

import android.content.Context

// Последний распознанный текст и статус — сервис пишет их сюда при каждом
// событии Vosk, а MainActivity (если сейчас открыта) периодически
// перечитывает и показывает. Через SharedPreferences, а не колбэк напрямую,
// чтобы не городить связывание с Activity, которой в фоновом режиме может
// вообще не быть — сервис работает независимо от того, слушает его кто-то
// или нет.
object RecognitionState {
    private const val PREFS_NAME = "audioreferent_settings"
    private const val KEY_LAST_TEXT = "last_recognized_text"
    private const val KEY_LAST_STATUS = "last_status"
    private const val KEY_HEARTBEAT = "last_heartbeat"

    fun setLast(context: Context, recognizedText: String, status: String) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putString(KEY_LAST_TEXT, recognizedText)
            .putString(KEY_LAST_STATUS, status)
            .apply()
    }

    fun getLastText(context: Context): String =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getString(KEY_LAST_TEXT, "") ?: ""

    fun getLastStatus(context: Context): String =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getString(KEY_LAST_STATUS, "") ?: ""

    // "Пульс" — время, когда сервис последний раз был точно жив (пишется
    // раз в 10 секунд независимо от того, распознаётся ли что-то). Главный
    // способ проверить, убивает ли систему процесс при закрытии окна: если
    // после ожидания это время сильно отстаёт от текущего — процесс мёртв.
    fun setHeartbeat(context: Context, time: String) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putString(KEY_HEARTBEAT, time)
            .apply()
    }

    fun getHeartbeat(context: Context): String =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getString(KEY_HEARTBEAT, "") ?: ""
}
