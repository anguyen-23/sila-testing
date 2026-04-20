"""WebUIProvider implementation factory — canonical, shared across all servers.

Usage in server.py:
    from sila_server_common.feature_implementations.webuiprovider_impl import create_webuiprovider_impl
    from .generated import webuiprovider as wui_gen

    WebUIProviderImpl = create_webuiprovider_impl(wui_gen)
    self.webuiprovider = WebUIProviderImpl(self)
    self.set_feature_implementation(wui_gen.WebUIProviderFeature, self.webuiprovider)
"""
from __future__ import annotations

from pathlib import Path
from types import ModuleType


def create_webuiprovider_impl(generated_module: ModuleType, html_path: Path | None = None) -> type:
    """Create a WebUIProviderImpl class bound to the server's generated module.

    Args:
        generated_module: The server's generated webuiprovider module.
        html_path: Optional path to custom_ui.html. If None, looks in the
                   server package's root directory (sibling to feature_implementations/).
    """

    Base = generated_module.WebUIProviderBase

    class WebUIProviderImpl(Base):
        def __init__(self, parent_server) -> None:
            super().__init__(parent_server=parent_server)
            if html_path is not None:
                self._html_path = html_path
            else:
                # Default: custom_ui.html in the server package root
                self._html_path = Path(__file__).parent.parent / "custom_ui.html"

        def get_CustomUI(self, *, metadata) -> str:
            return self._html_path.read_text(encoding="utf-8")

    # Allow callers to override _html_path after construction
    WebUIProviderImpl._default_html_path = html_path
    return WebUIProviderImpl
