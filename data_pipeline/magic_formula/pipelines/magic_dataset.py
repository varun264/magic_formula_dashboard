from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd

from ..services.csv_writer import CSVWriter
from ..services.stock_fetcher import StockDataFetcher
from ..utils.chunk import chunked


class MagicFormulaDatasetPipeline:
    """High-level orchestrator for building the stock master dataset."""

    def __init__(self, fetcher: StockDataFetcher, writer: CSVWriter) -> None:
        self._fetcher = fetcher
        self._writer = writer

    def run(self, symbols: Sequence[str], *, batch_size: int = 100, max_workers: int = 16) -> None:
        header_columns: Optional[list[str]] = None

        for index, chunk in enumerate(chunked(symbols, batch_size), start=1):
            print(f"Processing chunk {index} with {len(chunk)} stocks...")
            batch = self._fetcher.fetch_many(chunk, max_workers=max_workers)
            if batch.empty:
                continue

            batch = self._normalise_columns(batch, header_columns)

            if header_columns is None:
                header_columns = batch.columns.tolist()
                self._writer.write(batch[header_columns])
            else:
                self._writer.append(batch[header_columns], include_header=False)

        if header_columns is None:
            print("No data collected; nothing was written.")

    @staticmethod
    def _normalise_columns(batch: pd.DataFrame, header_columns: Optional[list[str]]) -> pd.DataFrame:
        if header_columns is None:
            return batch

        missing_in_batch = [column for column in header_columns if column not in batch.columns]
        extra_in_batch = [column for column in batch.columns if column not in header_columns]

        if extra_in_batch:
            print(
                "[Warning] Ignoring unexpected columns in batch:",
                ", ".join(sorted(extra_in_batch)),
            )

        adjusted = batch.reindex(columns=header_columns, fill_value=pd.NA)

        if missing_in_batch:
            print(
                "[Warning] Batch missing columns; filling with NA:",
                ", ".join(sorted(missing_in_batch)),
            )

        return adjusted
