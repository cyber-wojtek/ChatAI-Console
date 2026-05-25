import re

def fix_css(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        css = f.read()

    fixes = [
        # Fix the double-dot typo on .btn-new
        ('..btn-new {', '.btn-new {'),

        # Fix .sb-section letter-spacing (was .01em — too tight for uppercase labels)
        (
            '.sb-section {\n  font-size: var(--fs-xs); font-weight:700;\n  text-transform:uppercase; letter-spacing:.01em;',
            '.sb-section {\n  font-size: var(--fs-xs); font-weight:700;\n  text-transform:uppercase; letter-spacing:.08em;',
        ),

        # Splash: bring glyph down from 72px (already 72 in original, keep but ensure it's set)
        # Splash title: ensure it uses --fs-3xl not --fs-4xl for less "screaming"
        (
            '.splash-title { \n  font-family:var(--font-head); font-size: var(--fs-4xl); font-weight:700;',
            '.splash-title { \n  font-family:var(--font-head); font-size: var(--fs-3xl); font-weight:700;',
        ),

        # btn-splash-new: tighten padding to match btn-new height rhythm
        (
            '.btn-splash-new {\n  padding: 12px 28px; background:linear-gradient(135deg, var(--accent), #7c3aed);\n  border-radius:var(--r-l); color:#fff; font-size: var(--fs-base); font-weight:600;',
            '.btn-splash-new {\n  padding: 10px 24px; background:linear-gradient(135deg, var(--accent), #7c3aed);\n  border-radius:var(--r-l); color:#fff; font-size: var(--fs-md2); font-weight:600;',
        ),

        # btn-sec-small: align padding with btn-splash-new
        (
            '.btn-sec-small {\n  padding: 11px 18px; background:var(--bg-3); border:1px solid var(--border-m);\n  border-radius:var(--r-l); color:var(--text-2); font-size:var(--fs-md); font-weight:500;',
            '.btn-sec-small {\n  padding: 9px 16px; background:var(--bg-3); border:1px solid var(--border-m);\n  border-radius:var(--r-l); color:var(--text-2); font-size:var(--fs-md); font-weight:500;',
        ),

        # Toolbar: unify tb-toggle and tb-icon height to --h-sm (32px) for tighter bar
        # The toolbar is 48px; 32px elements give 8px padding each side — clean
        (
            '.tb-toggle,\n.tb-icon,\n.tb-branch-btn {\n  height: var(--h-md);          /* 36px everywhere */',
            '.tb-toggle,\n.tb-icon,\n.tb-branch-btn {\n  height: var(--h-sm);          /* 32px — tighter toolbar */',
        ),
        # tb-icon width to match new height
        (
            '.tb-icon   { width: var(--h-md); padding: 0; font-size: 14px; }',
            '.tb-icon   { width: var(--h-sm); padding: 0; font-size: 13px; }',
        ),

        # Model selector in toolbar: match new --h-sm
        (
            '.tb-group #modelSel.dd-wrap {\n  height: var(--h-md);\n}',
            '.tb-group #modelSel.dd-wrap {\n  height: var(--h-sm);\n}',
        ),
        (
            '.tb-group #modelSel > .dd-btn {\n  height: var(--h-md);\n  min-height: var(--h-md);',
            '.tb-group #modelSel > .dd-btn {\n  height: var(--h-sm);\n  min-height: var(--h-sm);',
        ),

        # Toolbar dd-btn context variant: match --h-sm
        (
            '.tb-group .dd-wrap .dd-btn { \n  min-height: var(--h-md);',
            '.tb-group .dd-wrap .dd-btn { \n  min-height: var(--h-sm);',
        ),

        # #modelSel pill: match --h-sm
        (
            '#modelSel > .dd-btn {\n  border-radius: var(--r-l);\n  padding: 0 10px;\n  background: var(--surface-2);\n  border-color: var(--border);\n  min-height: var(--h-md);',
            '#modelSel > .dd-btn {\n  border-radius: var(--r-l);\n  padding: 0 10px;\n  background: var(--surface-2);\n  border-color: var(--border);\n  min-height: var(--h-sm);',
        ),

        # send-btn: size down slightly so it sits flush in 8px padded input-box
        (
            '.send-btn {\n  width: 38px; height: 38px; border-radius:var(--r-l);',
            '.send-btn {\n  width: 34px; height: 34px; border-radius:var(--r-l);',
        ),

        # inp-btn: match send-btn scale
        (
            '.inp-btn {\n  width: 36px; height: 36px; background:none; border-radius:var(--r);\n  color:var(--text-3); font-size: 16px;',
            '.inp-btn {\n  width: 32px; height: 32px; background:none; border-radius:var(--r);\n  color:var(--text-3); font-size: 15px;',
        ),

        # msg padding: reduce horizontal from 28px to 22px — less wasted space
        (
            '.msg {\n  display:flex; flex-direction:column;\n  animation:fadeUp .2s var(--ease); padding: 0 28px;',
            '.msg {\n  display:flex; flex-direction:column;\n  animation:fadeUp .2s var(--ease); padding: 0 22px;',
        ),

        # msg + msg margin: from 24px to 20px
        (
            '.msg + .msg { margin-top: 24px; }',
            '.msg + .msg { margin-top: 20px; }',
        ),

        # human bubble max-width: 72% -> 68% (less dominant)
        (
            'max-width: 72%; padding: 12px 16px;',
            'max-width: 68%; padding: 10px 15px;',
        ),

        # quota-wrap: tighten internal spacing
        (
            '.quota-wrap { \n  margin-bottom: 10px; padding: 10px 12px;',
            '.quota-wrap { \n  margin-bottom: 8px; padding: 8px 10px;',
        ),

        # quota-bar-bg: thinner bar (3px -> 2px)
        (
            '.quota-bar-bg { height:3px; background:var(--bg-5); border-radius:2px; overflow:hidden; }',
            '.quota-bar-bg { height:2px; background:var(--bg-5); border-radius:2px; overflow:hidden; }',
        ),

        # acct-active padding: tighten
        (
            '.acct-active {\n  display:flex; align-items:center; gap:10px; padding: 7px 9px;',
            '.acct-active {\n  display:flex; align-items:center; gap:8px; padding: 6px 8px;',
        ),

        # sb-foot: slightly tighter
        (
            '.sb-foot { padding: 8px 10px 10px; border-top:1px solid var(--border); flex-shrink:0; }',
            '.sb-foot { padding: 6px 10px 8px; border-top:1px solid var(--border); flex-shrink:0; }',
        ),

        # Modal header font size: xl -> lg (less oversized)
        (
            '.modal-hd {\n  display:flex; align-items:center; gap:10px; margin-bottom: 20px;\n  font-family:var(--font-head); font-size: var(--fs-xl); font-weight:700;\n}',
            '.modal-hd {\n  display:flex; align-items:center; gap:10px; margin-bottom: 16px;\n  font-family:var(--font-head); font-size: var(--fs-lg); font-weight:700;\n}',
        ),

        # btn-pri/btn-sec: match --r (8px) radius everywhere for consistency
        # They already use var(--r) — ensure font sizes match
        (
            '.btn-pri {\n  padding: 9px 18px; background:linear-gradient(135deg, var(--accent), #7c3aed);\n  border-radius:var(--r); color:#fff; font-size: var(--fs-md2); font-weight:600;',
            '.btn-pri {\n  padding: 8px 16px; background:linear-gradient(135deg, var(--accent), #7c3aed);\n  border-radius:var(--r); color:#fff; font-size: var(--fs-md); font-weight:600;',
        ),
        (
            '.btn-sec {\n  padding: 9px 18px; background:var(--bg-3); border:1px solid var(--border);\n  border-radius:var(--r); color:var(--text-2); font-size: var(--fs-md2); font-weight:500;',
            '.btn-sec {\n  padding: 8px 16px; background:var(--bg-3); border:1px solid var(--border);\n  border-radius:var(--r); color:var(--text-2); font-size: var(--fs-md); font-weight:500;',
        ),

        # input-area: tighter vertical padding
        (
            '.input-area {\n  padding: var(--sp-3) var(--sp-5) var(--sp-4);',
            '.input-area {\n  padding: var(--sp-2) var(--sp-4) var(--sp-3);',
        ),

        # input-box focus glow: soften (was 4px ring)
        (
            '.input-box:focus-within {\n  border-color:rgba(168,85,247,0.35);\n  box-shadow:0 0 0 4px rgba(168,85,247,0.06), 0 0 30px rgba(168,85,247,0.06), 0 4px 20px rgba(0,0,0,.3);\n}',
            '.input-box:focus-within {\n  border-color:rgba(168,85,247,0.30);\n  box-shadow:0 0 0 3px rgba(168,85,247,0.05), 0 2px 12px rgba(0,0,0,.25);\n}',
        ),

        # canvas-tab: tighten padding
        (
            '.canvas-tab {\n  padding: 10px 14px; font-size: 12px; font-weight:600; cursor:pointer;',
            '.canvas-tab {\n  padding: 8px 12px; font-size: 11.5px; font-weight:600; cursor:pointer;',
        ),

        # omai/flowith/bex panel heads: tighten
        (
            '.omai-panel-head {\n  display: flex;\n  align-items: center;\n  gap: 10px;\n  padding: 12px 14px 10px;',
            '.omai-panel-head {\n  display: flex;\n  align-items: center;\n  gap: 10px;\n  padding: 10px 12px 8px;',
        ),
        (
            '.flowith-panel-head {\n  display: flex;\n  align-items: center;\n  gap: 10px;\n  padding: 12px 14px 10px;',
            '.flowith-panel-head {\n  display: flex;\n  align-items: center;\n  gap: 10px;\n  padding: 10px 12px 8px;',
        ),
        (
            '.bex-head {\n  display: flex;\n  align-items: center;\n  gap: 8px;\n  padding: 12px 14px 10px;',
            '.bex-head {\n  display: flex;\n  align-items: center;\n  gap: 8px;\n  padding: 10px 12px 8px;',
        ),

        # toast: slightly tighter
        (
            '.toast {\n  padding: 10px 14px; background:rgba(14,14,34,0.92); border:1px solid var(--border-m);\n  border-radius:var(--r-l); font-size: 12.5px;',
            '.toast {\n  padding: 8px 12px; background:rgba(14,14,34,0.92); border:1px solid var(--border-m);\n  border-radius:var(--r); font-size: 12px;',
        ),
    ]

    changed = 0
    for old, new in fixes:
        if old in css:
            css = css.replace(old, new, 1)
            changed += 1
        else:
            print(f"[WARN] Pattern not found:\n  {old[:80]!r}")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(css)

    print(f"\nDone — {changed}/{len(fixes)} fixes applied to {filepath}")


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else 'styles.css'
    fix_css(path)
