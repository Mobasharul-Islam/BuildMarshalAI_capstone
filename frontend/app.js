/* ═══════════════════════════════════════════════
   BuildMarshal — Main Application
   Scalable chat, document preview, audio support, responsive
   ═══════════════════════════════════════════════ */
(function () {
  'use strict';

  // ═══ State ═══
  const state = {
    currentPage: 'all-projects',
    expandedGroups: { projects: true, companySettings: false },
    chats: {},
    activeChatId: null,
    uploadedDocs: [],
    isStreaming: false,
    isConnected: false,
    pendingFiles: [],
    trades: [],
    vendors: [],
    teamMembers: [],
    users: [],
    projects: [],
    _projectsMeta: { total: 0, page: 1, pages: 1, per_page: 10 },
    _projectFilters: { name: '', manager: '', types: [], statuses: [], startAfter: '', startBefore: '', endAfter: '', endBefore: '', showArchived: false },
    activeProjectId: null,
    projectTasks: []
  };

  // ═══ DOM Helpers ═══
  const $ = sel => document.querySelector(sel);
  const $$ = sel => document.querySelectorAll(sel);

  const DOM = {
    sidebar: $('#sidebar'),
    sidebarOverlay: $('#sidebarOverlay'),
    btnCloseSidebar: $('#btnCloseSidebar'),
    contentArea: $('#contentArea'),
    headerPageTitle: $('#headerPageTitle'),
    chatPanel: $('#chatPanel'),
    chatOverlay: $('#chatOverlay'),
    chatMessages: $('#chatMessages'),
    chatInput: $('#chatInput'),
    chatAttachments: $('#chatAttachments'),
    chatFileInput: $('#chatFileInput'),
    btnChatSend: $('#btnChatSend'),
    btnToggleChat: $('#btnToggleChat'),
    btnSidebarToggle: $('#btnSidebarToggle'),
    btnOpenChatMobile: $('#btnOpenChatMobile'),
    statusDot: $('#statusDot'),
    statusText: $('#statusText'),
    statusDotNav: $('#statusDotNav'),
    statusTextNav: $('#statusTextNav'),
    settingsModal: $('#settingsModal'),
    btnCloseSettings: $('#btnCloseSettings'),
    btnCancelSettings: $('#btnCancelSettings'),
    btnSaveSettings: $('#btnSaveSettings'),
    btnOpenSettings: $('#btnOpenSettings'),
    btnHeaderSettings: $('#btnHeaderSettings'),
    apiUrlInput: $('#apiUrlInput'),
    modelSelect: $('#modelSelect'),
    topKInput: $('#topKInput'),
    crudModal: $('#crudModal'),
    crudModalTitle: $('#crudModalTitle'),
    crudModalBody: $('#crudModalBody'),
    btnCloseCrud: $('#btnCloseCrud'),
    btnCancelCrud: $('#btnCancelCrud'),
    btnSaveCrud: $('#btnSaveCrud'),
    docPreviewModal: $('#docPreviewModal'),
    docPreviewTitle: $('#docPreviewTitle'),
    docPreviewBody: $('#docPreviewBody'),
    btnCloseDocPreview: $('#btnCloseDocPreview'),
    imagePreviewOverlay: $('#imagePreviewOverlay'),
    imagePreviewImg: $('#imagePreviewImg'),
    uploadPanel: $('#uploadPanel'),
    uploadPanelOverlay: $('#uploadPanelOverlay'),
    btnCloseUploadPanel: $('#btnCloseUploadPanel'),
    dropZone: $('#dropZone'),
    fileInput: $('#fileInput'),
    documentList: $('#documentList'),
    docTotalCount: $('#docTotalCount'),
    docCountBadge: $('#docCountBadge'),
    toastContainer: $('#toastContainer'),
    btnChatAttach: $('#btnChatAttach'),
    btnNewChat: $('#btnNewChat'),
    btnChatHistory: $('#btnChatHistory'),
    btnCloseHistory: $('#btnCloseHistory'),
    chatHistoryPanel: $('#chatHistoryPanel'),
    chatHistoryList: $('#chatHistoryList'),
    chatResizeHandle: $('#chatResizeHandle')
  };

  // ═══ Utilities ═══
  function genId() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
  function esc(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
  function fmtSize(b) { if (b < 1024) return b + ' B'; if (b < 1048576) return (b / 1024).toFixed(1) + ' KB'; return (b / 1048576).toFixed(1) + ' MB'; }
  function fmtTime(d) { return new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
  function getExt(n) { return (n.split('.').pop() || '').toLowerCase(); }

  function renderMd(text) {
    if (!text) return '';
    let h = esc(text);
    h = h.replace(/```(\w*)\n([\s\S]*?)```/g, (_, l, c) => `<pre><code>${c.trim()}</code></pre>`);
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*(.+?)\*/g, '<em>$1</em>');
    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
    h = h.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    h = h.replace(/\n\n/g, '</p><p>');
    h = h.replace(/\n/g, '<br>');
    h = '<p>' + h + '</p>';
    h = h.replace(/<p>\s*<\/p>/g, '');
    return h;
  }

  function showToast(msg, type = 'info', dur = 4000) {
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    const icons = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
    t.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${esc(msg)}</span>`;
    DOM.toastContainer.appendChild(t);
    setTimeout(() => { t.classList.add('leaving'); setTimeout(() => t.remove(), 300); }, dur);
  }

  // ═══ Auto-resize textarea ═══
  function autoResize(ta) {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  }

  // ═══ File preview helpers ═══
  function isImage(ext) { return APP_CONFIG.PREVIEWABLE_IMAGE.includes(ext); }
  function isAudio(ext) { return APP_CONFIG.PREVIEWABLE_AUDIO.includes(ext); }
  function isVideo(ext) { return APP_CONFIG.PREVIEWABLE_VIDEO.includes(ext); }
  function isPdf(ext) { return APP_CONFIG.PREVIEWABLE_PDF.includes(ext); }
  function isText(ext) { return APP_CONFIG.PREVIEWABLE_TEXT.includes(ext); }
  function getFileIcon(ext) { return APP_CONFIG.FILE_ICONS[ext] || '📄'; }
  function getFileClass(ext) { return APP_CONFIG.FILE_TYPE_CLASS[ext] || 'doc'; }

  // ═══ Persistence ═══
  function saveChats() {
    try {
      localStorage.setItem(APP_CONFIG.STORAGE_KEYS.CHATS, JSON.stringify(state.chats));
      localStorage.setItem(APP_CONFIG.STORAGE_KEYS.ACTIVE_CHAT, state.activeChatId || '');
    } catch (e) { }
  }
  function loadChats() {
    try {
      const r = localStorage.getItem(APP_CONFIG.STORAGE_KEYS.CHATS);
      if (r) state.chats = JSON.parse(r);
      state.activeChatId = localStorage.getItem(APP_CONFIG.STORAGE_KEYS.ACTIVE_CHAT) || null;
    } catch (e) { }
  }

  // ═══ API ═══
  function getApiUrl() { return APP_CONFIG.API_URL || localStorage.getItem(APP_CONFIG.STORAGE_KEYS.API_URL) || ''; }

  async function apiReq(endpoint, opts = {}) {
    const base = getApiUrl();
    if (!base) throw new Error('Backend URL not configured. Open Settings.');
    const res = await fetch(`${base.replace(/\/$/, '')}${endpoint}`, {
      ...opts, headers: { ...opts.headers, 'ngrok-skip-browser-warning': 'true' }
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `API error: ${res.status}`); }
    return res;
  }

  async function checkConnection() {
    try {
      const base = getApiUrl();
      if (!base) { setConn('disconnected'); return; }
      setConn('connecting');
      const r = await apiReq('/api/health');
      const d = await r.json();
      d.status === 'healthy' ? setConn('connected') : setConn('disconnected');
      state.isConnected = d.status === 'healthy';
    } catch (e) { setConn('disconnected'); state.isConnected = false; }
  }

  function setConn(s) {
    const labels = { connected: 'Connected', disconnected: 'Disconnected', connecting: 'Connecting...' };
    DOM.statusDot.className = `status-dot ${s}`;
    DOM.statusText.textContent = labels[s] || s;
    DOM.statusDotNav.className = `status-dot ${s}`;
    DOM.statusTextNav.textContent = labels[s] || s;
  }

  // ═══ Data Fetching ═══
  async function fetchTrades() {
    try { const r = await apiReq('/api/trades'); const d = await r.json(); state.trades = d.trades || []; } catch (e) { state.trades = []; }
  }
  async function fetchVendors() {
    try { const r = await apiReq('/api/vendors'); const d = await r.json(); state.vendors = d.vendors || []; } catch (e) { state.vendors = []; }
  }
  async function fetchTeamMembers() {
    try { const r = await apiReq('/api/team-members'); const d = await r.json(); state.teamMembers = d.team_members || []; } catch (e) { state.teamMembers = []; }
  }
  async function fetchUsers() {
    try { const r = await apiReq('/api/users'); const d = await r.json(); state.users = d.users || []; } catch (e) { state.users = []; }
  }
  async function fetchProjects(extra = '') {
    try {
      const f = state._projectFilters;
      const params = new URLSearchParams();
      if (f.name) params.set('name', f.name);
      if (f.manager) params.set('manager', f.manager);
      if (f.types.length) params.set('type', f.types.join(','));
      if (f.statuses.length) params.set('status', f.statuses.join(','));
      if (f.showArchived) params.set('show_archived', 'true');
      if (f.startAfter) params.set('start_after', f.startAfter);
      if (f.startBefore) params.set('start_before', f.startBefore);
      if (f.endAfter) params.set('end_after', f.endAfter);
      if (f.endBefore) params.set('end_before', f.endBefore);
      params.set('page', state._projectsMeta.page);
      params.set('per_page', state._projectsMeta.per_page);
      const r = await apiReq(`/api/projects?${params}`);
      const d = await r.json();
      state.projects = d.projects || [];
      state._projectsMeta = { total: d.total || 0, page: d.page || 1, pages: d.pages || 1, per_page: d.per_page || 10 };
    } catch (e) { state.projects = []; }
  }
  async function fetchProjectTasks(projectId) {
    try {
      const r = await apiReq(`/api/projects/${projectId}/tasks`);
      const d = await r.json();
      state.projectTasks = d.tasks || [];
    } catch (e) { state.projectTasks = []; }
  }
  async function fetchDocuments() {
    try {
      const r = await apiReq('/api/documents');
      const d = await r.json();
      // Normalise: backend `pages` field = page_count; keep both consistent
      state.uploadedDocs = (d.documents || []).map(doc => ({
        ...doc,
        pages: doc.pages ?? doc.page_count ?? 0,
        page_count: doc.page_count ?? doc.pages ?? 0,
      }));
      renderDocList();
      updateDocBadge();
    } catch (e) { state.uploadedDocs = []; }
  }
  function updateDocBadge() {
    if (state.uploadedDocs.length > 0) {
      DOM.docCountBadge.textContent = state.uploadedDocs.length;
      DOM.docCountBadge.style.display = 'inline';
    } else { DOM.docCountBadge.style.display = 'none'; }
  }
  async function fetchAllData() {
    if (!getApiUrl()) return;
    await Promise.all([fetchTrades(), fetchVendors(), fetchTeamMembers(), fetchDocuments(), fetchUsers(), fetchProjects()]);
    renderPage();
  }

  // ═══ Navigation ═══
  const PAGE_TITLES = {
    'all-projects': 'Projects', 'project-details': 'Project Details',
    'trades': 'Trades Management', 'vendors': 'Vendors Management',
    'documents': 'Documents', 'marshal-chat': 'Marshal Chat',
    'users': 'User', 'contact': 'Contact', 'my-feedback': 'My Feedback',
    'company-info': 'Company Info', 'project-types': 'Project Types',
    'task-types': 'Task Types', 'tasks': 'Tasks', 'calendar': 'Calendar'
  };

  function navigateTo(page) {
    state.currentPage = page;
    $$('.nav-item').forEach(i => i.classList.remove('active'));
    const active = $(`.nav-item[data-page="${page}"]`);
    if (active) active.classList.add('active');
    if (['all-projects', 'project-details'].includes(page)) state.expandedGroups.projects = true;
    if (['trades', 'vendors', 'users', 'contact', 'my-feedback', 'company-info', 'project-types', 'task-types'].includes(page))
      state.expandedGroups.companySettings = true;
    updateNavGroups();
    DOM.headerPageTitle.textContent = PAGE_TITLES[page] || page;
    renderPage();
    closeSidebar();
  }

  function updateNavGroups() {
    document.querySelectorAll('.nav-group').forEach(g => {
      const hdr = g.querySelector('.nav-group-header');
      const key = hdr?.dataset.group;
      if (key && state.expandedGroups[key]) g.classList.add('expanded');
      else g.classList.remove('expanded');
    });
  }

  function renderPage() {
    const page = state.currentPage;
    switch (page) {
      case 'all-projects': renderAllProjectsPage(); break;
      case 'project-details': renderProjectDashboard(state.activeProjectId); break;
      case 'trades': DOM.contentArea.innerHTML = renderTradesPage(); break;
      case 'vendors': DOM.contentArea.innerHTML = renderVendorsPage(); break;
      case 'documents': DOM.contentArea.innerHTML = renderDocumentsPage(); break;
      case 'marshal-chat': DOM.contentArea.innerHTML = renderChatFullPage(); showChat(); break;
      case 'users': renderUsersPage(); break;
      case 'create-user': renderCreateUserPage(); break;
      case 'edit-user': renderEditUserPage(state._editUserId); break;
      case 'tasks': case 'calendar':
      case 'contact': case 'my-feedback': case 'company-info': case 'project-types': case 'task-types':
        DOM.contentArea.innerHTML = `<div class="empty-state"><span class="material-icons-outlined">construction</span><h3>${PAGE_TITLES[page] || page}</h3><p>This section is coming soon.</p></div>`; break;
      default: renderAllProjectsPage(); break;
    }
    bindPageEvents();
  }

  // ═══ Page Renderers ═══
  function notConnectedMsg() {
    if (getApiUrl()) return '';
    return `<div class="connection-banner">
      <span class="material-icons-outlined">cloud_off</span>
      <span>Backend not connected.</span>
      <button class="btn btn-primary btn-sm" onclick="document.getElementById('btnOpenSettings').click()">Open Settings</button>
    </div>`;
  }

  function renderProjectDetails() {
    const internal = state.teamMembers.filter(m => m.category === 'internal');
    const vendors = state.teamMembers.filter(m => m.category === 'vendor');
    const contractors = state.teamMembers.filter(m => m.category === 'contractor');
    const consultants = state.teamMembers.filter(m => m.category === 'consultant');
    const cards = [
      { title: 'Internal Team', members: internal, cols: ['Name', 'Email', 'Department'], getRow: m => [m.name, m.email, m.department || '—'] },
      { title: 'Subcontractors & Trades', members: contractors, cols: ['Name', 'Company'], getRow: m => [m.name, m.company || '—'] },
      { title: 'Consultants & Designers', members: consultants, cols: ['Name', 'Company'], getRow: m => [m.name, m.company || '—'] },
      { title: 'Vendors & Suppliers', members: vendors, cols: ['Vendor', 'Contact', 'Email'], getRow: m => [m.company || m.name, m.contactName || '—', m.email || '—'] }
    ];
    return `${notConnectedMsg()}<div class="team-grid">${cards.map(c => `
      <div class="team-card"><div class="team-card-header">
        <span class="team-card-title">${c.title} (${c.members.length})</span>
        <button class="btn btn-primary btn-sm" data-action="add-team" data-cat="${c.title}"><span class="material-icons-outlined" style="font-size:16px">add</span> Add</button>
      </div><div class="team-card-body">
        ${c.members.length ? `<table><thead><tr>${c.cols.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${c.members.map(m => `<tr>${c.getRow(m).map(v => `<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>` : `<div class="empty-msg">No ${c.title.toLowerCase()} yet</div>`}
      </div></div>`).join('')}</div>`;
  }

  function renderTradesPage() {
    return `${notConnectedMsg()}
      <div class="page-header"><h1 class="page-title">Trades Management</h1>
        <button class="btn btn-primary" id="btnCreateTrade"><span class="material-icons-outlined">add</span> Create Trade</button></div>
      <div class="filters-bar"><div class="filters-row">
        <div class="filter-group"><div class="filter-label">Search</div><input class="filter-input search" id="tradeSearch" placeholder="Search by name..."></div>
        <div class="filter-group"><div class="filter-label">Status</div><select class="filter-input" id="tradeStatusFilter"><option value="">All</option><option value="Active">Active</option><option value="Inactive">Inactive</option></select></div>
      </div><div class="filters-meta"><span class="total-count">Total: ${state.trades.length}</span></div></div>
      <div class="data-table-container"><table class="data-table" id="tradesTable">
        <thead><tr><th>Name</th><th>Description</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>${state.trades.length ? state.trades.map(t => `<tr data-id="${t.id}"><td>${esc(t.name)}</td><td>${esc(t.description)}</td><td><span class="badge ${t.status === 'Active' ? 'badge-active' : 'badge-inactive'}">${t.status}</span></td><td><div class="table-actions"><button class="btn-table-action" data-action="edit-trade" data-id="${t.id}" title="Edit"><span class="material-icons-outlined">edit</span></button><button class="btn-table-action delete" data-action="delete-trade" data-id="${t.id}" title="Delete"><span class="material-icons-outlined">delete</span></button></div></td></tr>`).join('') : `<tr><td colspan="4" class="td-empty">${getApiUrl() ? 'No trades found' : 'Connect backend to load trades'}</td></tr>`}</tbody></table></div>`;
  }

  function renderVendorsPage() {
    return `${notConnectedMsg()}
      <div class="breadcrumb"><a href="#" data-nav="project-details"><span class="material-icons-outlined">home</span></a><span class="sep">/</span><span>Company Settings</span><span class="sep">/</span><span>Vendors</span></div>
      <div class="page-header"><h1 class="page-title">Vendors Management</h1>
        <button class="btn btn-primary" id="btnCreateVendor"><span class="material-icons-outlined">add</span> Create Vendor</button></div>
      <div class="filters-bar"><div class="filters-row">
        <div class="filter-group"><div class="filter-label">Search</div><input class="filter-input search" id="vendorSearch" placeholder="Search by name..."></div>
        <div class="filter-group"><div class="filter-label">Status</div><select class="filter-input" id="vendorStatusFilter"><option value="">All</option><option value="Active">Active</option><option value="Inactive">Inactive</option></select></div>
      </div><div class="filters-meta"><span class="total-count">Total: ${state.vendors.length}</span></div></div>
      <div class="data-table-container"><table class="data-table" id="vendorsTable">
        <thead><tr><th>Vendor Name</th><th>Type</th><th>Trade</th><th class="hide-mobile">Active Projects</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>${state.vendors.length ? state.vendors.map(v => `<tr data-id="${v.id}"><td>${esc(v.name)}</td><td><span class="badge badge-blue">${v.vendorType || '—'}</span></td><td>${esc(v.trade || '—')}</td><td class="hide-mobile">${v.activeProjects || 0}</td><td><span class="badge ${v.status === 'Active' ? 'badge-active' : 'badge-inactive'}">${v.status}</span></td><td><div class="table-actions"><button class="btn-table-action" data-action="edit-vendor" data-id="${v.id}" title="Edit"><span class="material-icons-outlined">edit</span></button><button class="btn-table-action delete" data-action="delete-vendor" data-id="${v.id}" title="Delete"><span class="material-icons-outlined">delete</span></button></div></td></tr>`).join('') : `<tr><td colspan="6" class="td-empty">${getApiUrl() ? 'No vendors found' : 'Connect backend to load vendors'}</td></tr>`}</tbody></table></div>`;
  }

  function renderDocumentsPage() {
    return `${notConnectedMsg()}
      <div class="page-header"><h1 class="page-title">Documents</h1>
        <button class="btn btn-primary" id="btnUploadDocs"><span class="material-icons-outlined">upload_file</span> Upload</button></div>
      ${state.uploadedDocs.length ? `<div class="doc-cards-grid">${state.uploadedDocs.map(d => {
      const ext = getExt(d.name);
      const icon = getFileIcon(ext);
      const cls = getFileClass(ext);
      const previewable = isImage(ext) || isAudio(ext) || isVideo(ext) || isPdf(ext) || isText(ext);
      return `<div class="doc-card" data-doc-id="${d.id}" data-name="${esc(d.name)}">
          <div class="doc-card-icon ${cls}">${icon}</div>
          <div class="doc-card-info">
            <div class="doc-card-name">${esc(d.name)}</div>
            <div class="doc-card-meta">${d.pages ? d.pages + ' pages' : ext.toUpperCase()} · <span class="badge ${d.status === 'indexed' ? 'badge-active' : 'badge-inactive'}" style="font-size:0.68rem">${d.status || '—'}</span></div>
          </div>
          <div class="doc-card-actions">
            ${previewable ? `<button class="btn-table-action" data-action="preview-doc" data-id="${d.id}" data-name="${esc(d.name)}" title="Preview"><span class="material-icons-outlined">visibility</span></button>` : ''}
            <button class="btn-table-action delete" data-action="delete-doc" data-id="${d.id}" title="Delete"><span class="material-icons-outlined">delete</span></button>
          </div>
        </div>`;
    }).join('')}</div>` : `<div class="empty-state"><span class="material-icons-outlined">folder_open</span><h3>No documents uploaded</h3><p>${getApiUrl() ? 'Upload documents to enable AI chat. Supports PDFs, images, audio, Excel, Word, and more.' : 'Connect backend to manage documents.'}</p></div>`}`;
  }

  function renderChatFullPage() {
    return `<div class="empty-state">
      <span class="material-icons-outlined">smart_toy</span>
      <h3>Marshal Chat</h3>
      <p>Ask questions about your uploaded documents. Upload PDFs, images, audio files, and more.</p>
    </div>`;
  }

  // ═══ Projects Module ═══

  const PROJECT_STATUSES = ['Active', 'On Hold', 'Completed', 'Cancelled'];
  const PROJECT_TYPES = ['Residential', 'Commercial', 'Industrial', 'Renovation', 'Infrastructure', 'Interior'];

  // ── All Projects Page ───────────────────────────────────────────────────────
  function renderAllProjectsPage() {
    const m = state._projectsMeta;
    const f = state._projectFilters;

    const rows = state.projects.length
      ? state.projects.map(p => `
        <tr>
          <td><a href="#" class="project-link" data-action="open-project" data-id="${p.id}">${esc(p.name)}</a></td>
          <td>${esc(p.project_code)}</td>
          <td>${esc(p.manager || '—')}</td>
          <td>${p.type ? `<span class="badge badge-blue">${esc(p.type)}</span>` : '—'}</td>
          <td>${p.start_date || '—'}</td>
          <td>${p.end_date || '—'}</td>
          <td><span class="badge ${p.status === 'Active' ? 'badge-active' : p.status === 'Completed' ? 'badge-role-admin' : 'badge-inactive'}">${esc(p.status)}</span></td>
          <td>
            <div class="table-actions">
              <button class="btn-table-action" data-action="open-project" data-id="${p.id}" title="View"><span class="material-icons-outlined">open_in_new</span></button>
              <button class="btn-table-action" data-action="edit-project" data-id="${p.id}" title="Edit"><span class="material-icons-outlined">edit</span></button>
              <button class="btn-table-action delete" data-action="delete-project" data-id="${p.id}" title="Delete"><span class="material-icons-outlined">delete</span></button>
            </div>
          </td>
        </tr>`).join('')
      : `<tr><td colspan="8" class="td-empty">${getApiUrl() ? 'No projects found. Click <b>New Project</b> to create one.' : 'Connect backend to load projects.'}</td></tr>`;

    // Pagination
    const paging = m.pages > 1 ? `
      <div class="pagination-bar">
        <button class="btn btn-sm btn-ghost" data-action="proj-page" data-id="${m.page - 1}" ${m.page <= 1 ? 'disabled' : ''}><span class="material-icons-outlined">chevron_left</span></button>
        <span class="page-info">${m.page}</span>
        <button class="btn btn-sm btn-ghost" data-action="proj-page" data-id="${m.page + 1}" ${m.page >= m.pages ? 'disabled' : ''}><span class="material-icons-outlined">chevron_right</span></button>
        <span class="per-page-label">10 / page</span>
      </div>` : '';

    DOM.contentArea.innerHTML = `
      <div class="page-header">
        <h1 class="page-title">Projects</h1>
        <div class="header-actions">
          <button class="btn btn-ghost btn-sm" id="btnRefreshProjects"><span class="material-icons-outlined">refresh</span> Refresh</button>
          <button class="btn btn-primary" id="btnNewProject"><span class="material-icons-outlined">add</span> New Project</button>
        </div>
      </div>
      <div class="filters-bar">
        <div class="filters-row">
          <div class="filter-group">
            <div class="filter-label">Name</div>
            <input class="filter-input" id="projNameFilter" placeholder="Filter by name (min 2 ch...)" value="${esc(f.name)}">
          </div>
          <div class="filter-group">
            <div class="filter-label">Manager</div>
            <input class="filter-input" id="projManagerFilter" placeholder="Filter by manager (min..." value="${esc(f.manager)}">
          </div>
          <div class="filter-group">
            <div class="filter-label">Type</div>
            <div class="multi-select-wrap" id="projTypeWrap">
              <div class="multi-select-display" id="projTypeDisplay">${f.types.length ? f.types.map(t => `<span class="chip">${esc(t)} <button class="chip-x" data-type="${esc(t)}">×</button></span>`).join('') : '<span class="placeholder">Select type(s)</span>'}</div>
              <div class="multi-select-dropdown" id="projTypeDropdown">
                ${PROJECT_TYPES.map(t => `<label><input type="checkbox" class="proj-type-chk" value="${t}" ${f.types.includes(t) ? 'checked' : ''}> ${t}</label>`).join('')}
              </div>
            </div>
          </div>
          <div class="filter-group">
            <div class="filter-label">Status</div>
            <div class="multi-select-wrap" id="projStatusWrap">
              <div class="multi-select-display" id="projStatusDisplay">${f.statuses.length ? f.statuses.map(s => `<span class="chip">${esc(s)} <button class="chip-x" data-status="${esc(s)}">×</button></span>`).join('') : '<span class="placeholder">Select status(es)</span>'}</div>
              <div class="multi-select-dropdown" id="projStatusDropdown">
                ${PROJECT_STATUSES.map(s => `<label><input type="checkbox" class="proj-status-chk" value="${s}" ${f.statuses.includes(s) ? 'checked' : ''}> ${s}</label>`).join('')}
              </div>
            </div>
          </div>
          <div class="filter-group">
            <div class="filter-label">Start Date (Range)</div>
            <div class="date-range-row">
              <input type="date" class="filter-input date-input" id="projStartAfter" value="${f.startAfter}" placeholder="Start date">
              <span class="date-arrow">→</span>
              <input type="date" class="filter-input date-input" id="projStartBefore" value="${f.startBefore}" placeholder="End date">
            </div>
          </div>
          <div class="filter-group">
            <div class="filter-label">End Date (Range)</div>
            <div class="date-range-row">
              <input type="date" class="filter-input date-input" id="projEndAfter" value="${f.endAfter}" placeholder="Start date">
              <span class="date-arrow">→</span>
              <input type="date" class="filter-input date-input" id="projEndBefore" value="${f.endBefore}" placeholder="End date">
            </div>
          </div>
        </div>
        <div class="filters-meta">
          <label class="archive-check"><input type="checkbox" id="projShowArchived" ${f.showArchived ? 'checked' : ''}> Show Archived Projects</label>
          <span class="total-count">Total: ${m.total}</span>
          <button class="btn btn-ghost btn-sm" id="btnClearProjFilters">Clear</button>
        </div>
      </div>
      <div class="data-table-container">
        <table class="data-table">
          <thead><tr><th>Name</th><th>Project Code</th><th>Manager</th><th>Type</th><th>Start</th><th>End</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${paging}`;
  }

  // ── Project Dashboard ───────────────────────────────────────────────────────
  function renderProjectDashboard(projectId) {
    const p = state.projects.find(x => x.id === projectId) || null;
    if (!p) {
      DOM.contentArea.innerHTML = `
        <div class="page-header"><h1 class="page-title">Project Details</h1></div>
        <div class="empty-state">
          <span class="material-icons-outlined">folder_open</span>
          <h3>No Project Selected</h3>
          <p><button class="btn btn-ghost btn-sm" data-action="nav-all-projects">← All Projects</button></p>
        </div>`;
      return;
    }
    const activeTab = state._dashTab || 'overview';
    const tasksHtml = renderProjectTasksSection();

    DOM.contentArea.innerHTML = `
      <div class="proj-dash-header">
        <div class="proj-dash-name">${esc(p.name)}</div>
        <div class="proj-dash-actions">
          <button class="btn btn-ghost btn-sm" data-action="edit-project" data-id="${p.id}"><span class="material-icons-outlined">edit</span> Edit</button>
          <span class="badge ${p.status === 'Active' ? 'badge-active' : 'badge-inactive'} badge-lg">${esc(p.status)}</span>
          ${!p.archived
        ? `<button class="btn btn-ghost btn-sm" data-action="archive-project" data-id="${p.id}"><span class="material-icons-outlined">archive</span> Archive</button>`
        : `<button class="btn btn-ghost btn-sm" data-action="unarchive-project" data-id="${p.id}"><span class="material-icons-outlined">unarchive</span> Restore</button>`
      }
        </div>
      </div>
      <div class="tab-strip">
        <button class="tab-btn ${activeTab === 'overview' ? 'active' : ''}" data-tab="overview">Overview</button>
        <button class="tab-btn ${activeTab === 'people' ? 'active' : ''}" data-tab="people">People</button>
        <button class="tab-btn ${activeTab === 'cost' ? 'active' : ''}" data-tab="cost">Cost</button>
        <button class="tab-btn ${activeTab === 'timeline' ? 'active' : ''}" data-tab="timeline">Timeline</button>
        <button class="tab-btn ${activeTab === 'procore' ? 'active' : ''}" data-tab="procore">Procore</button>
      </div>
      <div class="tab-content" id="dashTabContent">
        ${activeTab === 'overview' ? renderDashOverview(p, tasksHtml) : `<div class="empty-state"><span class="material-icons-outlined">construction</span><h3>${activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}</h3><p>Coming soon.</p></div>`}
      </div>`;
  }

  function renderDashOverview(p, tasksHtml) {
    const field = (label, value) => `
      <div class="detail-field">
        <div class="detail-label">${label}</div>
        <div class="detail-value">${value || '—'}</div>
      </div>`;
    return `
      <div class="overview-section">
        <div class="overview-header">
          <h2>Project Overview</h2>
        </div>
        <div class="detail-grid">
          ${field('NAME', p.name)}
          ${field('PROJECT CODE', p.project_code)}
          ${field('PROJECT MANAGER', p.manager)}
          ${field('TYPE', p.type)}
          ${field('PROJECT STATUS', p.status)}
          ${''}
          ${field('START DATE', p.start_date)}
          ${field('END DATE', p.end_date)}
        </div>
        ${p.description ? `<div class="detail-field full-width"><div class="detail-label">DESCRIPTION</div><div class="detail-value">${esc(p.description)}</div></div>` : ''}

        <h3 class="section-sub-title">Address</h3>
        <div class="detail-grid">
          ${field('LINE 1', p.address_line1)}
          ${field('LINE 2', p.address_line2)}
          ${field('CITY', p.city)}
          ${field('STATE', p.state)}
          ${field('POSTAL CODE', p.postal_code)}
          ${field('COUNTRY', p.country)}
        </div>

        <div class="tasks-section-header">
          <h3 class="section-sub-title">Project Tasks</h3>
          <div class="tasks-section-actions">
            <button class="btn btn-primary btn-sm" id="btnOpenTasks">Open Tasks</button>
            <button class="btn btn-ghost btn-sm" id="btnRefreshTasks"><span class="material-icons-outlined">refresh</span></button>
          </div>
        </div>
        <div id="projTasksList">${tasksHtml}</div>
      </div>`;
  }

  function renderProjectTasksSection() {
    if (!state.projectTasks.length)
      return `<div class="empty-msg">No tasks yet. Click <b>Open Tasks</b> to add one.</div>`;
    return state.projectTasks.map(t => `
      <div class="task-row" data-task-id="${t.id}">
        <span class="material-icons-outlined task-expand-icon">chevron_right</span>
        <span class="task-status-icon ${t.status === 'Completed' ? 'task-done' : ''}">
          <span class="material-icons-outlined">${t.status === 'Completed' ? 'check_circle' : 'radio_button_unchecked'}</span>
        </span>
        <span class="task-name">${esc(t.name)}</span>
        <span class="task-status-chip ${t.status === 'Completed' ? 'chip-done' : 'chip-open'}">${t.status}</span>
      </div>`).join('');
  }

  // ── Project Modal (Create / Edit) ───────────────────────────────────────────
  function openProjectModal(pid = null) {
    const p = pid ? state.projects.find(x => x.id === pid) : null;
    const title = p ? 'Edit Project' : 'New Project';
    DOM.crudModalTitle.textContent = title;
    DOM.crudModalBody.innerHTML = `
      <div class="form-grid-2">
        <div class="form-group">
          <label class="form-label required">Project Name</label>
          <input class="form-input" id="projFName" value="${esc(p?.name || '')}" placeholder="Project name">
        </div>
        <div class="form-group">
          <label class="form-label required">Project Code</label>
          <input class="form-input" id="projFCode" value="${esc(p?.project_code || '')}" placeholder="e.g. PPWV">
        </div>
        <div class="form-group">
          <label class="form-label">Project Manager</label>
          <input class="form-input" id="projFMgr" value="${esc(p?.manager || '')}" placeholder="Manager name">
        </div>
        <div class="form-group">
          <label class="form-label">Type</label>
          <select class="form-input" id="projFType">
            <option value="">— Select —</option>
            ${PROJECT_TYPES.map(t => `<option value="${t}" ${p?.type === t ? 'selected' : ''}>${t}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Status</label>
          <select class="form-input" id="projFStatus">
            ${PROJECT_STATUSES.map(s => `<option value="${s}" ${(p?.status || 'Active') === s ? 'selected' : ''}>${s}</option>`).join('')}
          </select>
        </div>
        <div class="form-group"></div>
        <div class="form-group">
          <label class="form-label">Start Date</label>
          <input type="date" class="form-input" id="projFStart" value="${esc(p?.start_date || '')}">
        </div>
        <div class="form-group">
          <label class="form-label">End Date</label>
          <input type="date" class="form-input" id="projFEnd" value="${esc(p?.end_date || '')}">
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">Description</label>
        <textarea class="form-input" id="projFDesc" rows="3" placeholder="Project description">${esc(p?.description || '')}</textarea>
      </div>
      <p class="section-sub-title" style="margin:1rem 0 .5rem">Address</p>
      <div class="form-grid-2">
        <div class="form-group">
          <label class="form-label">Line 1</label>
          <input class="form-input" id="projFAddr1" value="${esc(p?.address_line1 || '')}">
        </div>
        <div class="form-group">
          <label class="form-label">Line 2</label>
          <input class="form-input" id="projFAddr2" value="${esc(p?.address_line2 || '')}">
        </div>
        <div class="form-group">
          <label class="form-label">City</label>
          <input class="form-input" id="projFCity" value="${esc(p?.city || '')}">
        </div>
        <div class="form-group">
          <label class="form-label">State / Province</label>
          <input class="form-input" id="projFState" value="${esc(p?.state || '')}">
        </div>
        <div class="form-group">
          <label class="form-label">Postal Code</label>
          <input class="form-input" id="projFPostal" value="${esc(p?.postal_code || '')}">
        </div>
        <div class="form-group">
          <label class="form-label">Country</label>
          <input class="form-input" id="projFCountry" value="${esc(p?.country || '')}">
        </div>
      </div>`;
    DOM.btnSaveCrud.dataset.crudAction = pid ? 'save-edit-project' : 'save-new-project';
    DOM.btnSaveCrud.dataset.crudId = pid || '';
    DOM.crudModal.classList.add('open');
  }

  function openAddTaskModal(projectId) {
    DOM.crudModalTitle.textContent = 'Add Task';
    DOM.crudModalBody.innerHTML = `
      <div class="form-group">
        <label class="form-label required">Task Name</label>
        <input class="form-input" id="taskFName" placeholder="Task name">
      </div>
      <div class="form-grid-2">
        <div class="form-group">
          <label class="form-label">Assignee</label>
          <input class="form-input" id="taskFAssignee" placeholder="Assignee">
        </div>
        <div class="form-group">
          <label class="form-label">Due Date</label>
          <input type="date" class="form-input" id="taskFDue">
        </div>
        <div class="form-group">
          <label class="form-label">Status</label>
          <select class="form-input" id="taskFStatus">
            <option value="Open">Open</option>
            <option value="In Progress">In Progress</option>
            <option value="Completed">Completed</option>
          </select>
        </div>
      </div>`;
    DOM.btnSaveCrud.dataset.crudAction = 'save-new-task';
    DOM.btnSaveCrud.dataset.crudId = projectId;
    DOM.crudModal.classList.add('open');
  }

  // ═══ User Management ═══

  const ROLES = ['Guest', 'User', 'Admin', 'Super Admin', 'System Admin'];
  const DEPARTMENTS = ['Management', 'Construction / Site Operations', 'Engineering', 'Finance', 'HR', 'IT', 'Sales', 'Operations'];
  const DESIGNATIONS = ['Project Manager', 'Site Supervisor', 'Engineer', 'Estimator', 'Coordinator', 'Director', 'Analyst', 'Developer'];
  const TIME_ZONES = ['UTC', 'UTC-8 (PST)', 'UTC-7 (MST)', 'UTC-6 (CST)', 'UTC-5 (EST)', 'UTC+0 (GMT)', 'UTC+5:30 (IST)', 'UTC+8 (CST/HKT)', 'UTC+10 (AEST)'];

  function roleBadgeClass(role) {
    return {
      'Guest': 'badge-role-guest', 'User': 'badge-role-user',
      'Admin': 'badge-role-admin', 'Super Admin': 'badge-role-super',
      'System Admin': 'badge-role-system'
    }[role] || 'badge-role-user';
  }

  function renderUsersPage() {
    // Extract unique departments from loaded users
    const depts = [...new Set(state.users.map(u => u.department).filter(Boolean))];

    const rows = state.users.map(u => `<tr data-id="${u.id}">
      <td>${esc(u.name)}</td>
      <td>${esc(u.email)}</td>
      <td>${esc(u.phone || '')}</td>
      <td>${esc(u.address || '')}</td>
      <td><span class="badge ${u.status === 'Active' ? 'badge-active' : 'badge-inactive'}">${u.status}</span></td>
      <td><span class="badge ${roleBadgeClass(u.role)}">${u.role}</span></td>
      <td>${u.department ? `<span class="badge badge-dept">${esc(u.department)}</span>` : '—'}</td>
      <td><div class="table-actions"><button class="btn-table-action" data-action="edit-user" data-id="${u.id}" title="Edit"><span class="material-icons-outlined">edit</span></button></div></td>
    </tr>`).join('');

    DOM.contentArea.innerHTML = `${notConnectedMsg()}
      <div class="page-header">
        <h1 class="page-title">User</h1>
        <button class="btn btn-primary" id="btnAddUser">
          <span class="material-icons-outlined" style="font-size:18px">add</span> Add User
        </button>
      </div>
      <div class="filters-bar">
        <div class="filters-row">
          <div class="filter-group">
            <div class="filter-label">Name</div>
            <input class="filter-input" id="userNameFilter" placeholder="Filter by name (min 3 chars)">
          </div>
          <div class="filter-group">
            <div class="filter-label">Email</div>
            <input class="filter-input" id="userEmailFilter" placeholder="Filter by email (min 3 chars)">
          </div>
          <div class="filter-group">
            <div class="filter-label">Status</div>
            <select class="filter-input" id="userStatusFilter">
              <option value="">Select status</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </div>
          <div class="filter-group">
            <div class="filter-label">Role</div>
            <select class="filter-input" id="userRoleFilter">
              <option value="">Select role</option>
              ${ROLES.map(r => `<option value="${r}">${r}</option>`).join('')}
            </select>
          </div>
          <div class="filter-group">
            <div class="filter-label">Department</div>
            <select class="filter-input" id="userDeptFilter">
              <option value="">Select department</option>
              ${depts.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="filters-meta">
          <span class="total-count" id="userTotalCount">Total: ${state.users.length}</span>
          <button class="btn btn-secondary btn-sm" id="btnClearUserFilters">Clear</button>
        </div>
      </div>
      <div class="data-table-container">
        <table class="data-table" id="usersTable">
          <thead><tr>
            <th>Name</th><th>Email</th><th>Phone</th><th>Address</th>
            <th>Status</th><th>Role</th><th>Department</th><th>Actions</th>
          </tr></thead>
          <tbody id="usersTableBody">${rows || `<tr><td colspan="8" class="td-empty">${getApiUrl() ? 'No users found' : 'Connect backend to load users'}</td></tr>`}</tbody>
        </table>
      </div>`;
  }

  function applyUserFilters() {
    const name = ($('#userNameFilter')?.value || '').toLowerCase();
    const email = ($('#userEmailFilter')?.value || '').toLowerCase();
    const status = $('#userStatusFilter')?.value || '';
    const role = $('#userRoleFilter')?.value || '';
    const dept = $('#userDeptFilter')?.value || '';

    let filtered = state.users;
    if (name.length >= 3) filtered = filtered.filter(u => u.name.toLowerCase().includes(name));
    if (email.length >= 3) filtered = filtered.filter(u => u.email.toLowerCase().includes(email));
    if (status) filtered = filtered.filter(u => u.status === status);
    if (role) filtered = filtered.filter(u => u.role === role);
    if (dept) filtered = filtered.filter(u => u.department === dept);

    const tbody = $('#usersTableBody');
    const countEl = $('#userTotalCount');
    if (!tbody) return;
    if (countEl) countEl.textContent = `Total: ${filtered.length} `;
    tbody.innerHTML = filtered.length ? filtered.map(u => `< tr data - id="${u.id}" >
      <td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${esc(u.phone || '')}</td>
      <td>${esc(u.address || '')}</td>
      <td><span class="badge ${u.status === 'Active' ? 'badge-active' : 'badge-inactive'}">${u.status}</span></td>
      <td><span class="badge ${roleBadgeClass(u.role)}">${u.role}</span></td>
      <td>${u.department ? `<span class="badge badge-dept">${esc(u.department)}</span>` : '—'}</td>
      <td><div class="table-actions"><button class="btn-table-action" data-action="edit-user" data-id="${u.id}" title="Edit"><span class="material-icons-outlined">edit</span></button></div></td>
    </tr > `).join('') : ` < tr > <td colspan="8" class="td-empty">No users match filters</td></tr > `;
    tbody.querySelectorAll('[data-action]').forEach(el => el.addEventListener('click', handleAction));
  }

  function clearUserFilters() {
    ['userNameFilter', 'userEmailFilter'].forEach(id => { const el = $(`#${id} `); if (el) el.value = ''; });
    ['userStatusFilter', 'userRoleFilter', 'userDeptFilter'].forEach(id => { const el = $(`#${id} `); if (el) el.value = ''; });
    applyUserFilters();
  }

  function renderCreateUserPage() {
    DOM.contentArea.innerHTML = `
    < div class="user-form-page" >
        <div class="page-header" style="margin-bottom:24px">
          <h1 class="page-title">Create User</h1>
        </div>
        <div class="user-form-card">
          <div class="user-form-grid">
            <div class="form-group">
              <label class="form-label required-label">Name</label>
              <input class="form-input" id="ufName" placeholder="Full name">
            </div>
            <div class="form-group">
              <label class="form-label required-label">Email</label>
              <input class="form-input" id="ufEmail" type="email" placeholder="email@example.com">
            </div>
            <div class="form-group">
              <label class="form-label required-label">Password</label>
              <div class="pw-group">
                <input class="form-input" id="ufPassword" type="password" placeholder="Password">
                <button type="button" class="pw-toggle" tabindex="-1"><span class="material-icons-outlined">visibility_off</span></button>
              </div>
            </div>
            <div class="form-group">
              <label class="form-label required-label">Confirm Password</label>
              <div class="pw-group">
                <input class="form-input" id="ufConfirmPassword" type="password" placeholder="Confirm password">
                <button type="button" class="pw-toggle" tabindex="-1"><span class="material-icons-outlined">visibility_off</span></button>
              </div>
            </div>
            <div class="form-group">
              <label class="form-label">Phone</label>
              <input class="form-input" id="ufPhone" placeholder="Phone number">
            </div>
            <div class="form-group">
              <label class="form-label">Address</label>
              <input class="form-input" id="ufAddress" placeholder="Address">
            </div>
            <div class="form-group">
              <label class="form-label required-label">Role</label>
              <select class="form-input" id="ufRole">
                <option value="">Select role...</option>
                ${ROLES.map(r => `<option value="${r}">${r}</option>`).join('')}
              </select>
            </div>
          </div>
          <div class="user-form-actions">
            <button class="btn btn-primary" id="btnCreateUserSubmit">Create</button>
            <button class="btn btn-secondary" id="btnCancelCreate">Cancel</button>
          </div>
        </div>
      </div > `;
  }

  async function submitCreateUser() {
    const name = $('#ufName')?.value.trim();
    const email = $('#ufEmail')?.value.trim();
    const pw = $('#ufPassword')?.value;
    const pwConf = $('#ufConfirmPassword')?.value;
    const role = $('#ufRole')?.value;
    const phone = $('#ufPhone')?.value.trim();
    const address = $('#ufAddress')?.value.trim();

    if (!name) { showToast('Name is required', 'warning'); return; }
    if (!email) { showToast('Email is required', 'warning'); return; }
    if (!pw) { showToast('Password is required', 'warning'); return; }
    if (pw !== pwConf) { showToast('Passwords do not match', 'error'); return; }
    if (!role) { showToast('Role is required', 'warning'); return; }

    try {
      await apiReq('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password: pw, role, phone, address }),
      });
      await fetchUsers();
      showToast('User created successfully', 'success');
      navigateTo('users');
    } catch (err) { showToast(err.message, 'error'); }
  }

  function renderEditUserPage(userId) {
    const user = state.users.find(u => u.id === userId);
    if (!user) { navigateTo('users'); return; }

    const isActive = user.status === 'Active';
    DOM.contentArea.innerHTML = `
    < div class="user-form-page" >
        <div class="edit-user-header">
          <h1 class="page-title">Edit User</h1>
          <div class="edit-user-status">
            <span style="margin-right:8px;font-size:14px;color:var(--text-muted)">Status</span>
            <label class="toggle-switch">
              <input type="checkbox" id="userStatusToggle" ${isActive ? 'checked' : ''}>
              <span class="toggle-track"></span>
            </label>
            <span class="toggle-label" id="userStatusLabel" style="margin-left:8px;font-weight:600;color:${isActive ? 'var(--brand-green)' : 'var(--text-muted)'}">${user.status}</span>
          </div>
        </div>
        <input type="hidden" id="editUserId" value="${user.id}">
        <div class="user-form-card">
          <div class="tab-strip">
            <button class="tab-btn active" data-tab="details">Details</button>
            <button class="tab-btn" data-tab="permission">Permission</button>
          </div>

          <div id="tab-details" class="tab-content active">
            <div class="edit-user-layout">
              <div class="edit-user-fields">
                <div class="user-form-grid">
                  <div class="form-group">
                    <label class="form-label required-label">Name</label>
                    <input class="form-input" id="euName" value="${esc(user.name)}">
                  </div>
                  <div class="form-group">
                    <label class="form-label required-label">Email</label>
                    <input class="form-input" id="euEmail" type="email" value="${esc(user.email)}">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Phone</label>
                    <input class="form-input" id="euPhone" value="${esc(user.phone || '')}">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Address</label>
                    <input class="form-input" id="euAddress" value="${esc(user.address || '')}">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Role</label>
                    <select class="form-input" id="euRole">
                      ${ROLES.map(r => `<option value="${r}" ${user.role === r ? 'selected' : ''}>${r}</option>`).join('')}
                    </select>
                  </div>
                  <div class="form-group">
                    <label class="form-label">Company</label>
                    <input class="form-input" id="euCompany" value="${esc(user.company || '')}" ${user.company ? 'disabled' : ''}>
                  </div>
                  <div class="form-group">
                    <label class="form-label">Department</label>
                    <select class="form-input" id="euDepartment">
                      <option value="">Select department</option>
                      ${DEPARTMENTS.map(d => `<option value="${d}" ${user.department === d ? 'selected' : ''}>${d}</option>`).join('')}
                    </select>
                  </div>
                  <div class="form-group">
                    <label class="form-label">Designation</label>
                    <select class="form-input" id="euDesignation">
                      <option value="">Select designation</option>
                      ${DESIGNATIONS.map(d => `<option value="${d}" ${user.designation === d ? 'selected' : ''}>${d}</option>`).join('')}
                    </select>
                  </div>
                  <div class="form-group">
                    <label class="form-label">Time Zone</label>
                    <select class="form-input" id="euTimeZone">
                      ${TIME_ZONES.map(tz => `<option value="${tz}" ${user.time_zone === tz ? 'selected' : ''}>${tz}</option>`).join('')}
                    </select>
                  </div>
                </div>
              </div>
              <div class="edit-user-avatar">
                <div class="avatar-circle">
                  <span class="material-icons-outlined avatar-placeholder">account_circle</span>
                  <div class="avatar-actions">
                    <button class="avatar-btn avatar-btn-camera" title="Upload photo"><span class="material-icons-outlined">photo_camera</span></button>
                    <button class="avatar-btn avatar-btn-delete" title="Remove photo"><span class="material-icons-outlined">delete</span></button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div id="tab-permission" class="tab-content">
            <div style="padding:32px;text-align:center;color:var(--text-muted)">
              <span class="material-icons-outlined" style="font-size:48px">security</span>
              <p style="margin-top:8px">Permission settings will appear here.</p>
            </div>
          </div>

          <div class="user-form-actions">
            <button class="btn btn-primary" id="btnUpdateUser">Save Changes</button>
            <button class="btn btn-secondary" id="btnCancelEdit">Cancel</button>
          </div>
        </div>
      </div>`;
  }

  async function submitUpdateUser() {
    const id = $('#editUserId')?.value;
    const name = $('#euName')?.value.trim();
    const email = $('#euEmail')?.value.trim();
    const phone = $('#euPhone')?.value.trim();
    const address = $('#euAddress')?.value.trim();
    const role = $('#euRole')?.value;
    const department = $('#euDepartment')?.value;
    const designation = $('#euDesignation')?.value;
    const time_zone = $('#euTimeZone')?.value;
    const company = $('#euCompany')?.value.trim();
    const status = $('#userStatusToggle')?.checked ? 'Active' : 'Inactive';

    if (!name) { showToast('Name is required', 'warning'); return; }
    if (!email) { showToast('Email is required', 'warning'); return; }

    try {
      await apiReq(`/ api / users / ${id} `, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, phone, address, role, department, designation, time_zone, company, status }),
      });
      await fetchUsers();
      showToast('User updated successfully', 'success');
      navigateTo('users');
    } catch (err) { showToast(err.message, 'error'); }
  }

  // ═══ Page Events ═══
  function bindPageEvents() {
    $$('[data-nav]').forEach(el => el.addEventListener('click', e => { e.preventDefault(); navigateTo(el.dataset.nav); }));
    $$('[data-action]').forEach(el => el.addEventListener('click', handleAction));
    const btnCT = $('#btnCreateTrade'); if (btnCT) btnCT.addEventListener('click', () => openCrudModal('trade'));
    const btnCV = $('#btnCreateVendor'); if (btnCV) btnCV.addEventListener('click', () => openCrudModal('vendor'));
    const btnUD = $('#btnUploadDocs'); if (btnUD) btnUD.addEventListener('click', openUploadPanel);

    // User page events
    const btnAddUser = $('#btnAddUser');
    if (btnAddUser) btnAddUser.addEventListener('click', () => navigateTo('create-user'));
    const userFilters = ['userNameFilter', 'userEmailFilter', 'userStatusFilter', 'userRoleFilter', 'userDeptFilter'];
    userFilters.forEach(id => { const el = $(`#${id}`); if (el) el.addEventListener('input', applyUserFilters); });
    const btnClearFilters = $('#btnClearUserFilters');
    if (btnClearFilters) btnClearFilters.addEventListener('click', clearUserFilters);

    // Create user form
    const btnCreateUser = $('#btnCreateUserSubmit');
    if (btnCreateUser) btnCreateUser.addEventListener('click', submitCreateUser);
    const btnCancelCreate = $('#btnCancelCreate');
    if (btnCancelCreate) btnCancelCreate.addEventListener('click', () => navigateTo('users'));

    // Password show/hide toggles
    $$('.pw-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const inp = btn.previousElementSibling;
        if (!inp) return;
        inp.type = inp.type === 'password' ? 'text' : 'password';
        btn.querySelector('span.material-icons-outlined').textContent = inp.type === 'password' ? 'visibility_off' : 'visibility';
      });
    });

    // Edit user form
    const btnUpdateUser = $('#btnUpdateUser');
    if (btnUpdateUser) btnUpdateUser.addEventListener('click', submitUpdateUser);
    const btnCancelEdit = $('#btnCancelEdit');
    if (btnCancelEdit) btnCancelEdit.addEventListener('click', () => navigateTo('users'));

    // Edit user tabs — scoped to .user-form-card to avoid conflict with project dashboard .tab-strip
    const userFormCard = $('.user-form-card');
    const userTabBtns = userFormCard
      ? userFormCard.querySelectorAll('.tab-btn')
      : [];
    Array.from(userTabBtns).forEach(btn => {
      btn.addEventListener('click', () => {
        Array.from(userTabBtns).forEach(b => b.classList.remove('active'));
        userFormCard.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const tab = $(`#tab-${btn.dataset.tab}`);
        if (tab) tab.classList.add('active');
      });
    });

    // Status toggle in edit user
    const statusToggle = $('#userStatusToggle');
    if (statusToggle) {
      statusToggle.addEventListener('change', () => {
        const lbl = $('#userStatusLabel');
        if (lbl) lbl.textContent = statusToggle.checked ? 'Active' : 'Inactive';
      });
    }

    // ── Project page events ──────────────────────────────────────────────────
    // Helper: fetch + full re-render (ensures bindPageEvents re-runs and new DOM gets listeners)
    const _refreshProjects = async () => { await fetchProjects(); renderPage(); };

    // All Projects list
    const btnNewProj = $('#btnNewProject');
    if (btnNewProj) btnNewProj.addEventListener('click', () => openProjectModal());

    const btnRefProj = $('#btnRefreshProjects');
    if (btnRefProj) btnRefProj.addEventListener('click', _refreshProjects);

    const btnClearProj = $('#btnClearProjFilters');
    if (btnClearProj) btnClearProj.addEventListener('click', () => {
      state._projectFilters = { name: '', manager: '', types: [], statuses: [], startAfter: '', startBefore: '', endAfter: '', endBefore: '', showArchived: false };
      state._projectsMeta.page = 1;
      _refreshProjects();
    });

    // Text filters (debounced)
    let _projFTimer;
    ['projNameFilter', 'projManagerFilter'].forEach(fid => {
      const el = $(`#${fid}`);
      if (!el) return;
      el.addEventListener('input', () => {
        clearTimeout(_projFTimer);
        const key = fid === 'projNameFilter' ? 'name' : 'manager';
        state._projectFilters[key] = el.value;
        state._projectsMeta.page = 1;
        _projFTimer = setTimeout(_refreshProjects, 500);
      });
    });

    // Date range filters
    ['projStartAfter', 'projStartBefore', 'projEndAfter', 'projEndBefore'].forEach(fid => {
      const el = $(`#${fid}`);
      if (!el) return;
      const keyMap = { projStartAfter: 'startAfter', projStartBefore: 'startBefore', projEndAfter: 'endAfter', projEndBefore: 'endBefore' };
      el.addEventListener('change', () => {
        state._projectFilters[keyMap[fid]] = el.value;
        state._projectsMeta.page = 1;
        _refreshProjects();
      });
    });

    // Archived checkbox
    const cbArch = $('#projShowArchived');
    if (cbArch) cbArch.addEventListener('change', () => {
      state._projectFilters.showArchived = cbArch.checked;
      state._projectsMeta.page = 1;
      _refreshProjects();
    });

    // Multi-select dropdowns (Type / Status)
    // NOTE: These listeners are attached to the current DOM elements.
    // _refreshProjects() calls renderPage() which calls bindPageEvents() — so new DOM always gets fresh listeners.
    ['projTypeWrap', 'projStatusWrap'].forEach(wrapId => {
      const wrap = $(`#${wrapId}`);
      if (!wrap) return;
      const isType = wrapId === 'projTypeWrap';
      const key = isType ? 'types' : 'statuses';
      const display = wrap.querySelector('.multi-select-display');
      const dropdown = wrap.querySelector('.multi-select-dropdown');

      // Click on display: either remove a chip or toggle the dropdown
      display.addEventListener('click', e => {
        const chipX = e.target.closest('.chip-x');
        if (chipX) {
          e.stopPropagation();
          // Read value from data-type or data-status attribute on the chip-x button
          const val = chipX.dataset.type || chipX.dataset.status;
          state._projectFilters[key] = state._projectFilters[key].filter(v => v !== val);
          state._projectsMeta.page = 1;
          _refreshProjects();
          return;
        }
        dropdown.classList.toggle('open');
      });

      // Checkboxes inside the dropdown
      dropdown.querySelectorAll('input[type=checkbox]').forEach(chk => {
        chk.addEventListener('change', () => {
          if (chk.checked) {
            if (!state._projectFilters[key].includes(chk.value)) state._projectFilters[key].push(chk.value);
          } else {
            state._projectFilters[key] = state._projectFilters[key].filter(v => v !== chk.value);
          }
          state._projectsMeta.page = 1;
          _refreshProjects();
        });
      });
    });

    // Project Dashboard tab switching (scoped to .tab-strip to avoid hitting edit-user tabs)
    $$('.tab-strip .tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const newTab = btn.dataset.tab;
        if (!newTab || newTab === state._dashTab) return;
        state._dashTab = newTab;
        // Swap active class without full re-render
        $$('.tab-strip .tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === newTab));
        const p = state.projects.find(x => x.id === state.activeProjectId) || null;
        const content = $('#dashTabContent');
        if (!content || !p) return;
        if (newTab === 'overview') {
          content.innerHTML = renderDashOverview(p, renderProjectTasksSection());
          // Re-bind tasks buttons only
          const btnOT = $('#btnOpenTasks'); if (btnOT) btnOT.addEventListener('click', () => openAddTaskModal(state.activeProjectId));
          const btnRT = $('#btnRefreshTasks'); if (btnRT) btnRT.addEventListener('click', async () => { await fetchProjectTasks(state.activeProjectId); const el = $('#projTasksList'); if (el) el.innerHTML = renderProjectTasksSection(); });
        } else {
          const label = newTab.charAt(0).toUpperCase() + newTab.slice(1);
          content.innerHTML = `<div class="empty-state"><span class="material-icons-outlined">construction</span><h3>${label}</h3><p>Coming soon.</p></div>`;
        }
      });
    });

    // Open Tasks button
    const btnOpenTasks = $('#btnOpenTasks');
    if (btnOpenTasks) btnOpenTasks.addEventListener('click', () => openAddTaskModal(state.activeProjectId));

    // Refresh Tasks button
    const btnRefTasks = $('#btnRefreshTasks');
    if (btnRefTasks) btnRefTasks.addEventListener('click', async () => {
      await fetchProjectTasks(state.activeProjectId);
      const el = $('#projTasksList');
      if (el) el.innerHTML = renderProjectTasksSection();
    });
  }

  async function handleAction(e) {
    const btn = e.currentTarget;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    if (action === 'edit-trade') openCrudModal('trade', id);
    else if (action === 'delete-trade') {
      if (!confirm('Delete this trade?')) return;
      try { await apiReq(`/api/trades/${id}`, { method: 'DELETE' }); await fetchTrades(); renderPage(); showToast('Trade deleted', 'info'); } catch (e) { showToast(e.message, 'error'); }
    }
    else if (action === 'edit-vendor') openCrudModal('vendor', id);
    else if (action === 'delete-vendor') {
      if (!confirm('Delete this vendor?')) return;
      try { await apiReq(`/api/vendors/${id}`, { method: 'DELETE' }); await fetchVendors(); renderPage(); showToast('Vendor deleted', 'info'); } catch (e) { showToast(e.message, 'error'); }
    }
    else if (action === 'add-team') {
      // Map card title → member category
      const catMap = { 'Internal Team': 'internal', 'Subcontractors & Trades': 'contractor', 'Consultants & Designers': 'consultant', 'Vendors & Suppliers': 'vendor' };
      const cat = catMap[btn.dataset.cat] || 'internal';
      openCrudModal('team-member', null, cat);
    }
    else if (action === 'preview-doc') openDocPreview(id, btn.dataset.name);
    else if (action === 'delete-doc') {
      if (!confirm('Delete this document?')) return;
      try { await apiReq(`/api/documents/${id}`, { method: 'DELETE' }); await fetchDocuments(); renderPage(); showToast('Document deleted', 'info'); } catch (e) { showToast(e.message, 'error'); }
    }
    else if (action === 'edit-user') {
      state._editUserId = id;
      navigateTo('edit-user');
    }
    // Project actions
    else if (action === 'open-project') {
      e.preventDefault();
      state.activeProjectId = id;
      state._dashTab = 'overview';
      await fetchProjectTasks(id);
      navigateTo('project-details');
    }
    else if (action === 'edit-project') {
      openProjectModal(id);
    }
    else if (action === 'delete-project') {
      if (!confirm('Permanently delete this project and all its tasks?')) return;
      try {
        await apiReq(`/api/projects/${id}`, { method: 'DELETE' });
        if (state.activeProjectId === id) { state.activeProjectId = null; state.projectTasks = []; }
        await fetchProjects();
        renderPage();
        showToast('Project deleted', 'info');
      } catch (err) { showToast(err.message, 'error'); }
    }
    else if (action === 'archive-project') {
      try {
        await apiReq(`/api/projects/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ archived: true }),
        });
        await fetchProjects();
        renderPage();
        showToast('Project archived', 'info');
      } catch (err) { showToast(err.message, 'error'); }
    }
    else if (action === 'unarchive-project') {
      try {
        await apiReq(`/api/projects/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ archived: false }),
        });
        await fetchProjects();
        renderPage();
        showToast('Project restored', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    }
    // Pagination
    else if (action === 'proj-page') {
      const pg = parseInt(id, 10);
      if (!isNaN(pg) && pg >= 1 && pg <= state._projectsMeta.pages) {
        state._projectsMeta.page = pg;
        await fetchProjects();
        renderAllProjectsPage();
      }
    }
    // nav-all-projects: back button in empty project state
    else if (action === 'nav-all-projects') {
      navigateTo('all-projects');
    }
  }

  // ═══ Document Preview ═══
  async function openDocPreview(docId, name) {
    const ext = getExt(name);
    const baseUrl = getApiUrl().replace(/\/$/, '');
    DOM.docPreviewTitle.textContent = name;
    // Open modal immediately so the user sees it right away
    DOM.docPreviewBody.innerHTML = '';
    DOM.docPreviewModal.classList.add('open');

    if (isPdf(ext)) {
      // Show loading spinner first
      DOM.docPreviewBody.innerHTML = `< div class="preview-pages" id = "previewPages" >
    <div class="preview-loading"><div class="typing-indicator"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div><p>Loading preview...</p></div>
      </div > `;
      // Load page images
      try {
        const meta = state.uploadedDocs.find(d => d.id === docId);
        // Backend returns page_count; uploadFiles stores it as doc.pages — normalise both
        const pageCount = meta?.page_count || meta?.pages || 1;
        let pagesHtml = '';
        for (let i = 1; i <= Math.min(pageCount, 10); i++) {
          pagesHtml += `< div class="preview-page" > <img src="${baseUrl}/api/pages/${docId}/${i}" alt="Page ${i}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=\\'preview-error\\'>Page ${i} unavailable</div>'"><div class="preview-page-label">Page ${i} of ${pageCount}</div></div>`;
        }
        if (pageCount > 10) pagesHtml += `< div class="preview-more" > Showing first 10 of ${pageCount} pages</div > `;
        const container = document.getElementById('previewPages');
        if (container) container.innerHTML = pagesHtml;
      } catch (e) {
        const container = document.getElementById('previewPages');
        if (container) container.innerHTML = `< div class="preview-error" > Could not load preview: ${esc(e.message)}</div > `;
      }
    }
    else if (isImage(ext)) {
      DOM.docPreviewBody.innerHTML = `< div class="preview-image-container" > <img src="${baseUrl}/api/pages/${docId}/1" alt="${esc(name)}" onerror="this.src='';this.alt='Preview unavailable'"></div>`;
    }
    else if (isAudio(ext)) {
      // Map ext → correct MIME type for <source type="">
      const audioMime = { mp3: 'audio/mpeg', wav: 'audio/wav', ogg: 'audio/ogg', m4a: 'audio/mp4', flac: 'audio/flac', aac: 'audio/aac', wma: 'audio/x-ms-wma', opus: 'audio/ogg; codecs=opus' };
      DOM.docPreviewBody.innerHTML = `< div class="preview-audio-container" >
        <div class="audio-visual"><span class="material-icons-outlined" style="font-size:64px;color:var(--brand-blue)">graphic_eq</span></div>
        <audio controls preload="metadata" style="width:100%"><source src="${baseUrl}/api/pages/${docId}/1" type="${audioMime[ext] || 'audio/' + ext}">Your browser doesn't support audio.</audio>
        <p class="preview-filename">${esc(name)}</p>
      </div > `;
    }
    else if (isVideo(ext)) {
      const videoMime = { mp4: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime', avi: 'video/x-msvideo', mkv: 'video/x-matroska' };
      DOM.docPreviewBody.innerHTML = `< div class="preview-video-container" > <video controls preload="metadata" style="width:100%;max-height:60vh;border-radius:8px"><source src="${baseUrl}/api/pages/${docId}/1" type="${videoMime[ext] || 'video/' + ext}">Your browser doesn't support video.</video></div > `;
    }
    else if (isText(ext)) {
      // Text files: fetch content from page 1 image path, but since backend renders
      // text files as PNG screenshots, display as an image the same way
      DOM.docPreviewBody.innerHTML = `< div class="preview-image-container" > <img src="${baseUrl}/api/pages/${docId}/1" alt="${esc(name)}" style="max-width:100%" onerror="this.parentElement.innerHTML='<div class=\\'preview-error\\'>Preview unavailable for this file</div>'"></div>`;
    }
    else {
      DOM.docPreviewBody.innerHTML = `< div class="preview-generic" ><span class="material-icons-outlined" style="font-size:48px;color:var(--text-muted)">description</span><p>Preview not available for .${ext} files</p><p class="preview-hint">This file has been indexed and can be queried via Marshal Chat.</p></div > `;
    }
  }
  function closeDocPreview() { DOM.docPreviewModal.classList.remove('open'); DOM.docPreviewBody.innerHTML = ''; }

  // ═══ CRUD Modal ═══
  let crudCallback = null;
  function openCrudModal(type, editId, defaultCat) {
    const isEdit = !!editId;
    DOM.crudModalTitle.textContent = isEdit ? `Edit ${type} ` : `Create ${type} `;
    let fields = '';
    if (type === 'trade') {
      const item = isEdit ? state.trades.find(t => t.id === editId) : { name: '', description: '', status: 'Active' };
      if (!item) return;
      fields = `< div class="form-group" ><label class="form-label">Name</label><input class="form-input" id="crudName" value="${esc(item.name)}"></div>
        <div class="form-group"><label class="form-label">Description</label><input class="form-input" id="crudDesc" value="${esc(item.description)}"></div>
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="crudStatus"><option value="Active" ${item.status === 'Active' ? 'selected' : ''}>Active</option><option value="Inactive" ${item.status === 'Inactive' ? 'selected' : ''}>Inactive</option></select></div>`;
      crudCallback = async () => {
        const payload = { name: $('#crudName').value.trim(), description: $('#crudDesc').value.trim() || '-', status: $('#crudStatus').value };
        if (!payload.name) { showToast('Name is required', 'warning'); return false; }
        try {
          if (isEdit) await apiReq(`/ api / trades / ${editId} `, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          else await apiReq('/api/trades', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          await fetchTrades(); return true;
        } catch (e) { showToast(e.message, 'error'); return false; }
      };
    } else if (type === 'vendor') {
      const item = isEdit ? state.vendors.find(v => v.id === editId) : { name: '', vendorType: 'Material Supplier', trade: '', status: 'Active' };
      if (!item) return;
      fields = `< div class="form-group" ><label class="form-label">Vendor Name</label><input class="form-input" id="crudName" value="${esc(item.name)}"></div>
        <div class="form-group"><label class="form-label">Vendor Type</label><select class="form-input" id="crudType"><option value="Material Supplier" ${item.vendorType === 'Material Supplier' ? 'selected' : ''}>Material Supplier</option><option value="Subcontractor" ${item.vendorType === 'Subcontractor' ? 'selected' : ''}>Subcontractor</option></select></div>
        <div class="form-group"><label class="form-label">Trade</label><select class="form-input" id="crudTrade"><option value="">Select trade...</option>${state.trades.map(t => `<option value="${esc(t.name)}" ${item.trade === t.name ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></div>
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="crudStatus"><option value="Active" ${item.status === 'Active' ? 'selected' : ''}>Active</option><option value="Inactive" ${item.status === 'Inactive' ? 'selected' : ''}>Inactive</option></select></div>`;
      crudCallback = async () => {
        const payload = { name: $('#crudName').value.trim(), vendorType: $('#crudType').value, trade: $('#crudTrade').value, status: $('#crudStatus').value };
        if (!payload.name) { showToast('Name is required', 'warning'); return false; }
        try {
          if (isEdit) await apiReq(`/ api / vendors / ${editId} `, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          else await apiReq('/api/vendors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          await fetchVendors(); return true;
        } catch (e) { showToast(e.message, 'error'); return false; }
      };
    }
    else if (type === 'team-member') {
      const item = editId ? state.teamMembers.find(m => m.id === editId) : { name: '', email: '', department: '', category: defaultCat || 'internal', company: '', contactName: '' };
      if (!item) return;
      const isVendorCat = (item.category === 'vendor');
      fields = `< div class="form-group" ><label class="form-label">Name</label><input class="form-input" id="crudName" value="${esc(item.name)}"></div>
        <div class="form-group"><label class="form-label">Email</label><input class="form-input" type="email" id="crudEmail" value="${esc(item.email || '')}"></div>
        <div class="form-group"><label class="form-label">Category</label><select class="form-input" id="crudCat"><option value="internal" ${item.category === 'internal' ? 'selected' : ''}>Internal Team</option><option value="contractor" ${item.category === 'contractor' ? 'selected' : ''}>Subcontractor</option><option value="consultant" ${item.category === 'consultant' ? 'selected' : ''}>Consultant</option><option value="vendor" ${item.category === 'vendor' ? 'selected' : ''}>Vendor / Supplier</option></select></div>
        <div class="form-group"><label class="form-label">Department</label><input class="form-input" id="crudDept" value="${esc(item.department || '')}"></div>
        <div class="form-group"><label class="form-label">Company</label><input class="form-input" id="crudCompany" value="${esc(item.company || '')}"></div>
        <div class="form-group"><label class="form-label">Contact Name</label><input class="form-input" id="crudContact" value="${esc(item.contactName || '')}"></div>`;
      crudCallback = async () => {
        const payload = { name: $('#crudName').value.trim(), email: $('#crudEmail').value.trim(), category: $('#crudCat').value, department: $('#crudDept').value.trim() || '—', company: $('#crudCompany').value.trim(), contactName: $('#crudContact').value.trim() };
        if (!payload.name) { showToast('Name is required', 'warning'); return false; }
        try {
          if (editId) await apiReq(`/ api / team - members / ${editId} `, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          else await apiReq('/api/team-members', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          await fetchTeamMembers(); return true;
        } catch (e) { showToast(e.message, 'error'); return false; }
      };
    }
    DOM.crudModalBody.innerHTML = fields;
    DOM.crudModal.classList.add('open');
  }
  function closeCrudModal() { DOM.crudModal.classList.remove('open'); crudCallback = null; }

  // ═══ Chat Panel ═══
  function showChat() { DOM.chatPanel.classList.add('visible'); DOM.chatPanel.classList.remove('collapsed'); DOM.chatOverlay.classList.add('open'); }
  function hideChat() { DOM.chatPanel.classList.remove('visible'); DOM.chatPanel.classList.add('collapsed'); DOM.chatOverlay.classList.remove('open'); }
  function toggleChat() { DOM.chatPanel.classList.contains('visible') ? hideChat() : showChat(); }

  // ═══ Chat Panel Resize (drag left edge) ═══
  function initChatResize() {
    const handle = DOM.chatResizeHandle;
    const panel = DOM.chatPanel;
    if (!handle || !panel) return;

    const MIN_W = 280;
    const MAX_W = 700;
    let startX = 0;
    let startW = 0;
    let isDragging = false;

    function onPointerDown(e) {
      // Only on desktop (> 1200px)
      if (window.innerWidth <= 1200) return;
      e.preventDefault();
      isDragging = true;
      startX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
      startW = panel.getBoundingClientRect().width;
      panel.classList.add('resizing');
      handle.classList.add('active');
      document.body.classList.add('chat-resizing');
      document.addEventListener('mousemove', onPointerMove);
      document.addEventListener('mouseup', onPointerUp);
      document.addEventListener('touchmove', onPointerMove, { passive: false });
      document.addEventListener('touchend', onPointerUp);
    }

    function onPointerMove(e) {
      if (!isDragging) return;
      e.preventDefault();
      const clientX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
      // Dragging left = increasing width, dragging right = decreasing width
      const delta = startX - clientX;
      const newW = Math.min(MAX_W, Math.max(MIN_W, startW + delta));
      panel.style.width = newW + 'px';
    }

    function onPointerUp() {
      if (!isDragging) return;
      isDragging = false;
      panel.classList.remove('resizing');
      handle.classList.remove('active');
      document.body.classList.remove('chat-resizing');
      document.removeEventListener('mousemove', onPointerMove);
      document.removeEventListener('mouseup', onPointerUp);
      document.removeEventListener('touchmove', onPointerMove);
      document.removeEventListener('touchend', onPointerUp);
      // Persist the width
      const finalW = panel.getBoundingClientRect().width;
      localStorage.setItem('bm_chat_width', Math.round(finalW));
    }

    handle.addEventListener('mousedown', onPointerDown);
    handle.addEventListener('touchstart', onPointerDown, { passive: false });

    // Restore saved width
    const savedW = localStorage.getItem('bm_chat_width');
    if (savedW && window.innerWidth > 1200) {
      const w = Math.min(MAX_W, Math.max(MIN_W, parseInt(savedW, 10)));
      panel.style.width = w + 'px';
    }
  }

  function createNewChat() {
    const id = genId();
    state.chats[id] = { id, title: 'New Chat', messages: [], createdAt: Date.now() };
    state.activeChatId = id; saveChats(); renderChatHistory(); return id;
  }
  function getActiveChat() { return state.activeChatId ? state.chats[state.activeChatId] : null; }

  function deleteChat(id) {
    delete state.chats[id];
    const remaining = Object.keys(state.chats);
    if (state.activeChatId === id) {
      state.activeChatId = remaining.length > 0 ? remaining[remaining.length - 1] : null;
      if (!state.activeChatId) createNewChat();
    }
    saveChats(); renderChatMessages(); renderChatHistory();
  }

  function switchChat(id) {
    if (!state.chats[id]) return;
    state.activeChatId = id;
    saveChats(); renderChatMessages(); renderChatHistory();
  }

  function openChatHistory() { DOM.chatHistoryPanel.classList.add('open'); renderChatHistory(); }
  function closeChatHistory() { DOM.chatHistoryPanel.classList.remove('open'); }
  function toggleChatHistory() { DOM.chatHistoryPanel.classList.contains('open') ? closeChatHistory() : openChatHistory(); }

  function renderChatHistory() {
    const chatList = Object.values(state.chats)
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
    if (chatList.length === 0) {
      DOM.chatHistoryList.innerHTML = '<div class="chat-history-empty">No conversations yet</div>';
      return;
    }
    DOM.chatHistoryList.innerHTML = chatList.map(chat => {
      const isActive = chat.id === state.activeChatId;
      const msgCount = chat.messages ? chat.messages.length : 0;
      const dateStr = chat.createdAt ? new Date(chat.createdAt).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '';
      return `< div class="chat-history-item ${isActive ? 'active' : ''}" data - chat - id="${chat.id}" >
        <span class="material-icons-outlined chat-history-icon">chat_bubble_outline</span>
        <div class="chat-history-info">
          <div class="chat-history-title">${esc(chat.title || 'New Chat')}</div>
          <div class="chat-history-meta"><span>${msgCount} message${msgCount !== 1 ? 's' : ''}</span><span>${dateStr}</span></div>
        </div>
        <button class="chat-history-delete" data-delete-id="${chat.id}" title="Delete chat">
          <span class="material-icons-outlined">delete_outline</span>
        </button>
      </div > `;
    }).join('');
    // Bind switch + delete
    DOM.chatHistoryList.querySelectorAll('.chat-history-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.closest('.chat-history-delete')) return;
        switchChat(item.dataset.chatId);
      });
    });
    DOM.chatHistoryList.querySelectorAll('.chat-history-delete').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm('Delete this conversation?')) deleteChat(btn.dataset.deleteId);
      });
    });
  }

  function addMessage(role, content, sources = null, attachments = null) {
    let chat = getActiveChat();
    if (!chat) { createNewChat(); chat = getActiveChat(); }
    const msg = { id: genId(), role, content, sources, attachments, timestamp: Date.now() };
    chat.messages.push(msg);
    if (role === 'user' && chat.messages.filter(m => m.role === 'user').length === 1) {
      chat.title = content.slice(0, 50) + (content.length > 50 ? '…' : '');
    }
    saveChats(); return msg;
  }

  function renderChatMessages() {
    const chat = getActiveChat();
    if (!chat || chat.messages.length === 0) {
      DOM.chatMessages.innerHTML = `< div class="chat-welcome" >
        <div class="chat-welcome-icon"><span class="material-icons-outlined">smart_toy</span></div>
        <h3>Ask Marshal anything</h3>
        <p>Upload documents, audio files, or images and ask questions.</p>
        <div class="chat-suggestions">
          <button class="suggestion-chip" data-q="Summarize the uploaded documents">📝 Summarize docs</button>
          <button class="suggestion-chip" data-q="What are the key findings?">🔍 Key findings</button>
          <button class="suggestion-chip" data-q="List all action items">✅ Action items</button>
        </div>
      </div > `;
      DOM.chatMessages.querySelectorAll('.suggestion-chip').forEach(c => {
        c.addEventListener('click', () => { DOM.chatInput.value = c.dataset.q; sendChatMessage(); });
      });
      return;
    }
    DOM.chatMessages.innerHTML = chat.messages.map(msg => {
      let attachHtml = '';
      if (msg.attachments && msg.attachments.length > 0) {
        attachHtml = `< div class="msg-attachments" > ${msg.attachments.map(a => {
          const ext = getExt(a.name);
          return `<div class="msg-attachment-chip"><span>${getFileIcon(ext)}</span><span class="att-name">${esc(a.name)}</span><span class="att-size">${fmtSize(a.size)}</span></div>`;
        }).join('')
          }</div > `;
      }
      let srcHtml = '';
      if (msg.sources && msg.sources.length > 0) {
        const cards = msg.sources.map(s => {
          const prev = s.image_url ? `< img src = "${esc(s.image_url)}" alt = "Preview" loading = "lazy" > ` : ` < span class="material-icons-outlined" style = "font-size:20px;color:var(--text-muted)" > description</span > `;
          return `< div class="citation-card" data - image - url="${s.image_url ? esc(s.image_url) : ''}" >
            <div class="card-preview">${prev}</div>
            <div class="card-info"><div class="card-doc-name">${esc(s.doc_name || 'Document')}</div><div class="card-page">Page ${s.page || '?'}</div>${s.score ? `<div class="card-score">${(s.score * 100).toFixed(0)}%</div>` : ''}</div>
          </div > `;
        }).join('');
        srcHtml = `< div class="source-citations" ><div class="citations-label">📎 Sources</div><div class="citation-cards">${cards}</div></div > `;
      }
      return `< div class="chat-msg ${msg.role === 'user' ? 'user' : 'bot'}" data - msg - id="${msg.id}" >
    ${attachHtml} <div class="message-text">${renderMd(msg.content)}</div>${srcHtml}
  <div class="chat-msg-time">${fmtTime(msg.timestamp)}</div>
      </div > `;
    }).join('');
    DOM.chatMessages.querySelectorAll('.citation-card').forEach(c => {
      c.addEventListener('click', () => { if (c.dataset.imageUrl) openImagePreview(c.dataset.imageUrl); });
    });
    scrollChatBottom();
  }
  function scrollChatBottom() { requestAnimationFrame(() => { DOM.chatMessages.scrollTop = DOM.chatMessages.scrollHeight; }); }

  // ═══ Chat File Attachments ═══
  function addPendingFiles(files) {
    for (const f of files) {
      if (f.size > APP_CONFIG.MAX_FILE_SIZE) { showToast(`Too large: ${f.name} `, 'warning'); continue; }
      state.pendingFiles.push(f);
    }
    renderPendingFiles();
  }
  function renderPendingFiles() {
    if (state.pendingFiles.length === 0) { DOM.chatAttachments.style.display = 'none'; return; }
    DOM.chatAttachments.style.display = 'flex';
    DOM.chatAttachments.innerHTML = state.pendingFiles.map((f, i) => {
      const ext = getExt(f.name);
      return `< div class="pending-file" ><span>${getFileIcon(ext)}</span><span class="pf-name">${esc(f.name.length > 20 ? f.name.slice(0, 18) + '…' : f.name)}</span><button class="pf-remove" data-idx="${i}" title="Remove">×</button></div > `;
    }).join('');
    DOM.chatAttachments.querySelectorAll('.pf-remove').forEach(btn => {
      btn.addEventListener('click', () => { state.pendingFiles.splice(parseInt(btn.dataset.idx), 1); renderPendingFiles(); });
    });
  }

  // ═══ Send Message ═══
  async function sendChatMessage() {
    const text = DOM.chatInput.value.trim();
    if ((!text && state.pendingFiles.length === 0) || state.isStreaming) return;
    if (!getActiveChat()) createNewChat();

    // Capture attachments info for display
    const attachInfo = state.pendingFiles.map(f => ({ name: f.name, size: f.size }));
    const filesToUpload = [...state.pendingFiles];
    state.pendingFiles = [];
    renderPendingFiles();

    addMessage('user', text || '(files attached)', null, attachInfo.length ? attachInfo : null);
    DOM.chatInput.value = '';
    autoResize(DOM.chatInput);
    renderChatMessages();
    state.isStreaming = true;

    // Upload attached files first
    if (filesToUpload.length > 0) {
      for (const file of filesToUpload) {
        try {
          const fd = new FormData(); fd.append('file', file); fd.append('doc_id', genId());
          await apiReq('/api/upload', { method: 'POST', body: fd });
          showToast(`Uploaded: ${file.name} `, 'success');
        } catch (e) { showToast(`Upload failed: ${file.name} `, 'error'); }
      }
      fetchDocuments(); // refresh doc list
    }

    // Show typing indicator
    const typEl = document.createElement('div');
    typEl.className = 'chat-msg bot'; typEl.id = 'typingIndicator';
    typEl.innerHTML = '<div class="typing-indicator"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
    DOM.chatMessages.appendChild(typEl);
    scrollChatBottom();

    try {
      const chat = getActiveChat();
      const history = chat.messages.filter(m => m.role === 'user' || m.role === 'bot').slice(-10).map(m => ({ role: m.role === 'bot' ? 'assistant' : m.role, content: m.content }));
      history.pop();
      const res = await apiReq('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text || 'Analyze the attached files', history, model: APP_CONFIG.MODEL, top_k: APP_CONFIG.TOP_K })
      });
      const el = document.getElementById('typingIndicator'); if (el) el.remove();
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('text/event-stream')) { await handleStream(res); }
      else { const data = await res.json(); addMessage('bot', data.response, data.sources || null); renderChatMessages(); }
    } catch (error) {
      const el = document.getElementById('typingIndicator'); if (el) el.remove();
      if (error.message.includes('Backend URL not configured')) {
        addMessage('bot', '⚙️ **Backend not connected.** Open Settings and paste your ngrok URL.');
      } else { addMessage('bot', `❌ ** Error:** ${error.message} `); }
      renderChatMessages();
    } finally { state.isStreaming = false; }
  }

  async function handleStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullText = '', sources = null, buffer = '';
    const msgId = addMessage('bot', '').id;
    renderChatMessages();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n'); buffer = lines.pop();
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') continue;
            try {
              const parsed = JSON.parse(data);
              if (parsed.token) { fullText += parsed.token; updateMsgContent(msgId, fullText); scrollChatBottom(); }
              if (parsed.sources) sources = parsed.sources;
            } catch (e) { fullText += data; updateMsgContent(msgId, fullText); scrollChatBottom(); }
          }
        }
      }
    } catch (e) { }
    const chat = getActiveChat();
    if (chat) { const msg = chat.messages.find(m => m.id === msgId); if (msg) { msg.content = fullText; msg.sources = sources; saveChats(); } }
    renderChatMessages();
  }
  function updateMsgContent(msgId, content) {
    const el = DOM.chatMessages.querySelector(`[data - msg - id= "${msgId}"] .message - text`);
    if (el) el.innerHTML = renderMd(content);
  }

  // ═══ Upload Panel ═══
  function openUploadPanel() { DOM.uploadPanel.classList.add('open'); DOM.uploadPanelOverlay.classList.add('open'); fetchDocuments(); }
  function closeUploadPanel() { DOM.uploadPanel.classList.remove('open'); DOM.uploadPanelOverlay.classList.remove('open'); }

  async function uploadFiles(files) {
    for (const file of Array.from(files)) {
      if (file.size > APP_CONFIG.MAX_FILE_SIZE) { showToast(`Too large: ${file.name} `, 'warning'); continue; }
      const docId = genId();
      const doc = { id: docId, name: file.name, type: getExt(file.name), size: file.size, status: 'uploading', pages: 0 };
      state.uploadedDocs.push(doc); renderDocList();
      try {
        const fd = new FormData(); fd.append('file', file); fd.append('doc_id', docId);
        const res = await apiReq('/api/upload', { method: 'POST', body: fd });
        const data = await res.json();
        doc.status = 'indexed'; doc.pages = data.pages || 0;
        renderDocList(); showToast(`Uploaded: ${file.name} `, 'success');
      } catch (e) { doc.status = 'error'; renderDocList(); showToast(`Upload failed: ${file.name} `, 'error'); }
    }
    updateDocBadge();
    if (state.currentPage === 'documents') renderPage();
  }

  function renderDocList() {
    const container = DOM.documentList;
    container.querySelectorAll('.document-item').forEach(el => el.remove());
    state.uploadedDocs.forEach(doc => {
      const ext = getExt(doc.name);
      const icon = getFileIcon(ext);
      const tc = getFileClass(ext);
      const item = document.createElement('div'); item.className = 'document-item';
      const sLabel = doc.status === 'indexing' ? '⟳ Indexing' : doc.status === 'indexed' ? '✓ Ready' : doc.status === 'uploading' ? '⬆ Up…' : '✕ Error';
      item.innerHTML = `< div class="doc-icon ${tc}" > ${icon}</div ><div class="doc-info"><div class="doc-name">${esc(doc.name)}</div><div class="doc-meta">${fmtSize(doc.size || 0)}${doc.pages ? ' · ' + doc.pages + ' pg' : ''}</div></div><span class="doc-status ${doc.status}">${sLabel}</span><button class="doc-delete" title="Remove">🗑</button>`;
      item.querySelector('.doc-delete').addEventListener('click', async () => {
        try { await apiReq(`/ api / documents / ${doc.id} `, { method: 'DELETE' }); state.uploadedDocs = state.uploadedDocs.filter(d => d.id !== doc.id); renderDocList(); updateDocBadge(); showToast('Removed', 'info'); } catch (e) { showToast('Delete failed', 'error'); }
      });
      container.appendChild(item);
    });
    DOM.docTotalCount.textContent = `${state.uploadedDocs.length} file${state.uploadedDocs.length !== 1 ? 's' : ''} `;
  }

  // ═══ Settings ═══
  function openSettings() {
    DOM.apiUrlInput.value = getApiUrl();
    DOM.modelSelect.value = APP_CONFIG.MODEL;
    DOM.topKInput.value = APP_CONFIG.TOP_K;
    DOM.settingsModal.classList.add('open');
  }
  function closeSettings() { DOM.settingsModal.classList.remove('open'); }
  function saveSettings() {
    const url = DOM.apiUrlInput.value.trim();
    APP_CONFIG.API_URL = url;
    APP_CONFIG.MODEL = DOM.modelSelect.value;
    APP_CONFIG.TOP_K = Math.max(1, Math.min(20, parseInt(DOM.topKInput.value) || 5));
    localStorage.setItem(APP_CONFIG.STORAGE_KEYS.API_URL, url);
    localStorage.setItem(APP_CONFIG.STORAGE_KEYS.MODEL, APP_CONFIG.MODEL);
    localStorage.setItem(APP_CONFIG.STORAGE_KEYS.TOP_K, String(APP_CONFIG.TOP_K));
    closeSettings();
    showToast('Settings saved!', 'success');
    checkConnection();
    fetchAllData();
  }

  // ═══ Image Preview ═══
  function openImagePreview(url) { DOM.imagePreviewImg.src = url; DOM.imagePreviewOverlay.classList.add('open'); }
  function closeImagePreview() { DOM.imagePreviewOverlay.classList.remove('open'); DOM.imagePreviewImg.src = ''; }

  // ═══ Sidebar ═══
  function openSidebar() { DOM.sidebar.classList.add('open'); DOM.sidebarOverlay.classList.add('open'); }
  function closeSidebar() { DOM.sidebar.classList.remove('open'); DOM.sidebarOverlay.classList.remove('open'); }

  // ═══ Event Listeners ═══
  function initEvents() {
    $$('.nav-item[data-page]').forEach(item => item.addEventListener('click', () => navigateTo(item.dataset.page)));
    $$('.nav-group-header').forEach(hdr => hdr.addEventListener('click', () => { state.expandedGroups[hdr.dataset.group] = !state.expandedGroups[hdr.dataset.group]; updateNavGroups(); }));

    // Sidebar
    DOM.btnSidebarToggle.addEventListener('click', openSidebar);
    DOM.btnCloseSidebar.addEventListener('click', closeSidebar);
    DOM.sidebarOverlay.addEventListener('click', closeSidebar);

    // Chat panel
    DOM.btnToggleChat.addEventListener('click', hideChat);
    DOM.btnOpenChatMobile.addEventListener('click', showChat);
    DOM.chatOverlay.addEventListener('click', hideChat);

    // Chat session management
    DOM.btnNewChat.addEventListener('click', () => { createNewChat(); renderChatMessages(); closeChatHistory(); });
    DOM.btnChatHistory.addEventListener('click', toggleChatHistory);
    DOM.btnCloseHistory.addEventListener('click', closeChatHistory);

    // Chat panel resize
    initChatResize();

    // Chat input — auto-resize textarea
    DOM.chatInput.addEventListener('input', () => autoResize(DOM.chatInput));
    DOM.chatInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); } });
    DOM.btnChatSend.addEventListener('click', sendChatMessage);

    // Chat file attachment
    DOM.btnChatAttach.addEventListener('click', () => DOM.chatFileInput.click());
    DOM.chatFileInput.addEventListener('change', e => { if (e.target.files.length > 0) { addPendingFiles(e.target.files); e.target.value = ''; } });

    // Settings
    DOM.btnOpenSettings.addEventListener('click', openSettings);
    DOM.btnHeaderSettings.addEventListener('click', openSettings);
    DOM.btnCloseSettings.addEventListener('click', closeSettings);
    DOM.btnCancelSettings.addEventListener('click', closeSettings);
    DOM.btnSaveSettings.addEventListener('click', saveSettings);
    DOM.settingsModal.addEventListener('click', e => { if (e.target === DOM.settingsModal) closeSettings(); });

    // CRUD
    DOM.btnCloseCrud.addEventListener('click', closeCrudModal);
    DOM.btnCancelCrud.addEventListener('click', closeCrudModal);
    DOM.btnSaveCrud.addEventListener('click', async () => {
      const crudAct = DOM.btnSaveCrud.dataset.crudAction;
      const crudId = DOM.btnSaveCrud.dataset.crudId;

      // Project & Task saves (use dataset.crudAction pattern)
      if (crudAct === 'save-new-project') {
        const name = $('#projFName')?.value.trim();
        const project_code = $('#projFCode')?.value.trim();
        if (!name || !project_code) { showToast('Name and Project Code are required', 'warning'); return; }
        const body = {
          name, project_code,
          manager: $('#projFMgr')?.value.trim(),
          type: $('#projFType')?.value,
          status: $('#projFStatus')?.value || 'Active',
          start_date: $('#projFStart')?.value,
          end_date: $('#projFEnd')?.value,
          description: $('#projFDesc')?.value.trim(),
          address_line1: $('#projFAddr1')?.value.trim(),
          address_line2: $('#projFAddr2')?.value.trim(),
          city: $('#projFCity')?.value.trim(),
          state: $('#projFState')?.value.trim(),
          postal_code: $('#projFPostal')?.value.trim(),
          country: $('#projFCountry')?.value.trim(),
        };
        try {
          await apiReq('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          await fetchProjects();
          closeCrudModal();
          renderPage();
          showToast('Project created', 'success');
        } catch (err) { showToast(err.message, 'error'); }
        return;
      }
      if (crudAct === 'save-edit-project') {
        const name = $('#projFName')?.value.trim();
        const project_code = $('#projFCode')?.value.trim();
        if (!name || !project_code) { showToast('Name and Project Code are required', 'warning'); return; }
        const body = {
          name, project_code,
          manager: $('#projFMgr')?.value.trim(),
          type: $('#projFType')?.value,
          status: $('#projFStatus')?.value,
          start_date: $('#projFStart')?.value,
          end_date: $('#projFEnd')?.value,
          description: $('#projFDesc')?.value.trim(),
          address_line1: $('#projFAddr1')?.value.trim(),
          address_line2: $('#projFAddr2')?.value.trim(),
          city: $('#projFCity')?.value.trim(),
          state: $('#projFState')?.value.trim(),
          postal_code: $('#projFPostal')?.value.trim(),
          country: $('#projFCountry')?.value.trim(),
        };
        try {
          await apiReq(`/ api / projects / ${crudId} `, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          await fetchProjects();
          // Refresh dashboard data if currently on project-details
          if (state.activeProjectId === crudId) {
            const updated = state.projects.find(p => p.id === crudId);
            if (updated) Object.assign(updated, body);
          }
          closeCrudModal();
          renderPage();
          showToast('Project updated', 'success');
        } catch (err) { showToast(err.message, 'error'); }
        return;
      }
      if (crudAct === 'save-new-task') {
        const name = $('#taskFName')?.value.trim();
        if (!name) { showToast('Task name is required', 'warning'); return; }
        const body = {
          name,
          assignee: $('#taskFAssignee')?.value.trim(),
          due_date: $('#taskFDue')?.value,
          status: $('#taskFStatus')?.value || 'Open',
        };
        try {
          await apiReq(`/ api / projects / ${crudId} /tasks`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          await fetchProjectTasks(crudId);
          closeCrudModal();
          const el = $('#projTasksList');
          if (el) el.innerHTML = renderProjectTasksSection();
          else renderPage();
          showToast('Task added', 'success');
        } catch (err) { showToast(err.message, 'error'); }
        return;
      }

      // Existing trade/vendor/team-member pattern
      if (crudCallback && await crudCallback()) { closeCrudModal(); renderPage(); showToast('Saved', 'success'); }
    });
    DOM.crudModal.addEventListener('click', e => { if (e.target === DOM.crudModal) closeCrudModal(); });

    // Doc Preview
    DOM.btnCloseDocPreview.addEventListener('click', closeDocPreview);
    DOM.docPreviewModal.addEventListener('click', e => { if (e.target === DOM.docPreviewModal) closeDocPreview(); });

    // Upload panel
    DOM.btnCloseUploadPanel.addEventListener('click', closeUploadPanel);
    DOM.uploadPanelOverlay.addEventListener('click', closeUploadPanel);
    DOM.dropZone.addEventListener('dragover', e => { e.preventDefault(); DOM.dropZone.classList.add('drag-over'); });
    DOM.dropZone.addEventListener('dragleave', () => DOM.dropZone.classList.remove('drag-over'));
    DOM.dropZone.addEventListener('drop', e => { e.preventDefault(); DOM.dropZone.classList.remove('drag-over'); uploadFiles(e.dataTransfer.files); });
    DOM.fileInput.addEventListener('change', e => { if (e.target.files.length > 0) { uploadFiles(e.target.files); e.target.value = ''; } });

    // Image preview
    DOM.imagePreviewOverlay.addEventListener('click', e => { if (e.target === DOM.imagePreviewOverlay || e.target.closest('.image-preview-close')) closeImagePreview(); });

    // Escape key
    document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeImagePreview(); closeSettings(); closeCrudModal(); closeUploadPanel(); closeDocPreview(); } });

    // Close multi-select dropdowns when clicking outside (registered once at startup)
    document.addEventListener('click', e => {
      if (!e.target.closest('.multi-select-wrap')) {
        $$('.multi-select-dropdown').forEach(d => d.classList.remove('open'));
      }
    });

    // Handle resize — reset sidebar/chat state
    window.addEventListener('resize', () => {
      if (window.innerWidth > 768) closeSidebar();
    });
  }

  // ═══ Init ═══
  function init() {
    loadChats();
    initEvents();
    updateNavGroups();
    navigateTo('all-projects');
    renderChatMessages();
    renderChatHistory();
    if (getApiUrl()) { checkConnection(); fetchAllData(); }
    else {
      setTimeout(() => showToast('Configure your backend URL in Settings to get started.', 'info', 6000), 500);
    }
    setInterval(checkConnection, 30000);
  }

  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', init) : init();
})();