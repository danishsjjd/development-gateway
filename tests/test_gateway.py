"""Exercise the built Caddy binary on loopback with dummy upstreams/credentials.

Usage: CADDY_BINARY=/tmp/caddy HEALTHCHECK_BINARY=/tmp/healthcheck python3 -m unittest discover -s tests -v
"""
import base64
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path.startswith("/api/") and self.headers.get("Authorization") != "Bearer test-key":
            self.send_response(401)
            self.end_headers()
            return
        if self.headers.get("Upgrade", "").lower() == "websocket":
            accept = base64.b64encode(hashlib.sha1((self.headers["Sec-WebSocket-Key"] +
                "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "websocket")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            return
        data = json.dumps({"path": self.path, "headers": dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class GatewayHarness(unittest.TestCase):
    customized = False
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="gateway-tests-")
        cls.directory = Path(cls.temporary.name)
        for port in range(9999, 9000, -1):
            try:
                cls.backend = ThreadingHTTPServer(("127.0.0.1", port), Upstream)
                break
            except OSError:
                continue
        else:
            raise RuntimeError("No free development test port")
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        cls.http_port, cls.https_port, cls.admin_port = (unused_port() for _ in range(3))
        configuration = (ROOT / "caddy/Caddyfile").read_text()
        if "forward_auth" in configuration:
            raise RuntimeError("Caddy 2.11.4 forward_auth advisory is not remediated upstream")
        configuration = configuration.replace("172.18.0.2", "127.0.0.1").replace("172.18.0.3", "127.0.0.3")
        configuration = configuration.replace(":8080", ":" + str(cls.http_port))
        configuration = configuration.replace("{\n", "{\n\tskip_install_trust\n\thttps_port " +
            str(cls.https_port) + "\n\tadmin 127.0.0.1:" + str(cls.admin_port) + "\n", 1)
        configuration = configuration.replace("dns cloudflare {env.CLOUDFLARE_API_TOKEN}", "issuer internal")
        if cls.customized:
            endpoint = "127.0.0.1:" + str(cls.backend.server_port)
            private_handler = """@example_private host admin.local.example.com data.local.example.com app.local.example.com
    handle @example_private {
        reverse_proxy BACKEND {
            import app_proxy_headers
        }
    }
    """.replace("BACKEND", endpoint)
            public_handler = """@example_public {
        host app.example.com
        path /api/items /api/messages /api/tasks /api/results /api/results/* /api/ws
    }
    handle @example_public {
        reverse_proxy BACKEND {
            import app_proxy_headers
        }
    }
    """.replace("BACKEND", endpoint)
            configuration = configuration.replace("# Add private app handlers here, before numeric development routing.", private_handler)
            configuration = configuration.replace("# Add public app handlers here, after the checks and before the fallback.", public_handler)
        configuration = configuration.replace("host.docker.internal:", "127.0.0.1:")
        # Exercise both the upgraded CEL module and the Caddy compatibility patch.
        configuration = configuration.replace("\tencode zstd gzip", "\tencode zstd gzip\n" +
            "\t@cel expression path('/cel-test')\n\thandle @cel {\n\t\trespond \"CEL matcher works\" 200\n\t}\n", 1)
        config_path = cls.directory / "Caddyfile"
        config_path.write_text(configuration)
        environment = os.environ | {"MY_DOMAIN": "example.com", "HOME": str(cls.directory),
            "XDG_DATA_HOME": str(cls.directory / "data"), "XDG_CONFIG_HOME": str(cls.directory / "config")}
        # Never pass production credentials into the test process.
        environment.pop("CLOUDFLARE_API_TOKEN", None)
        cls.log = (cls.directory / "caddy.log").open("w")
        cls.process = subprocess.Popen([os.environ["CADDY_BINARY"], "run", "--config", str(config_path),
            "--adapter", "caddyfile"], env=environment, stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.cleanup)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise RuntimeError((cls.directory / "caddy.log").read_text())
            try:
                with socket.create_connection(("127.0.0.1", cls.https_port), timeout=.2):
                    break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("Test Caddy did not start")
        root_certificate = cls.directory / "data/caddy/pki/authorities/local/root.crt"
        cls.tls_context = ssl.create_default_context(cafile=str(root_certificate))

    @classmethod
    def cleanup(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.log.close()
        cls.temporary.cleanup()

    def request(self, host, path="/", *, private=False, peer="127.0.0.3", headers=None):
        request_headers = {"Host": host, "X-Forwarded-Proto": "https"} | (headers or {})
        if private:
            connection = http.client.HTTPSConnection(host, self.https_port, timeout=5, context=self.tls_context)
            # Connect on loopback while verifying the actual wildcard hostname.
            connection.sock = self.tls_context.wrap_socket(socket.create_connection(
                ("127.0.0.1", self.https_port), timeout=5, source_address=(peer, 0)), server_hostname=host)
        else:
            connection = http.client.HTTPConnection("127.0.0.1", self.http_port, timeout=5, source_address=(peer, 0))
        try:
            connection.request("GET", path, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.headers), response.read()
        finally:
            connection.close()

class ExampleRoutesTests(GatewayHarness):
    customized = True

    def test_only_tunnel_peer_can_use_public_listener(self):
        status, _, _ = self.request("app.example.com", "/api/items", peer="127.0.0.4",
            headers={"CF-Connecting-IP": "127.0.0.3", "X-Forwarded-For": "127.0.0.3"})
        self.assertEqual(status, 403)

    def test_http_visitors_redirect_before_proxying(self):
        status, headers, _ = self.request("app.example.com", "/api/items?x=1", headers={"X-Forwarded-Proto": "http"})
        self.assertEqual(status, 308)
        self.assertEqual(headers["Location"], "https://app.example.com/api/items?x=1")

    def test_public_api_authentication_and_allowlist(self):
        for path in ["/api/items", "/api/messages", "/api/tasks", "/api/results", "/api/results/test"]:
            with self.subTest(path=path):
                self.assertEqual(self.request("app.example.com", path)[0], 401)
                self.assertEqual(self.request("app.example.com", path, headers={"Authorization": "Bearer test-key"})[0], 200)
        for path in ["/admin", "/api/admin", "/api/items/extra", "/api/results-extra"]:
            with self.subTest(path=path):
                self.assertEqual(self.request("app.example.com", path, headers={"Authorization": "Bearer test-key"})[0], 404)

    def test_private_admin_apps_stay_off_public_listener(self):
        for host in ["admin.example.com", "data.example.com", "admin.local.example.com", "data.local.example.com"]:
            self.assertEqual(self.request(host)[0], 404)
        for host in ["admin.local.example.com", "data.local.example.com", "app.local.example.com"]:
            self.assertEqual(self.request(host, private=True, peer="127.0.0.4")[0], 200)

    def test_forwarded_headers_are_sanitized(self):
        supplied = {"Authorization": "Bearer test-key", "CF-Connecting-IP": "203.0.113.9",
            "X-Forwarded-For": "198.51.100.88", "X-Real-IP": "198.51.100.88",
            "Forwarded": "for=198.51.100.88", "True-Client-IP": "198.51.100.88", "CF-Connecting-IPv6": "::1"}
        status, _, body = self.request("app.example.com", "/api/items", headers=supplied)
        self.assertEqual(status, 200)
        received = {key.lower(): value for key, value in json.loads(body)["headers"].items()}
        for field in ["x-forwarded-for", "x-real-ip", "cf-connecting-ip"]:
            self.assertEqual(received[field], "203.0.113.9")
        self.assertEqual(received["x-forwarded-proto"], "https")
        self.assertEqual(received["host"], "app.example.com")
        self.assertTrue({"forwarded", "true-client-ip", "cf-connecting-ipv6"}.isdisjoint(received))
        status, _, body = self.request("admin.local.example.com", private=True, peer="127.0.0.4", headers=supplied)
        self.assertEqual(status, 200)
        received = {key.lower(): value for key, value in json.loads(body)["headers"].items()}
        self.assertEqual(received["x-real-ip"], "127.0.0.4")

    def test_development_host_routing_and_unknown_hosts(self):
        host = str(self.backend.server_port) + ".local.example.com"
        status, _, body = self.request(host, private=True)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["headers"]["Host"], "localhost:" + str(self.backend.server_port))
        self.assertEqual(self.request("unknown.local.example.com", private=True)[0], 404)
        self.assertEqual(self.request("unknown.example.com")[0], 404)

    def test_websocket_upgrade_preserves_authentication(self):
        headers = {"Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="}
        self.assertEqual(self.request("app.example.com", "/api/ws", headers=headers)[0], 401)
        status, received, _ = self.request("app.example.com", "/api/ws", headers=headers | {"Authorization": "Bearer test-key"})
        self.assertEqual(status, 101)
        self.assertEqual({key.lower(): value for key, value in received.items()}["sec-websocket-accept"], "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_distroless_healthcheck(self):
        binary = os.environ["HEALTHCHECK_BINARY"]
        self.assertEqual(subprocess.run([binary, "http://127.0.0.1:" + str(self.admin_port) + "/config/"], capture_output=True).returncode, 0)
        self.assertNotEqual(subprocess.run([binary, "http://127.0.0.1:" + str(self.http_port) + "/"], capture_output=True).returncode, 0)

    def test_patched_cel_expression_matcher(self):
        status, _, body = self.request("unknown.local.example.com", "/cel-test", private=True)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"CEL matcher works")


class TemplateDefaultsTests(GatewayHarness):
    def test_public_template_denies_every_host_and_path(self):
        for host in ["app.example.com", "admin.local.example.com", "unknown.example.com"]:
            for path in ["/", "/api/items", "/api/ws", "/admin"]:
                with self.subTest(host=host, path=path):
                    self.assertEqual(self.request(host, path, headers={"Authorization": "Bearer test-key"})[0], 404)
        self.assertEqual(self.request("app.example.com", peer="127.0.0.4")[0], 403)
        status, headers, _ = self.request("app.example.com", headers={"X-Forwarded-Proto": "http"})
        self.assertEqual(status, 308)
        self.assertEqual(headers["Location"], "https://app.example.com/")

    def test_private_template_allows_only_development_range(self):
        host = str(self.backend.server_port) + ".local.example.com"
        status, _, body = self.request(host, private=True)
        self.assertEqual(status, 200)
        received = json.loads(body)["headers"]
        self.assertEqual(received["Host"], "localhost:" + str(self.backend.server_port))
        self.assertEqual(received["X-Forwarded-Proto"], "https")
        for host in ["2999.local.example.com", "10000.local.example.com", "admin.local.example.com"]:
            self.assertEqual(self.request(host, private=True)[0], 404)

    def test_default_configuration_supports_health_and_patched_cel(self):
        binary = os.environ["HEALTHCHECK_BINARY"]
        self.assertEqual(subprocess.run([binary, "http://127.0.0.1:" + str(self.admin_port) + "/config/"], capture_output=True).returncode, 0)
        status, _, body = self.request("unknown.local.example.com", "/cel-test", private=True)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"CEL matcher works")
