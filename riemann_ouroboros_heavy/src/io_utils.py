#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
io_utils.py — Streaming CSV writer for OUROBOROS HEAVY.
Single-writer pattern, header written once, periodic flush.
"""
import csv
import os
from typing import List, Dict, Any


class StreamingCSVWriter:
    """Append-mode streaming CSV writer."""

    def __init__(self, path: str, flush_every: int = 10):
        self.path = path
        self.flush_every = flush_every
        self._file = None
        self._writer = None
        self._header_written = False
        self._batch_count = 0
        self._total_rows = 0

    def write_header_once(self, fieldnames: List[str]):
        if self._header_written:
            return
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file, fieldnames=fieldnames, extrasaction="ignore"
        )
        self._writer.writeheader()
        self._file.flush()
        self._header_written = True

    def write_rows(self, rows: List[Dict[str, Any]]):
        if not self._header_written or self._writer is None:
            raise RuntimeError("Call write_header_once before write_rows")
        for row in rows:
            self._writer.writerow(row)
        self._total_rows += len(rows)
        self._batch_count += 1
        if self._batch_count % self.flush_every == 0:
            self._file.flush()

    def flush(self):
        if self._file and not self._file.closed:
            self._file.flush()

    def close(self):
        if self._file and not self._file.closed:
            self._file.flush()
            self._file.close()

    @property
    def total_rows(self) -> int:
        return self._total_rows

    @property
    def file_size_mb(self) -> float:
        if self._file and not self._file.closed:
            self._file.flush()
        if os.path.exists(self.path):
            return os.path.getsize(self.path) / (1024 * 1024)
        return 0.0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
