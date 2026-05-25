#!/usr/bin/env python3
"""
Mobile UX patcher v2 — fixes account switcher + general mobile clunkiness.
Run from project root: python patch_mobile_v2.py
"""

import re
import shutil
from pathlib import Path
from datetime import datetime

TARGET = Path("templates/index.html")
BACKUP = Path(f"templates/index.html.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")

# ─────────────────────────────────────────────────────────────────────────────
# CSS PATCH
# ─────────────────────────────────────────────────────────────────────────────
MOBILE_CSS = r"""
/* ═══════════════════════════════════════════════════════════
   MOBILE PATCH v2  — full responsive overhaul
═══════════════════════════════════════════════════════════ */

/* ── shared: backdrop overlay ── */
.m-backdrop {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.55);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  z-index: 180;
  touch-action: none;
}
.m-backdrop.on { display: block; }

/* ════════════════════════════════
   MOBILE  ≤ 768 px
════════════════════════════════ */
@media (max-width: 768px) {

  /* prevent iOS double-tap zoom everywhere */
  * { touch-action: manipulation; }

  /* ── root font / viewport ── */
  :root {
    --sidebar: 290px;
  }

  /* ── app shell ── */
  .app {
    display: block;          /* no flex row — prevents panels eating space */
    position: relative;
    overflow: hidden;
    height: 100dvh;
  }

  /* ── SIDEBAR — full-height slide-over drawer ── */
  #sidebarWrap {
    position: fixed !important;
    top: 0; left: 0;
    height: 100dvh;
    z-index: 200;
    /* width driven by child .sidebar */
  }

  .sidebar {
    position: relative !important;
    width: var(--sidebar) !important;
    min-width: var(--sidebar) !important;
    height: 100dvh;
    transform: translateX(-100%);
    transition: transform .28s cubic-bezier(.4,0,.2,1);
    opacity: 1 !important;
    pointer-events: none;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }
  .sidebar.m-open {
    transform: translateX(0);
    pointer-events: auto;
  }
  /* kill the old collapsed logic on mobile */
  .sidebar.collapsed {
    width: var(--sidebar) !important;
    min-width: var(--sidebar) !important;
    opacity: 1 !important;
  }

  /* hide desktop edge-toggle */
  .sb-toggle { display: none !important; }

  /* ── MAIN — take the whole screen ── */
  .main {
    position: fixed !important;
    inset: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  /* remove old sb-collapsed left-padding shift */
  .app.sb-collapsed .toolbar { padding-left: 52px; }

  /* hamburger always visible */
  .sb-open-btn {
    display: flex !important;
    position: absolute;
    left: 10px; top: 12px;
    width: 40px; height: 40px;
    font-size: 18px;
    z-index: 10;
  }

  /* ── TOOLBAR ── */
  .toolbar {
    padding: 8px 8px 8px 58px;
    min-height: 52px;
    gap: 5px;
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    flex-shrink: 0;
  }
  .toolbar::-webkit-scrollbar { display: none; }

  .conv-title-wrap { min-width: 0; flex: 1; max-width: 150px; }
  .conv-title-display { font-size: 13px; }

  .tb-group { flex-shrink: 0; gap: 4px; }
  .tb-select { height: 34px; padding: 0 8px; font-size: 11px; max-width: 130px; }
  .tb-toggle { height: 34px; padding: 0 8px; font-size: 11px; }
  .tb-icon   { width: 34px; height: 34px; font-size: 14px; flex-shrink: 0; }

  /* hide rarely-used toolbar buttons to save space */
  #refreshModelsBtn { display: none !important; }

  /* ── MESSAGES ── */
  .msgs { padding: 14px 0 8px; flex: 1; overflow-y: auto; }
  .msg  { padding: 0 12px; }
  .msg + .msg { margin-top: 14px; }

  .msg.human .msg-body {
    max-width: 90%;
    padding: 10px 14px;
    font-size: 15px;
    line-height: 1.6;
  }
  .msg.assistant .msg-body { font-size: 15px; line-height: 1.7; }

  /* always show action buttons (no hover on touch) */
  .msg-actions { opacity: 1 !important; }
  .conv-btns   { opacity: 1 !important; pointer-events: auto !important; }
  .cfile-btns  { opacity: 1 !important; }

  /* code blocks */
  .md pre { margin: 8px 0; border-radius: var(--r); }
  .md pre code { font-size: 11px; padding: 12px; }
  .code-header  { padding: 6px 10px; }
  .md table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; font-size: 12px; }

  /* ── INPUT AREA ── */
  .input-area {
    padding: 8px 10px env(safe-area-inset-bottom, 10px);
    flex-shrink: 0;
  }
  .input-box  { border-radius: 20px; padding: 6px 6px 6px 4px; }
  .msg-ta     { font-size: 16px !important; padding: 5px 0; } /* 16px stops iOS zoom */
  .send-btn   { width: 42px; height: 42px; border-radius: 14px; font-size: 19px; flex-shrink: 0; }
  .inp-btn    { width: 36px; height: 36px; }
  .inp-hint   { font-size: 10px; }

  /* ── SPLASH ── */
  .splash { padding: 20px 16px; gap: 14px; }
  .splash-glyph  { font-size: 48px; }
  .splash-title  { font-size: 20px; text-align: center; }
  .splash-sub    { font-size: 13px; }
  .splash-actions { flex-direction: column; width: 100%; gap: 8px; }
  .btn-splash-new, .btn-sec-small { width: 100%; padding: 13px; font-size: 14px; }

  /* ════════════════════════════════════════
     ACCOUNT SWITCHER  — full-screen modal
  ════════════════════════════════════════ */
  .sb-foot {
    position: sticky;
    bottom: 0;
    background: linear-gradient(180deg, var(--bg-1), #080818);
    padding: 10px 12px 14px;
    border-top: 1px solid var(--border);
  }

  .acct-switcher { position: static; }

  .acct-active {
    padding: 11px 14px;
    border-radius: var(--r-l);
    min-height: 52px;           /* fat tap target */
  }
  .acct-dot { width: 9px; height: 9px; }
  .acct-name { font-size: 14px; }
  .acct-org  { font-size: 12px; }
  .acct-chev { font-size: 11px; }

  /* Menu: full-screen bottom sheet */
  .acct-menu {
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    top: auto !important;
    width: 100% !important;
    max-width: 100% !important;
    max-height: 80dvh;
    border-radius: 20px 20px 0 0 !important;
    border: none !important;
    border-top: 1px solid var(--border-m) !important;
    z-index: 9999 !important;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 -8px 40px rgba(0,0,0,.6) !important;
    animation: slideUpSheet .22s cubic-bezier(.4,0,.2,1) !important;
  }
  @keyframes slideUpSheet {
    from { transform: translateY(40px); opacity: 0; }
    to   { transform: translateY(0);    opacity: 1; }
  }

  /* drag handle */
  .acct-menu::before {
    content: '';
    display: block;
    width: 40px; height: 4px;
    background: var(--bg-5);
    border-radius: 2px;
    margin: 10px auto 4px;
    flex-shrink: 0;
  }

  .acct-menu-search { padding: 6px 12px 8px; flex-shrink: 0; }
  .acct-menu-search-inp {
    padding: 10px 10px 10px 30px;
    font-size: 14px !important;
    border-radius: var(--r-l);
  }

  .acct-menu-list {
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 4px 8px;
    max-height: none;           /* let flex handle height */
  }

  /* bigger tap targets for each account row */
  .acct-menu-item {
    padding: 12px 12px;
    border-radius: var(--r-l);
    min-height: 56px;
    gap: 10px;
    margin-bottom: 2px;
  }
  .acct-menu-item::before { font-size: 13px; }
  .ami-name  { font-size: 14px; }
  .ami-org   { font-size: 12px; }
  .ami-badge { font-size: 11px; padding: 2px 7px; }
  .ami-del   { font-size: 18px; padding: 6px 8px; min-width: 36px; min-height: 36px; }

  .acct-menu-footer {
    flex-shrink: 0;
    padding: 6px 8px calc(env(safe-area-inset-bottom, 8px) + 8px);
    border-top: 1px solid var(--border-s);
  }
  .acct-menu-footer button {
    padding: 12px 14px;
    font-size: 14px;
    border-radius: var(--r-l);
    min-height: 48px;
  }

  /* ── SIDE PANELS — full-height drawers from right ── */
  .canvas-panel,
  .omai-panel,
  .flowith-panel,
  .bex-panel {
    position: fixed !important;
    top: 0; right: 0;
    height: 100dvh !important;
    width: min(340px, 96vw) !important;
    min-width: unset !important;
    z-index: 190;
    transform: translateX(100%);
    transition: transform .28s cubic-bezier(.4,0,.2,1) !important;
    opacity: 1 !important;
    border-left: 1px solid var(--border-m);
    box-shadow: -4px 0 32px rgba(0,0,0,.6);
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }
  /* open state driven by removing .collapsed */
  .canvas-panel:not(.collapsed),
  .omai-panel:not(.collapsed),
  .flowith-panel:not(.collapsed),
  .bex-panel:not(.collapsed) {
    transform: translateX(0) !important;
    pointer-events: auto;
  }
  .canvas-panel.collapsed,
  .omai-panel.collapsed,
  .flowith-panel.collapsed,
  .bex-panel.collapsed {
    transform: translateX(100%) !important;
    pointer-events: none;
  }

  /* ── MODALS ── */
  .overlay { align-items: flex-end !important; padding: 0 !important; }
  .modal {
    width: 100% !important;
    max-width: 100% !important;
    border-radius: 20px 20px 0 0 !important;
    padding: 20px 16px calc(env(safe-area-inset-bottom,12px) + 16px) !important;
    max-height: 90dvh !important;
    margin: 0 !important;
    transform: translateY(20px) scale(1) !important;
  }
  .overlay.open .modal { transform: translateY(0) scale(1) !important; }

  /* ── MISC ── */
  .conv-item { min-height: 48px; padding: 10px 10px 10px 12px; }
  .polling-panel { width: calc(100vw - 16px); bottom: 8px; right: 8px; }
  #cfOverlay { width: calc(100vw - 16px); bottom: 8px; right: 8px; }
  .efp {
    position: fixed !important;
    bottom: 80px; left: 8px; right: 8px;
    width: auto !important; max-height: 55dvh;
  }
  .att-chip { max-width: 160px; }
  .artifact-preview { height: 280px; }
  .ask-option { min-height: 48px; }
  .ask-submit-btn { width: 100%; padding: 13px; font-size: 14px; }

  /* quota wrap tighter on mobile */
  .quota-wrap { padding: 8px 10px; margin-bottom: 8px; }
}

/* ════════════════════════════════
   TABLET  769–1024 px
════════════════════════════════ */
@media (min-width: 769px) and (max-width: 1024px) {
  :root {
    --sidebar: 220px;
    --canvas-width: 300px;
    --omai-width: 300px;
    --flowith-panel-width: 300px;
    --bex-width: 280px;
  }
  .toolbar { gap: 5px; }
  .tb-select { max-width: 140px; font-size: 11px; }
  .tb-toggle { font-size: 11px; padding: 0 8px; }
  .msg { padding: 0 18px; }

  /* panels as overlays on tablet too */
  .canvas-panel, .omai-panel, .flowith-panel, .bex-panel {
    position: fixed !important;
    top: 0; right: 0;
    height: 100dvh !important;
    z-index: 190;
    box-shadow: -4px 0 24px rgba(0,0,0,.5);
  }
}

/* ════════════════════════════════
   LANDSCAPE MOBILE
════════════════════════════════ */
@media (max-width: 896px) and (orientation: landscape) and (max-height: 430px) {
  .msgs { padding: 8px 0 4px; }
  .input-area { padding: 5px 10px 6px; }
  .splash { padding: 12px; gap: 8px; }
  .splash-glyph { font-size: 32px; }
  .splash-title { font-size: 15px; }
  .acct-menu { max-height: 92dvh; }
}
"""

