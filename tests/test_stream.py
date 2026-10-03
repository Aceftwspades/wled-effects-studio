"""The stream's senders without the app: DDP, E1.31 (sACN) and Art-Net packets as their
standards lay them out, a frame split into universes of 170 pixels, each sent to a socket on
this machine and put back together, and the send rate the health line reads. Run with
python tests/test_stream.py  (or pytest).
"""
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from native import live_out as L                   # noqa: E402


def _listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(1.0)
    return s, s.getsockname()[1]


def _drain(s, n):
    out = []
    for _ in range(n):
        out.append(s.recvfrom(4096)[0])
    return out


def test_an_e131_packet_is_as_the_standard_lays_it_out():
    """ANSI E1.31: 126 bytes of layers then the data; the root's ID and vector 4, the framing
    layer's vector 2, the source name, priority, sequence and universe, the DMP layer's
    0x02 / 0xa1 / start 0 / increment 1 / count n + 1 and the start code 0; each layer's flags
    and length 0x7000 | the bytes from its start to the end."""
    e = L.E131Out("127.0.0.1", universe=1)
    data = bytes(range(256)) + bytes(range(254))           # 510: one full universe of RGB
    p = e.packet(7, data, 41)
    assert len(p) == 126 + 510
    assert struct.unpack("!HH", p[0:4]) == (0x0010, 0x0000) and p[4:16] == b"ASC-E1.17\x00\x00\x00"
    assert struct.unpack("!H", p[16:18])[0] == 0x7000 | (len(p) - 16) and struct.unpack("!I", p[18:22])[0] == 4
    assert p[22:38] == e.cid
    assert struct.unpack("!H", p[38:40])[0] == 0x7000 | (len(p) - 38) and struct.unpack("!I", p[40:44])[0] == 2
    assert p[44:108].rstrip(b"\x00") == b"WLED Effects Studio" and p[108] == 100
    assert p[111] == 41 and p[112] == 0 and struct.unpack("!H", p[113:115])[0] == 7
    assert struct.unpack("!H", p[115:117])[0] == 0x7000 | (len(p) - 115)
    assert p[117] == 0x02 and p[118] == 0xA1 and struct.unpack("!HHH", p[119:125]) == (0, 1, 511) and p[125] == 0
    assert p[126:] == data


def test_an_artdmx_packet_is_as_art_net_lays_it_out():
    """ArtDMX: "Art-Net", OpDmx 0x5000 low byte first, protocol 14, the sequence, the port-address
    split into SubUni and Net, the length big-endian and even (an odd one padded)."""
    a = L.ArtNetOut("127.0.0.1", universe=0)
    p = a.packet(0x1234, b"\x01\x02\x03", 9)
    assert p[:8] == b"Art-Net\x00" and p[8:10] == b"\x00\x50" and struct.unpack("!H", p[10:12])[0] == 14
    assert p[12] == 9 and p[13] == 0 and p[14] == 0x34 and p[15] == 0x12
    assert struct.unpack("!H", p[16:18])[0] == 4 and p[18:] == b"\x01\x02\x03\x00"


def test_a_frame_goes_out_a_universe_at_a_time_and_comes_back_whole():
    """1200 RGB pixels (3600 bytes) in eight universes of 170 pixels from the first universe,
    E1.31 and Art-Net alike - and DDP in packets of 480 pixels with the push flag on the last:
    each put back together where it came from is the frame."""
    frame = bytes((i * 7) & 255 for i in range(3600))
    for cls, start in ((L.E131Out, 5), (L.ArtNetOut, 0)):
        s, port = _listener()
        out = cls("127.0.0.1", start, port=port)
        out.send(frame)
        got = {}
        for p in _drain(s, 8):
            if cls is L.E131Out:
                u, n = struct.unpack("!H", p[113:115])[0], struct.unpack("!H", p[123:125])[0] - 1
                got[u] = p[126:126 + n]
            else:
                u, n = p[14] | (p[15] << 8), struct.unpack("!H", p[16:18])[0]
                got[u] = p[18:18 + n]
        assert sorted(got) == list(range(start, start + 8)), (cls.NAME, sorted(got))
        assert b"".join(got[u] for u in sorted(got))[:len(frame)] == frame, cls.NAME
        assert out.frames == 1 and out.errors == 0
        out.close(); s.close()
    s, port = _listener()
    d = L.DdpOut("127.0.0.1", port=port)
    d.send(frame)
    buf = bytearray(len(frame))
    pkts = _drain(s, 3)
    for p in pkts:
        off, n = struct.unpack("!IH", p[4:10])
        buf[off:off + n] = p[10:10 + n]
    assert bytes(buf) == frame and pkts[-1][0] & 0x01 and not pkts[0][0] & 0x01
    d.close(); s.close()


def test_each_universe_keeps_its_own_sequence():
    s, port = _listener()
    e = L.E131Out("127.0.0.1", 1, port=port)
    for _ in range(3):
        e.send(bytes(1020))                                # two universes a frame
    seqs = {}
    for p in _drain(s, 6):
        seqs.setdefault(struct.unpack("!H", p[113:115])[0], []).append(p[111])
    assert seqs == {1: [0, 1, 2], 2: [0, 1, 2]}, seqs
    s.close()


def test_the_rate_is_the_last_seconds():
    s, port = _listener()
    a = L.ArtNetOut("127.0.0.1", 0, port=port)
    for _ in range(10):
        a.send(bytes(510))
    fps, kbps = a.rate()
    assert fps == 10 and abs(kbps - 10 * (18 + 510) * 8 / 1000.0) < 1e-6, (fps, kbps)
    a._sent = type(a._sent)((t - 2.0, b) for t, b in a._sent)    # two seconds ago
    assert a.rate() == (0.0, 0.0)
    s.close()


def test_make_out_picks_the_protocol():
    assert isinstance(L.make_out("ddp", "127.0.0.1"), L.DdpOut)
    assert L.make_out("e131", "127.0.0.1:8080", 3).universe == 3 and L.make_out("e131", "127.0.0.1").universe == 1
    o = L.make_out("artnet", "127.0.0.1:8770")
    assert isinstance(o, L.ArtNetOut) and o.universe == 0 and o.ip == "127.0.0.1" and o.port == L.ARTNET_PORT


if __name__ == "__main__":                        # without pytest: every test_ function, in order
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e))
    sys.exit(1 if bad else 0)
