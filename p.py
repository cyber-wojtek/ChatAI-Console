#!/usr/bin/env python3
"""
ChatAI Console CSS Patcher
Improves proportions, spacing, and usability of the interface.
"""

import re
import shutil
import sys
from pathlib import Path


PATCHES = [
    # ─────────────────────────────────────────────────────────────────────
    # 1. ROOT TOKENS — slightly larger base font, better border radii
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Root tokens — bump base font, refine radii",
        "find": r"(html, body \{[^}]*font-size:)15px",
        "replace": r"\g<1>16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Root token --r bump to 10px",
        "find": r"(--r:\s*)8px",
        "replace": r"\g<1>10px",
    },
    {
        "description": "Root token --r-l bump to 14px",
        "find": r"(--r-l:\s*)12px",
        "replace": r"\g<1>14px",
    },
    {
        "description": "Root token --r-xl bump to 18px",
        "find": r"(--r-xl:\s*)16px",
        "replace": r"\g<1>18px",
    },
    {
        "description": "Root token --r-2xl bump to 24px",
        "find": r"(--r-2xl:\s*)20px",
        "replace": r"\g<1>24px",
    },
    {
        "description": "Widen sidebar to 280px",
        "find": r"(--sidebar:\s*)260px",
        "replace": r"\g<1>280px",
    },

    # ─────────────────────────────────────────────────────────────────────
    # 2. SIDEBAR — more breathing room
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Sidebar head padding increase",
        "find": r"(\.sb-head \{[^}]*padding:)\s*18px 16px 14px",
        "replace": r"\g<1> 22px 18px 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Logo mark bigger",
        "find": r"(\.logo-mark \{[^}]*width:)\s*32px;\s*height:\s*32px",
        "replace": r"\g<1> 38px; height: 38px",
        "flags": re.DOTALL,
    },
    {
        "description": "Logo mark font size",
        "find": r"(\.logo-mark \{[^}]*font-size:)\s*15px",
        "replace": r"\g<1> 18px",
        "flags": re.DOTALL,
    },
    {
        "description": "Logo text bigger",
        "find": r"(\.logo-text \{[^}]*font-size:)\s*15px",
        "replace": r"\g<1> 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "New conv button padding",
        "find": r"(\.btn-new \{[^}]*padding:)\s*10px 14px",
        "replace": r"\g<1> 12px 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "New conv button font size",
        "find": r"(\.btn-new \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Conv item min height and padding",
        "find": r"(\.conv-item \{[^}]*padding:)\s*9px 10px 9px 12px",
        "replace": r"\g<1> 11px 12px 11px 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Conv name font size",
        "find": r"(\.conv-name \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Conv date font size",
        "find": r"(\.conv-date \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Sb section font size",
        "find": r"(\.sb-section \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "Search input padding and font size",
        "find": r"(\.search-inp \{[^}]*padding:)\s*8px 10px 8px 32px",
        "replace": r"\g<1> 9px 12px 9px 34px",
        "flags": re.DOTALL,
    },
    {
        "description": "Search input font size",
        "find": r"(\.search-inp \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 3. ACCOUNT SWITCHER — taller, more readable
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Acct active padding",
        "find": r"(\.acct-active \{[^}]*padding:)\s*9px 12px",
        "replace": r"\g<1> 11px 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Acct name font size",
        "find": r"(\.acct-name \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Acct org font size",
        "find": r"(\.acct-org\s+\{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Acct menu item padding",
        "find": r"(\.acct-menu-item \{[^}]*padding:)\s*8px 10px",
        "replace": r"\g<1> 10px 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Ami name font size",
        "find": r"(\.ami-name \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Ami org font size",
        "find": r"(\.ami-org\s+\{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 4. TOOLBAR — taller, better spaced controls
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Toolbar min-height",
        "find": r"(\.toolbar \{[^}]*min-height:)\s*58px",
        "replace": r"\g<1> 64px",
        "flags": re.DOTALL,
    },
    {
        "description": "Toolbar padding",
        "find": r"(\.toolbar \{[^}]*padding:)\s*10px 20px",
        "replace": r"\g<1> 12px 22px",
        "flags": re.DOTALL,
    },
    {
        "description": "Conv title font size",
        "find": r"(\.conv-title-display \{[^}]*font-size:)\s*15px",
        "replace": r"\g<1> 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tb-select height",
        "find": r"(\.tb-select \{[^}]*height:)\s*34px",
        "replace": r"\g<1> 38px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tb-select font size",
        "find": r"(\.tb-select \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tb-toggle height",
        "find": r"(\.tb-toggle \{[^}]*height:)\s*34px",
        "replace": r"\g<1> 38px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tb-toggle font size",
        "find": r"(\.tb-toggle \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tb-toggle padding",
        "find": r"(\.tb-toggle \{[^}]*padding:)\s*0 12px",
        "replace": r"\g<1> 0 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tb-icon width/height",
        "find": r"(\.tb-icon \{[^}]*width:)\s*34px;\s*height:\s*34px",
        "replace": r"\g<1> 38px; height: 38px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tb-icon font size",
        "find": r"(\.tb-icon \{[^}]*font-size:)\s*14px",
        "replace": r"\g<1> 16px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 5. MESSAGES — more padding, larger text
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Msgs top padding",
        "find": r"(\.msgs \{[^}]*padding:)\s*28px 0 12px",
        "replace": r"\g<1> 32px 0 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Message padding horizontal",
        "find": r"(\.msg \{[^}]*padding:)\s*0 28px",
        "replace": r"\g<1> 0 32px",
        "flags": re.DOTALL,
    },
    {
        "description": "Message gap",
        "find": r"(\.msg \+ \.msg \{[^}]*margin-top:)\s*22px",
        "replace": r"\g<1> 28px",
        "flags": re.DOTALL,
    },
    {
        "description": "Human message font size",
        "find": r"(\.msg\.human \.msg-body \{[^}]*font-size:)\s*14px",
        "replace": r"\g<1> 15px",
        "flags": re.DOTALL,
    },
    {
        "description": "Human message padding",
        "find": r"(\.msg\.human \.msg-body \{[^}]*padding:)\s*13px 17px",
        "replace": r"\g<1> 14px 18px",
        "flags": re.DOTALL,
    },
    {
        "description": "Assistant message font size",
        "find": r"(\.msg\.assistant \.msg-body \{[^}]*font-size:)\s*14px",
        "replace": r"\g<1> 15px",
        "flags": re.DOTALL,
    },
    {
        "description": "Msg sender font size",
        "find": r"(\.msg-sender \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Msg timestamp font size",
        "find": r"(\.msg-ts \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Msg avatar size",
        "find": r"(\.msg-avatar \{[^}]*width:)\s*22px;\s*height:\s*22px",
        "replace": r"\g<1> 26px; height: 26px",
        "flags": re.DOTALL,
    },
    {
        "description": "Msg avatar font size",
        "find": r"(\.msg-avatar \{[^}]*font-size:)\s*9px",
        "replace": r"\g<1> 10px",
        "flags": re.DOTALL,
    },
    {
        "description": "Msg header margin-bottom",
        "find": r"(\.msg-header \{[^}]*margin-bottom:)\s*8px",
        "replace": r"\g<1> 10px",
        "flags": re.DOTALL,
    },
    {
        "description": "Action button font size",
        "find": r"(\.msg-act-btn \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "Action button padding",
        "find": r"(\.msg-act-btn \{[^}]*padding:)\s*3px 8px",
        "replace": r"\g<1> 4px 10px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 6. MARKDOWN — better type scale
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Markdown p margin-bottom",
        "find": r"(\.md p \{[^}]*margin-bottom:)\s*10px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Markdown h1 font size",
        "find": r"(\.md h1 \{ font-size:)\s*22px",
        "replace": r"\g<1> 24px",
        "flags": re.DOTALL,
    },
    {
        "description": "Markdown h2 font size",
        "find": r"(\.md h2 \{ font-size:)\s*18px",
        "replace": r"\g<1> 20px",
        "flags": re.DOTALL,
    },
    {
        "description": "Markdown h3 font size",
        "find": r"(\.md h3 \{ font-size:)\s*15px",
        "replace": r"\g<1> 17px",
        "flags": re.DOTALL,
    },
    {
        "description": "Markdown inline code font size",
        "find": r"(\.md code \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Code block font size",
        "find": r"(\.md pre code \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Code block padding",
        "find": r"(\.md pre code \{[^}]*padding:)\s*16px 18px",
        "replace": r"\g<1> 18px 20px",
        "flags": re.DOTALL,
    },
    {
        "description": "Code header padding",
        "find": r"(\.code-header \{[^}]*padding:)\s*7px 14px",
        "replace": r"\g<1> 9px 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Code lang font size",
        "find": r"(\.code-lang \{[^}]*font-size:)\s*9px",
        "replace": r"\g<1> 10px",
        "flags": re.DOTALL,
    },
    {
        "description": "Code copy button font size",
        "find": r"(\.code-copy \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "Blockquote padding-left",
        "find": r"(\.md blockquote \{[^}]*padding-left:)\s*14px",
        "replace": r"\g<1> 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Markdown table font size",
        "find": r"(\.md table \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Table cell padding",
        "find": r"(\.md th,\.md td \{[^}]*padding:)\s*8px 12px",
        "replace": r"\g<1> 10px 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Markdown list item margin",
        "find": r"(\.md li \{[^}]*margin-bottom:)\s*4px",
        "replace": r"\g<1> 6px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 7. THINKING / TOOL BLOCKS — more readable
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Think header padding",
        "find": r"(\.think-hd \{[^}]*padding:)\s*8px 12px",
        "replace": r"\g<1> 10px 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Think label font size",
        "find": r"(\.think-label \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Think body font size",
        "find": r"(\.think-body \{[^}]*font-size:)\s*11\.5px",
        "replace": r"\g<1> 12.5px",
        "flags": re.DOTALL,
    },
    {
        "description": "Think body padding",
        "find": r"(\.think-body \{[^}]*padding:)\s*12px 14px",
        "replace": r"\g<1> 14px 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tool header padding",
        "find": r"(\.tool-hd \{[^}]*padding:)\s*7px 12px",
        "replace": r"\g<1> 9px 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tool name font size",
        "find": r"(\.tool-name \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tool body font size",
        "find": r"(\.tool-body \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Tool body padding",
        "find": r"(\.tool-body \{[^}]*padding:)\s*10px 14px",
        "replace": r"\g<1> 12px 16px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 8. INPUT AREA — more comfortable
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Input area padding",
        "find": r"(\.input-area \{[^}]*padding:)\s*12px 24px 16px",
        "replace": r"\g<1> 14px 26px 18px",
        "flags": re.DOTALL,
    },
    {
        "description": "Input box padding",
        "find": r"(\.input-box \{[^}]*padding:)\s*8px 8px 8px 4px",
        "replace": r"\g<1> 10px 10px 10px 6px",
        "flags": re.DOTALL,
    },
    {
        "description": "Textarea font size (desktop)",
        "find": r"(\.msg-ta \{[^}]*font-size:)\s*14px",
        "replace": r"\g<1> 15px",
        "flags": re.DOTALL,
    },
    {
        "description": "Textarea padding",
        "find": r"(\.msg-ta \{[^}]*padding:)\s*6px 0",
        "replace": r"\g<1> 8px 0",
        "flags": re.DOTALL,
    },
    {
        "description": "Send button size",
        "find": r"(\.send-btn \{[^}]*width:)\s*38px;\s*height:\s*38px",
        "replace": r"\g<1> 42px; height: 42px",
        "flags": re.DOTALL,
    },
    {
        "description": "Send button font size",
        "find": r"(\.send-btn \{[^}]*font-size:)\s*17px",
        "replace": r"\g<1> 20px",
        "flags": re.DOTALL,
    },
    {
        "description": "Inp btn size",
        "find": r"(\.inp-btn \{[^}]*width:)\s*34px;\s*height:\s*34px",
        "replace": r"\g<1> 38px; height: 38px",
        "flags": re.DOTALL,
    },
    {
        "description": "Inp btn font size",
        "find": r"(\.inp-btn \{[^}]*font-size:)\s*16px",
        "replace": r"\g<1> 18px",
        "flags": re.DOTALL,
    },
    {
        "description": "Input footer padding",
        "find": r"(\.input-footer \{[^}]*padding:)\s*6px 6px 0",
        "replace": r"\g<1> 8px 8px 0",
        "flags": re.DOTALL,
    },
    {
        "description": "Input hint font size",
        "find": r"(\.inp-hint \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Input char count font size",
        "find": r"(\.inp-count \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Attachment chip max-width",
        "find": r"(\.att-chip \{[^}]*max-width:)\s*220px",
        "replace": r"\g<1> 240px",
        "flags": re.DOTALL,
    },
    {
        "description": "Attachment chip font size",
        "find": r"(\.att-chip \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 9. MODALS — wider, better spaced
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Modal padding",
        "find": r"(\.modal \{[^}]*padding:)\s*28px",
        "replace": r"\g<1> 32px",
        "flags": re.DOTALL,
    },
    {
        "description": "Modal header font size",
        "find": r"(\.modal-hd \{[^}]*font-size:)\s*16px",
        "replace": r"\g<1> 18px",
        "flags": re.DOTALL,
    },
    {
        "description": "Form label font size",
        "find": r"(\.form-lbl \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Form input padding",
        "find": r"(\.form-inp \{[^}]*padding:)\s*10px 12px",
        "replace": r"\g<1> 11px 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Form input font size",
        "find": r"(\.form-inp \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Form hint font size",
        "find": r"(\.form-hint \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Section title font size",
        "find": r"(\.section-title \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Toggle label font size",
        "find": r"(\.toggle-lbl \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Toggle sub font size",
        "find": r"(\.toggle-sub \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Primary button padding",
        "find": r"(\.btn-pri \{[^}]*padding:)\s*10px 20px",
        "replace": r"\g<1> 11px 22px",
        "flags": re.DOTALL,
    },
    {
        "description": "Primary button font size",
        "find": r"(\.btn-pri \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Secondary button padding",
        "find": r"(\.btn-sec \{[^}]*padding:)\s*10px 20px",
        "replace": r"\g<1> 11px 22px",
        "flags": re.DOTALL,
    },
    {
        "description": "Secondary button font size",
        "find": r"(\.btn-sec \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 10. CANVAS / SIDE PANELS — wider and more comfortable
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Canvas panel width",
        "find": r"(--canvas-width:\s*)380px",
        "replace": r"\g<1>420px",
    },
    {
        "description": "Canvas tab font size",
        "find": r"(\.canvas-tab \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Canvas tab padding",
        "find": r"(\.canvas-tab \{[^}]*padding:)\s*10px 14px",
        "replace": r"\g<1> 12px 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai panel width",
        "find": r"(--omai-width:\s*)360px",
        "replace": r"\g<1>400px",
    },
    {
        "description": "Flowith panel width",
        "find": r"(--flowith-panel-width:\s*)360px",
        "replace": r"\g<1>400px",
    },
    {
        "description": "BEX panel width",
        "find": r"(--bex-width:\s*)340px",
        "replace": r"\g<1>380px",
    },
    {
        "description": "Omai tab font size",
        "find": r"(\.omai-tab \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai label font size",
        "find": r"(\.omai-label \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai select font size",
        "find": r"(\.omai-select \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai select padding",
        "find": r"(\.omai-select \{[^}]*padding:)\s*8px 10px",
        "replace": r"\g<1> 9px 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai input font size",
        "find": r"(\.omai-input \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai textarea font size",
        "find": r"(\.omai-textarea \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai run button font size",
        "find": r"(\.omai-run-btn \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai run button padding",
        "find": r"(\.omai-run-btn \{[^}]*padding:)\s*11px 16px",
        "replace": r"\g<1> 13px 18px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai card head font size",
        "find": r"(\.omai-card-head \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "Omai result content font size",
        "find": r"(\.omai-result-content \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 11. TOAST NOTIFICATIONS
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Toast font size",
        "find": r"(\.toast \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Toast padding",
        "find": r"(\.toast \{[^}]*padding:)\s*10px 14px",
        "replace": r"\g<1> 11px 16px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 12. QUOTA BAR — more visible
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Quota label font size",
        "find": r"(\.quota-label \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "Quota pct font size",
        "find": r"(\.quota-pct \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Quota bar height",
        "find": r"(\.quota-bar-bg \{[^}]*height:)\s*3px",
        "replace": r"\g<1> 4px",
        "flags": re.DOTALL,
    },
    {
        "description": "Quota detail font size",
        "find": r"(\.quota-detail \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 13. SPLASH — better proportions
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Splash glyph size",
        "find": r"(\.splash-glyph \{[^}]*font-size:)\s*72px",
        "replace": r"\g<1> 80px",
        "flags": re.DOTALL,
    },
    {
        "description": "Splash title size",
        "find": r"(\.splash-title \{[^}]*font-size:)\s*26px",
        "replace": r"\g<1> 30px",
        "flags": re.DOTALL,
    },
    {
        "description": "Splash subtitle size",
        "find": r"(\.splash-sub \{[^}]*font-size:)\s*14px",
        "replace": r"\g<1> 15px",
        "flags": re.DOTALL,
    },
    {
        "description": "Splash new button padding",
        "find": r"(\.btn-splash-new \{[^}]*padding:)\s*11px 28px",
        "replace": r"\g<1> 13px 32px",
        "flags": re.DOTALL,
    },
    {
        "description": "Splash new button font size",
        "find": r"(\.btn-splash-new \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 15px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 14. CHAT SEARCH BAR
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Chat search bar padding",
        "find": r"(\.chat-search-bar \{[^}]*padding:)\s*7px 16px 6px",
        "replace": r"\g<1> 9px 18px 8px",
        "flags": re.DOTALL,
    },
    {
        "description": "Chat search input font size",
        "find": r"(\.chat-search-inp \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Chat search count font size",
        "find": r"(\.chat-search-count \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 15. BRANCH EXPLORER
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "BEX title font size",
        "find": r"(\.bex-title \{[^}]*font-size:)\s*13px",
        "replace": r"\g<1> 14px",
        "flags": re.DOTALL,
    },
    {
        "description": "BEX preview font size",
        "find": r"(\.bex-preview \{[^}]*font-size:)\s*11\.5px",
        "replace": r"\g<1> 12.5px",
        "flags": re.DOTALL,
    },
    {
        "description": "BEX card padding",
        "find": r"(\.bex-card \{[^}]*padding:)\s*7px 10px",
        "replace": r"\g<1> 9px 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "BEX sender badge font size",
        "find": r"(\.bex-sender \{[^}]*font-size:)\s*9px",
        "replace": r"\g<1> 10px",
        "flags": re.DOTALL,
    },
    {
        "description": "BEX nav label font size",
        "find": r"(\.bex-nav-label \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "BEX nav button font size",
        "find": r"(\.bex-nav-btn \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 16. FILE CHIPS AND CANVAS FILES
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "File chip font size",
        "find": r"(\.file-chip \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "File chip padding",
        "find": r"(\.file-chip \{[^}]*padding:)\s*5px 10px",
        "replace": r"\g<1> 6px 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Cfile name font size",
        "find": r"(\.cfile-name \{[^}]*font-size:)\s*11\.5px",
        "replace": r"\g<1> 12.5px",
        "flags": re.DOTALL,
    },
    {
        "description": "Cfile meta font size",
        "find": r"(\.cfile-meta \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "Cfile icon/thumb size",
        "find": r"(\.cfile-thumb \{[^}]*width:)\s*34px;\s*height:\s*34px",
        "replace": r"\g<1> 40px; height: 40px",
        "flags": re.DOTALL,
    },
    {
        "description": "Cfile icon size",
        "find": r"(\.cfile-icon \{[^}]*width:)\s*34px;\s*height:\s*34px",
        "replace": r"\g<1> 40px; height: 40px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 17. ARTIFACT BLOCK
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Artifact header padding",
        "find": r"(\.artifact-hd \{[^}]*padding:)\s*10px 14px",
        "replace": r"\g<1> 12px 16px",
        "flags": re.DOTALL,
    },
    {
        "description": "Artifact title font size",
        "find": r"(\.artifact-title \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },
    {
        "description": "Artifact badge font size",
        "find": r"(\.artifact-badge \{[^}]*font-size:)\s*8px",
        "replace": r"\g<1> 9px",
        "flags": re.DOTALL,
    },
    {
        "description": "Artifact preview height",
        "find": r"(\.artifact-preview \{[^}]*height:)\s*420px",
        "replace": r"\g<1> 480px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 18. POLLING PANEL
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Polling panel width",
        "find": r"(\.polling-panel \{[^}]*width:)\s*320px",
        "replace": r"\g<1> 360px",
        "flags": re.DOTALL,
    },
    {
        "description": "Poll label font size",
        "find": r"(\.poll-label \{[^}]*font-size:)\s*11px",
        "replace": r"\g<1> 12px",
        "flags": re.DOTALL,
    },
    {
        "description": "Poll sub font size",
        "find": r"(\.poll-sub \{[^}]*font-size:)\s*10px",
        "replace": r"\g<1> 11px",
        "flags": re.DOTALL,
    },
    {
        "description": "Poll save button font size",
        "find": r"(\.poll-save-btn \{[^}]*font-size:)\s*12px",
        "replace": r"\g<1> 13px",
        "flags": re.DOTALL,
    },

    # ─────────────────────────────────────────────────────────────────────
    # 19. TABLET BREAKPOINT — keep panels at better width
    # ─────────────────────────────────────────────────────────────────────
    {
        "description": "Tablet canvas width",
        "find": r"(--canvas-width:\s*)300px",
        "replace": r"\g<1>340px",
    },
    {
        "description": "Tablet omai width",
        "find": r"(--omai-width:\s*)300px",
        "replace": r"\g<1>340px",
    },
    {
        "description": "Tablet flowith width",
        "find": r"(--flowith-panel-width:\s*)300px",
        "replace": r"\g<1>340px",
    },
    {
        "description": "Tablet bex width",
        "find": r"(--bex-width:\s*)280px",
        "replace": r"\g<1>320px",
    },
]


