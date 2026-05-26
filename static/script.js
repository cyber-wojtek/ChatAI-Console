
/* ═══════════════════════════════════════════
   MOBILE HELPERS — part of main codebase
═══════════════════════════════════════════ */
const _isMobile        = () => window.innerWidth <= 768;
const _isTabletOrMobile = () => window.innerWidth <= 1024;

function _mobileBackdrop() {
  let bd = document.getElementById('mBackdrop');
  if (!bd) {
    bd = document.createElement('div');
    bd.id = 'mBackdrop';
    bd.className = 'm-backdrop';
    document.body.appendChild(bd);
  }
  return bd;
}
function _showMobileBackdrop(onTap) {
  const bd = _mobileBackdrop();
  bd.onclick = onTap;
  bd.classList.add('on');
}
function _hideMobileBackdrop() {
  document.getElementById('mBackdrop')?.classList.remove('on');
}

function _closeMobileSidebar() {
  document.getElementById('sidebar')?.classList.remove('m-open');
  _hideMobileBackdrop();
  document.body.style.overflow = '';
  _syncGlobalHamburger(false);
}
function _isMobileSidebarOpen() {
  return document.getElementById('sidebar')?.classList.contains('m-open') ?? false;
}

function _closeAllPanels() {
  ['canvasPanel','oneminaiPanel','flowithPanel','bexPanel'].forEach(id =>
    document.getElementById(id)?.classList.add('collapsed')
  );
  ['canvasToggleBtn','oneminaiPanelBtn','flowithPanelBtn','branchExplorerBtn'].forEach(id =>
    document.getElementById(id)?.classList.remove('active')
  );
  if (typeof S !== 'undefined') S.canvasOpen = false;
  if (typeof BEX !== 'undefined') BEX.open = false;
  _hideMobileBackdrop();
  document.body.style.overflow = '';
}

function _trackPanelBackdrop() {
  if (!_isTabletOrMobile()) return;
  const anyOpen = ['canvasPanel','oneminaiPanel','flowithPanel','bexPanel']
    .some(id => !document.getElementById(id)?.classList.contains('collapsed'));
  if (anyOpen) {
    _showMobileBackdrop(_closeAllPanels);
    document.body.style.overflow = 'hidden';
  } else {
    _hideMobileBackdrop();
    document.body.style.overflow = '';
  }
}

/* ═══════════════════════════════════════════
   STATE  — per-tab, not server-global
═══════════════════════════════════════════ */
const S = {
  // Per-tab account selection
  tabAccount:    null,   // { name, provider, provider_info, ... } chosen for THIS tab
  webSearch:     false,  // 1min.AI web search toggle
  
  // Conversation state
  convId:        null,
  convs:         {},
  allConvs:      [],
  pinnedIds:     [],
  
  // UI state
  streaming:     false,
  thinking:      false,
  attached:      [],
  configured:    false,
  activeAccount: null,   // server's "active" account (legacy fallback)
  accounts:      [],     // all known accounts
  sidebarOpen:   true,
  branchVisible: false,  // legacy — use BEX.open instead
  canvasOpen:    false,
  canvasTab:     'preview',
  chatQuery:     '',
};

let _activeNavCtl = null;

function _cancelPending() {
  if (_activeNavCtl) {
    _activeNavCtl.abort();
    _activeNavCtl = null;
  }
}

const contentCache = {};

/* ═══════════════════════════════════════════
   INIT
═══════════════════════════════════════════ */
async function init() {
  const renderer = new marked.Renderer();
  renderer.code = function(codeOrToken, lang) {
    let code, language;
    if (codeOrToken && typeof codeOrToken === 'object') {
      code     = codeOrToken.text || codeOrToken.raw || '';
      language = codeOrToken.lang || lang || '';
    } else {
      code     = codeOrToken || '';
      language = lang || '';
    }
    const validLang = language && hljs.getLanguage(language) ? language : 'plaintext';
    let highlighted;
    try { highlighted = hljs.highlight(code, { language: validLang }).value; }
    catch { highlighted = esc(code); }

    const id = 'cb_' + Math.random().toString(36).slice(2, 9);
    const encodedCode = btoa(unescape(encodeURIComponent(code)));

    let renderBtn = '';
    const l = validLang.toLowerCase();
    if (['svg', 'html', 'mermaid'].includes(l)) {
      renderBtn = `<button class="code-copy" onclick="renderCodeBlock('${id}', '${l}')" style="color:var(--teal);border-color:rgba(56,189,248,0.25)">👁 Render</button>`;
    }
    return `<pre><div class="code-header">
      <span class="code-lang">${esc(language || 'code')}</span>
      <div style="display:flex;gap:4px">
        ${renderBtn}
        <button class="code-copy" data-copy-id="${id}" style="color:var(--text-2)">⎘ Copy</button>
      </div>
    </div><code id="${id}" class="hljs language-${esc(validLang)}" data-raw="${encodedCode}">${highlighted}</code></pre>`;
  };


  renderer.link = async function(hrefOrToken, title, text) {
    let href, linkTitle, linkText;
    if (hrefOrToken && typeof hrefOrToken === 'object') {
      href      = hrefOrToken.href  || '';
      linkTitle = hrefOrToken.title || '';
      linkText  = hrefOrToken.text  || text || href;
    } else {
      href      = hrefOrToken || '';
      linkTitle = title || '';
      linkText  = text  || href;
    }
    const eHref = href.replace(/"/g,'&quot;');
    const titleAttr = linkTitle ? ` title="${linkTitle.replace(/"/g,'&quot;')}"` : '';
    return `<a href="${eHref}"${titleAttr} target="_blank" rel="noopener noreferrer">${linkText}</a>`;
  };

  marked.setOptions({ renderer: renderer });

  document.getElementById('msgs').addEventListener('click', function(e) {
    const btn = e.target.closest('.code-copy');
    if (!btn) return;
    
    const id = btn.dataset.copyId;
    const el = document.getElementById(id);
    if (!el) return;

    let rawCode = '';
    try {
      rawCode = decodeURIComponent(escape(atob(el.dataset.raw)));
    } catch {
      rawCode = el.textContent;
    }

    navigator.clipboard.writeText(rawCode).then(() => {
      btn.textContent = '✓ Copied';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = '⎘ Copy';
        btn.classList.remove('copied');
      }, 2000);
    }).catch(() => {
      toast('Copy failed', 'err');
    });
  });

  // Show UI immediately with empty state
  renderSidebar();
  setupDragDrop();

  // Load accounts first (fast — memory only now)
  await refreshAccountState();

  // Load pinned (local store, fast) immediately
  await loadPinnedIds();
  renderSidebar();  // show pinned convs right away

  // Load remote convs in background — don't await
  loadAllConvs().then(() => renderSidebar()).catch(() => {});

  // Preferences in background
  fetch('/api/preferences').then(r => r.json()).then(prefs => {
    if (prefs.theme) document.documentElement.setAttribute('data-theme', prefs.theme);
  }).catch(() => {});

  // Warm up models + credits for the initial account (background, no await)
  const _initAcct = getTabAccount();
  if (_initAcct) {
    const _initProv = (_initAcct.provider || 'claude').toLowerCase();
    if (_initProv === 'chatwithai') {
      _fetchAndCacheChatwithaiModels().then(models => {
        if (models.length) {
          const sel = document.getElementById('modelSel');
          if (sel && getTabProvider() === 'chatwithai') {
            const cur = ddGetValue(sel);
            const byVendor = {};
            models.forEach(m => {
              const v = m.vendor_slug || m.vendor || '__none__';
              (byVendor[v] = byVendor[v] || []).push(m);
            });
            const vendors = Object.keys(byVendor);
            const useGroups = vendors.length > 1 || (vendors[0] !== '__none__' && models[0]?.vendor);
            const groups = useGroups
              ? vendors.map(v => ({ label: byVendor[v][0].vendor || v, options: byVendor[v].map(m => ({ value: m.id, text: m.display_name || m.id })) }))
              : [{ options: models.map(m => ({ value: m.id, text: m.display_name || m.id })) }];
            ddRebuild(sel, groups);
            if (cur) ddSetValue(sel, cur);
          }
        }
      }).catch(() => {});
    } else if (_initProv === 'flowith') {
      _fetchAndCacheFlowithModels().catch(() => {});
    } else if (_initProv === 'oneminai') {
      _omaiScheduleRefresh(); // <-- ADD THIS LINE
      fetchOneminaiModels(false).catch(() => {});
    }
    else {
      refreshModels(true).catch(() => {});
    }
    // Claude quota fetched by _pollAllAccounts below
  }

  const urlAcct   = getAcctIdFromUrl();
  const urlConvId = getConvIdFromUrl();
  if (urlConvId) {
    let acctToUse = urlAcct || getTabAccountName();
    if (urlAcct) {
      const found = S.accounts.find(a => a.name === urlAcct);
      if (!found) {
        history.replaceState(null, '', '/');
        toast('Account in URL not found', 'err');
        acctToUse = null;
      } else if (urlAcct !== getTabAccountName()) {
        // Activate the account embedded in the URL before fetching the conv
        await switchTabAccount(urlAcct);
        refreshModels(true).catch(() => {});
      }
    }
    if (acctToUse) {
      await selectConv(urlConvId, acctToUse, true);
      if (!S.convs[urlConvId]?.chat_messages) {
        history.replaceState(null, '', '/');
        S.convId = null;
        document.getElementById('chat').classList.add('hidden');
        document.getElementById('splash').classList.remove('hidden');
        toast('Conversation not found', 'err');
      }
    }
  }

  window.addEventListener('popstate', onPopState);

  // First poll
  setTimeout(() => {
    _pollAllAccounts();
  }, 10 * 1000);
}

/* ═══════════════════════════════════════════
   URL ROUTING
═══════════════════════════════════════════ */
function getConvIdFromUrl() {
  // matches both /c/<uuid> and /a/<acct>/c/<uuid>
  const m = window.location.pathname.match(/\/c\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/);
  return m ? m[1] : null;
}

function getAcctIdFromUrl() {
  // Match /a/accountName/ or /a/accountName/c/convId
  const m = window.location.pathname.match(/^\/a\/([^\/]+)(?:\/c\/[a-f0-9-]+)?/);
  return m ? decodeURIComponent(m[1]) === "undefined" ? null : decodeURIComponent(m[1]) : null;
}
function navToHome(replace) {
  S.convId = null;
  document.getElementById('chat').classList.add('hidden');
  document.getElementById('splash').classList.remove('hidden');
  document.title = 'ChatAI Console';
  if (replace) history.replaceState(null, '', '/');
  else history.pushState(null, '', '/');
  renderSidebar();
  // Collapse sidebar when returning home
  if (_isMobile()) {
    _closeMobileSidebar();
  }
}
async function onPopState(e) {
  const urlAcct = getAcctIdFromUrl();
  const id      = e.state?.convId || getConvIdFromUrl();
  if (id) {
    if (urlAcct && urlAcct !== getTabAccountName()) {
      const found = S.accounts.find(a => a.name === urlAcct);
      if (found) await switchTabAccount(urlAcct);
    }
    await selectConv(id, urlAcct || getTabAccountName(), true);
    if (!S.convs[id]?.chat_messages) navToHome(true);
  } else {
    S.convId = null;
    document.getElementById('chat').classList.add('hidden');
    document.getElementById('splash').classList.remove('hidden');
    document.title = 'ChatAI Console';
    renderSidebar();
  }
}

/* ═══════════════════════════════════════════
   DRAG-AND-DROP + PASTE
═══════════════════════════════════════════ */
function setupDragDrop() {
  const overlay = document.getElementById('dropOverlay');
  let dragCount = 0;
  document.addEventListener('dragenter', e => {
    if (!S.convId) return;
    if (e.dataTransfer?.types?.includes('Files')) { dragCount++; overlay.classList.add('active'); }
  }, true);
  document.addEventListener('dragleave', () => {
    dragCount--; if (dragCount <= 0) { dragCount = 0; overlay.classList.remove('active'); }
  }, true);
  document.addEventListener('dragover', e => e.preventDefault(), true);
  document.addEventListener('drop', async e => {
    e.preventDefault(); dragCount = 0; overlay.classList.remove('active');
    if (!S.convId) return;
    for (const f of Array.from(e.dataTransfer?.files || [])) await uploadSingleFile(f);
  }, true);
}

async function handlePaste(e) {
  if (!S.convId) return;
  const items = Array.from(e.clipboardData?.items || []);
  const imageItems = items.filter(item => item.type.startsWith('image/'));
  if (!imageItems.length) return;
  e.preventDefault();
  for (const item of imageItems) {
    const file = item.getAsFile();
    if (!file) continue;
    const ext = item.type.split('/')[1] || 'png';
    const namedFile = new File([file], `clipboard-${Date.now()}.${ext}`, { type: item.type });
    await uploadSingleFile(namedFile);
  }
}

/* ═══════════════════════════════════════════
   UTILS
═══════════════════════════════════════════ */

/* ── Account for this tab ── */
function getTabAccount() {
  // Use explicitly chosen tab account, else server active, else first account
  return S.tabAccount 
      || S.accounts.find(a => a.active) 
      || S.accounts[0] 
      || null;
}

function getTabAccountName() {
  return getTabAccount()?.name || null;
}

function getTabProvider() {
  return (getTabAccount()?.provider || 'claude').toLowerCase();
}

function getTabProviderInfo() {
  return getTabAccount()?.provider_info || {
    type: 'claude',
    supports_files: true,
    supports_artifacts: true,
    supports_tools: true,
    supports_thinking: true,
    supports_branching: true,
    default_model: 'claude-sonnet-4-6',
  };
}

/* ── API fetch with per-tab account header ── */
// All JSON API calls
async function apiFetch(url, opts = {}) {
  opts.headers = opts.headers || {};
  const name = getTabAccountName();
  if (name) opts.headers['X-Account-Name'] = name;
  const r = await fetch(url, opts);
  if (!r.ok && r.status !== 404) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// Streaming / raw response calls
async function apiFetchRaw(url, opts = {}) {
  opts.headers = opts.headers || {};
  const name = getTabAccountName();
  if (name) opts.headers['X-Account-Name'] = name;
  return fetch(url, opts);
}

async function loadPinnedIds(signal) {
  try {
    S.pinnedIds = await apiFetch('/api/local/conversations?metadata_only=1', { signal });
  } catch(e) {
    if (e.name !== 'AbortError') S.pinnedIds = [];
  }
}

async function loadAllConvs(signal) {
  if (!getTabAccount()) { S.allConvs = []; return; }
  try {
    const data = await apiFetch('/api/conversations?metadata_only=1', { signal });
    const arr = Array.isArray(data) ? data : [];
    S.allConvs = arr.map(c => {
      if (c.uuid) return c;
      return {
        uuid:       c.conv_uuid || c.id || '',
        name:       c.display_name || '',
        created_at: c.pinned_at || '',
        updated_at: c.pinned_at || '',
        ...c
      };
    });
    for (const c of S.allConvs) if (c.uuid) S.convs[c.uuid] = c;
  } catch(e) {
    if (e.name === 'AbortError') return; // clean cancel, don't wipe data
    S.allConvs = [];
  }
}

function getPinnedSet() { return new Set((S.pinnedIds || []).map(p => p.conv_uuid)); }
function getSavedIds() { return (S.pinnedIds || []).map(p => p.conv_uuid); }
async function saveId(id, name) {
  await apiFetch('/api/local/conversations', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ conv_uuid:id, display_name:name||'' })
  });
  if (!S.pinnedIds.find(p => p.conv_uuid === id)) S.pinnedIds.unshift({ conv_uuid:id, display_name:name||'' });
}
async function removeId(id) {
  await apiFetch(`/api/local/conversations/${id}`, { method:'DELETE' });
  S.pinnedIds = (S.pinnedIds || []).filter(p => p.conv_uuid !== id);
}
async function togglePin(e, id) {
  e.stopPropagation();
  const pinned = getPinnedSet();
  if (pinned.has(id)) {
    await removeId(id);
    toast('Unpinned', 'info');
  } else {
    const c = S.convs[id];
    await saveId(id, c?.name || '');
    toast('Pinned', 'ok');
  }
  renderSidebar();
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fmtTime(iso) { if (!iso) return ''; return new Date(iso).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }
function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso), today = new Date();
  if (d.toDateString() === today.toDateString()) return 'Today';
  const yest = new Date(); yest.setDate(yest.getDate()-1);
  if (d.toDateString() === yest.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], {month:'short', day:'numeric'});
}
function fmtBytes(n) {
  if (!n) return '';
  if (n < 1024) return n + 'B';
  if (n < 1024*1024) return (n/1024).toFixed(1) + 'KB';
  return (n/1024/1024).toFixed(1) + 'MB';
}
function uuid4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random()*16|0;
    return (c==='x' ? r : (r&0x3|0x8)).toString(16);
  });
}
function fileIcon(mime) {
  if (!mime) return '📄';
  if (mime.startsWith('image/')) return '🖼';
  if (mime.includes('pdf')) return '📑';
  if (mime.includes('zip') || mime.includes('tar') || mime.includes('gzip')) return '🗜';
  if (mime.startsWith('video/')) return '🎬';
  if (mime.startsWith('audio/')) return '🎵';
  if (mime.includes('json') || mime.includes('javascript') || mime.includes('python') || mime.includes('text/')) return '📝';
  if (mime.includes('spreadsheet') || mime.includes('excel') || mime.includes('csv')) return '📊';
  return '📎';
}

function setStatus(ok, orgId) {
  const dot  = document.getElementById('acctDot');
  const name = document.getElementById('acctName');
  const org  = document.getElementById('acctOrg');
  
  const tabAcct = getTabAccount();
  const prov    = getTabProvider();
  
  if (ok && tabAcct) {
    dot.classList.add('ok');
    name.textContent = tabAcct.name;
    org.textContent  = prov === 'chatwithai' 
      ? '⚡ no account needed' 
      : prov === 'claude' 
        ? `Org: ${orgId || 'unknown'}`
        : prov === 'oneminai'
          ? `1min.AI`
          : prov === 'flowith'
            ? `Flowith`
            : '';
  } else {
    dot.classList.remove('ok');
    name.textContent = 'Not configured';
    org.textContent  = '';
  }
}

function toggleProviderFields() {
  const provider = ddGetValue(document.getElementById('providerSel')) || 'claude';
  const claudeRows = [
    document.getElementById('skInp')?.closest('.form-row'),
    document.getElementById('orgInp')?.closest('.form-row'),
    document.getElementById('claudeAuthRow'),
  ];
  claudeRows.forEach(el => { if (el) el.style.display = provider === 'claude' ? '' : 'none'; });
  const hint = document.getElementById('chatwithaiHint');
  if (hint) hint.style.display = provider === 'chatwithai' ? '' : 'none';
  const oneminaiKeyRow   = document.getElementById('oneminaiKeyRow');
  const oneminaiOAuthRow = document.getElementById('oneminaiOAuthRow');
  if (oneminaiKeyRow)   oneminaiKeyRow.style.display   = provider === 'oneminai' ? '' : 'none';
  if (oneminaiOAuthRow) oneminaiOAuthRow.style.display = provider === 'oneminai' ? '' : 'none';

  const flowithKeyRow    = document.getElementById('flowithKeyRow');
  const flowithUserIdRow = document.getElementById('flowithUserIdRow');
  if (flowithKeyRow)    flowithKeyRow.style.display    = provider === 'flowith' ? '' : 'none';
  if (flowithUserIdRow) flowithUserIdRow.style.display = provider === 'flowith' ? '' : 'none';

  // Extended Thinking — only relevant for Claude accounts
  const extThinkSec = document.getElementById('extThinkingSection');
  const extThinkDiv = document.getElementById('extThinkingDivider');
  const extThinkDivB = document.getElementById('extThinkingDividerBottom');
  const showThink = provider === 'claude';
  if (extThinkSec)  extThinkSec.style.display  = showThink ? '' : 'none';
  if (extThinkDiv)  extThinkDiv.style.display  = showThink ? '' : 'none';
  if (extThinkDivB) extThinkDivB.style.display = showThink ? '' : 'none';
}

/* ═══════════════════════════════════════════
   SIDEBAR TOGGLE
═══════════════════════════════════════════ */
function _syncGlobalHamburger(sidebarOpen) {
  const btn = document.getElementById('sbOpenBtnGlobal');
  if (!btn) return;
  // Hide the global button while sidebar drawer is open
  btn.style.display = sidebarOpen ? 'none' : '';
}

function toggleSidebar() {
  if (_isMobile()) {
    if (_isMobileSidebarOpen()) {
      _closeMobileSidebar();
    } else {
      document.getElementById('sidebar').classList.add('m-open');
      _showMobileBackdrop(_closeMobileSidebar);
      document.body.style.overflow = 'hidden';
      _syncGlobalHamburger(true);
    }
    return;
  }
  // Desktop: collapse/expand inline
  S.sidebarOpen = !S.sidebarOpen;
  const sb  = document.getElementById('sidebar');
  const btn = document.getElementById('sbToggle');
  sb.classList.toggle('collapsed', !S.sidebarOpen);
  document.getElementById('app').classList.toggle('sb-collapsed', !S.sidebarOpen);
  btn.textContent = S.sidebarOpen ? '‹' : '›';
}

/* ═══════════════════════════════════════════
   COPY
═══════════════════════════════════════════ */
function copyCode(id, btn) {
  const el = document.getElementById(id);
  if (!el) {
    console.error('Code element not found:', id);
    return;
  }
  
  // Decode from base64
  let rawCode = '';
  if (el.dataset.raw) {
    try {
      rawCode = decodeURIComponent(escape(atob(el.dataset.raw)));
    } catch (e) {
      console.error('Failed to decode raw code:', e);
      rawCode = el.textContent;
    }
  } else {
    rawCode = el.textContent;
  }
  
  navigator.clipboard.writeText(rawCode).then(() => {
    btn.textContent = '✓ Copied';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = '⎘ Copy';
      btn.classList.remove('copied');
    }, 2000);
  }).catch(err => {
    console.error('Copy failed:', err);
    // Fallback for older browsers or permission issues
    const textArea = document.createElement('textarea');
    textArea.value = rawCode;
    textArea.style.cssText = 'position:absolute;left:-9999px;top:-9999px;';
    document.body.appendChild(textArea);
    textArea.select();
    try {
      document.execCommand('copy');
      btn.textContent = '✓ Copied';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = '⎘ Copy';
        btn.classList.remove('copied');
      }, 2000);
    } catch (err) {
      console.error('Fallback copy failed:', err);
      toast('Copy failed', 'err');
    }
    document.body.removeChild(textArea);
  });
}

function copyMsg(uuid, btn) {
  const el = document.querySelector(`.msg[data-uuid="${uuid}"] .msg-body`);
  if (!el) return;
  navigator.clipboard.writeText(el.innerText).then(() => {
    btn.textContent = '✓'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '⎘ Copy'; btn.classList.remove('copied'); }, 2000);
  });
}

function editMsg(uuid) {
  const conv = S.convs[S.convId];
  if (!conv) return;
  const msg = (conv.chat_messages || []).find(m => m.uuid === uuid);
  if (!msg || msg.sender !== 'human') return;

  // Extract plain text from message
  const text = msg.text || (msg.content || []).find(b => b.type === 'text')?.text || '';

  // For branching providers (Claude, Flowith):
  // Set parent to this message's OWN parent so the edit creates a fork
  // that replaces this message at the same level in the tree.
  // CWA is fully local so branching is always supported
  const _cwaProvider = (S.tabAccount?.provider || 'claude').toLowerCase();
  const _supBranch = _cwaProvider === 'chatwithai'
    ? true
    : (S.tabAccount?._supBranching !== false);
  if (_supBranch) {
    const parentUuid = msg.parent_message_uuid || '00000000-0000-4000-8000-000000000000';
    _setBranchPoint(parentUuid, '— editing from parent —');
    if (!BEX.open) toggleBranchExplorer();
  }

  // Re-attach any files from the original message
  S.attached = [];
  if (msg.files_v2?.length) {
    for (const f of msg.files_v2) {
      S.attached.push({
        file_uuid: f.file_uuid,
        _filename: f.file_name || f.filename || 'file',
        _mime:     f.file_kind || f.content_type || '',
        _size:     f.file_size || 0,
      });
    }
    renderAttBar();
  }

  // Fill the textarea
  const ta = document.getElementById('msgTa');
  ta.value = text;
  resizeTa(ta);
  updateCount(ta);
  ta.focus();
  ta.selectionStart = ta.selectionEnd = ta.value.length;

  ta.scrollIntoView({ behavior: 'smooth', block: 'end' });
  toast('Message loaded for editing — press ↵ to resend', 'info');
}

// Re-run: resend the SAME text from the same parent (regenerate with different
// random seed / same branch point). Works for Claude and Flowith.
function rerunFromMsg(uuid) {
  const conv = S.convs[S.convId];
  if (!conv) return;
  const msg = (conv.chat_messages || []).find(m => m.uuid === uuid);
  if (!msg || msg.sender !== 'human') return;

  const text       = msg.text || (msg.content || []).find(b => b.type === 'text')?.text || '';
  const parentUuid = msg.parent_message_uuid || '00000000-0000-4000-8000-000000000000';

  const _supBranch = S.tabAccount?._supBranching !== false;
  if (_supBranch) {
    _setBranchPoint(parentUuid, '— re-running from parent —');
    if (!BEX.open) toggleBranchExplorer();
  }

  // Re-attach files
  S.attached = [];
  if (msg.files_v2?.length) {
    for (const f of msg.files_v2) {
      S.attached.push({
        file_uuid: f.file_uuid,
        _filename: f.file_name || f.filename || 'file',
        _mime:     f.file_kind || f.content_type || '',
        _size:     f.file_size || 0,
      });
    }
    renderAttBar();
  }

  const ta = document.getElementById('msgTa');
  ta.value = text;
  resizeTa(ta);
  updateCount(ta);

  // Send immediately — no manual confirmation needed for re-run
  doSend();
}

/* ═══════════════════════════════════════════
   MULTI-ACCOUNT
═══════════════════════════════════════════ */
let _accountsCache = null;
let _accountsCacheTs = 0;

async function refreshAccountState(force = false) {
  const now = Date.now();
  if (!force && _accountsCache && now - _accountsCacheTs < 10_000) {
    // Use cached data
    S.accounts = _accountsCache.accounts || [];
    S.activeAccount = _accountsCache.active || null;
  } else {
    const data = await fetch('/api/accounts').then(r => r.json());
    _accountsCache = data;
    _accountsCacheTs = now;
    S.accounts = data.accounts || [];
    S.activeAccount = data.active || null;
  }
  
  S.configured = S.accounts.length > 0;
  S.accounts.sort((a, b) => { /* sort by provider, then name */ 
    const provA = (a.provider || 'claude').toLowerCase();
    const provB = (b.provider || 'claude').toLowerCase();
    if (provA < provB) return -1;
    if (provA > provB) return 1;
    const nameA = a.name.toLowerCase();
    const nameB = b.name.toLowerCase();
    if (nameA < nameB) return -1;
    if (nameA > nameB) return 1;
    return 0;
  });

  if (!S.tabAccount) {
    S.tabAccount = S.accounts.find(a => a.active) || S.accounts[0] || null;
  } else {
    const refreshed = S.accounts.find(a => a.name === S.tabAccount.name);
    S.tabAccount = refreshed || S.accounts.find(a => a.active) || S.accounts[0] || null;
  }

  const acct = S.tabAccount;
  setStatus(!!acct, acct?.organization_id);
  renderAccountMenu();
  renderAccountList();
  applyProviderUI(acct);
}

function applyProviderUI(acct) {
  if (!acct) return;

  const provider  = (acct.provider || 'claude').toLowerCase();
  const provInfo  = acct.provider_info || {};
  const models    = acct.models        || [];
  const defModel  = acct.default_model || 'claude-sonnet-4-6';

  // ── Capability flags (graceful defaults keep Claude fully enabled) ──────
  const supFiles      = provInfo.supports_files      !== false && provider !== 'chatwithai';
  const supCanvas     = provInfo.supports_canvas     !== false && provider === 'claude';
  const supArtifacts  = provInfo.supports_artifacts  !== false && provider === 'claude';
  const supThinking   = provInfo.supports_thinking   !== false && provider === 'claude';
  // ChatWithAI stores everything locally — branching is fully supported
  const supBranching  = provider === 'chatwithai'
    ? true
    : provInfo.supports_branching !== false && provider !== 'chatwithai';
  const supDownload   = provInfo.supports_download   !== false && provider === 'claude';
  const supReuseFiles = provInfo.supports_reuse_files !== false && provider !== 'chatwithai';

  // ── Toolbar controls ─────────────────────────────────────────────────────
    // Show/hide Claude-specific toolbar items
  const thinkBtn        = document.getElementById('thinkBtn');
  const branchToggleBtn = document.getElementById('branchToggleBtn');
  const fileInpBtn      = document.querySelector('.inp-btn label[for="fileInp"]')?.parentElement;
  const efpBtn          = document.getElementById('efpBtn');
  const msgTa           = document.getElementById('msgTa');
  const quotaWrap       = document.getElementById('quotaWrap');
  const canvasToggleBtn = document.getElementById('canvasToggleBtn');
  const chatSearchBtn   = document.getElementById('chatSearchBtn');

  if (thinkBtn)        thinkBtn.style.display        = supThinking  ? '' : 'none';
  if (branchToggleBtn) branchToggleBtn.style.display = supBranching ? '' : 'none';
  const webSearchBtn = document.getElementById('webSearchBtn');
  if (webSearchBtn) {
    const supWebSearch = provider === 'oneminai';
    webSearchBtn.style.display = supWebSearch ? '' : 'none';
  }
  if (canvasToggleBtn) canvasToggleBtn.style.display = supCanvas    ? '' : 'none';

  // Canvas panel: hide only if truly unsupported (keep for flowith image preview)
  const canvasPanel = document.getElementById('canvasPanel');
  if (canvasPanel) {
    // Allow canvas for flowith (image preview) even though artifacts unsupported
    const canvasAllowed = supCanvas || provider === 'flowith';
    if (!canvasAllowed) {
      canvasPanel.classList.add('collapsed');
      S.canvasOpen = false;
    }
    canvasPanel.style.display = canvasAllowed ? '' : 'none';
  }
  if (canvasToggleBtn) canvasToggleBtn.style.display = (supCanvas || provider === 'flowith') ? '' : 'none';

  // Flowith supports image uploads for inline image chat
  const showFileBtn = supFiles || provider === 'flowith';
  if (fileInpBtn) fileInpBtn.style.display = showFileBtn   ? '' : 'none';
  if (efpBtn)     efpBtn.style.display     = supReuseFiles ? '' : 'none';

  // ── Placeholder text ──────────────────────────────────────────────────────
  if (msgTa) {
    if      (provider === 'chatwithai') msgTa.placeholder = 'Message ChatWithAI…';
    else if (provider === 'oneminai')   msgTa.placeholder = 'Message 1min.AI…';
    else if (provider === 'flowith')    msgTa.placeholder = 'Message Flowith…';
    else                                msgTa.placeholder = 'Message Claude…';
  }

  // ── Quota bar ─────────────────────────────────────────────────────────────
  if (quotaWrap) {
    if (provider === 'claude' || provider === 'oneminai') {
      fetchQuota();
    } else {
      quotaWrap.style.display = 'none';
    }
  }

  // ── 1min.AI panel button visibility ──────────────────────────────────────
  _syncOneminaiPanelBtn();
  // ── ChatWithAI: fetch models eagerly on account switch ──────────────────
  if (provider === 'chatwithai') {
    if (!models.length || _chatwithaiModelCache.fetched_at === 0) {
      _fetchAndCacheChatwithaiModels().then(fetchedModels => {
        if (!fetchedModels.length) return;
        const sel2 = document.getElementById('modelSel');
        if (!sel2) return;
        if (getTabProvider() !== 'chatwithai') return;
        const cur = ddGetValue(sel2);
        const byVendor = {};
        fetchedModels.forEach(m => {
          const v = m.vendor_slug || m.vendor || '__none__';
          (byVendor[v] = byVendor[v] || []).push(m);
        });
        const vendors = Object.keys(byVendor);
        const useGroups = vendors.length > 1 || (vendors[0] !== '__none__' && fetchedModels[0]?.vendor);
        const groups = useGroups
          ? vendors.map(v => ({ label: byVendor[v][0].vendor || v, options: byVendor[v].map(m => ({ value: m.id, text: m.display_name || m.id })) }))
          : [{ options: fetchedModels.map(m => ({ value: m.id, text: m.display_name || m.id })) }];
        ddRebuild(sel2, groups);
        const defModel2 = acct.default_model || 'claude-sonnet-4-6';
        if (cur) ddSetValue(sel2, cur);
        else if (defModel2) ddSetValue(sel2, defModel2);
        acct.models = fetchedModels;
      }).catch(() => {});
    }
  }

    if (provider === 'flowith') {
    _flowithScheduleRefresh();
    _fetchAndCacheFlowithModels().then(fetchedModels => {
      if (fetchedModels.length) {
        const textModels = fetchedModels.filter(
          m => !m.category || m.category === 'text' || m.category === 'chat'
        );
        if (textModels.length) {
          const sel = document.getElementById('modelSel');
          if (sel) {
            const cur = ddGetValue(sel);
            _fillFlowithSel('modelSel', textModels);
            if (cur) ddSetValue(sel, cur);
          }
        }
      }
    }).catch(() => {});
    // Fetch credits eagerly too
    apiFetch('/api/flowith/credits').then(d => {
      const raw = d.credits_total ?? (d.credits?.total) ?? d.credits ?? null;
      if (raw != null) _cacheFlowith(getTabAccountName(), raw);
    }).catch(() => {});
  }

  if (provider === 'oneminai') {
    _omaiScheduleRefresh(); // <-- ADD THIS LINE
    // Fetch 1min.AI models eagerly on account switch
    fetchOneminaiModels(false).catch(() => {});
    // Fetch credits eagerly
    apiFetch('/api/usage').then(d => {
      if (d.provider === 'oneminai') {
        const cr = d.credits ?? null;
        if (cr != null) {
          const name = getTabAccountName();
          if (name) {
            quotaCache[name] = { provider: 'oneminai', credits: cr };
            _renderSidebarBar();
            renderAccountMenu();
            _renderOmaiPanelFromCache();
          }
        }
      }
    }).catch(() => {});
  }

  // Pre-populate omaiTool hint on provider switch
  updateOmaiToolHint();

  // ── Branch row: collapse and hide if not supported ────────────────────────
  if (!supBranching) {
    const branchRow = document.getElementById('branchRow');
    if (branchRow) branchRow.classList.add('hidden');
    S.branchVisible = false;
  }

  // Store on tab account for downstream consumers
  if (S.tabAccount) {
    S.tabAccount._supFiles      = supFiles;
    S.tabAccount._supCanvas     = supCanvas;
    S.tabAccount._supArtifacts  = supArtifacts;
    S.tabAccount._supThinking   = supThinking;
    S.tabAccount._supBranching  = supBranching;
    S.tabAccount._supDownload   = supDownload;
    S.tabAccount._supReuseFiles = supReuseFiles;
  }

  // Model selector — built from the account's own model list

  const sel = document.getElementById('modelSel');
  if (sel) {
    const fallbacks = !models.length
      ? (provider === 'chatwithai'
          ? [{id:'claude-sonnet-4-6',display_name:'Claude Sonnet'},{id:'gpt-4o',display_name:'GPT-4o'},{id:'gemini-2.0-flash-exp',display_name:'Gemini 2.0 Flash'}]
          : [{id:'claude-sonnet-4-6',display_name:'sonnet-4-6'},{id:'claude-haiku-4-5-20251001',display_name:'haiku-4-5'}])
      : null;

    const src = fallbacks || models;
    const byVendor = {};
    src.forEach(m => {
      const v = m.vendor_slug || m.vendor || '__none__';
      (byVendor[v] = byVendor[v] || []).push(m);
    });
    const vendors = Object.keys(byVendor);
    const useGroups = !fallbacks && (vendors.length > 1 || (vendors[0] !== '__none__' && src[0]?.vendor));

    const groups = useGroups
      ? vendors.map(v => ({ label: byVendor[v][0].vendor || v, options: byVendor[v].map(m => ({ value: m.id, text: m.display_name || m.id })) }))
      : [{ options: src.map(m => ({ value: m.id, text: m.display_name || m.id })) }];

    ddRebuild(sel, groups);
    if (defModel) ddSetValue(sel, defModel);
  }

  if (thinkBtn)        thinkBtn.style.display        = provInfo.supports_thinking  ? '' : 'none';
  if (branchToggleBtn) branchToggleBtn.style.display = provInfo.supports_branching ? '' : 'none';
  if (fileInpBtn)      fileInpBtn.style.display      = provInfo.supports_files     ? '' : 'none';
  if (efpBtn)          efpBtn.style.display          = provInfo.supports_files     ? '' : 'none';
  if (msgTa) {
    if (provider === 'chatwithai') msgTa.placeholder = 'Message ChatWithAI…';
    else if (provider === 'oneminai') msgTa.placeholder = 'Message 1min.AI…';
    else if (provider === 'flowith') msgTa.placeholder = 'Message Flowith…';
    else msgTa.placeholder = 'Message Claude…';
  }

  if (provider === 'flowith') {
    const sel2 = document.getElementById('modelSel');
    if (sel2) {
      const textModels = (acct.models || []).filter(
        m => !m.category || m.category === 'text' || m.category === 'chat'
      );
      if (textModels.length) {
        const cur = ddGetValue(sel2);
        _fillFlowithSel('modelSel', textModels);
        if (cur) ddSetValue(sel2, cur);
      }
    }
    if (branchToggleBtn) branchToggleBtn.style.display = '';
  }
  if (quotaWrap) {
    if (provider === 'claude' || provider === 'oneminai') {
      fetchQuota();
    } else {
      quotaWrap.style.display = 'none';
    }
  }

  syncToolbarSeparators();
}

async function loadModelsForTab(sel, defaultModel) {
  try {
    const mdata  = await apiFetch('/api/models');
    const models = mdata.models || [];

    if (!models.length) {
      ddRebuild(sel, [{ options: [{ value: getTabProviderInfo().default_model, text: 'Default' }] }]);
      return;
    }

    const byVendor = {};
    models.forEach(m => {
      const v = m.vendor_slug || m.vendor || m.provider || '__single__';
      (byVendor[v] = byVendor[v] || []).push(m);
    });
    const vendors = Object.keys(byVendor);
    const useGroups = !(vendors.length === 1 && vendors[0] === '__single__');

    const groups = useGroups
      ? vendors.map(v => ({ label: byVendor[v][0].vendor || v, options: byVendor[v].map(m => ({ value: m.id, text: m.display_name || m.id })) }))
      : [{ options: models.map(m => ({ value: m.id, text: m.display_name || m.id })) }];

    ddRebuild(sel, groups);
    const def = mdata.default_model || defaultModel;
    if (def) ddSetValue(sel, def);
  } catch(e) {
    console.error('Failed to load models:', e);
    ddRebuild(sel, [{ options: [{ value: getTabProviderInfo().default_model, text: 'Default' }] }]);
  }
}

