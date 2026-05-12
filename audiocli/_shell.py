"""Cross-platform argv parsing and quoting for ``.acli`` scripts and the REPL.

The :mod:`shlex` standard library splits and quotes args using POSIX shell
rules by default — single-quote wrapping, backslash-as-escape, etc. That's
correct on POSIX systems but is actively wrong on Windows: a Windows path
``C:\\Users\\foo\\bar.wav`` parsed in POSIX mode collapses to
``CUsersfoobar.wav`` because every backslash is consumed as an escape.

This module wraps :mod:`shlex` in a thin platform shim:

* On POSIX, behaviour is identical to ``shlex.split`` / ``shlex.quote``.
* On Windows, parsing runs in non-POSIX mode (``posix=False``) so backslashes
  in paths are preserved, and quoting wraps args with whitespace in double
  quotes (matching ``cmd.exe`` conventions).

Round-trips through ``quote_arg`` → file → ``split_args`` are reliable on the
same platform. Cross-platform ``.acli`` files with paths containing
backslashes or spaces are a known limitation for v2.0.
"""

from __future__ import annotations

import os
import shlex

_IS_WIN = os.name == "nt"


def split_args(line: str) -> list[str]:
    """Split a command line into argv-style tokens.

    Uses POSIX rules on POSIX platforms and Windows rules (no backslash
    escapes, only double-quote pairing) on Windows.
    """
    return shlex.split(line, posix=not _IS_WIN)


def quote_arg(value: str) -> str:
    """Quote a single argument for inclusion in a shell command line.

    Mirrors :func:`shlex.quote` on POSIX. On Windows, wraps args containing
    any cmd.exe/PowerShell metacharacter in double quotes (with internal
    ``"`` escaped to ``\\"``) and leaves simple args untouched.
    """
    if _IS_WIN:
        if not value:
            return '""'
        # ``;`` is significant in PowerShell, ``&|<>()`` in cmd.exe; quote
        # them all conservatively so re-parsing yields the original token.
        if any(c in value for c in ' \t\n";&|<>()^%'):
            return '"' + value.replace('"', '\\"') + '"'
        return value
    return shlex.quote(value)


def unquote_token(token: str) -> str:
    """Strip a single layer of outer matching quotes from a token.

    Needed only on Windows: :func:`shlex.shlex` in ``posix=False`` mode leaves
    quote characters embedded in each token, while POSIX mode strips them.
    Callers that mix ``shlex_lexer`` with platform-portable downstream
    processing should pass each token through this first.
    """
    if not _IS_WIN:
        return token
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
        return token[1:-1]
    return token


def shlex_lexer(line: str) -> shlex.shlex:
    """Return a configured ``shlex.shlex`` lexer matching ``split_args`` rules.

    Used by the REPL chain splitter for token-by-token iteration (it needs to
    spot a literal ``;`` between commands without dropping it as a separator).
    """
    lex = shlex.shlex(line, posix=not _IS_WIN)
    lex.whitespace_split = True
    lex.commenters = ""
    return lex
