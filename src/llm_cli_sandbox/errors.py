"""User-facing error type.

Raising ``SandboxError`` from anywhere in the package produces a clean one-line
message at the CLI boundary (no Python traceback). Use it for expected failure
conditions with an actionable message; let unexpected bugs raise normally.
"""

from __future__ import annotations


class SandboxError(Exception):
    """An expected, user-facing failure. The CLI prints ``str(self)`` and exits
    with ``exit_code``."""

    def __init__(self, message: str, *, exit_code: int = 1, hint: str | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.hint = hint
