package com.audioreferent.test

// Выполнение действий на самом устройстве Android — аналог actions.py
// из основного проекта, только средствами Android SDK.

import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.net.Uri

class ActionError(message: String) : Exception(message)

object Actions {

    fun execute(context: Context, match: CommandMatch) {
        val spec = match.spec
        when (spec.action) {
            ActionType.OPEN_BROWSER -> openUrl(context, "https://www.google.com", spec.browserPackage)
            ActionType.OPEN_URL -> openUrl(context, spec.url ?: throw ActionError("В команде не указан url"), spec.browserPackage)
            ActionType.SEARCH -> {
                if (match.remainder.isEmpty()) throw ActionError("Не расслышала, что искать")
                val searchUrl = "https://www.google.com/search?q=" + Uri.encode(match.remainder)
                openUrl(context, searchUrl, spec.browserPackage)
            }
            ActionType.LAUNCH_APP -> launchApp(context, spec.appPackage ?: throw ActionError("В команде не указан package"))
            ActionType.VOLUME_CHANGE -> changeVolume(context, spec.arg)
            ActionType.VOLUME_MUTE -> setMute(context, spec.arg != 0)
        }
    }

    private fun openUrl(context: Context, url: String, browserPackage: String?) {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (!browserPackage.isNullOrEmpty()) setPackage(browserPackage)
        }
        try {
            context.startActivity(intent)
        } catch (e: Exception) {
            throw ActionError("Не удалось открыть ссылку" + (browserPackage?.let { " в $it" } ?: "") + ": ${e.message}")
        }
    }

    private fun launchApp(context: Context, packageName: String) {
        val intent = context.packageManager.getLaunchIntentForPackage(packageName)
            ?: throw ActionError("Приложение $packageName не установлено")
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
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