async function refreshModels(silent = false) {
  const sel = document.getElementById('modelSel');
  if (!sel) return;
  const btn = document.getElementById('refreshModelsBtn');
  if (btn) btn.style.opacity = '0.4';
  try {
    const _rmProv = getTabProvider();
    if (_rmProv === 'chatwithai') {
      const models = await _fetchAndCacheChatwithaiModels(true);
      if (models.length) {
        const cur = ddGetValue(sel);
        const byVendor = {};
        models.forEach(m => { const v = m.vendor_slug || m.vendor || '__none__'; (byVendor[v] = byVendor[v] || []).push(m); });
        const vendors = Object.keys(byVendor);
        const useGroups = vendors.length > 1 || (vendors[0] !== '__none__' && models[0]?.vendor);
        const groups = useGroups
          ? vendors.map(v => ({ label: byVendor[v][0].vendor || v, options: byVendor[v].map(m => ({ value: m.id, text: m.display_name || m.id })) }))
          : [{ options: models.map(m => ({ value: m.id, text: m.display_name || m.id })) }];
        ddRebuild(sel, groups);
        if (cur) ddSetValue(sel, cur);
        const _rmAcct = getTabAccount();
        if (_rmAcct) _rmAcct.models = models;
      }
    } else {
      loadModelsForTab(sel, ddGetValue(sel));
    }
    // Invalidate accounts cache so next load gets fresh models
    _cache_invalidate_client();
    if (!silent) {
      toast('Models loaded', 'ok');
    }
  } catch (e) {
    console.error('Model refresh failed:', e);
    toast('Model refresh failed', 'err');
  } finally {
    if (btn) btn.style.opacity = '';
  }
}

// Client-side cache invalidation
function _cache_invalidate_client() {
  // Force next refreshAccountState to bypass cache
  _accountsCacheTs = 0;
  // Also force next ChatWithAI model fetch to refresh
  _chatwithaiModelCache.fetched_at = 0;
}

const quotaCache = {};

/* ── Fetch quota/credits for the current tab account ── */
async function fetchQuota() {
  const acct = getTabAccount();
  if (!acct) return;
  const provider = (acct.provider || 'claude').toLowerCase();
  if (provider === 'chatwithai') {
    document.getElementById('quotaWrap').style.display = 'none';
    return;
  }
  try {
    const d = await apiFetch('/api/usage');
    if (d.provider === 'oneminai') {
      _cacheOneminai(acct.name, d.credits);
      _renderSidebarBar();
    } else if (d.provider === 'flowith' && d.credits) {
      _cacheFlowith(acct.name, d.credits);
      _renderSidebarBar();
    } else if (d.provider === 'claude' && d.windows) {
      _cacheClaude(acct.name, d);
      _renderSidebarBar();
    }
  } catch {}
}

/* ── Poll EVERY account in the background ── */
async function _pollAllAccounts() {
  try {
    const all = await fetch('/api/usage/all').then(r => r.json());
    let changed = false;

    for (const [name, d] of Object.entries(all)) {
      if (d.provider === 'oneminai') {
        if (d.credits !== null && d.credits !== undefined) {
          _cacheOneminai(name, d.credits);
          changed = true;
        }
      } else if (d.provider === 'flowith') {
        const raw = d.credits?.total ?? d.credits?.credits_total ?? d.credits_total ?? null;
        if (raw !== null && raw !== undefined) {
          _cacheFlowith(name, raw);
          changed = true;
        }
      } else if (d.provider === 'claude' && d.quota?.windows) {
        _cacheClaude(name, d.quota);
        changed = true;
      }
    }

    if (changed) {
      _renderSidebarBar();   // update the active tab's sidebar bar
      renderAccountMenu();
      renderAccountList();
    }
  } catch { /* silent background poll */ }
}

/* ── Cache helpers ── */
function _cacheOneminai(name, credits) {
  quotaCache[name] = { provider: 'oneminai', credits };
}

function _cacheFlowith(name, credits) {
  let total = null;
  if (credits !== null && credits !== undefined) {
    if (typeof credits === 'object') {
      total = credits.total ?? credits.credits_total ?? null;
      if (total !== null) total = Number(total);
    } else {
      total = Number(credits);
    }
  }
  if (total !== null && !isNaN(total)) {
    quotaCache[name] = { provider: 'flowith', credits: total };
    // Update panel badge immediately if this is the active tab
    const tabName = getTabAccountName();
    if (name === tabName) {
      const el = document.getElementById('flowithCreditsDisplay');
      if (el) el.textContent = `⋆ ${total.toFixed(2)} credits`;
    }
  }
}

function _cacheClaude(name, payload) {
  // payload is the raw usage endpoint response OR a saved snapshot
  // Shape: { windows: { "5h": { utilization, status, resets_at }, ... }, type, ... }
  const windows = payload.windows || {};
  if (!Object.keys(windows).length) return;

  const STATUS_RANK = { exceeded_limit: 3, approaching_limit: 2, within_limit: 1 };

  const parsed = Object.entries(windows).map(([key, w]) => {
    if (!w) return null;
    const rawUtil = w.utilization ?? 0;
    const util    = Math.min(rawUtil, 1.0);   // clamp to 100% for bar display
    if (w.resets_at && w.resets_at * 1000 < Date.now()) return null; // window reset
    return {
        key,
        util,       // clamped for bar width
        rawUtil,    // raw for status
        status:   w.status || 'within_limit',
        rank:     STATUS_RANK[w.status] ?? 0,
        resetsAt: w.resets_at ?? null,
    };
}).filter(Boolean);

  if (!parsed.length) return;

  // Worst first (highest rank, then highest utilization)
  parsed.sort((a, b) => b.rank - a.rank || b.util - a.util);

  quotaCache[name] = {
    provider:  'claude',
    windows:   parsed,
    limitType: payload.type || null,
  };
}

/* ── Render the sidebar quota/credits bar for the ACTIVE tab account ── */
// REPLACE _renderSidebarBar — fix the resetsAt * 1000 bug in Claude section
function _renderSidebarBar() {
  const wrap   = document.getElementById('quotaWrap');
  const acct   = getTabAccount();
  const provider = (acct?.provider || 'claude').toLowerCase();

  if (provider === 'chatwithai') { wrap.style.display = 'none'; return; }

  const name   = getTabAccountName();
  const cached = name ? quotaCache[name] : null;
  if (!cached)  { wrap.style.display = 'none'; return; }

  // ── 1min.AI ──────────────────────────────────────────────────────────
  if (cached.provider === 'oneminai') {
    const cr = cached.credits;
    if (cr == null) { wrap.style.display = 'none'; return; }
    wrap.style.display = 'block';
    const label  = document.getElementById('quotaLabel');
    const pctEl  = document.getElementById('quotaPct');
    const fill   = document.getElementById('quotaBarFill');
    const detail = document.getElementById('quotaDetail');
    label.textContent  = 'Credits · 1min.AI';
    pctEl.textContent  = typeof cr === 'number' ? cr.toLocaleString() : String(cr);
    fill.style.width   = '100%';
    fill.className     = 'quota-bar-fill';
    detail.textContent = `${typeof cr === 'number' ? cr.toLocaleString() : cr} credits remaining`;
    const omaiCr = document.getElementById('omaiCreditsDisplay');
    if (omaiCr) omaiCr.textContent = `✦ ${typeof cr === 'number' ? cr.toLocaleString() : cr} credits`;
    return;
  }

  // ── Flowith ───────────────────────────────────────────────────────────
  if (cached.provider === 'flowith') {
    const cr    = cached.credits;
    if (cr == null) { wrap.style.display = 'none'; return; }
    const crNum = typeof cr === 'number' ? cr : parseFloat(cr);
    wrap.style.display = 'block';
    const label  = document.getElementById('quotaLabel');
    const pctEl  = document.getElementById('quotaPct');
    const fill   = document.getElementById('quotaBarFill');
    const detail = document.getElementById('quotaDetail');
    label.textContent  = 'Credits · Flowith';
    pctEl.textContent  = isNaN(crNum) ? String(cr) : crNum.toFixed(1);
    fill.style.width   = crNum > 0 ? '100%' : '0%';
    fill.className     = 'quota-bar-fill' + (crNum < 1 ? ' crit' : crNum < 5 ? ' warn' : '');
    detail.textContent = `${isNaN(crNum) ? String(cr) : crNum.toFixed(2)} credits remaining`;
    const fwCr = document.getElementById('flowithCreditsDisplay');
    if (fwCr) fwCr.textContent = `⋆ ${isNaN(crNum) ? String(cr) : crNum.toFixed(1)} credits`;
    renderAccountMenu();
    return;
  }

  // ── Claude — one bar per window ───────────────────────────────────────
  if (cached.provider !== 'claude') { wrap.style.display = 'none'; return; }

  const wins = cached.windows || [];
  if (!wins.length) { wrap.style.display = 'none'; return; }

  const WIN_LABELS = {
    '5h': '5-hour', '1h': '1-hour', '7d': '7-day',
    '1d': '1-day',  '30d': '30-day',
  };

  wrap.style.display = 'block';

  const barsHtml = wins.map((w, i) => {
    const pctNum   = Math.round((w.util ?? 0) * 100);  // already clamped to 100
    const overPct  = w.rawUtil != null ? Math.round(w.rawUtil * 100) : pctNum;
    // Show overage if applicable
    const pctDisplay = overPct > 100 ? `${overPct}%` : `${pctNum}%`;

    const winLabel = WIN_LABELS[w.key] || w.key;
    const fillCls  = 'quota-bar-fill' +
      (pctNum >= 90 || w.status === 'exceeded_limit'    ? ' crit' :
       pctNum >= 70 || w.status === 'approaching_limit' ? ' warn' : '');

    let statusTxt = '';
    if      (w.status === 'exceeded_limit')    statusTxt = ' exceeded';
    else if (w.status === 'approaching_limit') statusTxt = ' nearing';

    let resetTxt = '';
    if (w.resetsAt) {
      // resetsAt is Unix SECONDS — multiply by 1000 for ms comparison
      const diff = w.resetsAt * 1000 - Date.now();
      if (diff > 0) {
        const hrs  = Math.floor(diff / 3_600_000);
        const mins = Math.floor((diff % 3_600_000) / 60_000);
        resetTxt = ` · ↺ ${hrs > 0 ? hrs + 'h ' : ''}${mins}m`;
      }
    }

    const marginTop = i > 0
      ? 'margin-top:8px;padding-top:8px;border-top:1px solid var(--border-s);'
      : '';

    return `
      <div style="${marginTop}">
        <div class="quota-row">
          <span class="quota-label">${winLabel}${statusTxt}</span>
          <span class="quota-pct">${pctDisplay}${resetTxt}</span>
        </div>
        <div class="quota-bar-bg">
          <div class="${fillCls}" style="width:${pctNum}%"></div>
        </div>
      </div>`;
  }).join('');

  wrap.innerHTML = barsHtml;
}

/* ── Called from the SSE stream handler when Claude sends message_limit ── */
function updateQuotaFromStream(msgLimit) {
  if (!msgLimit) return;
  const name = getTabAccountName();
  if (!name) return;
  _cacheClaude(name, msgLimit);
  _renderSidebarBar();
  renderAccountMenu();
}

/* ── Mini bar shown inside the account switcher / settings list ── */
// REPLACE buildMiniQuotaHtml — Claude section only
function buildMiniQuotaHtml(acctName) {
  const acct     = S.accounts.find(a => a.name === acctName);
  const provider = (acct?.provider || 'claude').toLowerCase();
  const cached   = quotaCache[acctName];
  if (!cached) return '';

  if (provider === 'oneminai') {
    const cr = cached.credits;
    if (cr == null) return '';
    return `<div class="mini-quota">
      <span class="mini-quota-pct" style="min-width:auto;font-size:9px;color:var(--oneminai)">
        ✦ ${typeof cr === 'number' ? cr.toLocaleString() : cr} credits
      </span>
    </div>`;
  }

  if (provider === 'flowith') {
    const cr = cached.credits;
    if (cr == null) return '';
    return `<div class="mini-quota">
      <span class="mini-quota-pct" style="min-width:auto;font-size:9px;color:var(--flowith)">
        ⋆ ${typeof cr === 'number' ? cr.toFixed(2) : cr} credits
      </span>
    </div>`;
  }

  if (provider !== 'claude') return '';

  // New shape: cached.windows = [{ key, util, status, rank, resetsAt }, ...]
  const wins = cached.windows;
  if (!wins?.length) return '';

  // Show worst window (first, already sorted worst-first)
  const w      = wins[0];
  const pctNum = Math.round((w.util ?? 0) * 100);
  const fillClass = pctNum >= 90 || w.status === 'exceeded_limit' ? ' crit'
                  : pctNum >= 70 || w.status === 'approaching_limit' ? ' warn' : '';

  let resetStr = '';
  if (w.resetsAt) {
    // resetsAt is Unix seconds
    const diff = w.resetsAt * 1000 - Date.now();
    if (diff > 0) {
      const hrs  = Math.floor(diff / 3_600_000);
      const mins = Math.floor((diff % 3_600_000) / 60_000);
      resetStr   = hrs > 0 ? `${hrs}h` : `${mins}m`;
    }
  }

  const WIN_LABELS = { '5h':'5h', '1h':'1h', '7d':'7d', '1d':'1d', '30d':'30d' };
  const winLbl = WIN_LABELS[w.key] || w.key;

  return `<div class="mini-quota">
    <div class="mini-quota-bar-bg">
      <div class="mini-quota-bar-fill${fillClass}" style="width:${pctNum}%"></div>
    </div>
    <span class="mini-quota-pct">${pctNum}% ${winLbl}</span>
    ${resetStr ? `<span class="mini-quota-reset">↺ ${resetStr}</span>` : ''}
  </div>`;
}


function closeAcctMenu() {
  document.getElementById('acctMenu')?.classList.add('hidden');
  document.getElementById('acctChev')?.classList.remove('open');
}
function _closeAcctOnOutside(e) {
  if (!document.getElementById('acctSwitcher')?.contains(e.target)) closeAcctMenu();
}

function toggleAcctMenu() {
  const menu   = document.getElementById('acctMenu');
  const chev   = document.getElementById('acctChev');
  const hidden = menu.classList.contains('hidden');
  if (hidden) {
    menu.classList.remove('hidden'); chev.classList.add('open');
    const inp = document.getElementById('acctMenuSearchInp');
    if (inp) { inp.value = ''; renderAccountMenu(); setTimeout(() => inp.focus(), 50); }
    document.addEventListener('click', _closeAcctOnOutside, { once:true, capture:true });
  } else closeAcctMenu();
}

function renderAccountMenu(filter = '') {
  const list = document.getElementById('acctMenuList');
  list.innerHTML = '';
  const q       = filter.toLowerCase().trim();
  const tabName = getTabAccountName();

  const visible = q
    ? S.accounts.filter(a =>
        a.name.toLowerCase().includes(q) ||
        (a.provider||'claude').toLowerCase().includes(q))
    : S.accounts;

  if (!S.accounts.length) {
    list.innerHTML = '<div style="padding:10px 12px;font-size:12px;color:var(--text-3)">No accounts yet</div>';
    return;
  }
  if (!visible.length) {
    list.innerHTML = '<div style="padding:10px 12px;font-size:12px;color:var(--text-3)">No matches</div>';
    return;
  }

  for (const acct of visible) {
    const prov    = (acct.provider || 'claude').toLowerCase();
    const isCWA   = prov === 'chatwithai';
    const isTabActive = acct.name === tabName;

    const is1min   = prov === 'oneminai';
    const isFlowith = prov === 'flowith';
    const badge = isCWA
      ? `<span class="ami-badge" style="color:#38bdf8;background:rgba(56,189,248,0.10);border-color:rgba(56,189,248,0.18)">⚡ ChatWithAI</span>`
      : is1min
        ? `<span class="ami-badge" style="color:var(--oneminai);background:var(--oneminai-dim);border-color:var(--oneminai-mid)">✦ 1min.AI</span>`
        : isFlowith
          ? `<span class="ami-badge" style="color:var(--flowith);background:var(--flowith-dim);border-color:var(--flowith-mid)">⠿ Flowith</span>`
          : `<span class="ami-badge" style="color:var(--accent);background:var(--accent-dim);border-color:var(--accent-mid)">🔑 Claude</span>`;

    const subtitle = isCWA
      ? 'No account needed'
      : is1min
        ? (acct.api_key ? 'api key set' : 'no key set')
        : isFlowith
          ? (acct.api_key ? 'token set' : 'no token set')
          : (acct.organization_id ? acct.organization_id.slice(0,8)+'…' : 'session key');

    // Mini quota bar (Claude only)
    const miniBar = buildMiniQuotaHtml(acct.name);

    const el = document.createElement('div');
    el.className = `acct-menu-item ${isTabActive ? 'active' : ''}`;
    el.innerHTML = `
      <div class="ami-info">
        <div class="ami-name">
          <span class="ami-name-text">${esc(acct.name)}</span>
          ${badge}
        </div>
        <div class="ami-org">${esc(subtitle)}</div>
        ${miniBar}
      </div>
      <div class="ami-dot ${isTabActive ? '' : 'inactive'}"></div>
      <button class="ami-del" onclick="deleteAccount(event,'${esc(acct.name)}')">✕</button>`;

    el.addEventListener('click', e => {
      if (e.target.classList.contains('ami-del')) return;
      switchTabAccount(acct.name);
    });
    list.appendChild(el);
  }
}

function filterAcctMenu(val) {
  renderAccountMenu(val);
}

function renderAccountList(filter = '') {
  document.getElementById('settingsOverlay')?.classList.remove('hidden');
  const list = document.getElementById('acctList');
  if (!list) return;
  list.innerHTML = '';
  const q = filter.toLowerCase().trim();
  const visible = q
    ? S.accounts.filter(a =>
        a.name.toLowerCase().includes(q) ||
        (a.provider||'claude').toLowerCase().includes(q))
    : S.accounts;

  if (!S.accounts.length) {
    list.innerHTML = '<div style="font-size:12px;color:var(--text-3);padding:4px 0 8px">No accounts added yet.</div>';
    return;
  }
  if (!visible.length) {
    list.innerHTML = '<div style="font-size:12px;color:var(--text-3);padding:4px 0 8px">No accounts match your search.</div>';
    return;
  }

  for (const acct of visible) {
    const prov  = (acct.provider || 'claude').toLowerCase();
    const isCWA      = prov === 'chatwithai';
    const is1minList = prov === 'oneminai';
    const isFlowithList = prov === 'flowith';
    const provBadge = isCWA
      ? `<span style="font-size:var(--fs-xs);padding:1px 6px;background:rgba(56,189,248,0.10);color:#38bdf8;border-radius:4px;font-weight:600;flex-shrink:0">⚡ Free</span>`
      : is1minList
        ? `<span style="font-size:var(--fs-xs);padding:1px 5px;background:var(--oneminai-dim);color:var(--oneminai);border-radius:4px;font-weight:600;flex-shrink:0">✦ 1min.AI</span>`
        : isFlowithList
          ? `<span style="font-size:var(--fs-xs);padding:1px 5px;background:var(--flowith-dim);color:var(--flowith);border-radius:4px;font-weight:600;flex-shrink:0">⠿ Flowith</span>`
          : `<span style="font-size:var(--fs-xs);padding:1px 5px;background:var(--accent-dim);color:var(--accent);border-radius:4px;font-weight:600;flex-shrink:0">🔑 Claude</span>`;
    const subtitle = isCWA
      ? 'No account needed'
      : is1minList
        ? (acct.api_key ? 'api key set' : 'no key set')
        : isFlowithList
          ? (acct.api_key ? 'token set' : 'no token set')
          : (acct.organization_id ? acct.organization_id.slice(0,8)+'…' : 'session key');

    // Mini quota bar (Claude only)
    const miniBar = buildMiniQuotaHtml(acct.name);
    const isActive = getTabAccountName() === acct.name;
    const el = document.createElement('div');
    el.className = `acct-list-item ${isActive ? 'active' : ''}`;
    el.innerHTML = `
      <div class="ali-info">
        <div class="ali-name">
          <span class="ali-name-text">${esc(acct.name)}</span>
          ${provBadge}
        </div>
        <div class="ali-org">${esc(subtitle)}</div>
        ${miniBar}
      </div>
      ${isActive ? '<span class="ali-badge">ACTIVE</span>' : ''}
      ${!isActive
        ? `<button class="ali-btn" onclick="switchTabAccount('${esc(acct.name)}'); document.getElementById('settingsOverlay')?.classList.add('hidden');">Switch</button>`

        : ''}
      <button class="ali-btn edit" onclick="editAccount('${esc(acct.name)}')">Edit</button>
      <button class="ali-btn del"  onclick="deleteAccount(null,'${esc(acct.name)}')">✕</button>`;
    list.appendChild(el);
  }
}

function filterAccounts(val) {
  renderAccountList(val);
}

/* Switch the account for THIS TAB only — no server state change */
async function switchTabAccount(name) {
  // Cancel anything in flight from previous account
  _cancelPending();
  _activeNavCtl = new AbortController();
  const signal = _activeNavCtl.signal;

  closeAcctMenu();
  const acct = S.accounts.find(a => a.name === name);
  if (!acct) { toast(`Account "${name}" not found`, 'err'); return; }

  S.tabAccount = acct;
  S.convId = null; S.convs = {}; S.allConvs = []; S.pinnedIds = [];

  document.getElementById('chat').classList.add('hidden');
  document.getElementById('splash').classList.remove('hidden');
  history.replaceState(null, '', '/');
  document.title = 'ChatAI Console';

  setStatus(true, acct.organization_id);
  renderAccountMenu();
  applyProviderUI(acct);

  const prov = (acct.provider || 'claude').toLowerCase();
  if (['claude', 'oneminai'].includes(prov)) fetchQuota();
  if (prov === 'flowith') {
    apiFetch('/api/flowith/credits', { signal }).then(d => {
      const raw = d.credits?.total ?? d.credits_total ?? null;
      if (raw != null) { _cacheFlowith(acct.name, raw); _renderSidebarBar(); renderAccountMenu(); }
    }).catch(() => {});
  }

  try {
    // Sequential, not parallel — avoids hammering the server
    await loadPinnedIds(signal);
    if (signal.aborted) return;
    await loadAllConvs(signal);
    if (signal.aborted) return;
  } catch(e) {
    if (e.name === 'AbortError') return;
  }

  renderSidebar();
  toast(`Switched to ${name}`, 'ok');

  // Models fetch in background — don't block the UI
  if (prov === 'chatwithai') {
    _fetchAndCacheChatwithaiModels().catch(() => {});
  } else if (prov === 'flowith') {
    _fetchAndCacheFlowithModels().catch(() => {});
  } else if (prov === 'oneminai') {
    fetchOneminaiModels(false).catch(() => {});
  }
}

/* Make an account the server-wide active (affects other tabs that haven't
   explicitly chosen an account yet) — available from settings panel */
async function setServerActiveAccount(name) {
  await fetch(`/api/accounts/${encodeURIComponent(name)}/activate`, { method:'POST' });
  await refreshAccountState();
  toast(`Default account → ${name}`, 'ok');
}

