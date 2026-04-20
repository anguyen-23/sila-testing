"""UserManualProvider implementation factory — canonical, shared across all servers.

Usage in server.py:
    from sila_server_common.feature_implementations.usermanualprovider_impl import create_usermanualprovider_impl
    from .generated import usermanualprovider as ump_gen

    UserManualProviderImpl = create_usermanualprovider_impl(ump_gen)
    self.usermanualprovider = UserManualProviderImpl(self)
    self.set_feature_implementation(ump_gen.UserManualProviderFeature, self.usermanualprovider)
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import ModuleType

log = logging.getLogger(__name__)


def create_usermanualprovider_impl(generated_module: ModuleType, pdf_path: Path | None = None) -> type:
    """Create a UserManualProviderImpl class bound to the server's generated module."""

    Base = generated_module.UserManualProviderBase

    class UserManualProviderImpl(Base):
        def __init__(self, parent_server) -> None:
            super().__init__(parent_server=parent_server)
            if pdf_path is not None:
                self._pdf_path = pdf_path
            else:
                self._pdf_path = Path(__file__).parent.parent / "user_manual.pdf"
            self._pdf_bytes: bytes | None = None
            self._manual_text: str | None = None

        def _load_pdf(self) -> None:
            """Load PDF bytes and extract text on first access."""
            if self._pdf_bytes is not None:
                return
            pdf_bytes = self._pdf_path.read_bytes()
            try:
                import fitz

                doc = fitz.open(self._pdf_path)
                pages = []
                for i, page in enumerate(doc):
                    text = page.get_text().strip()
                    if text:
                        pages.append(f"--- Page {i + 1} ---\n{text}")
                doc.close()
                self._manual_text = "\n\n".join(pages)
            except ImportError:
                log.warning("PyMuPDF (fitz) not installed; ManualText will be empty")
                self._manual_text = ""
            except Exception as e:
                log.warning("Failed to extract text from PDF: %s", e)
                self._manual_text = ""
            # Set _pdf_bytes last — it's the guard flag, so _manual_text must be ready first
            self._pdf_bytes = pdf_bytes

        def get_ManualDocument(self, *, metadata) -> bytes:
            self._load_pdf()
            return self._pdf_bytes  # type: ignore[return-value]

        def get_ManualText(self, *, metadata) -> str:
            self._load_pdf()
            return self._manual_text  # type: ignore[return-value]

    return UserManualProviderImpl
