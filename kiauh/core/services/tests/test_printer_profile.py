from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import components.printer_profile.service as module
import pytest
from components.printer_profile.profile import PROFILE_CONFIG, read_profile
from components.printer_profile.service import PrinterProfileService
from core.menus.printer_profile_menu import PrinterProfileMenu


@pytest.fixture
def setup(tmp_path, monkeypatch):
    service = PrinterProfileService(tmp_path / "host")
    source = tmp_path / "backup"
    source.mkdir()
    (source / "printer.cfg").write_text(
        "[mcu]\nserial: original-id\n#*# z_offset = 0.960\n"
    )
    (source / "moonraker.conf").write_text(
        "[server]\nklippy_uds_address: /home/biqu/printer_data/comms/klippy.sock\n"
    )
    service.config_dir.mkdir(parents=True)
    (service.config_dir / "old.cfg").write_text("original")
    calls = []

    def run(command, cwd=None, capture=False):
        calls.append([str(arg) for arg in command])
        return SimpleNamespace(stdout="", returncode=0)

    service.run = run
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=3)
    )

    class Backup:
        def backup_directory(self, target, name):
            recovery = tmp_path / "recovery"
            shutil.copytree(target, recovery, symlinks=True)
            return recovery

    monkeypatch.setattr(module, "BackupService", Backup)
    return service, source, calls


def test_profile_covers_actual_update_manager_and_menu():
    entries = read_profile()
    assert set(entries) == {
        "mainsail",
        "mainsail-config",
        "crowsnest",
        "sonar",
        "timelapse",
        "KlipperScreen",
        "klipper-backup",
        "KlipperLCD",
        "KlipperCameraControl",
        "KlipperPLR",
        "klipper-calibration-wizard",
    }
    menu = PrinterProfileMenu()
    assert len(menu.options) == len(entries) + 5
    assert {
        option.opt_data for key, option in menu.options.items() if key.isdigit()
    } == set(entries)


@pytest.mark.parametrize(
    "replacement",
    [
        "[update_manager unknown]\ntype: git_repo\norigin: https://github.com/example/unknown.git\npath: ~/unknown\n",
        "[update_manager sonar]\ntype: git_repo\norigin: https://github.com/example/sonar.git\npath: ~/sonar\n",
        "[update_manager sonar]\ntype: git_repo\norigin: https://github.com/mainsail-crew/sonar.git\npath: /etc/sonar\n",
    ],
)
def test_profile_rejects_unsupported_recipe_before_install(tmp_path, replacement):
    path = tmp_path / "update.cfg"
    path.write_text(replacement)
    with pytest.raises(ValueError):
        read_profile(path)


def test_restore_replaces_config_and_preserves_calibration_and_backup(setup):
    service, source, _ = setup
    service.restore_config(source)
    assert not (service.config_dir / "old.cfg").exists()
    assert (service.home.parent / "recovery/old.cfg").read_text() == "original"
    assert (service.config_dir / "printer.cfg").read_text() == (
        source / "printer.cfg"
    ).read_text()
    assert (
        str(service.home / "printer_data/comms/klippy.sock")
        in (service.config_dir / "moonraker.conf").read_text()
    )


def test_restore_recreates_generated_includes_and_preserves_frontend(setup):
    service, source, _ = setup
    (source / "printer.cfg").write_text(
        "[include mainsail.cfg]\n[include KAMP/Line_Purge.cfg]\n"
    )
    for path in [
        service.home / "mainsail-config/mainsail.cfg",
        service.home / "Klipper-Adaptive-Meshing-Purging/Configuration/Line_Purge.cfg",
    ]:
        path.parent.mkdir(parents=True)
        path.write_text("# dependency\n")
    theme = service.config_dir / ".theme"
    theme.mkdir()
    (theme / "navi.json").write_text('{"tools":true}')
    service.restore_config(source)
    assert (service.config_dir / "mainsail.cfg").is_symlink()
    assert (service.config_dir / "KAMP").is_symlink()
    assert (service.config_dir / ".theme/navi.json").read_text() == '{"tools":true}'


def test_missing_nested_include_leaves_existing_config_and_services_untouched(setup):
    service, source, calls = setup
    (source / "printer.cfg").write_text("[include macros.cfg]\n")
    (source / "macros.cfg").write_text("[include missing.cfg]\n")
    with pytest.raises(ValueError, match="Missing include"):
        service.restore_config(source)
    assert (service.config_dir / "old.cfg").read_text() == "original"
    assert calls == []


def test_symlink_in_backup_rejected_without_following_it(setup):
    service, source, _ = setup
    (source / "outside.cfg").symlink_to(service.config_dir / "old.cfg")
    with pytest.raises(ValueError, match="symlinks"):
        service.restore_config(source)
    assert (service.config_dir / "old.cfg").exists()


def test_backup_failure_aborts_before_replacement(setup, monkeypatch):
    service, source, _ = setup
    monkeypatch.setattr(
        module,
        "BackupService",
        lambda: SimpleNamespace(backup_directory=lambda *a: None),
    )
    with pytest.raises(RuntimeError, match="backup failed"):
        service.restore_config(source)
    assert (service.config_dir / "old.cfg").read_text() == "original"


