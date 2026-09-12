#!/usr/bin/env bash
set -euo pipefail
# Сборка RPM audioreferent на машине с rpmbuild (RED OS). Запускать из корня
# репозитория: packaging/build_rpm.sh
#
# Модели Vosk (Source1/Source2 спеки) слишком большие для репозитория — они
# должны уже лежать в ~/rpmbuild/SOURCES/:
#   vosk-model-ru-0.42-noextras.tar.gz  (vosk-model-ru-0.42 без rescore/ и rnnlm/)
#   vosk-model-spk-0.4.tar.gz
# Как их получить: см. packaging/README.md.

cd "$(dirname "$0")/.."

NAME=audioreferent
VERSION=$(grep -m1 '^Version:' packaging/audioreferent.spec | awk '{print $2}')

RPMBUILD_ROOT="${HOME}/rpmbuild"
mkdir -p "${RPMBUILD_ROOT}"/{SOURCES,SPECS,BUILD,RPMS,SRPMS,BUILDROOT}

for f in vosk-model-ru-0.42-noextras.tar.gz vosk-model-spk-0.4.tar.gz; do
    if [ ! -f "${RPMBUILD_ROOT}/SOURCES/${f}" ]; then
        echo "Нет ${RPMBUILD_ROOT}/SOURCES/${f} — положите модели (см. packaging/README.md)" >&2
        exit 1
    fi
done

git archive --format=tar.gz --prefix="${NAME}-${VERSION}/" -o "${RPMBUILD_ROOT}/SOURCES/${NAME}-${VERSION}.tar.gz" HEAD
cp packaging/audioreferent.spec "${RPMBUILD_ROOT}/SPECS/"

rpmbuild -ba "${RPMBUILD_ROOT}/SPECS/audioreferent.spec"

echo
echo "Готово. RPM:"
find "${RPMBUILD_ROOT}/RPMS" -name "${NAME}-${VERSION}*.rpm"
