import threading
import time
import RNS

from jnius import autoclass

BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")
UUID = autoclass("java.util.UUID")

SPP_UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

KISS_FEND = 0xC0
KISS_CMD_DETECT = 0x08

class RNodeInterface:

    def __init__(self, owner, name, config):
        self.owner = owner
        self.name = name
        self.config = config

        self.target_address = config["target_device_address"]
        self.online = False
        self.socket = None

        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    # -------------------------
    # Bluetooth connection
    # -------------------------

    def connect(self):

        adapter = BluetoothAdapter.getDefaultAdapter()

        if adapter is None:
            raise IOError("Bluetooth not available")

        device = adapter.getRemoteDevice(self.target_address)

        socket = device.createRfcommSocketToServiceRecord(SPP_UUID)

        adapter.cancelDiscovery()

        RNS.log("Connecting RFCOMM to "+self.target_address)

        socket.connect()

        self.socket = socket
        self.in_stream = socket.getInputStream()
        self.out_stream = socket.getOutputStream()

        self.online = True

        RNS.log("RFCOMM connected")

    # -------------------------
    # KISS helpers
    # -------------------------

    def send_kiss(self, cmd, payload=b""):
        frame = bytes([KISS_FEND, cmd]) + payload + bytes([KISS_FEND])
        self.out_stream.write(frame)
        self.out_stream.flush()

    def detect_radio(self):
        RNS.log("Sending RNode detect")
        self.send_kiss(KISS_CMD_DETECT)

    # -------------------------
    # RX loop
    # -------------------------

    def read_loop(self):

        buffer = bytearray()

        while self.online:

            data = self.in_stream.read()

            if data == -1:
                time.sleep(0.01)
                continue

            buffer.append(data)

            if data == KISS_FEND:
                if len(buffer) > 2:
                    self.process_frame(bytes(buffer))
                buffer.clear()

    # -------------------------
    # Frame processing
    # -------------------------

    def process_frame(self, frame):

        if len(frame) < 3:
            return

        cmd = frame[1]
        payload = frame[2:-1]

        if cmd == KISS_CMD_DETECT:
            RNS.log("RNode detected")

        else:
            # pass payload to Reticulum
            try:
                self.owner.inbound(payload, self)
            except:
                pass

    # -------------------------
    # Main interface loop
    # -------------------------

    def run(self):

        while True:

            try:

                self.connect()

                time.sleep(0.5)

                self.detect_radio()

                self.read_loop()

            except Exception as e:

                RNS.log("RNodeInterface error: "+str(e))

                self.online = False

                try:
                    if self.socket:
                        self.socket.close()
                except:
                    pass

                time.sleep(2)

    # -------------------------
    # TX
    # -------------------------

    def process_outgoing(self, data):

        if not self.online:
            return

        frame = bytes([KISS_FEND, 0x00]) + data + bytes([KISS_FEND])

        try:
            self.out_stream.write(frame)
            self.out_stream.flush()
        except:
            self.online = False
