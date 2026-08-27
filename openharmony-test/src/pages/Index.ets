// Диагностическая страница: проверка распознавания русской речи системным
// ASR (Core Speech Kit) на устройстве с OpenHarmony/HarmonyOS, плюс проверка
// текстового срабатывания на активационное слово "вика" (та же идея, что и
// в основном проекте audioreferent для RED OS — только там она реализована
// на Vosk, а здесь мы её просто повторяем поверх системного распознавания,
// чтобы решить, годится ли этот движок вообще).

import { abilityAccessCtrl, common, PermissionRequestResult } from '@kit.AbilityKit';
import { speechRecognizer } from '@kit.CoreSpeechKit';
import { BusinessError } from '@kit.BasicServicesKit';

const WAKE_WORD = 'вика';

@Entry
@Component
struct Index {
  @State recognizedText: string = '';
  @State statusText: string = 'Нажмите «Старт» и произнесите: «Вика, открой браузер»';
  @State isListening: boolean = false;
  @State wakeWordDetected: boolean = false;

  private asrEngine: speechRecognizer.SpeechRecognitionEngine | undefined = undefined;
  private readonly sessionId: string = 'audioreferent-test-session';

  private async ensureMicPermission(): Promise<boolean> {
    const context = getContext(this) as common.UIAbilityContext;
    const atManager = abilityAccessCtrl.createAtManager();
    try {
      const result: PermissionRequestResult =
        await atManager.requestPermissionsFromUser(context, ['ohos.permission.MICROPHONE']);
      return result.authResults.every((code: number) => code === 0);
    } catch (err) {
      const error = err as BusinessError;
      this.statusText = `Ошибка запроса разрешения: ${error.code} ${error.message}`;
      return false;
    }
  }

  private createEngine(): Promise<void> {
    return new Promise((resolve, reject) => {
      // online: 1 — облачный движок (шире языковая поддержка, нужен интернет)
      // online: 0 — движок на устройстве (офлайн, но язык может быть не поддержан)
      // Если 'ru-RU' не поддерживается выбранным режимом, увидите ошибку в onError.
      const initParams: speechRecognizer.CreateEngineParams = {
        language: 'ru-RU',
        online: 1,
        extraParams: { recognizerMode: 'long' }
      };
      speechRecognizer.createEngine(initParams, (err: BusinessError, engine: speechRecognizer.SpeechRecognitionEngine) => {
        if (err) {
          reject(err);
          return;
        }
        this.asrEngine = engine;
        this.asrEngine.setListener(this.buildListener());
        resolve();
      });
    });
  }

  private buildListener(): speechRecognizer.RecognitionListener {
    return {
      onStart: (_sessionId: string, _eventMessage: string) => {
        this.statusText = 'Слушаю…';
      },
      onEvent: (_sessionId: string, _eventCode: number, _eventMessage: string) => {
        // служебные события движка (например, старт/конец фразы по VAD)
      },
      onResult: (_sessionId: string, result: speechRecognizer.SpeechRecognitionResult) => {
        this.recognizedText = result.result;
        this.checkWakeWord(result.result);
      },
      onComplete: (_sessionId: string, _eventMessage: string) => {
        this.statusText = 'Распознавание завершено';
        this.isListening = false;
      },
      onError: (_sessionId: string, errorCode: number, errorMessage: string) => {
        this.statusText = `Ошибка ASR: ${errorCode} ${errorMessage}`;
        this.isListening = false;
      }
    };
  }

  private checkWakeWord(text: string): void {
    const normalized = text.toLowerCase();
    this.wakeWordDetected = normalized.includes(WAKE_WORD);
    if (this.wakeWordDetected) {
      this.statusText = `Ключевое слово «${WAKE_WORD}» обнаружено!`;
    }
  }

  private async startListening(): Promise<void> {
    this.recognizedText = '';
    this.wakeWordDetected = false;
    this.statusText = 'Проверяю разрешение на микрофон…';

    const granted = await this.ensureMicPermission();
    if (!granted) {
      this.statusText = 'Нет разрешения на использование микрофона';
      return;
    }

    try {
      if (!this.asrEngine) {
        this.statusText = 'Создаю движок распознавания…';
        await this.createEngine();
      }
      const startParams: speechRecognizer.StartParams = {
        sessionId: this.sessionId,
        audioInfo: {
          audioType: 'pcm',
          sampleRate: 16000,
          soundChannel: 1,
          sampleBit: 16
        },
        extraParams: {
          sourceType: 0, // 0 = движок сам захватывает звук с микрофона устройства
          maxAudioDuration: 60000
        }
      };
      this.asrEngine!.startListening(startParams);
      this.isListening = true;
    } catch (err) {
      const error = err as BusinessError;
      this.statusText = `Не удалось запустить распознавание: ${error.code} ${error.message}`;
    }
  }

  private stopListening(): void {
    if (this.asrEngine && this.isListening) {
      this.asrEngine.finishListening(this.sessionId);
      this.isListening = false;
      this.statusText = 'Остановлено';
    }
  }

  aboutToDisappear(): void {
    if (this.asrEngine) {
      this.asrEngine.shutdown();
    }
  }

  build() {
    Column({ space: 16 }) {
      Text('Тест распознавания речи (RU)')
        .fontSize(20)
        .fontWeight(FontWeight.Bold)

      Text(this.statusText)
        .fontSize(14)
        .fontColor(this.wakeWordDetected ? Color.Green : Color.Gray)

      Text(this.recognizedText.length > 0 ? this.recognizedText : '—')
        .fontSize(18)
        .padding(12)
        .backgroundColor('#f0f0f0')
        .borderRadius(8)
        .width('100%')

      Row({ space: 12 }) {
        Button(this.isListening ? 'Слушаю…' : 'Старт')
          .enabled(!this.isListening)
          .onClick(() => { this.startListening(); })

        Button('Стоп')
          .enabled(this.isListening)
          .onClick(() => { this.stopListening(); })
      }
    }
    .width('100%')
    .height('100%')
    .padding(24)
    .justifyContent(FlexAlign.Center)
  }
}
