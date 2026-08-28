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

enum class ActionType { OPEN_BROWSER, OPEN_URL, SEARCH, LAUNCH_APP, VOLUME_CHANGE, VOLUME_MUTE }

data class CommandSpec(
    val phrases: List<String>,
    val action: ActionType,
    val arg: Int = 0,
    val url: String? = null,
    val browserPackage: String? = null,
    val appPackage: String? = null,
    // Захватывать ли остаток фразы после совпавшей команды как параметр
    // (например, текст запроса для SEARCH). Для остальных действий не нужен.
    val captureRemainder: Boolean = false
)

data class CommandMatch(val spec: CommandSpec, val remainder: String)

object CommandRegistry {

    private const val PREFS_NAME = "audioreferent_settings"
    private const val KEY_WAKE_WORD = "wake_word"
    private const val KEY_COMMANDS_JSON = "commands_json"
    const val DEFAULT_WAKE_WORD = "вика"

    val DEFAULT_COMMANDS: List<CommandSpec> = listOf(
        CommandSpec(listOf("открой браузер", "запусти браузер"), ActionType.OPEN_BROWSER),
        CommandSpec(
            listOf("найди", "найди в интернете", "поищи"), ActionType.SEARCH,
            captureRemainder = true
        ),
        CommandSpec(
            listOf("открой яндекс"), ActionType.OPEN_URL,
            url = "https://ya.ru"
        ),
        CommandSpec(
            listOf("открой гугл"), ActionType.OPEN_URL,
            url = "https://www.google.com"
        ),
        CommandSpec(listOf("сделай громче", "увеличь громкость", "громче"), ActionType.VOLUME_CHANGE, 10),
        CommandSpec(listOf("сделай тише", "уменьши громкость", "тише"), ActionType.VOLUME_CHANGE, -10),
        CommandSpec(listOf("выключи звук", "заглуши звук", "без звука"), ActionType.VOLUME_MUTE, 1),
        CommandSpec(listOf("включи звук"), ActionType.VOLUME_MUTE, 0)
        // Пример запуска конкретного приложения (пакет узнать кнопкой
        // "Список приложений" в настройках):
        // CommandSpec(listOf("открой калькулятор"), ActionType.LAUNCH_APP, appPackage = "com.android.calculator2")
    )

    fun defaultCommandsJson(): String = commandsToJson(DEFAULT_COMMANDS)

    fun commandsToJson(commands: List<CommandSpec>): String {
        val array = JSONArray()
        for (spec in commands) {
            val obj = JSONObject()
            obj.put("phrases", JSONArray(spec.phrases))
            obj.put("action", spec.action.name)
            if (spec.arg != 0) obj.put("arg", spec.arg)
            if (spec.url != null) obj.put("url", spec.url)
            if (spec.browserPackage != null) obj.put("browser", spec.browserPackage)
            if (spec.appPackage != null) obj.put("package", spec.appPackage)
            if (spec.captureRemainder) obj.put("captureRemainder", true)
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
            result.add(
                CommandSpec(
                    phrases = phrases,
                    action = action,
                    arg = obj.optInt("arg", 0),
                    url = if (obj.has("url")) obj.getString("url") else null,
                    browserPackage = if (obj.has("browser")) obj.getString("browser") else null,
                    appPackage = if (obj.has("package")) obj.getString("package") else null,
                    captureRemainder = obj.optBoolean("captureRemainder", false)
                )
            )
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

    fun match(context: Context, text: String): CommandMatch? {
        val normalized = normalize(text)
        if (normalized.isEmpty()) return null
        var best: CommandMatch? = null
        var bestLen = -1
        for (spec in loadCommands(context)) {
            for (phrase in spec.phrases) {
                val normPhrase = normalize(phrase)
                if (normPhrase.isEmpty()) continue
                val idx = normalized.indexOf(normPhrase)
                if (idx >= 0 && normPhrase.length > bestLen) {
                    val remainder = normalized.substring(idx + normPhrase.length).trim()
                    best = CommandMatch(spec, remainder)
                    bestLen = normPhrase.length
                }
            }
        }
        return best
    }

    fun describe(match: CommandMatch): String = when (match.spec.action) {
        ActionType.OPEN_BROWSER -> "открыть браузер"
        ActionType.OPEN_URL -> "открыть ${match.spec.url}"
        ActionType.SEARCH -> if (match.remainder.isNotEmpty()) "искать «${match.remainder}»" else "искать (запрос не расслышан)"
        ActionType.LAUNCH_APP -> "запустить ${match.spec.appPackage}"
        ActionType.VOLUME_CHANGE -> if (match.spec.arg >= 0) "сделать громче" else "сделать тише"
        ActionType.VOLUME_MUTE -> if (match.spec.arg != 0) "выключить звук" else "включить звук"
    }
}
