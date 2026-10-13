"""Install the printer profile and restore a validated Git backup."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from components.printer_profile.profile import (
    BACKUP_REPO,
    RECIPES,
    read_profile,
    repository_id,
)
from core.logger import Logger
from core.services.backup_service import BackupService


class PrinterProfileService:
    def __init__(self, home: Path | None = None):
        self.home = home or Path.home()
        self.config_dir = self.home / "printer_data/config"

    def run(self, command, cwd=None, capture=False):
        return subprocess.run(
            [str(arg) for arg in command],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
        )

    @contextmanager
    def backup_checkout(self, ref: str = "HEAD") -> Iterator[Path]:
        # Use Git's credential helper or configured SSH transport; never ask for
        # tokens or embed them in repository URLs.
        with tempfile.TemporaryDirectory(prefix="kiauh-backup-") as temporary:
            checkout = Path(temporary) / "repo"
            self.run(["git", "clone", "--", BACKUP_REPO, checkout])
            if ref != "HEAD":
                if ref.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./-]+", ref):
                    raise ValueError(
                        "Use a branch, tag or full commit hash for the backup ref."
                    )
                self.run(["git", "-C", checkout, "fetch", "origin", ref])
                self.run(["git", "-C", checkout, "checkout", "--detach", "FETCH_HEAD"])
            config = checkout / "printer_data/config"
            if (
                not (config / "printer.cfg").is_file()
                or not (config / "moonraker.conf").is_file()
            ):
                raise ValueError(
                    "Backup must contain printer_data/config/{printer.cfg,moonraker.conf}."
                )
            Logger.print_info(
                "Backup commit: "
                + self.run(
                    ["git", "-C", checkout, "rev-parse", "HEAD"], capture=True
                ).stdout.strip()
            )
            yield config

    def checkout_component(self, name: str, entry: dict[str, str]) -> Path:
        target = self.home / Path(entry["path"]).name
        origin = entry["origin"]
        # HTTPS also works with credential helpers on fresh hosts without an SSH key.
        if origin.startswith("git@github.com:"):
            origin = "https://github.com/" + origin.split(":", 1)[1]
        branch = entry.get("primary_branch")
        if target.exists():
            actual = self.run(
                ["git", "-C", target, "remote", "get-url", "origin"], capture=True
            ).stdout.strip()
            if repository_id(actual) != repository_id(origin):
                raise ValueError(f"{target} belongs to a different repository.")
            if self.run(
                ["git", "-C", target, "status", "--porcelain"], capture=True
            ).stdout.strip():
                raise ValueError(
                    f"{target} has local changes. Commit or stash them before installing."
                )
            if branch:
                current = self.run(
                    ["git", "-C", target, "branch", "--show-current"], capture=True
                ).stdout.strip()
                if current != branch:
                    raise ValueError(
                        f"{target}: expected branch {branch}, found {current}."
                    )
            Logger.print_info(f"Using existing checkout: {target}")
        else:
            command = ["git", "clone"]
            if branch:
                command += ["--branch", branch]
            self.run(command + ["--", origin, target])
        return target

    def install_component(self, name: str, entries: dict[str, dict[str, str]]) -> None:
        entry = entries[name]
        Logger.print_status(f"Installing {name} ...")
        if name == "mainsail":
            from components.webui_client.services.web_client_setup_service import (
                WebClientSetupService,
            )

            if not WebClientSetupService("mainsail").install(
                interactive=False, port=80, install_client_cfg=False
            ):
                raise RuntimeError("Mainsail installation failed.")
            return
        target = self.checkout_component(name, entry)
        if name == "mainsail-config":
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.link(target / "mainsail.cfg", self.config_dir / "mainsail.cfg")
            return
        recipe = RECIPES[name]
        for command in recipe.commands:
            self.run(command, cwd=target)
        if recipe.service:
            self.run(["systemctl", "is-enabled", recipe.service])
            self.run(["systemctl", "is-active", recipe.service])
        Logger.print_ok(f"{name} installed.")

    @staticmethod
    def link(source: Path, destination: Path) -> None:
        if not source.exists():
            raise ValueError(f"Missing dependency: {source}")
        if destination.is_symlink() and destination.resolve() == source.resolve():
            return
        if destination.exists() or destination.is_symlink():
            raise ValueError(
                f"Refusing to overwrite {destination}; restore the config after installation."
            )
        destination.symlink_to(source, target_is_directory=source.is_dir())

    def install_dependencies(self) -> None:
        kamp = self.checkout_component(
            "KAMP",
            {
                "path": "~/Klipper-Adaptive-Meshing-Purging",
                "origin": "https://github.com/kyleisah/Klipper-Adaptive-Meshing-Purging.git",
                "primary_branch": "main",
            },
        )
        self.link(kamp / "Configuration", self.config_dir / "KAMP")
        # PLR installs the shell-command extension before CameraControl needs it.
        self.run(
            ["sudo", "apt-get", "install", "-y", "v4l-utils", "ffmpeg", "make", "gcc"]
        )

    def install_host_mcu(self) -> None:
        klipper = self.home / "klipper"
        with tempfile.TemporaryDirectory(prefix="kiauh-host-mcu-") as temporary:
            build = Path(temporary)
            config = build / "linux.config"
            config.write_text("CONFIG_MACH_LINUX=y\n")
            args = ["make", f"KCONFIG_CONFIG={config}", f"OUT={build}/out/"]
            self.run(args + ["olddefconfig"], cwd=klipper)
            self.run(args, cwd=klipper)
            with self.stopped_services(["klipper", "klipper-mcu"]):
                self.run(args + ["flash"], cwd=klipper)
                self.run(
                    [
                        "sudo",
                        "cp",
                        klipper / "scripts/klipper-mcu.service",
                        "/etc/systemd/system/klipper-mcu.service",
                    ]
                )
                self.run(["sudo", "systemctl", "daemon-reload"])
                self.run(["sudo", "systemctl", "enable", "--now", "klipper-mcu"])

    def install_all(self, source: Path) -> None:
        from components.klipper.klipper import Klipper
        from components.klipper.services.klipper_setup_service import (
            KlipperSetupService,
        )
        from components.moonraker.services.moonraker_setup_service import (
            MoonrakerSetupService,
        )
        from utils.instance_utils import get_instances

        entries = read_profile(source / "moonraker_update_manager.cfg")
        if "klipper-calibration-wizard" in entries:
            version = (
                self.run(["node", "--version"], capture=True).stdout.strip().lstrip("v")
            )
            major, minor = (int(part) for part in version.split(".")[:2])
            if not (
                (major == 20 and minor >= 19)
                or (major == 22 and minor >= 12)
                or major > 22
            ):
                raise ValueError(
                    "Install Node.js 20.19+ or 22.12+ and npm before installing this profile."
                )
            self.run(["npm", "--version"], capture=True)
        from components.moonraker.moonraker import Moonraker

        instances = get_instances(Klipper)
        moonrakers = get_instances(Moonraker)
        if (
            any(instance.suffix for instance in [*instances, *moonrakers])
            or len(instances) > 1
            or len(moonrakers) > 1
        ):
            raise ValueError(
                "This profile requires one unnamed instance in ~/printer_data."
            )
        # A recovery copy must exist BEFORE any third-party installer edits configs.
        if (
            self.config_dir.exists()
            and BackupService().backup_directory(
                self.config_dir, "config-before-profile"
            )
            is None
        ):
            raise RuntimeError("Pre-installation backup failed; installation aborted.")
        if not instances and not KlipperSetupService().install(
            count=1, create_example_cfg=True, interactive=False
        ):
            raise RuntimeError("Klipper installation failed.")
        if not moonrakers and not MoonrakerSetupService().install(
            klipper_suffixes=[""], create_example_cfg=True, interactive=False
        ):
            raise RuntimeError("Moonraker installation failed.")
        # Wizard modifies Mainsail; install it last. PLR provides gcode_shell_command.
        order = [
            "mainsail-config",
            "mainsail",
            "crowsnest",
            "sonar",
            "timelapse",
            "KlipperScreen",
            "klipper-backup",
            "KlipperPLR",
            "KlipperCameraControl",
            "KlipperLCD",
            "klipper-calibration-wizard",
        ]
        self.install_dependencies()
        self.install_host_mcu()
        for name in order:
            if name in entries:
                self.install_component(name, entries)
        self.restore_config(source)
        Logger.print_ok("Printer profile installed and backup config restored.")

    @contextmanager
    def stopped_services(self, services: list[str]) -> Iterator[None]:
        stopped = []
        try:
            for service in services:
                result = subprocess.run(
                    ["systemctl", "is-active", "--quiet", service],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if result.returncode == 0:
                    self.run(["sudo", "systemctl", "stop", service])
                    stopped.append(service)
                elif result.returncode not in (3, 4):
                    raise RuntimeError(f"Unable to determine state of {service}.")
            yield
        finally:
            failures = []
            for service in reversed(stopped):
                try:
                    self.run(["sudo", "systemctl", "start", service])
                except subprocess.CalledProcessError:
                    failures.append(service)
            if failures:
                raise RuntimeError("Unable to restart services: " + ", ".join(failures))

    def validate_includes(self, config: Path) -> None:
        visited = set()

        def check(path: Path):
            if path.resolve() in visited:
                return
            visited.add(path.resolve())
            for pattern in re.findall(
                r"^\s*\[include\s+([^\]]+)\]", path.read_text(), re.MULTILINE
            ):
                pattern = pattern.strip()
                if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                    raise ValueError(f"Unsupported include in {path.name}: {pattern}")
                matches = list(path.parent.glob(pattern))
                if not matches and not any(char in pattern for char in "*?["):
                    raise ValueError(
                        f"Missing include in {path.name}: {pattern}. Install profile dependencies first."
                    )
                for match in matches:
                    check(match)

        check(config / "printer.cfg")
        check(config / "moonraker.conf")

    def restore_config(self, source: Path) -> None:
        target = self.config_dir
        if target.is_symlink():
            raise ValueError("The target config directory must not be a symlink.")
        if (
            not (source / "printer.cfg").is_file()
            or not (source / "moonraker.conf").is_file()
        ):
            raise ValueError("Incomplete backup configuration.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".kiauh-restore-", dir=target.parent
        ) as temporary:
            stage = Path(temporary) / "config"
            # Git backup symlinks may reference the old machine. Recreate known
            # generated dependencies below instead of following arbitrary links.
            if any(path.is_symlink() for path in source.rglob("*")):
                raise ValueError(
                    "Backup contains symlinks; use tracked config files and install dependencies first."
                )
            shutil.copytree(source, stage)
            for path in stage.rglob("*"):
                if path.is_file() and path.suffix in (".cfg", ".conf"):
                    content = path.read_text()
                    content = re.sub(
                        r"/home/biqu(?=/|\s|$)", lambda _: str(self.home), content
                    )
                    if path.name == "moonraker_update_manager.cfg":
                        # The LCD backup uses SSH; match the actual remote used
                        # by the installer so Moonraker can update the checkout.
                        lcd = self.home / "KlipperLCD"
                        if (lcd / ".git").exists():
                            remote = self.run(
                                ["git", "-C", lcd, "remote", "get-url", "origin"],
                                capture=True,
                            ).stdout.strip()
                            if (
                                repository_id(remote)
                                == "herrhasegermany/artillery-klipperlcd"
                            ):
                                content = content.replace(
                                    "git@github.com:HerrHaseGermany/Artillery-KlipperLCD.git",
                                    remote,
                                )
                    path.write_text(content)
            for name, dependency in {
                "mainsail.cfg": self.home / "mainsail-config/mainsail.cfg",
                "KAMP": self.home / "Klipper-Adaptive-Meshing-Purging/Configuration",
            }.items():
                if not (stage / name).exists() and dependency.exists():
                    self.link(dependency, stage / name)
            # Keep locally generated frontend integration, which is not part
            # of the printer backup (the Wizard writes .theme/navi.json).
            theme = target / ".theme"
            if (
                theme.exists()
                and not theme.is_symlink()
                and not (stage / ".theme").exists()
            ):
                shutil.copytree(theme, stage / ".theme", symlinks=True)
            self.validate_includes(stage)
            services = [
                "klipper",
                "moonraker",
                "crowsnest",
                "sonar",
                "KlipperScreen",
                "KlipperLCD",
                "klipper-calibration-wizard",
            ]
            # Pause backup writers too, so they cannot publish a partially restored config.
            services = ["klipper-backup-filewatch", "klipper-backup", *services]
            with self.stopped_services(services):
                if target.exists():
                    svc = BackupService()
                    backup = svc.backup_directory(
                        target, "config-before-restore-" + Path(temporary).name
                    )
                    if backup is None:
                        raise RuntimeError("Config backup failed; restore aborted.")
                    Logger.print_info(f"Recovery backup: {backup}")
                old = Path(temporary) / "previous-config"
                if target.exists():
                    os.rename(target, old)
                try:
                    os.rename(stage, target)
                except BaseException:
                    if old.exists():
                        os.rename(old, target)
                    raise
            Logger.print_ok(
                f"Config restored to {target}. MCU identity and calibration values retained."
            )
