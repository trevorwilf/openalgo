"""Convert service-module shims to a hybrid form that preserves
both (a) module identity for test mocks (`mock.patch.object(svc, ...)`)
and (b) deferred-import name resolution inside long-lived Flask route
handlers.

The hybrid keeps the canonical ``sys.modules`` swap (so the shim and
relocated module share identity) AND eagerly copies every public
attribute from the relocated module into the shim's own ``__dict__``
(so any path that reads names off the shim's namespace BEFORE the
swap takes effect — e.g., a partially-initialized package attribute
inside Flask — still resolves correctly).

Idempotent: re-running over a hybrid shim leaves it unchanged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


SERVICES_DIR = Path(__file__).resolve().parent.parent / "services"

HYBRID_TEMPLATE = '''\
"""Hybrid shim for ``services.{name}``.

Both forms used here are necessary:

* ``_sys.modules[__name__] = _orig`` preserves module identity so
  ``mock.patch.object(services.{name}, "X", ...)`` and other tests
  that touch the service via the shim path still work.
* The post-swap attribute copy ensures any caller that looks up
  names on this shim's own ``__dict__`` (e.g., a deferred
  ``from services.{name} import X`` inside a Flask route that
  resolved to the shim before the swap settled) still finds them.

Source of truth:
``market_regions.india.legacy_v1.services.{name}``.
"""
from __future__ import annotations

import sys as _sys

from market_regions.india.legacy_v1.services import {name} as _orig

# Copy public attributes onto this module BEFORE the swap so any
# already-bound reference to the shim sees the relocated symbols.
_globals = globals()
for _name in dir(_orig):
    if _name.startswith("__"):
        continue
    if _name in _globals:
        continue
    _globals[_name] = getattr(_orig, _name)
del _globals, _name

# Replace this module in sys.modules with the relocated module so
# future imports of ``services.{name}`` resolve to ``_orig`` and so
# patches via ``mock.patch.object`` against either path land on the
# same dict.
_sys.modules[__name__] = _orig
'''


# Match either:
#   1. The original four-line swap pattern.
#   2. The pure-re-export pattern from the previous (broken) revision.
SWAP_RE = re.compile(
    r"\Afrom __future__ import annotations\s*\n+"
    r"import sys as _sys\s*\n+"
    r"from market_regions\.india\.legacy_v1\.services import (\w+) as _orig\s*\n+"
    r"_sys\.modules\[__name__\] = _orig\s*\n?\Z",
    re.MULTILINE,
)

REEXPORT_RE = re.compile(
    r"\Afrom __future__ import annotations\s*\n+"
    r"from market_regions\.india\.legacy_v1\.services\.(\w+) import \*.*?\n"
    r"from market_regions\.india\.legacy_v1\.services import \1 as _impl.*?\Z",
    re.DOTALL,
)


def _strip_docstring(text: str) -> tuple[int, str]:
    """Return (body_start_index, body_text)."""
    if text.startswith('"""'):
        end = text.find('"""', 3)
        if end != -1:
            body_start = end + 3
            while body_start < len(text) and text[body_start] in (" ", "\n", "\r"):
                body_start += 1
            return body_start, text[body_start:]
    return 0, text


def main() -> int:
    rewrites = 0
    skipped: list[str] = []

    for path in sorted(SERVICES_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "_orig" not in text and "_impl" not in text:
            continue
        # Heuristic: only rewrite files that look like a shim, not real services.
        if "market_regions.india.legacy_v1.services" not in text:
            continue
        if "Hybrid shim for" in text:
            # already in hybrid form
            continue

        body_start, body = _strip_docstring(text)
        m_swap = SWAP_RE.match(body)
        m_reexport = REEXPORT_RE.match(body)
        if not (m_swap or m_reexport):
            skipped.append(str(path))
            continue
        module_name = (m_swap or m_reexport).group(1)
        new_text = HYBRID_TEMPLATE.format(name=module_name)
        path.write_text(new_text, encoding="utf-8")
        rewrites += 1
        print(f"rewrote: {path}")

    print(f"\n{rewrites} files rewritten, {len(skipped)} skipped")
    if skipped:
        print("Skipped (no shim match):")
        for s in skipped:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
