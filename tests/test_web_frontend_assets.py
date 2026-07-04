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


def test_topology_stage_drop_does_not_add_qq_payload_as_default_target() -> None:
    text = (WEB_ASSETS / "app.js").read_text(encoding="utf-8")

    assert 'payload.type === "tg"' in text
    assert 'payload.type === "qq"' in text
    assert "addTopologyDefaultTarget" not in text
    assert "请将 QQ 群拖到左侧 Telegram 频道节点上建立专属关系。" in text


def test_topology_nodes_expose_context_menu_removal_actions() -> None:
    app_text = (WEB_ASSETS / "app.js").read_text(encoding="utf-8")
    css_text = (WEB_ASSETS / "css" / "components.css").read_text(encoding="utf-8")

    assert 'addEventListener("contextmenu"' in app_text
    assert "removeTopologyChannel(index)" in app_text
    assert "removeTopologyTarget(node.dataset.topologyTargetKey)" in app_text
    assert 'data-topology-target-key="${escapeHtml(target.key)}"' in app_text
    assert 'document.addEventListener("pointermove", onPointerMove)' in app_text
    assert "anchorNode.contains(target) || menu.contains(target)" in app_text
    assert 'menu.classList.add("danger-only")' in app_text
    assert ".topology-context-menu" in css_text
    assert ".topology-context-menu.danger-only" in css_text
    assert "@keyframes topology-context-in" in css_text
    assert ".topology-context-menu button.danger::before" in css_text
