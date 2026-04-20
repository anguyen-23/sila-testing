"""Embedded lab messaging server for testing the MessagingClient SiLA feature.

Runs an aiohttp server (HTTP + WebSocket on one port) in a background thread.
Flask routes on the main app proxy to this module for the UI.

Protocol (matches what MessagingTransport expects):
  WS endpoint  → /ws  — broadcasts instrument messages as JSON
  REST confirm → POST /api/messages/<id>/confirm
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, Optional

import aiohttp
from aiohttp import web

log = logging.getLogger(__name__)

# ── Data model ──────────────────────────────────────────────────────


@dataclass
class InstrumentMessage:
    id: str
    title: str
    body: str
    instrument_id: str
    status: str = "pending"  # "pending" | "confirmed"


class MessageStore:
    """Thread-safe message storage."""

    def __init__(self) -> None:
        self._messages: Dict[str, InstrumentMessage] = {}
        self._lock = threading.Lock()

    def add(self, msg: InstrumentMessage) -> None:
        with self._lock:
            self._messages[msg.id] = msg

    def confirm(self, msg_id: str) -> Optional[InstrumentMessage]:
        with self._lock:
            msg = self._messages.get(msg_id)
            if msg and msg.status == "pending":
                msg.status = "confirmed"
                return msg
            return None

    def get(self, msg_id: str) -> Optional[InstrumentMessage]:
        with self._lock:
            return self._messages.get(msg_id)

    def all_messages(self) -> list[dict]:
        with self._lock:
            return [asdict(m) for m in self._messages.values()]

    def pending(self) -> list[dict]:
        with self._lock:
            return [asdict(m) for m in self._messages.values() if m.status == "pending"]


# ── Singleton state ─────────────────────────────────────────────────

store = MessageStore()
_ws_clients: set[web.WebSocketResponse] = set()
_loop: Optional[asyncio.AbstractEventLoop] = None
_ws_port: int = 8765


def get_ws_port() -> int:
    return _ws_port


# ── aiohttp handlers ───────────────────────────────────────────────

async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _ws_clients.add(ws)
    log.info("WS client connected (%d total)", len(_ws_clients))
    try:
        async for _ in ws:
            pass  # We don't expect inbound messages
    finally:
        _ws_clients.discard(ws)
        log.info("WS client disconnected (%d remaining)", len(_ws_clients))
    return ws


async def _confirm_handler(request: web.Request) -> web.Response:
    msg_id = request.match_info["msg_id"]
    msg = store.confirm(msg_id)
    if msg is None:
        return web.json_response(
            {"error": "not found or already confirmed"}, status=404
        )
    await _broadcast({
        "updates": [{
            "type": "instrument_message",
            "data": asdict(msg),
        }]
    })
    log.info("Confirmed message %s (via HTTP)", msg_id[:8])
    return web.json_response({"id": msg.id, "status": msg.status})


async def _broadcast(data: dict) -> None:
    if not _ws_clients:
        return
    payload = json.dumps(data)
    stale = set()
    for ws in _ws_clients.copy():
        try:
            await ws.send_str(payload)
        except Exception:
            stale.add(ws)
    _ws_clients.difference_update(stale)


def _schedule_broadcast(data: dict) -> None:
    """Schedule a broadcast from a non-async context (Flask thread)."""
    if _loop is None or _loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast(data), _loop)
    except RuntimeError:
        log.debug("Event loop unavailable, skipping broadcast")


# ── Server lifecycle ───────────────────────────────────────────────

async def _run_server(port: int) -> None:
    global _loop
    _loop = asyncio.get_running_loop()

    app = web.Application()
    app.router.add_get("/ws", _ws_handler)
    app.router.add_post("/api/messages/{msg_id}/confirm", _confirm_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Message server listening on port %d (HTTP + WS)", port)
    await asyncio.Future()  # run forever


def start_ws_server(port: int = 8765) -> None:
    """Start the message server (HTTP + WS) in a daemon thread."""
    global _ws_port
    _ws_port = port

    def _thread_target():
        global _loop
        try:
            asyncio.run(_run_server(port))
        except OSError as e:
            log.error("Message server failed to start on port %d: %s", port, e)
            _loop = None  # Clear so _schedule_broadcast knows it's dead

    t = threading.Thread(target=_thread_target, daemon=True, name="msg-server")
    t.start()


# ── Public helpers (called from Flask routes) ───────────────────────

def send_message(title: str, body: str, instrument_id: str) -> InstrumentMessage:
    """Create and broadcast a new instrument message."""
    msg = InstrumentMessage(
        id=str(uuid.uuid4()),
        title=title,
        body=body,
        instrument_id=instrument_id,
    )
    store.add(msg)
    _schedule_broadcast({
        "updates": [{
            "type": "instrument_message",
            "data": asdict(msg),
        }]
    })
    log.info("Sent message %s to %s: %s", msg.id[:8], instrument_id, title)
    return msg


def confirm_message(msg_id: str) -> Optional[InstrumentMessage]:
    """Confirm a message and broadcast the update."""
    msg = store.confirm(msg_id)
    if msg:
        _schedule_broadcast({
            "updates": [{
                "type": "instrument_message",
                "data": asdict(msg),
            }]
        })
        log.info("Confirmed message %s", msg_id[:8])
    return msg
