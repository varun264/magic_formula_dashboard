from __future__ import annotations

from pathlib import Path

import pandas as pd


class CSVWriter:
    """Persist DataFrame batches to disk."""

    def __init__(self, path: Path, *, overwrite: bool = False) -> None:
        self._path = Path(path)
        if overwrite and self._path.exists():
            self._path.unlink()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def write(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        frame.to_csv(self._path, index=False)

    def append(self, frame: pd.DataFrame, *, include_header: bool) -> None:
        if frame.empty:
            return
        frame.to_csv(self._path, mode="a", index=False, header=include_header)

    def read(self) -> pd.DataFrame:
        return pd.read_csv(self._path)

    def exists(self) -> bool:
        return self._path.exists()
