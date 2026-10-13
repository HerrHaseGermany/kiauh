"""Menu for recreating the printer described by its Moonraker update manager."""

from __future__ import annotations

import configparser
import platform
import subprocess

from components.printer_profile.profile import BACKUP_REPO, read_profile
from components.printer_profile.service import PrinterProfileService
from core.logger import Logger
from core.menus import Option
from core.menus.base_menu import BaseMenu
from core.types.color import Color
from utils.input_utils import get_confirm, get_string_input


def require_printer_host() -> None:
    if platform.system() != "Linux":
        raise RuntimeError(
            "Run this operation on the Linux printer host as its normal user."
        )
    import os

    if os.geteuid() == 0:
        raise RuntimeError(
            "Run KIAUH as the printer user; installers use sudo when required."
        )


def restore_from_backup(**kwargs) -> None:
    try:
        require_printer_host()
        ref = get_string_input(
            "Backup branch, tag or commit", default="HEAD", allow_special_chars=True
        )
        service = PrinterProfileService()
        with service.backup_checkout(ref) as config:
            Logger.print_info(f"Source: {BACKUP_REPO}, target: {service.config_dir}")
            Logger.print_info(
                "Existing config is backed up before replacement. /home/biqu paths are adapted to the current user."
            )
            if get_confirm("Config aus Backup wiederherstellen?", default_choice=False):
                service.restore_config(config)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        configparser.Error,
    ) as error:
        Logger.print_error(f"Config restore failed: {error}")


class PrinterProfileMenu(BaseMenu):
    def __init__(self, previous_menu: type[BaseMenu] | None = None):
        self.entries = read_profile()
        super().__init__()
        self.title = "HerrHaseGermany Printer Profile"
        self.title_color = Color.GREEN
        self.previous_menu = previous_menu

    def set_previous_menu(self, previous_menu: type[BaseMenu] | None) -> None:
        from core.menus.install_menu import InstallMenu

        self.previous_menu = previous_menu or InstallMenu

    def set_options(self) -> None:
        self.options = {
            "a": Option(method=self.install_all),
            "r": Option(method=restore_from_backup),
            "d": Option(method=self.install_dependencies),
            "h": Option(method=self.install_host_mcu),
        }
        self.options.update(
            {
                str(index): Option(method=self.install_component, opt_data=name)
                for index, name in enumerate(self.entries, 1)
            }
        )

    def print_menu(self) -> None:
        print("╟───────────────────────────────────────────────────────╢")
        for row in [
            "A) Drucker nachbauen (inkl. Klipper + Moonraker)",
            "R) Config aus Backup wiederherstellen",
            "D) KAMP + System-Abhaengigkeiten",
            "H) Linux Host-MCU",
            "",
            *[f"{index}) {name}" for index, name in enumerate(self.entries, 1)],
        ]:
            print(f"║ {row:<53} ║")
        print("╟───────────────────────────────────────────────────────╢")

    def install_all(self, **kwargs) -> None:
        try:
            require_printer_host()
            ref = get_string_input(
                "Backup branch, tag or commit", default="HEAD", allow_special_chars=True
            )
            service = PrinterProfileService()
            with service.backup_checkout(ref) as source:
                entries = read_profile(source / "moonraker_update_manager.cfg")
                Logger.print_info(
                    "Install: Klipper, Moonraker, Linux Host-MCU, KAMP, "
                    + ", ".join(entries)
                )
                Logger.print_info(
                    f"Restore config from {BACKUP_REPO} to {service.config_dir} after installation."
                )
                Logger.print_info(
                    "Third-party installers may ask for hardware settings and backup credentials. Calibration Wizard requires Node.js 20.19+ or 22.12+ and npm."
                )
                if get_confirm(
                    "Druckerprofil installieren und Config wiederherstellen?",
                    default_choice=False,
                ):
                    service.install_all(source)
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
            configparser.Error,
        ) as error:
            Logger.print_error(f"Printer profile installation stopped: {error}")

    def install_component(self, **kwargs) -> None:
        try:
            require_printer_host()
            PrinterProfileService().install_component(kwargs["opt_data"], self.entries)
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
            configparser.Error,
        ) as error:
            Logger.print_error(f"Component installation failed: {error}")

    def install_dependencies(self, **kwargs) -> None:
        try:
            require_printer_host()
            PrinterProfileService().install_dependencies()
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
            configparser.Error,
        ) as error:
            Logger.print_error(f"Dependency installation failed: {error}")

    def install_host_mcu(self, **kwargs) -> None:
        try:
            require_printer_host()
            PrinterProfileService().install_host_mcu()
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
            configparser.Error,
        ) as error:
            Logger.print_error(f"Host MCU installation failed: {error}")
