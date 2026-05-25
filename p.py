#!/usr/bin/env python3
"""
Patch: Fix sb-open-btn alignment in toolbar on mobile.

The button sits position:absolute inside .main (before the toolbar),
so it floats outside flex flow and never aligns with adjacent toolbar
elements. Fix: move it inside .toolbar as first flex child, remove
absolute positioning, let flex do the alignment.
"""

import sys
import shutil
import argparse
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# 1. Fix the base CSS rule — static flex child instead of absolute
# ─────────────────────────────────────────────────────────────────────────────

OLD_CSS = """.sb-open-btn {
  position:absolute; left:10px; top:12px; z-index:10;
  width:32px; height:32px;
  background:var(--bg-2); border:1px solid var(--border);
  border-radius:var(--r); color:var(--text-2); font-size:13px;
  display:none; align-items:center; justify-content:center;
  cursor:pointer; transition:all .2s var(--ease);
}
.sb-open-btn:hover { background:var(--bg-3); color:var(--text); border-color:var(--border-m); }
.app.sb-collapsed .sb-open-btn { display:flex; }
.app.sb-collapsed .toolbar { padding-left:52px; }"""

NEW_CSS = """.sb-open-btn {
  /* Flex child inside .toolbar — no absolute positioning */
  position: static;
  flex-shrink: 0;
  align-self: center;
  width: 34px;
  height: 34px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--r);
  color: var(--text-2);
  font-size: 15px;
  display: none;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all .2s var(--ease);
  z-index: auto;
}
.sb-open-btn:hover { background:var(--bg-3); color:var(--text); border-color:var(--border-m); }
/* Shown as first item in toolbar when sidebar is collapsed */
.app.sb-collapsed .sb-open-btn { display:flex; }
/* No padding-left compensation needed — button is in-flow */
.app.sb-collapsed .toolbar { padding-left: 10px; }"""


# ─────────────────────────────────────────────────────────────────────────────
# 2. Move button from before splash (outside toolbar) into toolbar as first child
# ─────────────────────────────────────────────────────────────────────────────

# Remove button from its current location (outside toolbar, inside .main)
OLD_BTN_LOCATION = """    <button class="sb-open-btn" id="sbOpenBtn" onclick="toggleSidebar()">☰</button>

    <!-- Splash -->"""

NEW_BTN_LOCATION = """    <!-- Splash -->"""

# Insert it as first child inside .toolbar
OLD_TOOLBAR_START = """      <div class="toolbar">
        <div class="conv-title-wrap">"""

NEW_TOOLBAR_START = """      <div class="toolbar">
        <button class="sb-open-btn" id="sbOpenBtn" onclick="toggleSidebar()" aria-label="Open sidebar">☰</button>
        <div class="conv-title-wrap">"""


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fix mobile @media overrides that impose absolute positioning
#    The mobile block sets position:absolute + left/top which undoes fix #1.
# ─────────────────────────────────────────────────────────────────────────────

# The mobile CSS block that currently forces the button back to absolute
OLD_MOBILE_BTN_BLOCK = """  /* hamburger always visible */
  .sb-open-btn {
    display: flex !important;
    position: absolute;
    left: 10px; top: 12px;
    width: 40px; height: 40px;
    font-size: 18px;
    z-index: 10;
  }"""

NEW_MOBILE_BTN_BLOCK = """  /* hamburger — flex child, no absolute */
  .sb-open-btn {
    display: none;
    width: 38px;
    height: 38px;
    font-size: 17px;
    flex-shrink: 0;
    align-self: center;
  }
  .app.sb-collapsed .sb-open-btn { display: flex; }"""

# Fix the toolbar padding that was compensating for the absolute button
OLD_TOOLBAR_PAD_58 = """  .toolbar {
    padding: 8px 8px 8px 58px;"""

NEW_TOOLBAR_PAD_58 = """  .toolbar {
    padding: 8px 8px 8px 8px;"""

