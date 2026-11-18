# Metamorphosis

Local, offline chat translation for WeeChat with automatic language detection (en, es, fr, de, ru). Nothing leaves your machine after the one-time model download.

## Install

```
./setup.sh                 # venv, dependencies, symlinks the script into WeeChat autoload
/script load metamorphosis.py
/meta model nllb-600m      # downloads ~2.5GB on first use
```

## Usage

```
/meta in en        translate incoming messages into English (translation first, original below)
/meta out fr       translate what you send into French (skipped if already French)
/meta on | off     pause / resume, keeping settings
/meta -b ...       apply to the current buffer only
/meta status
/meta model list | <name>
```

Wrap words in `backticks` to keep them untranslated. URLs are always kept as-is.

Models (both Meta NLLB): `nllb-600m` (default) and `nllb-1.3b` (better, slower, ~5.5GB).
