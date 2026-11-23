"""scripts/weekly_refresh.sh: the success marker means real success (22 Nov 2026 wrote it after a failed week).

The script runs against stub `mip` / `dbt` / `python` commands and a temporary log directory, so no database, network
or real data/logs file is touched.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("MIP_WEEKLY_SCRIPT_UNDER_TEST", ROOT / "scripts" / "weekly_refresh.sh"))

STUB = """#!/usr/bin/env bash
# fake `mip`: logs its arguments; STUB_FAIL lists "<subcommand>[:<source>]" words that should fail
echo "$*" >> "$STUB_LOG"
sub="$1"; src=""
for ((i=1; i<=$#; i++)); do [ "${!i}" = "-s" ] && { j=$((i+1)); src="${!j}"; }; done
case "$sub" in
  report) exit "${STUB_REPORT_RC:-0}" ;;
  healthcheck) [ "$src" = youtube ] && exit "${STUB_YOUTUBE_RC:-0}"; exit 1 ;;
esac
for f in ${STUB_FAIL:-}; do
  [ "$f" = "$sub" ] && exit 1
  [ "$f" = "$sub:$src" ] && exit 1
done
exit 0
"""


@pytest.fixture
def env(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    stub = bin_ / "fake-mip"
    stub.write_text(STUB)
    stub.chmod(0o755)
    for name, rc in (("fake-dbt", "${STUB_DBT_RC:-0}"), ("fake-python", "${STUB_PY_RC:-0}")):
        p = bin_ / name
        p.write_text(f'#!/usr/bin/env bash\ncat > /dev/null\necho "{name} $*" >> "$STUB_LOG"\nexit {rc}\n')
        p.chmod(0o755)
    logs = tmp_path / "logs"
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "MIP_CMD": str(stub),
        "DBT_CMD": str(bin_ / "fake-dbt"),
        "PY_CMD": str(bin_ / "fake-python"),
        "MIP_LOG_DIR": str(logs),
        "MIP_ENV_FILE": "/dev/null",
        "MIP_PREFLIGHT_TRIES": "1",
        "STUB_LOG": str(tmp_path / "calls.log"),
    }


def _run(env: dict, **extra) -> tuple[subprocess.CompletedProcess, Path]:
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    p = subprocess.run(["/bin/bash", str(SCRIPT)], env={**env, **extra}, capture_output=True, text=True, timeout=60)
    return p, Path(env["MIP_LOG_DIR"])


def _status(logs: Path) -> dict:
    return dict(line.split("=", 1) for line in (logs / "weekly_last_status").read_text().splitlines())


def test_clean_week_writes_success_marker(env):
    p, logs = _run(env)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (logs / "weekly_last_success").exists()
    assert _status(logs)["result"] == "ok"
    calls = Path(env["STUB_LOG"]).read_text()
    assert "ml export content_features" in calls and "fetch -m berlin-food -s wolt" in calls


def test_failed_quality_checks_warn_but_do_not_fail_the_week(env):
    p, logs = _run(env, STUB_REPORT_RC="3")
    assert p.returncode == 0, p.stdout
    assert (logs / "weekly_last_success").exists()
    st = _status(logs)
    assert st["result"] == "ok" and st["warnings"] == "1" and st["failed_steps"] == "0"
    assert "warning: mip report" in p.stdout


def test_report_crash_fails_the_week(env):
    p, logs = _run(env, STUB_REPORT_RC="1")
    assert p.returncode == 1
    assert not (logs / "weekly_last_success").exists()
    assert "mip report crashed" in p.stdout


def test_failed_transform_fails_week_and_skips_ml_exports(env):
    p, logs = _run(env, STUB_FAIL="transform")
    assert p.returncode == 1
    assert not (logs / "weekly_last_success").exists()
    assert _status(logs)["result"] == "failed"
    assert "ml export" not in Path(env["STUB_LOG"]).read_text()
    assert "failed: mip transform (exit 1)" in p.stdout


def test_failed_background_fetch_fails_the_week(env):
    p, logs = _run(env, STUB_FAIL="fetch:wolt")
    assert p.returncode == 1
    assert not (logs / "weekly_last_success").exists()
    assert "failed: fetch wolt (exit 1" in p.stdout
    assert "fetch lieferando" not in p.stdout  # only the failing crawl is reported


def test_failed_dbt_content_build_is_counted(env):
    p, logs = _run(env, STUB_DBT_RC="1")
    assert p.returncode == 1 and not (logs / "weekly_last_success").exists()


def test_preflight_failure_writes_failed_status(env):
    p, logs = _run(env, STUB_PY_RC="1")
    assert p.returncode == 1
    assert not (logs / "weekly_last_success").exists()
    assert _status(logs)["result"] == "failed"
    assert "db partitions" not in Path(env["STUB_LOG"]).read_text() if Path(env["STUB_LOG"]).exists() else True


def test_stale_success_marker_is_not_refreshed_by_a_failed_week(env):
    logs = Path(env["MIP_LOG_DIR"])
    logs.mkdir(parents=True)
    (logs / "weekly_last_success").write_text("2026-11-15T03:00:00Z\n")
    p, _ = _run(env, STUB_FAIL="resolve")
    assert p.returncode == 1
    assert (logs / "weekly_last_success").read_text() == "2026-11-15T03:00:00Z\n"


def test_collector_dsn_in_environment_switches_to_import(env):
    p, _ = _run(env, MIP_COLLECTOR_DSN="postgresql://example.invalid/collector")
    assert p.returncode == 0, p.stdout
    calls = Path(env["STUB_LOG"]).read_text()
    assert "collector import" in calls and "-s wikipedia" not in calls
