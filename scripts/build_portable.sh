#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== SC2 ChatBot portable build ==="

python3 -m pip install -r requirements.txt
python3 -m pip install 'pyinstaller>=6.0'

pyinstaller --noconfirm SC2ChatBot.spec

mkdir -p dist/SC2ChatBot/config dist/SC2ChatBot/tools
cp -f config/config.example.yaml dist/SC2ChatBot/config/
if [[ ! -f dist/SC2ChatBot/config/config.yaml ]]; then
  cp -f config/config.yaml dist/SC2ChatBot/config/
fi
cp -f tools/measure_chat_region.py dist/SC2ChatBot/tools/
cp -f portable/README_PORTABLE.txt dist/SC2ChatBot/
cp -f portable/SWITCH_MODES.txt dist/SC2ChatBot/

echo
echo "Done. Portable folder: dist/SC2ChatBot/"
echo "  Run:  ./dist/SC2ChatBot/SC2ChatBot"
echo "  Edit: dist/SC2ChatBot/config/config.yaml"
