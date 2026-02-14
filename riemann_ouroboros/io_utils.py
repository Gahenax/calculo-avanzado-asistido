#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
io_utils.py
===========
Streaming merged CSV writer for OUROBOROS pipeline.
Single writer pattern: only the parent process writes to the merged file.
"""
import csv
import os
from typing import List, Dict, Any, Optional


# Canonical column order for merged_flow_traces.csv
MERGED_COLUMNS = [
    "run_id", "block_id", "type", "seed", "embed",
    "reducer_mode", "reducer_ks", "reducer_entropy_before", "reducer_entropy_after",
    "step", "time", "radius_mean", "radius_var", "sphericity",
    "laplacian_energy", "mean_flow_norm", "max_flow_norm", "status",
]


class MergedWriter:
    """
    Streaming CSV writer for merged flow traces.
    Opens file, writes header once, appends batches, flushes periodically.
    """

    def __init__(self, filepath: str, flush_every: int = 5):
        self.filepath = filepath
        self.flush_every = flush_every
        self._batch_count = 0
        self._total_rows = 0

        # Create/truncate file with header
        self._file = open(filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file, fieldnames=MERGED_COLUMNS, extrasaction="ignore"
        )
        self._writer.writeheader()
        self._file.flush()

    def write_block_history(self, rows: List[Dict[str, Any]]) -> int:
        """
        Write a batch of rows (one block's flow history) to the merged file.
        Returns number of rows written.
        """
        for row in rows:
            self._writer.writerow(row)
        self._total_rows += len(rows)
        self._batch_count += 1

        if self._batch_count % self.flush_every == 0:
            self._file.flush()

        return len(rows)

    @property
    def total_rows(self) -> int:
        return self._total_rows

    @property
    def file_size_mb(self) -> float:
        self._file.flush()
        return os.path.getsize(self.filepath) / (1024 * 1024)

    def close(self):
        if self._file and not self._file.closed:
            self._file.flush()
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def prepare_history_rows(
    history: List[Dict[str, Any]],
    run_id: int,
    block_id: str,
    block_type: str,
    block_seed: int,
    embed_name: str,
    reducer_info: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Inject metadata into each flow history row for merged CSV output.
    """
    r_info = reducer_info or {}
    rows = []
    for h in history:
        row = {
            "run_id": run_id,
            "block_id": block_id,
            "type": block_type,
            "seed": block_seed,
            "embed": embed_name,
            "reducer_mode": r_info.get("mode", "none"),
            "reducer_ks": r_info.get("ks_stat", 0.0),
            "reducer_entropy_before": r_info.get("entropy_before", 0.0),
            "reducer_entropy_after": r_info.get("entropy_after", 0.0),
        }
        row.update(h)
        rows.append(row)
    return rows
