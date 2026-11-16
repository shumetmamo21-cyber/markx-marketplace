"""Time-ordered UUIDs (version 7, RFC 9562).

PostgreSQL gains a built-in uuidv7() only in version 18, so keys are generated
here. Time-ordered keys keep B-tree inserts local, which random UUIDs do not.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    rand_a = (rand >> 62) & 0x0FFF  # 12 bits
    rand_b = rand & 0x3FFF_FFFF_FFFF_FFFF  # 62 bits
    value = (unix_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand_b
    return uuid.UUID(int=value)