def test_failed_directory_swap_rolls_back(setup, monkeypatch):
    service, source, _ = setup
    rename = os.rename

    def fail_stage(src, dst):
        if Path(src).name == "config" and Path(src).parent.name.startswith(
            ".kiauh-restore-"
        ):
            raise OSError("simulated rename failure")
        rename(src, dst)

    monkeypatch.setattr(module.os, "rename", fail_stage)
    with pytest.raises(OSError, match="simulated"):
        service.restore_config(source)
    assert (service.config_dir / "old.cfg").read_text() == "original"


def test_active_services_restart_even_after_failure(setup, monkeypatch):
    service, _, calls = setup
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **k: SimpleNamespace(
            returncode=0 if command[-1] == "klipper" else 3
        ),
    )
    with pytest.raises(ValueError), service.stopped_services(["klipper", "moonraker"]):
        raise ValueError("failed operation")
    assert calls == [
        ["sudo", "systemctl", "stop", "klipper"],
        ["sudo", "systemctl", "start", "klipper"],
    ]


def test_service_stop_failure_restarts_already_stopped_services(setup, monkeypatch):
    service, _, calls = setup
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)
    )
    run = service.run

    def fail_stop(command, **kwargs):
        if command == ["sudo", "systemctl", "stop", "moonraker"]:
            raise subprocess.CalledProcessError(1, command)
        return run(command, **kwargs)

    service.run = fail_stop
    with pytest.raises(subprocess.CalledProcessError), service.stopped_services(
        ["klipper", "moonraker"]
    ):
        pytest.fail("must not proceed after failing to stop a service")
    assert calls[-1] == ["sudo", "systemctl", "start", "klipper"]


def test_third_party_installer_failure_propagates(setup):
    service, _, _ = setup
    service.checkout_component = lambda *a: service.home / "KlipperPLR"
    service.run = lambda command, **k: (_ for _ in ()).throw(
        subprocess.CalledProcessError(1, command)
    )
    with pytest.raises(subprocess.CalledProcessError):
        service.install_component("KlipperPLR", read_profile())


def test_full_install_orders_dependencies_and_restores_last(setup, monkeypatch):
    import components.klipper.services.klipper_setup_service as klipper_module
    import components.moonraker.services.moonraker_setup_service as moonraker_module
    from utils import instance_utils

    service, source, _ = setup
    shutil.copy2(PROFILE_CONFIG, source / "moonraker_update_manager.cfg")
    monkeypatch.setattr(instance_utils, "get_instances", lambda *a: [])
    monkeypatch.setattr(
        klipper_module,
        "KlipperSetupService",
        lambda: SimpleNamespace(install=lambda **k: True),
    )
    monkeypatch.setattr(
        moonraker_module,
        "MoonrakerSetupService",
        lambda: SimpleNamespace(install=lambda **k: True),
    )
    service.run = lambda *a, **k: SimpleNamespace(stdout="v22.12.0")
    calls = []
    service.install_host_mcu = lambda: calls.append("host-mcu")
    service.install_dependencies = lambda: calls.append("dependencies")
    service.install_component = lambda name, entries: calls.append(name)
    service.restore_config = lambda source: calls.append("restore")
    service.install_all(source)
    assert calls[-1] == "restore"
    assert calls.index("KlipperPLR") < calls.index("KlipperCameraControl")
    assert calls.index("mainsail") < calls.index("klipper-calibration-wizard")
    assert calls.index("dependencies") < calls.index("KlipperPLR")
    assert set(read_profile()) <= set(calls)


def test_backup_checkout_fetches_selected_branch_and_cleans_up(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-b", "main")
    config = repository / "printer_data/config"
    config.mkdir(parents=True)
    (config / "printer.cfg").write_text("main")
    (config / "moonraker.conf").write_text("[server]\n")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "main config",
    )
    git("checkout", "-b", "recovery")
    (config / "printer.cfg").write_text("recovery")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "recovery config",
    )
    git("checkout", "main")
    service = PrinterProfileService(tmp_path / "host")
    run = service.run

    def clone_local(command, **kwargs):
        if command[:2] == ["git", "clone"]:
            command = ["git", "clone", "--", str(repository), command[-1]]
        return run(command, capture=True)

    service.run = clone_local
    with service.backup_checkout("recovery") as source:
        assert (source / "printer.cfg").read_text() == "recovery"
        checked_out = source
    assert not checked_out.exists()


def test_host_mcu_build_uses_separate_build_config(setup):
    service, _, calls = setup
    service.install_host_mcu()
    make = [command for command in calls if command[0] == "make"]
    assert len(make) == 3
    assert all(
        any(
            arg.startswith("KCONFIG_CONFIG=") and "linux.config" in arg
            for arg in command
        )
        for command in make
    )
    assert all(
        any(arg.startswith("OUT=") and "kiauh-host-mcu-" in arg for arg in command)
        for command in make
    )
    assert ["sudo", "systemctl", "enable", "--now", "klipper-mcu"] in calls
