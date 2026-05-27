"""
ChatAI Console — setup / install helper

Usage:
    python setup.py          # full setup (deps + cert + redis check)
    python setup.py --deps   # only install Python dependencies
    python setup.py --cert   # only generate TLS cert
    python setup.py --check  # only check system requirements
"""

import argparse
import shutil
import subprocess
import sys
import os
from pathlib import Path


# ── Python dependencies ───────────────────────────────────────────────────────

DEPS = [
    "quart",
    "hypercorn",
    "httpx",
    "redis",
    "bs4",
    "claude_webapi",
    "1minai_webapi",
    "flowith_webapi",
    "chataibotpro-webapi",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd, **kwargs):
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def _has(binary):
    return shutil.which(binary) is not None


def _ok(msg):   print(f"  ✓  {msg}")
def _warn(msg): print(f"  ⚠  {msg}")
def _fail(msg): print(f"  ✕  {msg}")


# ── Steps ─────────────────────────────────────────────────────────────────────

def check_requirements():
    print("\n── System requirements ──────────────────────────────────────────")
    ok = True

    # Python version
    if sys.version_info >= (3, 10):
        _ok(f"Python {sys.version.split()[0]}")
    else:
        _fail(f"Python 3.10+ required (you have {sys.version.split()[0]})")
        ok = False

    # redis-server
    if _has("redis-server"):
        _ok("redis-server found")
    else:
        _warn("redis-server not found — install it or set REDIS_URL to an external instance")
        _warn("  Ubuntu/Debian:  apt install redis-server")
        _warn("  macOS:          brew install redis")
        _warn("  Arch:           pacman -Sy redis")
        _warn("  Windows:        https://github.com/tporadowski/redis/releases")

    # openssl (needed for cert generation)
    if _has("openssl"):
        _ok("openssl found")
    else:
        _warn("openssl not found — TLS cert generation will be skipped")
        _warn("  Ubuntu/Debian:  apt install openssl")
        _warn("  macOS:          brew install openssl")

    return ok


def install_deps():
    print("\n── Python dependencies ──────────────────────────────────────────")
    _run([sys.executable, "-m", "pip", "install", "--upgrade", *DEPS])
    _ok("All dependencies installed")


def generate_cert():
    print("\n── TLS certificate ──────────────────────────────────────────────")

    cert = Path("cert.pem")
    key  = Path("key.pem")

    if cert.exists() and key.exists():
        _ok("cert.pem and key.pem already exist — skipping")
        _ok("Delete them and re-run if you want to regenerate")
        return

    if not _has("openssl"):
        _warn("openssl not found — skipping cert generation")
        _warn("App will start without TLS (HTTP/1.1 only, no HTTP/2)")
        _warn("This means the 6-connection browser limit stays in effect")
        return

    try:
        _run([
            "openssl", "req", "-x509",
            "-newkey", "rsa:4096",
            "-keyout", str(key),
            "-out",    str(cert),
            "-days",   "825",
            "-nodes",
            "-subj",   "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if os.name != "nt":
            key.chmod(0o600)

        _ok("cert.pem + key.pem generated (valid 825 days)")
        print()
        print("  First run: open https://localhost:5000 and accept the cert warning:")
        print("    Chrome  → Advanced → Proceed to localhost")
        print("    Firefox → Advanced → Accept the Risk")

    except subprocess.CalledProcessError as e:
        _fail(f"openssl failed: {e}")
        _warn("App will start without TLS")


def create_gitignore_entries():
    """Append security-sensitive patterns to .gitignore if missing."""
    print("\n── .gitignore ───────────────────────────────────────────────────")

    entries = [
        "# ChatAI Console — never commit these",
        "*.pem",
        "*.key",
        "*.crt",
        "*.cert",
        "keys.py",
        "data/",
        ".env",
    ]

    gi = Path(".gitignore")
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""

    to_add = [e for e in entries if e not in existing and not e.startswith("#")]
    if not to_add:
        _ok(".gitignore already has all required entries")
        return

    with gi.open("a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(entries) + "\n")

    _ok(f"Added {len(to_add)} entries to .gitignore: {', '.join(to_add)}")


def print_next_steps():
    cert_exists = Path("cert.pem").exists()
    scheme = "https" if cert_exists else "http"

    print()
    print("─" * 60)
    print("  Setup complete.  Next steps:")
    print()
    print(f"  1.  python app.py")
    print(f"  2.  Open {scheme}://localhost:5000")
    if cert_exists:
        print( "  3.  Accept the self-signed cert warning (once)")
    print( "  4.  Add an account via the sidebar ⚙")
    print()
    if not Path("keys.py").exists():
        print("  Optional: create keys.py to auto-seed accounts on startup")
        print("  See README for the format")
    print("─" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ChatAI Console setup helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--deps",  action="store_true", help="Only install Python deps")
    parser.add_argument("--cert",  action="store_true", help="Only generate TLS cert")
    parser.add_argument("--check", action="store_true", help="Only check requirements")
    args = parser.parse_args()

    print("ChatAI Console — Setup")
    print("=" * 60)

    if args.deps:
        install_deps()
    elif args.cert:
        generate_cert()
    elif args.check:
        check_requirements()
    else:
        # Full setup
        check_requirements()
        install_deps()
        generate_cert()
        create_gitignore_entries()
        print_next_steps()


if __name__ == "__main__":
    main()