async function saveAccount() {
  const name = document.getElementById('acctNameInp').value.trim();
  const act  = document.getElementById('acctActivateChk').checked;
  const provider = ddGetValue(document.getElementById('providerSel')) || 'claude';
  if (!name) { toast('Account name is required', 'err'); return; }

  const oneminaiKey = (document.getElementById('oneminaiKeyInp')?.value || '').trim();
  const flowithKey  = (document.getElementById('flowithKeyInp')?.value  || '').trim();
  const flowithUid  = (document.getElementById('flowithUserIdInp')?.value || '').trim();

  // Build the request body
  const body = {
    name,
    provider,
    activate: act,
    session_key:     (document.getElementById('skInp')?.value  || '').trim(),
    organization_id: (document.getElementById('orgInp')?.value || '').trim(),
    claude_code:     (document.getElementById('claudeCodeInp')?.value || '').trim(),
    api_key:         provider === 'flowith' ? flowithKey : oneminaiKey,
    user_id:         flowithUid,
    refresh_token:   provider === 'flowith'
      ? (document.getElementById('flowithRefreshTokenInp')?.value || '').trim()
      : '',
  };

  const r = await fetch('/api/accounts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(r => r.json());
  
  if (!r || r.error) { toast('Error: ' + (r?.error || 'Unknown error'), 'err'); return; }
  _resetAcctForm();
  await refreshAccountState();  // Refreshes S.accounts
  
  // Auto-switch this tab to the new account if activate was checked
  if (act) {
    await switchTabAccount(name);
  }
  toast('Account saved', 'ok');
}

/* ── Claude Google OAuth (auth code flow) ───────────────────────────────── */

function _claudeSetAuthStatus(msg, type) {
  const el = document.getElementById('claudeAuthStatus');
  if (!el) return;
  el.textContent = msg;
  el.className = 'miniapps-auth-status' + (type ? ' ' + type : '');
  el.style.display = msg ? '' : 'none';
}

function _claudeResetAuthStatus() {
  const el = document.getElementById('claudeAuthStatus');
  if (el) { el.style.display = 'none'; el.className = 'miniapps-auth-status'; el.textContent = ''; }
  const btn = document.getElementById('claudeGoogleBtn');
  if (btn) btn.disabled = false;
}

async function claudeGoogleSignIn() {
  const btn = document.getElementById('claudeGoogleBtn');
  if (btn) btn.disabled = true;
  _claudeSetAuthStatus('Starting sign-in session…', '');

  // Open immediately in the user gesture context to avoid popup blocking.
  const tab = window.open('about:blank', 'claude_gis', 'width=600,height=700,left=200,top=80');

  let r;
  try { r = await apiFetch('/api/oauth/claude/begin'); } catch(e) { r = null; }
  if (!r?.state) {
    if (tab && !tab.closed) tab.close();
    _claudeSetAuthStatus('Failed to start session — check server logs', 'err');
    if (btn) btn.disabled = false;
    return;
  }

  // Navigate popup to claude.ai so the extension content script can trigger GIS there.
  if (tab && !tab.closed) tab.location.href = 'https://claude.ai/';
  _claudeSetAuthStatus(
    tab
      ? 'Google sign-in prompt opening on claude.ai — complete it there…'
      : 'Visit claude.ai and complete the Google sign-in prompt…',
    ''
  );

  const iv = setInterval(async () => {
    let s;
    try { s = await apiFetch(`/api/oauth/claude/status?state=${encodeURIComponent(r.state)}`); } catch { return; }
    if (!s?.done) return;
    clearInterval(iv);
    if (tab && !tab.closed) tab.close();
    if (s.code) {
      document.getElementById('claudeCodeInp').value = s.code;
      _claudeSetAuthStatus('✓ Auth code received — ready', 'ok');
    } else {
      _claudeSetAuthStatus('Sign-in failed: ' + (s.error || 'unknown error'), 'err');
    }
    if (btn) btn.disabled = false;
  }, 1000);

  // Safety timeout after 2 minutes
  setTimeout(() => {
    clearInterval(iv);
    if (tab && !tab.closed) tab.close();
    if (btn) btn.disabled = false;
    _claudeSetAuthStatus('Timed out — try again', 'err');
  }, 120_000);
}


/* ── 1min.AI Google OAuth ───────────────────────────────────────────────── */

function _oneminaiSetAuthStatus(msg, type) {
  const el = document.getElementById('oneminaiAuthStatus');
  if (!el) return;
  el.textContent = msg;
  el.className = 'miniapps-auth-status' + (type ? ' ' + type : '');
  el.style.display = msg ? '' : 'none';
}

function _oneminaiResetAuthStatus() {
  const el = document.getElementById('oneminaiAuthStatus');
  if (el) { el.style.display = 'none'; el.className = 'miniapps-auth-status'; el.textContent = ''; }
  const btn = document.getElementById('oneminaiGoogleBtn');
  if (btn) btn.disabled = false;
}

async function oneminaiGoogleSignIn() {
  const btn = document.getElementById('oneminaiGoogleBtn');
  if (btn) btn.disabled = true;
  _oneminaiSetAuthStatus('Starting 1min.AI sign-in session…', '');

  // Open popup immediately (must be in user-gesture context)
  const tab = window.open('about:blank', 'oneminai_gis', 'width=600,height=700,left=200,top=80');

  let r;
  try { r = await apiFetch('/api/oauth/oneminai/begin'); } catch(e) { r = null; }
  if (!r?.state) {
    if (tab && !tab.closed) tab.close();
    _oneminaiSetAuthStatus('Failed to start session — check server logs', 'err');
    if (btn) btn.disabled = false;
    return;
  }

  // Navigate to 1min.AI so the extension can intercept the Google OAuth popup
  if (tab && !tab.closed) tab.location.href = 'https://app.1min.ai/';
  _oneminaiSetAuthStatus(
    tab
      ? 'Google sign-in prompt opening on app.1min.ai — complete it there…'
      : 'Visit app.1min.ai and complete Google sign-in…',
    ''
  );

  const iv = setInterval(async () => {
    let s;
    try { s = await apiFetch(`/api/oauth/oneminai/status?state=${encodeURIComponent(r.state)}`); } catch { return; }
    if (!s?.done) return;
    clearInterval(iv);
    if (tab && !tab.closed) tab.close();
    if (s.api_key) {
      document.getElementById('oneminaiKeyInp').value = s.api_key;
      _oneminaiSetAuthStatus(`✓ Authenticated as ${s.email || 'user'} — ready`, 'ok');
    } else {
      _oneminaiSetAuthStatus('Sign-in failed: ' + (s.error || 'unknown error'), 'err');
    }
    if (btn) btn.disabled = false;
  }, 1000);

  // 2-minute timeout
  setTimeout(() => {
    clearInterval(iv);
    if (tab && !tab.closed) tab.close();
    if (btn) btn.disabled = false;
    _oneminaiSetAuthStatus('Timed out — try again', 'err');
  }, 120_000);
}

function _resetAcctForm() {
  document.getElementById('acctNameInp').value      = '';
  document.getElementById('skInp').value            = '';
  document.getElementById('orgInp').value           = '';
  document.getElementById('claudeCodeInp').value    = '';
  ddSetValue(document.getElementById('providerSel'), 'claude');
  document.getElementById('oneminaiKeyInp').value    = '';
  const fki = document.getElementById('flowithKeyInp');
  if (fki) fki.value = '';
  const fui = document.getElementById('flowithUserIdInp');
  if (fui) fui.value = '';
  _flowithResetAuthStatus();
  _oneminaiResetAuthStatus();
  document.getElementById('acctFormTitle').textContent  = 'Add Account';
  document.getElementById('acctSaveBtn').textContent    = 'Add Account';
  document.getElementById('acctCancelEditBtn').style.display = 'none';
  _claudeResetAuthStatus();
  toggleProviderFields();
}

function editAccount(name) {
  const acct = S.accounts.find(a => a.name === name);
  if (!acct) return;
  document.getElementById('acctNameInp').value = acct.name;
  ddSetValue(document.getElementById('providerSel'), acct.provider || 'claude');
  document.getElementById('orgInp').value       = acct.organization_id || '';
  document.getElementById('skInp').value        = acct.session_key     || '';
  document.getElementById('oneminaiKeyInp').value = acct.provider === 'oneminai' ? (acct.api_key || '') : '';
  const fki2 = document.getElementById('flowithKeyInp');
  if (fki2) fki2.value = acct.provider === 'flowith' ? (acct.api_key || '') : '';
  const fui2 = document.getElementById('flowithUserIdInp');
  if (fui2) fui2.value = acct.provider === 'flowith' ? (acct.user_id || '') : '';
  // Reset Flowith auth status badge when editing a different account
  _flowithResetAuthStatus();
  document.getElementById('acctFormTitle').textContent       = 'Edit Account';
  document.getElementById('acctSaveBtn').textContent         = 'Save Changes';
  document.getElementById('acctCancelEditBtn').style.display = '';
  document.getElementById('acctNameInp').focus();
  toggleProviderFields();
}

function cancelAcctEdit() {
  _resetAcctForm();
}

async function deleteAccount(e, name) {
  if (e) e.stopPropagation();
  await fetch(`/api/accounts/${encodeURIComponent(name)}`, { method:'DELETE' });
  await refreshAccountState();
  
  // If this was our tab's account, switch to whatever is left
  if (S.tabAccount?.name === name) {
    S.tabAccount = S.accounts.find(a => a.active) || S.accounts[0] || null;
    S.convId = null; S.convs = {}; S.allConvs = []; S.pinnedIds = [];
    document.getElementById('chat').classList.add('hidden');
    document.getElementById('splash').classList.remove('hidden');
    history.replaceState(null, '', '/');
    document.title = 'ChatAI Console';
    if (S.tabAccount) {
      applyProviderUI(getTabProvider(), getTabProviderInfo());
    }
    renderSidebar();
  }
  toast(`Removed "${name}"`, 'info');
}

function openSettings() {
  const inp = document.getElementById('acctSearchInp');
  if (inp) inp.value = '';
  // Reset the form to "Add Account / Claude" state so Extended Thinking
  // visibility is correct before the user selects or edits any account.
  _resetAcctForm();
  renderAccountList();
  // toggleProviderFields() is already called inside _resetAcctForm()
  openOverlay('settingsOverlay');
}

/* ═══════════════════════════════════════════
   CONVERSATIONS
═══════════════════════════════════════════ */
async function fetchConvMeta(id, signal) {
  const data = await apiFetch(`/api/conversations/${id}`, { signal });
  if (!data.error) {
    S.convs[id] = data;
    if (data.name) {
      // Sync name into allConvs so sidebar reflects it
      const ac = (S.allConvs || []).find(c => c.uuid === id);
      if (ac) ac.name = data.name;
      apiFetch(`/api/local/conversations/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: data.name }),
        signal,
      }).catch(() => {});
    }
  }
}

async function newConv() {
  if (!S.configured) { toast('Configure an account first', 'err'); openSettings(); return; }
  const d = await apiFetch('/api/conversations', { method:'POST' });
  if (!d.success) { toast('Failed: ' + (d.error || ''), 'err'); return; }
  await saveId(d.id, '');
  S.convs[d.id] = d;
  S.allConvs.unshift({ uuid:d.id, name:'', created_at:new Date().toISOString(), updated_at:new Date().toISOString() });
  renderSidebar();
  if (_isMobile()) _closeMobileSidebar();
  selectConv(d.id, getAcctIdFromUrl() || getTabAccountName(), true);
}

async function selectConv(id, acct, skipPush) {
  // Cancel any previous in-flight conversation load
  _cancelPending();
  _activeNavCtl = new AbortController();
  const signal = _activeNavCtl.signal;

  S.convId = id;
  document.getElementById('chat').classList.remove('hidden');
  document.getElementById('chat').style.display = 'flex';
  document.getElementById('splash').classList.add('hidden');
  document.getElementById('app').classList.add('in-chat');
  const _urlAcct = acct || getTabAccountName() || 'default';
  const _urlPath = `/a/${encodeURIComponent(_urlAcct)}/c/${id}`;
  if (skipPush) history.replaceState({ convId: id }, '', _urlPath);
  else          history.pushState(   { convId: id }, '', _urlPath);
  renderSidebar();

  if (acct && acct !== getTabAccountName()) {
    await switchTabAccount(acct);
  }

  const cached = S.convs[id];
  if (!cached || !cached.chat_messages) {
    try {
      await fetchConvMeta(id, signal);
    } catch(e) {
      if (e.name === 'AbortError') return; // user navigated away, stop
    }
  }

  if (signal.aborted) return; // check again after any await

   // Reset BEX for the new conversation
  BEX.viewLeafUuid   = null;
  BEX.sendParentUuid = null;

  renderMsgs();
  syncToolbar();
  buildBranchSel();

  // Advance BEX to the loaded leaf
  const _scConv = S.convs[id];
  if (_scConv?.chat_messages?.length) {
    const { byUuid, leafUuids } = bexBuildTree(_scConv);
    const leaf = _scConv.current_leaf_message_uuid && byUuid[_scConv.current_leaf_message_uuid]
      ? _scConv.current_leaf_message_uuid
      : bexFindDeepestLeaf(leafUuids, byUuid);
    BEX.viewLeafUuid   = leaf;
    BEX.sendParentUuid = leaf;
    const _scSel = document.getElementById('branchSel');
    if (_scSel) _scSel.value = leaf || ROOT_UUID;
    _bexUpdatePill();
    if (BEX.open) bexRebuild();
  }

  const c = S.convs[id];
  const name = c?.name || 'Conversation';
  document.title = name + ' — ChatAI Console';
  if (_isMobile()) _closeMobileSidebar();
}

async function delConv(e, id) {
  e.stopPropagation();
  await removeId(id);
  delete S.convs[id];
  S.allConvs = (S.allConvs || []).filter(c => c.uuid !== id);
  if (S.convId === id) {
    navToHome();
    toast('Removed', 'info');
    return;
  }
  renderSidebar();
  toast('Removed', 'info');
}

function renderSidebar() {
  const list = document.getElementById('sbList');
  list.innerHTML = '';
  const pinSet = getPinnedSet();
  const pinnedIds = getSavedIds();

  /* ── Pinned section ── */
  if (pinnedIds.length) {
    const pinnedHdr = document.createElement('div');
    pinnedHdr.className = 'sb-section pinned-section';
    pinnedHdr.innerHTML = '<span class="pin-ico">📌</span> Pinned';
    list.appendChild(pinnedHdr);
    for (const id of pinnedIds) {
      const c      = S.convs[id];
      const name   = c ? (c.name || 'Untitled') : (S.pinnedIds.find(p=>p.conv_uuid===id)?.display_name || id.slice(0,8) + '…');
      const date   = c ? fmtDate(c.updated_at || c.created_at) : '';
      const active = id === S.convId;
      const el = document.createElement('div');
      el.className = `conv-item ${active ? 'active' : ''}`;
      el.innerHTML = `
        <span class="conv-ico">💬</span>
        <div class="conv-meta">
          <div class="conv-name">${esc(name)}</div>
          <div class="conv-date">${esc(date)}</div>
        </div>
        <div class="conv-btns">
          <button class="conv-btn pin-btn pinned" onclick="togglePin(event,'${id}')" title="Unpin">📌</button>
          <button class="conv-btn" onclick="renameConv(event,'${id}')" title="Rename" style="font-size:11px">✎</button>
          <button class="conv-btn del-btn" onclick="deleteConvFull(event,'${id}')" title="Delete conversation">✕</button>
        </div>`;
      el.onclick = e => {
        if (e.target.closest('.conv-btns')) return;
        selectConv(id, getAcctIdFromUrl() || getTabAccountName(), true);
      };
      list.appendChild(el);
    }
  }

  /* ── Recent section (all remote convos not pinned) ── */
  const recent = (S.allConvs || [])
    .filter(c => c.uuid && !pinSet.has(c.uuid))
    .sort((a,b) => (b.updated_at||b.created_at||'').localeCompare(a.updated_at||a.created_at||''));

  if (recent.length || !pinnedIds.length) {
    const recentHdr = document.createElement('div');
    recentHdr.className = 'sb-section';
    recentHdr.textContent = 'Recent';
    list.appendChild(recentHdr);
  }
  if (!pinnedIds.length && !recent.length) {
    list.innerHTML += `<div style="padding:16px 10px;text-align:center;font-size:12px;color:var(--text-3)">No conversations yet.<br>Click + New to start.</div>`;
    return;
  }
  for (const c of recent) {
    const id     = c.uuid;
    const name   = c.name || 'Untitled';
    const date   = fmtDate(c.updated_at || c.created_at);
    const active = id === S.convId;
    const el = document.createElement('div');
    el.className = `conv-item ${active ? 'active' : ''}`;
    el.innerHTML = `
      <span class="conv-ico">💬</span>
      <div class="conv-meta">
        <div class="conv-name">${esc(name)}</div>
        <div class="conv-date">${esc(date)}</div>
      </div>
      <div class="conv-btns">
        <button class="conv-btn pin-btn" onclick="togglePin(event,'${id}')" title="Pin">📌</button>
        <button class="conv-btn" onclick="renameConv(event,'${id}')" title="Rename" style="font-size:11px">✎</button>
      </div>`;
    el.onclick = e => {
      if (e.target.closest('.conv-btns')) return;
      selectConv(id, getAcctIdFromUrl() || getTabAccountName(), true);
    };
    list.appendChild(el);
  }
}

// ══════════════════════════════════════════════════════════════════════════
// CONVERSATION RENAME
// ══════════════════════════════════════════════════════════════════════════

async function renameConv(e, id) {
  e.stopPropagation();
  const c    = S.convs[id];
  const old  = c?.name || S.pinnedIds.find(p => p.conv_uuid === id)?.display_name || '';
  const name = prompt('Rename conversation:', old);
  if (!name || name === old) return;

  try {
    const r = await apiFetch(`/api/conversations/${id}/rename`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: name }),
    });
    if (r.success || r.conversation) {
      // Update local cache
      if (S.convs[id]) S.convs[id].name = name;
      const pinned = S.pinnedIds.find(p => p.conv_uuid === id);
      if (pinned) pinned.display_name = name;
      // Also update allConvs list
      const ac = (S.allConvs || []).find(c => c.uuid === id);
      if (ac) ac.name = name;
      renderSidebar();
      if (S.convId === id) syncToolbar();
      toast('Renamed', 'ok');
    } else {
      toast('Rename failed: ' + (r.error || 'unknown'), 'err');
    }
  } catch (err) {
    toast('Rename error: ' + err.message, 'err');
  }
}

// ══════════════════════════════════════════════════════════════════════════
// 1MIN.AI TOOLS PANEL
// ══════════════════════════════════════════════════════════════════════════

/* toggleOneminaiPanel: see definitive version below */

function omaiSwitchTab(tab) {
  ['text', 'image', 'audio'].forEach(t => {
    const btn     = document.getElementById(`omai-tab-${t}`);
    const content = document.getElementById(`omai-content-${t}`);
    const isActive = t === tab;
    if (btn)     btn.classList.toggle('active', isActive);
    if (content) {
      content.classList.toggle('active', isActive);
    }
  });
}

function updateOmaiToolHint() {
  const tool  = ddGetValue(document.getElementById('omaiTool'));
  const lang  = document.getElementById('omaiTranslateLang');
  const tone  = document.getElementById('omaiToneRow');
  if (lang)  lang.style.display  = tool === 'translate' ? '' : 'none';
  if (tone)  tone.style.display  = ['grammar', 'summarize', 'expand', 'shorten', 'translate'].includes(tool) ? 'none' : '';
}

async function runOmaiTextTool() {
  const tool   = ddGetValue(document.getElementById('omaiTool'));
  const text   = document.getElementById('omaiTextInput')?.value.trim();
  const lang   = document.getElementById('omaiLang')?.value.trim() || 'English';
  const tone   = ddGetValue(document.getElementById('omaiTone')) || null;
  const result = document.getElementById('omaiTextResult');
  const output = document.getElementById('omaiTextResultContent');

  if (!text) { toast('Enter some text first', 'err'); return; }

  if (result) result.classList.remove('visible');
  toast('Processing…', 'info');

  try {
    let applyTone = tone && !['grammar', 'summarize', 'expand', 'shorten', 'translate'].includes(tool);
    const r = await apiFetch('/api/oneminai/content-tool', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool, text, language: lang, tone: applyTone ? tone : null }),
    });
    if (r.text !== undefined) {
      if (output) output.textContent = r.text;
      if (result) result.style.display = '';
      toast('Done!', 'ok');
    } else {
      toast('Error: ' + (r.error || 'unknown'), 'err');
    }
  } catch (err) {
    toast('Error: ' + err.message, 'err');
  }
}

function omaiCopyResult() {
  const el = document.getElementById('omaiTextResultContent');
  if (el) navigator.clipboard.writeText(el.textContent).then(() => toast('Copied!', 'ok'));
}

function omaiInsertResult() {
  const el = document.getElementById('omaiTextResultContent');
  if (!el) return;
  const ta = document.getElementById('msgTa');
  if (ta) {
    const pos = ta.selectionStart;
    ta.value  = ta.value.slice(0, pos) + el.textContent + ta.value.slice(ta.selectionEnd);
    ta.focus();
    resizeTa(ta);
    updateCount(ta);
    toast('Inserted', 'ok');
  }
}

async function runOmaiImageGen() {
  const prompt = document.getElementById('omaiImagePrompt')?.value.trim();
  const model  = ddGetValue(document.getElementById('omaiImageModel'));
  const w      = parseInt(document.getElementById('omaiImgW')?.value || '1024');
  const h      = parseInt(document.getElementById('omaiImgH')?.value || '1024');
  const n      = parseInt(document.getElementById('omaiImgN')?.value || '1');
  const result = document.getElementById('omaiImageResult');
  const grid   = document.getElementById('omaiImageGrid');

  if (!prompt) { toast('Enter a prompt first', 'err'); return; }

  toast('Generating image…', 'info');
  if (result) result.classList.remove('visible');
  if (grid)   grid.innerHTML = '';

  try {
    const r = await apiFetch('/api/oneminai/image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, model, width: w, height: h, num_images: n }),
    });
    if (r.images && r.images.length) {
      if (result) result.classList.add('visible');
      r.images.forEach(img => {
        const wrap = document.createElement('div');
        wrap.className = 'omai-img-item';
        const im = document.createElement('img');
        im.src = img.url;
        im.alt = 'Generated image';
        im.title = 'Click to open in canvas';
        im.onclick = () => openInCanvas(img.url, 'generated.png', 'image/png');
        const dl = document.createElement('a');
        dl.href = img.url; dl.download = 'image.png';
        dl.className = 'omai-img-save';
        dl.textContent = '⬇ Save';
        wrap.appendChild(im); wrap.appendChild(dl);
        grid.appendChild(wrap);
      });
      toast(`Generated ${r.images.length} image(s)`, 'ok');
    } else {
      toast('Error: ' + (r.error || 'no images returned'), 'err');
    }
  } catch (err) {
    toast('Error: ' + err.message, 'err');
  }
}

async function runOmaiTTS() {
  const text  = document.getElementById('omaiTTSText')?.value.trim();
  const model = ddGetValue(document.getElementById('omaiTTSModel'));
  const voice = ddGetValue(document.getElementById('omaiTTSVoice'));
  const res   = document.getElementById('omaiTTSResult');
  const audio = document.getElementById('omaiTTSAudio');
  const dl    = document.getElementById('omaiTTSDownload');

  if (!text) { toast('Enter text first', 'err'); return; }
  if (res) res.style.display = 'none';
  toast('Synthesizing…', 'info');

  try {
    const r = await apiFetch('/api/oneminai/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, model, voice }),
    });
    if (r.audio_url) {
      if (audio) { audio.src = r.audio_url; audio.load(); }
      if (dl)    { dl.href = r.audio_url; dl.download = 'speech.mp3'; }
      if (res)   res.style.display = 'flex';
      toast('Done!', 'ok');
    } else {
      toast('Error: ' + (r.error || 'no audio'), 'err');
    }
  } catch (err) {
    toast('Error: ' + err.message, 'err');
  }
}

async function runOmaiMusic() {
  const prompt = document.getElementById('omaiMusicPrompt')?.value.trim();
  const model  = ddGetValue(document.getElementById('omaiMusicModel'));
  const instr  = document.getElementById('omaiInstrumental')?.checked;
  const res    = document.getElementById('omaiMusicResult');
  const audio  = document.getElementById('omaiMusicAudio');
  const dl     = document.getElementById('omaiMusicDownload');

  if (!prompt) { toast('Enter a music description first', 'err'); return; }
  if (res) res.style.display = 'none';
  toast('Composing music… (this may take a minute)', 'info');

  try {
    const r = await apiFetch('/api/oneminai/music', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, model, instrumental: instr }),
    });
    if (r.audio_url) {
      if (audio) { audio.src = r.audio_url; audio.load(); }
      if (dl)    { dl.href = r.audio_url; dl.download = 'music.mp3'; }
      if (res)   res.style.display = 'flex';
      toast('Music ready!', 'ok');
    } else {
      toast('Error: ' + (r.error || 'no audio'), 'err');
    }
  } catch (err) {
    toast('Error: ' + err.message, 'err');
  }
}

// Show 1min.AI panel button only for oneminai accounts
function _syncOneminaiPanelBtn() {
  const btn  = document.getElementById('oneminaiPanelBtn');
  const prov = getTabProvider();
  if (btn) btn.style.display = prov === 'oneminai' ? '' : 'none';

  // Flowith panel button
  const fbtn = document.getElementById('flowithPanelBtn');
  if (fbtn) fbtn.style.display = prov === 'flowith' ? '' : 'none';

  syncToolbarSeparators();
}

function filterConvs(q) {
  const lq = q.toLowerCase();
  document.querySelectorAll('.conv-item').forEach(el => {
    const name = el.querySelector('.conv-name')?.textContent || '';
    el.style.display = name.toLowerCase().includes(lq) ? '' : 'none';
  });
  /* show/hide section headers based on visible children */
  document.querySelectorAll('.sb-section').forEach(sec => {
    let next = sec.nextElementSibling;
    let anyVisible = false;
    while (next && !next.classList.contains('sb-section')) {
      if (next.classList.contains('conv-item') && next.style.display !== 'none') anyVisible = true;
      next = next.nextElementSibling;
    }
    sec.style.display = (q && !anyVisible) ? 'none' : '';
  });
}

async function refreshConv() {
  if (!S.convId) return;
  await fetchConvMeta(S.convId);
  renderMsgs(); syncToolbar(); buildBranchSel();
  const _scRef = S.canvasOpen && S.canvasTab === 'files';
  if (_scRef) renderCanvasFiles();
  toast('Refreshed', 'ok');
}

/* ═══════════════════════════════════════════
   TOOLBAR
═══════════════════════════════════════════ */
function syncToolbar() {
  if (!S.convId) return;
  const c = S.convs[S.convId];
  if (!c) return;
  const ttl = document.getElementById('tbTitle');
  const name = c.name || 'Untitled Conversation';
  ttl.textContent = name;
  ttl.className = `conv-title-display ${c.name ? '' : 'untitled'}`;
  document.title = (c.name || 'Conversation') + ' — Claude Console';
  const paprika = c.settings?.paprika_mode;
  S.thinking = (paprika === 'extended');
  updateThinkBtn();
}

async function cycleThink() {
  if (!S.convId) return;
  S.thinking = !S.thinking;
  toast(`Extended thinking ${S.thinking ? 'enabled' : 'disabled'}`, S.thinking ? 'ok' : 'info');
  updateThinkBtn();
}

function updateThinkBtn() {
  const btn = document.getElementById('thinkBtn');
  const lbl = document.getElementById('thinkLbl');
  if (S.thinking) {
    lbl.textContent = 'Think: on';
    btn.classList.add('on');
    btn.classList.remove('think-ext');
  } else {
    lbl.textContent = 'Think: off';
    btn.classList.remove('on', 'think-ext');
  }
}

function openConvInfo() {
  const c  = S.convs[S.convId];
  const el = document.getElementById('infoContent');
  if (c) {
    const safe = {...c}; delete safe.chat_messages;
    el.textContent =
      '=== Metadata ===\n' + JSON.stringify(safe, null, 2) +
      '\n\n=== Settings ===\n' + JSON.stringify(c.settings || {}, null, 2) +
      '\n\n=== Messages (' + (c.chat_messages?.length||0) + ') ===\n' +
      (c.chat_messages||[]).map(m => `[${m.sender}] ${(m.text||'').slice(0,80)}`).join('\n');
  }
  openOverlay('infoOverlay');
}

/* ═══════════════════════════════════════════
   MESSAGE RENDERING
═══════════════════════════════════════════ */
function renderMsgs() {
  const box = document.getElementById('msgs');
  if (!S.convId || !S.convs[S.convId]) { box.innerHTML = ''; return; }
  const conv = S.convs[S.convId];
  const msgs = buildChain(conv);
  if (!msgs.length) {
    box.innerHTML = `
      <div class="msg-empty">
        <div class="msg-empty-ico">✦</div>
        <div class="msg-empty-t">Start the conversation</div>
        <div class="msg-empty-s">Type a message below and press ↵</div>
      </div>`;
    return;
  }
  box.innerHTML = '';
  for (const m of msgs) box.appendChild(buildMsgEl(m));
  box.scrollTop = box.scrollHeight;

  if (BEX.open) {
    clearTimeout(window._bexRebuildTimer);
    window._bexRebuildTimer = setTimeout(bexRebuild, 120);
  }
}

function buildChain(conv) {
  const msgs = conv.chat_messages || [];
  if (!msgs.length) return [];

  const { byUuid, leafUuids } = bexBuildTree(conv);

  let leafUuid = BEX.viewLeafUuid;
  if (!leafUuid || !byUuid[leafUuid]) {
    leafUuid = conv.current_leaf_message_uuid;
    if (!leafUuid || !byUuid[leafUuid])
      leafUuid = bexFindDeepestLeaf(leafUuids, byUuid);
    BEX.viewLeafUuid = leafUuid;
  }

  if (!leafUuid) {
    return [...msgs].sort((a, b) => {
      if (a.index != null && b.index != null) return a.index - b.index;
      return new Date(a.created_at || 0) - new Date(b.created_at || 0);
    });
  }

  return bexChainFrom(leafUuid, byUuid);
}

function buildMsgEl(msg) {
  const el = document.createElement('div');
  el.className = `msg ${msg.sender}`;
  el.dataset.uuid = msg.uuid;

  // ── Provider label ──────────────────────────────────────────────────────
  const _prov = (S.tabAccount?.provider || 'claude').toLowerCase();
  const _aiLabel = { flowith: 'Flowith', oneminai: '1min.AI', chatwithai: 'ChatWithAI' }[_prov] ?? 'Claude';
  const isHuman = msg.sender === 'human';
  const senderLabel = isHuman ? 'You' : _aiLabel;
  const avatarChar  = isHuman ? 'Y' : 'C';
  const ts = fmtTime(msg.created_at);

  // ── Attached files ──────────────────────────────────────────────────────
  let filesHtml = '';
  if (msg.files_v2?.length) {
    const chips = msg.files_v2.map(f => {
      const mime    = f.file_kind || f.content_type || '';
      const name    = f.file_name || f.filename || 'file';
      const path    = f.path || '';
      const isImage = mime.startsWith('image/');

      if (!path) {
        return `<div class="file-chip"><span>${fileIcon(mime)}</span>
                  <span class="file-chip-name">${esc(name)}</span></div>`;
      }

      // Escape for inline event handlers
      const url       = dlUrl(S.convId, path);
      const urlInline = dlUrl(S.convId, path, true);
      const eUrl  = url.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      const eName = esc(name).replace(/'/g, "\\'");
      const eMime = mime.replace(/'/g, "\\'");

      if (isImage) {
        return `<div class="file-img-wrap">
          <img class="msg-img-preview" src="${urlInline}" alt="${esc(name)}" loading="lazy"
               onclick="openInCanvas('${eUrl}','${eName}','${eMime}')"
               title="Click to open in canvas"
               onerror="this.style.display='none'">
          <div style="display:flex;gap:4px;margin-top:3px">
            <button class="file-chip dl img-dl"
                    onclick="openInCanvas('${eUrl}','${eName}','${eMime}')"
                    style="border:none;cursor:pointer">👁 Canvas</button>
            <a class="file-chip dl img-dl" href="${url}" download="${esc(name)}">⬇ Save</a>
          </div>
        </div>`;
      }

      return `<div style="display:flex;gap:4px;align-items:center">
        <div class="file-chip"><span>${fileIcon(mime)}</span>
          <span class="file-chip-name">${esc(name)}</span></div>
        <button class="file-chip dl"
                onclick="openInCanvas('${eUrl}','${eName}','${eMime}')"
                title="Preview in canvas" style="border:none;cursor:pointer">👁</button>
        <a class="file-chip dl" href="${url}" download="${esc(name)}">⬇</a>
      </div>`;
    }).join('');
    filesHtml = `<div class="msg-files">${chips}</div>`;
  }

  // ── Content blocks ──────────────────────────────────────────────────────
  let blocks = msg.content?.length ? [...msg.content] : [];

  // Prefer cache if it has richer data
  const cached = contentCache[msg.uuid];
  if (cached?.length && (cached.length > blocks.length || cached.some(b => b.type !== 'text'))) {
    blocks = cached;
  }

  // Promote bare media URLs stored as plain text
  const _promoteUrl = (text) => {
    const t = text.trim();
    if (/\.(png|jpe?g|webp|gif|avif)(\?|$)/i.test(t))  return { type: 'flowith_image', url: t };
    if (/\.(mp4|webm|mov)(\?|$)/i.test(t))              return { type: 'flowith_video', url: t };
    return null;
  };

  if (!blocks.length && msg.text) {
    const promoted = _promoteUrl(msg.text);
    if (promoted) blocks = [promoted];
  } else if (blocks.length === 1 && blocks[0].type === 'text') {
    const promoted = _promoteUrl(blocks[0].text || '');
    if (promoted) blocks = [promoted];
  }

  // Render blocks → HTML string
  // Merge tool_result data onto tool_use blocks before rendering
  // (handles both streamed and non-streamed / server-loaded messages)
  mergeToolResults(blocks);

  let contentHtml = '';
  if (blocks.length) {
    for (const b of blocks) contentHtml += renderBlock(b, false, msg.sender);
  } else if (msg.text) {
    contentHtml = isHuman
      ? `<div class="md"><p>${esc(msg.text).replace(/\n/g, '<br>')}</p></div>`
      : `<div class="md">${marked.parse(msg.text)}</div>`;
  }

  // ── Action bars ─────────────────────────────────────────────────────────
  const _supBranch = S.tabAccount?._supBranching !== false;

  // Top utility bar (copy / collapse) — assistant only
  const topUtilsHtml = !isHuman ? `
    <div class="md-utils">
      <button class="md-util-btn copy"     onclick="copyMsgContent('${msg.uuid}', this)">
        <span>⎘</span><span>Copy</span>
      </button>
    </div>` : '';

  // Bottom utility bar — assistant only
  const forkBtnHtml = _supBranch
    ? `<button class="md-util-btn" onclick="bexForkFromNode('${msg.uuid}')" title="Fork a new branch from here">
         <span>⎇</span><span>Fork</span>
       </button>`
    : '';

  const bottomUtilsHtml = !isHuman ? `
    <div class="md-utils bottom">
      <button class="md-util-btn" onclick="regenerateMsg('${msg.uuid}')"
              title="Regenerate this response">
        <span>↻</span><span>Regenerate</span>
      </button>
      ${forkBtnHtml}
    </div>` : '';

  // Human message action row (edit / re-run)
  const humanActionsHtml = isHuman && _supBranch ? `
    <button class="msg-act-btn edit-btn" onclick="editMsg('${msg.uuid}')">✎ Edit</button>
    <button class="msg-act-btn"          onclick="rerunFromMsg('${msg.uuid}')"
            title="Re-run from this message">↻ Re-run</button>` : '';

  // ── Assemble ────────────────────────────────────────────────────────────
  el.innerHTML = `
    <div class="msg-header">
      ${!isHuman ? `<div class="msg-avatar assistant">${avatarChar}</div>` : ''}
      <span class="msg-sender ${isHuman ? 'human' : 'assistant'}">${senderLabel}</span>
      <span class="msg-ts">${ts}</span>
      ${isHuman ? `<div class="msg-avatar human">${avatarChar}</div>` : ''}
    </div>
    <div class="msg-body">
      ${filesHtml}
      ${topUtilsHtml}
      <div class="md-content-wrap" id="content-${msg.uuid}">
        ${contentHtml}
        <button class="md-expand-btn" onclick="expandMsg('${msg.uuid}')">Show more ↓</button>
      </div>
      ${bottomUtilsHtml}
    </div>
    ${humanActionsHtml ? `<div class="msg-actions">${humanActionsHtml}</div>` : ''}`;

  return el;
}

/* ═══════════════════════════════════════════
   TOOL WIDGET RENDERERS
═══════════════════════════════════════════ */

function _widgetId() {
  return 'w_' + Math.random().toString(36).slice(2, 9);
}

function _toolWidget(cssClass, badgeHtml, title, statusIcon, bodyHtml, rawData) {
  const wid     = _widgetId();
  const rawJson = rawData != null ? JSON.stringify(rawData, null, 2) : null;

  const rawBtn = rawJson
    ? `<button class="tool-raw-btn" onclick="_toggleRaw('${wid}')" title="View raw data">{ }</button>`
    : '';

  const rawPanel = rawJson ? `
    <div class="tool-raw-panel" id="raw_${wid}">
      <div class="tool-raw-content">${esc(rawJson)}</div>
    </div>` : '';

  return `
    <div class="widget-block ${cssClass}" id="${wid}">
      <div class="widget-head">
        ${badgeHtml}
        <span class="widget-title">${esc(title)}</span>
        <span class="widget-status">${statusIcon}</span>
        ${rawBtn}
      </div>
      ${bodyHtml}
      ${rawPanel}
    </div>`;
}

function _toolHead(badgeCss, badgeText, title, statusIcon) {
  return `<div class="widget-head">
    <span class="widget-badge" style="${badgeCss}">${badgeText}</span>
    <span class="widget-title">${esc(title)}</span>
    <span class="widget-status">${statusIcon}</span>
  </div>`;
}

function _toggleRaw(wid) {
  const panel = document.getElementById('raw_' + wid);
  if (!panel) return;
  panel.classList.toggle('open');
  const btn = document.querySelector('#' + wid + ' .tool-raw-btn');
  if (btn) btn.classList.toggle('active');
}

function _streamingBody() {
  return `<div class="widget-streaming">
    <div class="think-pulse"></div>
    <span>Fetching…</span>
  </div>`;
}

// ── Weather ───────────────────────────────────────────────────────────────
function renderWeatherTool(block, streaming) {
  const input = block.input || {};
  const loc   = input.location_name || input.city || 'Unknown location';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block weather-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:rgba(56,189,248,.1);color:var(--teal);border:1px solid rgba(56,189,248,.2)">🌤 WEATHER</span>
        <span class="widget-title">${esc(loc)}</span>
        <span class="widget-status">⟳ fetching</span>
      </div>
      <div class="widget-streaming"><div class="think-pulse"></div><span>Fetching weather…</span></div>
    </div>`;
  }

  const { text: rawText } = _extractToolResult(block);

  // rawText may be the parsed JSON object or a string we need to parse
  let data = {};
  if (rawText && typeof rawText === 'object' && !Array.isArray(rawText)) {
    data = rawText;
  } else if (typeof rawText === 'string') {
    try { data = JSON.parse(rawText); } catch {}
  }

  const current = data.current || {};

  const temp     = current.temperature ?? current.temp ?? null;
  const desc     = current.condition_text || current.condition || current.description || '';
  const humidity = current.humidity ?? null;
  const wind     = current.wind_speed ?? current.wind_kph ?? current.wind_mph ?? null;
  const feelsLike= current.feelslike_f ?? current.feelslike_c ?? null;
  const isDay    = current.is_day !== false;

  // Temperature unit: if temp > 55 it's almost certainly Fahrenheit
  const isFahrenheit = temp !== null && temp > 55;
  const unitSym = isFahrenheit ? '°F' : '°C';

  function _weatherIcon(d) {
    const dl = (d || '').toLowerCase();
    if (dl.includes('thunder') || dl.includes('storm')) return '⛈';
    if (dl.includes('snow') || dl.includes('blizzard')) return '❄️';
    if (dl.includes('rain') || dl.includes('drizzle') || dl.includes('shower')) return '🌧';
    if (dl.includes('cloud') || dl.includes('overcast')) return '☁️';
    if (dl.includes('fog') || dl.includes('mist') || dl.includes('haze')) return '🌫';
    if (dl.includes('partly')) return isDay ? '⛅' : '🌙';
    if (dl.includes('clear') || dl.includes('sunny') || dl.includes('fair')) return isDay ? '☀️' : '🌙';
    return '🌤';
  }

  const icon = _weatherIcon(desc);
  const displayTemp = temp !== null
    ? `${Math.round(temp)}${unitSym}`
    : '—';

  // Daily forecast (next 3 days)
  const daily = data.daily || [];
  const forecastHtml = daily.slice(0, 3).map(d => `
    <div style="display:flex;align-items:center;gap:6px;padding:3px 0;font-size:var(--fs-sm);color:var(--text-2);font-family:var(--font-mono)">
      <span style="min-width:36px;color:var(--text-3)">${d.day_of_week ? d.day_of_week.slice(0,3) : ''}</span>
      <span>${d.high != null ? Math.round(d.high) + unitSym : '—'}</span>
      ${d.precipitation_chance != null
        ? `<span style="color:var(--teal);margin-left:auto">${d.precipitation_chance}% 🌧</span>`
        : ''}
    </div>`).join('');

  let detailChips = '';
  if (humidity != null)  detailChips += `<div class="weather-detail-chip">💧 ${humidity}%</div>`;
  if (wind     != null)  detailChips += `<div class="weather-detail-chip">💨 ${Math.round(wind)} ${isFahrenheit ? 'mph' : 'km/h'}</div>`;
  if (feelsLike!= null)  detailChips += `<div class="weather-detail-chip">🌡 Feels ${Math.round(feelsLike)}${unitSym}</div>`;

  const locationDisplay = data.location || loc;

  const weatherBodyHtml = `<div class="widget-body">
    <div class="weather-main">
      <div class="weather-icon">${icon}</div>
      <div>
        <div class="weather-temp">${displayTemp}</div>
        <div class="weather-desc">${esc(desc)}</div>
        <div class="weather-location">📍 ${esc(locationDisplay)}</div>
      </div>
    </div>
    ${detailChips ? `<div class="weather-details">${detailChips}</div>` : ''}
    ${forecastHtml
      ? `<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border-s)">${forecastHtml}</div>`
      : ''}
  </div>`;

  return _toolWidget(
    'weather-widget',
    `<span class="widget-badge" style="background:rgba(56,189,248,.1);color:var(--teal);border:1px solid rgba(56,189,248,.2)">🌤 WEATHER</span>`,
    locationDisplay,
    '✓ done',
    weatherBodyHtml,
    { input: block.input, result: data }
  );
}

// ── Map ───────────────────────────────────────────────────────────────────
function renderMapTool(block, streaming) {
  const input = block.input || {};
  const title = input.title || 'Itinerary';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block map-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:var(--green-dim);color:var(--green);border:1px solid rgba(74,222,128,.2)">🗺 MAP</span>
        <span class="widget-title">${esc(title)}</span>
        <span class="widget-status">⟳ building</span>
      </div>
      <div class="widget-streaming"><div class="think-pulse"></div><span>Building map…</span></div>
    </div>`;
  }

  const days      = input.days || [];
  const narrative = input.narrative || '';

  const { text: rawText } = _extractToolResult(block);
  let enriched = {};

  if (rawText && typeof rawText === 'object') {
    enriched = rawText.enriched_places || {};
  } else if (typeof rawText === 'string') {
    try { const p = JSON.parse(rawText); enriched = p.enriched_places || {}; } catch {}
  }

  // Also check _result_parsed directly
  if (!Object.keys(enriched).length && block._result_parsed) {
    const items = Array.isArray(block._result_parsed) ? block._result_parsed : [block._result_parsed];
    for (const item of items) {
      if (!item) continue;
      if (typeof item === 'object' && item.enriched_places) { enriched = item.enriched_places; break; }
      if (item.type === 'text' && item.text) {
        try { const p = JSON.parse(item.text); if (p.enriched_places) { enriched = p.enriched_places; break; } }
        catch {}
      }
    }
  }

  let daysHtml = '';
  for (const day of days) {
    const locs = day.locations || [];
    const locsHtml = locs.map(loc => {
      const ep       = enriched[loc.place_id] || {};
      const rating   = ep.rating ?? loc.rating;
      const photo    = ep.photos?.[0]?.url || '';
      const mapsUrl  = ep.maps_url
        || `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(loc.name)}`;

      return `
        <div class="map-location-row">
          <div class="map-loc-line">
            <div class="map-loc-dot"></div>
            <div class="map-loc-vline"></div>
          </div>
          <div class="map-loc-info" style="display:flex;gap:8px;align-items:flex-start">
            ${photo
              ? `<img src="${esc(photo)}"
                      style="width:44px;height:44px;border-radius:var(--r);object-fit:cover;flex-shrink:0;border:1px solid var(--border);margin-top:2px"
                      onerror="this.style.display='none'">`
              : ''}
            <div style="flex:1">
              <div class="map-loc-name">
                <a href="${esc(mapsUrl)}" target="_blank" rel="noopener"
                   style="color:inherit;text-decoration:none"
                   onmouseover="this.style.textDecoration='underline'"
                   onmouseout="this.style.textDecoration='none'">${esc(loc.name)}</a>
                ${rating != null
                  ? `<span style="font-size:var(--fs-xs);color:var(--yellow);font-family:var(--font-mono);margin-left:5px">★ ${rating}</span>`
                  : ''}
              </div>
              ${loc.arrival_time
                ? `<div class="map-loc-time">🕐 ${esc(loc.arrival_time)}${loc.duration_minutes ? ` · ${loc.duration_minutes}min` : ''}</div>`
                : ''}
              ${loc.notes ? `<div class="map-loc-notes">${esc(loc.notes)}</div>` : ''}
            </div>
          </div>
        </div>`;
    }).join('');

    daysHtml += `
      <div class="map-day-title">${days.length > 1 ? `Day ${day.day_number}: ` : ''}${esc(day.title || '')}</div>
      <div class="map-locations">${locsHtml}</div>`;
  }

  const allLocs = days.flatMap(d => d.locations || []);
  let mapsUrl = '';
  if (allLocs.length >= 2) {
    const origin    = encodeURIComponent(allLocs[0].name);
    const dest      = encodeURIComponent(allLocs[allLocs.length - 1].name);
    const waypoints = allLocs.slice(1, -1).map(l => encodeURIComponent(l.name)).join('|');
    mapsUrl = `https://www.google.com/maps/dir/${origin}/${waypoints ? waypoints + '/' : ''}${dest}`;
  }

  return _toolWidget(
    'map-widget',
    `<span class="widget-badge" style="background:var(--green-dim);color:var(--green);border:1px solid rgba(74,222,128,.2)">🗺 MAP</span>`,
    title, '✓ done',
    `<div class="widget-body">
      ${narrative ? `<div style="font-size:12px;color:var(--text-3);margin-bottom:10px;line-height:1.55">${esc(narrative)}</div>` : ''}
      ${daysHtml}
      ${mapsUrl ? `<a class="map-open-btn" href="${esc(mapsUrl)}" target="_blank" rel="noopener">🗺 Open in Google Maps</a>` : ''}
    </div>`,
    { title, location_count: allLocs.length }
  );
}

// ── Places Search ─────────────────────────────────────────────────────────
function renderPlacesSearchTool(block, streaming) {
  const input   = block.input || {};
  const queries = input.queries || (input.query ? [{ query: input.query }] : []);
  const title   = queries.map(q => q.query).join(' · ').slice(0, 50) || 'Places';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block places-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(251,191,36,.2)">📍 PLACES</span>
        <span class="widget-title">${esc(title)}</span>
        <span class="widget-status">⟳ searching</span>
      </div>
      <div class="widget-streaming"><div class="think-pulse"></div><span>Searching places…</span></div>
    </div>`;
  }

  // Extract places from all possible locations
  let places = [];

  // 1. _result_parsed items
  if (block._result_parsed) {
    const items = Array.isArray(block._result_parsed) ? block._result_parsed : [block._result_parsed];
    for (const item of items) {
      if (!item) continue;
      // Direct object with places array
      if (typeof item === 'object' && Array.isArray(item.places)) { places = item.places; break; }
      // Direct array of place objects
      if (typeof item === 'object' && Array.isArray(item) && item[0]?.name) { places = item; break; }
      // Text JSON
      if (item.type === 'text' && item.text) {
        try {
          const p = JSON.parse(item.text);
          if (p && Array.isArray(p.places)) { places = p.places; break; }
          if (Array.isArray(p) && p[0]?.name) { places = p; break; }
        } catch {}
      }
    }
  }

  // 2. _extractToolResult fallback
  if (!places.length) {
    const { text: rawText } = _extractToolResult(block);
    if (rawText && typeof rawText === 'object') {
      if (Array.isArray(rawText.places))  places = rawText.places;
      else if (Array.isArray(rawText))    places = rawText;
    } else if (typeof rawText === 'string') {
      try { const p = JSON.parse(rawText); if (p.places) places = p.places; else if (Array.isArray(p)) places = p; }
      catch {}
    }
  }

  if (!places.length) {
    return _toolWidget(
      'places-widget',
      `<span class="widget-badge" style="background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(251,191,36,.2)">📍 PLACES</span>`,
      title, '✓ done',
      `<div class="widget-body" style="font-size:12px;color:var(--text-3)">Searched: ${esc(title)}</div>`,
      { queries: block.input?.queries }
    );
  }

  const placesHtml = places.slice(0, 8).map(p => {
    const name    = p.name || '?';
    const addr    = p.address || p.vicinity || p.formatted_address || '';
    const rating  = p.rating;
    const mapsUrl = p.maps_url
      || `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(name)}`;
    const photo   = p.photos?.[0]?.url || '';
    const hours   = p.weekday_hours || [];
    const todayHours = hours.find(h => h.includes(
      new Date().toLocaleDateString('en-US', { weekday: 'long' })
    ));
    const priceLevel = p.price_level;
    const priceStr   = priceLevel ? '💰'.repeat(Math.min(priceLevel, 4)) : '';

    return `
      <div class="place-item">
        ${photo
          ? `<img src="${esc(photo)}"
                  style="width:44px;height:44px;border-radius:var(--r);object-fit:cover;flex-shrink:0;border:1px solid var(--border)"
                  onerror="this.outerHTML='<div class=\\'place-icon\\'>📍</div>'">`
          : `<div class="place-icon">📍</div>`}
        <div class="place-info">
          <div class="place-name">
            <a href="${esc(mapsUrl)}" target="_blank" rel="noopener"
               style="color:inherit;text-decoration:none"
               onmouseover="this.style.textDecoration='underline'"
               onmouseout="this.style.textDecoration='none'">${esc(name)}</a>
          </div>
          ${addr ? `<div class="place-addr">${esc(addr.slice(0, 70))}</div>` : ''}
          <div class="place-meta">
            ${rating != null ? `<span class="place-rating">★ ${rating}</span>` : ''}
            ${priceStr ? `<span style="font-size:var(--fs-xs);color:var(--yellow)">${priceStr}</span>` : ''}
            ${todayHours
              ? `<span class="place-type">${esc(todayHours.replace(/^[^:]+:\s*/, ''))}</span>`
              : ''}
          </div>
        </div>
      </div>`;
  }).join('');

  return _toolWidget(
    'places-widget',
    `<span class="widget-badge" style="background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(251,191,36,.2)">📍 PLACES</span>`,
    title, '✓ done',
    `<div class="widget-body">${placesHtml}</div>`,
    { queries: block.input?.queries, place_count: places.length }
  );
}

// ── Recipe ────────────────────────────────────────────────────────────────


function renderRecipeTool(block, streaming) {
  const input = block.input || {};
  const title = input.title || 'Recipe';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block recipe-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:var(--oneminai-dim);color:var(--oneminai);border:1px solid var(--oneminai-mid)">🍽 RECIPE</span>
        <span class="widget-title">${esc(title)}</span>
        <span class="widget-status">⟳ preparing</span>
      </div>
      <div class="widget-streaming"><div class="think-pulse"></div><span>Preparing recipe…</span></div>
    </div>`;
  }

  // Use result data if richer, else fall back to input
  const { text: rawText, gallery } = _extractToolResult(block);
  let rdata = input;
  if (rawText && typeof rawText === 'object' && !Array.isArray(rawText)) {
    rdata = Object.keys(rawText).length > 3 ? rawText : input;
  } else if (typeof rawText === 'string') {
    try { const p = JSON.parse(rawText); if (p && typeof p === 'object') rdata = p; } catch {}
  }

  const ingredients = rdata.ingredients || input.ingredients || [];
  const steps       = rdata.steps       || input.steps       || [];
  const notes       = rdata.notes       || input.notes       || '';
  const description = rdata.description || input.description || '';
  const servings    = rdata.base_servings ?? input.base_servings;

  // Build ingredient id → name map
  const ingMap = {};
  for (const ing of ingredients) { if (ing.id) ingMap[ing.id] = ing.name; }

  function resolveIng(text) {
    return esc(text).replace(/\{(\w+)\}/g, (_, id) => {
      const name = ingMap[id];
      return name
        ? `<strong style="color:var(--oneminai)">${esc(name)}</strong>`
        : `{${esc(id)}}`;
    });
  }

  const foodPhoto = gallery?.[0]?.url || '';

  const ingredientsHtml = ingredients.map(ing => `
    <div class="recipe-ingredient">
      <span class="recipe-ingredient-amt">${ing.amount != null ? ing.amount : ''} ${esc(ing.unit || '')}</span>
      <span class="recipe-ingredient-name">${esc(ing.name || '')}</span>
    </div>`).join('');

  const stepsHtml = steps.map((step, i) => {
    const timer = step.timer_seconds
      ? `<div class="recipe-step-timer">⏱ ${Math.ceil(step.timer_seconds / 60)}min</div>`
      : '';
    return `
      <div class="recipe-step">
        <div class="recipe-step-num">${i + 1}</div>
        <div class="recipe-step-body">
          ${step.title ? `<div class="recipe-step-title">${esc(step.title)}</div>` : ''}
          <div class="recipe-step-text">${resolveIng(step.content || step.text || '')}</div>
          ${timer}
        </div>
      </div>`;
  }).join('');

  const recipeBodyHtml = `
    ${foodPhoto
      ? `<img src="${esc(foodPhoto)}" alt="${esc(title)}" loading="lazy"
              style="width:100%;height:160px;object-fit:cover;display:block;border-bottom:1px solid var(--border)"
              onerror="this.style.display='none'">`
      : ''}
    <div class="widget-body">
      ${description ? `<div style="font-size:12px;color:var(--text-3);margin-bottom:8px;line-height:1.55">${esc(description)}</div>` : ''}
      <div class="recipe-meta">
        ${servings != null ? `<span class="recipe-meta-chip">👥 ${servings} servings</span>` : ''}
        ${ingredients.length ? `<span class="recipe-meta-chip">🧂 ${ingredients.length} ingredients</span>` : ''}
        ${steps.length ? `<span class="recipe-meta-chip">📋 ${steps.length} steps</span>` : ''}
      </div>
      ${ingredients.length ? `<div class="recipe-section-title">Ingredients</div><div class="recipe-ingredients">${ingredientsHtml}</div>` : ''}
      ${steps.length ? `<div class="recipe-section-title">Steps</div><div class="recipe-steps">${stepsHtml}</div>` : ''}
      ${notes ? `<div class="recipe-notes">💡 ${esc(notes)}</div>` : ''}
    </div>`;

  return _toolWidget(
    'recipe-widget',
    `<span class="widget-badge" style="background:var(--oneminai-dim);color:var(--oneminai);border:1px solid var(--oneminai-mid)">🍽 RECIPE</span>`,
    title, '✓ done', recipeBodyHtml,
    { title, servings, ingredient_count: ingredients.length, step_count: steps.length }
  );
}

