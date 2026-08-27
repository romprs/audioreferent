#!/bin/bash
# Скачивает маленькую русскую модель Vosk в assets перед сборкой.
# Без этого шага сборка пройдёт, но StorageService.unpack() в приложении
# не найдёт файлы модели в assets/model-ru и упадёт с ошибкой в рантайме.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$SCRIPT_DIR/../app/src/main/assets"
MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
TMP_ZIP="$(mktemp)"

mkdir -p "$ASSETS_DIR"
echo "Скачиваю модель..."
curl -L -o "$TMP_ZIP" "$MODEL_URL"

echo "Распаковываю в $ASSETS_DIR/model-ru ..."
rm -rf "$ASSETS_DIR/model-ru"
unzip -q "$TMP_ZIP" -d "$ASSETS_DIR"
mv "$ASSETS_DIR/vosk-model-small-ru-0.22" "$ASSETS_DIR/model-ru"
rm -f "$TMP_ZIP"

echo "Готово: $ASSETS_DIR/model-ru"
