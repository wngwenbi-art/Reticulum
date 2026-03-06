import threading
import time
import RNS
from RNS.Interfaces.Interface import Interface
from jnius import autoclass

BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")
UUID = autoclass("java.util.UUID")

SPP_UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

KISS_FEND       = 0xC0
KISS_CMD_DATA   = 0x00
KISS_CMD_DETECT = 0x08
KISS_DETECT_REQ = 0x73


class RNodeInterface(Interface):

    def __init__(self, owner, configuration):
        super().__init__()

        c = Interface.get_config_obj(configuration)

        self.name           = c["name"]
        self.target_address = c["target_device_address"]
        self.owner          = owner
        self.online         = False
        self.socket         = None
        self.in_stream      = None
        self.out_stream     = None

        self.thread = threading.Thread(target=self.run, daemon=True,
                                       name=f"rnode-{self.name}")
        self.thread.start()

    # ── Bluetooth connection ──────────────────────────────────────────────

    def connect(self):
        adapter = BluetoothAdapter.getDefaultAdapter()
        if adapter is None:
            raise IOError("Bluetooth not available")
        if not adapter.isEnabled():
            raise IOError("Bluetooth is disabled")

        adapter.cancelDiscovery()

        device = adapter.getRemoteDevice(self.target_address)
        socket = device.createRfcommSocketToServiceRecord(SPP_UUID)

        RNS.log(f"[{self.name}] Connecting RFCOMM to {self.target_address}")
        socket.connect()

        self.socket     = socket
        self.in_stream  = socket.getInputStream()
        self.out_stream = socket.getOutputStream()

        RNS.log(f"[{self.name}] RFCOMM connected")
        # online is set to True only after detect response, not here

    # ── KISS helpers ──────────────────────────────────────────────────────

    def send_kiss(self, cmd, payload=b""):
        frame = bytes([KISS_FEND, cmd]) + payload + bytes([KISS_FEND])
        self.out_stream.write(frame)
        self.out_stream.flush()

    def detect_radio(self):
        RNS.log(f"[{self.name}] Sending RNode detect")
        # Correct detect frame: C0 08 73 C0
        self.out_stream.write(bytes([0xC0, 0x08, 0x73, 0xC0]))
        self.out_stream.flush()

    # ── RX loop ───────────────────────────────────────────────────────────

    def read_loop(self):
        buffer = bytearray()

        while True:
            try:
                data = self.in_stream.read()

                # Android RFCOMM returns -1 on empty read — never break on this
                if data == -1:
                    time.sleep(0.01)
                    continue

                buffer.append(data)

                if data == KISS_FEND:
                    if len(buffer) > 2:
                        self.process_frame(bytes(buffer))
                    buffer.clear()

            except Exception as e:
                RNS.log(f"[{self.name}] read_loop error: {e}", RNS.LOG_ERROR)
                self.online = False
                break

    # ── Frame processing ──────────────────────────────────────────────────

    def process_frame(self, frame):
        if len(frame) < 3:
            return

        cmd     = frame[1]
        payload = frame[2:-1]

        if cmd == KISS_CMD_DETECT:
            RNS.log(f"[{self.name}] RNode detected — interface online")
            self.online = True  # only mark online after radio confirms detect

        elif cmd == KISS_CMD_DATA:
            try:
                self.processIncoming(payload)  # correct RNS entry point
            except Exception as e:
                RNS.log(f"[{self.name}] processIncoming error: {e}", RNS.LOG_ERROR)

        else:
            RNS.log(f"[{self.name}] rx cmd=0x{cmd:02x} len={len(payload)}", RNS.LOG_DEBUG)

    # ── Main interface loop (auto-reconnect) ──────────────────────────────

    def run(self):
        while True:
            try:
                self.connect()
                time.sleep(0.5)
                self.detect_radio()
                self.read_loop()

            except Exception as e:
                RNS.log(f"[{self.name}] error: {e}", RNS.LOG_ERROR)
                self.online = False
                try:
                    if self.socket:
                        self.socket.close()
                except Exception:
                    pass
                self.socket     = None
                self.in_stream  = None
                self.out_stream = None
                RNS.log(f"[{self.name}] reconnecting in 2s...")
                time.sleep(2)

    # ── TX ────────────────────────────────────────────────────────────────

    def process_outgoing(self, data):
        if not self.online:
            return
        frame = bytes([KISS_FEND, KISS_CMD_DATA]) + data + bytes([KISS_FEND])
        try:
            self.out_stream.write(frame)
            self.out_stream.flush()
        except Exception as e:
            RNS.log(f"[{self.name}] TX error: {e}", RNS.LOG_ERROR)
            self.online = False

    def __str__(self):
        return f"RNodeInterface[{self.name}/{self.target_address}]"