// ── Message Compose ───────────────────────────────────────────────────────
function renderMessageComposeTool(block, streaming) {
  const input    = block.input || {};
  const title    = input.summary_title || 'Message';
  const variants = input.variants || [];
  const kind     = input.kind || 'message';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block compose-widget">
      ${_toolHead('', '✉ COMPOSE', title, '⟳ drafting')}
      ${_streamingBody()}
    </div>`;
  }

  const variantsHtml = variants.map((v, i) => {
    const vid = 'comp_' + Math.random().toString(36).slice(2, 7);
    return `
      <div class="compose-variant">
        ${v.label ? `<div class="compose-variant-label">${esc(v.label)}</div>` : ''}
        <div class="compose-variant-body" id="${vid}">${esc(v.body || '')}</div>
        <div class="compose-actions">
          <button class="compose-btn" onclick="_composeCopy('${vid}',this)">⎘ Copy</button>
          <button class="compose-btn" onclick="_composeInsert('${vid}')">↩ Insert</button>
        </div>
      </div>`;
  }).join('');

  return _toolWidget(
    'compose-widget',
    `<span class="widget-badge" style="background:var(--violet-dim);color:var(--violet);border:1px solid rgba(192,132,252,.2)">✉ COMPOSE</span>`,
    title,
    '✓ done',
    `<div class="widget-body">
      <div style="font-size:var(--fs-xs);color:var(--text-3);font-family:var(--font-mono);margin-bottom:8px;text-transform:uppercase;letter-spacing:.07em">
        ${esc(kind)}
      </div>
      ${variantsHtml}
    </div>`,
    { title, kind, variant_count: variants.length }
  );
}

function _composeCopy(id, btn) {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => {
    btn.textContent = '✓ Copied';
    setTimeout(() => { btn.textContent = '⎘ Copy'; }, 2000);
  });
}

function _composeInsert(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const ta = document.getElementById('msgTa');
  if (ta) {
    ta.value = el.textContent;
    resizeTa(ta);
    updateCount(ta);
    ta.focus();
    toast('Inserted', 'ok');
  }
}

// ── Sports ────────────────────────────────────────────────────────────────
function renderSportsTool(block, streaming) {
  const input    = block.input || {};
  const league   = (input.league || input.sport || 'Sports').toUpperCase();
  const dataType = input.data_type || 'scores';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block sports-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:var(--blue-dim);color:var(--blue);border:1px solid rgba(96,165,250,.2)">⚽ SPORTS</span>
        <span class="widget-title">${esc(league)}</span>
        <span class="widget-status">⟳ fetching</span>
      </div>
      <div class="widget-streaming"><div class="think-pulse"></div><span>Fetching data…</span></div>
    </div>`;
  }

  // Extract raw result — may be in _result_parsed text items
  let data = {};
  const { text: rawText } = _extractToolResult(block);

  if (rawText && typeof rawText === 'object' && !Array.isArray(rawText)) {
    data = rawText;
  } else if (typeof rawText === 'string') {
    try { data = JSON.parse(rawText); } catch {}
  }

  // Also try reading directly from _result_parsed items
  if (!Object.keys(data).length && block._result_parsed) {
    const items = Array.isArray(block._result_parsed) ? block._result_parsed : [block._result_parsed];
    for (const item of items) {
      if (!item) continue;
      // Direct object
      if (typeof item === 'object' && (item.standings || item.matches || item.scores || item.league)) {
        data = item; break;
      }
      // Text containing JSON
      if (item.type === 'text' && item.text) {
        try { const p = JSON.parse(item.text); if (p && typeof p === 'object') { data = p; break; } }
        catch {}
      }
    }
  }

  const leagueName = data.league || data.competition || league;
  const title      = data.title  || leagueName;

  const standings = data.standings || [];
  const matches   = data.matches || data.scores || data.games || data.results || [];

  // ── Standings ──
  if (standings.length > 0) {
    const rowsHtml = standings.slice(0, 20).map(r => {
      const teamName = (r.team && typeof r.team === 'object') ? r.team.name : (r.team || r.team_name || '?');
      const pts      = r.points ?? r.pts ?? '—';
      const isTop4   = r.rank <= 4;
      const isRelegation = r.rank >= standings.length - 2;
      const rowColor = isTop4 ? 'var(--teal)' : isRelegation ? 'var(--red)' : 'var(--text-2)';
      return `
        <div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border-s);font-size:12px">
          <span style="font-family:var(--font-mono);color:var(--text-3);min-width:20px;text-align:right">${r.rank}</span>
          <span style="flex:1;font-weight:${isTop4 ? '700' : '400'};color:${rowColor}">${esc(teamName)}</span>
          <span style="font-family:var(--font-mono);font-size:var(--fs-xs);color:var(--text-3)">${r.wins ?? ''}W ${r.draws ?? ''}D ${r.losses ?? ''}L</span>
          <span style="font-family:var(--font-mono);font-weight:700;color:var(--blue);min-width:36px;text-align:right">${pts}pts</span>
        </div>`;
    }).join('');

    return _toolWidget(
      'sports-widget',
      `<span class="widget-badge" style="background:var(--blue-dim);color:var(--blue);border:1px solid rgba(96,165,250,.2)">⚽ SPORTS</span>`,
      title,
      '✓ done',
      `<div class="widget-body">
        <div class="sports-league-label">${esc(leagueName)} · Standings</div>
        ${rowsHtml}
      </div>`,
      { input: block.input, data }
    );
  }

  // ── Scores / matches ──
  const matchesHtml = matches.slice(0, 10).map(m => {
    const home      = (m.home_team && typeof m.home_team === 'object') ? m.home_team.name : (m.home_team || m.home || '?');
    const away      = (m.away_team && typeof m.away_team === 'object') ? m.away_team.name : (m.away_team || m.away || '?');
    const homeScore = m.home_score ?? m.score_home ?? null;
    const awayScore = m.away_score ?? m.score_away ?? null;
    const hasScore  = homeScore !== null && awayScore !== null;
    const homeWon   = hasScore && Number(homeScore) > Number(awayScore);
    const awayWon   = hasScore && Number(awayScore) > Number(homeScore);
    const status    = m.status || m.state || '';
    return `
      <div class="sports-match">
        <div class="sports-team ${homeWon ? 'winner' : ''}">${esc(home)}</div>
        <div class="sports-score">${hasScore ? `${homeScore}–${awayScore}` : (status || 'vs')}</div>
        <div class="sports-team-home ${awayWon ? 'winner' : ''}">${esc(away)}</div>
      </div>`;
  }).join('');

  const noDataHtml = (!standings.length && !matches.length)
    ? `<div style="font-size:12px;color:var(--text-3);font-family:var(--font-mono);padding:4px 0">
        Data received for ${esc(leagueName)}
       </div>`
    : '';

  return _toolWidget(
    'sports-widget',
    `<span class="widget-badge" style="background:var(--blue-dim);color:var(--blue);border:1px solid rgba(96,165,250,.2)">⚽ SPORTS</span>`,
    title,
    '✓ done',
    `<div class="widget-body">
      <div class="sports-league-label">${esc(leagueName)} · ${esc(dataType)}</div>
      ${matchesHtml || noDataHtml}
    </div>`,
    { input: block.input, data }
  );
}

// ── Image Search ──────────────────────────────────────────────────────────
function renderImageSearchTool(block, streaming) {
  const input = block.input || {};
  const query = input.query || 'Images';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block imgsearch-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:var(--teal-dim);color:var(--teal);border:1px solid rgba(56,189,248,.2)">🖼 IMAGES</span>
        <span class="widget-title">${esc(query)}</span>
        <span class="widget-status">⟳ searching</span>
      </div>
      <div class="widget-streaming"><div class="think-pulse"></div><span>Searching images…</span></div>
    </div>`;
  }

  // Extract images from all possible locations
  let images = [];

  // 1. gallery from _extractToolResult (image_gallery block type)
  const { text: rawText, gallery } = _extractToolResult(block);
  if (gallery && gallery.length) images = gallery;

  // 2. _result_parsed items
  if (!images.length && block._result_parsed) {
    const items = Array.isArray(block._result_parsed) ? block._result_parsed : [block._result_parsed];
    for (const item of items) {
      if (!item) continue;
      // image_gallery type item
      if (item.type === 'image_gallery' && Array.isArray(item.images)) { images = item.images; break; }
      // Object with images array
      if (typeof item === 'object' && Array.isArray(item.images)) { images = item.images; break; }
      // Array of image objects
      if (typeof item === 'object' && Array.isArray(item) && item[0]?.url) { images = item; break; }
      // Text JSON
      if (item.type === 'text' && item.text) {
        try {
          const p = JSON.parse(item.text);
          if (p && Array.isArray(p.images)) { images = p.images; break; }
          if (p && Array.isArray(p.results)) { images = p.results; break; }
          if (Array.isArray(p) && p[0]?.url) { images = p; break; }
        } catch {}
      }
    }
  }

  // 3. rawText fallback
  if (!images.length && rawText) {
    if (typeof rawText === 'object') {
      if (Array.isArray(rawText.images))  images = rawText.images;
      else if (Array.isArray(rawText.results)) images = rawText.results;
      else if (Array.isArray(rawText))    images = rawText;
    } else if (typeof rawText === 'string') {
      try {
        const p = JSON.parse(rawText);
        if (Array.isArray(p.images)) images = p.images;
        else if (Array.isArray(p)) images = p;
      } catch {}
    }
  }

  if (!images.length) {
    return _toolWidget(
      'imgsearch-widget',
      `<span class="widget-badge" style="background:var(--teal-dim);color:var(--teal);border:1px solid rgba(56,189,248,.2)">🖼 IMAGES</span>`,
      query, '✓ done',
      `<div class="widget-body" style="font-size:12px;color:var(--text-3)">Searched: "${esc(query)}"</div>`,
      { query }
    );
  }

  const gridHtml = images.slice(0, 9).map(img => {
    const url     = img.url || img.thumbnail_url || img.image_url || img.src || '';
    const imgTitle= img.title || img.alt || '';
    const origin  = img.origin_url || img.source_url || img.link || '';
    if (!url) return '';
    const eUrl    = esc(url);
    const eName   = esc(imgTitle || 'image');
    return `
      <div class="imgsearch-item">
        <img src="${eUrl}" alt="${eName}" loading="lazy"
             onclick="openInCanvas('${eUrl}','${eName}','image/jpeg')"
             onerror="this.parentElement.style.display='none'">
        ${imgTitle
          ? `<div class="imgsearch-caption" title="${eName}">${esc(imgTitle.slice(0,40))}${imgTitle.length>40?'…':''}</div>`
          : ''}
      </div>`;
  }).join('');

  return _toolWidget(
    'imgsearch-widget',
    `<span class="widget-badge" style="background:var(--teal-dim);color:var(--teal);border:1px solid rgba(56,189,248,.2)">🖼 IMAGES</span>`,
    query, '✓ done',
    `<div class="widget-body">
      <div class="imgsearch-query">🔍 <span style="font-family:var(--font-mono);color:var(--teal)">${esc(query)}</span>
        <span style="color:var(--text-3);font-size:10px">${images.length} results</span>
      </div>
      <div class="imgsearch-grid">${gridHtml}</div>
    </div>`,
    { query, image_count: images.length }
  );
}

// ── Web Search ────────────────────────────────────────────────────────────
function renderWebSearchTool(block, streaming) {
  const input = block.input || {};
  const query = input.query || 'Search';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block websearch-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:var(--accent-dim);color:var(--accent);border:1px solid rgba(168,85,247,.2)">🔍 SEARCH</span>
        <span class="widget-title">${esc(query)}</span>
        <span class="widget-status">⟳ searching</span>
      </div>
      <div class="widget-streaming"><div class="think-pulse"></div><span>Searching the web…</span></div>
    </div>`;
  }

  // Gather all knowledge items from _result_parsed
  let results = [];
  if (block._result_parsed) {
    const items = Array.isArray(block._result_parsed) ? block._result_parsed : [block._result_parsed];
    for (const item of items) {
      if (!item) continue;
      if (item.type === 'knowledge') { results.push(item); continue; }
      // Array of knowledge items
      if (Array.isArray(item)) {
        const knowItems = item.filter(x => x && x.type === 'knowledge');
        if (knowItems.length) { results = results.concat(knowItems); continue; }
      }
      // JSON text containing results
      if (item.type === 'text' && item.text) {
        try {
          const p = JSON.parse(item.text);
          if (Array.isArray(p)) {
            const k = p.filter(x => x && (x.type === 'knowledge' || x.title));
            if (k.length) results = results.concat(k);
          } else if (p && Array.isArray(p.results)) {
            results = results.concat(p.results);
          }
        } catch {}
      }
    }
  }

  // Fallback via _extractToolResult
  if (!results.length) {
    const { text: rawText } = _extractToolResult(block);
    if (Array.isArray(rawText)) {
      results = rawText.filter(r => r && (r.type === 'knowledge' || r.title || r.url));
    } else if (rawText && typeof rawText === 'object' && Array.isArray(rawText._knowledge)) {
      results = rawText._knowledge;
    } else if (rawText && typeof rawText === 'object' && Array.isArray(rawText.results)) {
      results = rawText.results;
    }
  }

  const resultsHtml = results.slice(0, 6).map(r => {
    const title   = r.title || '?';
    const url     = r.url   || '';
    const favicon = r.metadata?.favicon_url || '';
    const source  = r.metadata?.site_name
      || (url ? url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0] : '');
    const dispUrl = url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 60);

    return `
      <div class="websearch-result">
        <div class="websearch-result-title" style="display:flex;align-items:center;gap:5px">
          ${favicon ? `<img src="${esc(favicon)}" width="12" height="12" style="border-radius:2px;flex-shrink:0" onerror="this.style.display='none'">` : ''}
          ${url
            ? `<a href="${esc(url)}" target="_blank" rel="noopener"
                 style="color:var(--teal);text-decoration:none"
                 onmouseover="this.style.textDecoration='underline'"
                 onmouseout="this.style.textDecoration='none'">${esc(title)}</a>`
            : esc(title)}
        </div>
        ${source ? `<div class="websearch-result-url">${esc(source)}</div>` : ''}
      </div>`;
  }).join('');

  return _toolWidget(
    'websearch-widget',
    `<span class="widget-badge" style="background:var(--accent-dim);color:var(--accent);border:1px solid rgba(168,85,247,.2)">🔍 SEARCH</span>`,
    query, '✓ done',
    `<div class="widget-body">
      <div class="websearch-query">
        🔍 <span class="websearch-query-text">${esc(query)}</span>
        ${results.length ? `<span style="color:var(--text-3);font-size:10px">${results.length} results</span>` : ''}
      </div>
      ${resultsHtml || `<div style="font-size:12px;color:var(--text-3)">Search completed</div>`}
    </div>`,
    { query, result_count: results.length }
  );
}

// ── Web Fetch ─────────────────────────────────────────────────────────────
function renderWebFetchTool(block, streaming) {
  const input  = block.input || {};
  const url    = input.url || '';
  const domain = url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0];

  const dispContent = block._result_display;
  const richLink    = dispContent?.type === 'rich_link' ? dispContent.link : null;
  const favicon     = richLink?.icon_url || '';
  const pageTitle   = richLink?.title || domain;

  if (streaming && !block._result_parsed && !block._result_display) {
    return `<div class="widget-block webfetch-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:var(--accent-dim);color:var(--accent);border:1px solid rgba(168,85,247,.2)">🌐 FETCH</span>
        <span class="widget-title">${esc(domain || url)}</span>
        <span class="widget-status">⟳ fetching</span>
      </div>
      <div class="widget-streaming"><div class="think-pulse"></div><span>Fetching page…</span></div>
    </div>`;
  }

  // Extract result — knowledge items or text summary
  let summary = '';
  let itemCount = 0;

  if (block._result_parsed) {
    const items = Array.isArray(block._result_parsed)
      ? block._result_parsed
      : [block._result_parsed];

    for (const item of items) {
      if (!item) continue;
      if (item.type === 'knowledge') {
        itemCount++;
        if (!summary && item.title) summary = item.title;
      } else if (item.type === 'text' && item.text) {
        // Plain text snippet — use first non-empty line as summary
        const firstLine = item.text.trim().split('\n').find(l => l.trim().length > 10) || '';
        if (!summary && firstLine) summary = firstLine.slice(0, 120);
        itemCount++;
      }
    }
  }

  // Fallback via _extractToolResult
  if (!summary) {
    const { text: rawText } = _extractToolResult(block);
    if (Array.isArray(rawText) && rawText.length) {
      itemCount = rawText.length;
      const first = rawText.find(r => r && (r.title || r.text));
      if (first) summary = first.title || (first.text || '').slice(0, 120);
    } else if (typeof rawText === 'string' && rawText.trim()) {
      summary = rawText.trim().split('\n').find(l => l.trim().length > 10) || '';
      summary = summary.slice(0, 120);
      itemCount = 1;
    }
  }

  const statusLine = itemCount > 0
    ? `${itemCount} section${itemCount !== 1 ? 's' : ''} fetched`
    : 'Page fetched';

  const bodyHtml = `<div class="widget-body">
    <div class="webfetch-url" style="display:flex;align-items:center;gap:6px">
      ${favicon
        ? `<img src="${esc(favicon)}" width="14" height="14"
               style="border-radius:3px;flex-shrink:0"
               onerror="this.style.display='none'">`
        : '🌐'}
      <a href="${esc(url)}" target="_blank" rel="noopener"
         style="color:var(--teal);text-decoration:none;flex:1;overflow:hidden;
                text-overflow:ellipsis;white-space:nowrap">${esc(pageTitle || url)}</a>
    </div>
    ${summary
      ? `<div style="font-size:12px;color:var(--text-2);margin-top:6px;line-height:1.55">${esc(summary)}${summary.length >= 120 ? '…' : ''}</div>`
      : ''}
    <div style="font-size:var(--fs-xs);color:var(--text-3);font-family:var(--font-mono);margin-top:4px">${esc(statusLine)}</div>
  </div>`;

  return _toolWidget(
    'webfetch-widget',
    `<span class="widget-badge" style="background:var(--accent-dim);color:var(--accent);border:1px solid rgba(168,85,247,.2)">🌐 FETCH</span>`,
    domain || url,
    '✓ done',
    bodyHtml,
    { url, page_title: pageTitle, item_count: itemCount }
  );
}

// ── Bash Tool ─────────────────────────────────────────────────────────────
function renderBashTool(block, streaming) {
  const input = block.input || {};
  const desc  = input.description || input.command?.slice(0, 60) || 'bash';

  // Build command display from all sources
  let command = input.command || input.code || '';
  // Also check display_content json_block
  const tuDisp = block.display_content;
  if (tuDisp && tuDisp.type === 'json_block' && tuDisp.json_block) {
    try { command = JSON.parse(tuDisp.json_block).code || command; } catch {}
  }
  const replaceWhitespaceEscape = command.replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\r/g, '\r').replace(/\\s/g, ' ');
  command = replaceWhitespaceEscape || command;
  const shortCmd = command.trim().slice(0, 360);

  if (streaming && !block._result_parsed && !block._result_display) {
    return `<div class="widget-block bash-widget">
      <div class="widget-head">
        <span class="widget-badge" style="background:var(--green-dim);color:var(--green);border:1px solid rgba(74,222,128,.2)">💻 BASH</span>
        <span class="widget-title">${esc(desc)}</span>
        <span class="widget-status running">⟳ running</span>
      </div>
      <div class="widget-body">
        ${shortCmd ? `<div class="bash-command">$ ${esc(shortCmd)}${command.length > 360 ? '…' : ''}</div>` : ''}
        <div class="widget-streaming"><div class="think-pulse"></div><span>Running…</span></div>
      </div>
    </div>`;
  }

  // ── Extract stdout/stderr/returncode from all possible locations ──────────
  let stdout = '', stderr = '', retcode = null;

  function _parseBashResult(obj) {
    if (!obj || typeof obj !== 'object') return false;
    if (obj.stdout !== undefined || obj.returncode !== undefined) {
      stdout  = String(obj.stdout  || '');
      stderr  = String(obj.stderr  || '');
      retcode = obj.returncode ?? null;
      return true;
    }
    return false;
  }

  function _parseBashStr(s) {
    if (!s || typeof s !== 'string') return false;
    const t = s.trim();
    if (t.startsWith('{') || t.startsWith('[')) {
      try { return _parseBashResult(JSON.parse(t)); } catch {}
    }
    // Plain text output
    stdout = s;
    return true;
  }

  // Priority 1: _result_display json_block (tool_result display_content)
  const resDisp = block._result_display;
  if (!stdout && resDisp) {
    if (resDisp.type === 'json_block' && resDisp.json_block) {
      const jb = resDisp.json_block;
      _parseBashResult(typeof jb === 'string' ? JSON.parse(jb) : jb);
    } else if (resDisp.type === 'text' && resDisp.text) {
      _parseBashStr(resDisp.text);
    }
  }

  // Priority 2: _result_parsed items
  if (!stdout && block._result_parsed) {
    const items = Array.isArray(block._result_parsed)
      ? block._result_parsed
      : [block._result_parsed];
    for (const item of items) {
      if (!item) continue;
      if (typeof item === 'object' && !item.type) {
        if (_parseBashResult(item)) break;
      }
      if (item.type === 'text'       && _parseBashStr(item.text)) break;
      if (item.type === 'json_block') {
        try {
          const jb = typeof item.json_block === 'string'
            ? JSON.parse(item.json_block) : item.json_block;
          if (_parseBashResult(jb)) break;
        } catch {}
      }
    }
  }

  // Priority 3: _extractToolResult
  if (!stdout) {
    const { text: exText } = _extractToolResult(block);
    if (exText && typeof exText === 'object') _parseBashResult(exText);
    else if (typeof exText === 'string') _parseBashStr(exText);
  }

  // Priority 4: tool_use block display_content json_block
  if (!stdout && tuDisp && tuDisp.type === 'json_block' && tuDisp.json_block) {
    try {
      const jb = typeof tuDisp.json_block === 'string'
        ? JSON.parse(tuDisp.json_block) : tuDisp.json_block;
      _parseBashResult(jb);
    } catch {}
  }

  const statusIcon = retcode === 0    ? '✓ done'
    : retcode !== null                ? `✗ exit ${retcode}`
    :
'✓ done';

  const bodyHtml = `<div class="widget-body">
    ${shortCmd ? `<div class="bash-command">$ ${esc(shortCmd)}${command.length > 360 ? '…' : ''}</div>` : ''}
    ${stdout
      ? `<div class="bash-output">${esc(stdout)}</div>`
      : `<div style="font-size:var(--fs-sm);color:var(--text-3);font-family:var(--font-mono);padding:4px 0">Command executed${retcode !== null ? ` (exit ${retcode})` : ''}</div>`}
    ${stderr ? `<div class="bash-output" style="color:var(--red);margin-top:4px">${esc(stderr)}</div>` : ''}
  </div>`;

  return _toolWidget(
    'bash-widget',
    `<span class="widget-badge" style="background:var(--green-dim);color:var(--green);border:1px solid rgba(74,222,128,.2)">💻 BASH</span>`,
    desc, statusIcon, bodyHtml,
    { command, returncode: retcode, stdout: stdout.slice(0, 500), stderr: stderr.slice(0, 200) }
  );
}

// ── Create File ───────────────────────────────────────────────────────────
function renderCreateFileTool(block, streaming) {
  const input = block.input || {};
  const path  = input.path || 'file';
  const fname = path.split('/').pop() || path;
  const desc  = input.description || fname;

  // Show code from display_content (tool_use update) or _result_display (tool_result)
  // Try all sources in priority order
  let content = '', lang = '';

  const _tryCodeBlock = (src) => {
    if (!src) return false;
    const cb = src.type === 'json_block' ? src.json_block : null;
    if (!cb) return false;
    try {
      const p = typeof cb === 'string' ? JSON.parse(cb) : cb;
      if (p.code) { content = p.code; lang = p.language || ''; return true; }
    } catch {}
    return false;
  };

  _tryCodeBlock(block.display_content) ||
  _tryCodeBlock(block._result_display) ||
  // fallback: check input directly
  (() => { if (block.input?.file_text) { content = block.input.file_text; } })();

  const codeBlock = null;  // legacy ref — no longer needed

  if (streaming && !block._result_parsed && !codeBlock) {
    return `<div class="widget-block file-tool-widget">
      ${_toolHead('', '📝 CREATE', fname, '⟳ writing')}
      ${_streamingBody()}
    </div>`;
  }

  // Check result display for success message
  const resDisplay = block._result_display;
  const resText    = resDisplay?.type === 'text' ? resDisplay.text : '';

  // Syntax highlight the content
  let highlighted = '';
  if (content) {
    const validLang = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
    try { highlighted = hljs.highlight(content.slice(0,600), { language: validLang }).value; }
    catch { highlighted = esc(content.slice(0,600)); }
  }

  return `<div class="widget-block file-tool-widget">
    ${_toolHead('', '📝 CREATE', fname, resText ? '✓ created' : '✓ done')}
    <div class="widget-body">
      <div class="file-tool-path">${esc(path)}</div>
      ${highlighted
        ? `<div class="file-tool-content">
             <code class="hljs language-${esc(lang || 'plaintext')}">${highlighted}</code>
             ${content.length > 600 ? `<div style="font-size:var(--fs-xs);color:var(--text-3);font-family:var(--font-mono);padding-top:4px">… ${content.length - 600} more chars</div>` : ''}
           </div>`
        : resText ? `<div style="font-size:var(--fs-sm);color:var(--green);font-family:var(--font-mono)">${esc(resText)}</div>` : ''}
    </div>
  </div>`;
}

function renderViewTool(block, streaming) {
  const input = block.input || {};
  const path  = input.path || 'file';
  const fname = path.split('/').pop() || path;

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block file-tool-widget">
      ${_toolHead('', '👁 VIEW', fname, '⟳ reading')}
      ${_streamingBody()}
    </div>`;
  }

  // View result can be in _result_display (json_block) or _result_parsed
  const resDisplay = block._result_display;
  const codeBlock  = resDisplay?.type === 'json_block' ? resDisplay.json_block : null;

  let content = '', lang = '';
  if (codeBlock) {
    try {
      const parsed = typeof codeBlock === 'string' ? JSON.parse(codeBlock) : codeBlock;
      content = parsed.code || '';
      lang    = parsed.language || path.split('.').pop() || '';
    } catch {}
  }

  // Also try _result_parsed for line-numbered view output
  if (!content && block._result_parsed) {
    const items = Array.isArray(block._result_parsed) ? block._result_parsed : [];
    for (const item of items) {
      if (item?.type === 'text' && item.text) {
        content = item.text;
        break;
      }
    }
  }

  let highlighted = '';
  if (content) {
    const validLang = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
    try { highlighted = hljs.highlight(content.slice(0, 800), { language: validLang }).value; }
    catch { highlighted = esc(content.slice(0, 800)); }
  }

  // Fallback to text result
  const { text } = _extractToolResult(block);
  const rawText   = typeof text === 'string' ? text : '';

  return `<div class="widget-block file-tool-widget">
    ${_toolHead('', '👁 VIEW', fname, '✓ done')}
    <div class="widget-body">
      <div class="file-tool-path">${esc(path)}</div>
      ${highlighted
        ? `<div class="file-tool-content"><code class="hljs language-${esc(lang || 'plaintext')}">${highlighted}</code></div>`
        : rawText
          ? `<div class="file-tool-content">${esc(rawText.slice(0, 800))}${rawText.length > 800 ? '\n…' : ''}</div>`
          : '<div style="font-size:var(--fs-sm);color:var(--text-3);font-family:var(--font-mono)">File viewed</div>'}
    </div>
  </div>`;
}

function renderStrReplaceTool(block, streaming) {
  const input  = block.input || {};
  const path   = input.path || 'file';
  const fname  = path.split('/').pop() || path;
  const oldStr = input.old_str || '';
  const newStr = input.new_str || '';

  const resDisplay = block._result_display;
  const resText    = resDisplay?.type === 'text' ? resDisplay.text : null;
  // Also check display_content on the tool_use block itself for the description
  const tuDisplay  = block.display_content;
  const tuText     = tuDisplay?.type === 'text' ? tuDisplay.text : null;

  if (streaming && !block._result_parsed && !tuText) {
    return `<div class="widget-block file-tool-widget">
      ${_toolHead('', '✏ EDIT', fname, '⟳ editing')}
      ${_streamingBody()}
    </div>`;
  }

  return `<div class="widget-block file-tool-widget">
    ${_toolHead('', '✏ EDIT', fname, resText || '✓ done')}
    <div class="widget-body">
      <div class="file-tool-path">${esc(path)}</div>
      <div class="str-replace-diff">
        ${oldStr ? `<div class="str-replace-old">- ${esc(oldStr.slice(0,200))}${oldStr.length>200?'\n…':''}</div>` : ''}
        ${newStr ? `<div class="str-replace-new">+ ${esc(newStr.slice(0,200))}${newStr.length>200?'\n…':''}</div>` : ''}
      </div>
    </div>
  </div>`;
}

// ── MCP Registry ──────────────────────────────────────────────────────────
function renderMCPRegistryTool(block, streaming) {
  const input    = block.input || {};
  const keywords = (input.keywords || []).join(', ') || 'search';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block mcp-widget">
      ${_toolHead('', '🔌 MCP', keywords, '⟳ searching')}
      ${_streamingBody()}
    </div>`;
  }

  const { text } = _extractToolResult(block);
  const _mcpData = (typeof text === 'object' && text !== null) ? text : {};
  const items = _mcpData.connectors || _mcpData.results || _mcpData.packages
    || (Array.isArray(text) ? text : []);

  const itemsHtml = items.slice(0, 6).map(item => {
    const name = item.name || item.title || item.package_name || '?';
    const desc = item.description || item.summary || '';
    return `
      <div class="mcp-result-item">
        <div class="mcp-result-name">🔌 ${esc(name)}</div>
        ${desc ? `<div class="mcp-result-desc">${esc(desc)}</div>` : ''}
      </div>`;
  }).join('');

  return _toolWidget(
    'mcp-widget',
    `<span class="widget-badge" style="background:var(--accent-dim);color:var(--accent);border:1px solid rgba(168,85,247,.2)">🔌 MCP</span>`,
    keywords,
    '✓ done',
    `<div class="widget-body">
      ${itemsHtml || '<div style="font-size:12px;color:var(--text-3)">Registry searched</div>'}
    </div>`,
    block._result_parsed ? { raw: block._result_parsed } : null
  );
}

// ── Suggest Connectors ────────────────────────────────────────────────────
function renderSuggestConnectorsTool(block, streaming) {
  const input = block.input || {};
  const title = input.title || input.query || 'Connectors';

  if (streaming && !block._result_parsed) {
    return `<div class="widget-block mcp-widget">
      ${_toolHead('', '🔌 CONNECTORS', title, '⟳ suggesting')}
      ${_streamingBody()}
    </div>`;
  }

  const { text: _suggestText } = _extractToolResult(block);
  const _suggestData = (typeof _suggestText === 'object' && _suggestText !== null) ? _suggestText : {};
  const connectors = _suggestData.connectors || _suggestData.suggestions
    || (Array.isArray(_suggestText) ? _suggestText : []);

  const html = connectors.slice(0, 6).map(c => {
    const name = c.name || c.title || '?';
    const desc = c.description || '';
    return `
      <div class="mcp-result-item">
        <div class="mcp-result-name">⚡ ${esc(name)}</div>
        ${desc ? `<div class="mcp-result-desc">${esc(desc)}</div>` : ''}
      </div>`;
  }).join('');

  return _toolWidget(
    'mcp-widget',
    `<span class="widget-badge" style="background:var(--accent-dim);color:var(--accent);border:1px solid rgba(168,85,247,.2)">🔌 CONNECTORS</span>`,
    title,
    '✓ done',
    `<div class="widget-body">
      ${html || '<div style="font-size:12px;color:var(--text-3)">Connectors suggested</div>'}
    </div>`,
    block._result_parsed ? { raw: block._result_parsed } : null
  );
}

/* ═══════════════════════════════════════════
   BLOCK RENDERER
═══════════════════════════════════════════ */

function renderBlock(block, streaming, sender) {
  if (sender === undefined) sender = 'assistant';

  switch (block.type) {

    case 'text': {
      const cursor = streaming ? '<span class="scursor"></span>' : '';
      if (sender === 'human') {
        return `<div class="md"><p>${esc(block.text || '').replace(/\n/g,'<br>')}</p></div>`;
      }
      return `<div class="md">${marked.parse(block.text || '')}${cursor}</div>`;
    }

    case 'thinking': {
      const id     = 'tk_' + Math.random().toString(36).slice(2, 9);
      const text   = block.thinking || '';
      const words  = text.trim().split(/\s+/).filter(Boolean).length;
      const summ   = block.summaries?.map(s => s.summary).join(' · ') || 'Thinking…';
      const cursor = streaming ? '<span class="scursor"></span>' : '';
      const icon   = streaming ? '<div class="think-pulse"></div>' : '<span class="think-icon">🧠</span>';
      const open   = streaming ? 'open' : '';
      return `
        <div class="think-block">
          <div class="think-hd" onclick="toggleCollapse('${id}','chev_${id}')">
            ${icon}
            <span class="think-label">${esc(summ)}${cursor}</span>
            ${!streaming && words ? `<span class="think-count">${words} words</span>` : ''}
            <span class="think-chev ${open}" id="chev_${id}"></span>
          </div>
          <div class="think-body ${open}" id="${id}">${esc(text)}</div>
        </div>`;
    }

    case 'tool_use': {
      const _prov = (S.tabAccount?.provider || 'claude').toLowerCase();

      if (block.name === 'ask_user_input_v0')      return renderAskUserInputWidget(block, streaming);
      if (block.name === 'artifacts')              return _prov === 'claude' ? renderArtifactBlock(block, streaming) : '';
      if (block.name === 'present_files')          return _prov === 'claude' ? renderPresentFiles(block) : '';
      if (block.name === 'weather_fetch')          return renderWeatherTool(block, streaming);
      if (block.name === 'places_map_display_v0')  return renderMapTool(block, streaming);
      if (block.name === 'places_search')          return renderPlacesSearchTool(block, streaming);
      if (block.name === 'recipe_display_v0')      return renderRecipeTool(block, streaming);
      if (block.name === 'message_compose_v1')     return renderMessageComposeTool(block, streaming);
      if (block.name === 'fetch_sports_data')      return renderSportsTool(block, streaming);
      if (block.name === 'image_search')           return renderImageSearchTool(block, streaming);
      if (block.name === 'web_search')             return renderWebSearchTool(block, streaming);
      if (block.name === 'web_fetch')              return renderWebFetchTool(block, streaming);
      if (block.name === 'bash_tool')              return renderBashTool(block, streaming);
      if (block.name === 'create_file')            return renderCreateFileTool(block, streaming);
      if (block.name === 'str_replace')            return renderStrReplaceTool(block, streaming);
      if (block.name === 'view')                   return renderViewTool(block, streaming);
      if (block.name === 'search_mcp_registry')    return renderMCPRegistryTool(block, streaming);
      if (block.name === 'suggest_connectors')     return renderSuggestConnectorsTool(block, streaming);

      // Generic fallback
      const tuId     = 'tu_' + Math.random().toString(36).slice(2, 9);
      const inputObj = block.input || {};
      const inputStr = JSON.stringify(inputObj, null, 2);
      const stat     = streaming ? 'running' : 'done';
      const statTxt  = streaming ? '⟳ running' : '✓ done';
      const wid2     = _widgetId();
      const rawJson  = JSON.stringify({
        name:   block.name,
        input:  inputObj,
        result: block._result_parsed || null,
      }, null, 2);
      return `
        <div class="tool-block" id="${wid2}">
          <div class="tool-hd" onclick="toggleCollapse('${tuId}','tuc_${tuId}')">
            <span class="tool-badge call">TOOL</span>
            <span class="tool-name">${esc(block.name || 'tool')}</span>
            <span class="tool-status ${stat}">${statTxt}</span>
            <button class="tool-raw-btn"
                    onclick="event.stopPropagation();_toggleRaw('${wid2}')"
                    title="Raw data">{ }</button>
            <span class="tool-chev" id="tuc_${tuId}"></span>
          </div>
          <div class="tool-body" id="${tuId}">${esc(inputStr)}</div>
          <div class="tool-raw-panel" id="raw_${wid2}">
            <div class="tool-raw-content">${esc(rawJson)}</div>
          </div>
        </div>`;
    }

    case 'tool_result':
      // tool_result blocks are consumed by mergeToolResults() before rendering.
      // They should never reach here in normal flow, but render a minimal
      // collapsed view just in case (e.g. human messages that contain results).
      return '';

    case 'flowith_image': {
      const url = block.url || block.image_url || '';
      if (!url) return '';
      const safeUrl  = esc(url);
      const safeName = esc(url.split('/').pop().split('?')[0] || 'generated.png');
      return `<div class="flowith-chat-media">
        <div class="code-header" style="border-radius:var(--r-l) var(--r-l) 0 0">
          <span class="code-lang">🖼 GENERATED IMAGE</span>
          <div style="display:flex;gap:4px">
            <button class="code-copy" onclick="openInCanvas('${safeUrl}','${safeName}','image/png')">👁 Canvas</button>
            <a class="code-copy" href="${safeUrl}" download="${safeName}" style="text-decoration:none">⬇ Save</a>
          </div>
        </div>
        <img class="flowith-gen-img" src="${safeUrl}" alt="Generated image"
          onclick="openInCanvas('${safeUrl}','${safeName}','image/png')"
          onerror="this.outerHTML='<div class=\\'flowith-media-err\\'>⚠ Image failed to load — <a href=\\'${safeUrl}\\' target=\\'_blank\\'>open URL</a></div>'">
      </div>`;
    }

    case 'flowith_video': {
      const url = block.url || block.video_url || '';
      if (!url) return '';
      const safeUrl  = esc(url);
      const safeName = esc(url.split('/').pop().split('?')[0] || 'generated.mp4');
      return `<div class="flowith-chat-media">
        <div class="code-header" style="border-radius:var(--r-l) var(--r-l) 0 0">
          <span class="code-lang">🎬 GENERATED VIDEO</span>
          <div style="display:flex;gap:4px">
            <a class="code-copy" href="${safeUrl}" target="_blank" rel="noopener" style="text-decoration:none">↗ Open</a>
            <a class="code-copy" href="${safeUrl}" download="${safeName}" style="text-decoration:none">⬇ Save</a>
          </div>
        </div>
        <video class="flowith-gen-video" controls preload="metadata">
          <source src="${safeUrl}">
        </video>
      </div>`;
    }

    default:
      return '';
  }
}