# ─────────────────────────────────────────────────────────────────────────────
# JS PATCH
# ─────────────────────────────────────────────────────────────────────────────
MOBILE_JS = r"""
/* ═══════════════════════════════════════════════════════════
   MOBILE PATCH v2 — JS helpers
═══════════════════════════════════════════════════════════ */
(function mobilePatch() {
  'use strict';

  const BP_MOBILE = 768;
  const BP_TABLET = 1024;
  const isMobile = () => window.innerWidth <= BP_MOBILE;
  const isTabletOrMobile = () => window.innerWidth <= BP_TABLET;

  /* ── backdrop singleton ─────────────────────────────────────── */
  let _bd = null;
  function backdrop(onTap) {
    if (!_bd) {
      _bd = document.createElement('div');
      _bd.className = 'm-backdrop';
      document.body.appendChild(_bd);
    }
    _bd._cb = onTap;
    _bd.onclick = () => { _bd._cb && _bd._cb(); };
    return _bd;
  }
  function showBackdrop(cb) { backdrop(cb).classList.add('on'); }
  function hideBackdrop()   { if (_bd) _bd.classList.remove('on'); }

  /* ══════════════════════════════════════════════════════════════
     SIDEBAR DRAWER
  ══════════════════════════════════════════════════════════════ */
  function sidebarIsOpen() {
    return document.getElementById('sidebar')?.classList.contains('m-open');
  }
  function openSidebar() {
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    sb.classList.add('m-open');
    showBackdrop(closeSidebar);
    document.body.style.overflow = 'hidden';
  }
  function closeSidebar() {
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    sb.classList.remove('m-open');
    hideBackdrop();
    document.body.style.overflow = '';
  }

  /* override global toggleSidebar */
  const _origToggleSidebar = window.toggleSidebar;
  window.toggleSidebar = function () {
    if (!isMobile()) { if (_origToggleSidebar) _origToggleSidebar(); return; }
    sidebarIsOpen() ? closeSidebar() : openSidebar();
  };

  /* auto-close sidebar when a conv is selected */
  const _origSelectConv = window.selectConv;
  window.selectConv = async function (...a) {
    const r = await _origSelectConv.apply(this, a);
    if (isMobile() && sidebarIsOpen()) setTimeout(closeSidebar, 120);
    return r;
  };

  /* auto-close sidebar on newConv */
  const _origNewConv = window.newConv;
  window.newConv = async function () {
    const r = await _origNewConv.apply(this);
    if (isMobile() && sidebarIsOpen()) setTimeout(closeSidebar, 120);
    return r;
  };

  /* ══════════════════════════════════════════════════════════════
     ACCOUNT SWITCHER — bottom-sheet on mobile
  ══════════════════════════════════════════════════════════════ */

  /* We wrap the original toggleAcctMenu so on mobile we get a proper
     bottom-sheet with its own backdrop instead of the dropdown. */
  const _origToggleAcctMenu = window.toggleAcctMenu;
  const _origCloseAcctMenu  = window.closeAcctMenu;

  window.toggleAcctMenu = function () {
    if (!isMobile()) { if (_origToggleAcctMenu) _origToggleAcctMenu(); return; }
    const menu = document.getElementById('acctMenu');
    if (!menu) return;
    const isHidden = menu.classList.contains('hidden');
    if (isHidden) {
      /* open */
      menu.classList.remove('hidden');
      document.getElementById('acctChev')?.classList.add('open');
      /* search field */
      const inp = document.getElementById('acctMenuSearchInp');
      if (inp) { inp.value = ''; if (typeof renderAccountMenu === 'function') renderAccountMenu(); }
      /* backdrop closes menu */
      showBackdrop(() => window.closeAcctMenu());
      document.body.style.overflow = 'hidden';
      /* scroll account list to active item */
      setTimeout(() => {
        const active = menu.querySelector('.acct-menu-item.active');
        if (active) active.scrollIntoView({ block: 'nearest' });
        if (inp) inp.focus();
      }, 80);
    } else {
      window.closeAcctMenu();
    }
  };

  window.closeAcctMenu = function () {
    const menu = document.getElementById('acctMenu');
    if (!menu) return;
    menu.classList.add('hidden');
    document.getElementById('acctChev')?.classList.remove('open');
    if (isMobile()) {
      hideBackdrop();
      document.body.style.overflow = '';
    }
    /* call original to handle any extra logic */
    /* (don't recurse — just update UI state) */
  };

  /* patch the outside-click listener that was added by the original code
     — on mobile we use the backdrop instead, so kill it cleanly */
  const _origCloseOnOutside = window._closeAcctOnOutside;
  window._closeAcctOnOutside = function (e) {
    if (isMobile()) return; /* backdrop handles this */
    if (_origCloseOnOutside) _origCloseOnOutside(e);
  };

  /* ══════════════════════════════════════════════════════════════
     SIDE PANELS — backdrop when open on mobile/tablet
  ══════════════════════════════════════════════════════════════ */
  const PANEL_IDS = ['canvasPanel','oneminaiPanel','flowithPanel','bexPanel'];

  function anyPanelOpen() {
    return PANEL_IDS.some(id => {
      const el = document.getElementById(id);
      return el && !el.classList.contains('collapsed');
    });
  }
  function closeAllPanels() {
    PANEL_IDS.forEach(id => document.getElementById(id)?.classList.add('collapsed'));
    hideBackdrop();
    document.body.style.overflow = '';
    /* sync btn states */
    ['canvasToggleBtn','oneminaiPanelBtn','flowithPanelBtn','branchExplorerBtn']
      .forEach(id => document.getElementById(id)?.classList.remove('active'));
    if (typeof S !== 'undefined') S.canvasOpen = false;
    if (typeof BEX !== 'undefined') BEX.open = false;
  }

  function afterPanelToggle() {
    if (!isTabletOrMobile()) return;
    if (anyPanelOpen()) {
      showBackdrop(closeAllPanels);
      document.body.style.overflow = 'hidden';
    } else {
      hideBackdrop();
      document.body.style.overflow = '';
    }
  }

  /* wrap each panel toggle */
  ;[
    ['toggleCanvas',          window.toggleCanvas],
    ['toggleOneminaiPanel',   window.toggleOneminaiPanel],
    ['toggleFlowithPanel',    window.toggleFlowithPanel],
    ['toggleBranchExplorer',  window.toggleBranchExplorer],
  ].forEach(([name, orig]) => {
    window[name] = function (...a) {
      if (orig) orig.apply(this, a);
      setTimeout(afterPanelToggle, 30);
    };
  });

  /* ══════════════════════════════════════════════════════════════
     SWIPE GESTURES
  ══════════════════════════════════════════════════════════════ */
  let tx0 = 0, ty0 = 0, tgt0 = null;

  document.addEventListener('touchstart', e => {
    tx0  = e.touches[0].clientX;
    ty0  = e.touches[0].clientY;
    tgt0 = e.target;
  }, { passive: true });

  document.addEventListener('touchend', e => {
    if (!isMobile()) return;
    const dx = e.changedTouches[0].clientX - tx0;
    const dy = e.changedTouches[0].clientY - ty0;
    if (Math.abs(dy) > Math.abs(dx) * 0.75) return; /* vertical swipe */
    if (Math.abs(dx) < 48) return;                   /* too short */

    /* swipe right from left edge → open sidebar */
    if (dx > 0 && tx0 < 28 && !sidebarIsOpen()) { openSidebar(); return; }

    /* swipe left inside sidebar → close */
    if (dx < 0 && sidebarIsOpen() &&
        document.getElementById('sidebar')?.contains(tgt0)) {
      closeSidebar(); return;
    }

    /* swipe left → close open panels */
    if (dx < -60 && anyPanelOpen()) closeAllPanels();
  }, { passive: true });

  /* ══════════════════════════════════════════════════════════════
     IOS KEYBOARD — keep messages visible
  ══════════════════════════════════════════════════════════════ */
  if (window.visualViewport) {
    let lastHeight = window.visualViewport.height;
    window.visualViewport.addEventListener('resize', () => {
      if (!isMobile()) return;
      const newH = window.visualViewport.height;
      if (newH < lastHeight - 80) {
        /* keyboard appeared — scroll to bottom */
        const msgs = document.getElementById('msgs');
        if (msgs) msgs.scrollTop = msgs.scrollHeight;
      }
      lastHeight = newH;
    });
  }

  /* prevent iOS zoom on textarea focus */
  const ta = document.getElementById('msgTa');
  if (ta) ta.addEventListener('focus', () => {
    if (isMobile()) setTimeout(() => {
      ta.scrollIntoView({ block: 'end', behavior: 'smooth' });
    }, 320);
  });

  /* ══════════════════════════════════════════════════════════════
     INITIAL SETUP
  ══════════════════════════════════════════════════════════════ */
  function mobileInit() {
    if (!isMobile()) return;

    /* Start with sidebar closed */
    const sb = document.getElementById('sidebar');
    if (sb) {
      sb.classList.add('collapsed');
      sb.classList.remove('m-open');
    }
    document.getElementById('app')?.classList.add('sb-collapsed');

    /* shorter placeholder */
    if (ta && ta.placeholder.length > 20) ta.placeholder = 'Message…';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mobileInit);
  } else {
    mobileInit();
  }

  /* re-init on resize (desktop ↔ mobile) */
  let _rt;
  window.addEventListener('resize', () => {
    clearTimeout(_rt);
    _rt = setTimeout(() => {
      if (!isMobile()) {
        hideBackdrop();
        document.body.style.overflow = '';
      } else {
        mobileInit();
      }
    }, 150);
  });

  console.log('[MobilePatch v2] loaded');
})();
"""

