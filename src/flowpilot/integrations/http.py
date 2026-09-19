import http.client
import ipaddress
import json
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from flowpilot.errors import ExecutionError


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: Any
    headers: dict[str, str]


class HttpTransport(Protocol):
    def request(self, method: str, url: str, headers: dict[str, str], body: Any, timeout: int) -> HttpResult: ...


def validate_url(url: str, allowed_hosts: set[str]) -> tuple[str, str]:
    if any(ord(char) <= 32 or ord(char) == 127 for char in url) or "\\" in url:
        raise ExecutionError("egress_url_invalid")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as error:
        raise ExecutionError("egress_url_invalid") from error
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment or port not in (None, 443):
        raise ExecutionError("egress_url_invalid")
    if host not in allowed_hosts or host.endswith(".") or "%" in host:
        raise ExecutionError("egress_host_denied")
    try:
        host.encode("ascii")
    except UnicodeEncodeError as error:
        raise ExecutionError("egress_url_invalid") from error
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return host, path


def public_addresses(host: str) -> list[str]:
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    except OSError as error:
        raise ExecutionError("dns_unavailable", retryable=True) from error
    if not addresses:
        raise ExecutionError("dns_unavailable", retryable=True)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        transition = isinstance(ip, ipaddress.IPv6Address) and (
            ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None
            or ip in ipaddress.ip_network("64:ff9b::/96")
        )
        if not ip.is_global or ip.is_multicast or transition:
            raise ExecutionError("egress_address_denied")
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: int):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the validated address, but validate the TLS certificate against the hostname.
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class SafeHttpTransport:
    def __init__(self, allowed_hosts: list[str], max_bytes: int):
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.max_bytes = max_bytes

    def request(self, method: str, url: str, headers: dict[str, str], body: Any, timeout: int) -> HttpResult:
        host, path = validate_url(url, self.allowed_hosts)
        address = public_addresses(host)[0]
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        if data is not None and len(data) > 65536:
            raise ExecutionError("request_body_too_large")
        outgoing = {"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "FlowPilot/0.1", **headers}
        if data is not None:
            outgoing["Content-Type"] = "application/json"
        connection = PinnedHTTPSConnection(host, address, timeout)
        deadline = time.monotonic() + timeout
        try:
            connection.request(method, path, body=data, headers=outgoing)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ExecutionError("redirect_denied")
            if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
                raise ExecutionError("response_encoding_denied")
            chunks = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                if connection.sock:
                    connection.sock.settimeout(remaining)
                piece = response.read1(min(16384, self.max_bytes + 1 - len(chunks)))
                if not piece:
                    break
                chunks.extend(piece)
                if len(chunks) > self.max_bytes:
                    raise ExecutionError("response_too_large")
            try:
                content = json.loads(chunks) if chunks else None
            except (ValueError, UnicodeDecodeError):
                content = chunks.decode("utf-8", errors="replace")
            selected = {key.lower(): value for key, value in response.getheaders() if key.lower() in {"content-type", "retry-after", "x-request-id"}}
            return HttpResult(response.status, content, selected)
        except ssl.SSLCertVerificationError as error:
            raise ExecutionError("tls_certificate_invalid") from error
        except (TimeoutError, socket.timeout) as error:
            raise ExecutionError("upstream_timeout", retryable=True) from error
        except (OSError, http.client.HTTPException) as error:
            raise ExecutionError("upstream_unavailable", retryable=True) from error
        finally:
            connection.close()


def require_success(result: HttpResult, allow_retry: bool = True) -> None:
    if 200 <= result.status < 300:
        return
    retry_after = None
    value = result.headers.get("retry-after", "")
    if value.isdigit():
        retry_after = min(float(value), 300)
    raise ExecutionError(f"upstream_http_{result.status}", retryable=allow_retry and (result.status == 429 or result.status >= 500), retry_after=retry_after)