/* ═══════════════════════════════════════════
   ARTIFACT RENDERING
═══════════════════════════════════════════ */
function renderArtifactBlock(block, streaming) {
  const input = block.input || {};
  const artifactType = input.type || '';
  const title  = input.title  || block.name || 'Artifact';
  const content = input.content || input.code || block.input_str || '';
  const language = input.language || '';
  const artId  = 'art_' + (block.id || Math.random().toString(36).slice(2, 9));

  let typeLabel = artifactType;
  if (artifactType.includes('react'))    typeLabel = 'React';
  else if (artifactType.includes('html')) typeLabel = 'HTML';
  else if (artifactType.includes('svg'))  typeLabel = 'SVG';
  else if (artifactType.includes('mermaid')) typeLabel = 'Mermaid';
  else if (language) typeLabel = language;

  const statusHtml = streaming
    ? `<span class="tool-status running">⟳ generating…</span>`
    : `<span class="tool-status done">✓ done</span>`;

  let previewHtml = '';

  if (!streaming && content) {
    if (artifactType.includes('html') || artifactType === 'text/html') {
      previewHtml = `
        <iframe class="artifact-preview" id="${artId}_iframe" sandbox="allow-scripts allow-same-origin"
          srcdoc="${content.replace(/"/g, '&quot;').replace(/'/g, '&#39;')}"></iframe>
        <div class="artifact-code" id="${artId}_code">${esc(content)}</div>`;
    } else if (artifactType === 'image/svg+xml' || content.trim().startsWith('<svg')) {
      previewHtml = `
        <div class="artifact-svg-wrap" id="${artId}_preview">${content}</div>
        <div class="artifact-code" id="${artId}_code">${esc(content)}</div>`;
    } else {
      const lang = language || (artifactType.includes('react') ? 'jsx' : (artifactType.includes('python') ? 'python' : 'text'));
      const validLang = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
      let highlighted = '';
      try { highlighted = hljs.highlight(content, {language: validLang}).value; }
      catch { highlighted = esc(content); }
      previewHtml = `
        <div class="artifact-code show" id="${artId}_code">
          <div class="code-header" style="margin:-14px -16px 12px;padding:7px 14px;background:rgba(255,255,255,0.02);border-bottom:1px solid var(--border-s)">
            <span class="code-lang">${esc(lang)}</span>
            <button class="code-copy" onclick="copyArtifactCode('${artId}',this)" style="color:var(--text-3)">⎘ Copy</button>
          </div>
          <code id="${artId}_hlcode" class="hljs language-${esc(validLang)}">${highlighted}</code>
        </div>`;
    }
  } else if (streaming) {
    previewHtml = `<div class="artifact-code show" id="${artId}_code" style="opacity:.5;font-size:var(--fs-sm);color:var(--text-3)">Generating…<span class="scursor"></span></div>`;
  }

  const showToggle = !streaming && content && (artifactType.includes('html') || artifactType === 'image/svg+xml' || content.trim().startsWith('<svg'));

  return `
    <div class="artifact-block" id="${artId}">
      <div class="artifact-hd">
        <span class="artifact-badge">ARTIFACT</span>
        <span class="artifact-title">${esc(title)}</span>
        <span class="artifact-type">${esc(typeLabel)}</span>
        ${statusHtml}
        ${showToggle ? `
        <div class="artifact-actions">
          <button class="artifact-btn active" id="${artId}_pbtn" onclick="toggleArtifactView('${artId}')">Preview</button>
          <button class="artifact-btn" id="${artId}_cbtn" onclick="toggleArtifactCode('${artId}')">Code</button>
        </div>` : ''}
        ${!streaming && content ? `<button class="artifact-btn" onclick="copyArtifactContent('${artId}')">⎘ Copy</button>` : ''}
        ${showToggle && !streaming ? `<button class="artifact-btn" style="color:var(--teal);border-color:rgba(56,189,248,.2)" onclick="openArtifactCanvas('${artId}','${title.replace(/'/g,'').replace(/"/g,'')}')">⊞ Canvas</button>` : ''}
      </div>
      ${previewHtml}
    </div>`;
}

function toggleArtifactView(artId) {
  const iframe   = document.getElementById(`${artId}_iframe`) || document.querySelector(`#${artId} .artifact-svg-wrap`);
  const code     = document.getElementById(`${artId}_code`);
  const pbtn     = document.getElementById(`${artId}_pbtn`);
  const cbtn     = document.getElementById(`${artId}_cbtn`);
  if (!iframe || !code) return;
  iframe.classList.remove('hide');
  code.classList.remove('show');
  pbtn?.classList.add('active');
  cbtn?.classList.remove('active');
}
function toggleArtifactCode(artId) {
  const iframe   = document.getElementById(`${artId}_iframe`) || document.querySelector(`#${artId} .artifact-svg-wrap`);
  const code     = document.getElementById(`${artId}_code`);
  const pbtn     = document.getElementById(`${artId}_pbtn`);
  const cbtn     = document.getElementById(`${artId}_cbtn`);
  if (!code) return;
  if (iframe) iframe.classList.add('hide');
  code.classList.add('show');
  pbtn?.classList.remove('active');
  cbtn?.classList.add('active');
}
function copyArtifactCode(artId, btn) {
  const code = document.getElementById(`${artId}_hlcode`);
  if (!code) return;
  navigator.clipboard.writeText(code.textContent).then(() => {
    btn.textContent = '✓ Copied'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '⎘ Copy'; btn.classList.remove('copied'); }, 2000);
  });
}
function copyArtifactContent(artId) {
  const code = document.getElementById(`${artId}_code`) || document.getElementById(`${artId}_hlcode`);
  if (!code) return;
  navigator.clipboard.writeText(code.textContent).then(() => toast('Copied!', 'ok'));
}

/* ═══════════════════════════════════════════
   PRESENT_FILES RENDERING
═══════════════════════════════════════════ */
function renderPresentFiles(block) {
  const input = block.input || {};
  const filepaths = input.filepaths || [];
  if (!filepaths.length) return '';

  const MIME = {jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',gif:'image/gif',webp:'image/webp',svg:'image/svg+xml',pdf:'application/pdf',html:'text/html',htm:'text/html',txt:'text/plain',js:'text/javascript',ts:'text/typescript',py:'text/x-python',json:'application/json',csv:'text/csv',md:'text/markdown',zip:'application/zip'};

  const rows = filepaths.map(fp => {
    const filename = fp.split('/').pop() || 'file';
    const ext  = filename.split('.').pop().toLowerCase();
    const mime = MIME[ext] || 'application/octet-stream';
    const isImg = mime.startsWith('image/');
    const href = S.convId ? dlUrl(S.convId, fp) : '#';
    const hrefInline = S.convId ? dlUrl(S.convId, fp, true) : '#';
    const ico  = fileIcon(mime);
    const escapedHref = href.replace(/'/g,"&#39;");
    const escapedName = esc(filename);
    const escapedMime = esc(mime);

    const mediaHtml = isImg
      ? `<img class="file-row-thumb" src="${href}" alt="${escapedName}" loading="lazy" onclick="openInCanvas('${escapedHref}','${escapedName}','${escapedMime}')" onerror="this.outerHTML='<div class=\'file-row-icon\'>${ico}</div>'">`
      : `<div class="file-row-icon">${ico}</div>`;

    return `<div class="file-row">
      ${mediaHtml}
      <div class="file-row-info">
        <div class="file-row-name" title="${escapedName}">${escapedName}</div>
        <div class="file-row-meta">${escapedMime}</div>
      </div>
      <div class="file-row-btns">
        <button class="file-row-btn canvas-b" onclick="openInCanvas('${escapedHref}','${escapedName}','${escapedMime}')">👁 Preview</button>
        <a class="file-row-btn dl-b" href="${href}" download="${escapedName}">⬇ Save</a>
      </div>
    </div>`;
  }).join('');

  const fpJson = JSON.stringify(filepaths).replace(/"/g,'&quot;');
  return `
    <div class="files-block">
      <div class="files-block-hd">
        <span class="files-block-badge">FILES</span>
        <span class="files-block-title">${filepaths.length} file${filepaths.length>1?'s':''}</span>
        <button class="files-block-dl-all" onclick='downloadFromPaths(${fpJson})'>⬇ All</button>
      </div>
      <div class="files-block-body">${rows}</div>
    </div>`;
}

function downloadFromPaths(filepaths) {
  for (const fp of filepaths) {
    const name = fp.split('/').pop() || 'file';
    if (!S.convId) continue;
    const url = dlUrl(S.convId, fp);
    const a = document.createElement('a'); a.href = url; a.download = name;
    a.style.display = 'none'; document.body.appendChild(a); a.click();
    setTimeout(() => a.remove(), 300);
  }
}

function toggleCollapse(bodyId, chevId) {
  document.getElementById(bodyId)?.classList.toggle('open');
  document.getElementById(chevId)?.classList.toggle('open');
}

/* ═══════════════════════════════════════════
   BRANCHING — REDESIGNED
═══════════════════════════════════════════ */

let _bpOpen = false;

function _setBranchPoint(uuid, label) {
  const inp     = document.getElementById('branchSel');
  const ROOT    = '00000000-0000-4000-8000-000000000000';
  const isRoot  = !uuid || uuid === ROOT;

  if (inp) inp.value = uuid || ROOT;

  const btn = document.getElementById('branchToggleBtn');
  if (btn) btn.classList.toggle('active', !isRoot);

  if (_bpOpen) _refreshBpHighlight();
}

function resetBranchPoint() {
    const ROOT = '00000000-0000-4000-8000-000000000000';
    const sel  = document.getElementById('branchSel');
    if (sel) sel.value = ROOT;  // buildBranchSel will advance to leaf
    buildBranchSel();
    closeBranchPicker();
    toast('Branch point cleared', 'info');
}

function toggleBranchRow() { toggleBranchPicker(); }  // compat shim

function toggleBranchPicker() {
  if (_bpOpen) closeBranchPicker();
  else         openBranchPicker();
}

function openBranchPicker() {
  const picker = document.getElementById('branchPicker');
  if (!picker) return;
  _bpOpen = true;
  picker.classList.remove('hidden');
  const srch = document.getElementById('bpSearch');
  if (srch) srch.value = '';
  _renderBpList('');
  setTimeout(() => document.getElementById('bpSearch')?.focus(), 50);
  setTimeout(() => {
    document.addEventListener('click', _bpOutside, { capture: true, once: true });
  }, 0);
}

function closeBranchPicker() {
  _bpOpen = false;
  document.getElementById('branchPicker')?.classList.add('hidden');
  document.removeEventListener('click', _bpOutside, { capture: true });
}

function _bpOutside(e) {
  const picker = document.getElementById('branchPicker');
  const btn    = document.getElementById('branchToggleBtn');
  if (picker && !picker.contains(e.target) && !btn?.contains(e.target)) {
    closeBranchPicker();
  } else if (_bpOpen) {
    setTimeout(() => {
      document.addEventListener('click', _bpOutside, { capture: true, once: true });
    }, 0);
  }
}

function _renderBpList(query) {
  const list = document.getElementById('bpList');
  if (!list) return;
  list.innerHTML = '';
  const curUuid = document.getElementById('branchSel')?.value || '';
  const ROOT    = '00000000-0000-4000-8000-000000000000';
  const q       = query.trim().toLowerCase();

  if (!q || 'root new thread'.includes(q)) {
    const rootEl = _makeBpItem(ROOT, 'root', '— new thread (root) —', '', curUuid === ROOT || !curUuid);
    rootEl.classList.add('bp-root');
    list.appendChild(rootEl);
  }

  const conv = S.convs[S.convId];
  if (!conv?.chat_messages) return;

  const msgs = buildChain(conv);
  for (const m of msgs) {
    const text = m.text || (m.content||[]).find(b=>b.type==='text')?.text || '';
    const preview = text.slice(0, 80).replace(/\n/g, ' ');
    if (q && !preview.toLowerCase().includes(q) && !m.sender.includes(q)) continue;
    const ts   = m.created_at ? fmtTime(m.created_at) : '';
    const item = _makeBpItem(m.uuid, m.sender, preview || m.uuid.slice(0,8)+'…', ts, m.uuid === curUuid);
    list.appendChild(item);
  }

  if (!list.children.length) {
    list.innerHTML = '<div style="padding:10px 12px;font-size:12px;color:var(--text-3)">No matches</div>';
  }
}

function _makeBpItem(uuid, sender, preview, ts, active) {
  const el = document.createElement('div');
  el.className = 'bp-item' + (active ? ' bp-active' : '');
  el.dataset.uuid = uuid;

  const badgeClass = sender === 'root' ? 'root' : sender === 'human' ? 'human' : 'assistant';
  const badgeTxt   = sender === 'root' ? 'ROOT' : sender === 'human' ? 'YOU' : 'AI';

  el.innerHTML = `
    <span class="bp-badge ${badgeClass}">${badgeTxt}</span>
    <span class="bp-preview" title="${esc(preview)}">${esc(preview)}</span>
    ${ts ? `<span class="bp-ts">${esc(ts)}</span>` : ''}
    <span class="bp-check">✓</span>`;

  el.addEventListener('click', ev => {
    ev.stopPropagation();
    const isRoot = uuid === '00000000-0000-4000-8000-000000000000';
    const label  = isRoot
      ? ''
      : `[${sender === 'human' ? 'You' : 'AI'}] ${preview.slice(0,55)}${preview.length>55?'…':''}`;
    _setBranchPoint(uuid, label);
    closeBranchPicker();
    document.getElementById('msgTa')?.focus();
  });
  return el;
}

function _refreshBpHighlight() {
  const curUuid = document.getElementById('branchSel')?.value || '';
  document.querySelectorAll('.bp-item').forEach(el => {
    el.classList.toggle('bp-active', el.dataset.uuid === curUuid);
  });
}

function filterBranchPicker(q) {
  _renderBpList(q);
}

function buildBranchSel() {
  const conv = S.convId ? S.convs[S.convId] : null;
  if (!conv?.chat_messages?.length) return;

  const { byUuid, leafUuids } = bexBuildTree(conv);

  if (!BEX.sendParentUuid || !byUuid[BEX.sendParentUuid]) {
    const leaf = BEX.viewLeafUuid && byUuid[BEX.viewLeafUuid]
      ? BEX.viewLeafUuid
      : (conv.current_leaf_message_uuid && byUuid[conv.current_leaf_message_uuid]
          ? conv.current_leaf_message_uuid
          : bexFindDeepestLeaf(leafUuids, byUuid));
    BEX.viewLeafUuid   = leaf;
    BEX.sendParentUuid = leaf;
    const sel = document.getElementById('branchSel');
    if (sel) sel.value = leaf || ROOT_UUID;
    _bexUpdatePill();
  }
}

// Compat shims for old callers
function openBranchOverlay()  { openBranchPicker();  }
function closeBranchOverlay() { closeBranchPicker(); }

// forkFromMsg — see canonical definition below

function toggleBranchRow() {
  S.branchVisible = !S.branchVisible;
  document.getElementById('branchRow').classList.toggle('hidden', !S.branchVisible);
  document.getElementById('branchToggleBtn').classList.toggle('active', S.branchVisible);
}

/* ═══════════════════════════════════════════
   FILE ATTACHMENT
═══════════════════════════════════════════ */
async function attachFiles(inp) {
  if (!inp.files?.length) return;
  if (!S.convId) { toast('Select a conversation first', 'err'); return; }
  for (const f of Array.from(inp.files)) await uploadSingleFile(f);
  inp.value = '';
}

async function uploadSingleFile(file) {
  if (!S.convId) { toast('Select a conversation first', 'err'); return; }
  const chipId = 'chip_' + Math.random().toString(36).slice(2, 9);
  const chip   = document.createElement('div');
  chip.className = 'att-chip uploading';
  chip.id = chipId;

  let thumbHtml = `<span>${fileIcon(file.type)}</span>`;
  if (file.type.startsWith('image/')) {
    const url = URL.createObjectURL(file);
    thumbHtml = `<img class="att-thumb" src="${url}" alt="">`;
  }

  chip.innerHTML = `
    ${thumbHtml}
    <span class="att-chip-name">${esc(file.name)}</span>
    <span class="att-chip-size">${fmtBytes(file.size)}</span>
    <div class="att-chip-prog"><div class="att-chip-prog-bar"></div></div>`;
  document.getElementById('attBar').appendChild(chip);

  const form = new FormData();
  form.append('file', file);

  const headers = {};
  const acctName = getTabAccountName();
  if (acctName) headers['X-Account-Name'] = acctName;
  const _uploadProv = getTabProvider();

  // Flowith: store image as data URL locally (no server upload endpoint)
  if (_uploadProv === 'flowith') {
    if (!file.type.startsWith('image/')) {
      document.getElementById(chipId)?.remove();
      toast('Flowith only supports image file attachments in chat', 'err');
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      const dataUrl = ev.target.result;
      document.getElementById(chipId)?.remove();
      const fakeRecord = {
        file_uuid:   '',
        _filename:   file.name,
        _mime:       file.type,
        _size:       file.size,
        url:         dataUrl,
        _previewUrl: dataUrl,
        _upload_ok:  true,
      };
      S.attached.push(fakeRecord);
      renderAttBar();
      toast(`Ready: ${file.name}`, 'ok');
    };
    reader.readAsDataURL(file);
    return;
  }

  try {
    const r = await fetch(`/api/conversations/${S.convId}/upload`, {
      method: 'POST',
      body: form,
      headers,
    });
    const d = await r.json();
    if (d.file_uuid || d._upload_ok) {
      if (!d.file_uuid && d.id) d.file_uuid = d.id;
      d._filename = d._filename || d.file_name || file.name;
      d._size     = d._size || file.size;
      d._mime     = d._mime || d.file_kind || file.type;
      S.attached.push(d);
      chip.remove();
      renderAttBar();
      toast(`Uploaded: ${file.name}`, 'ok');
      if (S.canvasOpen && S.canvasTab === 'files') renderCanvasFiles();
    } else {
      chip.remove();
      toast('Upload failed: ' + (d.error || JSON.stringify(d)), 'err');
    }
  } catch (e) {
    chip.remove();
    toast('Upload error: ' + e.message, 'err');
  }
}

function renderAttBar() {
  const bar = document.getElementById('attBar');
  bar.querySelectorAll('.att-chip:not(.uploading)').forEach(c => c.remove());
  S.attached.forEach((f, i) => {
    const name = f._filename || f.file_name || 'file';
    const mime = f._mime || f.file_kind || '';
    const size = fmtBytes(f._size || 0);
    const el = document.createElement('div');
    el.className = 'att-chip';

    let thumbHtml = `<span>${fileIcon(mime)}</span>`;
    if (mime.startsWith('image/') && f._previewUrl) {
      thumbHtml = `<img class="att-thumb" src="${f._previewUrl}" alt="">`;
    }

    el.innerHTML = `
      ${thumbHtml}
      <span class="att-chip-name">${esc(name)}</span>
      ${size ? `<span class="att-chip-size">${size}</span>` : ''}
      <button class="x" onclick="removeAtt(${i})">✕</button>`;
    bar.appendChild(el);
  });
}

function removeAtt(i) { S.attached.splice(i, 1); renderAttBar(); }

/* ═══════════════════════════════════════════
   EXISTING FILES POPUP  (📁 re-use files)
═══════════════════════════════════════════ */
async function toggleEfp(e) {
  e.stopPropagation();
  const popup = document.getElementById('efpPopup');
  const isHidden = popup.classList.contains('hidden');
  if (!isHidden) { popup.classList.add('hidden'); return; }

  popup.classList.remove('hidden');
  document.getElementById('efpSearchInp').value = '';
  document.getElementById('efpSearchInp').focus();

  setTimeout(() => {
    document.addEventListener('click', function _close(ev) {
      if (!document.getElementById('efpBtn')?.contains(ev.target)) {
        popup.classList.add('hidden');
        document.removeEventListener('click', _close);
      }
    });
  }, 0);

  await _loadEfpList();
}

async function _loadEfpList() {
  const list = document.getElementById('efpList');
  list.innerHTML = '<div class="efp-empty">Loading…</div>';
  if (!S.convId) { list.innerHTML = '<div class="efp-empty">No conversation selected.</div>'; return; }
  try {
    const uploads = await apiFetch(`/api/local/uploads/${S.convId}`);
    _renderEfpItems(uploads, '');
  } catch (err) {
    list.innerHTML = `<div class="efp-empty">Error: ${esc(err.message)}</div>`;
  }
}

function _renderEfpItems(uploads, query) {
  const list = document.getElementById('efpList');
  const usedUuids = new Set((S.attached || []).map(f => f.file_uuid));
  const filtered = query
    ? uploads.filter(u => (u.filename||'').toLowerCase().includes(query.toLowerCase()))
    : uploads;

  if (!filtered.length) {
    list.innerHTML = `<div class="efp-empty">${query ? 'No matches.' : 'No files uploaded yet.'}</div>`;
    return;
  }

  list.innerHTML = '';
  for (const u of filtered) {
    const mime  = u.content_type || '';
    const ico   = fileIcon(mime);
    const used  = usedUuids.has(u.file_uuid);
    const isImg = mime.startsWith('image/');
    const fileUrl = dlUrl(S.convId, u.filename || '');

    const thumbHtml = isImg
      ? `<img class="efp-thumb" src="${fileUrl}" alt="" onerror="this.outerHTML='<div class=\\'efp-icon\\'>${ico}</div>'">`
      : `<div class="efp-icon">${ico}</div>`;

    const el = document.createElement('div');
    el.className = `efp-item${used ? ' used' : ''}`;
    el.innerHTML = `
      ${thumbHtml}
      <span class="efp-name" title="${esc(u.filename)}">${esc(u.filename)}</span>
      <span class="efp-tag">${fmtBytes(u.size||0)}</span>
      <div class="efp-item-btns">
        ${!used ? `<button class="efp-item-btn attach" title="Attach" onclick="event.stopPropagation();reattachFile('${u.file_uuid}','${esc(u.filename||'')}','${esc(mime)}',${u.size||0})">＋</button>` : ''}
      </div>`;
    list.appendChild(el);
  }
  // store for filtering
  list._uploads = filtered;
}

function filterEfp(query) {
  if (!S.convId) return;
  apiFetch(`/api/local/uploads/${S.convId}`).then(uploads => _renderEfpItems(uploads, query)).catch(()=>{});
}

function reattachFile(fileUuid, filename, mime, size) {
  if (S.attached.find(f => f.file_uuid === fileUuid)) { toast('Already attached', 'info'); return; }
  S.attached.push({ file_uuid:fileUuid, _filename:filename, _mime:mime, _size:size });
  renderAttBar();
  document.getElementById('efpPopup').classList.add('hidden');
  toast(`Attached: ${filename}`, 'ok');
}

/* ═══════════════════════════════════════════
   CANVAS PANEL
═══════════════════════════════════════════ */
function toggleCanvas() {
  S.canvasOpen = !S.canvasOpen;
  const panel = document.getElementById('canvasPanel');
  const btn   = document.getElementById('canvasToggleBtn');
  panel.classList.toggle('collapsed', !S.canvasOpen);
  btn?.classList.toggle('active', S.canvasOpen);
  if (S.canvasOpen && S.canvasTab === 'files') renderCanvasFiles();
  _trackPanelBackdrop();
}

function switchCanvasTab(tab) {
  S.canvasTab = tab;
  // Tab buttons
  document.getElementById('ctab-preview').classList.toggle('active', tab === 'preview');
  document.getElementById('ctab-files').classList.toggle('active', tab === 'files');
  // Tab content
  const previewTab = document.getElementById('cvPreviewTab');
  const filesTab   = document.getElementById('cvFilesTab');
  if (previewTab) previewTab.style.display = tab === 'preview' ? 'flex' : 'none';
  if (filesTab)   { filesTab.style.display = tab === 'files'   ? 'flex' : 'none'; }
  if (tab === 'files') renderCanvasFiles();
}

function openInCanvas(url, name, mime) {
  // Ensure account_name is in the url
  const acct = getTabAccountName();
  if (acct && !url.includes('account_name=')) {
    url += (url.includes('?') ? '&' : '?') +
           'account_name=' + encodeURIComponent(acct);
  }

  // Ensure canvas panel is visible (may be display:none for non-claude providers)
  const _cvPanel = document.getElementById('canvasPanel');
  if (_cvPanel) _cvPanel.style.display = '';

  if (!S.canvasOpen) toggleCanvas();
  switchCanvasTab('preview');

  document.getElementById('cvPreviewEmpty').style.display    = 'none';
  document.getElementById('cvPreviewContent').style.display  = 'flex';
  document.getElementById('cvPreviewName').textContent = name;
  const dlBtn = document.getElementById('cvDlBtn');
  dlBtn.href = url; dlBtn.download = name;

  const copyBtn = document.getElementById('cvCopyBtn');
  copyBtn.dataset.canvasMime = mime || '';
  copyBtn.dataset.canvasUrl  = url || '';
  copyBtn.classList.remove('copied');
  copyBtn.textContent = '⎘ Copy';

  // hide all viewers
  const frame   = document.getElementById('cvFrame');
  const imgWrap = document.getElementById('cvImgWrap');
  const codeEl  = document.getElementById('cvCode');
  const pdfEl   = document.getElementById('cvPdf');
  [frame, imgWrap, codeEl, pdfEl].forEach(el => { if(el) el.style.display='none'; });

  const m = (mime||'').toLowerCase();
  if (m.startsWith('image/') || m.includes('pdf')) {
    // No meaningful text to copy for images/PDFs
    copyBtn.style.display = 'none';
  } else {
    copyBtn.style.display = '';
  }

  if (m.startsWith('image/')) {
    imgWrap.style.display = 'flex';
    document.getElementById('cvImg').src = url + (url.includes('?') ? '&' : '?') + 'inline=1';
  } else if (m.includes('pdf')) {
    pdfEl.style.display = 'block';
    pdfEl.src = url + (url.includes('?') ? '&' : '?') + 'inline=1';
  } else if (m.includes('html') || m.includes('htm')) {
    // Fetch as text and inject via srcdoc so Content-Disposition: attachment doesn't block rendering
    frame.style.display = 'block';
    frame.srcdoc = '';
    fetch(url)
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.text();
      })
      .then(html => { frame.srcdoc = html; })
      .catch(err => {
        frame.style.display = 'none';
        codeEl.style.display = 'block';
        codeEl.textContent = '(Could not load HTML: ' + err.message + ')';
      });
  } else {
    // fetch as text
    fetch(url).then(r => r.text()).then(txt => {
      codeEl.style.display = 'block';
      codeEl.textContent = txt;
    }).catch(() => {
      codeEl.style.display = 'block';
      codeEl.textContent = '(Could not load file)';
    });
  }
}

function openArtifactCanvas(artId, title) {
  const iframe  = document.getElementById(`${artId}_iframe`);
  const svgWrap = document.querySelector(`#${artId} .artifact-svg-wrap`);
  const codeEl  = document.getElementById(`${artId}_code`);

  if (!S.canvasOpen) toggleCanvas();
  switchCanvasTab('preview');

  document.getElementById('cvPreviewEmpty').style.display   = 'none';
  document.getElementById('cvPreviewContent').style.display = 'flex';
  document.getElementById('cvPreviewName').textContent = title || 'Artifact';
  document.getElementById('cvDlBtn').removeAttribute('href');

  const copyBtn = document.getElementById('cvCopyBtn');
  copyBtn.dataset.canvasMime = 'artifact';
  copyBtn.dataset.canvasUrl  = '';
  copyBtn.classList.remove('copied');
  copyBtn.textContent = '⎘ Copy';
  copyBtn.style.display = '';

  const frame   = document.getElementById('cvFrame');
  const imgWrap = document.getElementById('cvImgWrap');
  const cvCode  = document.getElementById('cvCode');
  const pdfEl   = document.getElementById('cvPdf');
  [frame, imgWrap, cvCode, pdfEl].forEach(el => { if(el) el.style.display='none'; });

  if (iframe) {
    // clone the srcdoc into the canvas iframe
    frame.style.display = 'block';
    frame.srcdoc = iframe.srcdoc || '';
  } else if (svgWrap) {
    cvCode.style.display = 'block';
    cvCode.innerHTML = svgWrap.innerHTML;
  } else if (codeEl) {
    cvCode.style.display = 'block';
    cvCode.textContent = codeEl.textContent;
  }
}

async function copyCanvasContent(btn) {
  const mime = btn.dataset.canvasMime || '';
  const url  = btn.dataset.canvasUrl  || '';

  let text = '';
  try {
    // Check for directly stored raw content first (set by openInCanvasRaw)
    if (btn._rawContent) {
      text = btn._rawContent;
    } else if (mime === 'artifact') {
      const frame  = document.getElementById('cvFrame');
      const codeEl = document.getElementById('cvCode');
      if (frame && frame.style.display !== 'none' && frame.srcdoc) {
        text = frame.srcdoc;
      } else if (codeEl && codeEl.style.display !== 'none') {
        text = codeEl.textContent;
      }
    } else if (mime.includes('html') || mime.includes('htm')) {
      const frame = document.getElementById('cvFrame');
      text = frame?.srcdoc || '';
      if (!text && url) text = await fetch(url).then(r => r.text());
    } else {
      const codeEl = document.getElementById('cvCode');
      if (codeEl && codeEl.style.display !== 'none') {
        text = codeEl.textContent;
      } else if (url) {
        text = await fetch(url).then(r => r.text());
      }
    }

    await navigator.clipboard.writeText(text);
    btn.textContent = '✓ Copied';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = '⎘ Copy';
      btn.classList.remove('copied');
    }, 2000);
  } catch (e) {
    toast('Copy failed: ' + e.message, 'err');
  }
}

async function renderCanvasFiles() {
  const list      = document.getElementById('cvFilesList');
  const countEl   = document.getElementById('cvFilesCount');
  if (!list) return;

  if (!S.convId) {
    list.innerHTML = '<div class="cv-files-empty">No conversation open.</div>';
    countEl.textContent = '';
    return;
  }

  list.innerHTML = '<div class="cv-files-empty">Loading…</div>';
  try {
    const uploads = await apiFetch(`/api/local/uploads/${S.convId}`);
    if (!uploads.length) {
      list.innerHTML = '<div class="cv-files-empty">No files uploaded in this conversation yet.</div>';
      countEl.textContent = '0 files';
      return;
    }
    countEl.textContent = `${uploads.length} file${uploads.length>1?'s':''}`;
    list.innerHTML = '<div class="cv-files-section">Uploaded Files</div>';
    for (const u of uploads) {
      const mime  = u.content_type || '';
      const ico   = fileIcon(mime);
      const isImg = mime.startsWith('image/');
      const fileUrl = dlUrl(S.convId, u.filename || '');
      const escapedDl   = esc(fileUrl);
      const escapedName = esc(u.filename||'file');
      const escapedMime = esc(mime);

      const thumbHtml = isImg
        ? `<img class="cfile-thumb" src="${escapedDl}" alt="" onerror="this.outerHTML='<div class=\\'cfile-icon\\'>${ico}</div>'">`
        : `<div class="cfile-icon">${ico}</div>`;

      const item = document.createElement('div');
      item.className = 'cfile-item';
      item.innerHTML = `
        ${thumbHtml}
        <div class="cfile-info">
          <div class="cfile-name" title="${escapedName}">${escapedName}</div>
          <div class="cfile-meta">${esc(mime||'—')} · ${fmtBytes(u.size||0)}</div>
        </div>
        <div class="cfile-btns">
          <button class="cfile-btn eye" onclick="openInCanvas('${escapedDl}','${escapedName}','${escapedMime}')" title="Preview">👁</button>
        </div>`;
      list.appendChild(item);
    }
  } catch (err) {
    list.innerHTML = `<div class="cv-files-empty">Error: ${esc(err.message)}</div>`;
  }
}

async function downloadAllFiles() {
  if (!S.convId) return;
  try {
    const uploads = await apiFetch(`/api/local/uploads/${S.convId}`);
    for (const u of uploads) {
      const url = dlUrl(S.convId, u.filename || '');
      const a = document.createElement('a');
      a.href = url; a.download = u.filename || 'file';
      a.style.display = 'none'; document.body.appendChild(a); a.click();
      setTimeout(() => a.remove(), 500);
      await new Promise(r => setTimeout(r, 300));
    }
  } catch(e) { toast('Download error: ' + e.message, 'err'); }
}

/* ═══════════════════════════════════════════
   CHAT SEARCH
═══════════════════════════════════════════ */
let _chatSearchMatches = [];
let _chatSearchIdx     = -1;

function toggleChatSearch() {
  const bar = document.getElementById('chatSearchBar');
  const inp = document.getElementById('chatSearchInp');
  const isHidden = bar.classList.contains('hidden');
  if (isHidden) {
    bar.classList.remove('hidden');
    document.getElementById('chatSearchBtn')?.classList.add('active');
    inp.focus();
  } else {
    bar.classList.add('hidden');
    document.getElementById('chatSearchBtn')?.classList.remove('active');
    inp.value = '';
    _clearChatHighlights();
    _chatSearchMatches = []; _chatSearchIdx = -1;
    document.getElementById('chatSearchCount').textContent = '';
  }
}

function runChatSearch(q) {
  S.chatQuery = q;
  _clearChatHighlights();
  _chatSearchMatches = [];
  _chatSearchIdx = -1;
  document.getElementById('chatSearchCount').textContent = '';
  if (!q.trim()) return;

  const msgs = document.querySelectorAll('#msgs .msg-body');
  msgs.forEach(msgEl => {
    _highlightTextIn(msgEl, q);
  });
  _chatSearchMatches = Array.from(document.querySelectorAll('.msg-highlight'));
  const n = _chatSearchMatches.length;
  if (n) {
    _chatSearchIdx = 0;
    _scrollToMatch(0);
    document.getElementById('chatSearchCount').textContent = `1 / ${n}`;
  } else {
    document.getElementById('chatSearchCount').textContent = '0 results';
  }
}

function chatSearchNav(dir) {
  const n = _chatSearchMatches.length;
  if (!n) return;
  _chatSearchMatches[_chatSearchIdx]?.classList.remove('current');
  _chatSearchIdx = (_chatSearchIdx + dir + n) % n;
  _scrollToMatch(_chatSearchIdx);
  document.getElementById('chatSearchCount').textContent = `${_chatSearchIdx+1} / ${n}`;
}

function chatSearchKey(e) {
  if (e.key === 'Enter') { e.shiftKey ? chatSearchNav(-1) : chatSearchNav(1); }
  if (e.key === 'Escape') toggleChatSearch();
}

function _scrollToMatch(idx) {
  const el = _chatSearchMatches[idx];
  if (!el) return;
  el.classList.add('current');
  el.scrollIntoView({ behavior:'smooth', block:'center' });
}

function _clearChatHighlights() {
  document.querySelectorAll('.msg-highlight').forEach(el => {
    const parent = el.parentNode;
    if (parent) { parent.replaceChild(document.createTextNode(el.textContent), el); parent.normalize(); }
  });
}

function _highlightTextIn(el, query) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  const lq = query.toLowerCase();
  for (const node of nodes) {
    const txt = node.textContent;
    const idx = txt.toLowerCase().indexOf(lq);
    if (idx < 0) continue;
    const span = document.createElement('mark');
    span.className = 'msg-highlight';
    span.textContent = txt.slice(idx, idx + query.length);
    const before = document.createTextNode(txt.slice(0, idx));
    const after  = document.createTextNode(txt.slice(idx + query.length));
    const parent = node.parentNode;
    parent.insertBefore(before, node);
    parent.insertBefore(span, node);
    parent.insertBefore(after, node);
    parent.removeChild(node);
  }
}


let streamBlocks = {};