# ── helpers ───────────────────────────────────────────────────────────────

def apply_patches(source: str, patches: list) -> tuple[str, list, list]:
    """Apply all patches. Returns (result, applied, skipped)."""
    result  = source
    applied = []
    skipped = []

    for patch in patches:
        flags   = patch.get("flags", 0)
        pattern = patch["find"]
        repl    = patch["replace"]
        desc    = patch["description"]

        new_result, n = re.subn(pattern, repl, result, flags=flags)
        if n > 0:
            applied.append((desc, n))
            result = new_result
        else:
            skipped.append(desc)

    return result, applied, skipped


def patch_file(path: str) -> None:
    src = Path(path)
    if not src.exists():
        print(f"[ERROR] File not found: {path}")
        sys.exit(1)

    original = src.read_text(encoding="utf-8")

    # Backup
    backup = src.with_suffix(src.suffix + ".bak")
    shutil.copy2(src, backup)
    print(f"[backup]  {backup}")

    patched, applied, skipped = apply_patches(original, PATCHES)

    src.write_text(patched, encoding="utf-8")

    print(f"\n{'─'*60}")
    print(f"  ✓ Applied  ({len(applied)} patches)")
    print(f"{'─'*60}")
    for desc, n in applied:
        mark = "  " if n == 1 else f"×{n} "
        print(f"  {mark}{desc}")

    if skipped:
        print(f"\n{'─'*60}")
        print(f"  ⚠ Skipped  ({len(skipped)} — pattern not found, may already be patched)")
        print(f"{'─'*60}")
        for desc in skipped:
            print(f"    {desc}")

    print(f"\n[done]  Wrote {src}  ({len(patched):,} bytes)")


# ── entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patcher.py <path/to/index.html>")
        sys.exit(1)

    patch_file(sys.argv[1])
