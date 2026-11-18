import json
import os
import subprocess

import weechat

weechat.register("metamorphosis", "chase", "0.1", "MIT",
                 "Local chat translation with automatic language detection", "", "")

HERE = os.path.dirname(os.path.realpath(globals().get("__file__", ""))) \
    or os.path.expanduser("~/syncedprojects/Metamorphosis")
LANGS = {"en": "en", "english": "en", "es": "es", "spanish": "es", "fr": "fr", "french": "fr",
         "de": "de", "german": "de", "ru": "ru", "russian": "ru"}
MODELS = ("argos", "opus-mt", "nllb-600m", "nllb-1.3b")
MARK = "metamorphosis"
DEFAULT_MODEL = "nllb-600m"

state = {}      # "*" / buffer full_name -> {"in": lang, "out": lang, "on": bool}; "model" -> name
pending = {}    # request id -> callback(text, src); text is None when skipped
bypass = set()  # outgoing strings we re-send ourselves
sent = {}       # translated outgoing string -> its language, for labelling our echo
seen_err = set()
proc = None
rbuf = ""
next_id = 0
WHITE = weechat.color("white")
GREY = weechat.color("darkgray")
RESET = weechat.color("reset")


def load():
    global state
    try:
        state = json.loads(weechat.config_get_plugin("meta") or "{}")
    except ValueError:
        state = {}


def save():
    weechat.config_set_plugin("meta", json.dumps(state))


def cfg(buf):
    name = weechat.buffer_get_string(buf, "full_name")
    c = {**state.get("*", {}), **state.get(name, {})}
    return c if c.get("on", True) else {}


