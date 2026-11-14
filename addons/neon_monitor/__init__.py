"""Neon Monitor add-on for KlipperScreen.

Replaces the print status screen (job_status) with the Neon print monitor,
without touching any file tracked by the KlipperScreen git repository.

Turn it off without uninstalling by adding to KlipperScreen.conf:

    [main]
    neon_monitor = False

The original screen stays reachable as the panel "job_status_classic".
"""

import logging
import os
import shutil
from importlib import import_module

PANEL_MODULE = "ks_addons.neon_monitor.panel"


def init(screen):
    try:
        _protect_theme(screen)
    except Exception:
        logging.exception("Neon Monitor: theme protection failed")

    enabled = screen._config.get_main_config().getboolean("neon_monitor", fallback=True)
    if not enabled:
        logging.info("Neon Monitor: disabled by neon_monitor = False")
        return

    original_load = screen._load_panel
    panels_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "panels")

    def load_panel(panel):
        if panel == "job_status":
            try:
                return import_module(PANEL_MODULE)
            except Exception:
                logging.exception("Neon Monitor: failed to load, falling back to stock job_status")
                return original_load(panel)
        if panel == "job_status_classic" and not os.path.exists(
            os.path.join(panels_dir, "job_status_classic.py")
        ):
            return original_load("job_status")
        return original_load(panel)

    screen._load_panel = load_panel
    logging.info("Neon Monitor: print status screen replaced")

    if screen._config.get_main_config().getboolean("neon_compact_temps", fallback=True):
        _compact_main_menu_temps()


def _compact_main_menu_temps():
    """Main menu: size the temperature list to fit all rows (no scrollbar);
    the graph below takes whatever height is left."""
    try:
        from gi.repository import Gtk
        from panels import main_menu
    except Exception:
        logging.exception("Neon Monitor: main menu patch skipped")
        return
    original = main_menu.Panel.create_left_panel
    if getattr(original, "_neon", False):
        return

    def create_left_panel(self):
        left = original(self)
        for child in left.get_children():
            if isinstance(child, Gtk.ScrolledWindow):
                child.set_propagate_natural_height(True)
                child.set_vexpand(False)
                child.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        return left

    create_left_panel._neon = True
    main_menu.Panel.create_left_panel = create_left_panel
    logging.info("Neon Monitor: compact temperature list on main menu")


def _protect_theme(screen):
    """Keep the Neon theme after a KlipperScreen update.

    - styles/neon missing or incomplete (update, `git clean`, reinstall):
      restore it from the copy kept inside this add-on (addons/ is gitignored,
      so updates never delete it).
    - theme switched away from neon: switch back, unless
      `neon_lock_theme: False` is set under [main] in KlipperScreen.conf.
    """
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    ks_dir = os.path.dirname(os.path.dirname(addon_dir))
    backup = os.path.join(addon_dir, "theme")
    target = os.path.join(ks_dir, "styles", "neon")
    if os.path.isdir(backup):
        want = set(_files(backup))
        have = set(_files(target)) if os.path.isdir(target) else set()
        if not want <= have:
            shutil.copytree(backup, target, dirs_exist_ok=True)
            logging.info(f"Neon Monitor: restored theme files ({len(want - have)} missing)")
            if screen.theme == "neon":
                screen.change_theme("neon")

    main = screen._config.get_main_config()
    if not main.getboolean("neon_lock_theme", fallback=True):
        return
    if main.get("theme", "") != "neon" and os.path.isdir(target):
        logging.info(f"Neon Monitor: theme was '{main.get('theme', '')}', locking back to neon")
        screen._config.set("main", "theme", "neon")
        screen._config.save_user_config_options()
        screen.theme = "neon"
        screen.change_theme("neon")


def _files(root):
    for base, _dirs, names in os.walk(root):
        for n in names:
            yield os.path.relpath(os.path.join(base, n), root)
