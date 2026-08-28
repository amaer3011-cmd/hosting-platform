"""Smoke tests for deployment-safe hosting utilities."""

import json
import zipfile
from pathlib import Path

import pytest

from utils import UnsafeZipError, extract_zip, find_entry_file, safe_filename


def test_safe_filename_rejects_path_traversal() -> None:
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("main.py") == "main.py"


def test_extract_zip_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    destination = tmp_path / "destination"
    destination.mkdir()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../../outside.txt", "blocked")
    with pytest.raises(UnsafeZipError):
        extract_zip(str(archive), str(destination))
    assert not (tmp_path / "outside.txt").exists()


def test_find_entry_file_prefers_main(tmp_path: Path) -> None:
    (tmp_path / "z.py").write_text("print('z')\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
    assert find_entry_file(str(tmp_path)) == str(tmp_path / "main.py")


def test_railway_config_points_to_production_image() -> None:
    config = json.loads(Path("railway.json").read_text(encoding="utf-8"))
    assert config["build"]["dockerfilePath"] == "infra/docker/Dockerfile"
    assert config["deploy"]["healthcheckPath"] == "/health"
    assert config["deploy"]["healthcheckTimeout"] == 300
