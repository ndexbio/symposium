from importlib.metadata import version as package_version

from symposium_data import version


def test_stamped_version_wins(tmp_path):
    stamp = tmp_path / "VERSION"
    stamp.write_text("1.0.7\n")
    assert version(stamp) == "1.0.7"


def test_falls_back_to_package_version(tmp_path):
    assert version(tmp_path / "missing") == package_version("symposium-data")


def test_empty_stamp_is_ignored(tmp_path):
    stamp = tmp_path / "VERSION"
    stamp.write_text("\n")
    assert version(stamp) == package_version("symposium-data")
