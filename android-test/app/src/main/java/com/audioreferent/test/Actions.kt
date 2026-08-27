package com.audioreferent.test

// Выполнение действий на самом устройстве Android — аналог actions.py
// из основного проекта, только средствами Android SDK вместо xdg-open/pactl.

import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.net.Uri

object Actions {

    fun execute(context: Context, spec: CommandSpec) {
        when (spec.action) {
            ActionType.OPEN_BROWSER -> openBrowser(context)
            ActionType.VOLUME_CHANGE -> changeVolume(context, spec.arg)
            ActionType.VOLUME_MUTE -> setMute(context, spec.arg != 0)
        }
    }

    private fun openBrowser(context: Context) {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.google.com")).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
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
