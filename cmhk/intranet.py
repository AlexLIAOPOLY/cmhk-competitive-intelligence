from __future__ import annotations

import ipaddress
import shutil
import socket
import subprocess
from collections.abc import Iterable


_RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_IGNORED_INTERFACE_PREFIXES = (
    "lo",
    "utun",
    "awdl",
    "llw",
    "bridge",
    "anpi",
    "gif",
    "stf",
    "ap",
)


def is_rfc1918_address(value: str) -> bool:
    """Return whether value is an RFC1918 IPv4 address suitable for LAN sharing."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network for network in _RFC1918_NETWORKS
    )


def parse_ifconfig_ipv4(output: str) -> list[tuple[str, str]]:
    """Extract interface/IPv4 pairs from macOS and BSD-style ifconfig output."""
    addresses: list[tuple[str, str]] = []
    interface = ""
    for raw_line in output.splitlines():
        if raw_line and not raw_line[0].isspace() and ":" in raw_line:
            interface = raw_line.split(":", 1)[0].strip()
            continue
        fields = raw_line.strip().split()
        if interface and len(fields) >= 2 and fields[0] == "inet":
            addresses.append((interface, fields[1]))
    return addresses


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def discover_intranet_ipv4_addresses() -> list[str]:
    """Discover physical-interface RFC1918 addresses, preferring normal LAN adapters."""
    candidates: list[tuple[str, str]] = []
    ifconfig = shutil.which("ifconfig")
    if ifconfig:
        try:
            completed = subprocess.run(
                [ifconfig],
                capture_output=True,
                check=False,
                text=True,
                timeout=3,
            )
            candidates.extend(parse_ifconfig_ipv4(completed.stdout))
        except (OSError, subprocess.SubprocessError):
            pass

    candidates = [
        (interface, address)
        for interface, address in candidates
        if is_rfc1918_address(address)
        and not interface.lower().startswith(_IGNORED_INTERFACE_PREFIXES)
    ]
    candidates.sort(
        key=lambda item: (
            0 if item[0].lower().startswith(("en", "eth", "wlan", "wl")) else 1,
            item[0],
            ipaddress.ip_address(item[1]),
        )
    )
    addresses = _unique(address for _, address in candidates)
    if addresses:
        return addresses

    try:
        fallback = (
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        )
        return _unique(address for address in fallback if is_rfc1918_address(address))
    except OSError:
        return []


def intranet_access_urls(port: int, *, host: str = "0.0.0.0") -> list[str]:
    """Build usable intranet URLs for a wildcard or explicitly bound host."""
    normalized_host = str(host).strip()
    if normalized_host not in {"", "0.0.0.0", "::"}:
        return [f"http://{normalized_host}:{port}"]
    return [f"http://{address}:{port}" for address in discover_intranet_ipv4_addresses()]
