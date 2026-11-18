"""scripts/install.sh: collision guard and safe options.

These tests use --dry-run, so they need no network and change nothing.
A full install and uninstall was also checked by hand in a throwaway HOME.
"""

import os
import subprocess
import sys

import pytest

import agents_farm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "install.sh")


def run(home, *args, path_first=None):
    bin_path = [os.path.dirname(sys.executable), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    if path_first:
        bin_path.insert(0, path_first)
    env = {"HOME": str(home), "PATH": os.pathsep.join(bin_path), "LANG": "C"}
    return subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True)


def test_script_syntax_is_valid():
    assert subprocess.run(["bash", "-n", SCRIPT]).returncode == 0


def test_version_flag_matches_package():
    out = subprocess.run([sys.executable, "-m", "agents_farm", "--version"], capture_output=True, text=True)
    assert out.stdout.strip() == f"agents-farm {agents_farm.__version__}"


def test_dry_run_plans_af_and_changes_nothing(tmp_path):
    r = run(tmp_path, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "/af  (will be created)" in r.stdout
    assert "nothing was changed" in r.stdout
    assert not (tmp_path / ".local").exists()


def test_foreign_command_named_af_blocks_the_short_name(tmp_path):
    fake = tmp_path / "fake"
    fake.mkdir()
    af = fake / "af"
    af.write_text("#!/bin/sh\necho other tool\n")
    af.chmod(0o755)
    r = run(tmp_path, "--dry-run", path_first=str(fake))
    assert r.returncode == 0
    assert "SKIPPED" in r.stdout and str(af) in r.stdout
    assert "will NOT be created" in r.stderr


def test_alias_in_shell_config_blocks_the_short_name(tmp_path):
    (tmp_path / ".zshrc").write_text("alias af='git add -f'\n")
    r = run(tmp_path, "--dry-run")
    assert "SKIPPED" in r.stdout and ".zshrc" in r.stdout


def test_function_in_shell_config_blocks_the_short_name(tmp_path):
    (tmp_path / ".bashrc").write_text("af() { echo hi; }\n")
    r = run(tmp_path, "--dry-run")
    assert "SKIPPED" in r.stdout and ".bashrc" in r.stdout


def test_existing_foreign_main_command_stops_the_install(tmp_path):
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "agents-farm").write_text("#!/bin/sh\necho mine\n")
    r = run(tmp_path, "--dry-run")
    assert r.returncode == 1
    assert "was not created by this script" in r.stderr
    assert (bin_dir / "agents-farm").read_text().endswith("mine\n")  # untouched


@pytest.mark.parametrize("name", ["a b", "-x", "../x", "af;ls", "1af", ""])
def test_invalid_short_names_are_rejected(tmp_path, name):
    assert run(tmp_path, "--dry-run", "--name", name).returncode == 1


def test_custom_name_and_no_alias(tmp_path):
    assert "/farm  (will be created)" in run(tmp_path, "--dry-run", "--name", "farm").stdout
    assert "short:    none" in run(tmp_path, "--dry-run", "--no-alias").stdout


def test_uninstall_only_lists_its_own_files(tmp_path):
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    target = tmp_path / ".local" / "share" / "agents-farm" / "venv" / "bin" / "agents-farm"
    os.symlink(target, bin_dir / "af")                 # ours: points at our venv
    os.symlink("/bin/ls", bin_dir / "foreign-link")    # not ours
    (bin_dir / "other-tool").write_text("x")
    r = run(tmp_path, "--uninstall", "--dry-run")
    assert r.returncode == 0
    assert "would remove" in r.stdout and "/af" in r.stdout
    assert "foreign-link" not in r.stdout and "other-tool" not in r.stdout
    assert (bin_dir / "other-tool").exists() and os.path.islink(bin_dir / "foreign-link")
