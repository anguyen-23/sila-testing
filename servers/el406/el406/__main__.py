from sila_server_common.server_main import create_main
from .server import Server

main = create_main(
    Server,
    default_port=50061,
    server_package="el406",
    log_filename="el406.log",
)

if __name__ == "__main__":
    import typer
    typer.run(main)
