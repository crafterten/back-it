import hashlib
from pathlib import Path


def source_tree_hash(root: Path) -> str:
    inputs = [
        *sorted(
            path
            for path in (root / "src" / "backit").rglob("*")
            if path.is_file()
        ),
        root / "pyproject.toml",
        root / "requirements.lock",
    ]
    digest = hashlib.sha256()
    for path in sorted(inputs, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
