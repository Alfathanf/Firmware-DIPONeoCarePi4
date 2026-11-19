import socket
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeviceIdentity:
    mac_address: str
    local_ip: str
    firmware_version: str

    @classmethod
    def detect(cls, firmware_version: str) -> "DeviceIdentity":
        mac_address = cls.get_active_mac_address()
        local_ip = cls.get_local_ip()
        if not firmware_version:
            raise ValueError("FIRMWARE_VERSION cannot be empty")
        return cls(mac_address, local_ip, firmware_version)

    @staticmethod
    def get_active_mac_address() -> str:
        sys_net = Path("/sys/class/net")
        candidates = []
        if sys_net.exists():
            for interface in sys_net.iterdir():
                if interface.name == "lo":
                    continue
                address_file = interface / "address"
                if not address_file.exists():
                    continue
                address = address_file.read_text(encoding="ascii").strip()
                operstate_file = interface / "operstate"
                operstate = (
                    operstate_file.read_text(encoding="ascii").strip()
                    if operstate_file.exists()
                    else ""
                )
                if address and address != "00:00:00:00:00:00":
                    candidates.append((operstate == "up", interface.name, address))

        candidates.sort(key=lambda item: (not item[0], item[1]))
        if not candidates:
            raise RuntimeError("No active network MAC address found")
        return candidates[0][2].upper()

    @staticmethod
    def get_local_ip() -> str:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            local_ip = probe.getsockname()[0]
        finally:
            probe.close()
        if not local_ip:
            raise RuntimeError("Unable to determine local IP address")
        return local_ip
