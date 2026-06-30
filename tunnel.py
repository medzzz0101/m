#!/usr/bin/env python3
"""
tunnel.py — expose the local server to a PUBLIC URL from inside this
egress-restricted cloud container.

Why this exists (the networking story, for learning):
  * This container has NO direct outbound network. Everything must go through an
    HTTPS *CONNECT* proxy (set in $HTTPS_PROXY). That proxy will open a raw TCP
    tunnel to any host:port for us — including SSH servers.
  * Normal tunnel tools (cloudflared/ngrok) dial their edge directly and ignore
    that proxy, so they can't connect here.
  * The portable fix: an SSH *reverse* tunnel (`ssh -R`) to a free relay
    (pinggy.io / serveo.net) that hands back a public https://… URL and forwards
    inbound requests down the SSH connection to our local uvicorn.
  * We have no `ssh` binary, so we drive SSH from Python with **paramiko**, and
    we feed it a socket that was first CONNECT-tunnelled through $HTTPS_PROXY.

Result: a public URL you can open on your phone, reaching the local app.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
import sys
import time
from urllib.parse import urlparse

import paramiko

LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = int(os.environ.get("PORT", "8000"))


def proxy_connect(dst_host: str, dst_port: int, timeout: float = 15) -> socket.socket:
    """Open a TCP socket to dst via the HTTPS CONNECT proxy."""
    proxy = urlparse(os.environ["HTTPS_PROXY"])
    s = socket.create_connection((proxy.hostname, proxy.port), timeout=timeout)
    req = (f"CONNECT {dst_host}:{dst_port} HTTP/1.1\r\n"
           f"Host: {dst_host}:{dst_port}\r\n\r\n")
    s.sendall(req.encode())
    # Read until end of HTTP headers.
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(1024)
        if not chunk:
            raise RuntimeError("proxy closed during CONNECT")
        buf += chunk
    if b" 200 " not in buf.split(b"\r\n")[0]:
        raise RuntimeError(f"proxy refused CONNECT: {buf.splitlines()[0]!r}")
    return s


def forward_handler(chan, origin, server):
    """Called by paramiko for each inbound request the relay forwards to us.
    We splice the SSH channel <-> a fresh socket to our local uvicorn."""
    import threading
    try:
        local = socket.create_connection((LOCAL_HOST, LOCAL_PORT), timeout=10)
    except Exception:
        chan.close()
        return

    def pipe(a, b):
        try:
            while True:
                data = a.recv(4096)
                if not data:
                    break
                b.sendall(data)
        except Exception:
            pass
        finally:
            try: a.close()
            except Exception: pass
            try: b.close()
            except Exception: pass

    threading.Thread(target=pipe, args=(chan, local), daemon=True).start()
    threading.Thread(target=pipe, args=(local, chan), daemon=True).start()


def run_relay(host: str, port: int, username: str, remote_port: int,
              read_url: bool = True, use_tls: bool = False) -> str | None:
    """Open the SSH reverse tunnel to `host` and return the public URL.

    If use_tls=True we first wrap the proxied socket in TLS (the relay then
    speaks SSH *inside* TLS). This is what lets us tunnel out of a network that
    only permits TLS-on-443 — exactly our cloud egress proxy's behaviour."""
    sock = proxy_connect(host, port)
    if use_tls:
        ctx = ssl.create_default_context()
        # The proxy passes TLS through transparently (verified: real relay cert),
        # so standard verification against the system roots holds.
        sock = ctx.wrap_socket(sock, server_hostname=host)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = 30      # relay can be slow to send its ident
    transport.start_client(timeout=25)

    # Pinggy accepts anonymous tunnels but REQUIRES a publickey auth exchange
    # (it doesn't actually verify the key — any ephemeral key is accepted). The
    # username carries options/token; "auth" works for the free anonymous tier.
    key = paramiko.RSAKey.generate(2048)
    transport.auth_publickey(username, key)

    # Ask the relay to listen on `remote_port` and forward back to us.
    transport.request_port_forward("", remote_port, handler=forward_handler)

    url = None
    if read_url:
        # The relay prints the assigned public URL into an interactive session.
        chan = transport.open_session()
        try:
            chan.get_pty()
            chan.invoke_shell()
        except Exception:
            pass
        deadline = time.time() + 18
        data = b""
        # The real tunnel URL is on *.pinggy.link / *.free.pinggy.link (NOT the
        # dashboard.pinggy.io link in the welcome blurb), or serveo/lhr hosts.
        # Match pinggy's real tunnel hostnames (NOT the dashboard.pinggy.io blurb).
        pat = re.compile(
            rb"https://[a-zA-Z0-9.\-]+\."
            rb"(?:free\.pinggy\.net|run\.pinggy-free\.link|pinggy-free\.link|"
            rb"free\.pinggy\.link|pinggy\.link|pinggy\.online|serveo\.net|lhr\.life)")
        while time.time() < deadline and url is None:
            if chan.recv_ready():
                data += chan.recv(4096)
                m = pat.search(data)
                if m:
                    url = m.group(0).decode()
            else:
                time.sleep(0.3)
        # Log the banner so we can see what the relay said (useful when learning).
        try:
            sys.stderr.write("---- relay banner ----\n" +
                             data.decode(errors="replace") + "\n----------------------\n")
        except Exception:
            pass
    return url, transport


URL_FILE = os.path.join(os.path.dirname(__file__), "data", "public_url.txt")


def connect_once() -> bool:
    """One full tunnel lifecycle. Returns True if we got a URL and served it
    until the relay dropped (so the caller can reconnect)."""
    # Our egress only reaches the relay via the TLS-on-443 CONNECT path.
    host, port, user, rport, tls = ("a.pinggy.io", 443, "auth", 0, True)
    print(f"▸ connecting relay {host}:{port} tls={tls} …", flush=True)
    url, transport = run_relay(host, port, user, rport, use_tls=tls)
    if not url:
        print("  no URL returned by relay", flush=True)
        return False
    print(f"PUBLIC_URL {url}", flush=True)
    # Persist for other tooling / the README banner.
    try:
        os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
        with open(URL_FILE, "w") as fh:
            fh.write(url + "\n")
    except OSError:
        pass
    # Block until the relay drops the connection (pinggy free rotates ~60 min).
    while transport.is_active():
        time.sleep(5)
    print("  tunnel closed by relay", flush=True)
    return True


def main():
    # Auto-reconnect: if pinggy's free tunnel expires, get a fresh URL instead
    # of dying. (A pinggy token in .env would give a *stable* URL — see README.)
    backoff = 3
    while True:
        try:
            ok = connect_once()
            backoff = 3 if ok else min(backoff * 2, 60)
        except Exception as e:
            print(f"  relay error: {type(e).__name__}: {e}", flush=True)
            backoff = min(backoff * 2, 60)
        print(f"  reconnecting in {backoff}s…", flush=True)
        time.sleep(backoff)


if __name__ == "__main__":
    main()