async function doSend() {
  if (S.streaming) {
    await apiFetchRaw(`/api/conversations/${S.convId}/stop`, { method: 'POST' });
    return;
  }

  const ta     = document.getElementById('msgTa');
  const prompt = ta.value.trim();
  if (!prompt && !S.attached.length) return;
  if (!S.convId)    { toast('No conversation selected', 'err'); return; }
  if (!S.configured){ toast('Not configured', 'err'); openSettings(); return; }

  const _tabProv   = (S.tabAccount?.provider || 'claude').toLowerCase();
  const _supBranch = S.tabAccount?._supBranching !== false &&
                     (_tabProv === 'claude' || _tabProv === 'flowith' || _tabProv === 'chatwithai');

  let parentUuid;
  if (_supBranch) {
    // Use explicit fork point if set, else current view leaf
    parentUuid = BEX.sendParentUuid
      || document.getElementById('branchSel').value
      || ROOT_UUID;
    BEX.sendParentUuid = null; // consume it
  } else {
    const conv = S.convs[S.convId];
    const msgs = conv?.chat_messages || [];
    if (msgs.length > 0) {
      const chainMsgs = buildChain(conv);
      parentUuid = chainMsgs.length > 0
        ? chainMsgs[chainMsgs.length - 1].uuid
        : ROOT_UUID;
    } else {
      parentUuid = ROOT_UUID;
    }
  }

  const model      = ddGetValue(document.getElementById('modelSel'));

  const active = S.accounts.find(a => a.active);
  const activeProvider = (active?.provider || 'claude').toLowerCase();

  const fileRefs = (activeProvider === 'chatwithai' || activeProvider === 'oneminai')
    ? S.attached.map(f => ({ file_uuid: f.file_uuid, file_id: f.file_id || f.file_uuid, _filename: f._filename }))
    : activeProvider === 'flowith'
      ? S.attached.map(f => ({
          file_uuid: f.file_uuid || '',
          url:       f.url || f._previewUrl || '',
          mime:      f._mime || f.file_kind || '',
          _mime:     f._mime || f.file_kind || '',
          _filename: f._filename || '',
        }))
      : S.attached.map(f => ({
          file_uuid: f.file_uuid,
          file_name: f._filename || f.file_name || '',
          file_kind: f._mime     || f.file_kind || '',
          path:      f.path      || ''
        }));

  const conv      = S.convs[S.convId];
  const humanUuid = uuid4();
  const humanMsg  = {
    uuid: humanUuid, sender: 'human',
    content: [{ type:'text', text:prompt }], text: prompt,
    files_v2: S.attached.map(f => ({
      file_name: f._filename || f.file_name || 'file',
      file_uuid: f.file_uuid,
      file_kind: f._mime || f.file_kind || ''
    })),
    parent_message_uuid: parentUuid,
    created_at: new Date().toISOString(),
    index: conv.chat_messages?.length || 0
  };
  if (!conv.chat_messages) conv.chat_messages = [];
  conv.chat_messages.push(humanMsg);
  conv.current_leaf_message_uuid = humanUuid;

  const asstUuid = uuid4();
  const asstMsg  = {
    uuid: asstUuid, 
    sender: 'assistant', 
    content: [], 
    text: '',
    parent_message_uuid: humanUuid,
    created_at: new Date().toISOString(), index: conv.chat_messages.length
  };
  conv.chat_messages.push(asstMsg);
  conv.current_leaf_message_uuid = asstUuid;

  // Sync branch state so the next send knows we're on the new leaf
  const _bsel = document.getElementById('branchSel');
  if (_bsel) _bsel.value = asstUuid;
  if (typeof BEX !== 'undefined') {
    BEX.viewLeafUuid   = asstUuid;
    BEX.sendParentUuid = asstUuid;
  }

  renderMsgs(); buildBranchSel();
  ta.value = ''; resizeTa(ta); updateCount(ta);
  S.attached = []; renderAttBar();

  S.streaming = true; streamBlocks = {};
  setSendBtn(true);
  // Close branch overlay if open
  closeBranchOverlay();

  const box = document.getElementById('msgs');
  let finalRealUuid = asstUuid;
  const msgBodyEl = () => document.querySelector(`.msg[data-uuid="${asstUuid}"] .msg-body`);

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3600000); // 1 hour timeout safeguard

    const resp = await apiFetchRaw(`/api/conversations/${S.convId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt, model,
        parent_message_uuid: parentUuid,
        files: fileRefs,
        locale: 'en-US',
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      }),
      signal: controller.signal
    });

    clearTimeout(timer);

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === '[DONE]') continue;
        try {
          const ev = JSON.parse(raw);
          handleStreamEv(ev, asstMsg, msgBodyEl);
          if (ev.type === 'message_start' && ev.message?.uuid) {
            finalRealUuid = ev.message.uuid;
          }
          if (ev.type === 'message_limit') {
            updateQuotaFromStream(ev.message_limit);
          }
        } catch {}
      }
      if (box) box.scrollTop = box.scrollHeight;
    }

    if (asstMsg.content.length) {
      contentCache[finalRealUuid] = [...asstMsg.content];
      contentCache[asstUuid]      = [...asstMsg.content];
    }

    await fetchConvMeta(S.convId);
    renderMsgs(); buildBranchSel();
    renderSidebar();   // ← add this
    if (S.canvasOpen && S.canvasTab === 'files') renderCanvasFiles();
    if (getTabProvider() === 'oneminai') fetchQuota(); 

  } catch (err) {
    toast('Stream error: ' + err.message, 'err');
    conv.chat_messages = conv.chat_messages.filter(m => m.uuid !== asstUuid);
    conv.current_leaf_message_uuid = humanUuid;
    // Restore branch state to the human message (last valid in chain)
    const _errSel = document.getElementById('branchSel');
    if (_errSel) _errSel.value = humanUuid;
    if (typeof BEX !== 'undefined') {
      BEX.viewLeafUuid   = humanUuid;
      BEX.sendParentUuid = humanUuid;
    }
    renderMsgs();
  } finally {
    S.streaming = false;
    setSendBtn(false);

    // Advance BEX to the new leaf after streaming completes
    const _postConv = S.convId ? S.convs[S.convId] : null;
    if (_postConv?.chat_messages?.length) {
      const { byUuid, leafUuids } = bexBuildTree(_postConv);
      const newLeaf = _postConv.current_leaf_message_uuid && byUuid[_postConv.current_leaf_message_uuid]
        ? _postConv.current_leaf_message_uuid
        : bexFindDeepestLeaf(leafUuids, byUuid);
      BEX.viewLeafUuid   = newLeaf;
      BEX.sendParentUuid = null;
      const sel2 = document.getElementById('branchSel');
      if (sel2) sel2.value = newLeaf || ROOT_UUID;
      _bexUpdatePill();
      if (BEX.open) bexRebuild();
    }
  }
}

function mergeToolResults(contentBlocks) {
  if (!contentBlocks || !contentBlocks.length) return contentBlocks;

  // Index tool_use blocks by id
  const tuById = {};
  for (const b of contentBlocks) {
    if (b.type === 'tool_use' && b.id) tuById[b.id] = b;
  }

  for (const b of contentBlocks) {
    if (b.type !== 'tool_result') continue;

    const tu = tuById[b.tool_use_id || b.id];
    if (!tu) continue;

    // Already merged (streaming path sets _result_parsed)
    if (tu._result_parsed !== undefined) continue;

    // b.content is the tool_result payload — array of {type,text} or plain string
    const raw = b.content;
    if (!raw) { tu._result_parsed = []; continue; }

    // Normalise to array of items
    const items = Array.isArray(raw)
      ? raw
      : (typeof raw === 'string'
          ? [{ type: 'text', text: raw }]
          : [raw]);

    // Try to parse each text item as JSON so _extractToolResult can handle it
    const parsed = items.map(item => {
      if (!item || item.type !== 'text') return item;
      const t = (item.text || '').trim();
      if (t.startsWith('{') || t.startsWith('[')) {
        try { return { type: 'text', text: item.text, _parsed: JSON.parse(t) }; }
        catch {}
      }
      return item;
    });

    tu._result_parsed  = parsed;
    tu._result_display = b.display_content || null;
  }

  return contentBlocks;
}

function _extractToolResult(block) {
  const parsed  = block._result_parsed;
  const display = block._result_display || null;

  if (!parsed) return { text: null, images: [], gallery: null, display };

  const items = Array.isArray(parsed) ? parsed : [parsed];

  let text    = null;
  let gallery = null;
  const knowledgeItems = [];

  for (const item of items) {
    if (!item || typeof item !== 'object') continue;

    switch (item.type) {
      case 'text': {
        // Fast path: mergeToolResults already parsed the JSON
        if (item._parsed !== undefined) {
          if (text === null) {
            text = item._parsed;
          } else if (typeof text === 'object' && typeof item._parsed === 'object'
                     && !Array.isArray(text) && !Array.isArray(item._parsed)) {
            Object.assign(text, item._parsed);
          }
          break;
        }
        const raw = item.text || '';
        if (!raw) break;
        try {
          const inner = JSON.parse(raw);
          if (text === null) text = inner;
          else if (typeof text === 'object' && typeof inner === 'object'
                   && !Array.isArray(text)) Object.assign(text, inner);
        } catch {
          if (text === null) text = raw;
        }
        break;
      }
      case 'image_gallery':
        if (item.images && item.images.length) gallery = item.images;
        break;
      case 'knowledge':
        knowledgeItems.push(item);
        break;
      case 'local_resource':
        if (!text || typeof text !== 'object') text = {};
        if (typeof text === 'object') text._local_resource = item;
        break;
      default:
        break;
    }
  }

  // display_content json_block fallback
  if (!text && display && display.type === 'json_block' && display.json_block) {
    try {
      const j = typeof display.json_block === 'string'
        ? JSON.parse(display.json_block)
        : display.json_block;
      text = j;
    } catch {}
  }

  if (knowledgeItems.length > 0) {
    if (text === null || typeof text === 'string') text = knowledgeItems;
    else if (typeof text === 'object') text._knowledge = knowledgeItems;
  }

  return { text, images: [], gallery, display };
}

function handleStreamEv(ev, asstMsg, bodyElFn) {
  switch (ev.type) {
    case 'message_start':
      streamBlocks = {}; asstMsg.content = [];
      if (ev.message?.uuid) asstMsg.uuid = ev.message.uuid;
      break;

    case 'content_block_start': {
      const b = ev.content_block;
      streamBlocks[ev.index] = {
        ...b,
        text:            b.text            || '',
        thinking:        b.thinking        || '',
        input_str:       '',
        // tool_result fields
        tool_use_id:     b.tool_use_id     || '',
        // capture display_content if present on the block itself
        display_content: b.display_content || null,
      };
      // If this is a tool_use block, immediately register it in asstMsg.content
      // so tool_result merges can find it even if content_block_stop hasn't fired yet
      if (b.type === 'tool_use' && b.id) {
        const existing = asstMsg.content.find(c => c.type === 'tool_use' && c.id === b.id);
        if (!existing) {
          asstMsg.content.push(streamBlocks[ev.index]);
        }
      }
      break;
    }

    case 'content_block_delta': {
      if (!streamBlocks[ev.index]) {
        const dtype = ev.delta?.type === 'thinking_delta' ? 'thinking' : 'text';
        streamBlocks[ev.index] = { type: dtype, text:'', thinking:'', input_str:'' };
      }
      const d = ev.delta;
      if (d.type === 'text_delta')
        streamBlocks[ev.index].text += d.text;
      else if (d.type === 'thinking_delta') {
        streamBlocks[ev.index].type     = 'thinking';
        streamBlocks[ev.index].thinking += d.thinking;
      }
      else if (d.type === 'input_json_delta') {
        streamBlocks[ev.index].input_str = (streamBlocks[ev.index].input_str||'') + d.partial_json;
      }
      // In content_block_delta, add:
      else if (d.type === 'tool_use_block_update_delta') {
        if (!streamBlocks[ev.index]) {
          streamBlocks[ev.index] = { type: 'tool_use', input_str: '', text: '', thinking: '' };
        }
        if (d.message)         streamBlocks[ev.index].message         = d.message;
        if (d.display_content) streamBlocks[ev.index].display_content = d.display_content;
        updateStreamDisplay(asstMsg, bodyElFn);
      }
      else if (d.type === 'citation_start_delta') {
        // Store open citation — text between start and end should be linked
        if (!streamBlocks[ev.index]) streamBlocks[ev.index] = { type: 'text', text: '', thinking: '', input_str: '' };
        streamBlocks[ev.index]._openCitation = d.citation;
      }

      else if (d.type === 'citation_end_delta') {
        if (streamBlocks[ev.index]) {
          streamBlocks[ev.index]._openCitation = null;
        }
      }
      break;
    }

    case 'content_block_stop': {
      const b = streamBlocks[ev.index];
      if (b) {
        // Parse accumulated JSON input
        if (b.input_str) {
          try { b.input = JSON.parse(b.input_str); } catch {}
        }

        if (b.type === 'tool_result') {
          // Find the matching tool_use by tool_use_id
          const tuId = b.tool_use_id || '';

          // Helper: merge result data onto a tool_use block
          const mergeResult = (tu) => {
            if (!tu) return;
            // _result_parsed: the parsed array from the tool_result input_json_delta
            tu._result_parsed  = Array.isArray(b.input) ? b.input
                               : (b.input != null ? [b.input] : null);
            // _result_display: the display_content from the tool_result block start
            tu._result_display = b.display_content || null;
          };

          // 1. Check streamBlocks (may still be open)
          let found = false;
          for (const sb of Object.values(streamBlocks)) {
            if (sb.type === 'tool_use' && sb.id === tuId) {
              mergeResult(sb);
              found = true;
              break;
            }
          }
          // 2. Check asstMsg.content (already stopped / pre-registered)
          if (!found || true) {  // always sync both to keep in-sync
            for (const cb of asstMsg.content) {
              if (cb.type === 'tool_use' && cb.id === tuId) {
                mergeResult(cb);
                found = true;
                break;
              }
            }
          }

          // Never push tool_result blocks to content — they are consumed by merging
        } else if (b.type === 'tool_use') {
          // Update the pre-registered entry rather than pushing a duplicate
          const existing = asstMsg.content.find(c => c.type === 'tool_use' && c.id === b.id);
          if (existing) {
            Object.assign(existing, b);
          } else {
            asstMsg.content.push({...b});
          }
        } else {
          asstMsg.content.push({...b});
        }
      }
      break;
    }

    case 'flowith_image': {
      asstMsg.content = [{ type: 'flowith_image', url: ev.image_url }];
      updateStreamDisplay(asstMsg, bodyElFn);
      return;
    }

    case 'flowith_video': {
      asstMsg.content = [{ type: 'flowith_video', url: ev.video_url }];
      updateStreamDisplay(asstMsg, bodyElFn);
      return;
    }

    case 'message_delta':
      if (ev.delta?.stop_reason) asstMsg.stop_reason = ev.delta.stop_reason;
      break;

    case 'message_stop':
      break;

    case 'message_limit':
      updateQuotaFromStream(ev.message_limit);
      return;

    case 'error': {
      const errEl  = bodyElFn();
      const errType = ev.error?.type || '';

      // Auto-refresh 1min.AI token on auth errors
      if (errType === 'authentication_error' && getTabProvider() === 'oneminai') {
        _oneminaiAutoRefresh().then(ok => {
          if (ok) toast('Token refreshed — please resend your message', 'ok');
          else    toast('1min.AI auth failed — check your API key in Settings', 'err');
        });
      }

      let displayMsg = ev.error?.message || JSON.stringify(ev.error || ev);

      if (errType === 'rate_limit_error') {
        let inner = {};
        try { inner = JSON.parse(displayMsg); } catch {}

        const wins        = inner.windows || {};
        const STATUS_RANK = { exceeded_limit: 3, approaching_limit: 2, within_limit: 1 };
        const WIN_LABELS  = { '5h': '5-hour', '1h': '1-hour', '7d': '7-day', '1d': '1-day', '30d': '30-day' };

        // Update quota cache from the error payload so sidebar refreshes
        if (Object.keys(wins).length) {
          const name = getTabAccountName();
          if (name) {
            _cacheClaude(name, inner);
            _renderSidebarBar();
            renderAccountMenu();
          }
        }

        const parts = Object.entries(wins)
          .map(([k, w]) => {
            if (!w) return null;
            const pct   = Math.round((w.utilization ?? 0) * 100);
            const lbl   = WIN_LABELS[k] || k;
            const st    = w.status === 'exceeded_limit'
              ? 'exceeded'
              : w.status === 'approaching_limit'
                ? 'nearing limit'
                : 'ok';
            let reset = '';
            if (w.resets_at) {
              const diff = w.resets_at * 1000 - Date.now();
              if (diff > 0) {
                const hrs  = Math.floor(diff / 3_600_000);
                const mins = Math.floor((diff % 3_600_000) / 60_000);
                reset = `, resets in ${hrs > 0 ? hrs + 'h ' : ''}${mins}m`;
              }
            }
            return `${lbl}: ${pct}% (${st}${reset})`;
          })
          .filter(Boolean);

        displayMsg = parts.length
          ? `Rate limit reached — ${parts.join(' · ')}`
          : 'Rate limit reached';
      }

      if (errEl) {
        const errDiv = document.createElement('div');
        errDiv.style.cssText = 'color:var(--red);font-size:var(--fs-md);padding:6px 0;line-height:1.6';
        errDiv.innerHTML = `⚠ ${esc(displayMsg)}`;
        errEl.innerHTML = '';
        errEl.appendChild(errDiv);
      }
      return;
    }

    case 'cloudflare_challenge': {
      beginCF();
      const errEl = bodyElFn();
      if (errEl) {
        const d = document.createElement('div');
        d.style.cssText = 'color:var(--oneminai);font-size:var(--fs-md);padding:6px 0';
        d.textContent = '⚠ Cloudflare challenge — complete the check in the overlay, then resend.';
        errEl.innerHTML = '';
        errEl.appendChild(d);
      }
      return;
    }

    case 'ping':
      return;
  }

  updateStreamDisplay(asstMsg, bodyElFn);
}

function updateStreamDisplay(asstMsg, bodyElFn) {
  const el = bodyElFn();
  if (!el) return;

  let html = '';
  // Render finalised content blocks (tool_use with results merged)
  for (const b of asstMsg.content) {
    if (b.type === 'tool_result') continue;  // never render tool_result blocks directly
    html += renderBlock(b, false, asstMsg.sender || 'assistant');
  }

  // Render still-streaming blocks that haven't been added to asstMsg.content yet
  const contentUuids = new Set(asstMsg.content.map(b => b.id || b.uuid || '').filter(Boolean));
  const maxIdx = Object.keys(streamBlocks).length
    ? Math.max(...Object.keys(streamBlocks).map(Number))
    : -1;

  for (let i = 0; i <= maxIdx; i++) {
    const b = streamBlocks[i];
    if (!b) continue;
    if (b.type === 'tool_result') continue;  // skip tool_result
    // Skip if already rendered via asstMsg.content
    if (b.type === 'tool_use' && b.id && contentUuids.has(b.id)) continue;
    // Skip pure text/thinking blocks already in asstMsg.content
    if (b.type !== 'tool_use' && i < asstMsg.content.length) continue;
    html += renderBlock(b, true);
  }

  if (!html) {
    html = '<div class="typing"><div class="tdot"></div><div class="tdot"></div><div class="tdot"></div></div>';
  }
  el.innerHTML = html;
}

function setSendBtn(streaming) {
  const btn = document.getElementById('sendBtn');
  btn.textContent = streaming ? '■' : '↑';
  btn.classList.toggle('stop', streaming);
}

/* ═══════════════════════════════════════════
   SETTINGS — ACCOUNT-WIDE THINKING
═══════════════════════════════════════════ */
async function setAcctThink(mode) {
  const r = await apiFetch('/api/settings', {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ paprika_mode: mode })
  });
  toast(r.success ? `Account thinking: ${mode || 'off'}` : 'Failed: '+(r.error||''), r.success?'ok':'err');
}

/* ═══════════════════════════════════════════
   OVERLAY
═══════════════════════════════════════════ */
function openOverlay(id)  { document.getElementById(id).classList.add('open'); }
function closeOverlay(id) { document.getElementById(id).classList.remove('open'); }
document.querySelectorAll('.overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) o.classList.remove('open'); });
});

// Close polling panel on outside click
document.addEventListener('click', e => {
  const panel = document.getElementById('pollingPanel');
  const btn   = document.getElementById('pollingConfigBtn');
  if (!panel || panel.style.display === 'none') return;
  if (!panel.contains(e.target) && e.target !== btn) closePollingPanel();
}, true);

/* ═══════════════════════════════════════════
   INPUT HELPERS
═══════════════════════════════════════════ */
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
}
function resizeTa(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 220) + 'px';
}
function updateCount(el) {
  document.getElementById('charCount').textContent = el.value.length.toLocaleString();
}

/* ═══════════════════════════════════════════
   TOAST
═══════════════════════════════════════════ */
function toast(msg, type = 'info') {
  const box = document.getElementById('toasts');
  const el  = document.createElement('div');
  const ico = type === 'ok' ? '✓' : type === 'err' ? '✕' : 'ℹ';
  el.className = `toast ${type}`;
  el.innerHTML = `<span style="opacity:.5">${ico}</span><span>${esc(msg)}</span>`;
  box.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// Copy message content with formatting preserved

function copyMsgContent(uuid, btn) {
  // Try to get text from the md-content-wrap (includes thinking text)
  const contentWrap = document.querySelector(
    `.msg[data-uuid="${uuid}"] .md-content-wrap`
  );
  const el = contentWrap || document.querySelector(
    `.msg[data-uuid="${uuid}"] .msg-body`
  );
  if (!el) return;
  
  // Collect text from all relevant blocks
  const parts = [];
  
  // Thinking blocks
  el.querySelectorAll('.think-body').forEach(tb => {
    const thinking = tb.textContent.trim();
    if (thinking) parts.push(`<thinking>\n${thinking}\n</thinking>`);
  });
  
  // Main text content
  el.querySelectorAll('.md').forEach(md => {
    const text = md.innerText.trim();
    if (text) parts.push(text);
  });
  
  const text = parts.join('\n\n') || el.innerText.trim();
  
  navigator.clipboard.writeText(text).then(() => {
    btn.innerHTML = '<span>✓</span><span>Copied</span>';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.innerHTML = '<span>⎘</span><span>Copy</span>';
      btn.classList.remove('copied');
    }, 2000);
  });
}

// Copy as raw markdown
function copyMsgAsMarkdown(uuid, btn) {
  const conv = S.convs[S.convId];
  if (!conv) return;
  
  const msg = (conv.chat_messages || []).find(m => m.uuid === uuid);
  if (!msg) return;
  
  // Extract markdown from message
  let markdown = '';
  if (msg.content && msg.content.length) {
    for (const block of msg.content) {
      if (block.type === 'text') {
        markdown += block.text || '';
      }
    }
  } else {
    markdown = msg.text || '';
  }
  
  navigator.clipboard.writeText(markdown).then(() => {
    btn.innerHTML = '<span>✓</span><span>Copied MD</span>';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.innerHTML = '<span>📝</span><span>Copy MD</span>';
      btn.classList.remove('copied');
    }, 2000);
  });
}

// Regenerate from a specific assistant message — works for Claude + Flowith
function regenerateMsg(uuid) {
  const conv = S.convs[S.convId];
  if (!conv) return;

  const msg = (conv.chat_messages || []).find(m => m.uuid === uuid);
  if (!msg || msg.sender !== 'assistant') return;

  // Find the parent human message
  const parentMsg = (conv.chat_messages || []).find(
    m => m.uuid === msg.parent_message_uuid
  );
  if (!parentMsg) return;

  const text       = parentMsg.text
    || (parentMsg.content || []).find(b => b.type === 'text')?.text || '';
  const grandParent = parentMsg.parent_message_uuid
    || '00000000-0000-4000-8000-000000000000';

  const _supBranch = S.tabAccount?._supBranching !== false;
  if (_supBranch) {
    _setBranchPoint(grandParent, '— regenerating from parent —');
    if (!BEX.open) toggleBranchExplorer();
  }

  // Reattach files
  S.attached = [];
  if (parentMsg.files_v2?.length) {
    for (const f of parentMsg.files_v2) {
      S.attached.push({
        file_uuid: f.file_uuid,
        _filename: f.file_name || f.filename || 'file',
        _mime:     f.file_kind || f.content_type || '',
        _size:     f.file_size || 0,
      });
    }
    renderAttBar();
  }

  const ta = document.getElementById('msgTa');
  ta.value = text;
  resizeTa(ta);
  updateCount(ta);
  ta.focus();
  toast('Ready to regenerate — press ↵ to send', 'info');
}

// Fork conversation from a message
function forkFromMsg(uuid) {
  const conv = S.convs[S.convId];
  if (!conv) return;

  const msg     = (conv.chat_messages || []).find(m => m.uuid === uuid);
  const preview = msg
    ? `[${msg.sender}] ${(msg.text || '').slice(0, 55).replace(/\n/g,' ')}`
    : uuid.slice(0, 8) + '…';

  _setBranchPoint(uuid, preview);
  if (!BEX.open) toggleBranchExplorer();
  document.getElementById('msgTa').focus();
  toast('Branch point set — type your message and send', 'info');
}

function toggleCodeBlock(wrapperId, btn) {
  const wrapper = document.getElementById(wrapperId);
  if (!wrapper) return;
  
  const isCollapsed = wrapper.classList.contains('collapsed');
  if (isCollapsed) {
    wrapper.classList.remove('collapsed');
    btn.textContent = '⊟ Collapse';
  } else {
    wrapper.classList.add('collapsed');
    btn.textContent = '⊞ Expand';
  }
}

function openFlowithMediaCanvas(url, mediaType) {
  if (mediaType === 'image') {
    const ext  = (url.split('?')[0].split('.').pop() || 'png').toLowerCase();
    const name = url.split('/').pop().split('?')[0] || 'generated.png';

    // Make canvas panel visible (Flowith provider hides it via display:none
    // until explicitly needed; re-show it here)
    const canvasPanel = document.getElementById('canvasPanel');
    if (canvasPanel) canvasPanel.style.display = '';

    if (!S.canvasOpen) {
      S.canvasOpen = true;
      canvasPanel.classList.remove('collapsed');
      document.getElementById('canvasToggleBtn')?.classList.add('active');
    }

    switchCanvasTab('preview');

    document.getElementById('cvPreviewEmpty').style.display   = 'none';
    document.getElementById('cvPreviewContent').style.display = 'flex';
    document.getElementById('cvPreviewName').textContent      = name;

    const dlBtn = document.getElementById('cvDlBtn');
    if (dlBtn) { dlBtn.href = url; dlBtn.download = name; }

    const copyBtn = document.getElementById('cvCopyBtn');
    if (copyBtn) copyBtn.style.display = 'none';

    // Hide all viewers
    ['cvFrame', 'cvCode', 'cvPdf'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });

    const imgWrap = document.getElementById('cvImgWrap');
    if (imgWrap) {
      imgWrap.style.display = 'flex';
      const img = document.getElementById('cvImg');
      if (img) img.src = url;
    }
  } else {
    window.open(url, '_blank');
  }
}

function dlUrl(convId, filePath, inline = false) {
  const base = `/api/conversations/${convId}/download`
    + `?path=${encodeURIComponent(filePath)}`;
  const acct = getTabAccountName();
  const inl  = inline ? '&inline=1' : '';
  const acctParam = acct ? `&account_name=${encodeURIComponent(acct)}` : '';
  return base + inl + acctParam;
}

/* ═══════════════════════════════════════════
   POLLING CONFIG PANEL
═══════════════════════════════════════════ */

let _pollTimer = null;
let _pollCfg = {
  auto_poll_credits: true,
  poll_interval_sec: 90,
  stagger_delay_sec: 2.5,
  request_timeout_sec: 30,
};

async function loadPollingConfig() {
  try {
    const cfg = await fetch('/api/settings/polling').then(r => r.json());
    Object.assign(_pollCfg, cfg);
    _applyPollingCfgToUI();
  } catch {}
}

function _applyPollingCfgToUI() {
  const t = document.getElementById('pollAutoToggle');
  const i = document.getElementById('pollIntervalInp');
  const s = document.getElementById('pollStaggerInp');
  const x = document.getElementById('pollTimeoutInp');
  if (t) t.checked = !!_pollCfg.auto_poll_credits;
  if (i) i.value   = _pollCfg.poll_interval_sec;
  if (s) s.value   = _pollCfg.stagger_delay_sec;
  if (x) x.value   = _pollCfg.request_timeout_sec;
  _reschedulePoller();
}

function pollingDirty() {
  const btn = document.getElementById('pollSaveBtn');
  if (btn) btn.style.background = 'linear-gradient(135deg, #e0943a, #c27a20)';
}

async function savePollingConfig() {
  const t = document.getElementById('pollAutoToggle');
  const i = document.getElementById('pollIntervalInp');
  const s = document.getElementById('pollStaggerInp');
  const x = document.getElementById('pollTimeoutInp');
  const body = {
    auto_poll_credits:   t ? t.checked : true,
    poll_interval_sec:   parseFloat(i?.value || 90),
    stagger_delay_sec:   parseFloat(s?.value || 2.5),
    request_timeout_sec: parseFloat(x?.value || 30),
  };
  const statusEl = document.getElementById('pollStatus');
  try {
    const r = await fetch('/api/settings/polling', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    }).then(r => r.json());
    if (r.success) {
      Object.assign(_pollCfg, r.config);
      if (statusEl) { statusEl.textContent = '✓ Saved'; statusEl.className = 'poll-status ok'; }
      const btn = document.getElementById('pollSaveBtn');
      if (btn) btn.style.background = '';
      _reschedulePoller();
      setTimeout(() => { if (statusEl) { statusEl.textContent = ''; statusEl.className = 'poll-status'; } }, 3000);
    } else {
      if (statusEl) { statusEl.textContent = '✕ ' + (r.error || 'Failed'); statusEl.className = 'poll-status err'; }
    }
  } catch (err) {
    if (statusEl) { statusEl.textContent = '✕ ' + err.message; statusEl.className = 'poll-status err'; }
  }
}

function _reschedulePoller() {
  if (_pollTimer) clearInterval(_pollTimer);
  if (!_pollCfg.auto_poll_credits) return;
  const ms = Math.max(10_000, (_pollCfg.poll_interval_sec || 90) * 1000);
  _pollTimer = setInterval(() => {
    _pollAllAccounts(); // already covers flowith
  }, ms);
}

function togglePollingPanel() {
  const panel = document.getElementById('pollingPanel');
  const btn   = document.getElementById('pollingConfigBtn');
  if (!panel) return;
  const isHidden = panel.style.display === 'none' || !panel.style.display;
  panel.style.display = isHidden ? '' : 'none';
  if (btn) btn.classList.toggle('active', isHidden);
  if (isHidden) _applyPollingCfgToUI();
}

function closePollingPanel() {
  const panel = document.getElementById('pollingPanel');
  const btn   = document.getElementById('pollingConfigBtn');
  if (panel) panel.style.display = 'none';
  if (btn)   btn.classList.remove('active');
}

async function _pollAllAccounts() {
  if (!_pollCfg.auto_poll_credits) return;
  try {
    const all = await fetch('/api/usage/all').then(r => r.json());
    let changed = false;
    for (const [name, d] of Object.entries(all)) {
      if (d.provider === 'oneminai') {
        if (d.credits !== null && d.credits !== undefined) {
          _cacheOneminai(name, d.credits);
          changed = true;
        }
      } else if (d.provider === 'flowith') {
        const raw = d.credits?.total ?? d.credits?.credits_total ?? d.credits_total ?? null;
        if (raw !== null && raw !== undefined) {
          _cacheFlowith(name, raw);
          changed = true;
        }
      } else if (d.provider === 'claude' && d.quota?.windows) {
        _cacheClaude(name, d.quota);
        changed = true;
      }
    }
    if (changed) {
      _renderSidebarBar();
      renderAccountMenu();
      renderAccountList();
    }
  } catch { /* silent */ }
}

// Background helper: fetch latest credits for every flowith account and
// cache them so the sidebar / account-menu always shows fresh data.
async function _pollAllFlowithCredits() {
  const flowithAccounts = S.accounts.filter(
    a => (a.provider || '').toLowerCase() === 'flowith'
  );
  if (!flowithAccounts.length) return;

  let changed = false;
  for (const acct of flowithAccounts) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);

    try {
      const d = await fetch('/api/flowith/credits', {
        headers: { 'X-Account-Name': acct.name },
        signal: controller.signal
      }).then(r => r.json());
      clearTimeout(timer);
      const raw = d.credits?.total ?? d.credits?.credits_total ?? d.credits_total ?? null;
      if (raw != null) {
        _cacheFlowith(acct.name, raw);
        changed = true;
      }
    } catch { /* per-account failure is non-fatal */ }
    // Small stagger between accounts
    await new Promise(res => setTimeout(res, 600));
  }

  if (changed) {
    _renderSidebarBar();
    renderAccountMenu();
  }
}

/* ═══════════════════════════════════════════
   1MIN.AI — MODEL CATALOG FETCH + CACHE
═══════════════════════════════════════════ */

let _omaiModelCache = { fetched_at: 0, models: [], by_category: {} };

// Called on account switch and background warm-up — NOT on panel open.
async function fetchOneminaiModels(force = false) {
  const now = Date.now();
  if (!force && _omaiModelCache.models.length && now - _omaiModelCache.fetched_at < 900_000) {
    return _omaiModelCache;
  }
  try {
    const data = await apiFetch('/api/oneminai/models');
    if (data.models) {
      _omaiModelCache = {
        fetched_at:  now,
        models:      data.models,
        by_category: data.by_category || {},
      };
    }
  } catch {}
  return _omaiModelCache;
}

function populateOmaiImageModels() {
  const sel = document.getElementById('omaiImageModel');
  if (!sel) return;
  const acct = getTabAccount();
  if (!acct || (acct.provider || '').toLowerCase() !== 'oneminai') return;
  const imgModels = (_omaiModelCache.by_category?.image || []).filter(m => m.id);
  if (!imgModels.length) return;
  const cur = ddGetValue(sel);
  ddRebuild(sel, [{ options: imgModels.map(m => ({ value: m.id, text: m.display_name || m.id })) }]);
  if (cur) ddSetValue(sel, cur);
}

function populateOmaiAudioModels() {
  const modelSel = document.getElementById('omaiTTSModel');
  const acct = getTabAccount();
  if (!acct || (acct.provider || '').toLowerCase() !== 'oneminai') return;
  const audioModels = (_omaiModelCache.by_category?.audio || _omaiModelCache.by_category?.tts || []).filter(m => m.id);
  if (!audioModels.length || !modelSel) return;
  const cur = ddGetValue(modelSel);
  ddRebuild(modelSel, [{ options: audioModels.map(m => ({ value: m.id, text: m.display_name || m.id })) }]);
  if (cur) ddSetValue(modelSel, cur);
}

/* ═══════════════════════════════════════════
   1MIN.AI — ENHANCED PANEL INIT
═══════════════════════════════════════════ */

function _omaiPanelOnOpen() {
  // Panel open just renders from cache — no fetching.
  _renderOmaiPanelFromCache();
  // Model selects read from already-populated cache (no network call)
  populateOmaiImageModels();
  populateOmaiAudioModels();
  updateOmaiToolHint();
}

function _renderOmaiPanelFromCache() {
  const name   = getTabAccountName();
  const cached = name ? quotaCache[name] : null;
  const el     = document.getElementById('omaiCreditsDisplay');
  if (!el) return;
  if (!cached || cached.provider !== 'oneminai' || cached.credits == null) {
    el.textContent = '';
    return;
  }
  const cr = cached.credits;
  el.textContent = typeof cr === 'number'
    ? `✦ ${cr.toLocaleString()} credits`
    : `✦ ${cr} credits`;
}

function toggleOneminaiPanel() {
  const panel = document.getElementById('oneminaiPanel');
  if (!panel) return;
  const wasCollapsed = panel.classList.contains('collapsed');
  panel.classList.toggle('collapsed');
  const btn = document.getElementById('oneminaiPanelBtn');
  if (btn) btn.classList.toggle('active', wasCollapsed);
  if (wasCollapsed) _omaiPanelOnOpen();  // renders from cache only
  _trackPanelBackdrop();
}

/* ═══════════════════════════════════════════
   IMPROVED CONVERSATION DELETE (all providers)
═══════════════════════════════════════════ */

async function deleteConvFull(e, id) {
  e.stopPropagation();
  if (!confirm('Delete this conversation?')) return;
  const provider = getTabProvider();

  // For oneminai / claude: server-side delete
  if (provider === 'oneminai' || provider === 'claude') {
    try {
      await apiFetch(`/api/conversations/${id}`, { method: 'DELETE' });
    } catch (err) {
      toast('Delete error: ' + err.message, 'err');
      return;
    }
  }

  // Local cleanup
  await removeId(id);
  delete S.convs[id];
  S.allConvs = (S.allConvs || []).filter(c => c.uuid !== id);
  if (S.convId === id) {
    navToHome();
    toast('Deleted', 'info');
    return;
  }
  renderSidebar();
  toast('Deleted', 'info');
}

function toggleWebSearch() {
  S.webSearch = !S.webSearch;
  const btn = document.getElementById('webSearchBtn');
  if (btn) {
    btn.classList.toggle('on', S.webSearch);
    const lbl = btn.querySelector('#webSearchLbl');
    if (lbl) lbl.textContent = S.webSearch ? 'Web Search: on' : 'Web Search: off';
    else btn.textContent = S.webSearch ? '🌐 Web Search: On' : '🌐 Web Search: Off';
  }
}



/* ═══════════════════════════════════════════
   FLOWITH GOOGLE OAUTH
═══════════════════════════════════════════ */

function _flowithSetAuthStatus(msg, type) {
  const el = document.getElementById('flowithAuthStatus');
  if (!el) return;
  el.textContent = msg;
  el.className   = 'miniapps-auth-status' + (type ? ' ' + type : '');
  el.style.display = msg ? '' : 'none';
}

function _flowithResetAuthStatus() {
  const el  = document.getElementById('flowithAuthStatus');
  if (el) { el.style.display = 'none'; el.className = 'miniapps-auth-status'; el.textContent = ''; }
  const btn = document.getElementById('flowithGoogleBtn');
  if (btn) btn.disabled = false;
}

async function flowithGoogleSignIn() {
  const btn = document.getElementById('flowithGoogleBtn');
  if (btn) btn.disabled = true;
  _flowithSetAuthStatus('Starting Flowith sign-in session…', '');

  // Open immediately in the user gesture context to avoid popup blocking.
  const tab = window.open('about:blank', 'flowith_gis', 'width=600,height=700,left=200,top=80');

  let r;
  try { r = await fetch('/api/oauth/flowith/begin').then(x => x.json()); }
  catch (e) { r = null; }

  if (!r?.state) {
    if (tab && !tab.closed) tab.close();
    _flowithSetAuthStatus('Failed to start session — check server logs', 'err');
    if (btn) btn.disabled = false;
    return;
  }

  // Navigate to flowith.io so the extension content script can intercept the hash token.
  if (tab && !tab.closed) tab.location.href = 'https://flowith.io/';
  _flowithSetAuthStatus(
    tab
      ? 'Google sign-in prompt opening on flowith.io — complete it there…'
      : 'Visit flowith.io and complete the Google sign-in prompt…',
    ''
  );

  const iv = setInterval(async () => {
    let s;
    try { s = await fetch(`/api/oauth/flowith/status?state=${encodeURIComponent(r.state)}`).then(x => x.json()); }
    catch { return; }
    if (!s?.done) return;
    clearInterval(iv);
    if (tab && !tab.closed) tab.close();
    if (s.access_token) {
      const keyInp = document.getElementById('flowithKeyInp');
      const uidInp = document.getElementById('flowithUserIdInp');
      if (keyInp) keyInp.value = s.access_token;
      if (uidInp && s.user_id) uidInp.value = s.user_id;
      // Store refresh_token in a hidden field so saveAccount() picks it up
      let rtInp = document.getElementById('flowithRefreshTokenInp');
      if (!rtInp) {
        rtInp = document.createElement('input');
        rtInp.type = 'hidden';
        rtInp.id   = 'flowithRefreshTokenInp';
        document.body.appendChild(rtInp);
      }
      if (s.refresh_token) rtInp.value = s.refresh_token;
      _flowithSetAuthStatus('✓ Authenticated' + (s.user_id ? ' (user: ' + s.user_id.slice(0,8) + '…)' : '') + ' — ready', 'ok');
    } else {
      _flowithSetAuthStatus('Sign-in failed: ' + (s.error || 'unknown error'), 'err');
    }
    if (btn) btn.disabled = false;
  }, 1000);

  // Safety timeout after 2 minutes
  setTimeout(() => {
    clearInterval(iv);
    if (tab && !tab.closed) tab.close();
    if (btn) btn.disabled = false;
    _flowithSetAuthStatus('Timed out — try again or paste token manually', 'err');
  }, 120_000);
}

/* ═══════════════════════════════════════════
   FLOWITH PANEL
═══════════════════════════════════════════ */

function toggleFlowithPanel() {
  const panel = document.getElementById('flowithPanel');
  const btn   = document.getElementById('flowithPanelBtn');
  if (!panel) return;
  const wasCollapsed = panel.classList.contains('collapsed');
  panel.classList.toggle('collapsed');
  if (btn) btn.classList.toggle('active', wasCollapsed);
  if (wasCollapsed) _flowithPanelOnOpen();  // renders from cache only
  _trackPanelBackdrop();
}

function _renderFlowithPanelFromCache() {
  const name   = getTabAccountName();
  const cached = name ? quotaCache[name] : null;
  const el     = document.getElementById('flowithCreditsDisplay');
  if (!el) return;
  if (!cached || cached.provider !== 'flowith' || cached.credits == null) {
    el.textContent = '';
    return;
  }
  const cr   = cached.credits;
  const crN  = typeof cr === 'number' ? cr : parseFloat(cr);
  const disp = isNaN(crN) ? String(cr) : crN.toFixed(2);
  el.textContent = `⋆ ${disp} credits`;
}

function _flowithPanelOnOpen() {
  _renderFlowithPanelFromCache();
  if (_flowithModelCache.models.length) {
    _populateFlowithModelSelects();
  } else {
    // First open — fetch models then populate
    _fetchAndCacheFlowithModels().then(() => _populateFlowithModelSelects()).catch(() => {});
  }
  setTimeout(() => _flowithRefreshCredits(false), 300);
}

/* ── Flowith model catalog with tier badges ── */
let _flowithModelCache = { fetched_at: 0, models: [] };

// ChatWithAI model cache (mirrors server-side _CHATWITHAI_MODEL_CACHE)
let _chatwithaiModelCache = { fetched_at: 0, models: [] };


// Reads from cache only — no network call.
// Cache is populated by _fetchAndCacheFlowithModels() on account switch.
function _populateFlowithModelSelects() {
  const models = _flowithModelCache.models;
  if (!models.length) return;

  const imageModels = models.filter(m => m.category === 'image');
  const videoModels = models.filter(m => m.category === 'video');
  _fillFlowithSel('flowithImageModel', imageModels);
  _fillFlowithSel('flowithVideoModel', videoModels);
}

// ChatWithAI model fetch — called on account switch and init warm-up
async function _fetchAndCacheChatwithaiModels(force = false) {
  const now = Date.now();
  if (!force && _chatwithaiModelCache.models.length &&
      now - _chatwithaiModelCache.fetched_at < 900_000) {
    return _chatwithaiModelCache.models;
  }
  try {
    // Use X-Account-Name header so the backend picks the right account
    const data = await apiFetch('/api/models');
    if (data.models && data.models.length) {
      _chatwithaiModelCache = { fetched_at: now, models: data.models };
    }
  } catch (e) {
    console.warn('[ChatWithAI] model fetch failed:', e.message);
  }
  return _chatwithaiModelCache.models;
}

// Called on account switch and background warm-up — NOT on panel open.
async function _fetchAndCacheFlowithModels() {
  const now = Date.now();
  if (_flowithModelCache.models.length &&
      now - _flowithModelCache.fetched_at < 900_000) {
    return _flowithModelCache.models;
  }
  try {
    const data = await apiFetch('/api/flowith/models');
    if (data.models?.length) {
      _flowithModelCache = { fetched_at: now, models: data.models };
    }
  } catch { /* keep cached */ }
  return _flowithModelCache.models;
}

function _fillFlowithSel(selId, models) {
  const sel = document.getElementById(selId);
  if (!sel || !models.length) return;
  const cur = ddGetValue(sel);
  const sorted = [...models].sort((a, b) => (a.tier ?? 2) - (b.tier ?? 2));
  const free = sorted.filter(m => (m.tier ?? 2) !== 't1');
  const paid = sorted.filter(m => (m.tier ?? 2) === 't1');
  const groups = [];
  if (free.length) groups.push({ label: '🆓 Free tier', options: free.map(m => ({ value: m.id, text: '🆓 ' + (m.display_name || m.id), badge: 'free' })) });
  if (paid.length) groups.push({ label: '💎 Paid tier', options: paid.map(m => ({ value: m.id, text: '💎 ' + (m.display_name || m.id), badge: 'paid' })) });
  ddRebuild(sel, groups);
  if (cur) ddSetValue(sel, cur);
}

// ── Flowith token auto-refresh ────────────────────────────────────────────────
// Parse expiry from the stored JWT and schedule a refresh 5 minutes before
// it expires. Called whenever the active account changes to a Flowith account.
let _flowithRefreshTimer = null;

function _flowithScheduleRefresh() {
  if (_flowithRefreshTimer) { clearTimeout(_flowithRefreshTimer); _flowithRefreshTimer = null; }
  const acct = getTabAccount();
  if (!acct || acct.provider !== 'flowith' || !acct.api_key) return;
  if (!acct.refresh_token) return;  // nothing to rotate with

  let expiresAt = 0;
  try {
    const parts   = acct.api_key.split('.');
    const payload = JSON.parse(atob(parts[1].replace(/-/g,'+').replace(/_/g,'/')));
    expiresAt     = (payload.exp || 0) * 1000;  // ms
  } catch (_) { return; }

  const now    = Date.now();
  const margin = 5 * 60 * 1000;  // refresh 5 min before expiry
  const delay  = expiresAt - now - margin;

  if (delay <= 0) {
    // Already expired or very close — refresh immediately
    _flowithDoRefresh();
    return;
  }

  _flowithRefreshTimer = setTimeout(_flowithDoRefresh, delay);
  const mins = Math.round(delay / 60000);
  console.debug(`[Flowith] token refresh scheduled in ~${mins} min`);
}

// ── Flowith session-cycle credit refresh ─────────────────────────────────────
async function _flowithCycleSession(opts = {}) {
  const acct = getTabAccount();
  if (!acct || acct.provider !== 'flowith') return null;
  const { cycles = 3, delay_sec = 1.0 } = opts;
  try {
    const r = await apiFetch('/api/flowith/session-cycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cycles, delay_sec }),
    });
    if (r.credits !== undefined) {
      const raw = r.credits?.total ?? r.credits ?? null;
      if (raw !== null) {
        _cacheFlowith(acct.name, raw);
        _renderSidebarBar();
        renderAccountMenu();
        // Update panel header badge immediately
        const el = document.getElementById('flowithCreditsDisplay');
        if (el) {
          const n = typeof raw === 'number' ? raw : parseFloat(raw);
          el.textContent = isNaN(n) ? `⋆ ${raw} credits` : `⋆ ${n.toFixed(2)} credits`;
        }
      }
    }
    return r;
  } catch (err) {
    console.warn('[Flowith] session-cycle failed:', err.message);
    return null;
  }
}

// Convenience: cycle then fetch credits — refreshes ALL flowith accounts,
// not just the active one, so the sidebar shows up-to-date credits for every account.
async function _flowithRefreshCredits(showToast = false) {
  const flowithAccounts = S.accounts.filter(a => (a.provider || '').toLowerCase() === 'flowith');
  if (!flowithAccounts.length) return;

  if (showToast) toast('Refreshing Flowith credits…', 'info');

  // Refresh the active/tab account first (cycle + fetch)
  const activeAcct = flowithAccounts.find(a => a.name === getTabAccountName())
                  || flowithAccounts[0];

  // Helper: fetch credits for a named flowith account via the server
  async function _fetchFlowithCreditsFor(acctName) {
    try {
      const headers = { 'X-Account-Name': acctName };
      const d = await fetch('/api/flowith/credits', { headers }).then(r => r.json());
      const raw = d.credits?.total ?? d.credits?.credits_total ?? d.credits_total ?? null;
      if (raw != null) {
        _cacheFlowith(acctName, raw);
        return raw;
      }
    } catch {}
    return null;
  }

  // Cycle session + fetch for the active account
  const r = await _flowithCycleSession({ cycles: 3, delay_sec: 1.0 });
  await _fetchFlowithCreditsFor(activeAcct.name);

  // Background-refresh all OTHER flowith accounts (no cycle, just credits)
  const others = flowithAccounts.filter(a => a.name !== activeAcct.name);
  if (others.length) {
    // Fire-and-forget with a small stagger to avoid hammering the server
    (async () => {
      for (const acct of others) {
        await _fetchFlowithCreditsFor(acct.name);
        await new Promise(res => setTimeout(res, 800));
      }
      _renderSidebarBar();
      renderAccountMenu();
      renderAccountList();
    })().catch(() => {});
  }

  _renderSidebarBar();
  renderAccountMenu();

  if (showToast) {
    const name   = getTabAccountName();
    const cached = name ? quotaCache[name] : null;
    const num    = cached?.credits ?? null;
    const display = num != null ? num.toFixed(2) : '?';
    toast(`Flowith credits: ${display}`, 'ok');
  }
}

// ── 1min.AI auto-refresh on 401 ────────────────────────────────────────────
async function _oneminaiAutoRefresh() {
  const acct = getTabAccount();
  if (!acct || acct.provider !== 'oneminai') return false;
  try {
    const r = await apiFetch('/api/oneminai/refresh', { method: 'POST' });
    if (r.access_token) {
      // Update in-memory account so next request uses the new token
      if (S.tabAccount) S.tabAccount.api_key = r.access_token;
      const cached = S.accounts.find(a => a.name === acct.name);
      if (cached) {
        cached.api_key = r.access_token;
        if (r.team_id) cached.team_id = r.team_id;
      }
      _cache_invalidate_client();
      console.log('[1min.AI] token refreshed automatically');
      return true;
    }
  } catch (e) {
    console.warn('[1min.AI] auto-refresh failed:', e.message);
  }
  return false;
}

// ── 1min.AI proactive token refresh scheduler ──────────────────────────
let _omaiRefreshTimer = null;

function _omaiScheduleRefresh() {
  if (_omaiRefreshTimer) { clearTimeout(_omaiRefreshTimer); _omaiRefreshTimer = null; }
  const acct = getTabAccount();
  if (!acct || (acct.provider || '').toLowerCase() !== 'oneminai') return;
  if (!acct.api_key) return;

  let expiresAt = 0;
  try {
    const parts   = acct.api_key.split('.');
    const payload = JSON.parse(atob(parts[1].replace(/-/g,'+').replace(/_/g,'/')));
    expiresAt     = (payload.exp || 0) * 1000;
  } catch (_) { return; }

  const now    = Date.now();
  const margin = 5 * 60 * 1000; // refresh 5 min before expiry
  const delay  = expiresAt - now - margin;

  if (delay <= 0) {
    _omaiDoRefresh();
    return;
  }

  _omaiRefreshTimer = setTimeout(_omaiDoRefresh, delay);
  const mins = Math.round(delay / 60000);
  console.debug(`[1min.AI] token refresh scheduled in ~${mins} min`);
}

async function _omaiDoRefresh() {
  _omaiRefreshTimer = null;
  const acct = getTabAccount();
  if (!acct || (acct.provider || '').toLowerCase() !== 'oneminai') return;

  try {
    const r = await apiFetch('/api/oneminai/refresh', { method: 'POST' });
    if (r.access_token) {
      if (S.tabAccount) {
        S.tabAccount.api_key = r.access_token;
        if (r.team_id) S.tabAccount.team_id = r.team_id;
      }
      const cached = S.accounts.find(a => a.name === acct.name);
      if (cached) {
        cached.api_key = r.access_token;
        if (r.team_id) cached.team_id = r.team_id;
      }
      _cache_invalidate_client();
      console.debug('[1min.AI] token refreshed automatically');
      // Reschedule for the new token's expiry
      _omaiScheduleRefresh();
    } else {
      console.warn('[1min.AI] auto-refresh returned no access_token:', r);
    }
  } catch (err) {
    console.warn('[1min.AI] auto-refresh failed:', err.message);
    // Retry in 2 minutes if it failed
    _omaiRefreshTimer = setTimeout(_omaiDoRefresh, 2 * 60 * 1000);
  }
}

async function _flowithDoRefresh() {
  _flowithRefreshTimer = null;
  const acct = getTabAccount();
  if (!acct || acct.provider !== 'flowith') return;
  try {
    const r = await apiFetch('/api/flowith/refresh', { method: 'POST' });
    if (r.access_token) {
      // Update the in-memory account so the new token is used immediately
      if (S.tabAccount) {
        S.tabAccount.api_key      = r.access_token;
        S.tabAccount.refresh_token = r.refresh_token || S.tabAccount.refresh_token;
        S.tabAccount.user_id      = r.user_id || S.tabAccount.user_id;
      }
      // Also update S.accounts cache
      const cached = S.accounts.find(a => a.name === acct.name);
      if (cached) {
        cached.api_key       = r.access_token;
        cached.refresh_token = r.refresh_token || cached.refresh_token;
        cached.user_id       = r.user_id || cached.user_id;
      }
      console.debug('[Flowith] token refreshed successfully');
      // Schedule the next refresh
      _flowithScheduleRefresh();
    } else {
      console.warn('[Flowith] token refresh returned no access_token:', r);
    }
  } catch (err) {
    console.warn('[Flowith] token refresh failed:', err.message);
  }
}

function flowithSwitchTab(tab) {
  // Chat tab removed — Flowith chat uses main interface
  ['image', 'video'].forEach(t => {
    const btn     = document.getElementById(`flowith-tab-${t}`);
    const content = document.getElementById(`flowith-content-${t}`);
    const isActive = t === tab;
    if (btn)     btn.classList.toggle('active', isActive);
    if (content) content.classList.toggle('active', isActive);
  });
}

// Flowith chat is handled via the main conversation interface.
// runFlowithChat / flowithCopyResult / flowithInsertResult removed.

async function runFlowithImage() {
  const prompt  = document.getElementById('flowithImagePrompt')?.value.trim();
  const model   = ddGetValue(document.getElementById('flowithImageModel'));
  const ratio   = ddGetValue(document.getElementById('flowithImageRatio'));
  const result  = document.getElementById('flowithImageResult');
  const grid    = document.getElementById('flowithImageGrid');
  const runBtn  = document.getElementById('flowithImageRunBtn');

  if (!prompt) { toast('Enter a prompt first', 'err'); return; }
  if (result) result.classList.remove('visible');
  if (grid)   grid.innerHTML = '';
  if (runBtn) runBtn.disabled = true;
  toast('Generating image… (may take 20-60 s)', 'info');

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      controller.abort();
    }, 3600000); // 1 hour timeout

    const r = await apiFetch('/api/flowith/image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        model,
        aspect_ratio: ratio,
        timeout: 3600000,
      }),
      signal: controller.signal
    });

    clearTimeout(timer);

    if (r.images && r.images.length) {
      if (result) result.classList.add('visible');
      r.images.forEach(img => {
        if (!img.url) return;
        const wrap = document.createElement('div');
        wrap.className = 'flowith-img-item';
        const im = document.createElement('img');
        im.src = img.url; im.alt = 'Generated';
        im.title = 'Click to open in canvas';
        im.onclick = () => openInCanvas(img.url, 'flowith-image.png', 'image/png');
        const dl = document.createElement('a');
        dl.href = img.url; dl.download = 'flowith-image.png';
        dl.className = 'flowith-img-save'; dl.textContent = '⬇ Save';
        wrap.appendChild(im); wrap.appendChild(dl);
        grid.appendChild(wrap);
      });
      toast(`Generated ${r.images.length} image(s)`, 'ok');
    } else {
      toast('Error: ' + (r.error || 'no images returned'), 'err');
    }
  } catch (err) {
    toast('Error: ' + err.message, 'err');
  } finally {
    if (runBtn) runBtn.disabled = false;
  }
}

async function runFlowithVideo() {
  const prompt  = document.getElementById('flowithVideoPrompt')?.value.trim();
  const model   = ddGetValue(document.getElementById('flowithVideoModel'));
  const ratio   = ddGetValue(document.getElementById('flowithVideoRatio'));
  const result  = document.getElementById('flowithVideoResult');
  const wrap    = document.getElementById('flowithVideoWrap');
  const videoEl = document.getElementById('flowithVideo');
  const dlEl    = document.getElementById('flowithVideoDl');
  const runBtn  = document.getElementById('flowithVideoRunBtn');

  if (!prompt) { toast('Enter a prompt first', 'err'); return; }
  if (wrap) wrap.style.display = 'none';
  if (runBtn) runBtn.disabled = true;
  toast('Generating video… (may take 1–5 minutes)', 'info');

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      controller.abort();
    }, 3600000); // 1 hour timeout

    const r = await apiFetch('/api/flowith/video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        model,
        aspect_ratio: ratio,
        timeout: 3600000,
      }),
      signal: controller.signal
    });

    clearTimeout(timer);

    if (r.video_url) {
      if (videoEl) { videoEl.src = r.video_url; videoEl.load(); }
      if (dlEl)    { dlEl.href = r.video_url; dlEl.download = 'flowith-video.mp4'; }
      if (wrap)    wrap.style.display = 'flex';
      if (result)  result.classList.add('visible');
      toast('Video ready!', 'ok');
    } else {
      toast('Error: ' + (r.error || 'no video returned'), 'err');
    }
  } catch (err) {
    toast('Error: ' + err.message, 'err');
  } finally {
    if (runBtn) runBtn.disabled = false;
  }
}
/* ═══════════════════════════════════════════
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
  const fmt = ddGetValue(document.getElementById('copyConvFormatSel'));
  const msgs = buildChain(S.convs[S.convId]);
  let res = '';
  
  if (fmt === 'json') {
    res = JSON.stringify(msgs, null, 2);
  } else {
    for (const m of msgs) {
      const role = m.sender === 'human' ? 'Human' : 'Assistant';
      const text = m.text || (m.content || []).filter(c=>c.type==='text').map(c=>c.text).join('\n');
      
      if (fmt === 'prompt') {
        res += `---- ${role}: ----\n${text}\n\n`;
      } else {
        const name = role === 'Human' ? 'You' : 'Assistant';
        res += `${name}:\n${text}\n\n`;
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
  try {
    rawCode = decodeURIComponent(escape(atob(el.dataset.raw)));
  } catch {
    rawCode = el.textContent || '';
  }

  if (lang === 'svg') {
    openInCanvasRaw(rawCode, 'Rendered SVG', 'image/svg+xml');
    return;
  }

  if (lang === 'html') {
    openInCanvasRaw(rawCode, 'Rendered HTML', 'text/html');
    return;
  }

  if (lang === 'mermaid') {
    const code64 = btoa(unescape(encodeURIComponent(rawCode)));
    const html = [
      '<!doctype html><html><head><meta charset="utf-8">',
      '<style>body{background:#fff;display:flex;justify-content:center;padding:20px;}</style>',
      '</head><body>',
      '<div id="m" class="mermaid"></div>',
      '<script type="module">',
      'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";',
      'const code = decodeURIComponent(escape(atob(' + JSON.stringify(code64) + ')));',
      'document.getElementById("m").textContent = code;',
      'mermaid.initialize({ startOnLoad: true });',
      '<\/script>',
      '</body></html>'
    ].join('');
    openInCanvasRaw(html, 'Rendered MERMAID', 'text/html');
    return;
  }
}

// ── State ─────────────────────────────────────────────────────────────────
const BEX = {
  open:          false,
  viewLeafUuid:  null,   // which leaf the chat view is showing (null = latest)
  sendParentUuid: null,  // parent UUID for next send (null = auto = viewLeaf)
};

const ROOT_UUID = '00000000-0000-4000-8000-000000000000';

// ── Panel toggle ──────────────────────────────────────────────────────────
function toggleBranchExplorer() {
  BEX.open = !BEX.open;
  const panel = document.getElementById('bexPanel');
  const btn   = document.getElementById('branchExplorerBtn');
  panel.classList.toggle('collapsed', !BEX.open);
  if (btn) btn.classList.toggle('active', BEX.open);
  if (BEX.open) bexRebuild();
  _trackPanelBackdrop();
}

// ── Core tree builder ─────────────────────────────────────────────────────
// Returns { nodes, byUuid, childrenOf, leafUuids, branchPoints }
function bexBuildTree(conv) {
  const msgs = conv.chat_messages || [];
  const byUuid = {};
  const childrenOf = {};

  for (const m of msgs) {
    if (!m.uuid) continue;
    byUuid[m.uuid] = m;
  }

  for (const m of msgs) {
    if (!m.uuid) continue;
    // If parent doesn't exist in this conversation's messages, treat as root child
    const rawParent = m.parent_message_uuid;
    const p = (rawParent && rawParent !== ROOT_UUID && byUuid[rawParent])
      ? rawParent
      : ROOT_UUID;
    (childrenOf[p] = childrenOf[p] || []).push(m);
  }

  // Sort children by created_at / index
  for (const p of Object.keys(childrenOf)) {
    childrenOf[p].sort((a, b) => {
      if (a.index != null && b.index != null) return a.index - b.index;
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
      return ta - tb;
    });
  }

  const leafUuids = msgs
    .filter(m => m.uuid && !(childrenOf[m.uuid]?.length))
    .map(m => m.uuid);

  const branchPoints = new Set(
    Object.entries(childrenOf)
      .filter(([, children]) => children.length > 1)
      .map(([p]) => p)
  );

  return { byUuid, childrenOf, leafUuids, branchPoints };
}

// Walk from a leaf uuid back to root, returning ordered chain
function bexChainFrom(leafUuid, byUuid) {
  const ROOT = ROOT_UUID;
  const chain = [];
  const visited = new Set();
  let cur = leafUuid;
  while (cur && cur !== ROOT && byUuid[cur] && !visited.has(cur)) {
    visited.add(cur);
    chain.unshift(byUuid[cur]);
    cur = byUuid[cur].parent_message_uuid;
  }
  return chain;
}

// Find the "deepest" leaf (most messages in chain back to root)
function bexFindDeepestLeaf(leafUuids, byUuid) {
  let best = null, bestLen = -1;
  for (const lu of leafUuids) {
    const chain = bexChainFrom(lu, byUuid);
    if (chain.length > bestLen) { bestLen = chain.length; best = lu; }
  }
  return best;
}

// ── Set which leaf to view + refresh messages ─────────────────────────────
function bexSetLeaf(leafUuid, skipTreeRebuild) {
  BEX.viewLeafUuid  = leafUuid;
  BEX.sendParentUuid = leafUuid;  // next send continues from this leaf

  // Persist the active leaf on the conversation object so it survives
  // BEX state resets, page reloads, and backend round-trips.
  const conv = S.convId ? S.convs[S.convId] : null;
  if (conv && leafUuid) {
    conv.current_leaf_message_uuid = leafUuid;
  }

  // Update the hidden branchSel for legacy doSend() compatibility
  const sel = document.getElementById('branchSel');
  if (sel) sel.value = leafUuid || ROOT_UUID;

  // Update toolbar pill
  _bexUpdatePill();

  // Re-render messages on this branch
  renderMsgs();
  buildBranchSel();

  if (BEX.open && !skipTreeRebuild) bexRebuild();
}

function bexResetLeaf(e) {
  if (e) e.stopPropagation();
  BEX.viewLeafUuid   = null;
  BEX.sendParentUuid = null;

  const sel = document.getElementById('branchSel');
  if (sel) sel.value = ROOT_UUID;

  // Jump to the latest / deepest leaf
  const conv = S.convId ? S.convs[S.convId] : null;
  if (conv?.chat_messages?.length) {
    const { byUuid, leafUuids } = bexBuildTree(conv);
    const leaf = conv.current_leaf_message_uuid && byUuid[conv.current_leaf_message_uuid]
      ? conv.current_leaf_message_uuid
      : bexFindDeepestLeaf(leafUuids, byUuid);
    BEX.viewLeafUuid   = leaf;
    BEX.sendParentUuid = leaf;
    if (sel) sel.value = leaf || ROOT_UUID;
  }

  _bexUpdatePill();
  renderMsgs();
  if (BEX.open) bexRebuild();
}

function _bexUpdatePill() {
  const pill  = document.getElementById('bexActivePill');
  const label = document.getElementById('bexActivePillLabel');
  if (!pill || !label) return;

  const conv = S.convId ? S.convs[S.convId] : null;
  if (!conv?.chat_messages?.length || !BEX.viewLeafUuid) {
    pill.classList.remove('visible');
    return;
  }

  const { byUuid, leafUuids } = bexBuildTree(conv);
  const deepest = bexFindDeepestLeaf(leafUuids, byUuid);

  // Only show pill when NOT on the latest leaf
  if (BEX.viewLeafUuid === deepest || BEX.viewLeafUuid === conv.current_leaf_message_uuid) {
    pill.classList.remove('visible');
    return;
  }

  const msg = byUuid[BEX.viewLeafUuid];
  const preview = msg
    ? ((msg.text || (msg.content||[]).find(b=>b.type==='text')?.text || '') + '')
        .slice(0, 40).replace(/\n/g,' ')
    : BEX.viewLeafUuid.slice(0,8);

  pill.classList.add('visible');
  label.textContent = `[${msg?.sender === 'human' ? 'You' : 'AI'}] ${preview}${preview.length >= 40 ? '…' : ''}`;
}

// ── Navigate to prev/next sibling of the current leaf ─────────────────────
function bexNavSibling(dir) {
  const conv = S.convId ? S.convs[S.convId] : null;
  if (!conv?.chat_messages?.length) return;

  const { byUuid, childrenOf, leafUuids } = bexBuildTree(conv);
  const currentLeaf = BEX.viewLeafUuid || bexFindDeepestLeaf(leafUuids, byUuid);
  if (!currentLeaf) return;

  // Walk from the current leaf to root, find the first branch point
  const chain = bexChainFrom(currentLeaf, byUuid);
  for (let i = chain.length - 1; i >= 0; i--) {
    const node   = chain[i];
    const parent = node.parent_message_uuid || ROOT_UUID;
    const siblings = childrenOf[parent] || [];
    if (siblings.length < 2) continue;

    const sibIdx = siblings.findIndex(s => s.uuid === node.uuid);
    const nextSib = siblings[sibIdx + dir];
    if (!nextSib) continue;  // at boundary

    // From nextSib, find its deepest descendant leaf
    const nextLeaf = _bexDeepestDescendant(nextSib.uuid, childrenOf, leafUuids);
    bexSetLeaf(nextLeaf);
    return;
  }
  toast('No sibling branch found in this direction', 'info');
}

function _bexDeepestDescendant(startUuid, childrenOf, leafUuids) {
  // BFS / DFS to find the deepest leaf descended from startUuid
  const leafSet = new Set(leafUuids);
  if (leafSet.has(startUuid)) return startUuid;

  // DFS
  let best = startUuid, bestDepth = 0;
  function dfs(uuid, depth) {
    const children = childrenOf[uuid] || [];
    if (!children.length) {
      if (depth > bestDepth) { bestDepth = depth; best = uuid; }
      return;
    }
    for (const c of children) dfs(c.uuid, depth + 1);
  }
  dfs(startUuid, 0);
  return best;
}

// Jump to latest (deepest) leaf
function bexGoLatest() {
  const conv = S.convId ? S.convs[S.convId] : null;
  if (!conv?.chat_messages?.length) return;
  const { byUuid, leafUuids } = bexBuildTree(conv);
  const leaf = conv.current_leaf_message_uuid && byUuid[conv.current_leaf_message_uuid]
    ? conv.current_leaf_message_uuid
    : bexFindDeepestLeaf(leafUuids, byUuid);
  bexSetLeaf(leaf);
}

// ── Build the visual tree in the panel ───────────────────────────────────
function bexRebuild() {
  const treeEl  = document.getElementById('bexTree');
  const navLbl  = document.getElementById('bexNavLabel');
  const prevBtn = document.getElementById('bexPrevSibBtn');
  const nextBtn = document.getElementById('bexNextSibBtn');
  if (!treeEl) return;

  const conv = S.convId ? S.convs[S.convId] : null;
  if (!conv?.chat_messages?.length) {
    treeEl.innerHTML = `
      <div style="padding:24px 16px;text-align:center">
        <div style="font-size:var(--fs-4xl);opacity:.2;margin-bottom:8px">⎇</div>
        <div style="font-size:12px;color:var(--text-3)">No messages yet</div>
      </div>`;
      treeEl.style.minWidth = '0';
    if (navLbl)  navLbl.textContent = 'No conversation open';
    if (prevBtn) prevBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = true;
    return;
  }

  const { byUuid, childrenOf, leafUuids, branchPoints } = bexBuildTree(conv);
  const currentLeaf  = BEX.viewLeafUuid || bexFindDeepestLeaf(leafUuids, byUuid);
  const currentChain = new Set(bexChainFrom(currentLeaf, byUuid).map(m => m.uuid));

  // Stats
  const totalBranches = leafUuids.length;
  const activeLen     = currentChain.size;
  if (navLbl) navLbl.textContent = `${activeLen} msg${activeLen!==1?'s':''} · ${totalBranches} branch${totalBranches!==1?'es':''}`;

  // Prev/next sibling detection
  let hasPrev = false, hasNext = false;
  for (const node of bexChainFrom(currentLeaf, byUuid)) {
    const parent   = node.parent_message_uuid || ROOT_UUID;
    const siblings = childrenOf[parent] || [];
    if (siblings.length < 2) continue;
    const idx = siblings.findIndex(s => s.uuid === node.uuid);
    if (idx > 0)                    hasPrev = true;
    if (idx < siblings.length - 1) hasNext = true;
    if (hasPrev && hasNext) break;
  }
  if (prevBtn) prevBtn.disabled = !hasPrev;
  if (nextBtn) nextBtn.disabled = !hasNext;

  const scrollTop = treeEl.scrollTop;
  treeEl.innerHTML = '';

  // Always render root at top
  _bexRenderNodeSimple(treeEl, ROOT_UUID, 0, { byUuid, childrenOf, leafUuids, branchPoints, currentLeaf, currentChain });

  treeEl.scrollTop = scrollTop;

  // Scroll current node into view
  requestAnimationFrame(() => {
    const curEl = treeEl.querySelector('[data-uuid="' + currentLeaf + '"]');
    if (curEl) {
      const rect     = curEl.getBoundingClientRect();
      const treeRect = treeEl.getBoundingClientRect();
      if (rect.top < treeRect.top || rect.bottom > treeRect.bottom) {
        curEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  });
}

// Recursive DFS renderer — renders every node starting from parentUuid
function _bexRenderNodeSimple(container, parentUuid, depth, ctx) {
  const { byUuid, childrenOf, leafUuids, branchPoints, currentLeaf, currentChain } = ctx;
  const children = (childrenOf[parentUuid] || []);

  // Render the node itself (skip for ROOT_UUID — render a synthetic root row)
  if (parentUuid === ROOT_UUID) {
    // Synthetic root row
    const rootEl = _bexMakeRow({
      uuid:    ROOT_UUID,
      sender:  'root',
      text:    '',
    }, depth, false, false, false, true, ctx);
    container.appendChild(rootEl);
  }

  // Render children
  if (children.length === 1) {
    const child = children[0];
    const isActive  = currentChain.has(child.uuid);
    const isCurrent = child.uuid === currentLeaf;
    const isBranch  = branchPoints.has(child.uuid);
    const isLeaf    = leafUuids.includes(child.uuid);
    const el = _bexMakeRow(child, depth + 1, isActive, isCurrent, isBranch, isLeaf, ctx);
    container.appendChild(el);
    _bexRenderNodeSimple(container, child.uuid, depth + 1, ctx);

  } else if (children.length > 1) {
    // Branch point: render each child branch in a slightly indented group
    for (let i = 0; i < children.length; i++) {
      const child     = children[i];
      const isActive  = currentChain.has(child.uuid);
      const isCurrent = child.uuid === currentLeaf;
      const isBranch  = branchPoints.has(child.uuid);
      const isLeaf    = leafUuids.includes(child.uuid);

      // Branch separator label
      const sep = document.createElement('div');
      sep.style.cssText = `
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px 2px ${(depth + 1) * 18 + 4}px;
      `;
      sep.innerHTML = `
        <div style="height:1px;width:12px;background:${isActive?'var(--teal)':'var(--border)'};flex-shrink:0"></div>
        <span style="
          font-size:9px;font-family:var(--font-mono);font-weight:700;
          color:${isActive?'var(--teal)':'var(--text-4)'};
          white-space:nowrap;padding:1px 6px;
          border:1px solid ${isActive?'rgba(56,189,248,.3)':'var(--border)'};
          border-radius:8px;
          background:${isActive?'rgba(56,189,248,.07)':'var(--bg-2)'};
          cursor:pointer;
        " onclick="event.stopPropagation();bexSetLeaf(_bexDeepestDescendant('${child.uuid}',_bexCtxChildrenOf,_bexCtxLeafUuids))">
          Branch ${i + 1}${isActive?' ✓':''}
        </span>`;
      // Store ctx refs for onclick (avoid closure issues with inline onclick)
      container.appendChild(sep);
      // Fix the onclick to use proper closure
      const branchBtn = sep.querySelector('span');
      branchBtn.onclick = (e) => {
        e.stopPropagation();
        const leaf = _bexDeepestDescendant(child.uuid, ctx.childrenOf, ctx.leafUuids);
        bexSetLeaf(leaf);
      };

      const el = _bexMakeRow(child, depth + 1, isActive, isCurrent, isBranch, isLeaf, ctx);
      container.appendChild(el);
      _bexRenderNodeSimple(container, child.uuid, depth + 1, ctx);
    }
  }
}

function bexGoToLeafFrom(uuid) {
  const conv = S.convId ? S.convs[S.convId] : null;
  if (!conv) return;
  const { childrenOf, leafUuids } = bexBuildTree(conv);
  const leaf = _bexDeepestDescendant(uuid, childrenOf, leafUuids);
  bexSetLeaf(leaf);
  toast('Jumped to leaf', 'info');
}

function _bexMakeRow(msg, depth, isActive, isCurrent, isBranchPt, isLeaf, ctx) {
  const { childrenOf, leafUuids } = ctx;
  const isRoot      = msg.uuid === ROOT_UUID;
  const hasChildren = (childrenOf[msg.uuid] || []).length > 0;
  const indentPx    = depth * 18;

  const preview = isRoot
    ? 'Conversation start'
    : (msg.text || (msg.content || []).find(b => b.type === 'text')?.text || '')
        .replace(/\s+/g, ' ').trim()
        .slice(0, 60);
  const ts = (!isRoot && msg.created_at) ? fmtTime(msg.created_at) : '';
  const senderClass = isRoot ? 'root' : msg.sender === 'human' ? 'human' : 'assistant';
  const senderLabel = isRoot ? 'ROOT' : msg.sender === 'human' ? 'YOU' : 'AI';

  const dotColor  = isCurrent ? 'var(--accent)' : isActive ? 'var(--teal)' : isBranchPt ? 'var(--yellow)' : 'var(--bg-5)';
  const dotBorder = isCurrent ? 'var(--accent)' : isActive ? 'var(--teal)' : 'var(--border-m)';
  const dotGlow   = isCurrent ? '0 0 8px rgba(168,85,247,.5)' : isActive ? '0 0 8px rgba(56,189,248,.4)' : 'none';
  const dotSize   = (isCurrent || isActive) ? '9px' : '7px';

  const cardBg     = isCurrent ? 'rgba(168,85,247,0.08)' : isActive ? 'rgba(56,189,248,0.05)' : 'transparent';
  const cardBorder = isCurrent ? 'rgba(168,85,247,0.25)' : isActive ? 'rgba(56,189,248,0.2)'  : 'transparent';
  const previewColor = isCurrent ? 'var(--text)' : isActive ? 'var(--text-2)' : 'var(--text-3)';

  const badgeStyle = senderClass === 'root'
    ? 'background:var(--teal-dim);color:var(--teal);'
    : senderClass === 'human'
      ? 'background:rgba(255,255,255,0.06);color:var(--text-3);'
      : 'background:var(--accent-dim);color:var(--accent);';

  // ── Outer wrap ────────────────────────────────────────────────────────
  const wrap = document.createElement('div');
  wrap.dataset.uuid = msg.uuid;
  wrap.style.cssText = `display:flex;align-items:stretch;padding-left:${indentPx}px;min-width:max-content;width:max-content;`;

  // ── Connector ─────────────────────────────────────────────────────────
  const connector = document.createElement('div');
  connector.style.cssText = `display:flex;flex-direction:column;align-items:center;width:36px;flex-shrink:0;`;
  connector.innerHTML = `
    <div style="flex:1;width:1px;background:var(--border);min-height:${isRoot ? '0' : '6'}px;${isRoot ? 'opacity:0' : ''}"></div>
    <div style="width:${dotSize};height:${dotSize};border-radius:50%;background:${dotColor};border:1.5px solid ${dotBorder};box-shadow:${dotGlow};flex-shrink:0;transition:all var(--t-fast);"></div>
    <div style="flex:1;width:1px;background:var(--border);min-height:6px;${!hasChildren ? 'opacity:0' : ''}"></div>
  `;

  // ── Card ──────────────────────────────────────────────────────────────
  const card = document.createElement('div');
  card.style.cssText = `flex:1;min-width:0;margin:3px 6px 3px 0;padding:7px 10px;border-radius:8px;border:1px solid ${cardBorder};background:${cardBg};cursor:pointer;transition:all var(--t-fast);`;

  // Header row
  const header = document.createElement('div');
  header.style.cssText = `display:flex;align-items:center;gap:5px;${preview ? 'margin-bottom:3px;' : ''}`;
  header.innerHTML = `
    <span style="font-size:9px;font-weight:700;font-family:var(--font-mono);padding:1px 5px;border-radius:3px;letter-spacing:.05em;flex-shrink:0;${badgeStyle}">${senderLabel}</span>
    ${isBranchPt && !isRoot
      ? `<span style="font-size:8px;font-weight:700;padding:1px 4px;border-radius:8px;background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(250,204,21,.2);font-family:var(--font-mono)">${(childrenOf[msg.uuid]||[]).length}×</span>`
      : ''}
    ${ts ? `<span style="font-size:9px;color:var(--text-4);font-family:var(--font-mono);margin-left:auto">${ts}</span>` : ''}
  `;

  // Preview text
  const previewEl = document.createElement('div');
  previewEl.style.cssText = `font-size:var(--fs-sm2);color:${previewColor};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.4;`;
  previewEl.textContent = preview;

  // Action row — hidden by default, shown on hover
  const actionsEl = document.createElement('div');
  actionsEl.style.cssText = `display:none;align-items:center;gap:4px;margin-top:6px;padding-top:5px;border-top:1px solid var(--border-s);`;

  if (!isRoot) {
    const mkBtn = (label, cls) => {
      const b = document.createElement('button');
      b.style.cssText = `
        display:inline-flex;align-items:center;gap:3px;
        padding:2px 8px;border-radius:4px;
        border:1px solid var(--border);background:var(--bg-3);
        color:var(--text-3);font-size:var(--fs-xs);font-family:var(--font-mono);
        cursor:pointer;line-height:1.6;white-space:nowrap;
        transition:all .12s;
      `;
      b.dataset.action = cls;
      b.innerHTML = label;
      b.addEventListener('mouseenter', () => {
        if (cls === 'view') { b.style.color = 'var(--teal)';   b.style.borderColor = 'rgba(56,189,248,.3)';  b.style.background = 'var(--teal-dim)'; }
        if (cls === 'fork') { b.style.color = 'var(--accent)'; b.style.borderColor = 'rgba(168,85,247,.3)'; b.style.background = 'var(--accent-dim)'; }
        if (cls === 'go')   { b.style.color = 'var(--green)';  b.style.borderColor = 'rgba(74,222,128,.3)'; b.style.background = 'var(--green-dim)'; }
      });
      b.addEventListener('mouseleave', () => {
        b.style.color = 'var(--text-3)';
        b.style.borderColor = 'var(--border)';
        b.style.background = 'var(--bg-3)';
      });
      return b;
    };

    const viewBtn = mkBtn('👁 View', 'view');
    const forkBtn = mkBtn('⎇ Fork', 'fork');
    const goBtn   = mkBtn('↓ Go',   'go');

    viewBtn.addEventListener('click', e => { e.stopPropagation(); bexViewFromNode(msg.uuid); });
    forkBtn.addEventListener('click', e => { e.stopPropagation(); bexForkFromNode(msg.uuid); });
    goBtn.addEventListener('click',   e => { e.stopPropagation(); bexGoToLeafFrom(msg.uuid); });

    actionsEl.appendChild(viewBtn);
    actionsEl.appendChild(forkBtn);
    actionsEl.appendChild(goBtn);
  }

  card.appendChild(header);
  if (preview) card.appendChild(previewEl);
  if (!isRoot) card.appendChild(actionsEl);

  // ── Hover handlers ────────────────────────────────────────────────────
  wrap.addEventListener('mouseenter', () => {
    if (!isActive && !isCurrent) {
      card.style.background   = 'var(--bg-3)';
      card.style.borderColor  = 'var(--border)';
    }
    actionsEl.style.display = 'flex';
  });
  wrap.addEventListener('mouseleave', () => {
    if (!isActive && !isCurrent) {
      card.style.background  = cardBg;
      card.style.borderColor = cardBorder;
    }
    actionsEl.style.display = 'none';
  });

  // ── Click to navigate ─────────────────────────────────────────────────
  wrap.addEventListener('click', e => {
    if (e.target.closest('button')) return;
    if (isRoot) { bexResetLeaf(null); return; }
    const leaf = _bexDeepestDescendant(msg.uuid, childrenOf, leafUuids);
    bexSetLeaf(leaf);
    setTimeout(() => {
      document.querySelector(`.msg[data-uuid="${msg.uuid}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 80);
  });

  wrap.appendChild(connector);
  wrap.appendChild(card);

  return wrap;
}

