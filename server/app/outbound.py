from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class OutboundRequestError(RuntimeError):
    pass


class _ConnectionAttemptError(OutboundRequestError):
    pass


@dataclass(frozen=True)
class ResolvedEndpoint:
    normalized_url: str
    scheme: str
    hostname: str
    port: int
    base_path: str
    addresses: tuple[str, ...]

    def request_path(self, suffix: str) -> str:
        tail = str(suffix or "").lstrip("/")
        base = self.base_path.rstrip("/")
        path = f"{base}/{tail}" if tail else (base or "/")
        return path if path.startswith("/") else f"/{path}"

    @property
    def host_header(self) -> str:
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        default_port = 443 if self.scheme == "https" else 80
        return host if self.port == default_port else f"{host}:{self.port}"


@dataclass(frozen=True)
class PinnedResponse:
    status_code: int
    body: bytes

    def raise_for_status(self) -> None:
        if 200 <= self.status_code < 300:
            return
        raise OutboundRequestError(f"AI 服务返回 HTTP {self.status_code}")

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OutboundRequestError("AI 服务返回了无效 JSON") from exc


def _normalize_hostname(hostname: str) -> str:
    candidate = hostname.split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        try:
            return candidate.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("AI Base URL 主机名无效") from exc


def resolve_ai_endpoint(value: str, allow_private: bool = False) -> ResolvedEndpoint:
    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("AI Base URL 不能为空")
    try:
        parsed = urlsplit(raw)
        explicit_port = parsed.port
    except ValueError as exc:
        raise ValueError("AI Base URL 格式无效") from exc
    allowed_schemes = {"http", "https"} if allow_private else {"https"}
    if parsed.scheme not in allowed_schemes:
        raise ValueError("AI Base URL 必须使用 HTTPS")
    if not parsed.hostname:
        raise ValueError("AI Base URL 缺少主机名")
    if parsed.username or parsed.password:
        raise ValueError("AI Base URL 不能包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("AI Base URL 不能包含查询参数或片段")

    hostname = _normalize_hostname(parsed.hostname)
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    try:
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("AI Base URL 主机无法解析") from exc
    addresses = []
    for info in resolved:
        address = info[4][0].split("%", 1)[0]
        try:
            parsed_ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("AI Base URL 主机解析结果无效") from exc
        if not allow_private and not parsed_ip.is_global:
            raise ValueError("AI Base URL 必须解析到公网地址")
        normalized_ip = parsed_ip.compressed
        if normalized_ip not in addresses:
            addresses.append(normalized_ip)
    if not addresses:
        raise ValueError("AI Base URL 主机无法解析")

    url_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = url_host if explicit_port is None or port == default_port else f"{url_host}:{port}"
    base_path = parsed.path.rstrip("/")
    normalized_url = urlunsplit((parsed.scheme, netloc, base_path, "", ""))
    return ResolvedEndpoint(
        normalized_url=normalized_url,
        scheme=parsed.scheme,
        hostname=hostname,
        port=port,
        base_path=base_path,
        addresses=tuple(addresses),
    )


def validate_ai_base_url(value: str, allow_private: bool = False) -> str:
    return resolve_ai_endpoint(value, allow_private).normalized_url


def _connect_ip(address: str, port: int, timeout: float):
    parsed_ip = ipaddress.ip_address(address)
    family = socket.AF_INET6 if parsed_ip.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    target = (parsed_ip.compressed, port, 0, 0) if parsed_ip.version == 6 else (parsed_ip.compressed, port)
    try:
        sock.connect(target)
        return sock
    except Exception:
        sock.close()
        raise


def _open_connection(endpoint: ResolvedEndpoint, address: str, timeout: float):
    raw_socket = _connect_ip(address, endpoint.port, timeout)
    transport_socket = raw_socket
    try:
        if endpoint.scheme == "https":
            transport_socket = ssl.create_default_context().wrap_socket(
                raw_socket,
                server_hostname=endpoint.hostname,
            )
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=timeout)
        connection.sock = transport_socket
        return connection
    except Exception:
        raw_socket.close()
        raise


def _request_once(
    endpoint: ResolvedEndpoint,
    address: str,
    path: str,
    headers: dict,
    payload: dict,
    timeout: float,
) -> PinnedResponse:
    request_headers = {
        **headers,
        "Host": endpoint.host_header,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "close",
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        connection = _open_connection(endpoint, address, timeout)
    except (OSError, ssl.SSLError) as exc:
        raise _ConnectionAttemptError(str(exc)) from exc
    try:
        connection.request("POST", path, body=body, headers=request_headers)
        response = connection.getresponse()
        response_body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(response_body) > _MAX_RESPONSE_BYTES:
            raise OutboundRequestError("AI 服务响应过大")
        return PinnedResponse(response.status, response_body)
    except OutboundRequestError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise OutboundRequestError("AI 服务请求失败") from exc
    finally:
        connection.close()


def post_json(
    endpoint: ResolvedEndpoint,
    suffix: str,
    headers: dict,
    payload: dict,
    timeout: float = 40,
) -> PinnedResponse:
    path = endpoint.request_path(suffix)
    failures = []
    for address in endpoint.addresses:
        try:
            return _request_once(endpoint, address, path, headers, payload, timeout)
        except _ConnectionAttemptError as exc:
            failures.append(f"{address}: {exc}")
    detail = "; ".join(failures) if failures else "无可用地址"
    raise OutboundRequestError(f"无法连接 AI 服务：{detail}")
