package com.audioreferent.test

// Тот же принцип сопоставления команд, что и в основном проекте
// audioreferent для РЭД ОС (commands.py): фиксированный список фраз,
// подстрочное сравнение, побеждает самая длинная совпавшая фраза.

enum class ActionType { OPEN_BROWSER, VOLUME_CHANGE, VOLUME_MUTE }

data class CommandSpec(val phrases: List<String>, val action: ActionType, val arg: Int = 0)

object CommandRegistry {

    private val commands: List<CommandSpec> = listOf(
        CommandSpec(listOf("открой браузер", "запусти браузер"), ActionType.OPEN_BROWSER),
        CommandSpec(listOf("сделай громче", "увеличь громкость", "громче"), ActionType.VOLUME_CHANGE, 10),
        CommandSpec(listOf("сделай тише", "уменьши громкость", "тише"), ActionType.VOLUME_CHANGE, -10),
        CommandSpec(listOf("выключи звук", "заглуши звук", "без звука"), ActionType.VOLUME_MUTE, 1),
        CommandSpec(listOf("включи звук"), ActionType.VOLUME_MUTE, 0)
    )

    private val nonWordRegex = Regex("[^\\p{L}\\p{Nd}\\s]")
    private val spacesRegex = Regex("\\s+")

    private fun normalize(text: String): String {
        val lower = text.lowercase()
        val noPunct = nonWordRegex.replace(lower, "")
        return spacesRegex.replace(noPunct, " ").trim()
    }

    fun match(text: String): CommandSpec? {
        val normalized = normalize(text)
        if (normalized.isEmpty()) return null
        var best: CommandSpec? = null
        var bestLen = -1
        for (spec in commands) {
            for (phrase in spec.phrases) {
                val normPhrase = normalize(phrase)
                if (normPhrase.isNotEmpty() && normalized.contains(normPhrase) && normPhrase.length > bestLen) {
                    best = spec
                    bestLen = normPhrase.length
                }
            }
        }
        return best
    }

    fun describe(spec: CommandSpec): String = when (spec.action) {
        ActionType.OPEN_BROWSER -> "открыть браузер"
        ActionType.VOLUME_CHANGE -> if (spec.arg >= 0) "сделать громче" else "сделать тише"
        ActionType.VOLUME_MUTE -> if (spec.arg != 0) "выключить звук" else "включить звук"
    }
}
