"""deploy/weekly: secret files become the environment the job reads, and the Compose file is valid."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEEKLY = ROOT / "deploy" / "weekly"


def test_entrypoint_maps_secret_files_to_env(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "mip_pg_password").write_text("p@ss:w/rd%\n")
    (secrets / "youtube_api_key").write_text("yt-test-key\n")
    (secrets / "meta_access_token").write_text("")            # unused secret = empty file = unset
    (secrets / "collector_ssh_key").write_text("not-a-real-key\n")
    env = {"PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}", "MIP_SECRETS_DIR": str(secrets),
           "MIP_PG_HOST": "mip-postgres", "MIP_PG_PORT": "5432", "MIP_PG_USER": "mip", "MIP_PG_DB": "mip"}
    probe = ("import os, json; print(json.dumps({k: os.environ.get(k) for k in "
             "['MIP_DATABASE_URL','MIP_PG_PASSWORD','YOUTUBE_API_KEY','META_ACCESS_TOKEN','MIP_COLLECTOR_SSH_KEY',"
             "'COLLECTOR_SSH_KEY']}))")
    out = subprocess.run(["/bin/bash", str(WEEKLY / "entrypoint.sh"), sys.executable, "-c", probe], env=env,
                         capture_output=True, text=True, check=True)
    import json

    got = json.loads(out.stdout)
    assert got["MIP_PG_PASSWORD"] == "p@ss:w/rd%"
    assert got["MIP_DATABASE_URL"] == "postgresql://mip:p%40ss%3Aw%2Frd%25@mip-postgres:5432/mip"
    assert got["YOUTUBE_API_KEY"] == "yt-test-key"
    assert got["META_ACCESS_TOKEN"] is None
    assert got["MIP_COLLECTOR_SSH_KEY"] == str(secrets / "collector_ssh_key") and got["COLLECTOR_SSH_KEY"] is None
    assert out.stderr == ""


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_compose_file_is_valid_and_hardened(tmp_path):
    env = {**os.environ, "GIT_COMMIT": "abc1234", "MIP_DB_NETWORK": "mip-postgres_default",
           "MIP_PG_HOST": "mip-postgres"}
    # secrets must exist as files for `config`: validate a copy with empty placeholders, never the real directory
    work = tmp_path / "deploy" / "weekly"
    shutil.copytree(WEEKLY, work, ignore=shutil.ignore_patterns("secrets", ".env", "known_hosts"))
    (work / "secrets").mkdir()
    for line in (WEEKLY / "compose.yaml").read_text().split("\nsecrets:\n", 1)[1].splitlines():
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            (work / "secrets" / line.strip().rstrip(":")).write_text("")
    (work / "known_hosts").write_text("")
    p = subprocess.run(["docker", "compose", "-f", str(work / "compose.yaml"), "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    if p.returncode and "Cannot connect" in p.stderr:
        pytest.skip("docker daemon not running")
    assert p.returncode == 0, p.stderr
    import json

    svc = json.loads(p.stdout)["services"]["weekly"]
    assert svc["cap_drop"] == ["ALL"] and "no-new-privileges:true" in svc["security_opt"]
    assert svc["user"] == "10003:10003" and not svc.get("ports")
    assert svc["mem_limit"] and svc["cpus"]
    assert "environment" in svc and not any("PASSWORD" in k or "TOKEN" in k or "KEY" in k.split("_")[-1]
                                            for k in svc["environment"] if k != "MIP_COLLECTOR_SSH")
    assert svc["logging"]["options"] == {"max-size": "10m", "max-file": "3"}


def test_image_carries_every_repo_folder_the_job_reads():
    # the code resolves these relative to the repo root (mip.settings.ROOT = /app in the image); a missing one only
    # fails at run time (geo/ was missing: lieferando discovery could not open geo/berlin.geojson)
    dockerfile = (WEEKLY / "Dockerfile").read_text()
    for folder in ("src", "config", "geo", "db", "dbt"):
        assert f"COPY {folder} ./{folder}" in dockerfile, folder
        assert (ROOT / folder).is_dir(), folder
