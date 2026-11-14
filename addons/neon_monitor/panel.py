# -*- coding: utf-8 -*-
"""Neon print monitor for KlipperScreen.

Subclass of the stock job_status panel: every piece of print logic (state
machine, pause / resume / cancel, time estimates, thumbnails, z-offset save)
stays in the stock code. This class only builds a different layout and adds
a few live indicators read straight from Moonraker / Klipper.

Every value shown comes from the printer. Missing sensors show "N/A".
"""
import logging
import math
import os
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from ks_includes.KlippyGtk import find_widget
from panels.job_status import Panel as StockPanel


# ---------------------------------------------------------------- colours
ORANGE = (1.00, 0.64, 0.11)
CYAN = (0.22, 0.78, 1.00)
BLUE = (0.18, 0.48, 1.00)
GREEN = (0.24, 0.92, 0.43)
PURPLE = (0.70, 0.40, 1.00)
AMBER = (1.00, 0.76, 0.20)
RED = (1.00, 0.24, 0.29)
TRACK = (0.10, 0.17, 0.32)

STATE_TEXT = {
    "printing": ("Printing…", CYAN),
    "paused": ("Paused", AMBER),
    "complete": ("Complete", GREEN),
    "cancelled": ("Cancelled", RED),
    "cancelling": ("Cancelling…", AMBER),
    "error": ("Error", RED),
    "standby": ("Ready", CYAN),
}

CSS = b"""
.neon-root { margin: 4px 6px 2px 6px; }
.neon-card {
    background-image: linear-gradient(to bottom, #0E1D40, #091430);
    border: 1px solid rgba(56, 200, 255, 0.45);
    border-radius: 12px;
    box-shadow: 0 0 8px rgba(47, 123, 255, 0.30), inset 0 0 12px rgba(56, 160, 255, 0.08);
    padding: 4px 8px;
}
button.neon-press {
    background-image: none;
    background-color: transparent;
    border: 0;
    box-shadow: none;
    margin: 0;
    padding: 0;
}
button.neon-press:active .neon-card,
button.neon-press:active.neon-card {
    border-color: #38C8FF;
    box-shadow: 0 0 14px rgba(56, 200, 255, 0.85);
}
.neon-filename { font-size: 1.05em; font-weight: bold; color: #FFFFFF; }
.neon-muted { color: #8FA8CC; font-size: 0.8em; }
.neon-small { color: #C9DCF5; font-size: 0.8em; }
.neon-pct { font-size: 2.4em; font-weight: bold; color: #FFFFFF; }
.neon-pct-unit { font-size: 1.1em; font-weight: bold; color: #FFFFFF; }
.neon-time { font-size: 1.0em; font-weight: bold; color: #FFFFFF; }
.neon-temp-name { font-size: 0.8em; font-weight: bold; color: #E6F1FF; }
.neon-temp-val { font-size: 1.35em; font-weight: bold; }
.neon-orange { color: #FFA41B; }
.neon-cyan { color: #38C8FF; }
.neon-purple { color: #B266FF; }
.neon-green { color: #3DEB6E; }
.neon-amber { color: #FFC233; }
.neon-red { color: #FF3D4A; }
.neon-tile-title { font-size: 0.72em; color: #C9DCF5; }
.neon-tile-val { font-size: 1.05em; font-weight: bold; color: #FFFFFF; }
.neon-tile-sub { font-size: 0.65em; color: #8FA8CC; }
.neon-thumb, .neon-thumb:active {
    background-image: none;
    background-color: transparent;
    border: 0;
    box-shadow: none;
    margin: 0;
    padding: 0;
}
.neon-buttons button {
    margin: 3px 4px;
    border-radius: 12px;
    padding: 0 6px;
    font-weight: bold;
    border: 1px solid rgba(56, 200, 255, 0.55);
    background-image: linear-gradient(to bottom, #12295C, #0A1735);
    box-shadow: 0 0 8px rgba(56, 160, 255, 0.35);
}
.neon-buttons button.neon-btn-blue {
    background-image: linear-gradient(to bottom, #2E7BFF, #1449C2);
    border-color: #6FB7FF;
    box-shadow: 0 0 10px rgba(47, 123, 255, 0.7);
}
.neon-buttons button.neon-btn-red {
    background-image: linear-gradient(to bottom, #F0303D, #A5121C);
    border-color: #FF7A84;
    box-shadow: 0 0 10px rgba(255, 61, 74, 0.7);
}
.neon-buttons button.neon-btn-green {
    background-image: linear-gradient(to bottom, #20B85A, #0E7A39);
    border-color: #7DF2A5;
    box-shadow: 0 0 10px rgba(61, 235, 110, 0.6);
}
.neon-buttons button:active {
    box-shadow: 0 0 16px rgba(56, 200, 255, 1.0);
}
.neon-buttons button:disabled {
    background-image: none;
    background-color: #0A1224;
    border-color: #1A2A48;
    box-shadow: none;
}
.neon-buttons button label { font-size: 1.0em; color: #FFFFFF; }
.neon-idle .neon-tile-val { font-size: 1.3em; }
.neon-idle .neon-tile-sub { font-size: 0.72em; }
button.neon-side label { font-size: 0.7em; font-weight: bold; }
"""

