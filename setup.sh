#!/usr/bin/env bash
# One-time setup: venv + Argos Translate + es<->en models. Network only needed here.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -m venv .venv
.venv/bin/pip install -q argostranslate lingua-language-detector transformers
.venv/bin/python - <<'PY'
import argostranslate.package as p
p.update_package_index()
for a in p.get_available_packages():
    if (a.from_code, a.to_code) in (("es", "en"), ("en", "es")):
        print("installing", a.from_code, "->", a.to_code)
        p.install_from_path(a.download())
PY
mkdir -p ~/.local/share/weechat/python/autoload
ln -sf "$PWD/metamorphosis.py" ~/.local/share/weechat/python/autoload/metamorphosis.py
echo done
