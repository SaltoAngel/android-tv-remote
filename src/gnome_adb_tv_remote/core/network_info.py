from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class InterfaceNetwork:
    ifname: str
    ip: ipaddress.IPv4Address
    network: ipaddress.IPv4Network


def get_ipv4_interface_networks(limit_to_slash24_if_broader: bool = True) -> list[InterfaceNetwork]:
    """Return private IPv4 networks derived from local interfaces.

    If an interface network is broader than /24 (e.g. /16), we default to scanning
    only a /24 around the interface IP for safety and speed.
    """
    out: list[InterfaceNetwork] = []
    addrs = psutil.net_if_addrs()

    for ifname, items in addrs.items():
        for a in items:
            if getattr(a, "family", None) != socket.AF_INET:
                continue

            ip_s = getattr(a, "address", None)
            mask_s = getattr(a, "netmask", None)
            if not ip_s or not mask_s:
                continue

            try:
                ip = ipaddress.IPv4Address(ip_s)
            except ValueError:
                continue

            if ip.is_loopback or ip.is_link_local:
                continue

            try:
                iface = ipaddress.IPv4Interface(f"{ip_s}/{mask_s}")
            except ValueError:
                continue

            net = iface.network
            if not net.is_private:
                continue

            if limit_to_slash24_if_broader and net.prefixlen < 24:
                net = ipaddress.ip_network(f"{ip}/24", strict=False)

            out.append(InterfaceNetwork(ifname=ifname, ip=ip, network=net))

    # De-duplicate by network
    uniq: dict[str, InterfaceNetwork] = {}
    for item in out:
        uniq[str(item.network)] = item

    return sorted(uniq.values(), key=lambda x: (int(x.network.network_address), x.network.prefixlen))


