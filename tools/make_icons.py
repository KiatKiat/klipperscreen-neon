#!/usr/bin/env python3
"""Generate the Neon icon set for KlipperScreen.

Every icon KlipperScreen asks for (106 names, same list as the stock themes)
is produced as a neon-tube SVG: a blurred glow, a coloured stroke and a thin
white core. Outline geometry comes from Lucide (ISC licence) or from small
custom drawings below.
"""
import os
import re
import shutil
import sys

LUCIDE = sys.argv[1]
OUT = sys.argv[2]
SPOOL_SRC = sys.argv[3]

CYAN = "#38C8FF"
BLUE = "#4A90FF"
ORANGE = "#FFA41B"
RED = "#FF3D4A"
GREEN = "#3DEB6E"
PURPLE = "#B266FF"
AMBER = "#FFC233"
WHITE = "#DDEFFF"


def lucide(name):
    with open(os.path.join(LUCIDE, f"{name}.svg")) as f:
        svg = f.read()
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    inner = re.sub(r"<!--.*?-->", "", inner, flags=re.S)
    return inner.replace("currentColor", "COLOR").strip()


# --- custom drawings (24x24 grid, stroke only) ---------------------------
NOZZLE = (
    '<rect x="4.5" y="2.5" width="15" height="8" rx="1.2"/>'
    '<path d="M8.5 6.5h7"/><path d="M8 10.5v3.5h8v-3.5"/><path d="M8.5 14h7l-2.6 5.5h-1.8z"/>'
)
BED = (
    '<rect x="3" y="15" width="18" height="4" rx="1"/>'
    '<path d="M8 12c1.2-1.4-1.2-2.6 0-4s-1.2-2.6 0-4"/>'
    '<path d="M12 12c1.2-1.4-1.2-2.6 0-4s-1.2-2.6 0-4"/>'
    '<path d="M16 12c1.2-1.4-1.2-2.6 0-4s-1.2-2.6 0-4"/>'
    '<path d="M6 19v2M18 19v2"/>'
)
PRINTER3D = (
    '<rect x="3" y="2.5" width="18" height="19" rx="2"/>'
    '<path d="M3 7.5h18"/><path d="M10.5 7.5v3h3v-3"/><path d="M11.3 10.5l.7 1.5.7-1.5"/>'
    '<path d="M7 17.5h10"/><path d="M9.5 15.5h5v2h-5z"/>'
)
FRAME = '<rect x="3" y="3" width="18" height="18" rx="2.5"/>'


def text(t, x, y, size, anchor="middle"):
    return (
        f'<text x="{x}" y="{y}" font-family="DejaVu Sans, sans-serif" font-weight="bold" '
        f'font-size="{size}" text-anchor="{anchor}" fill="COLOR" stroke="none">{t}</text>'
    )


def scaled(inner, s, dx=0, dy=0):
    return f'<g transform="translate({dx} {dy}) scale({s})">{inner}</g>'


def badge(sign):
    # small round badge bottom-right with + or -
    d = "M18 15.5v5M15.5 18h5" if sign == "+" else "M15.5 18h5"
    return f'<circle cx="18" cy="18" r="4.6" fill="#0B1424" stroke="COLOR"/><path d="{d}"/>'


def dot(cx, cy):
    return f'<circle cx="{cx}" cy="{cy}" r="2.4" fill="COLOR"/>'


ICONS = {}


def add(name, inner, color):
    ICONS[name] = (inner, color)


# Navigation / generic
for n, l in [
    ("arrow-down", "arrow-down"), ("arrow-up", "arrow-up"),
    ("arrow-left", "arrow-left"), ("arrow-right", "arrow-right"),
]:
    add(n, lucide(l), CYAN)
add("back", lucide("undo-2"), WHITE)
add("home", lucide("house"), WHITE)
add("main", lucide("layout-grid"), CYAN)
add("backspace", lucide("delete"), WHITE)
add("increase", lucide("plus"), GREEN)
add("decrease", lucide("minus"), AMBER)
add("refresh", lucide("refresh-cw"), CYAN)
add("shuffle", lucide("shuffle"), CYAN)
add("info", lucide("info"), CYAN)
add("lock", lucide("lock"), CYAN)
add("edit", lucide("pencil"), CYAN)
add("hashtag", lucide("hash"), CYAN)
add("clock", lucide("clock"), CYAN)
add("hourglass", lucide("hourglass"), CYAN)
add("settings", lucide("settings"), CYAN)
add("fine-tune", lucide("sliders-horizontal"), CYAN)
add("console", lucide("square-terminal"), GREEN)
add("custom-script", lucide("file-code"), GREEN)
add("network", lucide("network"), CYAN)
add("camera", lucide("camera"), CYAN)
add("light", lucide("lightbulb"), AMBER)
add("notifications", lucide("bell"), CYAN)
add("notifications_active", lucide("bell-ring"), AMBER)
add("notifications_important", lucide("bell-dot"), RED)
add("warning", lucide("triangle-alert"), AMBER)
add("klipper", lucide("cpu"), CYAN)
add("printer", PRINTER3D, CYAN)
add("toolchanger", lucide("arrow-right-left"), CYAN)
add("spoolman", lucide("database"), CYAN)
add("sd", lucide("hard-drive"), CYAN)

# Files
add("file", lucide("file"), CYAN)
add("files", lucide("folder-open"), CYAN)
add("folder", lucide("folder"), CYAN)
add("archived", lucide("archive"), CYAN)
add("delete", lucide("trash-2"), RED)

