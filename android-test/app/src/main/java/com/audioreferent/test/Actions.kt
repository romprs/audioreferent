package com.audioreferent.test

// Выполнение действий на самом устройстве Android.

import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.net.Uri

class ActionError(message: String) : Exception(message)

object Actions {

    // Для действий, открывающих что-то на экране (браузер/приложение),
    // отдаём готовый Intent, а не запускаем его сами: реальный запуск и
    // резервная кнопка на уведомлении оркестрируются в ListenerService.
    // Так надо, потому что прямой startActivity() из фонового сервиса
    // Android иногда молча блокирует (background activity launch
    // restrictions — без исключения, просто ничего не происходит), и без
    // запасного варианта команда время от времени просто ничего не делает.
    fun buildActivityIntent(context: Context, match: CommandMatch): Intent? {
        val spec = match.spec
        return when (spec.action) {
            ActionType.OPEN_BROWSER -> viewIntent("https://www.google.com", spec.browserPackage)
            ActionType.OPEN_URL -> viewIntent(
                spec.url ?: throw ActionError("В команде не указан url"), spec.browserPackage
            )
            ActionType.SEARCH -> {
                if (match.remainder.isEmpty()) throw ActionError("Не расслышала, что искать")
                viewIntent("https://www.google.com/search?q=" + Uri.encode(match.remainder), spec.browserPackage)
            }
            ActionType.LAUNCH_APP -> {
                val pkg = spec.appPackage ?: throw ActionError("В команде не указан package")
                context.packageManager.getLaunchIntentForPackage(pkg)?.apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                } ?: throw ActionError("Приложение $pkg не установлено")
            }
            ActionType.VOLUME_CHANGE, ActionType.VOLUME_MUTE -> null
        }
    }

    private fun viewIntent(url: String, browserPackage: String?): Intent =
        Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (!browserPackage.isNullOrEmpty()) setPackage(browserPackage)
        }

    // Громкость и mute не открывают Activity — фоновые ограничения на них
    // не действуют, выполняются сразу и надёжно.
    fun executeNonActivity(context: Context, match: CommandMatch) {
        when (match.spec.action) {
            ActionType.VOLUME_CHANGE -> changeVolume(context, match.spec.arg)
            ActionType.VOLUME_MUTE -> setMute(context, match.spec.arg != 0)
            else -> Unit
        }
    }

    private fun changeVolume(context: Context, deltaPercent: Int) {
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val max = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val current = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
        val steps = (max * kotlin.math.abs(deltaPercent) / 100.0).toInt().coerceAtLeast(1)
        val target = (current + if (deltaPercent >= 0) steps else -steps).coerceIn(0, max)
        audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, target, AudioManager.FLAG_SHOW_UI)
    }

    private fun setMute(context: Context, mute: Boolean) {
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audioManager.adjustStreamVolume(
            AudioManager.STREAM_MUSIC,
            if (mute) AudioManager.ADJUST_MUTE else AudioManager.ADJUST_UNMUTE,
            AudioManager.FLAG_SHOW_UI
        )
    }
}
