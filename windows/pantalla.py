#!/usr/bin/env python3
"""
Pantalla Extra - emisor para Windows.

Captura una pantalla de Windows (normalmente la pantalla virtual creada por
Virtual Display Driver), la codifica en H.264 con el chip de video de la laptop
y la envía al iPad por el cable USB-C, usando el servicio de Apple que viene
con la app "Apple Devices" o iTunes (usbmuxd, puerto 27015).

Flujo:
  FFmpeg (ddagrab + codificador por hardware) --RTP/UDP local--> este script
  --> cuadros completos con prefijo de longitud --> túnel USB (usbmux) --> app del iPad

Solo usa la biblioteca estándar de Python. Necesita FFmpeg 6.1 o superior en el PATH.
"""

import argparse
import os
import plistlib
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

PUERTO_IPAD = 7100
_mux = os.environ.get("PANTALLA_USBMUX", "127.0.0.1:27015").rsplit(":", 1)
USBMUX_HOST = (_mux[0], int(_mux[1]))


# --------------------------------------------------------------------------
# Utilidades de consola
# --------------------------------------------------------------------------

def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


# --------------------------------------------------------------------------
# usbmux: el protocolo que usa Windows para hablar con el iPad por cable
# --------------------------------------------------------------------------

class UsbmuxError(Exception):
    pass


def _usbmux_send(sock, payload, tag):
    data = plistlib.dumps(payload, fmt=plistlib.FMT_XML)
    # longitud total, versión 1 (plist), tipo 8 (plist), tag
    header = struct.pack("<IIII", 16 + len(data), 1, 8, tag)
    sock.sendall(header + data)


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise UsbmuxError("usbmuxd cerró la conexión")
        buf.extend(chunk)
    return bytes(buf)


def _usbmux_recv(sock):
    header = _recv_exact(sock, 16)
    length, _version, _msgtype, _tag = struct.unpack("<IIII", header)
    body = _recv_exact(sock, length - 16)
    return plistlib.loads(body)


def _usbmux_open(addr=USBMUX_HOST):
    try:
        return socket.create_connection(addr, timeout=3)
    except OSError as exc:
        raise UsbmuxError(
            "No encuentro el servicio de Apple para USB (puerto 27015). "
            "Instala la app 'Apple Devices' desde la Microsoft Store (o iTunes) "
            "y vuelve a intentar."
        ) from exc


def _base_msg(kind):
    return {
        "MessageType": kind,
        "ClientVersionString": "pantalla-extra",
        "ProgName": "pantalla-extra",
        "kLibUSBMuxVersion": 3,
    }


def usbmux_list_devices(addr=USBMUX_HOST):
    sock = _usbmux_open(addr)
    try:
        _usbmux_send(sock, _base_msg("ListDevices"), 1)
        reply = _usbmux_recv(sock)
    finally:
        sock.close()
    devices = []
    for dev in reply.get("DeviceList", []):
        props = dev.get("Properties", {})
        devices.append({
            "id": dev.get("DeviceID", props.get("DeviceID")),
            "tipo": props.get("ConnectionType", "?"),
            "serie": props.get("SerialNumber", "?"),
        })
    return devices


def usbmux_connect(device_id, port, addr=USBMUX_HOST):
    """Abre un túnel TCP hasta `port` dentro del iPad. Devuelve el socket."""
    sock = _usbmux_open(addr)
    msg = _base_msg("Connect")
    msg["DeviceID"] = device_id
    # usbmuxd espera el puerto en orden de red dentro de un entero little-endian
    msg["PortNumber"] = ((port & 0xFF) << 8) | ((port >> 8) & 0xFF)
    _usbmux_send(sock, msg, 2)
    reply = _usbmux_recv(sock)
    if reply.get("MessageType") != "Result" or reply.get("Number", -1) != 0:
        sock.close()
        code = reply.get("Number")
        if code == 3:
            raise UsbmuxError("El iPad rechazó la conexión: abre la app 'Pantalla Extra' en el iPad.")
        raise UsbmuxError(f"usbmuxd respondió con error {code}")
    sock.settimeout(None)
    return sock