def start_worker():
    global proc
    py = os.path.join(HERE, ".venv", "bin", "python")
    proc = subprocess.Popen([py, os.path.join(HERE, "translate_worker.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    os.set_blocking(proc.stdout.fileno(), False)
    weechat.hook_fd(proc.stdout.fileno(), 1, 0, 0, "worker_cb", "")


def worker_cb(data, fd):
    fd = int(fd)
    global rbuf
    try:
        rbuf += os.read(fd, 65536).decode()
    except OSError:
        return weechat.WEECHAT_RC_OK
    *lines, rbuf = rbuf.split("\n")
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if "status" in r:
            weechat.prnt("", "metamorphosis: " + r["status"])
            continue
        if r.get("err") and r["err"] not in seen_err:
            seen_err.add(r["err"])
            weechat.prnt("", "metamorphosis: " + r["err"])
        cb = pending.pop(r.get("id"), None)
        if cb:
            cb(r.get("text"), r.get("src"))
    return weechat.WEECHAT_RC_OK


def translate(text, dst, cb, assume=None):
    send({"dst": dst, "text": text, "assume": assume}, cb)


def send(req, cb=None):
    global next_id
    next_id += 1
    if cb:
        pending[next_id] = cb
    try:
        proc.stdin.write(json.dumps({"id": next_id, **req}) + "\n")
        proc.stdin.flush()
    except (OSError, ValueError):
        pending.pop(next_id, None)
        weechat.prnt("", "metamorphosis: worker not running (run setup.sh)")


def in_cb(data, buf, date, tags, displayed, highlight, prefix, message):
    t = tags.split(",")
    me = weechat.buffer_get_string(buf, "localvar_nick")
    if MARK in t or "self_msg" in t or (me and "nick_" + me in t):
        return weechat.WEECHAT_RC_OK
    dst = cfg(buf).get("in")
    if not dst:
        return weechat.WEECHAT_RC_OK

    hd = weechat.hdata_get("line_data")
    own_lines = weechat.hdata_pointer(weechat.hdata_get("buffer"), buf, "own_lines")
    last = weechat.hdata_pointer(weechat.hdata_get("lines"), own_lines, "last_line")
    target = weechat.hdata_pointer(weechat.hdata_get("line"), last, "data")

    def show(out, src):
        if not out or out.strip().lower() == message.strip().lower():
            return
        hl = weechat.hdata_get("line")
        line = last
        for _ in range(300):
            if not line or weechat.hdata_pointer(hl, line, "data") == target:
                break
            line = weechat.hdata_move(hl, line, -1)
        if line:
            weechat.hdata_update(hd, target, {"message": f"{WHITE}[{dst.upper()}] {out}"})
        else:
            weechat.prnt_date_tags(buf, 0, MARK + ",no_log", f"\t{WHITE}[{dst.upper()}] {out}")
        weechat.prnt_date_tags(buf, 0, MARK + ",no_log", f"\t{GREY}[{src.upper()}] {message}")
    translate(message, dst, show)
    return weechat.WEECHAT_RC_OK


def line_cb(data, line):
    lang = sent.pop(line["message"], None)
    return {"message": f"{GREY}[{lang.upper()}] {line['message']}"} if lang else {}


def out_cb(data, modifier, buf, string):
    dst = cfg(buf).get("out")
    if weechat.buffer_get_string(buf, "localvar_type") not in ("channel", "private"):
        return string
    if string in bypass:
        bypass.discard(string)
        return string
    if not dst or not string.strip() or (string.startswith("/") and not string.startswith("//")):
        return string

    def done(out, src):
        if not out:
            bypass.add(string)
            weechat.command(buf, string)
            return
        bypass.add(out)
        sent[out] = dst
        weechat.command(buf, out)
        weechat.prnt_date_tags(buf, 0, MARK + ",no_log", f"\t{WHITE}[{src.upper()}] {string}")
    translate(string, dst, done, cfg(buf).get("in") or "en")
    return ""


def cmd_cb(data, buf, args):
    a = args.split()
    name = weechat.buffer_get_string(buf, "full_name")
    if a and a[0] == "model":
        if len(a) == 1 or a[1] == "list":
            send({"cmd": "list"}, lambda t, _: [weechat.prnt(buf, "metamorphosis: " + l) for l in t.split("\n")])
        elif a[1] in MODELS:
            state["model"] = a[1]
            save()
            send({"cmd": "load", "name": a[1]})
        else:
            weechat.prnt(buf, "metamorphosis: unknown model, see /meta model list")
        return weechat.WEECHAT_RC_OK
    here = bool(a and a[0] == "-b")
    if here:
        a = a[1:]
    else:
        name = "*"
    if not a or a[0] == "status":
        weechat.prnt(buf, f"metamorphosis: global={state.get('*', {})} here={state.get(name, {}) if here else cfg(buf)} "
                          f"model={state.get('model', DEFAULT_MODEL)}")
        return weechat.WEECHAT_RC_OK
    s = state.setdefault(name, {})
    if a[0] in ("in", "out") and len(a) == 2 and (a[1] == "off" or a[1] in LANGS):
        if a[1] != "off":
            s[a[0]] = LANGS[a[1]]
        elif here:
            s[a[0]] = ""
        else:
            s.pop(a[0], None)
    elif a[0] in ("on", "off") and len(a) == 1:
        s["on"] = a[0] == "on"
    else:
        weechat.command(buf, "/help meta")
        return weechat.WEECHAT_RC_OK
    save()
    weechat.prnt(buf, f"metamorphosis: {'here' if here else 'global'} -> {s}")
    return weechat.WEECHAT_RC_OK


load()
start_worker()
send({"cmd": "load", "name": state.get("model", DEFAULT_MODEL)})
weechat.hook_print("", "irc_privmsg", "", 1, "in_cb", "")
weechat.hook_line("formatted", "*", "irc_privmsg", "line_cb", "")
weechat.hook_modifier("input_text_for_buffer", "out_cb", "")
weechat.hook_command(
    "meta", "local chat translation with automatic language detection (en es fr de ru)",
    "[-b] in <lang|off> || [-b] out <lang|off> || [-b] on|off || status || model [list|<name>]",
    "  in: translate incoming messages into <lang> (translation first, original below)\n"
    " out: translate what you send into <lang> (skipped if already in it)\n"
    "on/off: pause or resume everything, keeping settings\n"
    "  -b: apply to the current buffer only instead of globally\n"
    "model: list models, or switch to one (downloaded on first use, then fully offline)",
    "in|out en|es|fr|de|ru|off || on || off || status || model list|argos|opus-mt|nllb-600m|nllb-1.3b"
    " || -b in|out en|es|fr|de|ru|off || -b on || -b off", "cmd_cb", "")
