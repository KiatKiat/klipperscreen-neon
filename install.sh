#!/usr/bin/env bash
# Neon theme + print monitor for KlipperScreen
#
#   bash install.sh              install (or update) and restart KlipperScreen
#   bash install.sh --uninstall  remove everything and restore your previous theme
#
# Only adds new files: styles/neon and addons/neon_monitor inside KlipperScreen.
# No file tracked by the KlipperScreen git repo is changed.
# KlipperScreen.conf is backed up before every change.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KS_DIR="${KS_DIR:-$HOME/KlipperScreen}"
CONF="${KS_CONF:-$HOME/printer_data/config/KlipperScreen.conf}"
BACKUP_ROOT="${NEON_BACKUP:-$HOME/neon-ks-backup}"
STATE="$BACKUP_ROOT/state.json"
MOONRAKER="${MOONRAKER_URL:-http://127.0.0.1:7125}"
NO_RESTART="${NO_RESTART:-0}"

c_ok() { printf '\033[1;32m%s\033[0m\n' "$*"; }
c_info() { printf '\033[1;36m%s\033[0m\n' "$*"; }
c_err() { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }

check() {
    if [[ ! -f "$KS_DIR/screen.py" || ! -f "$KS_DIR/panels/job_status.py" ]]; then
        c_err "KlipperScreen not found in $KS_DIR (set KS_DIR=/path/to/KlipperScreen)"
        exit 1
    fi
    if ! grep -q "_load_addons" "$KS_DIR/screen.py"; then
        c_err "This KlipperScreen build has no add-on support. Update KlipperScreen first."
        exit 1
    fi
    if [[ ! -f "$CONF" ]]; then
        c_info "No $CONF yet, creating an empty one"
        mkdir -p "$(dirname "$CONF")"
        touch "$CONF"
    fi
    command -v python3 >/dev/null || { c_err "python3 is required"; exit 1; }
}

backup() {
    local ts dir
    ts="$(date +%Y%m%d-%H%M%S)"
    dir="$BACKUP_ROOT/$ts"
    mkdir -p "$dir"
    cp -a "$CONF" "$dir/KlipperScreen.conf"
    [[ -d "$KS_DIR/styles/neon" ]] && cp -a "$KS_DIR/styles/neon" "$dir/styles-neon"
    [[ -d "$KS_DIR/addons/neon_monitor" ]] && cp -a "$KS_DIR/addons/neon_monitor" "$dir/addon-neon_monitor"
    c_ok "Backup saved: $dir"
}

