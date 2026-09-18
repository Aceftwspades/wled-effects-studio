"""WLED's live view ("Peek") over its websocket: one frame of LED colours,
the way the web UI's Peek gets them - {"lv":true} on /ws, then binary
frames: 'L', version (2 for a matrix), width, height, RGB triples. A
matrix over 1024 LEDs comes every nth pixel (a 48 x 48 net as 24 x 24).

    python tests/peek.py <host> [out.png]      # prints the size, saves the frame 8x

What the cube actually shows, for checking a script or a flash against
the sim; stdlib only.
"""
import base64, os, socket, struct, sys, json

def ws_connect(host, port=80, path="/ws"):
    s = socket.create_connection((host, port), timeout=8)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    head, rest = buf.split(b"\r\n\r\n", 1)
    assert b" 101 " in head.split(b"\r\n")[0], head
    return s, rest

def ws_send(s, text):
    data = text.encode()
    mask = os.urandom(4)
    hdr = bytes([0x81])
    n = len(data)
    if n < 126:
        hdr += bytes([0x80 | n])
    else:
        hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

def ws_recv(s, rest):
    buf = rest
    def need(n):
        nonlocal buf
        while len(buf) < n:
            chunk = s.recv(65536)
            if not chunk:
                raise EOFError
            buf += chunk
    while True:
        need(2)
        b0, b1 = buf[0], buf[1]
        op = b0 & 0x0F
        n = b1 & 0x7F
        p = 2
        if n == 126:
            need(4); n = struct.unpack(">H", buf[2:4])[0]; p = 4
        elif n == 127:
            need(10); n = struct.unpack(">Q", buf[2:10])[0]; p = 10
        need(p + n)
        payload = buf[p:p + n]
        buf = buf[p + n:]
        if op == 2:
            return payload, buf
        if op == 1:
            continue                      # JSON state: ignore
        if op == 8:
            raise EOFError("closed")

def peek(host):
    s, rest = ws_connect(host)
    ws_send(s, '{"lv":true}')
    for _ in range(3):
        frame, rest = ws_recv(s, rest)
    s.close()
    return frame

if __name__ == "__main__":
    host = sys.argv[1]
    f = peek(host)
    print("frame", len(f), "bytes; header", list(f[:4]))
    if f[0] == ord("L"):
        ver = f[1]
        if ver == 2:
            w, h = f[2], f[3]
            px = f[4:]
            print(f"2-D live view {w} x {h}, {len(px)//3} pixels")
            if len(sys.argv) > 2:
                from PIL import Image
                img = Image.frombytes("RGB", (w, h), bytes(px[:w * h * 3]))
                img = img.resize((w * 8, h * 8), Image.NEAREST)
                img.save(sys.argv[2]); print("saved", sys.argv[2])
        else:
            px = f[2:]
            print(f"1-D live view, {len(px)//3} pixels")
