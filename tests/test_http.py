import socket

import pytest

from flowpilot.errors import ExecutionError
from flowpilot.integrations.http import HttpResult, public_addresses, require_success, validate_url


@pytest.mark.parametrize('url', [
    'http://api.example.com/data', 'https://api.example.com:444/data',
    'https://api.example.com@evil.example/data', 'https://api.example.com\\@evil.example/',
    'https://api.example.com./data', 'https://api.example.com/#fragment',
    'https://127.0.0.1/', 'https://169.254.169.254/latest/meta-data/',
    'file:///etc/passwd', 'https://api.example.com/\r\nHost:evil.example',
    'https://sub.api.example.com/', 'https://user:pass@api.example.com/',
])
def test_unsafe_url_is_rejected(url):
    with pytest.raises(ExecutionError):
        validate_url(url, {'api.example.com'})


def test_valid_url_preserves_query_not_fragment():
    assert validate_url('https://api.example.com/data?q=two%20words', {'api.example.com'}) == ('api.example.com', '/data?q=two%20words')


@pytest.mark.parametrize('address', ['127.0.0.1', '10.1.1.1', '172.16.0.1', '192.168.1.1', '169.254.169.254', '::1', 'fc00::1', '::ffff:127.0.0.1', '224.0.0.1', '2002:7f00:1::', '64:ff9b::7f00:1'])
def test_dns_private_addresses_rejected(monkeypatch, address):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))])
    with pytest.raises(ExecutionError, match='egress_address_denied'):
        public_addresses('api.example.com')


def test_any_private_dns_answer_rejects_whole_set(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [(socket.AF_INET, 1, 6, '', (ip, 443)) for ip in ['93.184.216.34', '127.0.0.1']])
    with pytest.raises(ExecutionError):
        public_addresses('api.example.com')


def test_public_dns_answer_accepted(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [(socket.AF_INET, 1, 6, '', ('93.184.216.34', 443))])
    assert public_addresses('api.example.com') == ['93.184.216.34']


@pytest.mark.parametrize('status,retryable', [(200, False), (400, False), (401, False), (429, True), (500, True), (503, True)])
def test_status_classification(status, retryable):
    if status == 200:
        require_success(HttpResult(status, {}, {}))
        return
    with pytest.raises(ExecutionError) as error:
        require_success(HttpResult(status, {}, {'retry-after': '900'}))
    assert error.value.retryable is retryable
    assert error.value.retry_after == 300

class StubResponse:
    def __init__(self, status=200, payload=b'{"accepted":true}', headers=None):
        self.status = status
        self.payload = payload
        self.offset = 0
        self.headers = headers or {'Content-Type': 'application/json'}

    def getheader(self, name, default=None):
        return next((value for key, value in self.headers.items() if key.lower() == name.lower()), default)

    def getheaders(self):
        return list(self.headers.items())

    def read1(self, size):
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class StubConnection:
    def __init__(self, response, error=None):
        self.response = response
        self.error = error
        self.sock = None
        self.closed = False
        self.sent = None

    def request(self, method, path, body=None, headers=None):
        self.sent = (method, path, body, headers)
        if self.error:
            raise self.error

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def configured_transport(monkeypatch, response, error=None, limit=1024):
    from flowpilot.integrations import http
    connection = StubConnection(response, error)
    monkeypatch.setattr(http, 'public_addresses', lambda host: ['93.184.216.34'])
    monkeypatch.setattr(http, 'PinnedHTTPSConnection', lambda *args: connection)
    return http.SafeHttpTransport(['api.example.com'], limit), connection


def test_transport_encodes_json_and_omits_upstream_cookies(monkeypatch):
    response = StubResponse(headers={'Content-Type': 'application/json', 'Set-Cookie': 'secret=value', 'X-Request-ID': 'req-1'})
    transport, connection = configured_transport(monkeypatch, response)
    result = transport.request('POST', 'https://api.example.com/items?q=1', {}, {'name': 'é'}, 3)
    assert result.body == {'accepted': True}
    assert result.headers == {'content-type': 'application/json', 'x-request-id': 'req-1'}
    assert connection.sent[1] == '/items?q=1'
    assert connection.sent[3]['Accept-Encoding'] == 'identity'
    assert connection.closed


@pytest.mark.parametrize('status,payload,headers,expected', [
    (302, b'', {'Location': 'http://127.0.0.1'}, 'redirect_denied'),
    (200, b'compressed', {'Content-Encoding': 'gzip'}, 'response_encoding_denied'),
    (200, b'x' * 1025, {}, 'response_too_large'),
])
def test_transport_rejects_unsafe_responses(monkeypatch, status, payload, headers, expected):
    transport, connection = configured_transport(monkeypatch, StubResponse(status, payload, headers))
    with pytest.raises(ExecutionError, match=expected):
        transport.request('GET', 'https://api.example.com/', {}, None, 3)
    assert connection.closed


@pytest.mark.parametrize('payload,expected', [(b'', None), (b'hello', 'hello'), (b'\xff', '\ufffd')])
def test_transport_handles_empty_and_text_responses(monkeypatch, payload, expected):
    transport, connection = configured_transport(monkeypatch, StubResponse(payload=payload))
    assert transport.request('GET', 'https://api.example.com/', {}, None, 3).body == expected
    assert connection.closed


@pytest.mark.parametrize('error,code,retryable', [
    (TimeoutError(), 'upstream_timeout', True),
    (ConnectionResetError(), 'upstream_unavailable', True),
])
def test_transport_sanitizes_connection_errors(monkeypatch, error, code, retryable):
    transport, connection = configured_transport(monkeypatch, StubResponse(), error)
    with pytest.raises(ExecutionError) as caught:
        transport.request('GET', 'https://api.example.com/', {}, None, 3)
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert connection.closed


def test_transport_rejects_oversized_request_before_connect(monkeypatch):
    transport, connection = configured_transport(monkeypatch, StubResponse())
    with pytest.raises(ExecutionError, match='request_body_too_large'):
        transport.request('POST', 'https://api.example.com/', {}, {'x': 'x' * 65536}, 3)
    assert connection.sent is None


def test_transport_rejects_bad_tls_without_retry(monkeypatch):
    import ssl
    transport, connection = configured_transport(monkeypatch, StubResponse(), ssl.SSLCertVerificationError('bad certificate'))
    with pytest.raises(ExecutionError) as caught:
        transport.request('GET', 'https://api.example.com/', {}, None, 3)
    assert caught.value.code == 'tls_certificate_invalid'
    assert caught.value.retryable is False
    assert connection.closed


def test_pinned_connection_uses_validated_ip_and_original_tls_host(monkeypatch):
    from unittest.mock import Mock
    from flowpilot.integrations import http
    sock, context = Mock(), Mock()
    create = Mock(return_value=sock)
    monkeypatch.setattr(http.socket, 'create_connection', create)
    monkeypatch.setattr(http.ssl, 'create_default_context', lambda: context)
    connection = http.PinnedHTTPSConnection('api.example.com', '93.184.216.34', 5)
    connection.connect()
    create.assert_called_once_with(('93.184.216.34', 443), 5)
    context.wrap_socket.assert_called_once_with(sock, server_hostname='api.example.com')


def test_dns_resolution_error_is_retryable(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror('unavailable')
    monkeypatch.setattr(socket, 'getaddrinfo', fail)
    with pytest.raises(ExecutionError) as caught:
        public_addresses('api.example.com')
    assert caught.value.retryable
