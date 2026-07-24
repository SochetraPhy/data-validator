"""Gatekeeper: validation rules and Frictionless checks for the factory registry."""
from . import rules  # noqa: F401 (re-exported for convenience: gatekeeper.rules.X)

__all__ = ["rules"]
__version__ = "0.1.0"
