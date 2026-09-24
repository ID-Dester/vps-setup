import datetime
import grp
import ipaddress
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import uuid
from urllib.parse import urlencode

if os.geteuid() != 0:
    raise SystemExit("STOP: run this script as root.")

if len(sys.argv) != 3:
    raise SystemExit(
        "Usage: python3 setup-reality.py SERVER_IPV4 SNI"
    )

server_ip = str(ipaddress.IPv4Address(sys.argv[1]))
sni = sys.argv[2].strip().lower()

if not re.fullmatch(r"[a-z0-9.-]+", sni):
    raise SystemExit("STOP: invalid SNI hostname.")

config_path = pathlib.Path("/usr/local/etc/xray/config.json")
link_path = pathlib.Path("/root/vless-reality.txt")
candidate_path = pathlib.Path("/usr/local/etc/xray/config.pending.json")

if link_path.exists():
    raise SystemExit(
        "STOP: client link already exists. "
        "Existing credentials were not changed."
    )

xray_group = grp.getgrnam("xray").gr_gid
os.umask(0o077)

result = subprocess.run(
    ["/usr/local/bin/xray", "x25519"],
    check=True,
    capture_output=True,
    text=True,
)

fields = {}
for line in result.stdout.splitlines():
    if ":" in line:
        label, value = line.split(":", 1)
        label = re.sub(r"\s+", "", label).lower()
        fields[label] = value.strip()

private_key = fields.get("privatekey")
public_key = fields.get("password") or fields.get("publickey")

key_pattern = r"[A-Za-z0-9_-]{43}"
if not private_key or not re.fullmatch(key_pattern, private_key):
    raise SystemExit("STOP: unexpected private key format.")
if not public_key or not re.fullmatch(key_pattern, public_key):
    raise SystemExit("STOP: unexpected public key format.")

client_id = str(uuid.uuid4())
short_id = secrets.token_hex(8)

config = {
    "log": {
        "loglevel": "warning"
    },
    "inbounds": [
        {
            "tag": "vless-reality",
            "listen": "0.0.0.0",
            "port": 443,
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "id": client_id,
                        "flow": "xtls-rprx-vision"
                    }
                ],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "raw",
                "security": "reality",
                "realitySettings": {
                    "show": False,
                    "target": sni + ":443",
                    "xver": 0,
                    "serverNames": [sni],
                    "privateKey": private_key,
                    "shortIds": [short_id]
                }
            }
        }
    ],
    "outbounds": [
        {
            "tag": "direct",
            "protocol": "freedom"
        },
        {
            "tag": "block",
            "protocol": "blackhole"
        }
    ],
    "routing": {
        "domainStrategy": "IPIfNonMatch",
        "rules": [
            {
                "type": "field",
                "ip": ["geoip:private"],
                "outboundTag": "block"
            }
        ]
    }
}

candidate_path.write_text(
    json.dumps(config, indent=2) + "\n",
    encoding="utf-8",
)
os.chown(candidate_path, 0, xray_group)
candidate_path.chmod(0o640)

test = subprocess.run(
    [
        "runuser", "-u", "xray", "--",
        "/usr/local/bin/xray", "run",
        "-test", "-config", str(candidate_path),
    ],
    capture_output=True,
    text=True,
)

if test.returncode != 0:
    candidate_path.unlink(missing_ok=True)
    print("STOP: configuration check failed.")
    print("Existing configuration was not changed.")
    details = (test.stdout + test.stderr).replace(
        private_key, "[REDACTED]"
    )
    print(details)
    raise SystemExit(1)

if config_path.exists():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = pathlib.Path(
        "/root/xray-config-before-" + stamp + ".json"
    )
    shutil.copyfile(config_path, backup)
    backup.chmod(0o600)

os.replace(candidate_path, config_path)

params = {
    "encryption": "none",
    "security": "reality",
    "sni": sni,
    "fp": "chrome",
    "pbk": public_key,
    "sid": short_id,
    "type": "tcp",
    "flow": "xtls-rprx-vision",
    "spx": "/",
}

link = (
    f"vless://{client_id}@{server_ip}:443?"
    + urlencode(params)
    + "#My-VPS-REALITY"
)

link_path.write_text(link + "\n", encoding="utf-8")
link_path.chmod(0o600)

print("OK: configuration validated and saved.")
print("OK: client link saved to /root/vless-reality.txt")
print("Private key was not printed.")
