"""WebSocket messaging client for the autonomous lab messaging system.

Connects to a lab server's WebSocket endpoint, listens for instrument
messages, and provides methods to confirm (acknowledge) them.

Ported from the autonomous_lab_mockup pc_client.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


class MessagingTransport:
    """WebSocket-based messaging client for lab instrument messages."""

    def __init__(self) -> None:
        self._server_url: Optional[str] = None
        self._instrument_id: Optional[str] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pending_messages: dict[str, dict] = {}
        self._lock = threading.Lock()

    @property
    def is_listening(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def pending_messages(self) -> list[dict]:
        with self._lock:
            return list(self._pending_messages.values())

    def connect(self, server_url: str, instrument_id: str) -> None:
        """Start listening for messages from the server.

        Raises ConnectionError on failure.
        """
        server_url = server_url.rstrip("/")
        if not server_url.startswith(("http://", "https://", "ws://", "wss://")):
            server_url = f"http://{server_url}"

        self.disconnect()
        self._server_url = server_url
        self._instrument_id = instrument_id
        self._running = True
        self._thread = threading.Thread(target=self._ws_thread, daemon=True)
        self._thread.start()
        logger.info("Messaging client connecting to %s for instrument %s", server_url, instrument_id)

    def disconnect(self) -> None:
        """Stop listening and close the WebSocket connection."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        with self._lock:
            self._pending_messages.clear()
        self._server_url = None
        self._instrument_id = None
        logger.info("Messaging client disconnected")

    def confirm_message(self, message_id: str) -> None:
        """Confirm a pending message by its ID.

        Raises KeyError if message not found.
        Raises RuntimeError on server error.
        """
        with self._lock:
            if message_id not in self._pending_messages:
                raise KeyError(f"Message {message_id} not found in pending messages")

        try:
            resp = requests.post(
                f"{self._server_url}/api/messages/{message_id}/confirm",
                json={"confirmed_by": "sila_server"},
                timeout=10,
            )
            if resp.ok:
                with self._lock:
                    self._pending_messages.pop(message_id, None)
                logger.info("Confirmed message %s", message_id[:8])
            else:
                raise RuntimeError(f"Server returned {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to confirm message: {e}") from e

    def _ws_thread(self) -> None:
        """Background thread running the async WebSocket listener."""
        try:
            asyncio.run(self._listen_ws())
        except Exception as e:
            logger.error("WebSocket thread error: %s", e)
            self._running = False

    async def _listen_ws(self) -> None:
        """Async WebSocket listener with auto-reconnect."""
        import websockets

        parsed = urlparse(self._server_url)
        is_secure = parsed.scheme in ("https", "wss")
        ws_scheme = "wss" if is_secure else "ws"
        host = parsed.netloc or parsed.path
        ws_url = f"{ws_scheme}://{host}/ws"

        import ssl
        ssl_ctx = ssl.create_default_context() if is_secure else None

        while self._running:
            try:
                async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
                    logger.info("WebSocket connected to %s", ws_url)
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(raw)
                            for update in data.get("updates", []):
                                if update.get("type") == "instrument_message":
                                    msg = update["data"]
                                    if (
                                        msg.get("instrument_id") == self._instrument_id
                                        and msg.get("status") == "pending"
                                    ):
                                        msg_id = msg["id"]
                                        with self._lock:
                                            self._pending_messages[msg_id] = {
                                                "id": msg_id,
                                                "title": msg.get("title", ""),
                                                "body": msg.get("body", ""),
                                                "instrument_id": msg.get("instrument_id", ""),
                                            }
                                        logger.info("New message: %s", msg.get("title", ""))
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                if self._running:
                    logger.warning("WebSocket disconnected: %s. Reconnecting in 3s...", e)
                    await asyncio.sleep(3)