function _bexRenderChildren(container, parentUuid, depth, ctx) {
  const children = ctx.childrenOf[parentUuid] || [];
  if (!children.length) return;

  if (children.length === 1) {
    _bexRenderNode(container, children[0], depth, ctx);
    _bexRenderChildren(container, children[0].uuid, depth, ctx);
  } else {
    _bexRenderBranchFork(container, children, depth, ctx);
  }
}

function _bexRenderNode(container, msg, depth, ctx) {
  const { currentChain, currentLeaf, branchPoints, leafUuids, childrenOf } = ctx;
  const isRoot     = msg.uuid === ROOT_UUID;
  const isActive   = currentChain.has(msg.uuid);
  const isCurrent  = msg.uuid === currentLeaf;
  const isBranchPt = branchPoints.has(msg.uuid);
  const isLeaf     = leafUuids.includes(msg.uuid);
  const hasChildren = (childrenOf[msg.uuid] || []).length > 0;
  const indentPx   = depth * 14;

  const preview = isRoot ? 'Conversation start'
    : (msg.text || (msg.content || []).find(b => b.type === 'text')?.text || '')
        .slice(0, 65).replace(/\n/g, ' ');
  const ts = msg.created_at ? fmtTime(msg.created_at) : '';
  const senderClass = isRoot ? 'root' : msg.sender === 'human' ? 'human' : 'assistant';
  const senderLabel = isRoot ? 'ROOT' : msg.sender === 'human' ? 'YOU' : 'AI';

  const rowClasses = [
    'bex-node-row',
    isActive   && 'is-active',
    isCurrent  && 'is-current',
    isBranchPt && 'is-branch-pt',
    isRoot     && 'is-root',
    isLeaf && !isRoot && 'is-leaf',
  ].filter(Boolean).join(' ');

  const wrap = document.createElement('div');
  wrap.style.paddingLeft = indentPx + 'px';

  wrap.innerHTML = `
    <div class="${rowClasses}" data-uuid="${msg.uuid}" style="display:flex;align-items:stretch;cursor:pointer;transition:background .12s;border-radius:8px;margin:1px 4px;">
      <div class="bex-node-trunk" style="display:flex;flex-direction:column;align-items:center;width:36px;flex-shrink:0;">
        <div class="bex-node-trunk-line-top" style="flex:1;width:1px;background:var(--border);min-height:6px;${isRoot?'opacity:0':''}"></div>
        <div class="bex-node-trunk-dot"></div>
        <div class="bex-node-trunk-line-bot" style="flex:1;width:1px;background:var(--border);min-height:6px;${!hasChildren&&!isRoot?'opacity:0':''}"></div>
      </div>
      <div class="bex-card" style="flex:1;min-width:0;margin:3px 6px 3px 0;padding:7px 10px;border-radius:10px;border:1px solid ${isActive?'rgba(56,189,248,0.2)':isCurrent?'rgba(168,85,247,0.25)':'transparent'};background:${isCurrent?'rgba(168,85,247,0.08)':isActive?'rgba(56,189,248,0.05)':'transparent'};transition:all var(--t-fast);">
        <div class="bex-card-top" style="display:flex;align-items:center;gap:5px;margin-bottom:2px;">
          <span class="bex-sender ${senderClass}" style="font-size:9px;font-weight:700;font-family:var(--font-mono);padding:1px 5px;border-radius:3px;letter-spacing:.05em;flex-shrink:0;">${senderLabel}</span>
          ${isBranchPt && !isRoot ? `<span style="font-size:8px;font-weight:700;padding:1px 5px;border-radius:10px;background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(250,204,21,.2);font-family:var(--font-mono)">${(childrenOf[msg.uuid]||[]).length}×</span>` : ''}
          ${isLeaf && !isRoot ? '<span style="margin-left:auto;font-size:8px;color:var(--text-4);font-family:var(--font-mono)">leaf</span>' : ''}
          ${ts ? `<span style="font-size:9px;color:var(--text-4);font-family:var(--font-mono);${isLeaf&&!isRoot?'':'margin-left:auto'}">${ts}</span>` : ''}
        </div>
        <div class="bex-preview" style="font-size:var(--fs-sm2);color:${isCurrent?'var(--text)':isActive?'var(--text-2)':'var(--text-3)'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.4;">${esc(preview)}</div>
      </div>
      ${!isRoot ? `
      <div class="bex-node-actions" style="display:none;gap:2px;align-items:center;padding-right:4px;flex-shrink:0;">
        <button class="bex-node-btn view" style="width:22px;height:22px;border-radius:5px;background:var(--bg-4);border:1px solid var(--border);color:var(--text-3);font-size:var(--fs-xs);display:flex;align-items:center;justify-content:center;cursor:pointer;" title="View" onclick="event.stopPropagation();bexViewFromNode('${msg.uuid}')">👁</button>
        <button class="bex-node-btn fork" style="width:22px;height:22px;border-radius:5px;background:var(--bg-4);border:1px solid var(--border);color:var(--text-3);font-size:var(--fs-xs);display:flex;align-items:center;justify-content:center;cursor:pointer;" title="Fork" onclick="event.stopPropagation();bexForkFromNode('${msg.uuid}')">⎇</button>
      </div>` : ''}
    </div>`;

  const row = wrap.querySelector('.bex-node-row');
  const card = wrap.querySelector('.bex-card');

  row.addEventListener('mouseenter', () => {
    const acts = row.querySelector('.bex-node-actions');
    if (acts) acts.style.display = 'flex';
    if (!isActive && !isCurrent) {
      card.style.background = 'var(--bg-3)';
      card.style.borderColor = 'var(--border)';
    }
  });
  row.addEventListener('mouseleave', () => {
    const acts = row.querySelector('.bex-node-actions');
    if (acts) acts.style.display = 'none';
    if (!isActive && !isCurrent) {
      card.style.background = 'transparent';
      card.style.borderColor = 'transparent';
    }
  });
  row.addEventListener('click', e => {
    if (e.target.closest('.bex-node-actions')) return;
    if (isRoot) { bexResetLeaf(null); return; }
    const leaf = _bexDeepestDescendant(msg.uuid, ctx.childrenOf, ctx.leafUuids);
    bexSetLeaf(leaf);
    setTimeout(() => {
      document.querySelector(`.msg[data-uuid="${msg.uuid}"]`)
        ?.scrollIntoView({ behavior:'smooth', block:'center' });
    }, 80);
  });

  container.appendChild(wrap);
}

