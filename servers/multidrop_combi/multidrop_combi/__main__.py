from sila_server_common.server_main import create_main

from .server import Server

main = create_main(Server, default_port=50055, server_package="multidrop_combi", log_filename="multidrop_combi.log")

if __name__ == "__main__":
    import typer
    typer.run(main)