# --------------------------------------------------------------------------
# FFmpeg: captura de pantalla y codificador
# --------------------------------------------------------------------------

def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.exit(
            "No encuentro FFmpeg. Instálalo con:  winget install Gyan.FFmpeg\n"
            "y abre una ventana nueva de la terminal."
        )
    return exe


def build_chain(encoder, source, fps, bitrate, gop):
    """Devuelve (filtro, opciones del codificador) para cada tipo de chip."""
    br = str(bitrate)
    if source == "prueba":
        grab = f"testsrc2=size=1280x720:rate={fps}"
        from_gpu = ""
    else:
        grab = f"ddagrab=output_idx={source}:framerate={fps}:draw_mouse=1"
        from_gpu = ",hwdownload,format=bgra"

    if encoder == "nvenc":   # NVIDIA
        return grab, ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull",
                      "-zerolatency", "1", "-rc", "cbr", "-b:v", br, "-bf", "0", "-g", gop]
    if encoder == "qsv":     # Intel (Quick Sync)
        return (grab + ",hwmap=derive_device=qsv,format=qsv",
                ["-c:v", "h264_qsv", "-preset", "veryfast", "-look_ahead", "0",
                 "-low_delay_brc", "1", "-async_depth", "1", "-b:v", br, "-bf", "0", "-g", gop])
    if encoder == "amf":     # AMD
        return grab, ["-c:v", "h264_amf", "-usage", "ultralowlatency", "-quality", "speed",
                      "-rc", "cbr", "-b:v", br, "-bf", "0", "-g", gop]
    if encoder == "mf":      # Media Foundation (cualquier chip, vía Windows)
        return (grab + from_gpu + ",format=nv12",
                ["-c:v", "h264_mf", "-hw_encoding", "1", "-scenario", "display_remoting",
                 "-rate_control", "cbr", "-b:v", br, "-g", gop])
    if encoder == "x264":    # CPU, último recurso
        return (grab + from_gpu + ",format=yuv420p",
                ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                 "-b:v", br, "-maxrate", br, "-bufsize", br, "-bf", "0", "-g", gop])
    raise ValueError(encoder)


ENCODERS = ["nvenc", "qsv", "amf", "mf", "x264"]


