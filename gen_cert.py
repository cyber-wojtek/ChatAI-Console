import subprocess
import sys
import os
from pathlib import Path

CERT = Path("cert.pem")
KEY  = Path("key.pem")

def generate():
    if CERT.exists() and KEY.exists():
        print("cert.pem and key.pem already exist — skipping generation")
        print("Delete them first if you want to regenerate")
        return

    if not _has_openssl():
        print("ERROR: openssl not found on PATH")
        print("Install it:")
        print("  Ubuntu/Debian:  apt install openssl")
        print("  macOS:          brew install openssl")
        print("  Windows:        https://slproweb.com/products/Win32OpenSSL.html")
        sys.exit(1)

    print("Generating self-signed cert for localhost (HTTP/2)...")
    subprocess.run([
        "openssl", "req", "-x509",
        "-newkey", "rsa:4096",
        "-keyout", str(KEY),
        "-out",    str(CERT),
        "-days",   "825",       # max accepted by modern browsers
        "-nodes",               # no passphrase
        "-subj",   "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ], check=True)

    # Restrict key permissions on unix
    if os.name != "nt":
        KEY.chmod(0o600)

    print(f"Done:  {CERT}  +  {KEY}")
    print()
    print("Open https://localhost:5000 the first time and click:")
    print("  Chrome:  Advanced → Proceed to localhost")
    print("  Firefox: Advanced → Accept the Risk")

def _has_openssl():
    try:
        subprocess.run(["openssl", "version"],
                       check=True,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

if __name__ == "__main__":
    generate()