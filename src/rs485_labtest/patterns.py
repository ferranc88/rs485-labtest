"""Generacio de payloads de test."""

from __future__ import annotations

import random


def make_payload(pattern: str, size: int, seq: int, rng: random.Random) -> bytes:
    """Genera un payload segons el patro demanat.

    Patrons: ``random``, ``counter``, ``walking`` o un valor de byte fix
    en qualsevol base Python (``0x55``, ``0``, ``255``...).
    """
    if pattern == "random":
        return bytes(rng.getrandbits(8) for _ in range(size))
    if pattern == "counter":
        return bytes((seq + i) & 0xFF for i in range(size))
    if pattern == "walking":
        return bytes((1 << ((seq + i) % 8)) & 0xFF for i in range(size))
    val = int(pattern, 0) & 0xFF
    return bytes([val] * size)