edit_conf() {
    # $1 = install | uninstall
    python3 - "$1" "$CONF" "$STATE" <<'PY'
import json, os, re, sys

mode, conf, state_path = sys.argv[1], sys.argv[2], sys.argv[3]
MARK = "#~# --- Do not edit below this line. This section is auto generated --- #~#"
BEGIN, END = "# >>> neon-klipperscreen >>>", "# <<< neon-klipperscreen <<<"
MENU = f"""{BEGIN}
[menu __main monitor]
name: Monitor
icon: clock
panel: job_status
{END}"""

text = open(conf).read()
if MARK in text:
    user, saved = text.split(MARK, 1)
    saved_lines = saved.strip("\n").splitlines()
else:
    user, saved_lines = text, []

# strip a previous menu block
user = re.sub(rf"\n*{re.escape(BEGIN)}.*?{re.escape(END)}\n*", "\n", user, flags=re.S)

# saved section -> dict of sections keeping order
def parse(lines):
    out, cur = [], None
    for ln in lines:
        body = ln[4:] if ln.startswith("#~# ") else ln[3:] if ln.startswith("#~#") else None
        if body is None:
            continue
        m = re.match(r"\s*\[(.+)\]\s*$", body)
        if m:
            cur = [m.group(1), []]
            out.append(cur)
        elif cur is not None and body.strip():
            k, _, v = body.partition("=")
            cur[1].append([k.strip(), v.strip()])
    return out

def get(sections, name):
    for s in sections:
        if s[0] == name:
            return s
    s = [name, []]
    sections.insert(0, s)
    return s

def setkv(sec, key, value):
    for kv in sec[1]:
        if kv[0] == key:
            old = kv[1]
            kv[1] = value
            return old
    sec[1].append([key, value])
    return None

def delkv(sec, key):
    sec[1] = [kv for kv in sec[1] if kv[0] != key]

sections = parse(saved_lines)
main = get(sections, "main")

if mode == "install":
    state = {}
    if os.path.exists(state_path):
        state = json.load(open(state_path))
    if "prev_theme" not in state:
        cur = dict(main[1]).get("theme")
        state["prev_theme"] = cur if cur != "neon" else None
        state["had_addons"] = dict(main[1]).get("enable_addons")
    setkv(main, "theme", "neon")
    setkv(main, "enable_addons", "True")
    user = user.rstrip("\n") + "\n\n" + MENU + "\n\n"
    json.dump(state, open(state_path, "w"))
else:
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    if state.get("prev_theme"):
        setkv(main, "theme", state["prev_theme"])
    else:
        delkv(main, "theme")
    if state.get("had_addons") is None:
        delkv(main, "enable_addons")
    else:
        setkv(main, "enable_addons", state["had_addons"])
    user = user.rstrip("\n") + "\n\n"

out = [user.rstrip("\n") + "\n", MARK, "#~#"]
for name, kvs in sections:
    if not kvs:
        continue
    out.append(f"#~# [{name}]")
    out += [f"#~# {k} = {v}" for k, v in kvs]
    out.append("#~#")
open(conf, "w").write("\n".join(out) + "\n")
print("KlipperScreen.conf updated")
PY
}

restart_ks() {
    [[ "$NO_RESTART" == "1" ]] && return 0
    c_info "Restarting KlipperScreen..."
    if curl -fs -X POST "$MOONRAKER/machine/services/restart?service=KlipperScreen" >/dev/null 2>&1; then
        c_ok "KlipperScreen restarted"
    elif sudo systemctl restart KlipperScreen; then
        c_ok "KlipperScreen restarted"
    else
        c_err "Could not restart KlipperScreen. Restart it from Mainsail (Power menu > Services)."
    fi
}

install() {
    check
    mkdir -p "$BACKUP_ROOT"
    backup
    rm -rf "$KS_DIR/styles/neon" "$KS_DIR/addons/neon_monitor"
    mkdir -p "$KS_DIR/styles" "$KS_DIR/addons"
    cp -a "$SRC/styles/neon" "$KS_DIR/styles/neon"
    cp -a "$SRC/addons/neon_monitor" "$KS_DIR/addons/neon_monitor"
    # spare copy of the theme inside the add-on (addons/ survives updates)
    cp -a "$SRC/styles/neon" "$KS_DIR/addons/neon_monitor/theme"
    find "$KS_DIR/addons/neon_monitor" -name '__pycache__' -prune -exec rm -rf {} +
    c_ok "Theme copied to $KS_DIR/styles/neon ($(ls "$KS_DIR/styles/neon/images" | wc -l) icons)"
    c_ok "Monitor add-on copied to $KS_DIR/addons/neon_monitor"
    edit_conf install
    restart_ks
    c_ok "Done. Theme: Neon. Print monitor: on. Main menu: new 'Monitor' button."
}

uninstall() {
    check
    backup
    rm -rf "$KS_DIR/styles/neon" "$KS_DIR/addons/neon_monitor"
    edit_conf uninstall
    rm -f "$STATE"
    restart_ks
    c_ok "Neon removed. Previous theme restored. Backups kept in $BACKUP_ROOT"
}

case "${1:-}" in
    --uninstall|-u) uninstall ;;
    ""|--install) install ;;
    *) echo "usage: bash install.sh [--uninstall]"; exit 2 ;;
esac
