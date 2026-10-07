from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_http_url(raw_url: str) -> str:
    raw_url = raw_url.strip()
    if not raw_url:
        raise UnsafeURLError("A URL is required.")

    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError("Only http and https URLs are supported.")
    if not parsed.hostname:
        raise UnsafeURLError("The URL does not contain a valid host.")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs containing embedded credentials are not allowed.")

    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise UnsafeURLError("Local addresses are not allowed.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError("The host could not be resolved.") from exc

    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise UnsafeURLError("The host did not resolve to an address.")
    for address in addresses:
        try:
            if not _is_public_ip(address):
                raise UnsafeURLError("Private, local and reserved network addresses are blocked.")
        except ValueError as exc:
            raise UnsafeURLError("The host resolved to an invalid address.") from exc

    return raw_url
