package com.audioreferent.test

// Настройки (активационное слово и список команд) хранятся в
// SharedPreferences как обычный текст/JSON — тот же принцип, что и
// config.yaml в основном проекте для РЭД ОС: пользователь редактирует
// текстовое представление, а не тыкает форму с кнопками "добавить строку".
// Список команд перечитывается при каждом сопоставлении, поэтому правки
// применяются сразу, без перезапуска фонового сервиса.

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

enum class ActionType { OPEN_BROWSER, VOLUME_CHANGE, VOLUME_MUTE }

data class CommandSpec(val phrases: List<String>, val action: ActionType, val arg: Int = 0)

object CommandRegistry {

    private const val PREFS_NAME = "audioreferent_settings"
    private const val KEY_WAKE_WORD = "wake_word"
    private const val KEY_COMMANDS_JSON = "commands_json"
    const val DEFAULT_WAKE_WORD = "вика"

    val DEFAULT_COMMANDS: List<CommandSpec> = listOf(
        CommandSpec(listOf("открой браузер", "запусти браузер"), ActionType.OPEN_BROWSER),
        CommandSpec(listOf("сделай громче", "увеличь громкость", "громче"), ActionType.VOLUME_CHANGE, 10),
        CommandSpec(listOf("сделай тише", "уменьши громкость", "тише"), ActionType.VOLUME_CHANGE, -10),
        CommandSpec(listOf("выключи звук", "заглуши звук", "без звука"), ActionType.VOLUME_MUTE, 1),
        CommandSpec(listOf("включи звук"), ActionType.VOLUME_MUTE, 0)
    )

    fun defaultCommandsJson(): String = commandsToJson(DEFAULT_COMMANDS)

    fun commandsToJson(commands: List<CommandSpec>): String {
        val array = JSONArray()
        for (spec in commands) {
            val obj = JSONObject()
            obj.put("phrases", JSONArray(spec.phrases))
            obj.put("action", spec.action.name)
            obj.put("arg", spec.arg)
            array.put(obj)
        }
        return array.toString(2)
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun getWakeWord(context: Context): String =
        prefs(context).getString(KEY_WAKE_WORD, DEFAULT_WAKE_WORD) ?: DEFAULT_WAKE_WORD

    fun setWakeWord(context: Context, word: String) {
        prefs(context).edit().putString(KEY_WAKE_WORD, word.trim()).apply()
    }

    fun getCommandsJson(context: Context): String =
        prefs(context).getString(KEY_COMMANDS_JSON, null) ?: defaultCommandsJson()

    // Бросает исключение на неверном JSON — вызывающая сторона (экран
    // настроек) должна поймать её и показать ошибку, а не тихо сохранить
    // нерабочий конфиг.
    fun setCommandsJson(context: Context, json: String) {
        parseCommands(json)
        prefs(context).edit().putString(KEY_COMMANDS_JSON, json).apply()
    }

    fun parseCommands(json: String): List<CommandSpec> {
        val array = JSONArray(json)
        val result = mutableListOf<CommandSpec>()
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            val phrasesArray = obj.getJSONArray("phrases")
            val phrases = (0 until phrasesArray.length()).map { phrasesArray.getString(it) }
            val action = ActionType.valueOf(obj.getString("action"))
            val arg = obj.optInt("arg", 0)
            result.add(CommandSpec(phrases, action, arg))
        }
        return result
    }

    private fun loadCommands(context: Context): List<CommandSpec> = try {
        parseCommands(getCommandsJson(context))
    } catch (e: Exception) {
        DEFAULT_COMMANDS
    }

    private val nonWordRegex = Regex("[^\\p{L}\\p{Nd}\\s]")
    private val spacesRegex = Regex("\\s+")

    private fun normalize(text: String): String {
        val lower = text.lowercase()
        val noPunct = nonWordRegex.replace(lower, "")
        return spacesRegex.replace(noPunct, " ").trim()
    }

    fun match(context: Context, text: String): CommandSpec? {
        val normalized = normalize(text)
        if (normalized.isEmpty()) return null
        var best: CommandSpec? = null
        var bestLen = -1
        for (spec in loadCommands(context)) {
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
