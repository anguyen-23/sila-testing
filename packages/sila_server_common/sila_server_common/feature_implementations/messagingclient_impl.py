"""MessagingClient implementation factory — canonical, shared across all servers.

Usage in server.py:
    from sila_server_common.feature_implementations.messagingclient_impl import create_messagingclient_impl
    from .generated import messagingclient as mc_gen

    MessagingClientImpl = create_messagingclient_impl(mc_gen)
    self.messagingclient = MessagingClientImpl(self)
    self.set_feature_implementation(mc_gen.MessagingClientFeature, self.messagingclient)
"""
from __future__ import annotations

import json
import logging
import uuid
from types import ModuleType

from sila_server_common.transports.messaging_transport import MessagingTransport

logger = logging.getLogger(__name__)


def create_messagingclient_impl(generated_module: ModuleType) -> type:
    """Create a MessagingClientImpl class bound to the server's generated module."""

    Base = generated_module.MessagingClientBase
    ConfirmMessage_Responses = generated_module.ConfirmMessage_Responses
    ConnectToMessageServer_Responses = generated_module.ConnectToMessageServer_Responses
    DisconnectFromMessageServer_Responses = generated_module.DisconnectFromMessageServer_Responses
    MessageNotFound = generated_module.MessageNotFound
    MessagingError = generated_module.MessagingError
    NotListening = generated_module.NotListening

    class MessagingClientImpl(Base):
        """Lab messaging client SiLA 2 feature implementation.

        In simulation mode, simulates WebSocket message listening.
        In real mode, connects to the lab messaging server via WebSocket.
        """

        def __init__(self, parent_server) -> None:
            super().__init__(parent_server=parent_server)
            self._transport = MessagingTransport()
            self._simulation_mode: bool = True
            self._sim_listening: bool = False
            self._sim_pending: dict[str, dict] = {}

        def get_IsListening(self, *, metadata) -> bool:
            if self._simulation_mode:
                return self._sim_listening
            return self._transport.is_listening

        def get_PendingMessages(self, *, metadata) -> str:
            if self._simulation_mode:
                return json.dumps(list(self._sim_pending.values()))
            return json.dumps(self._transport.pending_messages)

        def ConnectToMessageServer(
            self, ServerUrl: str, InstrumentId: str, *, metadata
        ) -> ConnectToMessageServer_Responses:
            logger.info("ConnectToMessageServer: url=%s, id=%s, simulation=%s",
                        ServerUrl, InstrumentId, self._simulation_mode,
                        extra={"category": "command", "command_name": "ConnectToMessageServer"})

            if self._simulation_mode:
                self._sim_listening = True
                msg_id = str(uuid.uuid4())
                self._sim_pending[msg_id] = {
                    "id": msg_id,
                    "title": "Simulated instrument message",
                    "body": "This is a simulated message from the messaging system.",
                    "instrument_id": InstrumentId,
                }
                return ConnectToMessageServer_Responses()

            try:
                self._transport.connect(ServerUrl, InstrumentId)
            except Exception as e:
                raise MessagingError(str(e))
            return ConnectToMessageServer_Responses()

        def DisconnectFromMessageServer(self, *, metadata) -> DisconnectFromMessageServer_Responses:
            if self._simulation_mode:
                if not self._sim_listening:
                    raise NotListening()
                self._sim_listening = False
                self._sim_pending.clear()
                return DisconnectFromMessageServer_Responses()

            if not self._transport.is_listening:
                raise NotListening()
            self._transport.disconnect()
            return DisconnectFromMessageServer_Responses()

        def ConfirmMessage(self, MessageId: str, *, metadata) -> ConfirmMessage_Responses:
            logger.info("ConfirmMessage: id=%s", MessageId[:8] if len(MessageId) > 8 else MessageId)

            if self._simulation_mode:
                if not self._sim_listening:
                    raise NotListening()
                if MessageId not in self._sim_pending:
                    raise MessageNotFound(f"Message {MessageId} not found")
                del self._sim_pending[MessageId]
                return ConfirmMessage_Responses()

            if not self._transport.is_listening:
                raise NotListening()
            try:
                self._transport.confirm_message(MessageId)
            except KeyError:
                raise MessageNotFound(f"Message {MessageId} not found")
            except RuntimeError as e:
                raise MessagingError(str(e))
            return ConfirmMessage_Responses()

    return MessagingClientImpl