# ─────────────────────────────────────────────────────────────────────────────
# VIEWPORT META FIX
# ─────────────────────────────────────────────────────────────────────────────
VIEWPORT_TAG = (
    '<meta name="viewport" content="width=device-width, initial-scale=1.0, '
    'maximum-scale=5.0, viewport-fit=cover">'
)


def patch_html(src: str) -> str:
    out = src

    # ── 1. Fix / add viewport meta ────────────────────────────────────────
    vp_pat = re.compile(r'<meta\s+name=["\']viewport["\'][^>]*/?>',
                        re.IGNORECASE)
    if vp_pat.search(out):
        out = vp_pat.sub(VIEWPORT_TAG, out)
    else:
        out = out.replace('<head>', f'<head>\n{VIEWPORT_TAG}', 1)

    # ── 2. Remove any previous mobile patch blocks (idempotent) ──────────
    out = re.sub(
        r'/\* ={5,}\s*MOBILE (PATCH|RESPONSIVENESS).*?(?=/\* ={5,}|\Z)',
        '',
        out,
        flags=re.DOTALL,
    )

    # ── 3. Inject CSS just before first </style> ─────────────────────────
    out = out.replace('</style>', f'\n{MOBILE_CSS}\n</style>', 1)

    # ── 4. Inject JS just before last </script> ───────────────────────────
    pos = out.rfind('</script>')
    if pos != -1:
        out = out[:pos] + f'\n{MOBILE_JS}\n' + out[pos:]

    return out


