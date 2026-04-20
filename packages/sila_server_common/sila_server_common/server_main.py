"""Shared server entry point logic — CLI, logging setup, and server lifecycle.

Usage in a server's __main__.py:

    from sila_server_common.server_main import create_main
    from .server import Server

    main = create_main(Server, default_port=50061, server_package="my_server", log_filename="my_server.log")

    if __name__ == "__main__":
        import typer
        typer.run(main)
"""
from __future__ import annotations

import contextlib
import logging
import signal
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from uuid import UUID

from sila2.framework.utils import running_in_docker
from typer import BadParameter, Option


def create_main(server_class: type, default_port: int, server_package: str, log_filename: str = "server.log"):
    """Create a typer-compatible main function for a SiLA 2 server.

    Args:
        server_class: The Server class to instantiate.
        default_port: Default port number for this server.
        server_package: Python package name (e.g., "multidrop_combi") for logging.
        log_filename: Name of the log file (e.g., "multidrop_combi.log").
    """

    _default_ip = "0.0.0.0" if running_in_docker() else "127.0.0.1"

    def main(
        ip_address: str = Option(_default_ip, "-a", "--ip-address", help="The IP address"),
        port: int = Option(default_port, "-p", "--port", help="The port"),
        server_uuid: Optional[str] = Option(
            None, "--server-uuid", help="The server UUID [default: generate random UUID]", show_default=False
        ),
        server_name: Optional[str] = Option(
            None, "--server-name", help="The server name [default: defined by implementation]", show_default=False
        ),
        server_description: Optional[str] = Option(
            None, "--server-description",
            help="The server description [default: defined by implementation]", show_default=False,
        ),
        disable_discovery: bool = Option(False, "--disable-discovery", help="Disable SiLA Server Discovery"),
        insecure: bool = Option(False, "--insecure", help="Start without encryption"),
        private_key_file: Optional[str] = Option(
            None, "-k", "--private-key-file", help="Private key file (e.g. 'server-key.pem')"
        ),
        cert_file: Optional[str] = Option(None, "-c", "--cert-file", help="Certificate file (e.g. 'server-cert.pem')"),
        ca_file_for_discovery: Optional[str] = Option(
            None, "--ca-file-for-discovery",
            help="Certificate Authority file for distribution via the SiLA Server Discovery",
        ),
        ca_export_file: Optional[str] = Option(
            None, help="When using a self-signed certificate, write the generated CA to this file"
        ),
        quiet: bool = Option(False, "--quiet", help="Only log errors"),
        verbose: bool = Option(False, "--verbose", help="Enable verbose logging"),
        debug: bool = Option(False, "--debug", help="Enable debug logging"),
    ):
        logger = logging.getLogger(__name__)

        # validate parameters
        if (insecure or ca_export_file is not None) and (cert_file is not None or private_key_file is not None):
            raise BadParameter("Cannot use --insecure or --ca-export-file with --private-key-file or --cert-file")
        if (cert_file is None and private_key_file is not None) or (private_key_file is None and cert_file is not None):
            raise BadParameter("Either provide both --private-key-file and --cert-file, or none of them")
        if insecure and ca_export_file is not None:
            raise BadParameter("Cannot use --export-ca-file with --insecure")

        # prepare server parameters
        cert = Path(cert_file).read_bytes() if cert_file is not None else None
        private_key = Path(private_key_file).read_bytes() if private_key_file is not None else None
        ca_for_discovery = Path(ca_file_for_discovery).read_bytes() if ca_file_for_discovery is not None else None
        parsed_server_uuid = UUID(server_uuid) if server_uuid is not None else None

        # logging setup
        initialize_logging(
            quiet=quiet, verbose=verbose, debug=debug,
            server_package=server_package, log_filename=log_filename,
        )

        # run server
        server = server_class(server_uuid=parsed_server_uuid, name=server_name, description=server_description)

        def start_server():
            if insecure:
                server.start_insecure(ip_address, port, enable_discovery=not disable_discovery)
            else:
                server.start(
                    ip_address, port, cert_chain=cert, private_key=private_key,
                    enable_discovery=not disable_discovery, ca_for_discovery=ca_for_discovery,
                )
                if ca_export_file is not None:
                    with open(ca_export_file, "wb") as fp:
                        fp.write(server.generated_ca)
                    logger.info(f"Wrote generated CA to '{ca_export_file}'")

        try:
            start_server()
        except:
            logger.exception("Server startup failed, shutting down")
            if server.running:
                server.stop()
            logger.info("Server shutdown complete")
            return

        logger.info("Server startup complete")
        signal.signal(signal.SIGTERM, lambda *args: server.grpc_server.stop())

        with contextlib.suppress(KeyboardInterrupt):
            server.grpc_server.wait_for_termination()

        server.stop()
        logger.info("Server shutdown complete")

    return main


def initialize_logging(
    *,
    quiet: bool = False,
    verbose: bool = False,
    debug: bool = False,
    server_package: str = "",
    log_filename: str = "server.log",
):
    """Set up console, file, and structured logging for a SiLA 2 server."""

    if sum((quiet, verbose, debug)) > 1:
        raise BadParameter("--quiet, --verbose and --debug are mutually exclusive")

    level = logging.WARNING
    if verbose:
        level = logging.INFO
    if debug:
        level = logging.DEBUG
    if quiet:
        level = logging.ERROR

    # Set root logger to DEBUG so all messages reach the file/structured handlers.
    # The console handler uses the user-specified level to control terminal output.
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(level)
    logging.getLogger(__name__).setLevel(logging.INFO)
    logging.getLogger("xmlschema").setLevel(logging.WARNING)

    # Determine log directory (inside the server package)
    import importlib
    try:
        pkg = importlib.import_module(server_package)
        log_dir = Path(pkg.__file__).parent / "logs"
    except (ImportError, AttributeError):
        log_dir = Path.cwd() / "logs"
    log_dir.mkdir(exist_ok=True)

    # Persisted log file with rotation
    file_handler = RotatingFileHandler(
        log_dir / log_filename,
        maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s:%(message)s"))
    logging.getLogger().addHandler(file_handler)

    # Structured log handler (SQLite) for ServerLogProvider queries
    from sila_server_common.transports.structured_logging import StructuredLogHandler
    structured_handler = StructuredLogHandler(log_dir / "structured.db", server_package=server_package)
    structured_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(structured_handler)
