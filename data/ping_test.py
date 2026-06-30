import os, socket, ssl, time, re, sys
from urllib.parse import urlparse
import paramiko
proxy = urlparse(os.environ["HTTPS_PROXY"])
def pconn(h,p):
    s=socket.create_connection((proxy.hostname,proxy.port),timeout=12)
    s.sendall(("CONNECT %s:%d HTTP/1.1\r\nHost:%s:%d\r\n\r\n"%(h,p,h,p)).encode())
    b=b""
    while b"\r\n\r\n" not in b:
        c=s.recv(1024); b+=c
        if not c: break
    return s
host="a.pinggy.io"
sock=pconn(host,443)
sock=ssl.create_default_context().wrap_socket(sock,server_hostname=host)
t=paramiko.Transport(sock); t.banner_timeout=30
t.start_client(timeout=25)
key=paramiko.RSAKey.generate(2048)
try:
    t.auth_publickey("auth", key)
except Exception as e:
    print("auth_publickey:", type(e).__name__, e, flush=True)
print("authenticated:", t.is_authenticated(), flush=True)
rp=t.request_port_forward("", 0)
print("remote forward port:", rp, flush=True)
chan=t.open_session(); chan.get_pty(); chan.invoke_shell()
data=b""; deadline=time.time()+15
while time.time()<deadline:
    if chan.recv_ready(): data+=chan.recv(8192)
    else: time.sleep(0.3)
sys.stdout.write("=== BANNER START ===\n"+data.decode(errors="replace")+"\n=== BANNER END ===\n")
sys.stdout.flush()
