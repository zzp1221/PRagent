"""Network reachability helpers for the onboarding wizard.

GitHub can only deliver a webhook to an address it can reach from the public
internet, so the wizard must know whether the configured public base URL is
actually usable before offering that path.
"""
import ipaddress
import urllib.parse
from typing import Tuple


_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}
_UNREACHABLE_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _unreachable_reason(host: str) -> str:
    """Return why a host cannot receive GitHub deliveries, or an empty string."""
    lowered = host.strip().lower().rstrip(".")
    if not lowered:
        return "公网地址为空"
    if lowered in _LOCAL_HOSTNAMES or lowered.endswith(".localhost"):
        return "当前地址是本机回环地址，GitHub 无法访问"
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        # A regular DNS name is reachable as long as it resolves publicly; the
        # wizard cannot verify DNS from here, so it trusts the operator.
        return ""
    if address.is_unspecified:
        return "当前地址是未指定地址，GitHub 无法访问"
    if address.is_loopback:
        return "当前地址是本机回环地址，GitHub 无法访问"
    if getattr(address, "ipv4_mapped", None):
        return _unreachable_reason(str(address.ipv4_mapped))
    for network in _UNREACHABLE_NETWORKS:
        if address.version == network.version and address in network:
            return "当前地址属于私有或链路本地网段，GitHub 无法访问"
    return ""


def inspect_public_base_url(url: str) -> Tuple[bool, str]:
    """Report whether a base URL can receive GitHub webhook deliveries.

    Returns a (usable, reason) tuple. The reason is always a human readable
    Chinese sentence so the console can display it unchanged.
    """
    raw = (url or "").strip()
    if not raw:
        return False, "未配置公网访问地址"
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return False, "公网访问地址格式无法解析"
    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        return False, "GitHub 要求回调地址使用 HTTPS，当前配置是 %s" % (scheme or "空协议")
    host = parsed.hostname or ""
    if not host:
        return False, "公网访问地址缺少主机名"
    reason = _unreachable_reason(host)
    if reason:
        return False, reason
    return True, ""


def webhook_endpoint(url: str) -> str:
    """Absolute webhook URL GitHub should deliver to."""
    return (url or "").strip().rstrip("/") + "/webhooks/github"
