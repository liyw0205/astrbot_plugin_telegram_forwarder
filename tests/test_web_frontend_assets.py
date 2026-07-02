from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ASSETS = ROOT / "web" / "assets"
IMPORT_RE = re.compile(r"""^\s*import\s+(?:[^'"]+\s+from\s+)?['"](?P<path>\.{1,2}/[^'"]+)['"]""")


def test_frontend_relative_module_imports_resolve() -> None:
    for source in [WEB_ASSETS / "app.js", *(WEB_ASSETS / "js").glob("*.js")]:
        text = source.read_text(encoding="utf-8")
        for match in IMPORT_RE.finditer(text):
            target = (source.parent / match.group("path")).resolve()
            assert target.is_file(), (
                f"{source.relative_to(ROOT)} imports missing module "
                f"{match.group('path')}"
            )
