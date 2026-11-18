import json
import sys
import threading

import re

# name -> (description, HF repo)
MODELS = {
    "nllb-600m": ("Meta NLLB distilled 600M, ~2.5GB (default)", "facebook/nllb-200-distilled-600M"),
    "nllb-1.3b": ("Meta NLLB distilled 1.3B, ~5.5GB, best quality, slower", "facebook/nllb-200-distilled-1.3B"),
}
NLLB = {"en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn", "ru": "rus_Cyrl"}

active = None
loaded = {}  # name -> translate fn
lock = threading.Lock()
out_lock = threading.Lock()


_detector = None


def detect(text):
    """Return a language code from NLLB's set, or None if too short/unsure."""
    global _detector
    from lingua import Language, LanguageDetectorBuilder
    if _detector is None:
        by_code = {"en": Language.ENGLISH, "es": Language.SPANISH, "fr": Language.FRENCH,
                   "de": Language.GERMAN, "ru": Language.RUSSIAN}
        _detector = (LanguageDetectorBuilder.from_languages(*by_code.values())
                     .with_minimum_relative_distance(0.2).build(), {v: k for k, v in by_code.items()})
    det, codes = _detector
    plain = re.sub(r"https?://\S+|ZQ\d+ZQ|\w*_\w*", " ", text)
    if len(re.findall(r"\w+", plain)) < 2:
        return None
    return codes.get(det.detect_language_of(plain))


def protect(text):
    """Swap `backticked` words and URLs for placeholders the model leaves alone."""
    keep = []

    def sub(m):
        keep.append(m.group(1) or m.group(0))
        return f"ZQ{len(keep) - 1}ZQ"
    return re.sub(r"`([^`]+)`|https?://\S+", sub, text), keep


def restore(text, keep):
    for i, word in enumerate(keep):
        mark = f"ZQ{i}ZQ"
        text = text.replace(mark, word) if mark in text else f"{text} {word}"
    return text


def translate_text(text, src, dst):
    """Translate sentence by sentence; models drop trailing sentences on long input."""
    parts = [p for p in re.split(r"(?<=[.!?…])\s+", text.strip()) if p]
    return " ".join(loaded[active](p, src, dst) for p in parts)


def emit(obj):
    with out_lock:
        print(json.dumps(obj), flush=True)


def repos(name):
    return [MODELS[name][1]]


def fetch(repo):
    from huggingface_hub import HfApi, snapshot_download
    names = HfApi().list_repo_files(repo)
    weights = "*.safetensors" if any(n.endswith(".safetensors") for n in names) else "pytorch_model.bin"
    snapshot_download(repo, allow_patterns=["*.json", "*.model", "*.spm", "*.txt", weights])


def installed(name):
    from pathlib import Path

    from huggingface_hub import try_to_load_from_cache
    for r in repos(name):
        cfg = try_to_load_from_cache(r, "config.json")
        if not isinstance(cfg, str):
            return False
        d = Path(cfg).parent
        if not (any(d.glob("*.safetensors")) or (d / "pytorch_model.bin").exists()):
            return False
    return True


def build(name):
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    repo = MODELS[name][1]
    tok = AutoTokenizer.from_pretrained(repo)
    model = AutoModelForSeq2SeqLM.from_pretrained(repo).eval()

    def run(text, src, dst):
        tok.src_lang = NLLB[src]
        enc = tok(text, return_tensors="pt", truncation=True, max_length=512)
        out = model.generate(**enc, num_beams=4, max_new_tokens=512,
                             forced_bos_token_id=tok.convert_tokens_to_ids(NLLB[dst]))
        return re.sub(r"\s+([.,])", r"\1", tok.decode(out[0], skip_special_tokens=True))
    return run


def load(name):
    global active
    try:
        if name not in loaded:
            if not installed(name):
                emit({"status": f"downloading {name} ({MODELS[name][0]}) ..."})
                for r in repos(name):
                    fetch(r)
            emit({"status": f"loading {name} ..."})
            loaded[name] = build(name)
        active = name
        emit({"status": f"model: {name} ready"})
    except Exception as e:
        emit({"status": f"model {name} failed: {e}"})


def listing():
    return "\n".join(
        f"{'*' if n == active else ' '} {n:10} {'installed' if installed(n) else 'not downloaded':15} {d}"
        for n, (d, _) in MODELS.items())


for line in sys.stdin:
    req = {}
    try:
        req = json.loads(line)
        if req.get("cmd") == "load":
            threading.Thread(target=load, args=(req["name"],), daemon=True).start()
            continue
        if req.get("cmd") == "list":
            emit({"id": req["id"], "text": listing()})
            continue
        text, keep = protect(req["text"])
        if keep and not re.search(r"\w", re.sub(r"ZQ\d+ZQ", "", text)):
            emit({"id": req["id"], "text": restore(text, keep), "src": req.get("assume") or req["dst"]})
            continue
        src = detect(text) or req.get("assume")
        if src is None or src == req["dst"] or active not in loaded:
            emit({"id": req["id"], "skip": True})
            continue
        emit({"id": req["id"], "text": restore(translate_text(text, src, req["dst"]), keep), "src": src})
    except Exception as e:
        emit({"id": req.get("id"), "skip": True, "err": str(e)})
