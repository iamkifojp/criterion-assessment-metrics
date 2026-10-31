"""Errors the teacher may see.

Engine code never builds user-facing sentences itself: it raises a
:class:`UserError` carrying a stable ``code`` (an i18n key under ``error.``)
plus parameters, and the UI translates it with :func:`engine.i18n.t`. The
English ``str()`` is only a fallback for logs and tests.
"""

from __future__ import annotations


class UserError(ValueError):
    """A problem the teacher can understand and act on."""

    def __init__(self, code: str, **params):
        self.code = code
        self.params = params
        detail = ", ".join(f"{k}={v!r}" for k, v in sorted(params.items()))
        super().__init__(f"{code}({detail})" if detail else code)

    @property
    def i18n_key(self) -> str:
        return "error." + self.code


class SaveError(UserError):
    """Base class for anything that stopped a save from completing."""
