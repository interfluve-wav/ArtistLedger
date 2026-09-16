"""Minimal local stand-in for the `genlayer` package so Intelligent
Contract modules can be imported and unit-tested off-chain.

Install as `genlayer/__init__.py` inside the test venv's site-packages.
NOT used on GenVM — the real py-genlayer runner replaces this at deploy
time.

Verified 2026-09: the full ArtistLedger test suite (56 tests, including
register_artist/anchor_release/dispute flows with patched collectors)
passes against this stub.
"""

from dataclasses import dataclass  # noqa: F401  (re-export)
from types import SimpleNamespace


# ─── Primitive types ───────────────────────────────────────────────────────

class Address(str):
    """Wallet/contract address (string on the wire)."""


class u256(int):
    """Unsigned 256-bit integer; plain int locally."""


class DynArray(list):
    """Dynamic array; plain list locally."""

    def append(self, item):
        super().append(item)


class TreeMap(dict):
    """Key-value storage; dict locally."""

    def get(self, key, default=None):
        return super().get(key, default)


def allow_storage(cls):
    """Marker decorator for storage-capable dataclasses."""
    return cls


# ─── gl namespace ──────────────────────────────────────────────────────────

class _NondetWeb:
    def get(self, url, headers=None):
        raise RuntimeError("nondet.web.get unavailable off-chain; mock it")

    def render(self, url, mode="text"):
        raise RuntimeError("nondet.web.render unavailable off-chain; mock it")


class _Nondet:
    web = _NondetWeb()

    @staticmethod
    def exec_prompt(prompt, response_format=None):
        raise RuntimeError("nondet.exec_prompt unavailable off-chain; mock it")


class _VM:
    class Return:
        def __init__(self, calldata=None):
            self.calldata = calldata

    @staticmethod
    def run_nondet_unsafe(leader_fn, validator_fn):
        return leader_fn()


class _EqPrinciple:
    @staticmethod
    def strict_eq(fn):
        return fn()


class _Public:
    @staticmethod
    def write(fn):
        return fn

    @staticmethod
    def view(fn):
        return fn


class Contract:
    """Base class for the on-chain contract. One per file on GenVM.

    Off-chain, this stub materializes annotated TreeMap storage fields as
    empty TreeMaps after __init__."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        original_init = cls.__dict__.get("__init__")
        annotations = dict(getattr(cls, "__annotations__", {}))

        def wrapped_init(self, *args, **kw):
            if original_init is not None:
                original_init(self, *args, **kw)
            for name, typ in annotations.items():
                if hasattr(self, name):
                    continue
                if getattr(typ, "__origin__", None) is TreeMap:
                    setattr(self, name, TreeMap())

        cls.__init__ = wrapped_init


gl = SimpleNamespace(
    nondet=_Nondet(),
    vm=_VM(),
    eq_principle=_EqPrinciple(),
    public=_Public(),
    Contract=Contract,
    message=SimpleNamespace(sender_address=Address("0x" + "0" * 40)),
    message_raw={"datetime": "2026-09-05T00:00:00+00:00"},
)

__all__ = [
    "Address", "DynArray", "TreeMap", "allow_storage", "dataclass",
    "gl", "u256",
]