function _bexRenderBranchFork(container, branches, depth, ctx) {
  const { currentChain, childrenOf, leafUuids } = ctx;
  const indentPx = depth * 14;

  // Fork divider
  const divider = document.createElement('div');
  divider.style.cssText = `padding:6px ${8}px 4px ${indentPx+36}px;display:flex;align-items:center;gap:6px;`;
  divider.innerHTML = `
    <div style="flex:1;height:1px;background:linear-gradient(90deg,rgba(250,204,21,.4),transparent)"></div>
    <span style="font-size:8px;font-family:var(--font-mono);font-weight:700;color:var(--yellow);white-space:nowrap;padding:2px 7px;border:1px solid rgba(250,204,21,.25);border-radius:10px;background:var(--yellow-dim);">
      ⎇ ${branches.length} BRANCHES
    </span>
    <div style="flex:1;height:1px;background:linear-gradient(270deg,rgba(250,204,21,.4),transparent)"></div>`;
  container.appendChild(divider);

  // Render each branch
  for (let i = 0; i < branches.length; i++) {
    const branch   = branches[i];
    const onPath   = currentChain.has(branch.uuid) || 
                     [...currentChain].some(id => {
                       // check if any chain member is descended from this branch
                       const n = ctx.byUuid[id];
                       return n?.parent_message_uuid === branch.parent_message_uuid;
                     });
    const isSelectedBranch = currentChain.has(branch.uuid) ||
      bexChainFrom(BEX.viewLeafUuid || '', ctx.byUuid)
        .some(m => m.uuid === branch.uuid);

    // Branch label strip
    const branchHeader = document.createElement('div');
    branchHeader.style.cssText = `
      padding: 2px 8px 2px ${indentPx + 36}px;
      display: flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
    `;
    branchHeader.innerHTML = `
      <div style="
        height: 14px;
        border-left: 2px solid ${isSelectedBranch ? 'var(--teal)' : 'var(--border)'};
        flex-shrink: 0;
        transition: border-color .2s;
      "></div>
      <span style="
        font-size: 8px;
        font-family: var(--font-mono);
        font-weight: 700;
        color: ${isSelectedBranch ? 'var(--teal)' : 'var(--text-4)'};
        letter-spacing: .06em;
        text-transform: uppercase;
        transition: color .2s;
      ">Branch ${i + 1}${isSelectedBranch ? '  ✓ active' : ''}</span>`;
    
    branchHeader.addEventListener('click', () => {
      const leaf = _bexDeepestDescendant(branch.uuid, childrenOf, leafUuids);
      bexSetLeaf(leaf);
    });
    container.appendChild(branchHeader);

    // Render nodes in this branch
    _bexRenderNode(container, branch, depth + 1, ctx);
    _bexRenderChildren(container, branch.uuid, depth + 1, ctx);

    // Gap between branches
    if (i < branches.length - 1) {
      const gap = document.createElement('div');
      gap.style.cssText = `
        height: 3px;
        margin: 2px ${8}px 2px ${indentPx + 52}px;
        border-top: 1px dashed var(--border-s);
      `;
      container.appendChild(gap);
    }
  }

  // Close fork
  const closer = document.createElement('div');
  closer.style.cssText = `
    padding: 2px 8px 8px ${indentPx + 36}px;
  `;
  closer.innerHTML = `
    <div style="height:1px;background:var(--border-s);margin-left:0"></div>`;
  container.appendChild(closer);
}

function _bexMakeNodeEl(msg, depth, ctx) {
  const { childrenOf, leafUuids, branchPoints, currentLeaf, currentChain } = ctx;
  const isRoot    = msg.uuid === ROOT_UUID;
  const isActive  = currentChain.has(msg.uuid);
  const isCurrent = msg.uuid === currentLeaf;
  const isBranchPt= branchPoints.has(msg.uuid);
  const isLeaf    = leafUuids.includes(msg.uuid);
  const children  = childrenOf[msg.uuid] || [];
  const hasChildren = children.length > 0;

  const preview = isRoot
    ? '— start —'
    : (msg.text || (msg.content || []).find(b => b.type === 'text')?.text || '')
        .slice(0, 60).replace(/\n/g, ' ');

  const ts = msg.created_at ? fmtTime(msg.created_at) : '';

  const senderClass = isRoot ? 'root' : msg.sender === 'human' ? 'human' : 'assistant';
  const senderLabel = isRoot ? 'ROOT' : msg.sender === 'human' ? 'YOU' : 'AI';

  const activeClass  = isActive  ? ' bex-active'       : '';
  const currentClass = isCurrent ? ' bex-current'      : '';
  const bpClass      = isBranchPt ? ' bex-branch-point': '';

  const branchBadge = isBranchPt && children.length > 1
    ? `<span class="bex-branch-badge">${children.length} branches</span>` : '';
  const leafBadge = isLeaf && !isRoot
    ? `<span style="font-size:9px;color:var(--text-4);font-family:var(--font-mono)">leaf</span>` : '';

  const actionsHtml = isRoot ? '' : `
    <div class="bex-node-actions">
      <button class="bex-node-btn view" title="View up to here"
              onclick="event.stopPropagation();bexViewFromNode('${msg.uuid}')">👁</button>
      <button class="bex-node-btn fork" title="Fork from here"
              onclick="event.stopPropagation();bexForkFromNode('${msg.uuid}')">⎇</button>
    </div>`;

  const wrapper = document.createElement('div');
  wrapper.style.paddingLeft = `${depth * 14}px`;
  wrapper.innerHTML = `
    <div class="bex-node${activeClass}${currentClass}${bpClass}" data-uuid="${msg.uuid}">
      <div class="bex-connector">
        <div class="bex-line-v"></div>
        <div class="bex-dot"></div>
        <div class="bex-line-v" style="${!hasChildren ? 'opacity:0' : ''}"></div>
      </div>
      <div class="bex-card">
        <div class="bex-card-top">
          <span class="bex-sender ${senderClass}">${senderLabel}</span>
          ${branchBadge}
          ${leafBadge}
          <span class="bex-ts">${ts}</span>
        </div>
        <div class="bex-preview">${esc(preview) || '&nbsp;'}</div>
      </div>
      ${actionsHtml}
    </div>`;

  wrapper.querySelector('.bex-node').addEventListener('click', () => {
    if (isRoot) { bexResetLeaf(null); return; }
    const leaf = _bexDeepestDescendant(msg.uuid, childrenOf, leafUuids);
    bexSetLeaf(leaf);
    setTimeout(() => {
      document.querySelector(`.msg[data-uuid="${msg.uuid}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 80);
  });

  return wrapper;
}


function _bexMakeSibBar(children, ctx) {
  const { childrenOf, leafUuids, currentChain } = ctx;

  const bar = document.createElement('div');
  bar.className = 'bex-siblings-bar';

  for (let i = 0; i < children.length; i++) {
    const child    = children[i];
    const isActive = currentChain.has(child.uuid);
    const preview  = (child.text || (child.content || []).find(b => b.type === 'text')?.text || '')
      .slice(0, 22).replace(/\n/g, ' ') || `branch ${i + 1}`;

    const btn = document.createElement('button');
    btn.className = 'bex-sib-btn' + (isActive ? ' active' : '');
    btn.textContent = `${i + 1}: ${preview}${preview.length >= 22 ? '…' : ''}`;
    btn.title = `Switch to branch ${i + 1}`;
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const leaf = _bexDeepestDescendant(child.uuid, childrenOf, leafUuids);
      bexSetLeaf(leaf);
    });
    bar.appendChild(btn);
  }

  return bar;
}

// View conversation chain up to (and including) a specific node
function bexViewFromNode(uuid) {
  bexSetLeaf(uuid);
  setTimeout(() => {
    const msgEl = document.querySelector(`.msg[data-uuid="${uuid}"]`);
    if (msgEl) msgEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 80);
}

// Fork: set this node as the send-parent so the next message branches from here
function bexForkFromNode(uuid) {
  BEX.sendParentUuid = uuid;
  // Update hidden input
  const sel = document.getElementById('branchSel');
  if (sel) sel.value = uuid;

  // Show the active pill
  const conv = S.convId ? S.convs[S.convId] : null;
  const msg  = conv?.chat_messages?.find(m => m.uuid === uuid);
  const preview = msg
    ? ((msg.text || (msg.content||[]).find(b=>b.type==='text')?.text || '') + '')
        .slice(0, 40).replace(/\n/g,' ')
    : uuid.slice(0, 8);
  const pill  = document.getElementById('bexActivePill');
  const label = document.getElementById('bexActivePillLabel');
  if (pill) pill.classList.add('visible');
  if (label) label.textContent = `Fork from: ${preview}${preview.length >= 40 ? '…' : ''}`;

  // Focus textarea
  document.getElementById('msgTa')?.focus();
  toast(`Next message will branch from: "${preview.slice(0,30)}…"`, 'info');
}

console.log('[BEX] Branch Explorer loaded');

function openInCanvasRaw(content, name, mime) {
  // Ensure canvas is visible
  const canvasPanel = document.getElementById('canvasPanel');
  if (canvasPanel) canvasPanel.style.display = '';
  if (!S.canvasOpen) toggleCanvas();
  switchCanvasTab('preview');

  document.getElementById('cvPreviewEmpty').style.display   = 'none';
  document.getElementById('cvPreviewContent').style.display = 'flex';
  document.getElementById('cvPreviewName').textContent = name;

  // Download button — create a real blob only for download (not for display)
  const dlBtn = document.getElementById('cvDlBtn');
  if (dlBtn) {
    const blob = new Blob([content], { type: mime });
    const url  = URL.createObjectURL(blob);
    dlBtn.href = url;
    dlBtn.download = name.toLowerCase().replace(/\s+/g, '-') + (
      mime.includes('svg') ? '.svg' :
      mime.includes('html') ? '.html' : '.txt'
    );
  }

  // Copy button
  const copyBtn = document.getElementById('cvCopyBtn');
  if (copyBtn) {
    copyBtn.style.display = '';
    copyBtn.dataset.canvasMime = mime;
    copyBtn.dataset.canvasUrl  = '';
    copyBtn.dataset.canvasRaw  = '';  // don't store raw here; handle below
    copyBtn.classList.remove('copied');
    copyBtn.textContent = '⎘ Copy';
    // Store content on the button directly for copyCanvasContent
    copyBtn._rawContent = content;
  }

  // Hide all viewers
  const frame   = document.getElementById('cvFrame');
  const imgWrap = document.getElementById('cvImgWrap');
  const codeEl  = document.getElementById('cvCode');
  const pdfEl   = document.getElementById('cvPdf');
  [frame, imgWrap, codeEl, pdfEl].forEach(el => { if (el) el.style.display = 'none'; });

  const m = mime.toLowerCase();

  if (m.includes('html')) {
    // Use srcdoc — no blob URL needed, no security error
    frame.style.display = 'block';
    frame.srcdoc = content;
    return;
  }

  if (m.includes('svg')) {
    // Inject SVG directly into a container
    codeEl.style.display = 'block';
    codeEl.innerHTML = content;  // SVG renders inline fine
    return;
  }

  // Fallback: plain text
  codeEl.style.display = 'block';
  codeEl.textContent = content;
}

/* ═══════════════════════════════════════════
   CLOUDFLARE CHALLENGE OVERLAY
═══════════════════════════════════════════ */
let _cfState     = null;
let _cfPollTimer = null;
let _cfPopup     = null;

function showCFOverlay(state) {
  _cfState = state;
  document.getElementById('cfOverlay').classList.add('active');
  _cfSetStatus('Click "Open popup" to complete the Cloudflare check', false);
  openCFPopup();
}

function beginCF() {
  const acctName = getTabAccountName() || '';
  fetch('/api/oneminai/cf-begin', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_name: acctName }),
  }).then(r => {
    if (!r.ok) { toast('Failed to start Cloudflare check', 'err'); return; }
    return r.json();
  }).then(d => {
    if (d && d.ok && d.state) {
      showCFOverlay(d.state);
    }
  }).catch(() => {
    toast('Failed to start Cloudflare check', 'err');
  });
}

function openCFPopup() {
  if (_cfPopup && !_cfPopup.closed) { _cfPopup.focus(); return; }
  const w = 520, h = 600;
  const l = Math.round(screen.width  / 2 - w / 2);
  const t = Math.round(screen.height / 2 - h / 2);
  _cfPopup = window.open(
    'https://app.1min.ai',
    'chatai_cf_check',
    `width=${w},height=${h},left=${l},top=${t},resizable=yes`
  );
  _cfSetStatus('Complete the Cloudflare check in the popup…', false);
  _cfStartPoll();
}

function closeCFOverlay() {
  _cfState = null;
  if (_cfPollTimer) { clearTimeout(_cfPollTimer); _cfPollTimer = null; }
  if (_cfPopup && !_cfPopup.closed) _cfPopup.close();
  _cfPopup = null;
  document.getElementById('cfOverlay').classList.remove('active');
}

function _cfSetStatus(msg, done) {
  const dot = document.getElementById('cfDot');
  const txt = document.getElementById('cfStatusTxt');
  const bar = document.getElementById('cfBar');
  if (txt) txt.textContent = msg;
  if (done) {
    dot?.classList.remove('waiting');
    dot?.classList.add('done');
    bar?.classList.add('done');
  } else {
    dot?.classList.remove('done');
    dot?.classList.add('waiting');
    bar?.classList.remove('done');
  }
}

function _cfStartPoll() {
  if (_cfPollTimer) clearTimeout(_cfPollTimer);
  _cfPollTimer = setTimeout(_cfPoll, 1500);
}

async function _cfPoll() {
  if (!_cfState) return;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);

    const r = await fetch(
      `/api/oneminai/cf-status?state=${encodeURIComponent(_cfState)}`,
      { signal: controller.signal }
    );

    clearTimeout(timer);

    if (r.ok) {
      const d = await r.json();
      if (d.done) {
        _cfSetStatus('✓ Cloudflare cleared — resuming…', true);
        if (_cfPopup && !_cfPopup.closed) _cfPopup.close();
        _cfPopup = null;
        setTimeout(closeCFOverlay, 2000);
        return;
      }
    }
  } catch { /* keep polling */ }
  _cfPollTimer = setTimeout(_cfPoll, 1500);
}

/* ── 1min.AI manual token refresh ── */
async function omaiManualRefresh(btn) {
  if (!btn) btn = document.getElementById('omaiRefreshBtn');
  const acct = getTabAccount();
  if (!acct || (acct.provider || '').toLowerCase() !== 'oneminai') {
    toast('Switch to a 1min.AI account first', 'err');
    return;
  }

  // Spinning state
  if (btn) btn.classList.add('spinning');

  try {
    const r = await apiFetch('/api/oneminai/refresh', { method: 'POST' });

    if (r.access_token) {
      // Patch in-memory account objects so next request uses new token
      if (S.tabAccount) {
        S.tabAccount.api_key = r.access_token;
        if (r.team_id) S.tabAccount.team_id = r.team_id;
      }
      const cached = S.accounts.find(a => a.name === acct.name);
      if (cached) {
        cached.api_key = r.access_token;
        if (r.team_id) cached.team_id = r.team_id;
      }
      // Force cache invalidation so next account list load is fresh
      _cache_invalidate_client();

      // Fetch fresh credits immediately after token rotation
      try {
        const usage = await apiFetch('/api/usage');
        if (usage.provider === 'oneminai' && usage.credits != null) {
          _cacheOneminai(acct.name, usage.credits);
          _renderSidebarBar();
          renderAccountMenu();
          _renderOmaiPanelFromCache();
        }
      } catch { /* non-fatal */ }

      toast('1min.AI token refreshed ✓', 'ok');
    } else {
      const msg = r.error || 'Refresh failed — check server logs';
      toast(msg, 'err');
    }
  } catch (err) {
    toast('Refresh error: ' + err.message, 'err');
  } finally {
    if (btn) btn.classList.remove('spinning');
  }
}

/* ═══════════════════════════════════════════
   ASK_USER_INPUT_V0 WIDGET
═══════════════════════════════════════════ */

const _askWidgets = {};

// ── question type renderers ───────────────────────────────────────────────

function _askRenderQuestion(widgetId, q, qi, state) {
  const qtype   = q.type || 'single_select';
  const options = q.options || [];
  const isMulti = qtype === 'multi_select';
  const isRank  = qtype === 'rank_priorities';
  const isFree  = qtype === 'free_text';

  let inputHtml = '';

  if (isFree) {
    const val = state.answers[qi] || '';
    inputHtml = `
      <textarea
        class="ask-free-input"
        id="${widgetId}_q${qi}"
        placeholder="Type your answer…"
        ${state.submitted ? 'disabled' : ''}
        oninput="_askUpdateFreeText('${widgetId}',${qi},this.value)"
      >${esc(val)}</textarea>`;

  } else if (isRank) {
    // answers[qi] is an ordered array of option indices
    if (!Array.isArray(state.answers[qi])) {
      state.answers[qi] = options.map((_, i) => i);
    }
    const order = state.answers[qi];
    const items = order.map((oi, rank) => `
      <div class="ask-rank-item"
           id="${widgetId}_q${qi}_rank${rank}"
           draggable="true"
           data-widget="${widgetId}"
           data-qi="${qi}"
           data-rank="${rank}"
           ondragstart="_askRankDragStart(event)"
           ondragover="_askRankDragOver(event)"
           ondrop="_askRankDrop(event)"
           ondragend="_askRankDragEnd(event)">
        <span class="ask-rank-handle">⠿</span>
        <span class="ask-rank-num">${rank + 1}</span>
        <span class="ask-rank-label">${esc(options[oi])}</span>
        <div class="ask-rank-arrows">
          <button class="ask-rank-arrow"
                  onclick="_askRankMove('${widgetId}',${qi},${rank},-1)"
                  ${rank === 0 ? 'disabled' : ''}>▲</button>
          <button class="ask-rank-arrow"
                  onclick="_askRankMove('${widgetId}',${qi},${rank},1)"
                  ${rank === order.length - 1 ? 'disabled' : ''}>▼</button>
        </div>
      </div>`).join('');
    inputHtml = `<div class="ask-rank-list" id="${widgetId}_q${qi}_list">${items}</div>`;

  } else {
    // single_select or multi_select
    const optionsHtml = options.map((opt, oi) => {
      const isSelected = isMulti
        ? (Array.isArray(state.answers[qi]) && state.answers[qi].includes(oi))
        : state.answers[qi] === oi;
      return `
        <div class="ask-option ${isMulti ? 'multi' : ''} ${isSelected ? 'selected' : ''}"
             onclick="_askToggleOption('${widgetId}',${qi},${oi},${isMulti})">
          <div class="ask-option-indicator"></div>
          <span class="ask-option-label">${esc(opt)}</span>
        </div>`;
    }).join('');
    inputHtml = `<div class="ask-options">${optionsHtml}</div>`;
  }

  return `
    <div class="ask-question-block">
      <div class="ask-question-text">${esc(q.question)}</div>
      ${inputHtml}
    </div>`;
}

// ── build full widget HTML ────────────────────────────────────────────────

function _askBuildHtml(widgetId, state) {
  const questions   = state.questions;
  const answeredCls = state.submitted ? ' answered' : '';

  const questionsHtml = questions
    .map((q, qi) => _askRenderQuestion(widgetId, q, qi, state))
    .join('');

  const footerHtml = state.submitted
    ? `<div class="ask-answered-note">✓ Answer submitted</div>`
    : `<button class="ask-submit-btn"
               onclick="_askSubmit('${widgetId}')"
               ${_askAllAnswered(state) ? '' : 'disabled'}>
         ↑ Send Answer
       </button>`;

  const titleText = questions.length === 1
    ? questions[0].question
    : `${questions.length} questions`;

  return `
    <div class="ask-widget-head">
      <span class="ask-widget-badge">${state.submitted ? 'ANSWERED' : 'INPUT'}</span>
      <span class="ask-widget-title">${esc(titleText)}</span>
    </div>
    <div class="ask-widget-body">
      ${questionsHtml}
      <div class="ask-submit-row">${footerHtml}</div>
    </div>`;
}

// ── public: render (called from renderBlock) ──────────────────────────────

function renderAskUserInputWidget(block, streaming) {
  const input     = block.input || {};
  const questions = input.questions || [];
  if (!questions.length) return '';

  const widgetId = 'ask_' + (block.id || Math.random().toString(36).slice(2, 9));

  if (!_askWidgets[widgetId]) {
    _askWidgets[widgetId] = {
      questions,
      answers:   questions.map(() => null),
      submitted: false,
    };
  }

  const state = _askWidgets[widgetId];

  if (streaming) {
    return `
      <div class="ask-widget" id="${widgetId}">
        <div class="ask-widget-head">
          <span class="ask-widget-badge">INPUT</span>
          <span class="ask-widget-title">Claude is asking…</span>
          <div class="think-pulse" style="margin-left:auto"></div>
        </div>
      </div>`;
  }

  return `
    <div class="ask-widget${state.submitted ? ' answered' : ''}" id="${widgetId}">
      ${_askBuildHtml(widgetId, state)}
    </div>`;
}

// ── re-render widget in place ─────────────────────────────────────────────

function _askRerender(widgetId) {
  const el    = document.getElementById(widgetId);
  const state = _askWidgets[widgetId];
  if (!el || !state) return;
  el.className = `ask-widget${state.submitted ? ' answered' : ''}`;
  el.innerHTML = _askBuildHtml(widgetId, state);
}

// ── interaction handlers ──────────────────────────────────────────────────

function _askAllAnswered(state) {
  return state.answers.every((a, i) => {
    const q = state.questions[i];
    if (!q) return true;
    const t = q.type || 'single_select';
    if (t === 'free_text')      return a && a.trim().length > 0;
    if (t === 'multi_select')   return Array.isArray(a) && a.length > 0;
    if (t === 'rank_priorities') return Array.isArray(a) && a.length > 0;
    return a !== null;  // single_select
  });
}

function _askToggleOption(widgetId, qi, oi, isMulti) {
  const state = _askWidgets[widgetId];
  if (!state || state.submitted) return;
  if (isMulti) {
    if (!Array.isArray(state.answers[qi])) state.answers[qi] = [];
    const idx = state.answers[qi].indexOf(oi);
    if (idx === -1) state.answers[qi].push(oi);
    else            state.answers[qi].splice(idx, 1);
  } else {
    state.answers[qi] = oi;
  }
  _askRerender(widgetId);
}

function _askUpdateFreeText(widgetId, qi, value) {
  const state = _askWidgets[widgetId];
  if (!state || state.submitted) return;
  state.answers[qi] = value;
  // just update submit button — no full rerender needed
  const btn = document.querySelector(`#${widgetId} .ask-submit-btn`);
  if (btn) btn.disabled = !_askAllAnswered(state);
}

// ── rank drag-and-drop ────────────────────────────────────────────────────

let _rankDragSrc = null;  // { widgetId, qi, rank }

function _askRankDragStart(e) {
  const el = e.currentTarget;
  _rankDragSrc = {
    widgetId: el.dataset.widget,
    qi:       parseInt(el.dataset.qi),
    rank:     parseInt(el.dataset.rank),
  };
  el.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function _askRankDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  e.currentTarget.classList.add('drag-over');
}

function _askRankDragEnd(e) {
  e.currentTarget.classList.remove('dragging');
  document.querySelectorAll('.ask-rank-item').forEach(el => {
    el.classList.remove('drag-over', 'dragging');
  });
}

function _askRankDrop(e) {
  e.preventDefault();
  const target = e.currentTarget;
  target.classList.remove('drag-over');
  if (!_rankDragSrc) return;

  const destRank = parseInt(target.dataset.rank);
  const srcRank  = _rankDragSrc.rank;
  const widgetId = _rankDragSrc.widgetId;
  const qi       = _rankDragSrc.qi;
  _rankDragSrc   = null;

  if (srcRank === destRank) return;

  const state = _askWidgets[widgetId];
  if (!state) return;

  const order = [...state.answers[qi]];
  const [moved] = order.splice(srcRank, 1);
  order.splice(destRank, 0, moved);
  state.answers[qi] = order;

  _askRerender(widgetId);
}

// ── rank arrow buttons ────────────────────────────────────────────────────

function _askRankMove(widgetId, qi, rank, dir) {
  const state = _askWidgets[widgetId];
  if (!state || state.submitted) return;

  const order   = [...state.answers[qi]];
  const newRank = rank + dir;
  if (newRank < 0 || newRank >= order.length) return;

  [order[rank], order[newRank]] = [order[newRank], order[rank]];
  state.answers[qi] = order;

  _askRerender(widgetId);
}

// ── submit ────────────────────────────────────────────────────────────────

async function _askSubmit(widgetId) {
  const state = _askWidgets[widgetId];
  if (!state || state.submitted || !_askAllAnswered(state)) return;
  if (!S.convId) return;

  const lines = state.questions.map((q, qi) => {
    const answer = state.answers[qi];
    const qtype  = q.type || 'single_select';
    const opts   = q.options || [];
    let   answerText = '';

    if (qtype === 'free_text') {
      answerText = (answer || '').trim();
    } else if (qtype === 'multi_select' && Array.isArray(answer)) {
      answerText = answer.map(i => opts[i]).filter(Boolean).join(', ');
    } else if (qtype === 'rank_priorities' && Array.isArray(answer)) {
      answerText = answer.map((oi, rank) => `${rank + 1}. ${opts[oi]}`).join(', ');
    } else {
      answerText = opts[answer] ?? String(answer);
    }

    return `Q: ${q.question}\nA: ${answerText}`;
  });

  const replyText = lines.join('\n');

  state.submitted = true;
  _askRerender(widgetId);

  const ta = document.getElementById('msgTa');
  if (ta) {
    ta.value = replyText;
    resizeTa(ta);
    updateCount(ta);
  }

  await doSend();
}
/* ═══════════════════════════════════════════
   BOOT
═══════════════════════════════════════════ */
init();
loadPollingConfig();

/* ── Mobile: initial state ── */
(function mobileSetup() {
  if (!_isMobile()) return;
  // Sidebar starts closed on mobile
  document.getElementById('sidebar')?.classList.remove('m-open');
  document.getElementById('app')?.classList.add('sb-collapsed');
  const ta = document.getElementById('msgTa');
  if (ta && ta.placeholder.length > 20) ta.placeholder = 'Message…';
})();

/* ── Swipe gestures ── */
(function swipeSetup() {
  let x0 = 0, y0 = 0, tgt0 = null;
  document.addEventListener('touchstart', e => {
    x0 = e.touches[0].clientX;
    y0 = e.touches[0].clientY;
    tgt0 = e.target;
  }, { passive: true });
  document.addEventListener('touchend', e => {
    if (!_isMobile()) return;
    const dx = e.changedTouches[0].clientX - x0;
    const dy = e.changedTouches[0].clientY - y0;
    if (Math.abs(dy) > Math.abs(dx) * 0.7 || Math.abs(dx) < 50) return;
    if (dx > 0 && x0 < 30 && !_isMobileSidebarOpen()) { toggleSidebar(); return; }
    if (dx < 0 && _isMobileSidebarOpen() && document.getElementById('sidebar')?.contains(tgt0)) { toggleSidebar(); return; }
    if (dx < -60) _closeAllPanels();
  }, { passive: true });
})();

/* ── iOS keyboard: keep messages in view ── */
if (window.visualViewport) {
  let _lastVH = window.visualViewport.height;
  window.visualViewport.addEventListener('resize', () => {
    if (!_isMobile()) return;
    if (window.visualViewport.height < _lastVH - 80) {
      const msgs = document.getElementById('msgs');
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
    }
    _lastVH = window.visualViewport.height;
  });
}

/* ═══════════════════ DIV DROPDOWNS ═══════════════════ */

let _ddOpen = null;

function ddClose() {
  if (!_ddOpen) return;
  _ddOpen.classList.remove('open');
  _ddOpen = null;
}

function ddOpen(wrap) {
  if (_ddOpen && _ddOpen !== wrap) ddClose();
  wrap.classList.add('open');
  _ddOpen = wrap;
  const menu = wrap.querySelector('.dd-menu');
  const rect = wrap.getBoundingClientRect();
  menu.classList.toggle('drop-up', window.innerHeight - rect.bottom < 280 && rect.top > 280);
  const opts = menu.querySelectorAll('.dd-option');
  const search = wrap.querySelector('.dd-search-wrap');
  if (search) search.classList.toggle('visible', opts.length > 6);
  if (opts.length > 6) {
    const inp = wrap.querySelector('.dd-search');
    if (inp) { inp.value = ''; ddFilter(wrap, ''); setTimeout(() => inp.focus(), 30); }
  } else {
    const sel = menu.querySelector('.dd-option.selected') || menu.querySelector('.dd-option');
    if (sel) { ddFocus(wrap, sel); }
  }
}

function ddToggle(wrap) {
  wrap.classList.contains('open') ? ddClose() : ddOpen(wrap);
}

function ddSelect(wrap, value) {
  const menu = wrap.querySelector('.dd-menu');
  menu.querySelectorAll('.dd-option').forEach(o => {
    const sel = o.dataset.value === String(value);
    o.classList.toggle('selected', sel);
    o.classList.remove('focused');
  });
  const chosen = menu.querySelector(`.dd-option[data-value="${CSS.escape(String(value))}"]`);
  const label = wrap.querySelector('.dd-label');
  if (label && chosen) {
    label.textContent = chosen.querySelector('span')?.textContent || chosen.textContent.trim();
  }
  wrap.dataset.value = value;
  ddClose();
  wrap.querySelector('.dd-btn')?.focus();
  wrap.dispatchEvent(new CustomEvent('dd-change', { detail: { value }, bubbles: true }));
}

function ddGetValue(wrap) {
  return wrap.dataset.value || '';
}

function ddSetValue(wrap, value) {
  const menu = wrap.querySelector('.dd-menu');
  menu.querySelectorAll('.dd-option').forEach(o => {
    o.classList.toggle('selected', o.dataset.value === String(value));
  });
  const chosen = menu.querySelector(`.dd-option[data-value="${CSS.escape(String(value))}"]`);
  const label = wrap.querySelector('.dd-label');
  if (label && chosen) {
    label.textContent = chosen.querySelector('span')?.textContent || chosen.textContent.trim();
  }
  wrap.dataset.value = value;
}

function ddFilter(wrap, query) {
  const q = query.toLowerCase().trim();
  let any = false;
  const menu = wrap.querySelector('.dd-menu');
  menu.querySelectorAll('.dd-option').forEach(el => {
    const show = !q || el.textContent.toLowerCase().includes(q);
    el.classList.toggle('hidden', !show);
    if (show) any = true;
  });
  menu.querySelectorAll('.dd-group-label').forEach(grp => {
    let next = grp.nextElementSibling;
    let vis = false;
    while (next && !next.classList.contains('dd-group-label')) {
      if (next.classList.contains('dd-option') && !next.classList.contains('hidden')) vis = true;
      next = next.nextElementSibling;
    }
    grp.classList.toggle('hidden', !vis);
  });
  let empty = menu.querySelector('.dd-empty');
  if (!any) {
    if (!empty) { empty = document.createElement('div'); empty.className = 'dd-empty'; empty.textContent = 'No matches'; menu.querySelector('.dd-list').appendChild(empty); }
    empty.style.display = '';
  } else if (empty) {
    empty.style.display = 'none';
  }
  menu.querySelectorAll('.dd-option.focused').forEach(el => el.classList.remove('focused'));
  const first = menu.querySelector('.dd-option:not(.hidden)');
  if (first) ddFocus(wrap, first);
}

function ddFocus(wrap, el) {
  wrap.querySelector('.dd-menu').querySelectorAll('.dd-option').forEach(o => o.classList.remove('focused'));
  el.classList.add('focused');
  el.scrollIntoView({ block: 'nearest' });
}

function ddMoveFocus(wrap, dir) {
  const menu = wrap.querySelector('.dd-menu');
  const opts = [...menu.querySelectorAll('.dd-option')].filter(o => !o.classList.contains('hidden'));
  if (!opts.length) return;
  const cur = menu.querySelector('.dd-option.focused');
  let idx = cur ? opts.indexOf(cur) : -1;
  opts.forEach(o => o.classList.remove('focused'));
  idx = Math.max(0, Math.min(opts.length - 1, idx + dir));
  opts[idx].classList.add('focused');
  opts[idx].scrollIntoView({ block: 'nearest' });
}

function ddKeyNav(e, wrap) {
  if (e.key === 'ArrowDown') { e.preventDefault(); wrap.classList.contains('open') ? ddMoveFocus(wrap, 1) : ddOpen(wrap); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); wrap.classList.contains('open') ? ddMoveFocus(wrap, -1) : ddOpen(wrap); }
  else if (e.key === 'Escape') { ddClose(); wrap.querySelector('.dd-btn')?.focus(); }
  else if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    if (!wrap.classList.contains('open')) { ddOpen(wrap); return; }
    const focused = wrap.querySelector('.dd-option.focused');
    if (focused) ddSelect(wrap, focused.dataset.value);
  }
}

function ddRebuild(wrap, groups) {
  // groups: [{label, options:[{value,text,badge}]}] or flat [{value,text,badge}]
  const list = wrap.querySelector('.dd-list');
  const curVal = ddGetValue(wrap);
  list.innerHTML = '';
  let firstVal = null;
  for (const g of groups) {
    if (g.label) {
      const grp = document.createElement('div');
      grp.className = 'dd-group-label';
      grp.textContent = g.label;
      list.appendChild(grp);
    }
    for (const o of (g.options || [g])) {
      if (!o.value && o.value !== 0) continue;
      if (firstVal === null) firstVal = o.value;
      const el = document.createElement('div');
      el.className = 'dd-option' + (String(o.value) === String(curVal) ? ' selected' : '');
      el.dataset.value = o.value;
      let inner = `<span style="flex:1;overflow:hidden;text-overflow:ellipsis">${o.text || o.value}</span>`;
      if (o.badge) inner += `<span class="dd-tier-${o.badge}">${o.badge === 'free' ? 'FREE' : 'PRO'}</span>`;
      el.innerHTML = inner;
      el.addEventListener('click', ev => { ev.stopPropagation(); ddSelect(wrap, o.value); });
      list.appendChild(el);
    }
  }
  // sync label
  const sel = list.querySelector('.dd-option.selected');
  const label = wrap.querySelector('.dd-label');
  if (label) label.textContent = sel ? (sel.querySelector('span')?.textContent || '') : (firstVal || '—');
  if (!sel && firstVal !== null) { wrap.dataset.value = firstVal; list.querySelector('.dd-option')?.classList.add('selected'); }
  const search = wrap.querySelector('.dd-search-wrap');
  if (search) search.classList.toggle('visible', list.querySelectorAll('.dd-option').length > 6);
}

document.addEventListener('click', e => {
  if (_ddOpen && !_ddOpen.contains(e.target)) ddClose();
}, true);

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && _ddOpen) ddClose();
});

function syncToolbarSeparators() {
  const toolbar = document.querySelector('.toolbar');
  if (!toolbar) return;
  const items = [...toolbar.children];

  function groupVisible(el) {
    if (!el || !el.classList.contains('tb-group')) return false;
    return [...el.children].some(c => c.style.display !== 'none');
  }

  // Hide all seps first
  items.forEach(el => {
    if (el.classList.contains('tb-sep')) el.classList.add('hidden');
  });

  // Get indices of visible groups only
  const vis = items.map((el, i) => groupVisible(el) ? i : -1).filter(i => i !== -1);

  // Between each consecutive pair of visible groups, show one sep
  for (let k = 0; k < vis.length - 1; k++) {
    const a = vis[k];
    const b = vis[k + 1];
    for (let j = a + 1; j < b; j++) {
      if (items[j].classList.contains('tb-sep')) {
        items[j].classList.remove('hidden');
        break;
      }
    }
  }
}
