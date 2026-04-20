"""Boilerplate feature implementations for standard SiLA 2 server features.

These implementations are generic and work with any server. They import
from the server's own `generated` package using the factory functions
in this module.

Usage in a server's feature_implementations/:

    # screenstreamer_impl.py
    from sila_server_common.feature_implementations.screenstreamer_impl import ScreenStreamerImpl

    # No per-server copy needed — import directly from the common package.
"""
