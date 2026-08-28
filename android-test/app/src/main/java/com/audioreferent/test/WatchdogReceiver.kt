package com.audioreferent.test

// Дополнительная страховка поверх foreground-сервиса: раз в 15 минут
// проверяем, жив ли ListenerService, и если нет (а работать он должен) —
// поднимаем его заново. Не зависит от того, открыто ли окно приложения —
// AlarmManager будит получателя независимо от Activity.
//
// Не спасает, если "закрытие окна" на этой прошивке равносильно полному
// принудительному останову приложения (force-stop) — в таком состоянии
// Android не доставляет даже явные broadcast/alarm до ручного повторного
// открытия приложения. Это ограничение платформы, а не то, что можно
// обойти кодом.

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.SystemClock

object ServiceWatchdog {
    private const val CHECK_INTERVAL_MS = 15 * 60 * 1000L
    private const val REQUEST_CODE = 1001

    private fun pendingIntent(context: Context): PendingIntent {
        val intent = Intent(context, WatchdogReceiver::class.java)
        return PendingIntent.getBroadcast(
            context, REQUEST_CODE, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    fun scheduleNextCheck(context: Context) {
        try {
            val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val triggerAt = SystemClock.elapsedRealtime() + CHECK_INTERVAL_MS
            alarmManager.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pendingIntent(context))
        } catch (e: Exception) {
            // Не критично — это лишь дополнительная страховка поверх
            // основного механизма (foreground-сервис + stopWithTask=false)
        }
    }

    fun cancel(context: Context) {
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        alarmManager.cancel(pendingIntent(context))
    }
}

class WatchdogReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (!ServiceState.getShouldRun(context)) return

        if (!ListenerService.isRunning) {
            val serviceIntent = Intent(context, ListenerService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent)
            } else {
                context.startService(serviceIntent)
            }
        }

        ServiceWatchdog.scheduleNextCheck(context)
    }
}