# Also remove the sb-collapsed override that re-adds left padding
OLD_SB_COLLAPSED_TOOLBAR = "  /* remove old sb-collapsed left-padding shift */\n  .app.sb-collapsed .toolbar { padding-left: 52px; }"
NEW_SB_COLLAPSED_TOOLBAR = "  /* sb-open-btn is in-flow — no padding-left shift needed */"

# And the variant that says padding-left: 52px as a standalone rule
OLD_PAD_LEFT_52 = "  .app.sb-collapsed .toolbar { padding-left: 52px; }"
NEW_PAD_LEFT_52 = "  /* padding-left removed — sb-open-btn is a flex child */"


# ─────────────────────────────────────────────────────────────────────────────
# 4. JS: mobileSetup no longer needs sb-collapsed class (CSS handles it)
#    but it does need to ensure the button is NOT force-shown via inline style.
#    The current JS block is fine — just remove any explicit display manipulation
#    of #sbOpenBtn if present.
# ─────────────────────────────────────────────────────────────────────────────
# Nothing to change here — the JS doesn't touch sbOpenBtn display directly.


# ─────────────────────────────────────────────────────────────────────────────
# PATCHER
# ─────────────────────────────────────────────────────────────────────────────

def patch(html: str) -> str:
    changes = []

    def apply(desc: str, old: str, new: str, required: bool = True) -> None:
        nonlocal html
        if old not in html:
            status = "NOT FOUND" if required else "not found (optional)"
            print(f"  {'⚠' if required else '·'} {status}: {desc}")
            return
        html = html.replace(old, new, 1)
        changes.append(desc)
        print(f"  ✓ {desc}")

    print("\n── Step 1: Base CSS — make sb-open-btn a flex child ──")
    apply("Replace absolute .sb-open-btn CSS with flex-child version",
          OLD_CSS, NEW_CSS)

    print("\n── Step 2: HTML — move button inside .toolbar ──")
    apply("Remove sb-open-btn from before-splash position (outside toolbar)",
          OLD_BTN_LOCATION, NEW_BTN_LOCATION)
    apply("Insert sb-open-btn as first child inside .toolbar",
          OLD_TOOLBAR_START, NEW_TOOLBAR_START)

    print("\n── Step 3: Mobile @media — remove absolute override ──")
    apply("Replace absolute hamburger rule in mobile media query",
          OLD_MOBILE_BTN_BLOCK, NEW_MOBILE_BTN_BLOCK)
    apply("Remove 58px left padding from mobile toolbar (was compensating for abs button)",
          OLD_TOOLBAR_PAD_58, NEW_TOOLBAR_PAD_58)
    apply("Replace sb-collapsed toolbar padding-left comment block",
          OLD_SB_COLLAPSED_TOOLBAR, NEW_SB_COLLAPSED_TOOLBAR,
          required=False)
    # Catch any remaining standalone 52px override
    apply("Remove residual 52px padding-left on .app.sb-collapsed .toolbar",
          OLD_PAD_LEFT_52, NEW_PAD_LEFT_52,
          required=False)

    print(f"\n── {len(changes)} change(s) applied ──")
    return html


def main() -> None:
    ap = argparse.ArgumentParser(description="Fix hamburger button alignment")
    ap.add_argument("--input",  "-i", default="templates/index.html")
    ap.add_argument("--output", "-o", default=None)
    ap.add_argument("--backup", "-b", action="store_true")
    ap.add_argument("--dry-run","-n", action="store_true")
    args = ap.parse_args()

    src  = Path(args.input)
    dest = Path(args.output) if args.output else src

    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        sys.exit(1)

    original = src.read_text(encoding="utf-8")
    patched  = patch(original)

    if args.dry_run:
        import difflib
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile=str(src) + " (original)",
            tofile=str(dest) + " (patched)",
            n=4,
        )
        sys.stdout.writelines(diff)
        print("\n[dry-run] nothing written")
        return

    if args.backup:
        bak = src.with_suffix(src.suffix + ".bak")
        shutil.copy2(src, bak)
        print(f"Backup → {bak}")

    dest.write_text(patched, encoding="utf-8")
    print(f"\nWritten → {dest}")


if __name__ == "__main__":
    main()