_css_loaded = False


def _load_css():
    global _css_loaded
    if _css_loaded:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
    )
    _css_loaded = True


def hms(seconds):
    if seconds is None or seconds < 0:
        return "--:--:--"
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def pretty(name):
    name = name.split(" ", 1)[-1] if " " in name else name
    return name.replace("_", " ").strip().title().replace("Mcu", "MCU").replace("Pi", "Pi")


def rounded_rect(ctx, x, y, w, h, r):
    r = min(r, h / 2, w / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


class Bar(Gtk.DrawingArea):
    """Thin rounded neon bar."""

    def __init__(self, color, height):
        super().__init__()
        self.fraction = 0.0
        self.color = color
        self.set_size_request(-1, height)
        self.connect("draw", self._draw)

    def set(self, fraction, color=None):
        fraction = 0.0 if fraction is None else max(0.0, min(1.0, fraction))
        if color:
            self.color = color
        if abs(fraction - self.fraction) > 0.001 or color:
            self.fraction = fraction
            self.queue_draw()

    def _draw(self, da, ctx):
        w = da.get_allocated_width()
        h = da.get_allocated_height()
        ctx.set_source_rgb(*TRACK)
        rounded_rect(ctx, 0, 0, w, h, h / 2)
        ctx.fill()
        if self.fraction > 0:
            fw = max(h, w * self.fraction)
            ctx.set_source_rgba(*self.color, 0.35)
            rounded_rect(ctx, 0, 0, fw, h, h / 2)
            ctx.fill()
            ctx.set_source_rgb(*self.color)
            rounded_rect(ctx, 0, h * 0.15, fw, h * 0.7, h * 0.35)
            ctx.fill()


class Panel(StockPanel):
    def __init__(self, screen, title):
        super().__init__(screen, title)
        self.neon = {}
        self._neon_remaining = None
        self._neon_timer = None
        self._cpu = None
        self._cpu_temp = None
        self._thumb_ok = False
        self._thumb_tries = 0
        if self._screen.vertical_mode:
            logging.info("Neon Monitor: vertical mode, keeping stock layout")
            self.neon_enabled = False
            return
        self.neon_enabled = True
        _load_css()
        try:
            self._build()
        except Exception:
            logging.exception("Neon Monitor: build failed, keeping stock layout")
            self.neon_enabled = False

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _take(widget):
        parent = widget.get_parent()
        if parent is not None:
            parent.remove(widget)
        return widget

    def _label(self, text="", css=None, xalign=0.0, ellipsize=True):
        lbl = Gtk.Label(label=text, xalign=xalign)
        if ellipsize:
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
        if css:
            for c in css.split():
                lbl.get_style_context().add_class(c)
        return lbl

    def _card(self, child, orientation=Gtk.Orientation.VERTICAL):
        box = Gtk.Box(orientation=orientation, spacing=2)
        box.get_style_context().add_class("neon-card")
        box.add(child) if child is not None else None
        return box

    def _pressable(self, card, panel, extra=None):
        btn = Gtk.Button(relief=Gtk.ReliefStyle.NONE, hexpand=True, vexpand=True)
        btn.get_style_context().add_class("neon-press")
        btn.add(card)
        item = {"panel": panel}
        if extra:
            item["extra"] = extra
        btn.connect("clicked", self.menu_item_clicked, item)
        btn.connect("clicked", self._screen.screensaver.reset_timeout)
        return btn

    # ------------------------------------------------------------ layout
    def _build(self):
        fs = self._gtk.font_size
        cw = self._gtk.content_width
        ch = self._gtk.content_height
        self.content.remove(self.grid)

        root = Gtk.Grid(row_spacing=6, column_spacing=6, hexpand=True, vexpand=True,
                        column_homogeneous=True)
        root.get_style_context().add_class("neon-root")

        btn_h = int(ch * 0.15)
        tile_h = int(ch * 0.205)
        top_h = ch - btn_h - tile_h - 22
        col0_w = int((cw - 24) * 0.40)
        self._thumb_size = (max(col0_w - 24, 60), max(top_h - fs * 2.6 - 16, 60))

        # ---- job card
        file_icon = self._gtk.Image("file", fs * 1.7, fs * 1.7)
        fname = self._take(self.labels["file"])
        fname.get_style_context().add_class("neon-filename")
        fname.set_xalign(0)
        self.neon["layer"] = self._label("Layer - / -", "neon-small")
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        txt.add(fname)
        txt.add(self.neon["layer"])
        lcd = self._take(self.labels["lcdmessage"])
        lcd.get_style_context().add_class("neon-muted")
        txt.add(lcd)
        head = Gtk.Box(spacing=6)
        head.add(file_icon)
        head.add(txt)
        thumb = self._take(self.labels["thumbnail"])
        thumb.get_style_context().remove_class("printing-thumbnail")
        thumb.get_style_context().add_class("neon-thumb")
        thumb.set_hexpand(True)
        thumb.set_vexpand(True)
        job = self._card(head)
        job.pack_start(thumb, True, True, 0)
        job.set_size_request(-1, top_h)
        root.attach(job, 0, 0, 8, 1)

        # ---- progress card
        self.neon["ring"] = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.neon["ring"].connect("draw", self._draw_ring)
        self.neon["pct"] = self._label("0", "neon-pct", 1.0, False)
        unit = self._label("%", "neon-pct-unit", 0.0, False)
        unit.set_valign(Gtk.Align.START)
        unit.set_margin_top(int(fs * 0.55))
        pct_row = Gtk.Box(halign=Gtk.Align.CENTER)
        pct_row.add(self.neon["pct"])
        pct_row.add(unit)
        self.neon["state"] = self._label("", "neon-small", 0.5)
        center = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER
        )
        center.add(pct_row)
        center.add(self.neon["state"])
        overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        overlay.add(self.neon["ring"])
        overlay.add_overlay(center)

        times = Gtk.Grid(column_homogeneous=True, column_spacing=4)
        for col, (key, icon, name) in enumerate(
            [("elapsed", "clock", "Elapsed"), ("remain", "hourglass", "Remain")]
        ):
            hb = Gtk.Box(spacing=3, halign=Gtk.Align.CENTER)
            hb.add(self._gtk.Image(icon, fs * 1.0, fs * 1.0))
            hb.add(self._label(name, "neon-small", 0.5, False))
            times.attach(hb, col, 0, 1, 1)
            self.neon[key] = self._label("--:--:--", "neon-time", 0.5)
            times.attach(self.neon[key], col, 1, 1, 1)
        self.neon["finish"] = self._label("", "neon-muted", 0.5)
        prog = self._card(overlay)
        prog.add(times)
        prog.add(self.neon["finish"])
        root.attach(prog, 8, 0, 6, 1)

        # ---- temperatures
        temps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        self.neon["temps"] = []
        for dev, name, icon, color, css in self._pick_temp_devices():
            temps.pack_start(self._temp_card(dev, name, icon, color, css), True, True, 0)
        root.attach(temps, 14, 0, 6, 1)

        # ---- indicator tiles
        tiles = Gtk.Box(spacing=5, homogeneous=True, vexpand=True)
        tiles.set_size_request(-1, tile_h)
        self.neon["tiles"] = {}
        for key, icon, title, color, panel in self._pick_tiles():
            tiles.pack_start(self._tile(key, icon, title, color, panel), True, True, 0)
        root.attach(tiles, 0, 1, 20, 1)

        # ---- control buttons (stock buttons, restyled)
        self._restyle_buttons()
        bgrid = self._take(self.buttons["button_grid"])
        bgrid.get_style_context().add_class("neon-buttons")
        bgrid.set_size_request(-1, btn_h)
        root.attach(bgrid, 0, 2, 20, 1)
        self.neon["bgrid"] = bgrid
        self.neon["root"] = root

        self.content.add(root)
        self._neon_refresh()
        self._neon_buttons()

    def _restyle_buttons(self):
        size = self._gtk.font_size * 1.5
        styles = {
            "pause": ("pause", "neon-btn-blue"),
            "resume": ("resume", "neon-btn-blue"),
            "cancel": ("stop", "neon-btn-red"),
            "restart": ("refresh", "neon-btn-green"),
            "menu": ("main", None),
            "fine_tune": ("fine-tune", None),
            "control": ("settings", None),
            "save_offset_probe": ("home-z", None),
            "save_offset_endstop": ("home-z", None),
        }
        for key, (icon, css) in styles.items():
            b = self.buttons.get(key)
            if b is None:
                continue
            ctx = b.get_style_context()
            for c in ("color1", "color2", "color3", "color4"):
                ctx.remove_class(c)
            if css:
                ctx.add_class(css)
            b.set_image(self._gtk.Image(icon, size, size))
            b.set_image_position(Gtk.PositionType.LEFT)
            b.set_always_show_image(True)

    # ---------------------------------------------------------- devices
    def _pick_temp_devices(self):
        devs = []
        temp_devices = self._printer.get_temp_devices()
        ext = self.current_extruder or ("extruder" if "extruder" in temp_devices else None)
        if ext:
            devs.append((ext, "Nozzle", "extruder", ORANGE, "neon-orange"))
        if "heater_bed" in temp_devices:
            devs.append(("heater_bed", "Bed", "bed", CYAN, "neon-cyan"))
        others = [d for d in temp_devices if d not in (ext, "heater_bed")]
        third = next((d for d in others if "chamber" in d.lower()), None)
        if third is None:
            third = next((d for d in others if "toolhead" in d.lower()), None)
        if third is None:
            third = next(
                (d for d in others if d != self._mcu_sensor() and d != self._host_sensor()), None
            )
        if third:
            name = "Chamber" if "chamber" in third.lower() else pretty(third)
            devs.append((third, name, "heater", PURPLE, "neon-purple"))
        return devs

    def _mcu_sensor(self):
        sensors = self._printer.get_temp_sensors()
        for s in sensors:
            if s.split(" ", 1)[-1].lower() == "mcu":
                return s
        return next((s for s in sensors if "mcu" in s.lower() and "toolhead" not in s.lower()), None)

    def _host_sensor(self):
        for s in self._printer.get_temp_sensors():
            n = s.lower()
            if any(k in n for k in ("raspberry", "rpi", "host", " pi", "cpu")):
                return s
        return None

    def _pick_tiles(self):
        fans = self._printer.get_fans()
        tiles = []
        if "fan" in fans:
            tiles.append(("fan:fan", "fan", "Part Fan", CYAN, "fan"))
        hotend = next((f for f in fans if f.startswith("heater_fan")), None)
        if hotend:
            tiles.append((f"fan:{hotend}", "fan", "Hotend", BLUE, "fan"))
        if len(tiles) < 2:
            other = next((f for f in fans if f != "fan" and f != hotend), None)
            if other:
                tiles.append((f"fan:{other}", "fan", pretty(other), BLUE, "fan"))
        tiles += [
            ("speed", "speed+", "Speed", GREEN, "fine_tune"),
            ("flow", "flow+", "Flow", PURPLE, "fine_tune"),
            ("filament", "filament", "Filament", CYAN, "extrude"),
            ("mcu", "klipper", "MCU", GREEN, "system"),
            ("host", "printer", "CPU", GREEN, "system"),
        ]
        return tiles

    # ------------------------------------------------------------ widgets
    def _temp_card(self, dev, name, icon, color, css):
        fs = self._gtk.font_size
        gauge = Gtk.DrawingArea()
        gauge.set_size_request(int(fs * 3.4), -1)
        gauge.connect("draw", self._draw_gauge, dev, color)
        img = self._gtk.Image(icon, fs * 1.6, fs * 1.6)
        g_ov = Gtk.Overlay()
        g_ov.add(gauge)
        img.set_halign(Gtk.Align.CENTER)
        img.set_valign(Gtk.Align.CENTER)
        g_ov.add_overlay(img)
        g_ov.set_overlay_pass_through(img, True)

        spark = Gtk.DrawingArea(hexpand=True, vexpand=True)
        spark.connect("draw", self._draw_spark, dev, color)
        lab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        top = Gtk.Box(spacing=4)
        top.pack_start(self._label(name, "neon-temp-name"), True, True, 0)
        sub = self._label("", "neon-muted", 1.0)
        top.pack_end(sub, False, False, 0)
        val = self._label("--°C", f"neon-temp-val {css}")
        lab.add(top)
        lab.add(val)
        r_ov = Gtk.Overlay(hexpand=True)
        r_ov.add(spark)
        r_ov.add_overlay(lab)
        r_ov.set_overlay_pass_through(lab, True)

        row = Gtk.Box(spacing=6)
        row.add(g_ov)
        row.pack_start(r_ov, True, True, 0)
        card = self._card(row, Gtk.Orientation.HORIZONTAL)
        self.neon["temps"].append(
            {"dev": dev, "val": val, "sub": sub, "gauge": gauge, "spark": spark}
        )
        heater = not dev.startswith("temperature_sensor")
        return self._pressable(card, "temperature", dev if heater else None)

    def _tile(self, key, icon, title, color, panel):
        fs = self._gtk.font_size
        head = Gtk.Box(spacing=3)
        head.add(self._gtk.Image(icon, fs * 1.25, fs * 1.25))
        head.add(self._label(title, "neon-tile-title"))
        val = self._label("N/A", "neon-tile-val", 0.5)
        sub = self._label("", "neon-tile-sub", 0.5)
        bar = Bar(color, max(int(fs * 0.4), 5))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, vexpand=True)
        box.add(head)
        box.pack_start(val, True, True, 0)
        box.add(sub)
        box.add(bar)
        card = self._card(box)
        self.neon["tiles"][key] = {"val": val, "sub": sub, "bar": bar}
        return self._pressable(card, panel)

    # ------------------------------------------------------------ drawing
    def _draw_ring(self, da, ctx):
        w = da.get_allocated_width()
        h = da.get_allocated_height()
        lw = max(self._gtk.font_size * 0.75, 8)
        r = min(w, h) / 2 - lw
        cx, cy = w / 2, h / 2
        start = -math.pi / 2
        ctx.set_line_cap(1)  # round
        ctx.set_line_width(lw)
        ctx.set_source_rgb(*TRACK)
        ctx.arc(cx, cy, r, 0, 2 * math.pi)
        ctx.stroke()
        p = max(0.0, min(1.0, self.progress))
        if p <= 0:
            return
        color = STATE_TEXT.get(self.state, STATE_TEXT["printing"])[1]
        end = start + p * 2 * math.pi
        # glow
        ctx.set_line_width(lw * 1.9)
        ctx.set_source_rgba(*color, 0.18)
        ctx.arc(cx, cy, r, start, end)
        ctx.stroke()
        # main arc: green -> cyan gradient feel via two passes
        ctx.set_line_width(lw)
        ctx.set_source_rgb(*(GREEN if self.state == "printing" else color))
        ctx.arc(cx, cy, r, start, start + p * math.pi)
        ctx.stroke()
        ctx.set_source_rgb(*color)
        ctx.arc(cx, cy, r, start + p * math.pi * 0.9, end)
        ctx.stroke()
        ctx.set_source_rgba(1, 1, 1, 0.55)
        ctx.set_line_width(lw * 0.18)
        ctx.arc(cx, cy, r, start, end)
        ctx.stroke()

    def _temp_values(self, dev):
        temp = self._printer.get_stat(dev, "temperature")
        target = self._printer.get_stat(dev, "target")
        return (
            float(temp) if isinstance(temp, (int, float)) else None,
            float(target) if isinstance(target, (int, float)) else None,
        )

    def _max_temp(self, dev):
        try:
            return float(self._printer.get_config_section(dev).get("max_temp", 0)) or 100.0
        except Exception:
            return 100.0

    def _draw_gauge(self, da, ctx, dev, color):
        w = da.get_allocated_width()
        h = da.get_allocated_height()
        lw = max(self._gtk.font_size * 0.28, 3)
        r = min(w, h) / 2 - lw * 1.2
        cx, cy = w / 2, h / 2
        a0, span = 0.75 * math.pi, 1.5 * math.pi
        ctx.set_line_cap(1)
        ctx.set_line_width(lw)
        ctx.set_source_rgb(*TRACK)
        ctx.arc(cx, cy, r, a0, a0 + span)
        ctx.stroke()
        temp, target = self._temp_values(dev)
        if temp is None:
            return
        frac = max(0.0, min(1.0, temp / self._max_temp(dev)))
        ctx.set_line_width(lw * 2.0)
        ctx.set_source_rgba(*color, 0.22)
        ctx.arc(cx, cy, r, a0, a0 + span * frac)
        ctx.stroke()
        ctx.set_line_width(lw)
        ctx.set_source_rgb(*color)
        ctx.arc(cx, cy, r, a0, a0 + span * max(frac, 0.01))
        ctx.stroke()
        if target:
            ta = a0 + span * max(0.0, min(1.0, target / self._max_temp(dev)))
            ctx.set_source_rgb(1, 1, 1)
            ctx.set_line_width(lw * 0.5)
            ctx.move_to(cx + (r - lw) * math.cos(ta), cy + (r - lw) * math.sin(ta))
            ctx.line_to(cx + (r + lw) * math.cos(ta), cy + (r + lw) * math.sin(ta))
            ctx.stroke()

    def _draw_spark(self, da, ctx, dev, color):
        raw = self._printer.get_temp_store(dev, "temperatures", 300)
        if not raw or len(raw) < 6:
            return
        step = 5
        temps = [sum(raw[i : i + step]) / len(raw[i : i + step]) for i in range(0, len(raw), step)]
        w = da.get_allocated_width()
        h = da.get_allocated_height()
        top = h * 0.70
        bottom = h - 3
        lo, hi = min(temps), max(temps)
        span = 20 if dev.startswith(("extruder", "heater")) else 8
        if hi - lo < span:
            mid = (hi + lo) / 2
            lo, hi = mid - span / 2, mid + span / 2
        n = len(temps)

        def pt(i, v):
            return (w * i / (n - 1), bottom - (v - lo) / (hi - lo) * (bottom - top))

        ctx.move_to(*pt(0, temps[0]))
        for i, v in enumerate(temps[1:], 1):
            ctx.line_to(*pt(i, v))
        path = ctx.copy_path()
        ctx.line_to(w, h)
        ctx.line_to(0, h)
        ctx.close_path()
        ctx.set_source_rgba(*color, 0.12)
        ctx.fill()
        ctx.new_path()
        ctx.append_path(path)
        ctx.set_source_rgba(*color, 0.35)
        ctx.set_line_width(4)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*color)
        ctx.set_line_width(1.6)
        ctx.stroke()

    # ------------------------------------------------------------ updates
    def format_eta(self, total, elapsed):
        # stock update_time_left() calls this with its best estimate
        if total is not None:
            self._neon_remaining = max(total - elapsed, 0)
        return super().format_eta(total, elapsed)

    def update_progress(self, progress: float):
        super().update_progress(progress)
        if getattr(self, "neon_enabled", False) and "pct" in self.neon:
            self.neon["pct"].set_label(f"{math.trunc(progress * 100)}")
            self.neon["ring"].queue_draw()

    def show_buttons_for_state(self):
        super().show_buttons_for_state()
        if getattr(self, "neon_enabled", False) and "bgrid" in self.neon:
            self._neon_buttons()

    def _neon_buttons(self):
        """Bottom row only while a print runs. After a print ends (complete,
        cancelled, error) or with nothing loaded, Main Menu and Restart move to
        the side bar and the tiles take the free space."""
        active = self.state in ("printing", "paused", "cancelling")
        bgrid = self.neon["bgrid"]
        ctx = self.neon["root"].get_style_context()
        if active:
            ctx.remove_class("neon-idle")
            bgrid.set_no_show_all(False)
            bgrid.show_all()
            self.neon["finish"].show()
        else:
            ctx.add_class("neon-idle")
            bgrid.set_no_show_all(True)
            bgrid.hide()
            self.neon["finish"].hide()
        self._side_buttons(not active)

    # ---------------------------------------------------------- side bar
    def _side_buttons(self, show):
        """Main Menu + Restart in KlipperScreen's left action bar."""
        bp = self._screen.base_panel
        side = getattr(bp, "_neon_side", None)
        if side is None:
            if not show:
                return
            side = {}
            scale = getattr(bp, "abscale", self._gtk.bsidescale * 1.1)
            for key, icon, text in (
                ("menu", "main", _("Main Menu")),
                ("restart", "refresh", _("Restart")),
            ):
                b = self._gtk.Button(icon, text, None, scale, Gtk.PositionType.TOP, 1)
                b.get_style_context().add_class("neon-side")
                b.set_no_show_all(True)
                b.connect("clicked", self._side_clicked, key)
                bp.action_bar.add(b)
                side[key] = b
            bp._neon_side = side
            bp._neon_owner = self
            # first in the bar
            bp.action_bar.reorder_child(side["restart"], 0)
            bp.action_bar.reorder_child(side["menu"], 0)
        bp._neon_owner = self
        stock = [bp.control.get("back"), bp.control.get("home")]
        if show:
            for w in stock:
                if w is not None:
                    w.set_no_show_all(True)
                    w.hide()
            want = {"menu": True, "restart": bool(self.filename)}
        else:
            want = {"menu": False, "restart": False}
        for key, visible in want.items():
            b = side[key]
            if visible:
                b.set_no_show_all(False)
                b.show_all()
            else:
                b.set_no_show_all(True)
                b.hide()
        if not show:
            for w in stock:
                if w is not None:
                    w.set_no_show_all(False)
                    w.show()

    def _side_clicked(self, widget, key):
        owner = getattr(self._screen.base_panel, "_neon_owner", None) or self
        self._screen.screensaver.reset_timeout(widget)
        if key == "menu":
            owner.can_close = True
            owner.close_panel()
        elif key == "restart" and owner.filename:
            owner.restart(widget)

    def show_file_thumbnail(self):
        if not getattr(self, "neon_enabled", False) or not hasattr(self, "_thumb_size"):
            return super().show_file_thumbnail()
        if not self.filename:
            return self._show_logo()
        w, h = self._thumb_size
        self._thumb_tries += 1
        self._neon_load_thumbnail(self.filename, int(w), int(h))

    def _neon_load_thumbnail(self, filename, w, h):
        """Load the print photo directly.

        KlipperScreen's shared image queue is also used by the Print (files)
        page, which queues a thumbnail for every file; on the Pi our one image
        waited behind that queue for about a minute. A local file is read
        right here (a few ms), a remote one on a private thread.
        """
        if not self._files.has_thumbnail(filename):
            return
        loc = self._files.get_thumbnail_location(filename)
        if loc is None:
            return
        if loc[0] == "file":
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(loc[1], w, h, True)
            except Exception as e:
                logging.error(f"Neon Monitor: cannot read thumbnail {loc[1]}: {e}")
                pixbuf = None
            self._neon_set_thumbnail(pixbuf)
            return

        def fetch():
            pixbuf = None
            try:
                import requests

                url = f"{self._screen.moonraker_endpoint}/server/files/gcodes/{loc[1]}"
                key = self._screen.moonraker_api_key
                resp = requests.get(url, headers={"x-api-key": key} if key else {}, timeout=5)
                resp.raise_for_status()
                stream = Gio.MemoryInputStream.new_from_data(resp.content, None)
                pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, w, h, True, None)
            except Exception as e:
                logging.error(f"Neon Monitor: cannot fetch thumbnail {loc[1]}: {e}")
            GLib.idle_add(self._neon_set_thumbnail, pixbuf)

        threading.Thread(target=fetch, daemon=True).start()

    def _neon_set_thumbnail(self, pixbuf):
        if pixbuf is None:
            logging.info(f"Neon Monitor: no thumbnail yet for {self.filename}")
            return False
        if not self.content.get_parent():
            return False
        image = find_widget(self.labels["thumbnail"], Gtk.Image)
        if image:
            image.set_from_pixbuf(pixbuf)
            if not self._thumb_ok:
                logging.info(
                    f"Neon Monitor: thumbnail shown for {self.filename} "
                    f"({pixbuf.get_width()}x{pixbuf.get_height()}, try {self._thumb_tries})"
                )
            self._thumb_ok = True
        return False

    def update_filename(self, filename):
        if filename and filename != self.filename:
            self._thumb_ok = False
            self._thumb_tries = 0
        super().update_filename(filename)

    def show_fullscreen_thumbnail(self, widget):
        """Tap on the photo box: while printing, show the photo full screen
        (stock); otherwise open the file list, same as Print on the main menu."""
        if getattr(self, "neon_enabled", False) and self.state not in (
            "printing",
            "paused",
            "cancelling",
        ):
            self.menu_item_clicked(widget, {"panel": "gcodes", "name": _("Print")})
            return
        super().show_fullscreen_thumbnail(widget)

    def _show_logo(self):
        """No file loaded (standby): show the neon standby emblem."""
        text = _("No print loaded")
        self.filename_label = {"complete": text, "current": text}
        self.labels["file"].set_label(text)
        image = find_widget(self.labels["thumbnail"], Gtk.Image)
        if image is None:
            return
        w, h = self._thumb_size
        size = int(min(w, h) * 0.9)
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standby.svg")
        try:
            image.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True))
        except Exception as e:
            logging.error(f"Neon Monitor: standby image: {e}")

    def process_update(self, action, data):
        super().process_update(action, data)
        if not getattr(self, "neon_enabled", False):
            return
        try:
            if action == "notify_proc_stat_update":
                usage = data.get("system_cpu_usage", {})
                if "cpu" in usage:
                    self._cpu = float(usage["cpu"])
                if data.get("cpu_temp") is not None:
                    self._cpu_temp = float(data["cpu_temp"])
                self._update_host()
            elif action == "notify_status_update":
                self._neon_refresh()
        except Exception:
            logging.exception("Neon Monitor: update failed")

    def activate(self):
        super().activate()
        if getattr(self, "neon_enabled", False):
            if self._neon_timer is None:
                self._neon_timer = GLib.timeout_add_seconds(2, self._tick)
            if self.filename:
                # thumbnail callbacks are dropped while another panel is on top
                self.show_file_thumbnail()
            else:
                self._show_logo()

    def deactivate(self):
        super().deactivate()
        if getattr(self, "neon_enabled", False):
            self._side_buttons(False)
        if self._neon_timer is not None:
            GLib.source_remove(self._neon_timer)
            self._neon_timer = None

    def _tick(self):
        try:
            # metadata can arrive late; retry the print thumbnail for ~1 minute
            if self.filename and not self._thumb_ok and self._thumb_tries < 30:
                self.show_file_thumbnail()
            for t in self.neon.get("temps", []):
                t["spark"].queue_draw()
            self._neon_refresh()
        except Exception:
            logging.exception("Neon Monitor: tick failed")
        return True

    def _neon_refresh(self):
        p = self._printer
        # state + times
        text, _c = STATE_TEXT.get(self.state, (self.state.title(), CYAN))
        self.neon["state"].set_label(text)
        elapsed = p.get_stat("print_stats", "total_duration")
        self.neon["elapsed"].set_label(hms(elapsed) if elapsed else "--:--:--")
        if self.state == "complete":
            self.neon["remain"].set_label("00:00:00")
            self.neon["finish"].set_label("")
        elif self.state in ("printing", "paused") and self._neon_remaining is not None:
            self.neon["remain"].set_label(hms(self._neon_remaining))
            fin = GLib.DateTime.new_now_local().add_seconds(self._neon_remaining)
            fmt = "%H:%M" if self._config.get_main_config().getboolean("24htime", True) else "%I:%M %p"
            self.neon["finish"].set_label(f"Finish ≈ {fin.format(fmt)}")
        else:
            self.neon["remain"].set_label("--:--:--")
            self.neon["finish"].set_label("")
        self.neon["ring"].queue_draw()
        self._update_layer()
        self._update_temps()
        self._update_tiles()

    def _update_layer(self):
        p = self._printer
        info = p.get_stat("print_stats", "info") or {}
        cur = info.get("current_layer") if isinstance(info, dict) else None
        tot = info.get("total_layer") if isinstance(info, dict) else None
        z = None
        pos = p.get_stat("gcode_move", "gcode_position")
        if pos and len(pos) > 2:
            z = float(pos[2])
        md = self.file_metadata or {}
        lh = md.get("layer_height")
        flh = md.get("first_layer_height") or lh
        if cur is None and lh and z and self.state in ("printing", "paused"):
            cur = max(1, int(round((z - flh) / lh)) + 1)
        if tot is None and lh and md.get("object_height"):
            tot = int(math.ceil((float(md["object_height"]) - flh) / lh)) + 1
        parts = []
        if cur is None and tot is not None and self.state not in ("printing", "paused"):
            parts.append(f"{tot} layers")
        elif cur is not None or tot is not None:
            parts.append(f"Layer {cur if cur is not None else '-'} / {tot if tot is not None else '-'}")
        if z is not None and self.state in ("printing", "paused"):
            parts.append(f"Z {z:.2f} mm")
        elif lh:
            parts.append(f"{lh:.2f} mm")
        if self.state not in ("printing", "paused", "cancelling"):
            parts.append(_("Tap photo to print"))
        self.neon["layer"].set_label("  •  ".join(parts) if parts else " ")

    def _update_temps(self):
        for t in self.neon["temps"]:
            temp, target = self._temp_values(t["dev"])
            t["val"].set_label(f"{temp:.0f}°C" if temp is not None else "N/A")
            ctx = t["sub"].get_style_context()
            for c in ("neon-green", "neon-amber"):
                ctx.remove_class(c)
            if target is None:
                t["sub"].set_label("")
            elif target <= 0:
                t["sub"].set_label("Off")
            else:
                t["sub"].set_label(f"▸ {target:.0f}°C")
                ctx.add_class("neon-green" if temp is not None and abs(temp - target) <= 3 else "neon-amber")
            t["gauge"].queue_draw()

    def _set_tile(self, key, value, sub="", fraction=None, color=None):
        tile = self.neon["tiles"].get(key)
        if tile is None:
            return
        if "<" in value:
            tile["val"].set_markup(value)
        else:
            tile["val"].set_label(value)
        tile["sub"].set_label(sub)
        tile["bar"].set(fraction, color)

    @staticmethod
    def _level_color(value, warn, crit):
        if value is None:
            return None
        return RED if value >= crit else AMBER if value >= warn else GREEN

    def _update_tiles(self):
        p = self._printer
        for key in self.neon["tiles"]:
            if key.startswith("fan:"):
                fan = key[4:]
                spd = p.get_fan_speed(fan)
                spd = float(spd) if isinstance(spd, (int, float)) else None
                self._set_tile(key, f"{spd * 100:.0f}%" if spd is not None else "N/A", "", spd)
        # speed
        # actual = live toolhead velocity, setpoint = G-code feedrate x speed factor
        sf = p.get_stat("gcode_move", "speed_factor")
        feed = p.get_stat("gcode_move", "speed")
        vel = p.get_stat("motion_report", "live_velocity")
        if isinstance(sf, (int, float)):
            act = float(vel) if isinstance(vel, (int, float)) else None
            setp = float(feed) / 60 * sf if isinstance(feed, (int, float)) else None
            if self.state in ("printing", "paused") and act is not None and setp:
                self._set_tile(
                    "speed",
                    f'{act:.0f}<span size="small" weight="normal"> / {setp:.0f}</span>',
                    f"mm/s · {sf * 100:.0f}%",
                    act / setp,
                    GREEN if act >= setp * 0.5 else AMBER,
                )
            else:
                self._set_tile("speed", f"{sf * 100:.0f}%", "speed factor", sf / 1.5)
        # flow
        ef = p.get_stat("gcode_move", "extrude_factor")
        if isinstance(ef, (int, float)):
            sub = f"{self.flowrate:.1f} mm³/s" if self.state == "printing" else ""
            self._set_tile("flow", f"{ef * 100:.0f}%", sub, ef / 1.5)
        # filament
        used = p.get_stat("print_stats", "filament_used")
        used = float(used) if isinstance(used, (int, float)) else 0.0
        md = self.file_metadata or {}
        total = md.get("filament_total")
        frac = used / total if total else None
        sub = ""
        weight = md.get("filament_weight_total")
        if weight and total:
            sub = f"≈ {weight * used / total:.0f} g"
        elif total:
            sub = f"of {total / 1000:.1f} m"
        self._set_tile("filament", f"{used / 1000:.1f} m", sub, frac)
        # mcu
        mcu = self._mcu_sensor()
        if mcu:
            t, _ = self._temp_values(mcu)
            if t is not None:
                self._set_tile("mcu", f"{t:.0f}°C", "", t / 80, self._level_color(t, 55, 70))
        else:
            self._set_tile("mcu", "N/A")
        self._update_host()

    def _update_host(self):
        sensor = self._host_sensor()
        temp = self._cpu_temp
        if temp is None and sensor:
            temp, _ = self._temp_values(sensor)
        sub = f"{temp:.0f}°C" if temp is not None else ""
        if self._cpu is not None:
            self._set_tile(
                "host", f"{self._cpu:.0f}%", sub, self._cpu / 100, self._level_color(self._cpu, 70, 90)
            )
        elif temp is not None:
            self._set_tile("host", f"{temp:.0f}°C", "CPU temp", temp / 85, self._level_color(temp, 65, 78))