def ffmpeg_cmd(ffmpeg, encoder, source, fps, bitrate, gop, output):
    vf, enc = build_chain(encoder, source, fps, bitrate, gop)
    if source == "prueba":
        inp = ["-re", "-f", "lavfi", "-i", vf]
        filt = []
    else:
        inp = []
        filt = ["-filter_complex", vf]
    return ([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
            + inp + filt + enc + ["-an"] + output)


def pick_encoder(ffmpeg, source, fps, bitrate, gop, preferred):
    order = [preferred] if preferred != "auto" else ENCODERS
    for enc in order:
        cmd = ffmpeg_cmd(ffmpeg, enc, source, fps, bitrate, gop,
                         ["-t", "1.5", "-f", "null", "-"])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 0:
            return enc
        if preferred != "auto":
            sys.exit(f"El codificador '{enc}' no funcionó:\n{r.stderr.strip()[-800:]}")
    sys.exit(
        "Ningún codificador funcionó. Revisa que FFmpeg sea 6.1 o superior "
        "(ffmpeg -version) y que el número de --pantalla exista."
    )


# --------------------------------------------------------------------------
# RTP H.264 -> cuadros completos (access units) en formato Annex-B
# --------------------------------------------------------------------------

START = b"\x00\x00\x00\x01"


class Depacketizer:
    """Reconstruye cuadros completos a partir de paquetes RTP (RFC 6184).

    El bit "marker" de RTP marca el último paquete de cada cuadro, así que el
    cuadro se entrega en cuanto llega completo, sin esperar al siguiente.
    """

    def __init__(self):
        self.nals = []
        self.fu = None
        self.last_seq = None
        self.broken = False

    def push(self, pkt):
        if len(pkt) < 12 or (pkt[0] >> 6) != 2:
            return None
        b0, b1 = pkt[0], pkt[1]
        marker = b1 >> 7
        seq = struct.unpack(">H", pkt[2:4])[0]
        if self.last_seq is not None and seq != (self.last_seq + 1) & 0xFFFF:
            self.broken = True          # se perdió un paquete
        self.last_seq = seq

        off = 12 + 4 * (b0 & 0x0F)
        if (b0 >> 4) & 1:               # extensión de cabecera
            ext_len = struct.unpack(">H", pkt[off + 2:off + 4])[0]
            off += 4 + 4 * ext_len
        end = len(pkt)
        if (b0 >> 5) & 1:               # relleno
            end -= pkt[-1]
        payload = pkt[off:end]
        if payload:
            self._payload(payload)

        if not marker:
            return None
        frame = (None if self.broken or not self.nals
                 else b"".join(START + n for n in self.nals))
        self.nals = []
        self.fu = None
        self.broken = False
        return frame

    def _payload(self, p):
        t = p[0] & 0x1F
        if 1 <= t <= 23:                # un NAL completo
            self.nals.append(bytes(p))
        elif t == 24:                   # STAP-A: varios NAL juntos
            i = 1
            while i + 2 <= len(p):
                size = struct.unpack(">H", p[i:i + 2])[0]
                i += 2
                self.nals.append(bytes(p[i:i + size]))
                i += size
        elif t == 28 and len(p) >= 2:   # FU-A: un NAL partido en pedazos
            start, stop = p[1] >> 7, (p[1] >> 6) & 1
            if start:
                self.fu = bytearray([(p[0] & 0xE0) | (p[1] & 0x1F)])
            if self.fu is None:
                self.broken = True
                return
            self.fu.extend(p[2:])
            if stop:
                self.nals.append(bytes(self.fu))
                self.fu = None


def is_keyframe(frame):
    i = 0
    while True:
        i = frame.find(b"\x00\x00\x01", i)
        if i < 0 or i + 3 >= len(frame):
            return False
        if frame[i + 3] & 0x1F == 5:
            return True
        i += 3


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------

class Sender:
    def __init__(self, args):
        self.args = args
        self.sock = None
        self.lock = threading.Lock()
        self.need_key = True
        self.stop = threading.Event()
        self.frames = 0
        self.bytes = 0

    # ---- conexión con el iPad ----
    def connect_loop(self):
        warned = None
        while not self.stop.is_set():
            if self.sock is not None:
                time.sleep(0.5)
                continue
            try:
                if self.args.directo:
                    host, port = self.args.directo.rsplit(":", 1)
                    s = socket.create_connection((host, int(port)), timeout=3)
                    s.settimeout(None)
                    name = self.args.directo
                else:
                    devs = [d for d in usbmux_list_devices() if d["tipo"] == "USB"]
                    if not devs:
                        raise UsbmuxError("Conecta el iPad a la laptop con el cable USB-C.")
                    s = usbmux_connect(devs[0]["id"], self.args.puerto)
                    name = f"iPad {devs[0]['serie']}"
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
                with self.lock:
                    self.sock = s
                    self.need_key = True
                log(f"Conectado a {name}. Mostrando la pantalla.")
                warned = None
            except (OSError, UsbmuxError) as exc:
                msg = str(exc)
                if msg != warned:
                    log("Esperando al iPad: " + msg)
                    warned = msg
                time.sleep(1.0)

    def send(self, frame):
        with self.lock:
            s = self.sock
            if s is None:
                return
            if self.need_key:
                if not is_keyframe(frame):
                    return
                self.need_key = False
            try:
                s.sendall(struct.pack(">I", len(frame)) + frame)
                self.frames += 1
                self.bytes += len(frame)
            except OSError:
                log("Se desconectó el iPad. Reintentando...")
                try:
                    s.close()
                except OSError:
                    pass
                self.sock = None

    # ---- video ----
    def run(self):
        a = self.args
        ffmpeg = find_ffmpeg()
        gop = str(a.fps)  # un cuadro clave por segundo: si algo falla, se recupera en <1 s
        log("Probando el codificador de video de tu laptop...")
        enc = pick_encoder(ffmpeg, a.pantalla, a.fps, a.bitrate, gop, a.codificador)
        log(f"Codificador: {enc}  |  pantalla: {a.pantalla}  |  {a.fps} fps  |  {a.bitrate // 1_000_000} Mbps")

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
        udp.bind(("127.0.0.1", 0))
        udp.settimeout(1.0)
        rtp_port = udp.getsockname()[1]

        threading.Thread(target=self.connect_loop, daemon=True).start()
        threading.Thread(target=self.stats_loop, daemon=True).start()

        out = ["-bsf:v", "dump_extra", "-flush_packets", "1", "-f", "rtp",
               "-payload_type", "96", f"rtp://127.0.0.1:{rtp_port}?pkt_size=1400"]
        dep = Depacketizer()
        proc = None
        try:
            while not self.stop.is_set():
                if proc is None or proc.poll() is not None:
                    if proc is not None:
                        err = proc.stderr.read().decode(errors="replace").strip()
                        log("FFmpeg se detuvo" + (f": {err[-400:]}" if err else "") + ". Reiniciando...")
                        time.sleep(1)
                    cmd = ffmpeg_cmd(ffmpeg, enc, a.pantalla, a.fps, a.bitrate, gop, out)
                    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
                    with self.lock:
                        self.need_key = True
                try:
                    pkt = udp.recv(65536)
                except socket.timeout:
                    continue
                frame = dep.push(pkt)
                if frame:
                    self.send(frame)
                    if a.max_cuadros and self.frames >= a.max_cuadros:
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()
            if proc and proc.poll() is None:
                proc.terminate()
            with self.lock:
                if self.sock:
                    self.sock.close()
            log("Listo, cerrado.")

    def stats_loop(self):
        last_f, last_b = 0, 0
        while not self.stop.wait(5):
            f, b = self.frames, self.bytes
            if self.sock is not None and f > last_f:
                log(f"{(f - last_f) / 5:.0f} fps enviados, {(b - last_b) * 8 / 5 / 1e6:.1f} Mbps")
            last_f, last_b = f, b


def main():
    p = argparse.ArgumentParser(description="Pantalla Extra: usa tu iPad como segunda pantalla por cable.")
    p.add_argument("--pantalla", default="1",
                   help="Número de la pantalla de Windows a enviar (0 = principal, 1 = la segunda/virtual). "
                        "Usa 'prueba' para una imagen de prueba.")
    p.add_argument("--fps", type=int, default=60)
    p.add_argument("--bitrate", type=int, default=20_000_000, help="Bits por segundo (por defecto 20 Mbps)")
    p.add_argument("--codificador", default="auto", choices=["auto"] + ENCODERS)
    p.add_argument("--puerto", type=int, default=PUERTO_IPAD, help="Puerto de la app en el iPad")
    p.add_argument("--directo", metavar="HOST:PUERTO",
                   help="Conectar por red en vez de USB (para pruebas)")
    p.add_argument("--listar", action="store_true", help="Mostrar los iPad conectados y salir")
    p.add_argument("--max-cuadros", type=int, default=0, help=argparse.SUPPRESS)
    args = p.parse_args()

    if args.listar:
        try:
            devs = usbmux_list_devices()
        except UsbmuxError as exc:
            sys.exit(str(exc))
        if not devs:
            print("No hay ningún iPad conectado.")
        for d in devs:
            print(f"{d['tipo']:8} id={d['id']}  serie={d['serie']}")
        return

    if os.name == "nt":
        signal.signal(signal.SIGINT, signal.default_int_handler)
    log("Pantalla Extra. Cierra esta ventana o pulsa Ctrl+C para terminar.")
    Sender(args).run()


if __name__ == "__main__":
    main()
