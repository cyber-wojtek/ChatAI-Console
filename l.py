import os

FILE_PATH = "templates/index.html"

def patch_file():
    if not os.path.exists(FILE_PATH):
        print(f"Error: {FILE_PATH} not found.")
        return

    with open(FILE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Add "Copy Conversation" button to the toolbar
    toolbar_search = '<button class="tb-icon" onclick="refreshConv()" title="Refresh">↻</button>'
    toolbar_replace = '''<button class="tb-icon" onclick="openCopyConvOverlay()" title="Copy Conversation">📋</button>
          <button class="tb-icon" onclick="refreshConv()" title="Refresh">↻</button>'''
    
    if toolbar_search in html:
        html = html.replace(toolbar_search, toolbar_replace)
        print("Patched: Toolbar 'Copy Conversation' button.")
    else:
        print("Skipped: Toolbar button (already patched or not found).")

    # 2. Add the Copy Conversation Format Modal
    modal_search = '<!-- ── TOASTS ── -->'
    modal_replace = '''<!-- ── COPY CONV MODAL ── -->
<div class="overlay" id="copyConvOverlay">
  <div class="modal">
    <div class="modal-hd">📋 Copy Conversation
      <button class="modal-close" onclick="closeOverlay('copyConvOverlay')">×</button>
    </div>
    <div class="form-row">
      <label class="form-lbl">Format</label>
      <select class="form-inp" id="copyConvFormatSel">
        <option value="standard">Standard (You: ... Assistant: ...)</option>
        <option value="prompt">Prompt Format (---- Human: ... ---- Assistant: ...)</option>
        <option value="json">JSON</option>
      </select>
    </div>
    <div class="modal-actions">
      <button class="btn-sec" onclick="closeOverlay('copyConvOverlay')">Cancel</button>
      <button class="btn-pri" onclick="doCopyConv(this)">Copy</button>
    </div>
  </div>
</div>

<!-- ── TOASTS ── -->'''
    
    if modal_search in html and 'id="copyConvOverlay"' not in html:
        html = html.replace(modal_search, modal_replace)
        print("Patched: Copy Conversation modal.")
    else:
        print("Skipped: Copy Conversation modal.")

    # 3. Patch the Marked.js code renderer to include a "Render" button
    render_search = '''    return `<pre><div class="code-header">
      <span class="code-lang">${esc(language || 'code')}</span>
      <button class="code-copy" data-copy-id="${id}">⎘ Copy</button>
    </div><code id="${id}" class="hljs language-${esc(validLang)}" data-raw="${encodedCode}">${highlighted}</code></pre>`;'''
    
    render_replace = '''    let renderBtn = '';
    const l = validLang.toLowerCase();
    if (['svg', 'html', 'mermaid'].includes(l)) {
      renderBtn = `<button class="code-copy" onclick="renderCodeBlock('${id}', '${l}')" style="color:var(--teal);border-color:rgba(56,189,248,0.25)">👁 Render</button>`;
    }
    return `<pre><div class="code-header">
      <span class="code-lang">${esc(language || 'code')}</span>
      <div style="display:flex;gap:4px">
        ${renderBtn}
        <button class="code-copy" data-copy-id="${id}">⎘ Copy</button>
      </div>
    </div><code id="${id}" class="hljs language-${esc(validLang)}" data-raw="${encodedCode}">${highlighted}</code></pre>`;'''
    
    if render_search in html:
        html = html.replace(render_search, render_replace)
        print("Patched: Markdown code block renderer.")
    else:
        print("Skipped: Markdown code block renderer.")

    # 4. Inject the supporting JavaScript logic
    js_search = '/* ═══════════════════════════════════════════\n   BOOT\n═══════════════════════════════════════════ */'
    js_replace = '''/* ═══════════════════════════════════════════
   COPY CONV & RENDER UTILS
═══════════════════════════════════════════ */
function openCopyConvOverlay() {
  if (!S.convId || !S.convs[S.convId] || !S.convs[S.convId].chat_messages?.length) {
    toast('Conversation is empty', 'err');
    return;
  }
  openOverlay('copyConvOverlay');
}

function doCopyConv(btn) {
  const fmt = document.getElementById('copyConvFormatSel').value;
  const msgs = buildChain(S.convs[S.convId]);
  let res = '';
  
  if (fmt === 'json') {
    res = JSON.stringify(msgs, null, 2);
  } else {
    for (const m of msgs) {
      const role = m.sender === 'human' ? 'Human' : 'Assistant';
      const text = m.text || (m.content || []).filter(c=>c.type==='text').map(c=>c.text).join('\\n');
      
      if (fmt === 'prompt') {
        res += `---- ${role}: ----\\n${text}\\n\\n`;
      } else {
        const name = role === 'Human' ? 'You' : 'Assistant';
        res += `${name}:\\n${text}\\n\\n`;
      }
    }
  }
  
  navigator.clipboard.writeText(res.trim()).then(() => {
    const old = btn.textContent;
    btn.textContent = '✓ Copied';
    setTimeout(() => { btn.textContent = old; closeOverlay('copyConvOverlay'); }, 1500);
  }).catch(e => toast('Copy failed', 'err'));
}

function renderCodeBlock(id, lang) {
  const el = document.getElementById(id);
  if (!el) return;
  let rawCode = '';
  try { rawCode = decodeURIComponent(escape(atob(el.dataset.raw))); }
  catch { rawCode = el.textContent; }

  let mime = 'text/plain';
  if (lang === 'svg') mime = 'image/svg+xml';
  else if (lang === 'html') mime = 'text/html';

  if (lang === 'mermaid') {
    rawCode = `<!DOCTYPE html><html><body style="background:#fff;display:flex;justify-content:center;padding:20px;"><script type="module">import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';mermaid.initialize({startOnLoad:true});</script><div class="mermaid">${rawCode}</div></body></html>`;
    mime = 'text/html';
  }

  const blob = new Blob([rawCode], { type: mime });
  const url = URL.createObjectURL(blob);
  openInCanvas(url, `Rendered ${lang.toUpperCase()}`, mime);
}

/* ═══════════════════════════════════════════
   BOOT
═══════════════════════════════════════════ */'''

    if js_search in html and 'function doCopyConv' not in html:
        html = html.replace(js_search, js_replace)
        print("Patched: Core JS functions.")
    else:
        print("Skipped: Core JS functions.")

    with open(FILE_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    
    print("Patching complete!")

if __name__ == "__main__":
    patch_file()