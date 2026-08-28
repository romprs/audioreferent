package com.audioreferent.test

import android.content.Context

// Флаг "должен ли сервис работать" — отдельно от факта, жив ли он прямо
// сейчас. Нужен, чтобы watchdog (см. WatchdogReceiver) не поднимал сервис
// заново после того, как пользователь сам его остановил.
object ServiceState {
    private const val PREFS_NAME = "audioreferent_settings"
    private const val KEY_SHOULD_RUN = "service_should_run"

    fun getShouldRun(context: Context): Boolean =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(KEY_SHOULD_RUN, false)

    fun setShouldRun(context: Context, value: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit().putBoolean(KEY_SHOULD_RUN, value).apply()
    }
}