# Job control
add("pause", lucide("pause"), WHITE)
add("resume", lucide("play"), GREEN)
add("stop", lucide("square"), RED)
add("cancel", lucide("circle-x"), RED)
add("complete", lucide("circle-check"), GREEN)
add("emergency", lucide("octagon-alert"), RED)
add("shutdown", lucide("power"), RED)
add("motor-off", lucide("power-off"), AMBER)

# Temperature
add("heater", lucide("thermometer"), ORANGE)
add("heat-up", lucide("flame"), ORANGE)
add("cool-down", lucide("snowflake"), CYAN)
add("bed", BED, BLUE)
add("extruder", NOZZLE, ORANGE)
for i in range(12):
    add(f"extruder-{i}", scaled(NOZZLE, 0.78, -0.5, 0) + text(str(i), 18.5, 22.5, 10 if i < 10 else 8.5), ORANGE)

# Fans
add("fan", lucide("fan"), CYAN)
add("fan-on", lucide("fan"), GREEN)

# Motion
add("move", lucide("move"), CYAN)
add("home-x", scaled(lucide("house"), 0.7, 0, 0) + text("X", 18.5, 22.5, 11), CYAN)
add("home-y", scaled(lucide("house"), 0.7, 0, 0) + text("Y", 18.5, 22.5, 11), CYAN)
add("home-z", scaled(lucide("house"), 0.7, 0, 0) + text("Z", 18.5, 22.5, 11), CYAN)
add("z-closer", lucide("arrow-down-to-line"), CYAN)
add("z-farther", lucide("arrow-up-from-line"), CYAN)
add("z-tilt", lucide("scale"), CYAN)
add("cw", lucide("rotate-cw"), CYAN)
add("ccw", lucide("rotate-ccw"), CYAN)
add("bed-mesh", lucide("grid-3x3"), PURPLE)
add("bed-level", FRAME + '<path d="M7 15l5-6 5 6"/><path d="M7 15h10"/>', PURPLE)
pos = {"t": 7.5, "m": 12, "b": 16.5, "l": 7.5, "r": 16.5}
for n in ["b-l", "b-m", "b-r", "l-m", "r-m", "t-l", "t-m", "t-r"]:
    a, b = n.split("-")
    if n in ("l-m", "r-m"):
        x, y = pos[a], 12
    else:
        y = pos[a]
        x = 12 if b == "m" else pos[b]
    add(f"bed-level-{n}", FRAME + dot(x, y), PURPLE)
add("bed-level-center", FRAME + dot(12, 12), PURPLE)

# Extrusion / filament
add("extrude", scaled(NOZZLE, 0.72, 3.4, -1) + '<path d="M12 15.5v6M9.5 19l2.5 2.5 2.5-2.5"/>', ORANGE)
add("retract", scaled(NOZZLE, 0.72, 3.4, -1) + '<path d="M12 21.5v-6M9.5 18l2.5-2.5 2.5 2.5"/>', CYAN)
add("load", lucide("arrow-down-to-line"), GREEN)
add("filament", lucide("disc-3"), PURPLE)
add("speed+", lucide("gauge") + badge("+"), GREEN)
add("speed-", lucide("gauge") + badge("-"), AMBER)
add("flow+", lucide("droplet") + badge("+"), PURPLE)
add("flow-", lucide("droplet") + badge("-"), PURPLE)

# Wifi / battery
WIFI = ["M12 20h.01", "M8.5 16.429a5 5 0 0 1 7 0", "M5 12.859a10 10 0 0 1 14 0",
        "M2 8.82a15 15 0 0 1 20 0"]


def wifi(level):
    return "".join(
        f'<path d="{d}"{"" if i <= level else " opacity=\'0.22\'"}/>' for i, d in enumerate(WIFI)
    )


add("wifi_excellent", wifi(3), GREEN)
add("wifi_good", wifi(2), GREEN)
add("wifi_fair", wifi(1), AMBER)
add("wifi_weak", wifi(0), RED)
add("battery-0", lucide("battery"), RED)
add("battery-25", lucide("battery-low"), AMBER)
add("battery-50", lucide("battery-medium"), GREEN)
add("battery-75", lucide("battery-medium"), GREEN)
add("battery-100", lucide("battery-full"), GREEN)
add("battery-charging", lucide("battery-charging"), GREEN)
add("battery-unknown", lucide("battery-warning"), AMBER)

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="-3 -3 30 30">
<defs><filter id="glow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="1.15"/></filter></defs>
<g fill="none" stroke-linecap="round" stroke-linejoin="round">
<g stroke="{c}" stroke-width="3.2" opacity="0.8" filter="url(#glow)">{glow}</g>
<g stroke="{c}" stroke-width="2">{main}</g>
<g stroke="#FFFFFF" stroke-width="0.7" opacity="0.55">{core}</g>
</g>
</svg>
"""


def strip_fill(inner):
    # glow/core layers: keep geometry, drop solid fills (dots, badges, text)
    s = re.sub(r'fill="COLOR"', 'fill="none"', inner)
    s = re.sub(r'fill="#0B1424"', 'fill="none"', s)
    s = re.sub(r"<text[^>]*>.*?</text>", "", s)
    return s


def render(inner, color):
    main = inner.replace("COLOR", color)
    glow = inner.replace("COLOR", color).replace('fill="#0B1424"', 'fill="none"')
    core = strip_fill(inner).replace("COLOR", "#FFFFFF")
    return TEMPLATE.format(c=color, glow=glow, main=main, core=core)


os.makedirs(OUT, exist_ok=True)
for name, (inner, color) in ICONS.items():
    with open(os.path.join(OUT, f"{name}.svg"), "w") as f:
        f.write(render(inner, color))
shutil.copy(SPOOL_SRC, os.path.join(OUT, "spool.svg"))
print(len(ICONS) + 1, "icons written")
