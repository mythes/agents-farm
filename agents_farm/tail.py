"""Bounded, incremental line reader for append-only JSONL files."""

from __future__ import annotations

import os
from typing import Iterator

CHUNK = 8 * 1024 * 1024  # bytes read per step: memory stays bounded for huge logs
MAX_LINE = 64 * 1024 * 1024  # a "line" longer than this without a newline is dropped


class Tail:
    def __init__(self, path: str):
        self.path = path
        self.offset = 0
        self._buf = b""

    def lines(self) -> Iterator[bytes]:
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        if size < self.offset:  # truncated / rewritten
            self.offset, self._buf = 0, b""
        if size == self.offset:
            return
        try:
            fh = open(self.path, "rb")
        except OSError:
            return
        with fh:
            fh.seek(self.offset)
            while True:
                data = fh.read(CHUNK)
                if not data:
                    break
                self.offset += len(data)
                parts = (self._buf + data).split(b"\n")
                self._buf = parts.pop()  # incomplete last line: finish it next time
                if len(self._buf) > MAX_LINE:
                    self._buf = b""
                for part in parts:
                    if part.strip():
                        yield part
