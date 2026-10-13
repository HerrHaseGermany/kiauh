"""Installation recipes for the HerrHaseGermany printer.

Moonraker's install_script is an *update* hook, not necessarily a complete
installer (Crowsnest is an example). Keep initial installation recipes explicit.
"""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from pathlib import Path

BACKUP_REPO = "https://github.com/HerrHaseGermany/KlipperBackup.git"
PROFILE_CONFIG = Path(__file__).parent / "assets/moonraker_update_manager.cfg"


@dataclass(frozen=True)
class Recipe:
    origin: str
    commands: tuple[tuple[str, ...], ...]
    service: str = ""


RECIPES = {
    "crowsnest": Recipe(
        "mainsail-crew/crowsnest", (("sudo", "make", "install"),), "crowsnest"
    ),
    "sonar": Recipe(
        "mainsail-crew/sonar",
        (("make", "config"), ("sudo", "make", "install")),
        "sonar",
    ),
    "timelapse": Recipe("mainsail-crew/moonraker-timelapse", (("make", "install"),)),
    "KlipperScreen": Recipe(
        "KlipperScreen/KlipperScreen",
        (("bash", "scripts/KlipperScreen-install.sh"),),
        "KlipperScreen",
    ),
    "klipper-backup": Recipe(
        "Staubgeborener/klipper-backup", (("bash", "install.sh"),)
    ),
    "KlipperLCD": Recipe(
        "HerrHaseGermany/Artillery-KlipperLCD",
        (("sudo", "bash", "install.sh"),),
        "KlipperLCD",
    ),
    "KlipperCameraControl": Recipe(
        "HerrHaseGermany/KlipperCameraControl", (("bash", "install.sh"),)
    ),
    "KlipperPLR": Recipe("HerrHaseGermany/KlipperPLR", (("bash", "install.sh"),)),
    "klipper-calibration-wizard": Recipe(
        "HerrHaseGermany/Calibration-Wizard",
        (("bash", "install.sh"),),
        "klipper-calibration-wizard",
    ),
}


def repository_id(url: str) -> str:
    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            return re.sub(r"\.git$", "", url[len(prefix) :]).lower()
    raise ValueError(f"Unsupported repository URL: {url}")


def read_profile(
    path: Path = PROFILE_CONFIG, home: Path | None = None
) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser(
        interpolation=None, inline_comment_prefixes=("#", ";")
    )
    with path.open() as handle:
        parser.read_file(handle)
    entries = {
        section.split(" ", 1)[1]: dict(parser[section])
        for section in parser.sections()
        if section.startswith("update_manager ")
    }
    if not entries:
        raise ValueError("No update manager entries found in printer profile.")
    for name, entry in entries.items():
        expected_type = "web" if name == "mainsail" else "git_repo"
        if entry.get("type") != expected_type:
            raise ValueError(f"Unsupported update manager type for {name}.")
        if name in ("mainsail", "mainsail-config"):
            expected = "mainsail-crew/" + name
            actual = (
                entry.get("repo", "")
                if name == "mainsail"
                else repository_id(entry.get("origin", ""))
            )
        elif name in RECIPES:
            expected = RECIPES[name].origin.lower()
            actual = repository_id(entry.get("origin", ""))
        else:
            raise ValueError(f"No installation recipe for update manager '{name}'.")
        if actual.lower() != expected.lower():
            raise ValueError(f"Unexpected repository for {name}: {actual}")
        target = entry.get("path", "")
        if target not in (
            f"~/{Path(target).name}",
            f"/home/biqu/{Path(target).name}",
            str((home or Path.home()) / Path(target).name),
        ) or Path(target).name in ("", ".", ".."):
            raise ValueError(f"Unsupported installation path for {name}: {target}")
    return entries
