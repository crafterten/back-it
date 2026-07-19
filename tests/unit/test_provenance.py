from pathlib import Path

from backit.provenance import source_tree_hash


def test_source_tree_hash_excludes_generated_archives(tmp_path: Path) -> None:
    (tmp_path / "src" / "backit").mkdir(parents=True)
    (tmp_path / "src" / "backit" / "engine.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("numpy==1\n", encoding="utf-8")

    before = source_tree_hash(tmp_path)
    (tmp_path / "engine-archive").mkdir()
    (tmp_path / "engine-archive" / "generated.txt").write_text(
        "ignored",
        encoding="utf-8",
    )
    assert source_tree_hash(tmp_path) == before

    (tmp_path / "src" / "backit" / "engine.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    assert source_tree_hash(tmp_path) != before
