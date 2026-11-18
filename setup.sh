#!/usr/bin/env bash
# One-time setup: venv + dependencies, links the script into WeeChat autoload.
# The NLLB model downloads on first use: /meta model nllb-600m
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -m venv .venv
.venv/bin/pip install -q torch transformers sentencepiece lingua-language-detector
mkdir -p ~/.local/share/weechat/python/autoload
ln -sf "$PWD/metamorphosis.py" ~/.local/share/weechat/python/autoload/metamorphosis.py
echo done
