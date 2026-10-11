"""Optional HTTPS for standalone deployments; reverse proxies also work."""

import os
import ssl


def server_tls():
    cert = os.getenv("TLS_CERTFILE", "")
    key = os.getenv("TLS_KEYFILE", "")
    if not cert and not key:
        return None
    if not cert or not key:
        raise ValueError("TLS_CERTFILE and TLS_KEYFILE must both be set")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context
