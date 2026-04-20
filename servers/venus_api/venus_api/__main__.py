import contextlib
import logging
import signal
from pathlib import Path
from typing import Optional
from uuid import UUID

import typer
from sila2.framework.utils import running_in_docker
from sila_server_common.server_main import initialize_logging
from typer import BadParameter, Option

from .server import Server

logger = logging.getLogger(__name__)

_DEFAULT_IP = "0.0.0.0" if running_in_docker() else "127.0.0.1"  # noqa: S104


def main(
    ip_address: str = Option(_DEFAULT_IP, "-a", "--ip-address", help="The IP address"),
    port: int = Option(50056, "-p", "--port", help="The port"),
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
    venus_url: str = Option("http://localhost:51745", "--venus-url", help="VENUS Web API base URL"),
    quiet: bool = Option(False, "--quiet", help="Only log errors"),
    verbose: bool = Option(False, "--verbose", help="Enable verbose logging"),
    debug: bool = Option(False, "--debug", help="Enable debug logging"),
):
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

    # logging setup (shared with all servers)
    initialize_logging(
        quiet=quiet, verbose=verbose, debug=debug,
        server_package="venus_api", log_filename="venus_api.log",
    )

    # run server (venus_url is the only custom kwarg)
    server = Server(
        server_uuid=parsed_server_uuid,
        name=server_name,
        description=server_description,
        venus_url=venus_url,
    )

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


if __name__ == "__main__":
    typer.run(main)