def main() -> int:
    if not TARGET.exists():
        print(f'ERROR: {TARGET} not found — run from the project root.')
        return 1

    print(f'Backing up → {BACKUP}')
    shutil.copy2(TARGET, BACKUP)

    src = TARGET.read_text(encoding='utf-8')
    patched = patch_html(src)
    TARGET.write_text(patched, encoding='utf-8')

    added = len(patched) - len(src)
    print(f'Done.  {len(src):,} → {len(patched):,} bytes  (+{added:,})')
    print()
    print('Changes applied:')
    print('  ✓ Viewport meta corrected (viewport-fit=cover, max-scale 5)')
    print('  ✓ Sidebar → fixed slide-over drawer with swipe + backdrop')
    print('  ✓ Account switcher → full-width bottom-sheet on mobile')
    print('  ✓ All side panels (Canvas/BEX/1min.AI/Flowith) → right drawers')
    print('  ✓ Modals → bottom-sheet on mobile')
    print('  ✓ Toolbar → horizontal scroll, fat tap targets')
    print('  ✓ Input → 16 px font (stops iOS zoom), safe-area padding')
    print('  ✓ Swipe-from-edge gestures (open sidebar / close panels)')
    print('  ✓ iOS keyboard scroll fix via visualViewport API')
    print('  ✓ Backdrop singleton (one element, reused)')
    print(f'\nBackup: {BACKUP}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
