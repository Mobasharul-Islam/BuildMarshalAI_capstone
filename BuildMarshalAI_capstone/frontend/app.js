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
    projectTasks: [],
    projectSources: [],
    uploadProjectId: null,
    isRecordingVoice: false,
    isTranscribingVoice: false,
    voiceRecorder: null,
    voiceStream: null,
    voiceChunks: [],
    voiceStopTimer: null,
    // Which box a dictated phrase lands in, and which button shows the
    // recording state. Defaults to the chat composer.
    voiceTarget: null,
    // One slice per connected-workspace provider; see WORKSPACE_PROVIDERS.
    providers: {},
    activeWorkspaceProvider: 'google',
    taskBoard: null,
    taskTypes: [],
    projectTypes: [],
    // The account's roles, the permission catalogue behind the role form, and
    // what this user may do. The server decides all three.
    userRoles: [],
    rolesEditable: false,
    permissionGroups: [],
    myPermissions: [],
    // The to-do list being composed: its filters, the preview the server
    // returned, and whether a send is awaiting confirmation.
    todo: null,
    // The onboarding draft being built from uploaded documents, and the
    // step of the flow on screen. Nothing here is live data.
    onboarding: null,
    // Company Settings catalogs and profile, with whether this user may edit
    // them. The server decides; this only chooses what to draw.
    catalogsEditable: false,
    company: null,
    projectTab: null,
    // Computed project figures, the report built from them, and what the
    // document store costs. All read-only views over server-side numbers.
    stats: null,
    storage: null,
    calendar: null,
    // Deadline notifications: open state and the poll that keeps "next two
    // days" true as the clock moves.
    notificationsOpen: false,
    _notificationTimer: null,
    // An online meeting being scheduled over several chat turns:
    // { providerId, known, stage: 'collecting' | 'confirming' }
    pendingMeet: null,
    // An event edit awaiting a yes/no in chat:
    // { providerId, accountId, eventId, title, patch }
    pendingEventEdit: null,
    activeEvidence: null,
    activeEvidenceMessageId: null,
    // The session is the only thing that decides which account's data the app
    // may load; everything below it is refreshed whenever it changes.
    session: null,
    currentUser: null,
    account: null,
    settings: {},
    userDropdownOpen: false,
    conversationsLoaded: false,
    _conversationSaveTimer: null
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
    btnNotifications: $('#btnNotifications'),
    notifBadge: $('#notifBadge'),
    notifPanel: $('#notifPanel'),
    chatPanel: $('#chatPanel'),
    chatOverlay: $('#chatOverlay'),
    chatMessages: $('#chatMessages'),
    chatInput: $('#chatInput'),
    chatAttachments: $('#chatAttachments'),
    chatFileInput: $('#chatFileInput'),
    btnVoiceInput: $('#btnVoiceInput'),
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
    voiceApiUrlInput: $('#voiceApiUrlInput'),
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
    evidenceModal: $('#evidenceModal'),
    evidenceTitle: $('#evidenceTitle'),
    evidenceSubtitle: $('#evidenceSubtitle'),
    evidenceBody: $('#evidenceBody'),
    btnCloseEvidence: $('#btnCloseEvidence'),
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
    chatResizeHandle: $('#chatResizeHandle'),
    userProfileHeader: $('#userProfileHeader'),
    authGate: $('#authGate'),
    authApiUrlInput: $('#authApiUrlInput'),
    tabBtnSignIn: $('#tabBtnSignIn'),
    tabBtnSignUp: $('#tabBtnSignUp'),
    formSignIn: $('#formSignIn'),
    formSignUp: $('#formSignUp'),
    signInError: $('#signInError'),
    signUpError: $('#signUpError'),
    btnSignInSubmit: $('#btnSignInSubmit'),
    btnSignUpSubmit: $('#btnSignUpSubmit'),
    linkSwitchToSignUp: $('#linkSwitchToSignUp'),
    linkSwitchToSignIn: $('#linkSwitchToSignIn')
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
  // Conversations belong to an account, so the browser cache is keyed by
  // account id and the server copy is the source of truth.  Two accounts used
  // from the same browser can never read each other's history.
  function accountScopedKey(base) {
    const accountId = state.account && state.account.id;
    return accountId ? `${base}::${accountId}` : base;
  }

  function saveChats() {
    try {
      localStorage.setItem(accountScopedKey(APP_CONFIG.STORAGE_KEYS.CHATS), JSON.stringify(state.chats));
      localStorage.setItem(accountScopedKey(APP_CONFIG.STORAGE_KEYS.ACTIVE_CHAT), state.activeChatId || '');
    } catch (e) { }
    scheduleConversationSync();
  }

  function loadChats() {
    state.chats = {};
    state.activeChatId = null;
    try {
      const raw = localStorage.getItem(accountScopedKey(APP_CONFIG.STORAGE_KEYS.CHATS));
      if (raw) state.chats = JSON.parse(raw) || {};
      state.activeChatId = localStorage.getItem(accountScopedKey(APP_CONFIG.STORAGE_KEYS.ACTIVE_CHAT)) || null;
    } catch (e) { state.chats = {}; }
  }

  function scheduleConversationSync() {
    if (!state.session || !state.conversationsLoaded) return;
    clearTimeout(state._conversationSaveTimer);
    state._conversationSaveTimer = setTimeout(async () => {
      try {
        await apiReq('/api/conversations', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conversations: state.chats })
        });
      } catch (e) { /* the local cache still holds the history */ }
    }, 800);
  }

  async function loadConversations() {
    state.conversationsLoaded = false;
    loadChats();
    try {
      const res = await apiReq('/api/conversations');
      const data = await res.json();
      const remote = data.conversations || {};
      // The server copy wins; the local cache only covers an offline backend.
      if (Object.keys(remote).length || !Object.keys(state.chats).length) state.chats = remote;
      if (!state.chats[state.activeChatId]) {
        const ids = Object.keys(state.chats)
          .sort((a, b) => (state.chats[a].createdAt || 0) - (state.chats[b].createdAt || 0));
        state.activeChatId = ids.length ? ids[ids.length - 1] : null;
      }
    } catch (e) { /* keep whatever the cache had */ }
    state.conversationsLoaded = true;
    try {
      localStorage.setItem(accountScopedKey(APP_CONFIG.STORAGE_KEYS.CHATS), JSON.stringify(state.chats));
    } catch (e) { }
  }

  // ═══ API ═══
  function getApiUrl() { return APP_CONFIG.API_URL || localStorage.getItem(APP_CONFIG.STORAGE_KEYS.API_URL) || ''; }
  function getVoiceApiUrl() { return APP_CONFIG.VOICE_API_URL || (state.settings && state.settings.voice_api_url) || ''; }

  function getToken() { return (state.session && state.session.token) || ''; }

  /** Routes that act on a linked Google or Microsoft account, not on this app. */
  const PROVIDER_ROUTE = /^\/api\/(google|microsoft)\//;

  async function apiReq(endpoint, opts = {}) {
    const base = getApiUrl();
    if (!base) throw new Error('Backend URL not configured. Open Settings.');
    const headers = { ...opts.headers, 'ngrok-skip-browser-warning': 'true' };
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${base.replace(/\/$/, '')}${endpoint}`, { ...opts, headers });
    if (!res.ok) {
      // An expired or revoked session must drop the app straight back to the
      // gate rather than leaving stale account data on screen.
      //
      // A 401 from a connected Google or Microsoft route is a different thing
      // entirely: that link needs reconnecting, and the BuildMarshal session
      // is still perfectly good. Signing the user out for it locked them out
      // of the whole app the moment a provider token lapsed.
      if (res.status === 401 && !opts.skipAuthRedirect && !PROVIDER_ROUTE.test(endpoint)) {
        handleSessionExpired();
        throw new Error('Your session has ended. Please sign in again.');
      }
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail || `API error: ${res.status}`);
    }
    return res;
  }

  // ═══ Voice input (separate Whisper service) ═══
  /** The box a dictated phrase lands in: the chat composer unless another asked. */
  function voiceInput() {
    const target = state.voiceTarget && $(`#${state.voiceTarget.inputId}`);
    return target || DOM.chatInput;
  }

  function voiceButton() {
    const target = state.voiceTarget && $(`#${state.voiceTarget.buttonId}`);
    return target || DOM.btnVoiceInput;
  }

  function setVoiceButton(mode) {
    const button = voiceButton();
    if (!button) return;
    const icon = button.querySelector('.material-icons-outlined');
    button.classList.toggle('recording', mode === 'recording');
    button.classList.toggle('transcribing', mode === 'transcribing');
    button.disabled = mode === 'transcribing';
    if (icon) icon.textContent = mode === 'recording' ? 'stop' : (mode === 'transcribing' ? 'hourglass_top' : 'mic');
    button.title = mode === 'recording' ? 'Stop recording' : (mode === 'transcribing' ? 'Transcribing…' : 'Record voice message');
    button.setAttribute('aria-label', button.title);
    if (mode === 'idle') state.voiceTarget = null;
  }

  function stopVoiceTracks() {
    if (state.voiceStream) state.voiceStream.getTracks().forEach(track => track.stop());
    state.voiceStream = null;
    if (state.voiceStopTimer) clearTimeout(state.voiceStopTimer);
    state.voiceStopTimer = null;
  }

  async function transcribeVoice(blob) {
    const base = getVoiceApiUrl();
    if (!base) throw new Error('Voice service URL not configured. Open Settings.');
    state.isTranscribingVoice = true;
    setVoiceButton('transcribing');
    try {
      const extension = blob.type.includes('ogg') ? 'ogg' : (blob.type.includes('mp4') ? 'm4a' : 'webm');
      const file = new File([blob], `voice-message.${extension}`, { type: blob.type || 'audio/webm' });
      const form = new FormData();
      form.append('file', file);
      const response = await fetch(`${base.replace(/\/$/, '')}/api/transcribe`, {
        method: 'POST',
        headers: { 'ngrok-skip-browser-warning': 'true' },
        body: form
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Voice API error: ${response.status}`);
      const transcript = (data.text || '').trim();
      if (!transcript) throw new Error('No speech was detected. Please try again closer to the microphone.');
      const target = voiceInput();
      target.value = `${target.value.trim()}${target.value.trim() ? ' ' : ''}${transcript}`;
      if (target === DOM.chatInput) autoResize(target);
      target.focus();
      const language = data.language ? ` (${String(data.language).toUpperCase()})` : '';
      showToast(`Voice transcribed${language}. Review it, then press Send.`, 'success', 5000);
    } finally {
      state.isTranscribingVoice = false;
      setVoiceButton('idle');
    }
  }

  function stopVoiceRecording() {
    if (!state.voiceRecorder || state.voiceRecorder.state === 'inactive') return;
    state.voiceRecorder.stop();
  }

  async function toggleVoiceRecording() {
    if (state.isTranscribingVoice) return;
    if (state.isRecordingVoice) { stopVoiceRecording(); return; }
    if (!getVoiceApiUrl()) {
      openSettings();
      showToast('Add the Voice Service URL before recording.', 'warning', 5000);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      showToast('Voice recording is not supported by this browser.', 'error');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const preferredTypes = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'];
      const mimeType = preferredTypes.find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      state.voiceStream = stream;
      state.voiceRecorder = recorder;
      state.voiceChunks = [];
      recorder.addEventListener('dataavailable', event => { if (event.data.size) state.voiceChunks.push(event.data); });
      recorder.addEventListener('stop', async () => {
        const chunks = state.voiceChunks;
        state.voiceChunks = [];
        state.isRecordingVoice = false;
        stopVoiceTracks();
        if (!chunks.length) { setVoiceButton('idle'); return; }
        try {
          await transcribeVoice(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }));
        } catch (error) {
          showToast(error.message, 'error', 6000);
          setVoiceButton('idle');
        }
      });
      recorder.start(250);
      state.isRecordingVoice = true;
      setVoiceButton('recording');
      showToast('Recording… click the red stop button when finished.', 'info', 4000);
      state.voiceStopTimer = setTimeout(() => {
        if (state.isRecordingVoice) {
          stopVoiceRecording();
          showToast('Maximum recording length is 60 seconds.', 'info');
        }
      }, 60000);
    } catch (error) {
      stopVoiceTracks();
      state.isRecordingVoice = false;
      setVoiceButton('idle');
      showToast(error.name === 'NotAllowedError' ? 'Microphone permission was denied.' : `Could not start microphone: ${error.message}`, 'error');
    }
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
  async function fetchProjectSources(projectId) {
    if (!projectId) { state.projectSources = []; return; }
    try {
      const r = await apiReq(`/api/projects/${projectId}/source-documents`);
      const d = await r.json();
      state.projectSources = (d.documents || []).map(doc => ({
        ...doc,
        pages: doc.pages ?? doc.page_count ?? 0,
        page_count: doc.page_count ?? doc.pages ?? 0,
      }));
    } catch (e) { state.projectSources = []; }
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
    if (!getApiUrl() || !state.session) return;
    await Promise.all([fetchTrades(), fetchVendors(), fetchTeamMembers(), fetchDocuments(),
                       fetchUsers(), fetchProjects(), fetchTaskTypes(), fetchProjectTypes(),
                       fetchCompany(), fetchUserRoles()]);
    renderPage();
  }

  // ═══ Navigation ═══
  const PAGE_TITLES = {
    'all-projects': 'Projects', 'project-details': 'Project Details',
    'trades': 'Trades Management', 'vendors': 'Vendors Management',
    'documents': 'Documents', 'marshal-chat': 'Marshal Chat',
    'google-workspace': 'Google Workspace', 'microsoft-workspace': 'Microsoft 365',
    'users': 'User', 'contact': 'Contact', 'my-feedback': 'My Feedback',
    'company-info': 'Company Info', 'project-types': 'Project Types',
    'user-roles': 'User Roles', 'todo-lists': 'To-Do Lists',
    'task-types': 'Task Types', 'tasks': 'Tasks', 'calendar': 'Calendar',
    'onboarding': 'Project Onboarding',
    'account': 'My Account'
  };

  function navigateTo(page) {
    if (page !== 'company-info') state._companyEditing = false;
    state.currentPage = page;
    $$('.nav-item').forEach(i => i.classList.remove('active'));
    const active = $(`.nav-item[data-page="${page}"]`);
    if (active) active.classList.add('active');
    if (['all-projects', 'project-details'].includes(page)) state.expandedGroups.projects = true;
    if (['trades', 'vendors', 'users', 'contact', 'my-feedback', 'company-info', 'project-types', 'task-types', 'user-roles'].includes(page))
      state.expandedGroups.companySettings = true;
    updateNavGroups();
    DOM.headerPageTitle.textContent = PAGE_TITLES[page] || page;
    renderPage();
    closeSidebar();
  }

  function updateNavGroups() {
    // Onboarding creates projects, people, types, and roles, so it is offered
    // only to administrators. The API refuses everyone else regardless.
    const onboardingNav = $('#navOnboarding');
    if (onboardingNav) onboardingNav.hidden = !isAccountAdmin();
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
      case 'documents':
        DOM.contentArea.innerHTML = renderDocumentsPage() + renderStoragePanel();
        break;
      case 'google-workspace': DOM.contentArea.innerHTML = renderWorkspacePage('google'); break;
      case 'microsoft-workspace': DOM.contentArea.innerHTML = renderWorkspacePage('microsoft'); break;
      case 'marshal-chat': DOM.contentArea.innerHTML = renderChatFullPage(); showChat(); break;
      case 'users': renderUsersPage(); break;
      case 'account': renderAccountPage(); break;
      case 'create-user': renderCreateUserPage(); break;
      case 'edit-user': renderEditUserPage(state._editUserId); break;
      case 'tasks': renderTasksPage(); break;
      case 'calendar': DOM.contentArea.innerHTML = renderCalendarPage(); break;
      case 'company-info': DOM.contentArea.innerHTML = renderCompanyInfoPage(); break;
      case 'task-types': DOM.contentArea.innerHTML = renderTypeCatalogPage('task'); break;
      case 'user-roles': DOM.contentArea.innerHTML = renderUserRolesPage(); break;
      case 'todo-lists': DOM.contentArea.innerHTML = renderTodoListPage(); break;
      case 'onboarding': DOM.contentArea.innerHTML = renderOnboardingPage(); break;
      case 'project-types': DOM.contentArea.innerHTML = renderTypeCatalogPage('project'); break;
      case 'contact': case 'my-feedback':
        DOM.contentArea.innerHTML = `<div class="empty-state"><span class="material-icons-outlined">construction</span><h3>${PAGE_TITLES[page] || page}</h3><p>This section is coming soon.</p></div>`; break;
      default: renderAllProjectsPage(); break;
    }
    bindPageEvents();
    // Opening Company Info before the first bootstrap finished should fetch it
    // rather than sit on the loading line.
    if (page === 'company-info' && !state.company && !state._companyLoading && getApiUrl() && state.session) {
      state._companyLoading = true;
      fetchCompany().finally(() => { state._companyLoading = false; renderPage(); });
    }
    if (page === 'todo-lists' && !todoState().loaded && !todoState().loading) refreshTodoPreview();
    if (page === 'documents' && !storageState().data && !storageState().loading
        && getApiUrl() && state.session) loadStorage();
    if (page === 'onboarding' && isAccountAdmin() && !onboarding().loaded && !onboarding().loading
        && getApiUrl() && state.session) {
      fetchOnboardingDrafts().then(() => { if (state.currentPage === 'onboarding') renderPage(); });
    }
    // The role editor reuses the permission catalogue, so make sure it is there.
    if (page === 'onboarding' && !state.permissionGroups.length && getApiUrl() && state.session) {
      fetchPermissionCatalogue();
    }
    if (page === 'user-roles' && !state.permissionGroups.length && getApiUrl() && state.session) {
      fetchPermissionCatalogue().then(() => { if (state.currentPage === 'user-roles') renderPage(); });
    }
    if (page === 'calendar' && !calendarState().loaded && !calendarState().loading) loadCalendar();
    if (page === 'tasks' && !taskBoard().loading && !taskBoard()._loaded) {
      taskBoard()._loaded = true;
      fetchBoardTasks().then(renderPage);
    }
    const workspaceMatch = /^(google|microsoft)-workspace$/.exec(page);
    if (workspaceMatch) {
      const providerId = workspaceMatch[1];
      state.activeWorkspaceProvider = providerId;
      if (!ws(providerId).config && !ws(providerId).loading) loadWorkspaceProvider(providerId);
    }
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

  // ═══ Company Settings ═══
  //
  // The company profile and the two type catalogs. Everyone in the account can
  // read them; only administrators see the controls that change them, and the
  // backend refuses the write regardless of what this page renders.

  const COMPANY_SECTIONS = [
    ['Identity', [
      ['name', 'Company name', 'required'], ['legal_name', 'Registered legal name'],
      ['registration_number', 'Company registration number'], ['tax_id', 'Tax / VAT number'],
      ['industry', 'Industry'], ['founded', 'Founded'],
    ]],
    ['Contact', [
      ['email', 'Email', 'email'], ['phone', 'Phone'], ['website', 'Website'],
    ]],
    ['Registered address', [
      ['address_line1', 'Address line 1'], ['address_line2', 'Address line 2'],
      ['city', 'City'], ['state', 'State / Region'],
      ['postal_code', 'Postal code'], ['country', 'Country'],
    ]],
    ['Primary contact', [
      ['contact_name', 'Contact name'], ['contact_role', 'Role'],
      ['contact_email', 'Contact email', 'email'], ['contact_phone', 'Contact phone'],
    ]],
  ];

  /** Unlike detailRow, an unset company field is shown as blank rather than hidden. */
  function companyRow(label, value) {
    return `<div class="cal-detail-row"><span>${esc(label)}</span><b>${value ? esc(String(value)) : '—'}</b></div>`;
  }

  function companyBreadcrumb(label) {
    return `<div class="breadcrumb"><a href="#" data-nav="all-projects"><span class="material-icons-outlined">home</span></a><span class="sep">/</span><span>Company Settings</span><span class="sep">/</span><span>${esc(label)}</span></div>`;
  }

  function renderCompanyInfoPage() {
    const company = state.company;
    if (!company) return `${notConnectedMsg()}${companyBreadcrumb('Company Info')}<div class="empty-msg">Loading company information…</div>`;
    const profile = company.profile || {};
    const editing = !!state._companyEditing;
    const canEdit = company.canEdit;

    const view = COMPANY_SECTIONS.map(([title, fields]) => `
      <div class="detail-card">
        <h3 class="section-sub-title">${esc(title)}</h3>
        <div class="cal-detail-grid">
          ${fields.map(([key, label]) => companyRow(label, profile[key])).join('')}
        </div>
      </div>`).join('');

    const form = COMPANY_SECTIONS.map(([title, fields]) => `
      <div class="detail-card">
        <h3 class="section-sub-title">${esc(title)}</h3>
        <div class="form-grid-2">
          ${fields.map(([key, label, kind]) => `
            <div class="form-group">
              <label class="form-label ${kind === 'required' ? 'required-label' : ''}">${esc(label)}</label>
              <input class="form-input" id="co_${key}" ${kind === 'email' ? 'type="email"' : ''} value="${esc(profile[key] || '')}">
            </div>`).join('')}
        </div>
      </div>`).join('');

    return `${notConnectedMsg()}
      ${companyBreadcrumb('Company Info')}
      <div class="page-header">
        <div><h1 class="page-title">Company Info</h1>
          <p class="page-subtitle">${canEdit
            ? 'Details shared across this workspace. Administrators can edit them.'
            : 'Details shared across this workspace. Only an account administrator can change them.'}</p></div>
        <div class="header-actions">
          ${editing
            ? `<button class="btn btn-secondary" id="btnCompanyCancel">Cancel</button>
               <button class="btn btn-primary" id="btnCompanySave"><span class="material-icons-outlined">save</span> Save changes</button>`
            : canEdit
              ? `<button class="btn btn-primary" id="btnCompanyEdit"><span class="material-icons-outlined">edit</span> Edit</button>`
              : ''}
        </div>
      </div>
      ${company.error ? `<div class="connection-banner warning"><span class="material-icons-outlined">warning</span><span>${esc(company.error)}</span></div>` : ''}
      ${editing ? form : view}
      ${editing ? `<div class="detail-card"><div class="form-group"><label class="form-label">About the company</label>
          <textarea class="form-input" id="co_about" rows="4">${esc(profile.about || '')}</textarea></div></div>`
        : `<div class="detail-card"><h3 class="section-sub-title">About</h3>
            <p class="detail-text">${profile.about ? esc(profile.about) : '<span class="form-hint">No description added yet.</span>'}</p></div>`}
      ${profile.updated_at ? `<p class="form-hint">Last updated ${esc(humanDate(profile.updated_at, true))}${profile.updated_by ? ` by ${esc(profile.updated_by)}` : ''}.</p>` : ''}`;
  }

  // ═══ To-Do Lists ═══
  //
  // One builder serves all three actions, so what you download is exactly what
  // recipients are mailed. Sending is outward-facing: it needs the todo.send
  // permission and an explicit confirmation naming who would be written to.

  function todoState() {
    if (!state.todo) {
      state.todo = {
        filters: { project_id: '', statuses: ['Open', 'In Progress', 'Blocked'],
                   assignee: '', due_before: '', include_archived: false },
        roles: [], per_recipient: false, title: 'To-do list', note: '',
        preview: null, loading: false, loaded: false, sending: false, pending: null
      };
    }
    return state.todo;
  }

  function todoBody(extra = {}) {
    const todo = todoState();
    return { ...todo.filters, roles: todo.roles, per_recipient: todo.per_recipient,
             title: todo.title || 'To-do list', note: todo.note, ...extra };
  }

  async function refreshTodoPreview() {
    const todo = todoState();
    todo.loading = true;
    todo.loaded = true;
    renderPage();
    try {
      const response = await apiReq('/api/todo-list/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(todoBody())
      });
      todo.preview = await response.json();
    } catch (error) {
      todo.preview = null;
      showToast(error.message, 'error');
    } finally {
      todo.loading = false;
      renderPage();
    }
  }

  async function downloadTodoList(format) {
    try {
      const response = await apiReq(`/api/todo-list/download?fmt=${format}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(todoBody())
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      const stamp = new Date().toISOString().slice(0, 10);
      link.download = `${(todoState().title || 'todo-list').replace(/[^a-z0-9._-]+/gi, '-')}-${stamp}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      showToast(`Downloaded as ${format.toUpperCase()}`, 'success');
    } catch (error) {
      showToast(`Could not download the list: ${error.message}`, 'error', 7000);
    }
  }

  /** Two steps: ask what would happen, then do it once the user agrees. */
  async function sendTodoList(confirmed) {
    const todo = todoState();
    const providerId = agentProvider();
    if (!providerId) {
      showToast('Connect a Google or Microsoft account to send a to-do list', 'warning', 7000);
      return;
    }
    todo.sending = true;
    renderPage();
    try {
      const response = await apiReq('/api/todo-list/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(todoBody({
          provider: providerId, account_id: ws(providerId).accountId, confirm: !!confirmed
        }))
      });
      const result = await response.json();
      if (result.confirmation_required) {
        todo.pending = result;
        return;
      }
      todo.pending = null;
      const parts = [`Sent to ${result.sent}`];
      if (result.skipped) parts.push(`${result.skipped} skipped`);
      if (result.failed) parts.push(`${result.failed} failed`);
      showToast(parts.join(' · '), result.failed ? 'warning' : 'success', 7000);
      if (result.failed) {
        console.warn('To-do list send failures:', result.details.failed);
      }
    } catch (error) {
      todo.pending = null;
      showToast(`Could not send the list: ${error.message}`, 'error', 8000);
    } finally {
      todo.sending = false;
      renderPage();
    }
  }

  function renderTodoListPage() {
    const todo = todoState();
    const preview = todo.preview;
    const roles = state.userRoles.map(role => role.name);
    const connected = Object.keys(WORKSPACE_PROVIDERS).filter(id => ws(id).accountId);
    const canSend = preview ? preview.can_send : can('todo.send');

    return `${notConnectedMsg()}
      <div class="page-header">
        <div><h1 class="page-title">To-Do Lists</h1>
          <p class="page-subtitle">Build a list of outstanding work, download it, or send it to everyone holding a role.</p></div>
        <div class="header-actions">
          <button class="btn btn-secondary btn-sm" id="btnTodoRefresh"><span class="material-icons-outlined">refresh</span></button>
          <button class="btn btn-secondary btn-sm" id="btnTodoCsv"><span class="material-icons-outlined" style="font-size:18px">table_view</span> CSV</button>
          <button class="btn btn-secondary btn-sm" id="btnTodoPdf"><span class="material-icons-outlined" style="font-size:18px">picture_as_pdf</span> PDF</button>
          ${canSend ? `<button class="btn btn-primary btn-sm" id="btnTodoSend" ${connected.length ? '' : 'disabled'}>
            <span class="material-icons-outlined" style="font-size:18px">send</span> Send</button>` : ''}
        </div>
      </div>

      <div class="detail-card">
        <h3 class="section-sub-title">What goes on the list</h3>
        <div class="form-grid-2">
          <div class="form-group"><label class="form-label">Project</label>
            <select class="form-input" id="todoProject">
              <option value="">All projects</option>
              ${state.projects.filter(p => !p.archived).map(p =>
                `<option value="${esc(p.id)}" ${todo.filters.project_id === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}
            </select></div>
          <div class="form-group"><label class="form-label">Due on or before</label>
            <input type="date" class="form-input" id="todoDueBefore" value="${esc(todo.filters.due_before)}"></div>
          <div class="form-group"><label class="form-label">Assignee</label>
            <select class="form-input" id="todoAssignee">
              <option value="">Anyone</option>
              ${state.users.map(u => `<option value="${esc(u.name)}" ${todo.filters.assignee === u.name ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}
            </select></div>
          <div class="form-group"><label class="form-label">Title on the list</label>
            <input class="form-input" id="todoTitle" value="${esc(todo.title)}"></div>
        </div>
        <div class="form-group"><label class="form-label">Status</label>
          <div class="todo-status-row">
            ${['Open', 'In Progress', 'Blocked', 'Completed'].map(status => `
              <label class="todo-chip"><input type="checkbox" class="todo-status" value="${status}"
                ${todo.filters.statuses.includes(status) ? 'checked' : ''}> ${status}</label>`).join('')}
          </div></div>
        <div class="form-group"><label class="form-label">Note (appears at the top)</label>
          <input class="form-input" id="todoNote" value="${esc(todo.note)}" placeholder="Optional"></div>
      </div>

      <div class="detail-card">
        <h3 class="section-sub-title">Who it goes to</h3>
        ${roles.length ? `<div class="todo-status-row">
          ${roles.map(role => `<label class="todo-chip"><input type="checkbox" class="todo-role" value="${esc(role)}"
            ${todo.roles.includes(role) ? 'checked' : ''}> ${esc(role)}</label>`).join('')}
        </div>` : '<div class="form-hint">No roles yet. Create one under <b>Company Settings → User Roles</b>.</div>'}
        <label class="cal-meet-toggle" style="margin-top:12px"><input type="checkbox" id="todoPerRecipient" ${todo.per_recipient ? 'checked' : ''}>
          <span>Send each person only <b>their own</b> tasks</span></label>
        ${connected.length ? '' : '<div class="form-hint">Connect a Google or Microsoft account to send. Downloading works either way.</div>'}
        ${canSend ? '' : '<div class="form-hint">Your role cannot send lists to other people. You can still download one.</div>'}
      </div>

      ${todo.pending ? `<div class="connection-banner warning">
        <span class="material-icons-outlined">outgoing_mail</span>
        <span>Send <b>${todo.pending.total}</b> item${todo.pending.total === 1 ? '' : 's'} to
          <b>${todo.pending.recipients.length}</b> recipient${todo.pending.recipients.length === 1 ? '' : 's'}
          (${esc(todo.pending.recipients.map(r => r.email).join(', '))}) via ${esc(todo.pending.provider)}?</span>
        <button class="btn btn-primary btn-sm" id="btnTodoConfirm" ${todo.sending ? 'disabled' : ''}>
          ${todo.sending ? 'Sending…' : 'Yes, send'}</button>
        <button class="btn btn-secondary btn-sm" id="btnTodoCancel">Cancel</button>
      </div>` : ''}

      ${todo.loading ? '<div class="empty-msg">Building the list…</div>' : (preview ? `
        <div class="tasks-section-header">
          <div><h3 class="section-sub-title">${esc(todo.title)}</h3>
            <div class="form-hint">${preview.total} item${preview.total === 1 ? '' : 's'}${
              preview.recipients.length ? ` · ${preview.recipients.length} recipient${preview.recipients.length === 1 ? '' : 's'}` : ' · no recipients chosen'}</div></div>
        </div>
        ${todo.per_recipient && preview.breakdown.length ? `<div class="todo-status-row" style="margin-bottom:10px">
          ${preview.breakdown.map(row => `<span class="role-perm">${esc(row.name || row.email)}: ${row.count}</span>`).join('')}
        </div>` : ''}
        ${preview.total ? `<div class="data-table-container"><table class="data-table">
          <thead><tr><th>Task</th><th>Project</th><th>Assignee</th><th>Priority</th><th>Status</th><th>Due</th></tr></thead>
          <tbody>${preview.tasks.map(row => `<tr>
            <td><strong>${esc(row.name)}</strong></td>
            <td>${esc(row.project_name)}</td>
            <td>${esc(row.assignee || '—')}</td>
            <td>${esc(row.priority)}</td>
            <td><span class="task-status-chip ${taskStatusClass(row.status)}">${esc(row.status)}</span></td>
            <td>${esc(row.due_date || '—')}</td></tr>`).join('')}</tbody>
        </table></div>`
        : '<div class="empty-msg">Nothing outstanding matches these filters.</div>'}`
      : '<div class="empty-msg">Choose your filters, then Refresh to build the list.</div>')}`;
  }

  function bindTodoEvents() {
    const todo = todoState();
    const reload = () => refreshTodoPreview();

    $('#btnTodoRefresh')?.addEventListener('click', reload);
    $('#btnTodoPdf')?.addEventListener('click', () => downloadTodoList('pdf'));
    $('#btnTodoCsv')?.addEventListener('click', () => downloadTodoList('csv'));
    $('#btnTodoSend')?.addEventListener('click', () => sendTodoList(false));
    $('#btnTodoConfirm')?.addEventListener('click', () => sendTodoList(true));
    $('#btnTodoCancel')?.addEventListener('click', () => { todo.pending = null; renderPage(); });

    $('#todoProject')?.addEventListener('change', e => { todo.filters.project_id = e.target.value; reload(); });
    $('#todoAssignee')?.addEventListener('change', e => { todo.filters.assignee = e.target.value; reload(); });
    $('#todoDueBefore')?.addEventListener('change', e => { todo.filters.due_before = e.target.value; reload(); });
    $('#todoTitle')?.addEventListener('input', e => { todo.title = e.target.value; });
    $('#todoNote')?.addEventListener('input', e => { todo.note = e.target.value; });
    $('#todoPerRecipient')?.addEventListener('change', e => { todo.per_recipient = e.target.checked; reload(); });

    $$('.todo-status').forEach(box => box.addEventListener('change', () => {
      todo.filters.statuses = [...document.querySelectorAll('.todo-status:checked')].map(b => b.value);
      reload();
    }));
    $$('.todo-role').forEach(box => box.addEventListener('change', () => {
      todo.roles = [...document.querySelectorAll('.todo-role:checked')].map(b => b.value);
      // Changing the audience invalidates a pending confirmation.
      todo.pending = null;
      reload();
    }));
  }

  // ═══ User Roles ═══
  //
  // Super Admin and System Admin are built in and cannot be edited. Every
  // other role is a name plus the permissions ticked for it, created here.
  // Managing roles is Super Admin work and is deliberately not itself a
  // permission: an authority that could be ticked on a role would be an
  // authority that could be given away.

  function permissionName(key) {
    for (const group of state.permissionGroups) {
      const found = group.permissions.find(entry => entry.key === key);
      if (found) return found.name;
    }
    return key;
  }

  function renderUserRolesPage() {
    const roles = state.userRoles;
    const canManage = state.rolesEditable;
    return `${notConnectedMsg()}
      ${companyBreadcrumb('User Roles')}
      <div class="page-header">
        <div><h1 class="page-title">User Roles</h1>
          <p class="page-subtitle">${canManage
            ? 'Define what each role in this workspace is allowed to do.'
            : 'What each role in this workspace is allowed to do. Only a Super Admin can change these.'}</p></div>
        ${canManage ? '<button class="btn btn-primary" id="btnCreateRole"><span class="material-icons-outlined">add</span> Create Role</button>' : ''}
      </div>
      <div class="filters-bar"><div class="filters-row"></div>
        <div class="filters-meta"><span class="total-count">Total: ${roles.length}</span></div></div>
      ${roles.length ? `<div class="role-grid">${roles.map(role => `
        <div class="role-card ${role.builtin ? 'role-card-builtin' : ''}">
          <div class="role-card-head">
            <div>
              <h3 class="role-card-name">${esc(role.name)}
                ${role.builtin ? '<span class="badge badge-role-system">Built-in</span>' : ''}</h3>
              <div class="form-hint">${esc(role.description || 'No description.')}</div>
            </div>
            ${canManage && role.editable ? `<div class="table-actions">
              <button class="btn-table-action" data-role-edit="${esc(role.id)}" title="Edit"><span class="material-icons-outlined">edit</span></button>
              <button class="btn-table-action delete" data-role-delete="${esc(role.id)}" data-name="${esc(role.name)}" title="Delete"><span class="material-icons-outlined">delete</span></button>
            </div>` : ''}
          </div>
          <div class="role-card-meta">
            <span>${role.users || 0} user${role.users === 1 ? '' : 's'}</span>
            <span>${role.builtin ? 'All permissions' : `${role.permissions.length} permission${role.permissions.length === 1 ? '' : 's'}`}</span>
          </div>
          ${role.builtin
            ? `<div class="form-hint">${role.name === 'Super Admin'
                ? 'Full access, and the only role that can manage roles, permissions, and company information.'
                : 'Account administration, unchanged.'}</div>`
            : (role.permissions.length
              ? `<div class="role-perms">${role.permissions.map(key =>
                  `<span class="role-perm">${esc(permissionName(key))}</span>`).join('')}</div>`
              : '<div class="form-hint">No permissions yet — this role can sign in but do nothing.</div>')}
        </div>`).join('')}</div>`
      : `<div class="empty-state"><span class="material-icons-outlined">badge</span>
          <h3>No roles yet</h3>
          <p>${canManage ? 'Create a role to describe what a group of people may do, then assign it when you add a user.' : 'A Super Admin has not created any roles yet.'}</p></div>`}`;
  }

  function openRoleModal(roleId) {
    const role = roleId ? state.userRoles.find(r => r.id === roleId) : null;
    if (roleId && !role) return;
    const held = new Set(role?.permissions || []);
    DOM.crudModalTitle.textContent = role ? `Edit ${role.name}` : 'Create Role';
    DOM.crudModalBody.innerHTML = `
      <div class="form-group"><label class="form-label required-label">Role name</label>
        <input class="form-input" id="roleName" value="${esc(role?.name || '')}" placeholder="e.g. Site Lead"></div>
      <div class="form-group"><label class="form-label">Description</label>
        <input class="form-input" id="roleDescription" value="${esc(role?.description || '')}" placeholder="What this role is for"></div>
      <div class="form-hint" style="margin-bottom:10px">Tick everything this role should be allowed to do. Managing roles, permissions, and company information stays with Super Admins and cannot be granted here.</div>
      ${state.permissionGroups.map(group => `
        <div class="perm-group">
          <div class="perm-group-head">
            <h4 class="perm-group-title">${esc(group.group)}</h4>
            <button type="button" class="btn btn-ghost btn-sm" data-perm-group="${esc(group.group)}">Select all</button>
          </div>
          ${group.permissions.map(entry => `
            <label class="perm-row">
              <input type="checkbox" class="perm-check" value="${esc(entry.key)}" data-group="${esc(group.group)}" ${held.has(entry.key) ? 'checked' : ''}>
              <span>
                <strong class="perm-name">${esc(entry.name)}</strong>
                <span class="perm-desc">${esc(entry.description)}</span>
              </span>
            </label>`).join('')}
        </div>`).join('')}`;

    DOM.crudModalBody.querySelectorAll('[data-perm-group]').forEach(button =>
      button.addEventListener('click', () => {
        const boxes = [...DOM.crudModalBody.querySelectorAll(`.perm-check[data-group="${CSS.escape(button.dataset.permGroup)}"]`)];
        const turnOn = boxes.some(box => !box.checked);
        boxes.forEach(box => { box.checked = turnOn; });
        button.textContent = turnOn ? 'Clear all' : 'Select all';
      }));

    DOM.btnSaveCrud.dataset.crudAction = 'save-user-role';
    DOM.btnSaveCrud.dataset.crudId = roleId || '';
    DOM.crudModal.classList.add('open');
  }

  async function submitUserRole(roleId) {
    const name = $('#roleName')?.value.trim();
    if (!name) { showToast('Role name is required', 'warning'); return; }
    const permissions = [...document.querySelectorAll('.perm-check:checked')].map(box => box.value);
    const body = { name, description: $('#roleDescription')?.value.trim() || '', permissions };
    const save = DOM.btnSaveCrud;
    save.disabled = true;
    try {
      await apiReq(`/api/user-roles${roleId ? '/' + encodeURIComponent(roleId) : ''}`, {
        method: roleId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      closeCrudModal();
      // A rename follows its holders, so the user list can be stale too.
      await Promise.all([fetchUserRoles(), fetchUsers()]);
      renderPage();
      showToast(roleId ? 'Role updated' : 'Role created', 'success');
    } catch (error) {
      showToast(error.message, 'error', 8000);
    } finally { save.disabled = false; }
  }

  async function deleteUserRole(roleId, name) {
    if (!confirm(`Delete the role "${name}"? Anyone still holding it would lose every permission, so it must be unassigned first.`)) return;
    try {
      await apiReq(`/api/user-roles/${encodeURIComponent(roleId)}`, { method: 'DELETE' });
      await fetchUserRoles();
      renderPage();
      showToast(`${name} deleted`, 'info');
    } catch (error) {
      showToast(error.message, 'error', 8000);
    }
  }

  const TYPE_CATALOGS = {
    task: { key: 'task', title: 'Task Types', segment: 'task-types', noun: 'task type',
            listKey: 'taskTypes', blurb: 'Used by the Task type field when creating or editing a task.' },
    project: { key: 'project', title: 'Project Types', segment: 'project-types', noun: 'project type',
               listKey: 'projectTypes', blurb: 'Used by the Type field on projects and by the project filters.' }
  };

  function renderTypeCatalogPage(kind) {
    const cfg = TYPE_CATALOGS[kind];
    const entries = state[cfg.listKey] || [];
    const canEdit = state.catalogsEditable;
    return `${notConnectedMsg()}
      ${companyBreadcrumb(cfg.title)}
      <div class="page-header">
        <div><h1 class="page-title">${esc(cfg.title)}</h1>
          <p class="page-subtitle">${esc(cfg.blurb)}${canEdit ? '' : ' Only an account administrator can add or remove entries.'}</p></div>
        ${canEdit ? `<button class="btn btn-primary" data-type-add="${cfg.key}"><span class="material-icons-outlined">add</span> Add ${esc(cfg.noun)}</button>` : ''}
      </div>
      <div class="filters-bar"><div class="filters-row"></div>
        <div class="filters-meta"><span class="total-count">Total: ${entries.length}</span></div></div>
      <div class="data-table-container"><table class="data-table">
        <thead><tr><th>Name</th><th>Description</th><th>Status</th>${canEdit ? '<th>Actions</th>' : ''}</tr></thead>
        <tbody>${entries.length ? entries.map(item => `<tr data-id="${esc(item.id)}">
          <td>${esc(item.name)}</td>
          <td>${esc(item.description || '-')}</td>
          <td><span class="badge ${item.status === 'Inactive' ? 'badge-inactive' : 'badge-active'}">${esc(item.status || 'Active')}</span></td>
          ${canEdit ? `<td><div class="table-actions">
            <button class="btn-table-action" data-type-edit="${cfg.key}" data-id="${esc(item.id)}" title="Edit"><span class="material-icons-outlined">edit</span></button>
            <button class="btn-table-action delete" data-type-delete="${cfg.key}" data-id="${esc(item.id)}" data-name="${esc(item.name)}" title="Delete"><span class="material-icons-outlined">delete</span></button>
          </div></td>` : ''}
        </tr>`).join('') : `<tr><td colspan="${canEdit ? 4 : 3}" class="td-empty">${getApiUrl() ? `No ${esc(cfg.noun)}s defined` : 'Connect backend to load types'}</td></tr>`}</tbody>
      </table></div>`;
  }

  async function saveCompanyProfile() {
    const button = $('#btnCompanySave');
    const payload = { about: $('#co_about')?.value.trim() || '' };
    COMPANY_SECTIONS.forEach(([, fields]) => fields.forEach(([key]) => {
      payload[key] = $(`#co_${key}`)?.value.trim() || '';
    }));
    if (!payload.name) { showToast('Company name is required', 'warning'); return; }
    if (button) button.disabled = true;
    try {
      const response = await apiReq('/api/company', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      });
      const saved = await response.json();
      state.company = { profile: saved.company || payload, canEdit: true };
      state._companyEditing = false;
      renderPage();
      showToast('Company information saved', 'success');
    } catch (error) {
      if (button) button.disabled = false;
      showToast(error.message, 'error', 7000);
    }
  }

  async function deleteCatalogEntry(kind, id, name) {
    const cfg = TYPE_CATALOGS[kind];
    if (!confirm(`Delete the ${cfg.noun} “${name}”? Projects and tasks already using it keep the value, but it will no longer be offered.`)) return;
    try {
      await apiReq(`/api/${cfg.segment}/${encodeURIComponent(id)}`, { method: 'DELETE' });
      await refreshCatalog(kind);
      renderPage();
      showToast(`${name} deleted`, 'info');
    } catch (error) {
      // A type still in use, or a member without permission, lands here.
      showToast(error.message, 'error', 8000);
    }
  }

  async function refreshCatalog(kind) {
    if (kind === 'task') await fetchTaskTypes();
    else await fetchProjectTypes();
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
  /** The account's own project types, managed under Company Settings. */
  function projectTypeNames() {
    return state.projectTypes.filter(t => t.status !== 'Inactive').map(t => t.name);
  }

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
          ${can('project.create') ? '<button class="btn btn-primary" id="btnNewProject"><span class="material-icons-outlined">add</span> New Project</button>' : ''}
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
                ${projectTypeNames().map(t => `<label><input type="checkbox" class="proj-type-chk" value="${esc(t)}" ${f.types.includes(t) ? 'checked' : ''}> ${esc(t)}</label>`).join('') || '<span class="form-hint">No project types defined.</span>'}
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
          <button class="btn btn-ghost btn-sm" data-action="upload-project-sources" data-id="${p.id}"><span class="material-icons-outlined">upload_file</span> Upload Sources</button>
          <button class="btn btn-ghost btn-sm" data-action="generate-report" data-id="${p.id}"><span class="material-icons-outlined">picture_as_pdf</span> Generate Doc</button>
          <button class="btn btn-ghost btn-sm" data-action="project-report" data-id="${p.id}"><span class="material-icons-outlined">description</span> Report</button>
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
        <button class="tab-btn ${activeTab === 'procore' ? 'active' : ''}" data-tab="procore">Procurement</button>
        <button class="tab-btn ${activeTab === 'stats' ? 'active' : ''}" data-tab="stats">Statistics</button>
      </div>
      <div class="project-dashboard-content" id="dashTabContent">
        ${activeTab === 'overview' ? renderDashOverview(p, tasksHtml) : renderDashTab(activeTab, p)}
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
            ${can('task.create') ? '<button class="btn btn-primary btn-sm" id="btnOpenTasks"><span class="material-icons-outlined">add_task</span> Add Task</button>' : ''}
            <button class="btn btn-ghost btn-sm" id="btnRefreshTasks"><span class="material-icons-outlined">refresh</span></button>
          </div>
        </div>
        <div id="projTasksList">${tasksHtml}</div>

        <div class="tasks-section-header">
          <h3 class="section-sub-title">Project Documents</h3>
          <div class="tasks-section-actions">
            <span class="total-count">${state.projectSources.length} source${state.projectSources.length === 1 ? '' : 's'}</span>
            <button class="btn btn-primary btn-sm" data-action="upload-project-sources" data-id="${p.id}"><span class="material-icons-outlined">upload_file</span> Upload Source</button>
            <button class="btn btn-ghost btn-sm" id="btnRefreshProjectSources" title="Refresh project documents"><span class="material-icons-outlined">refresh</span></button>
          </div>
        </div>
        <div id="projectSourcesList">${renderProjectSourcesSection()}</div>
      </div>`;
  }

  // Task Manager ------------------------------------------------------------
  //
  // One board over the account's projects: a tab per project the user opens,
  // a filter bar, a task tree with expandable subtasks, and a detail panel for
  // viewing and editing the selected task. Every call is account-scoped by
  // apiReq, so a user only ever sees tasks in their own workspace.

  const TASK_STATUSES = ['Open', 'In Progress', 'Blocked', 'Completed'];
  const TASK_PRIORITIES = ['Low', 'Normal', 'High', 'Urgent'];

  function emptyTaskFilters() {
    return { name: '', trade: '', status: '', assignee: '', priority: '' };
  }

  function taskBoard() {
    if (!state.taskBoard) {
      state.taskBoard = {
        openProjectIds: [],
        activeProjectId: '',
        tasks: [],
        selectedId: null,
        filters: emptyTaskFilters(),
        showArchived: false,
        moveCheckedToBottom: false,
        showMoreFilters: false,
        expanded: {},
        loading: false
      };
    }
    return state.taskBoard;
  }

  function projectName(projectId) {
    return state.projects.find(p => p.id === projectId)?.name || 'Project';
  }

  /** Tasks for the active scope: one project, or every project when on All. */
  async function fetchBoardTasks() {
    const board = taskBoard();
    board.loading = true;
    const params = new URLSearchParams();
    if (board.filters.name) params.set('name', board.filters.name);
    if (board.filters.trade) params.set('trade', board.filters.trade);
    if (board.filters.status) params.set('status', board.filters.status);
    if (board.filters.assignee) params.set('assignee', board.filters.assignee);
    if (board.filters.priority) params.set('priority', board.filters.priority);
    if (board.showArchived) params.set('show_archived', 'true');

    const ids = board.activeProjectId ? [board.activeProjectId] : state.projects.map(p => p.id);
    try {
      const responses = await Promise.all(ids.map(async id => {
        try {
          const res = await apiReq(`/api/projects/${id}/tasks?${params}`);
          return (await res.json()).tasks || [];
        } catch (e) { return []; }
      }));
      board.tasks = responses.flat();
    } finally { board.loading = false; }
  }

  async function fetchTaskTypes() {
    try {
      const r = await apiReq('/api/task-types');
      const d = await r.json();
      state.taskTypes = d.task_types || [];
      state.catalogsEditable = !!d.can_edit;
    } catch (e) { state.taskTypes = []; }
  }

  async function fetchProjectTypes() {
    try {
      const r = await apiReq('/api/project-types');
      const d = await r.json();
      state.projectTypes = d.project_types || [];
      state.catalogsEditable = !!d.can_edit;
    } catch (e) { state.projectTypes = []; }
  }

  async function fetchUserRoles() {
    try {
      const r = await apiReq('/api/user-roles');
      const d = await r.json();
      state.userRoles = d.roles || [];
      state.rolesEditable = !!d.can_manage;
      state.myPermissions = d.my_permissions || [];
    } catch (e) { state.userRoles = []; state.rolesEditable = false; }
  }

  async function fetchPermissionCatalogue() {
    if (state.permissionGroups.length) return;
    try {
      const r = await apiReq('/api/permissions');
      state.permissionGroups = (await r.json()).groups || [];
    } catch (e) { state.permissionGroups = []; }
  }

  /**
   * Whether this user's role allows something.
   *
   * The server resolves this and sends the list; the UI only decides what to
   * draw. A client that lied about it would still be refused on the write.
   */
  function can(permission) {
    return state.myPermissions.includes(permission);
  }

  /** Managing roles is Super Admin work and deliberately not a permission. */
  function isSuperAdmin() {
    const user = state.currentUser;
    return !!user && (!!user.is_owner || user.role === 'Super Admin');
  }

  async function fetchCompany() {
    try {
      const r = await apiReq('/api/company');
      const d = await r.json();
      state.company = { profile: d.company || {}, canEdit: !!d.can_edit };
    } catch (e) { state.company = { profile: {}, canEdit: false, error: e.message }; }
  }

  /**
   * Whether this user may change Company Settings.
   *
   * Mirrors the server's rule so the page does not offer buttons that would be
   * refused; the server enforces it either way, so a client that lies about
   * this gains nothing.
   */
  function isAccountAdmin() {
    const user = state.currentUser;
    if (!user) return false;
    return !!user.is_owner || SYSTEM_ROLES.includes(user.role);
  }

  function selectedTask() {
    const board = taskBoard();
    return board.tasks.find(t => t.id === board.selectedId) || null;
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  function renderTasksPage() {
    const board = taskBoard();
    const detail = selectedTask();
    DOM.contentArea.innerHTML = `${notConnectedMsg()}
      <div class="task-board">
        <div class="task-board-main">
          ${renderTaskProjectTabs()}
          <h1 class="page-title task-board-title">Tasks</h1>
          ${renderTaskFilters()}
          <div class="task-list-card">
            <div class="task-list-header">
              <div class="task-list-heading">
                <h3>Tasks List</h3>
                ${can('task.create') ? `<button class="btn btn-primary btn-sm" id="btnCreateTask" ${state.projects.length ? '' : 'disabled'}>` : `<button class="btn btn-primary btn-sm" hidden>`}
                  <span class="material-icons-outlined" style="font-size:18px">add</span> Create Task
                </button>
              </div>
              <div class="task-list-toggles">
                <label><input type="checkbox" id="taskMoveChecked" ${board.moveCheckedToBottom ? 'checked' : ''}> Move Checked to Bottom</label>
                <label><input type="checkbox" id="taskShowArchived" ${board.showArchived ? 'checked' : ''}> Show Archived</label>
              </div>
            </div>
            <div class="task-list-hint">Click a task to view details</div>
            ${renderTaskTable()}
          </div>
        </div>
        ${detail ? `<aside class="task-detail-panel" id="taskDetailPanel">${renderTaskDetail(detail)}</aside>` : ''}
      </div>`;
  }

  function renderTaskProjectTabs() {
    const board = taskBoard();
    const tabs = board.openProjectIds.filter(id => state.projects.some(p => p.id === id));
    return `<div class="task-project-tabs">
      <button class="task-tab ${board.activeProjectId ? '' : 'active'}" data-task-project="">All Projects</button>
      ${tabs.map(id => `<button class="task-tab ${board.activeProjectId === id ? 'active' : ''}" data-task-project="${esc(id)}">
        ${esc(projectName(id))}<span class="task-tab-close material-icons-outlined" data-close-task-project="${esc(id)}">close</span>
      </button>`).join('')}
      <select class="form-input task-tab-add" id="taskAddProjectTab">
        <option value="">+ Open project…</option>
        ${state.projects.filter(p => !tabs.includes(p.id)).map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}
      </select>
    </div>`;
  }

  function renderTaskFilters() {
    const board = taskBoard();
    const f = board.filters;
    const trades = state.trades.map(t => t.name);
    return `<div class="filters-bar">
      <div class="filters-row">
        <div class="filter-group grow">
          <div class="filter-label">Task Name</div>
          <input class="filter-input" id="taskFilterName" value="${esc(f.name)}" placeholder="Search by task name...">
        </div>
        <div class="filter-group">
          <div class="filter-label">Trade</div>
          <select class="filter-input" id="taskFilterTrade">
            <option value="">Any</option>
            ${trades.map(name => `<option value="${esc(name)}" ${f.trade === name ? 'selected' : ''}>${esc(name)}</option>`).join('')}
          </select>
        </div>
        <button class="btn btn-secondary" id="btnClearTaskFilters">Clear Filters</button>
        <button class="btn btn-ghost" id="btnMoreTaskFilters">
          <span class="material-icons-outlined" style="font-size:18px">${board.showMoreFilters ? 'expand_less' : 'expand_more'}</span> More filters
        </button>
      </div>
      ${board.showMoreFilters ? `<div class="filters-row">
        <div class="filter-group">
          <div class="filter-label">Status</div>
          <select class="filter-input" id="taskFilterStatus">
            <option value="">Any</option>
            ${TASK_STATUSES.map(s => `<option value="${s}" ${f.status === s ? 'selected' : ''}>${s}</option>`).join('')}
          </select>
        </div>
        <div class="filter-group">
          <div class="filter-label">Priority</div>
          <select class="filter-input" id="taskFilterPriority">
            <option value="">Any</option>
            ${TASK_PRIORITIES.map(s => `<option value="${s}" ${f.priority === s ? 'selected' : ''}>${s}</option>`).join('')}
          </select>
        </div>
        <div class="filter-group grow">
          <div class="filter-label">Assignee</div>
          <select class="filter-input" id="taskFilterAssignee">
            <option value="">Any</option>
            ${state.users.map(u => `<option value="${esc(u.name)}" ${f.assignee === u.name ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}
          </select>
        </div>
      </div>` : ''}
      <div class="filters-row filters-summary"><span>Total: ${taskBoard().tasks.length}</span></div>
    </div>`;
  }

  /** Ordered rows: roots first, each followed by its expanded descendants. */
  function taskRows() {
    const board = taskBoard();
    const byParent = new Map();
    const ids = new Set(board.tasks.map(t => t.id));
    board.tasks.forEach(task => {
      // A task whose parent is filtered out is shown at the root, so it can
      // never become invisible.
      const key = task.parent_id && ids.has(task.parent_id) ? task.parent_id : null;
      if (!byParent.has(key)) byParent.set(key, []);
      byParent.get(key).push(task);
    });

    const sortTasks = list => {
      const copy = [...list];
      if (board.moveCheckedToBottom) {
        copy.sort((a, b) => (a.status === 'Completed' ? 1 : 0) - (b.status === 'Completed' ? 1 : 0));
      }
      return copy;
    };

    const rows = [];
    const walk = (parentId, depth) => {
      sortTasks(byParent.get(parentId) || []).forEach(task => {
        const children = byParent.get(task.id) || [];
        rows.push({ task, depth, hasChildren: children.length > 0 });
        if (children.length && board.expanded[task.id]) walk(task.id, depth + 1);
      });
    };
    walk(null, 0);
    return rows;
  }

  function taskStatusClass(status) {
    return { 'Completed': 'chip-done', 'Blocked': 'chip-blocked', 'In Progress': 'chip-progress' }[status] || 'chip-open';
  }

  function renderTaskTable() {
    const board = taskBoard();
    if (board.loading) return `<div class="empty-msg">Loading tasks…</div>`;
    if (!state.projects.length) {
      return `<div class="empty-msg">No projects yet. Create a project first, then add tasks to it.</div>`;
    }
    const rows = taskRows();
    if (!rows.length) {
      return `<div class="empty-msg">No tasks match. Click <b>Create Task</b> to add one.</div>`;
    }
    return `<div class="data-table-container"><table class="data-table task-table">
      <thead><tr><th class="task-col-expand"></th><th class="task-col-type">Type</th><th>Task</th>${board.activeProjectId ? '' : '<th>Project</th>'}<th class="task-col-status">Status</th></tr></thead>
      <tbody>
        ${rows.map(({ task, depth, hasChildren }) => `
          <tr class="task-row-item ${board.selectedId === task.id ? 'selected' : ''} ${task.archived ? 'archived' : ''}" data-task-id="${esc(task.id)}" data-task-project="${esc(task.project_id)}">
            <td class="task-col-expand">${hasChildren
              ? `<button class="task-expand" data-toggle-task="${esc(task.id)}" aria-label="Toggle subtasks"><span class="material-icons-outlined">${board.expanded[task.id] ? 'expand_more' : 'chevron_right'}</span></button>`
              : ''}</td>
            <td class="task-col-type"><span class="task-type-badge material-icons-outlined" title="${esc(task.task_type || 'Task')}">assignment</span></td>
            <td>
              <div class="task-cell" style="padding-left:${depth * 20}px">
                <span class="task-status-icon ${task.status === 'Completed' ? 'task-done' : ''}"><span class="material-icons-outlined">${task.status === 'Completed' ? 'check_circle' : 'radio_button_unchecked'}</span></span>
                <div>
                  <div class="task-name">${esc(task.name)}</div>
                  <div class="task-chips">
                    ${task.trade ? `<span class="task-chip">${esc(task.trade)}</span>` : ''}
                    ${task.delegation ? `<span class="task-chip">${esc(task.delegation)}</span>` : ''}
                    ${task.priority && task.priority !== 'Normal' ? `<span class="task-chip chip-priority">${esc(task.priority)}</span>` : ''}
                    ${task.archived ? '<span class="task-chip chip-archived">Archived</span>' : ''}
                  </div>
                </div>
              </div>
            </td>
            ${board.activeProjectId ? '' : `<td class="task-col-project">${esc(projectName(task.project_id))}</td>`}
            <td class="task-col-status"><span class="task-status-chip ${taskStatusClass(task.status)}">${esc(task.status)}</span></td>
          </tr>`).join('')}
      </tbody>
    </table></div>`;
  }

  function taskOptionList(values, selected) {
    return values.map(v => `<option value="${esc(v)}" ${v === selected ? 'selected' : ''}>${esc(v)}</option>`).join('');
  }

  /** Options for the parent selector: same project, excluding self and descendants. */
  function parentTaskOptions(task) {
    const board = taskBoard();
    const siblings = board.tasks.filter(t => t.project_id === task.project_id);
    const banned = new Set([task.id]);
    let changed = true;
    while (changed) {
      changed = false;
      siblings.forEach(t => {
        if (!banned.has(t.id) && t.parent_id && banned.has(t.parent_id)) { banned.add(t.id); changed = true; }
      });
    }
    const options = siblings.filter(t => !banned.has(t.id));
    return `<option value="">None (root under project)</option>${options.map(t =>
      `<option value="${esc(t.id)}" ${t.id === task.parent_id ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}`;
  }

  function renderTaskDetail(task) {
    const members = state.users.map(u => u.name).filter(Boolean);
    const workers = state.teamMembers.map(m => m.name).filter(Boolean);
    const trades = state.trades.map(t => t.name);
    const types = state.taskTypes.map(t => t.name);
    return `
      <div class="task-detail-header">
        <div>
          <h2>${esc(task.name)}</h2>
          <div class="task-detail-sub">Task${task.archived ? ' · Archived' : ''}</div>
        </div>
        <button class="btn-icon-only" id="btnCloseTaskDetail" aria-label="Close details"><span class="material-icons-outlined">close</span></button>
      </div>
      <div class="task-detail-actions">
        <button class="btn btn-secondary btn-sm" id="btnTaskMarkDone">${task.status === 'Completed' ? 'Reopen' : 'Mark Done'}</button>
        <button class="btn btn-danger btn-sm" id="btnTaskArchive">${task.archived ? 'Restore' : 'Archive'}</button>
        <button class="btn btn-primary btn-sm" id="btnTaskSave">Save</button>
      </div>
      <div class="task-detail-body">
        <div class="form-grid-2">
          <div class="form-group"><label class="form-label">Title</label><input class="form-input" id="tdName" value="${esc(task.name)}"></div>
          <div class="form-group"><label class="form-label">Project</label><select class="form-input" id="tdProject" disabled><option>${esc(projectName(task.project_id))}</option></select></div>
          <div class="form-group"><label class="form-label">Task type</label><select class="form-input" id="tdType"><option value="">Task (workspace default)</option>${taskOptionList(types, task.task_type)}</select></div>
          <div class="form-group"><label class="form-label">Parent task</label><select class="form-input" id="tdParent">${parentTaskOptions(task)}</select></div>
          <div class="form-group"><label class="form-label">Trade</label><select class="form-input" id="tdTrade"><option value="">None</option>${taskOptionList(trades, task.trade)}</select></div>
          <div class="form-group"><label class="form-label">Assignee</label><select class="form-input" id="tdAssignee"><option value="">Select assignee</option>${taskOptionList(members, task.assignee)}</select></div>
          <div class="form-group"><label class="form-label">On Site Field Worker</label><select class="form-input" id="tdWorker"><option value="">Select on site field worker</option>${taskOptionList(workers, task.field_worker)}</select></div>
          <div class="form-group"><label class="form-label">Start Time</label><input type="datetime-local" class="form-input" id="tdStart" value="${esc(task.start_time || '')}"></div>
          <div class="form-group"><label class="form-label">End Time</label><input type="datetime-local" class="form-input" id="tdEnd" value="${esc(task.end_time || '')}"></div>
          <div class="form-group"><label class="form-label">Priority</label><select class="form-input" id="tdPriority">${taskOptionList(TASK_PRIORITIES, task.priority || 'Normal')}</select></div>
          <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="tdStatus">${taskOptionList(TASK_STATUSES, task.status)}</select></div>
          <div class="form-group"><label class="form-label">Delegation</label><input class="form-input" id="tdDelegation" value="${esc(task.delegation || '')}" placeholder="None"></div>
        </div>
        <div class="form-group"><label class="form-label">Description</label><textarea class="form-input" id="tdDescription" rows="4">${esc(task.description || '')}</textarea></div>
        <div class="task-detail-meta">
          ${task.created_at ? `<span>Created ${new Date(task.created_at).toLocaleString()}</span>` : ''}
          ${task.updated_at ? `<span>Updated ${new Date(task.updated_at).toLocaleString()}</span>` : ''}
        </div>
        <div class="task-detail-danger">
          <button class="btn btn-ghost btn-sm" id="btnTaskDelete"><span class="material-icons-outlined" style="font-size:18px">delete</span> Delete task</button>
        </div>
      </div>`;
  }

  // ── Create ────────────────────────────────────────────────────────────────

  function openCreateTaskModal(presetProjectId) {
    const board = taskBoard();
    const projectId = presetProjectId || board.activeProjectId || state.projects[0]?.id || '';
    if (!projectId) { showToast('Create a project before adding tasks.', 'warning'); return; }
    const siblings = board.tasks.filter(t => t.project_id === projectId);
    DOM.crudModalTitle.textContent = 'Create Task';
    DOM.crudModalBody.innerHTML = `
      <div class="form-grid-2">
        <div class="form-group"><label class="form-label required-label">Title</label><input class="form-input" id="ctName" placeholder="Task title"></div>
        <div class="form-group"><label class="form-label">Project</label><select class="form-input" id="ctProject">${state.projects.map(p => `<option value="${esc(p.id)}" ${p.id === projectId ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>
        <div class="form-group"><label class="form-label">Task type</label><select class="form-input" id="ctType"><option value="">Task (workspace default)</option>${taskOptionList(state.taskTypes.map(t => t.name), '')}</select></div>
        <div class="form-group"><label class="form-label">Parent task</label><select class="form-input" id="ctParent"><option value="">None (root under project)</option>${siblings.map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')}</select></div>
        <div class="form-group"><label class="form-label">Trade</label><select class="form-input" id="ctTrade"><option value="">None</option>${taskOptionList(state.trades.map(t => t.name), '')}</select></div>
        <div class="form-group"><label class="form-label">Assignee</label><select class="form-input" id="ctAssignee"><option value="">Select assignee</option>${taskOptionList(state.users.map(u => u.name).filter(Boolean), '')}</select></div>
        <div class="form-group"><label class="form-label">On Site Field Worker</label><select class="form-input" id="ctWorker"><option value="">Select on site field worker</option>${taskOptionList(state.teamMembers.map(m => m.name).filter(Boolean), '')}</select></div>
        <div class="form-group"><label class="form-label">Start Time</label><input type="datetime-local" class="form-input" id="ctStart"></div>
        <div class="form-group"><label class="form-label">End Time</label><input type="datetime-local" class="form-input" id="ctEnd"></div>
        <div class="form-group"><label class="form-label">Priority</label><select class="form-input" id="ctPriority">${taskOptionList(TASK_PRIORITIES, 'Normal')}</select></div>
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="ctStatus">${taskOptionList(TASK_STATUSES, 'Open')}</select></div>
        <div class="form-group"><label class="form-label">Delegation</label><input class="form-input" id="ctDelegation" placeholder="None"></div>
      </div>
      <div class="form-group"><label class="form-label">Description</label><textarea class="form-input" id="ctDescription" rows="3"></textarea></div>`;
    DOM.btnSaveCrud.dataset.crudAction = 'create-task';
    DOM.btnSaveCrud.dataset.crudId = projectId;
    DOM.crudModal.classList.add('open');

    // Re-scoping the project changes which tasks can be a parent.
    const projectSelect = $('#ctProject');
    if (projectSelect) projectSelect.addEventListener('change', () => {
      const chosen = projectSelect.value;
      const options = board.tasks.filter(t => t.project_id === chosen);
      $('#ctParent').innerHTML = `<option value="">None (root under project)</option>${options.map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')}`;
      DOM.btnSaveCrud.dataset.crudId = chosen;
    });
  }

  function readCreateTaskForm() {
    return {
      name: $('#ctName')?.value.trim() || '',
      task_type: $('#ctType')?.value || '',
      parent_id: $('#ctParent')?.value || null,
      trade: $('#ctTrade')?.value || '',
      assignee: $('#ctAssignee')?.value || '',
      field_worker: $('#ctWorker')?.value || '',
      start_time: $('#ctStart')?.value || '',
      end_time: $('#ctEnd')?.value || '',
      priority: $('#ctPriority')?.value || 'Normal',
      status: $('#ctStatus')?.value || 'Open',
      delegation: $('#ctDelegation')?.value.trim() || '',
      description: $('#ctDescription')?.value.trim() || ''
    };
  }

  async function submitCreateTask(projectId) {
    const body = readCreateTaskForm();
    if (!body.name) { showToast('Task title is required', 'warning'); return; }
    try {
      const res = await apiReq(`/api/projects/${projectId}/tasks`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      const task = await res.json();
      const board = taskBoard();
      if (!board.openProjectIds.includes(projectId)) board.openProjectIds.push(projectId);
      board.selectedId = task.id;
      if (task.parent_id) board.expanded[task.parent_id] = true;
      closeCrudModal();
      await fetchBoardTasks();
      renderPage();
      showToast('Task created', 'success');
    } catch (error) { showToast(error.message, 'error'); }
  }

  // ── Edit ──────────────────────────────────────────────────────────────────

  function readTaskDetailForm() {
    return {
      name: $('#tdName')?.value.trim() || '',
      task_type: $('#tdType')?.value || '',
      parent_id: $('#tdParent')?.value || null,
      trade: $('#tdTrade')?.value || '',
      assignee: $('#tdAssignee')?.value || '',
      field_worker: $('#tdWorker')?.value || '',
      start_time: $('#tdStart')?.value || '',
      end_time: $('#tdEnd')?.value || '',
      priority: $('#tdPriority')?.value || 'Normal',
      status: $('#tdStatus')?.value || 'Open',
      delegation: $('#tdDelegation')?.value.trim() || '',
      description: $('#tdDescription')?.value.trim() || ''
    };
  }

  async function saveTaskChanges(changes) {
    const task = selectedTask();
    if (!task) return;
    const body = changes || readTaskDetailForm();
    if ('name' in body && !body.name) { showToast('Task title is required', 'warning'); return; }
    try {
      await apiReq(`/api/projects/${task.project_id}/tasks/${task.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      await fetchBoardTasks();
      renderPage();
      showToast('Task saved', 'success');
    } catch (error) { showToast(error.message, 'error'); }
  }

  async function deleteSelectedTask() {
    const task = selectedTask();
    if (!task) return;
    if (!confirm(`Delete “${task.name}”? Any subtasks move up to its parent.`)) return;
    try {
      await apiReq(`/api/projects/${task.project_id}/tasks/${task.id}`, { method: 'DELETE' });
      taskBoard().selectedId = null;
      await fetchBoardTasks();
      renderPage();
      showToast('Task deleted', 'info');
    } catch (error) { showToast(error.message, 'error'); }
  }

  /** Open the Tasks page focused on one task, from anywhere in the app. */
  async function openTaskInBoard(projectId, taskId) {
    const board = taskBoard();
    board.activeProjectId = projectId;
    if (projectId && !board.openProjectIds.includes(projectId)) board.openProjectIds.push(projectId);
    board.selectedId = taskId || null;
    navigateTo('tasks');
    await fetchBoardTasks();
    renderPage();
  }

  // ── Events ────────────────────────────────────────────────────────────────

  function bindTasksPageEvents() {
    const board = taskBoard();

    $$('[data-task-project]').forEach(tab => {
      if (tab.tagName !== 'BUTTON') return;
      tab.addEventListener('click', async event => {
        if (event.target.closest('[data-close-task-project]')) return;
        board.activeProjectId = tab.dataset.taskProject;
        board.selectedId = null;
        await fetchBoardTasks();
        renderPage();
      });
    });
    $$('[data-close-task-project]').forEach(close => close.addEventListener('click', async event => {
      event.stopPropagation();
      const id = close.dataset.closeTaskProject;
      board.openProjectIds = board.openProjectIds.filter(x => x !== id);
      if (board.activeProjectId === id) { board.activeProjectId = ''; board.selectedId = null; }
      await fetchBoardTasks();
      renderPage();
    }));
    const addTab = $('#taskAddProjectTab');
    if (addTab) addTab.addEventListener('change', async () => {
      const id = addTab.value;
      if (!id) return;
      if (!board.openProjectIds.includes(id)) board.openProjectIds.push(id);
      board.activeProjectId = id;
      board.selectedId = null;
      await fetchBoardTasks();
      renderPage();
    });

    // Filters
    const nameFilter = $('#taskFilterName');
    if (nameFilter) {
      let timer = null;
      nameFilter.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          board.filters.name = nameFilter.value.trim();
          await fetchBoardTasks();
          renderPage();
          const restored = $('#taskFilterName');
          if (restored) { restored.focus(); restored.setSelectionRange(restored.value.length, restored.value.length); }
        }, 400);
      });
    }
    [['taskFilterTrade', 'trade'], ['taskFilterStatus', 'status'],
     ['taskFilterPriority', 'priority'], ['taskFilterAssignee', 'assignee']].forEach(([id, key]) => {
      const el = $(`#${id}`);
      if (el) el.addEventListener('change', async () => {
        board.filters[key] = el.value;
        await fetchBoardTasks();
        renderPage();
      });
    });
    const clearFilters = $('#btnClearTaskFilters');
    if (clearFilters) clearFilters.addEventListener('click', async () => {
      board.filters = emptyTaskFilters();
      await fetchBoardTasks();
      renderPage();
    });
    const moreFilters = $('#btnMoreTaskFilters');
    if (moreFilters) moreFilters.addEventListener('click', () => {
      board.showMoreFilters = !board.showMoreFilters;
      renderPage();
    });
    const showArchived = $('#taskShowArchived');
    if (showArchived) showArchived.addEventListener('change', async () => {
      board.showArchived = showArchived.checked;
      await fetchBoardTasks();
      renderPage();
    });
    const moveChecked = $('#taskMoveChecked');
    if (moveChecked) moveChecked.addEventListener('change', () => {
      board.moveCheckedToBottom = moveChecked.checked;
      renderPage();
    });

    // List
    const create = $('#btnCreateTask');
    if (create) create.addEventListener('click', () => openCreateTaskModal());
    $$('[data-toggle-task]').forEach(button => button.addEventListener('click', event => {
      event.stopPropagation();
      const id = button.dataset.toggleTask;
      board.expanded[id] = !board.expanded[id];
      renderPage();
    }));
    $$('.task-row-item').forEach(row => row.addEventListener('click', () => {
      board.selectedId = row.dataset.taskId;
      renderPage();
    }));

    // Detail panel
    const close = $('#btnCloseTaskDetail');
    if (close) close.addEventListener('click', () => { board.selectedId = null; renderPage(); });
    const save = $('#btnTaskSave');
    if (save) save.addEventListener('click', () => saveTaskChanges());
    const markDone = $('#btnTaskMarkDone');
    if (markDone) markDone.addEventListener('click', () => {
      const task = selectedTask();
      if (task) saveTaskChanges({ status: task.status === 'Completed' ? 'Open' : 'Completed' });
    });
    const archive = $('#btnTaskArchive');
    if (archive) archive.addEventListener('click', () => {
      const task = selectedTask();
      if (task) saveTaskChanges({ archived: !task.archived });
    });
    const remove = $('#btnTaskDelete');
    if (remove) remove.addEventListener('click', deleteSelectedTask);
  }

  // Project Details: People, Cost, Timeline, Procurement ---------------------
  //
  // Each tab loads its own slice on demand and re-renders in place, so opening
  // a project stays cheap. Everything is account-scoped by apiReq.

  function projectTab() {
    if (!state.projectTab) {
      state.projectTab = {
        projectId: null, loading: false, error: '',
        people: null, costs: null, timeline: null, procurement: null
      };
    }
    return state.projectTab;
  }

  function resetProjectTabData(projectId) {
    state.projectTab = {
      projectId, loading: false, error: '',
      people: null, costs: null, timeline: null, procurement: null
    };
  }

  const STATS_TAB = 'stats';

  const TAB_ENDPOINTS = {
    people: 'members', cost: 'costs', timeline: 'timeline', procore: 'procurement'
  };
  const TAB_KEYS = { people: 'people', cost: 'costs', timeline: 'timeline', procore: 'procurement' };

  /** Load the data one dashboard tab needs, then repaint just that tab. */
  async function loadProjectTab(tab, projectId, { force = false } = {}) {
    const slice = projectTab();
    if (slice.projectId !== projectId) resetProjectTabData(projectId);
    // Statistics is computed rather than fetched from a tab endpoint, and
    // it carries its own slice so switching tabs does not discard it.
    if (tab === STATS_TAB) { loadProjectStatistics(projectId); return; }
    const key = TAB_KEYS[tab];
    if (!key) return;
    if (!force && projectTab()[key]) return;

    projectTab().loading = true;
    projectTab().error = '';
    paintDashTab(tab);
    try {
      const res = await apiReq(`/api/projects/${projectId}/${TAB_ENDPOINTS[tab]}`);
      projectTab()[key] = await res.json();
    } catch (error) {
      projectTab().error = error.message;
    } finally {
      projectTab().loading = false;
      paintDashTab(tab);
    }
  }

  function paintDashTab(tab) {
    const host = document.getElementById('dashTabContent');
    if (!host) return;
    const project = state.projects.find(p => p.id === state.activeProjectId);
    if (!project) return;
    host.innerHTML = renderDashTab(tab, project);
    bindDashTabEvents(tab, project);
  }

  function renderDashTab(tab, project) {
    const slice = projectTab();
    if (tab === STATS_TAB) return renderStatsTab(project);
    if (slice.loading) return `<div class="empty-msg">Loading…</div>`;
    if (slice.error) {
      return `<div class="connection-banner warning"><span class="material-icons-outlined">warning</span>
        <span>${esc(slice.error)}</span>
        <button class="btn btn-secondary btn-sm" data-dash-retry="${tab}">Retry</button></div>`;
    }
    if (tab === 'people') return renderPeopleTab(project);
    if (tab === 'cost') return renderCostTab(project);
    if (tab === 'timeline') return renderTimelineTab(project);
    if (tab === 'procore') return renderProcurementTab(project);
    if (tab === STATS_TAB) return renderStatsTab(project);
    return '';
  }

  /** The symbols for the currency codes a project may be priced in. */
  const CURRENCY_SYMBOLS = {
    USD: '$', GBP: '£', EUR: '€', JPY: '¥', INR: '₹', ZAR: 'R',
    BDT: '৳', PKR: 'Rs ', LKR: 'Rs ', NPR: 'Rs ',
    CAD: 'CA$', AUD: 'A$', NZD: 'NZ$', AED: 'AED ', SAR: 'SAR ', SGD: 'S$'
  };

  /** The currency of the project on screen.
   *
   * A project carries its own currency, so a sterling job must not be
   * reported in dollars. Away from a project there is nothing to read it
   * from, and the account default stands.
   */
  function activeCurrency() {
    const open = (state.projects || []).find(p => p.id === state.activeProjectId);
    const code = String((open && open.currency) || '').toUpperCase();
    return CURRENCY_SYMBOLS[code] ? code : 'USD';
  }

  function currencyMark() { return CURRENCY_SYMBOLS[activeCurrency()] || '$'; }

  /** Currencies counted in lakh and crore rather than thousands and millions.
   *
   * ৳6,00,00,000 groups in twos after the first thousand and is spoken as
   * “6 crore”, so both the separators and the abbreviation differ from the
   * western scale — not a formatting preference, a different counting system.
   */
  const LAKH_CRORE = new Set(['BDT', 'INR', 'PKR', 'LKR', 'NPR']);

  /** Group digits South Asian style: 6,00,00,000 rather than 600,000,000. */
  function groupSouthAsian(value) {
    const digits = String(Math.round(Math.abs(value)));
    if (digits.length <= 3) return digits;
    let head = digits.slice(0, -3);
    const parts = [digits.slice(-3)];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) parts.unshift(head);
    return parts.join(',');
  }

  function money(value) {
    const amount = Number(value || 0);
    const code = activeCurrency();
    if (LAKH_CRORE.has(code)) {
      return `${amount < 0 ? '-' : ''}${CURRENCY_SYMBOLS[code]}${groupSouthAsian(amount)}`;
    }
    return amount.toLocaleString(undefined,
      { style: 'currency', currency: code, maximumFractionDigits: 2 });
  }

  // ── People ────────────────────────────────────────────────────────────────

  function renderPeopleTab(project) {
    const data = projectTab().people;
    if (!data) return `<div class="empty-msg">Loading people…</div>`;
    const rows = data.members.map(m => `<tr>
      <td><div class="people-cell"><span class="user-avatar-badge">${esc((m.name || m.email || '?').slice(0, 2))}</span>
        <div><div class="people-name">${esc(m.name || '—')}</div><div class="people-email">${esc(m.email)}</div></div></div></td>
      <td>${m.role ? `<span class="badge ${roleBadgeClass(m.role)}">${esc(m.role)}</span>` : '—'}</td>
      <td>${esc(m.department || '—')}</td>
      <td>${m.added_at ? new Date(m.added_at).toLocaleDateString() : '—'}</td>
      <td><div class="table-actions"><button class="btn-table-action" data-remove-member="${esc(m.user_id)}" title="Remove from project"><span class="material-icons-outlined">person_remove</span></button></div></td>
    </tr>`).join('');

    return `<div class="overview-section">
      <div class="tasks-section-header">
        <div><h3 class="section-sub-title">Project People</h3>
          <div class="form-hint">${data.total} assigned · ${data.available.length} more available in this account</div></div>
        <div class="tasks-section-actions">
          ${can('project.people.manage') ? `<button class="btn btn-primary btn-sm" id="btnAddProjectMembers" ${data.available.length ? '' : 'disabled'}>` : `<button class="btn btn-primary btn-sm" hidden>`}
            <span class="material-icons-outlined" style="font-size:18px">person_add</span> Add People</button>
          <button class="btn btn-ghost btn-sm" data-dash-refresh="people" title="Refresh"><span class="material-icons-outlined">refresh</span></button>
        </div>
      </div>
      ${data.members.length ? `<div class="data-table-container"><table class="data-table">
        <thead><tr><th>Person</th><th>Role</th><th>Department</th><th>Added</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>`
      : `<div class="empty-msg">No one is assigned to this project yet. Click <b>Add People</b> to assign account members.</div>`}
      ${data.available.length ? '' : '<div class="form-hint" style="margin-top:10px">Everyone active in this account is already on this project. Add more people under <b>Company Settings → User</b>.</div>'}
    </div>`;
  }

  function openAddMembersModal(project) {
    const data = projectTab().people;
    if (!data || !data.available.length) return;
    DOM.crudModalTitle.textContent = 'Add People to Project';
    DOM.crudModalBody.innerHTML = `
      <div class="form-hint" style="margin-bottom:10px">Choose account members to assign to <b>${esc(project.name)}</b>.</div>
      <div class="member-picker">${data.available.map(u => `
        <label class="member-option">
          <input type="checkbox" class="member-check" value="${esc(u.user_id)}">
          <span class="user-avatar-badge">${esc((u.name || u.email || '?').slice(0, 2))}</span>
          <span><span class="people-name">${esc(u.name || u.email)}</span><span class="people-email">${esc(u.email)}${u.role ? ' · ' + esc(u.role) : ''}</span></span>
        </label>`).join('')}</div>
      <div class="form-group" style="margin-top:14px">
        <label class="form-label">Role on this project (optional)</label>
        <input class="form-input" id="memberProjectRole" placeholder="e.g. Site Supervisor">
      </div>`;
    DOM.btnSaveCrud.dataset.crudAction = 'add-project-members';
    DOM.btnSaveCrud.dataset.crudId = project.id;
    DOM.crudModal.classList.add('open');
  }

  async function submitAddMembers(projectId) {
    const ids = [...document.querySelectorAll('.member-check:checked')].map(c => c.value);
    if (!ids.length) { showToast('Select at least one person', 'warning'); return; }
    try {
      await apiReq(`/api/projects/${projectId}/members`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_ids: ids, project_role: $('#memberProjectRole')?.value.trim() || '' })
      });
      closeCrudModal();
      await loadProjectTab('people', projectId, { force: true });
      showToast(`Added ${ids.length} person${ids.length === 1 ? '' : 's'} to the project`, 'success');
    } catch (error) { showToast(error.message, 'error'); }
  }

  // ── Cost ──────────────────────────────────────────────────────────────────

  function renderCostTab(project) {
    const data = projectTab().costs;
    if (!data) return `<div class="empty-msg">Loading costs…</div>`;
    const taskRows = data.tasks.filter(t => !t.archived);
    // The server decides; these only choose what to draw. A member who forges
    // the request still gets 403.
    const canEditBaseline = !!data.can_edit_baseline;
    const canEditProject = !!data.can_edit_additional;
    const editableTasks = new Set(data.editable_task_costs || []);
    const managerOnly = '<div class="form-hint">Only a Project Manager can change these figures.</div>';
    return `<div class="overview-section">
      <div class="cost-summary">
        ${[['Baseline', data.baseline_cost], ['Additional', data.additional_total],
           ['Task costs', data.tasks_total], ['Total', data.total]].map(([label, value], index) => `
          <div class="cost-card ${index === 3 ? 'cost-card-total' : ''}">
            <div class="cost-card-label">${label}</div>
            <div class="cost-card-value">${money(value)}</div>
          </div>`).join('')}
      </div>
      <div class="form-hint cost-formula">Total = Baseline + Additional project costs + Sum of task costs</div>

      <div class="tasks-section-header">
        <h3 class="section-sub-title">Baseline cost</h3>
      </div>
      ${canEditBaseline ? `<div class="cost-baseline-row">
        <input type="number" min="0" step="0.01" class="form-input" id="baselineCostInput" value="${Number(data.baseline_cost || 0)}">
        <button class="btn btn-primary btn-sm" id="btnSaveBaseline">Save baseline</button>
      </div>` : `<div class="cost-baseline-row"><strong class="cost-readonly">${money(data.baseline_cost)}</strong></div>${managerOnly}`}

      <div class="tasks-section-header">
        <div><h3 class="section-sub-title">Additional project costs</h3>
          <div class="form-hint">Costs that do not belong to a single task.</div></div>
        <div class="tasks-section-actions">
          <span class="total-count">${money(data.additional_total)}</span>
          ${canEditProject ? '<button class="btn btn-primary btn-sm" id="btnAddProjectCost"><span class="material-icons-outlined" style="font-size:18px">add</span> Add Cost</button>' : ''}
        </div>
      </div>
      ${data.additional_costs.length ? `<div class="data-table-container"><table class="data-table">
        <thead><tr><th>Name</th><th>Details</th><th class="cost-col">Amount</th>${canEditProject ? '<th></th>' : ''}</tr></thead>
        <tbody>${data.additional_costs.map(c => `<tr>
          <td><strong>${esc(c.name)}</strong></td>
          <td>${esc(c.details || '—')}</td>
          <td class="cost-col">${money(c.amount)}</td>
          ${canEditProject ? `<td><div class="table-actions">
            <button class="btn-table-action" data-edit-cost="${esc(c.id)}" title="Edit"><span class="material-icons-outlined">edit</span></button>
            <button class="btn-table-action" data-delete-cost="${esc(c.id)}" title="Delete"><span class="material-icons-outlined">delete</span></button>
          </div></td>` : ''}</tr>`).join('')}</tbody></table></div>`
      : `<div class="empty-msg">No additional costs yet. Click <b>Add Cost</b> for anything not tied to a task.</div>`}

      <div class="tasks-section-header">
        <div><h3 class="section-sub-title">Task costs</h3>
          <div class="form-hint">${canEditProject
            ? 'Set on each task; edits here update the project total immediately.'
            : 'You can set the cost of the tasks assigned to you. A Project Manager maintains the rest.'}</div></div>
        <div class="tasks-section-actions"><span class="total-count">${money(data.tasks_total)}</span></div>
      </div>
      ${taskRows.length ? `<div class="data-table-container"><table class="data-table">
        <thead><tr><th>Task</th><th>Trade</th><th>Status</th><th class="cost-col">Cost</th><th></th></tr></thead>
        <tbody>${taskRows.map(t => `<tr>
          <td><strong>${esc(t.name)}</strong></td>
          <td>${esc(t.trade || '—')}</td>
          <td><span class="task-status-chip ${taskStatusClass(t.status)}">${esc(t.status)}</span></td>
          ${editableTasks.has(t.id) ? `
          <td class="cost-col"><input type="number" min="0" step="0.01" class="form-input cost-inline" data-task-cost="${esc(t.id)}" value="${Number(t.cost || 0)}"></td>
          <td><div class="table-actions"><button class="btn-table-action" data-save-task-cost="${esc(t.id)}" title="Save cost"><span class="material-icons-outlined">check</span></button></div></td>`
          : `<td class="cost-col">${money(t.cost || 0)}</td><td></td>`}
        </tr>`).join('')}</tbody></table></div>`
      : `<div class="empty-msg">This project has no tasks yet. Add tasks to track their costs here.</div>`}

      <div class="cost-total-bar"><span>Project total</span><strong>${money(data.total)}</strong></div>
    </div>`;
  }

  function openCostModal(project, cost) {
    DOM.crudModalTitle.textContent = cost ? 'Edit Cost' : 'Add Project Cost';
    DOM.crudModalBody.innerHTML = `
      <div class="form-group"><label class="form-label required-label">Name</label>
        <input class="form-input" id="costName" value="${esc(cost?.name || '')}" placeholder="e.g. Site insurance"></div>
      <div class="form-group"><label class="form-label">Details</label>
        <textarea class="form-input" id="costDetails" rows="3" placeholder="What is this cost for?">${esc(cost?.details || '')}</textarea></div>
      <div class="form-group"><label class="form-label required-label">Amount</label>
        <input type="number" min="0" step="0.01" class="form-input" id="costAmount" value="${Number(cost?.amount || 0)}"></div>`;
    DOM.btnSaveCrud.dataset.crudAction = cost ? 'update-project-cost' : 'add-project-cost';
    DOM.btnSaveCrud.dataset.crudId = project.id;
    DOM.btnSaveCrud.dataset.crudExtra = cost?.id || '';
    DOM.crudModal.classList.add('open');
  }

  async function submitProjectCost(projectId, costId) {
    const name = $('#costName')?.value.trim();
    if (!name) { showToast('Cost name is required', 'warning'); return; }
    const amount = Number($('#costAmount')?.value || 0);
    if (!Number.isFinite(amount) || amount < 0) { showToast('Amount must be zero or more', 'warning'); return; }
    const body = { name, details: $('#costDetails')?.value.trim() || '', amount };
    try {
      await apiReq(`/api/projects/${projectId}/costs${costId ? '/' + costId : ''}`, {
        method: costId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      closeCrudModal();
      await loadProjectTab('cost', projectId, { force: true });
      showToast(costId ? 'Cost updated' : 'Cost added', 'success');
    } catch (error) { showToast(error.message, 'error'); }
  }

  // ── Timeline ──────────────────────────────────────────────────────────────

  function renderTimelineTab(project) {
    const data = projectTab().timeline;
    if (!data) return `<div class="empty-msg">Loading timeline…</div>`;
    const { window: win } = data;
    if (!win.start || !win.end) {
      return `<div class="overview-section">
        <div class="tasks-section-header"><h3 class="section-sub-title">Timeline</h3>
          <div class="tasks-section-actions"><button class="btn btn-ghost btn-sm" data-dash-refresh="timeline"><span class="material-icons-outlined">refresh</span></button></div></div>
        <div class="empty-msg">Set a start and end date on the project, or dates on its tasks, to draw the timeline.</div>
      </div>`;
    }

    const startMs = new Date(win.start).getTime();
    const endMs = new Date(win.end).getTime();
    const span = Math.max(endMs - startMs, 86400000);
    const pct = value => ((new Date(value).getTime() - startMs) / span) * 100;
    const bar = (from, to) => {
      const left = Math.max(0, Math.min(100, pct(from)));
      const right = Math.max(0, Math.min(100, pct(to)));
      // A single-day item still needs a visible sliver.
      return { left, width: Math.max(1.5, right - left) };
    };

    const months = [];
    const cursor = new Date(startMs);
    cursor.setDate(1);
    while (cursor.getTime() <= endMs) {
      months.push({ label: cursor.toLocaleDateString([], { month: 'short', year: '2-digit' }), at: pct(cursor.toISOString().slice(0, 10)) });
      cursor.setMonth(cursor.getMonth() + 1);
    }

    const projectBar = data.project.start && data.project.end ? bar(data.project.start, data.project.end) : null;
    const scheduled = data.tasks.filter(t => t.scheduled);
    const unscheduled = data.tasks.filter(t => !t.scheduled);

    return `<div class="overview-section">
      <div class="tasks-section-header">
        <div><h3 class="section-sub-title">Timeline</h3>
          <div class="form-hint">${new Date(win.start).toLocaleDateString()} → ${new Date(win.end).toLocaleDateString()} · ${data.scheduled_count} scheduled task${data.scheduled_count === 1 ? '' : 's'}</div></div>
        <div class="tasks-section-actions"><button class="btn btn-ghost btn-sm" data-dash-refresh="timeline" title="Refresh"><span class="material-icons-outlined">refresh</span></button></div>
      </div>
      <div class="gantt">
        <div class="gantt-axis">${months.map(m => `<span class="gantt-month" style="left:${m.at}%">${esc(m.label)}</span>`).join('')}</div>
        ${projectBar ? `<div class="gantt-row gantt-row-project">
          <div class="gantt-label">${esc(data.project.name)}</div>
          <div class="gantt-track"><div class="gantt-bar gantt-bar-project" style="left:${projectBar.left}%;width:${projectBar.width}%">
            <span>${new Date(data.project.start).toLocaleDateString()} – ${new Date(data.project.end).toLocaleDateString()}</span>
          </div></div></div>` : ''}
        ${scheduled.map(task => {
          const b = bar(task.start || win.start, task.end || task.start || win.start);
          return `<div class="gantt-row">
            <div class="gantt-label" title="${esc(task.name)}">${task.parent_id ? '<span class="gantt-sub">↳</span>' : ''}${esc(task.name)}</div>
            <div class="gantt-track">
              <div class="gantt-bar ${ganttStatusClass(task.status)}" style="left:${b.left}%;width:${b.width}%" title="${esc(task.name)} · ${task.start || '?'} → ${task.end || '?'}"></div>
            </div></div>`;
        }).join('')}
      </div>
      ${unscheduled.length ? `<div class="form-hint" style="margin-top:14px">
        ${unscheduled.length} task${unscheduled.length === 1 ? ' has' : 's have'} no dates and cannot be drawn:
        ${unscheduled.slice(0, 6).map(t => `<b>${esc(t.name)}</b>`).join(', ')}${unscheduled.length > 6 ? '…' : ''}
      </div>` : ''}
      <div class="gantt-legend">
        <span><i class="gantt-swatch gantt-bar-project"></i>Project</span>
        <span><i class="gantt-swatch gantt-open"></i>Open</span>
        <span><i class="gantt-swatch gantt-progress"></i>In Progress</span>
        <span><i class="gantt-swatch gantt-blocked"></i>Blocked</span>
        <span><i class="gantt-swatch gantt-done"></i>Completed</span>
      </div>
    </div>`;
  }

  function ganttStatusClass(status) {
    return { 'Completed': 'gantt-done', 'Blocked': 'gantt-blocked', 'In Progress': 'gantt-progress' }[status] || 'gantt-open';
  }

  // ── Procurement ───────────────────────────────────────────────────────────

  function procurementStatusClass(status) {
    return {
      'Delivered': 'chip-done', 'Ordered': 'chip-progress',
      'Cancelled': 'chip-archived', 'Quoted': 'chip-open'
    }[status] || 'chip-open';
  }

  function renderProcurementTab(project) {
    const data = projectTab().procurement;
    if (!data) return `<div class="empty-msg">Loading procurement…</div>`;
    return `<div class="overview-section">
      <div class="tasks-section-header">
        <div><h3 class="section-sub-title">Procurement</h3>
          <div class="form-hint">Materials and services ordered for this project. Cancelled lines are excluded from committed spend.</div></div>
        <div class="tasks-section-actions">
          <span class="total-count">${data.count} item${data.count === 1 ? '' : 's'} · ${money(data.total)} committed</span>
          <button class="btn btn-primary btn-sm" id="btnAddProcurement"><span class="material-icons-outlined" style="font-size:18px">add</span> Add Item</button>
          <button class="btn btn-ghost btn-sm" data-dash-refresh="procore" title="Refresh"><span class="material-icons-outlined">refresh</span></button>
        </div>
      </div>
      ${data.items.length ? `<div class="data-table-container"><table class="data-table">
        <thead><tr><th>Item</th><th>Supplier</th><th>Qty</th><th class="cost-col">Unit</th><th class="cost-col">Line total</th><th>Needed by</th><th>Status</th><th></th></tr></thead>
        <tbody>${data.items.map(i => `<tr>
          <td><strong>${esc(i.name)}</strong>${i.description ? `<div class="google-snippet">${esc(i.description)}</div>` : ''}</td>
          <td>${esc(i.supplier || '—')}</td>
          <td>${Number(i.quantity)} ${esc(i.unit || '')}</td>
          <td class="cost-col">${money(i.unit_cost)}</td>
          <td class="cost-col"><strong>${money(i.line_total)}</strong></td>
          <td>${i.needed_by ? new Date(i.needed_by).toLocaleDateString() : '—'}</td>
          <td><span class="task-status-chip ${procurementStatusClass(i.status)}">${esc(i.status)}</span></td>
          <td><div class="table-actions">
            <button class="btn-table-action" data-edit-procurement="${esc(i.id)}" title="Edit"><span class="material-icons-outlined">edit</span></button>
            <button class="btn-table-action" data-delete-procurement="${esc(i.id)}" title="Delete"><span class="material-icons-outlined">delete</span></button>
          </div></td></tr>`).join('')}</tbody></table></div>
        <div class="cost-total-bar"><span>Committed spend</span><strong>${money(data.total)}</strong></div>`
      : `<div class="empty-msg">Nothing has been procured for this project yet. Click <b>Add Item</b> to start.</div>`}
    </div>`;
  }

  function openProcurementModal(project, item) {
    const statuses = projectTab().procurement?.statuses || ['Requested', 'Quoted', 'Ordered', 'Delivered', 'Cancelled'];
    DOM.crudModalTitle.textContent = item ? 'Edit Procurement Item' : 'Add Procurement Item';
    DOM.crudModalBody.innerHTML = `
      <div class="form-grid-2">
        <div class="form-group"><label class="form-label required-label">Item</label>
          <input class="form-input" id="procName" value="${esc(item?.name || '')}" placeholder="e.g. Engineered hardwood"></div>
        <div class="form-group"><label class="form-label">Supplier</label>
          <input class="form-input" id="procSupplier" value="${esc(item?.supplier || '')}" placeholder="Vendor name"></div>
        <div class="form-group"><label class="form-label">Trade</label>
          <select class="form-input" id="procTrade"><option value="">None</option>
            ${state.trades.map(t => `<option value="${esc(t.name)}" ${item?.trade === t.name ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></div>
        <div class="form-group"><label class="form-label">Status</label>
          <select class="form-input" id="procStatus">${statuses.map(s => `<option value="${s}" ${item?.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
        <div class="form-group"><label class="form-label">Quantity</label>
          <input type="number" min="0" step="0.01" class="form-input" id="procQty" value="${Number(item?.quantity ?? 1)}"></div>
        <div class="form-group"><label class="form-label">Unit</label>
          <input class="form-input" id="procUnit" value="${esc(item?.unit || 'ea')}" placeholder="ea, m², box"></div>
        <div class="form-group"><label class="form-label">Unit cost</label>
          <input type="number" min="0" step="0.01" class="form-input" id="procUnitCost" value="${Number(item?.unit_cost || 0)}"></div>
        <div class="form-group"><label class="form-label">Needed by</label>
          <input type="date" class="form-input" id="procNeededBy" value="${esc(item?.needed_by || '')}"></div>
      </div>
      <div class="form-group"><label class="form-label">Description</label>
        <textarea class="form-input" id="procDescription" rows="2">${esc(item?.description || '')}</textarea></div>
      <div class="form-group"><label class="form-label">Notes</label>
        <textarea class="form-input" id="procNotes" rows="2">${esc(item?.notes || '')}</textarea></div>`;
    DOM.btnSaveCrud.dataset.crudAction = item ? 'update-procurement' : 'add-procurement';
    DOM.btnSaveCrud.dataset.crudId = project.id;
    DOM.btnSaveCrud.dataset.crudExtra = item?.id || '';
    DOM.crudModal.classList.add('open');
  }

  async function submitProcurement(projectId, itemId) {
    const name = $('#procName')?.value.trim();
    if (!name) { showToast('Item name is required', 'warning'); return; }
    const body = {
      name, supplier: $('#procSupplier')?.value.trim() || '', trade: $('#procTrade')?.value || '',
      status: $('#procStatus')?.value || 'Requested', quantity: Number($('#procQty')?.value || 1),
      unit: $('#procUnit')?.value.trim() || 'ea', unit_cost: Number($('#procUnitCost')?.value || 0),
      needed_by: $('#procNeededBy')?.value || '', description: $('#procDescription')?.value.trim() || '',
      notes: $('#procNotes')?.value.trim() || ''
    };
    try {
      await apiReq(`/api/projects/${projectId}/procurement${itemId ? '/' + itemId : ''}`, {
        method: itemId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      closeCrudModal();
      await loadProjectTab('procore', projectId, { force: true });
      showToast(itemId ? 'Procurement item updated' : 'Procurement item added', 'success');
    } catch (error) { showToast(error.message, 'error'); }
  }

  // ── Tab events ────────────────────────────────────────────────────────────

  function bindDashTabEvents(tab, project) {
    if (tab === STATS_TAB) { bindStatsEvents(project); return; }
    $$('[data-dash-refresh]').forEach(b => b.addEventListener('click', () =>
      loadProjectTab(b.dataset.dashRefresh, project.id, { force: true })));
    $$('[data-dash-retry]').forEach(b => b.addEventListener('click', () =>
      loadProjectTab(b.dataset.dashRetry, project.id, { force: true })));

    if (tab === 'people') {
      const add = $('#btnAddProjectMembers');
      if (add) add.addEventListener('click', () => openAddMembersModal(project));
      $$('[data-remove-member]').forEach(b => b.addEventListener('click', async () => {
        if (!confirm('Remove this person from the project? Their account is not affected.')) return;
        try {
          await apiReq(`/api/projects/${project.id}/members/${b.dataset.removeMember}`, { method: 'DELETE' });
          await loadProjectTab('people', project.id, { force: true });
          showToast('Removed from project', 'info');
        } catch (error) { showToast(error.message, 'error'); }
      }));
    }

    if (tab === 'cost') {
      const saveBaseline = $('#btnSaveBaseline');
      if (saveBaseline) saveBaseline.addEventListener('click', async () => {
        const amount = Number($('#baselineCostInput')?.value || 0);
        if (!Number.isFinite(amount) || amount < 0) { showToast('Baseline must be zero or more', 'warning'); return; }
        try {
          await apiReq(`/api/projects/${project.id}/costs/baseline`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount })
          });
          await loadProjectTab('cost', project.id, { force: true });
          showToast('Baseline cost saved', 'success');
        } catch (error) { showToast(error.message, 'error'); }
      });
      const addCost = $('#btnAddProjectCost');
      if (addCost) addCost.addEventListener('click', () => openCostModal(project, null));
      $$('[data-edit-cost]').forEach(b => b.addEventListener('click', () => {
        const cost = projectTab().costs.additional_costs.find(c => c.id === b.dataset.editCost);
        if (cost) openCostModal(project, cost);
      }));
      $$('[data-delete-cost]').forEach(b => b.addEventListener('click', async () => {
        if (!confirm('Delete this cost?')) return;
        try {
          await apiReq(`/api/projects/${project.id}/costs/${b.dataset.deleteCost}`, { method: 'DELETE' });
          await loadProjectTab('cost', project.id, { force: true });
          showToast('Cost deleted', 'info');
        } catch (error) { showToast(error.message, 'error'); }
      }));
      $$('[data-save-task-cost]').forEach(b => b.addEventListener('click', async () => {
        const taskId = b.dataset.saveTaskCost;
        const input = document.querySelector(`[data-task-cost="${taskId}"]`);
        const cost = Number(input?.value || 0);
        if (!Number.isFinite(cost) || cost < 0) { showToast('Task cost must be zero or more', 'warning'); return; }
        try {
          await apiReq(`/api/projects/${project.id}/tasks/${taskId}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cost })
          });
          // The project total is recomputed server-side from the task costs.
          await loadProjectTab('cost', project.id, { force: true });
          await fetchProjectTasks(project.id);
          showToast('Task cost saved; project total updated', 'success');
        } catch (error) { showToast(error.message, 'error'); }
      }));
    }

    if (tab === 'procore') {
      const add = $('#btnAddProcurement');
      if (add) add.addEventListener('click', () => openProcurementModal(project, null));
      $$('[data-edit-procurement]').forEach(b => b.addEventListener('click', () => {
        const item = projectTab().procurement.items.find(i => i.id === b.dataset.editProcurement);
        if (item) openProcurementModal(project, item);
      }));
      $$('[data-delete-procurement]').forEach(b => b.addEventListener('click', async () => {
        if (!confirm('Delete this procurement item?')) return;
        try {
          await apiReq(`/api/projects/${project.id}/procurement/${b.dataset.deleteProcurement}`, { method: 'DELETE' });
          await loadProjectTab('procore', project.id, { force: true });
          showToast('Procurement item deleted', 'info');
        } catch (error) { showToast(error.message, 'error'); }
      }));
    }
  }

  // Global Calendar ---------------------------------------------------------
  //
  // A month grid combining project dates, task dates, and events from the
  // already-connected Google and Microsoft accounts. It reuses the provider
  // slices and calendar endpoints the workspace pages use; there is no second
  // integration path here.

  const CALENDAR_SOURCES = {
    project: { label: 'Project dates', className: 'cal-project' },
    task: { label: 'Task dates', className: 'cal-task' },
    google: { label: 'Google Calendar', className: 'cal-google' },
    microsoft: { label: 'Outlook Calendar', className: 'cal-microsoft' }
  };

  function calendarState() {
    if (!state.calendar) {
      const today = new Date();
      state.calendar = {
        year: today.getFullYear(), month: today.getMonth(),
        events: [], loading: false, loaded: false,
        show: { project: true, task: true, google: true, microsoft: true },
        selectedDay: null, selectedItem: null, errors: []
      };
    }
    return state.calendar;
  }

  function isoDay(value) {
    const d = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(d.getTime())) return '';
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  /** Every day an item spans, so multi-day bars appear on each date. */
  function daySpan(start, end) {
    const from = isoDay(start);
    const to = isoDay(end || start);
    if (!from) return [];
    const days = [];
    const cursor = new Date(from);
    const last = new Date(to < from ? from : to);
    // Guard against a pathological range dominating the grid.
    for (let i = 0; i < 400 && cursor <= last; i += 1) {
      days.push(isoDay(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    return days;
  }

  async function loadCalendar({ force = false } = {}) {
    const cal = calendarState();
    if (cal.loading || (cal.loaded && !force)) return;
    cal.loading = true;
    cal.errors = [];
    renderPage();

    const events = [];

    // Projects and their tasks come from the account's own data.
    state.projects.filter(p => !p.archived).forEach(project => {
      if (project.start_date || project.end_date) {
        events.push({
          id: `project:${project.id}`,
          source: 'project', title: project.name,
          start: project.start_date || project.end_date,
          end: project.end_date || project.start_date,
          meta: `${project.project_code || 'Project'} · ${project.status || ''}`.trim(),
          projectId: project.id, record: project
        });
      }
    });

    await Promise.all(state.projects.filter(p => !p.archived).map(async project => {
      try {
        const res = await apiReq(`/api/projects/${project.id}/tasks`);
        (await res.json()).tasks.forEach(task => {
          const start = task.start_time || task.due_date;
          if (!start) return;
          events.push({
            id: `task:${task.id}`,
            source: 'task', title: task.name,
            start, end: task.end_time || task.due_date || start,
            meta: `${project.name}${task.assignee ? ' · ' + task.assignee : ''}`,
            status: task.status, projectId: project.id, taskId: task.id,
            record: task, projectName: project.name
          });
        });
      } catch (error) { cal.errors.push(`Tasks for ${project.name}: ${error.message}`); }
    }));

    // Connected calendars, through the existing provider endpoints.
    const from = new Date(cal.year, cal.month - 1, 1).toISOString();
    const to = new Date(cal.year, cal.month + 2, 0).toISOString();
    await Promise.all(Object.keys(WORKSPACE_PROVIDERS).map(async providerId => {
      const slice = ws(providerId);
      if (!slice.accountId) return;
      const cfg = providerConfig(providerId);
      try {
        const res = await apiReq(`${cfg.api}/calendar/events?account_id=${encodeURIComponent(slice.accountId)}` +
          `&time_min=${encodeURIComponent(from)}&time_max=${encodeURIComponent(to)}&max_results=250`);
        (await res.json()).events.forEach(event => {
          const start = event.start?.dateTime || event.start?.date;
          if (!start) return;
          events.push({
            id: `${providerId}:${event.id}`,
            source: providerId, title: event.summary || '(no title)',
            start, end: event.end?.dateTime || event.end?.date || start,
            meta: cfg.calendarLabel, link: event.htmlLink,
            timed: Boolean(event.start?.dateTime),
            meetLink: event.meet_link || event.hangoutLink || '',
            eventId: event.id, accountId: slice.accountId, record: event
          });
        });
      } catch (error) { cal.errors.push(`${cfg.label}: ${error.message}`); }
    }));

    cal.events = events;
    cal.loading = false;
    cal.loaded = true;
    renderNotificationBadge();
    renderPage();
  }

  function calendarEventsByDay() {
    const cal = calendarState();
    const map = new Map();
    cal.events.filter(e => cal.show[e.source]).forEach(event => {
      daySpan(event.start, event.end).forEach(day => {
        if (!map.has(day)) map.set(day, []);
        map.get(day).push(event);
      });
    });
    return map;
  }

  function renderCalendarPage() {
    const cal = calendarState();
    const first = new Date(cal.year, cal.month, 1);
    const monthLabel = first.toLocaleDateString([], { month: 'long', year: 'numeric' });
    const daysInMonth = new Date(cal.year, cal.month + 1, 0).getDate();
    const leading = first.getDay();
    const byDay = calendarEventsByDay();
    const todayIso = isoDay(new Date());

    const cells = [];
    for (let i = 0; i < leading; i += 1) cells.push('<div class="cal-cell cal-cell-muted"></div>');
    for (let day = 1; day <= daysInMonth; day += 1) {
      const iso = `${cal.year}-${String(cal.month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const items = byDay.get(iso) || [];
      const shown = items.slice(0, 3);
      cells.push(`<div class="cal-cell ${iso === todayIso ? 'cal-today' : ''} ${cal.selectedDay === iso ? 'cal-selected' : ''}" data-cal-day="${iso}">
        <div class="cal-date">${day}</div>
        ${shown.map(e => `<div class="cal-event ${CALENDAR_SOURCES[e.source].className}" title="${esc(e.title)} — ${esc(e.meta || '')}">${esc(e.title)}</div>`).join('')}
        ${items.length > shown.length ? `<div class="cal-more">+${items.length - shown.length} more</div>` : ''}
      </div>`);
    }
    while (cells.length % 7 !== 0) cells.push('<div class="cal-cell cal-cell-muted"></div>');

    const counts = Object.keys(CALENDAR_SOURCES).reduce((acc, key) => {
      acc[key] = cal.events.filter(e => e.source === key).length;
      return acc;
    }, {});
    const connected = Object.keys(WORKSPACE_PROVIDERS).filter(id => ws(id).accountId);
    const selected = cal.selectedDay ? (byDay.get(cal.selectedDay) || []) : [];

    return `${notConnectedMsg()}
      <div class="page-header">
        <div><h1 class="page-title">Calendar</h1>
          <p class="page-subtitle">Project and task dates with events from your connected calendars.</p></div>
        <div class="header-actions">
          <button class="btn btn-ghost btn-sm" id="btnCalPrev"><span class="material-icons-outlined">chevron_left</span></button>
          <span class="cal-month-label">${esc(monthLabel)}</span>
          <button class="btn btn-ghost btn-sm" id="btnCalNext"><span class="material-icons-outlined">chevron_right</span></button>
          <button class="btn btn-secondary btn-sm" id="btnCalToday">Today</button>
          <button class="btn btn-ghost btn-sm" id="btnCalRefresh" title="Refresh"><span class="material-icons-outlined">refresh</span></button>
          ${connected.length ? '<button class="btn btn-primary btn-sm" id="btnCalCreate"><span class="material-icons-outlined">add</span> New event</button>' : ''}
        </div>
      </div>

      <div class="cal-legend">
        ${Object.entries(CALENDAR_SOURCES).map(([key, src]) => `
          <label class="cal-legend-item ${cal.show[key] ? '' : 'off'}">
            <input type="checkbox" data-cal-source="${key}" ${cal.show[key] ? 'checked' : ''}>
            <i class="cal-swatch ${src.className}"></i>${src.label}
            <span class="cal-count">${counts[key]}</span>
          </label>`).join('')}
        ${connected.length ? '' : '<span class="form-hint">No Google or Microsoft account is connected, so only project and task dates are shown.</span>'}
      </div>

      ${cal.errors.length ? `<div class="connection-banner warning"><span class="material-icons-outlined">warning</span>
        <span>${esc(cal.errors[0])}${cal.errors.length > 1 ? ` (+${cal.errors.length - 1} more)` : ''}</span></div>` : ''}

      ${cal.loading ? '<div class="empty-msg">Loading calendar…</div>' : `
        <div class="cal-grid">
          ${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => `<div class="cal-head">${d}</div>`).join('')}
          ${cells.join('')}
        </div>`}

      ${cal.selectedDay ? `<div class="cal-day-panel">
        <div class="tasks-section-header">
          <h3 class="section-sub-title">${new Date(cal.selectedDay).toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}</h3>
          <button class="btn btn-ghost btn-sm" id="btnCalCloseDay"><span class="material-icons-outlined">close</span></button>
        </div>
        ${selected.length ? selected.map(e => renderCalendarDayItem(e)).join('') : '<div class="empty-msg">Nothing scheduled on this day.</div>'}
      </div>` : ''}`;
  }

  const CALENDAR_NAVIGABLE = { project: 'project', task: 'task' };

  function calendarItemKey(event) {
    return event.id || `${event.source}:${event.title}:${event.start}`;
  }

  function renderCalendarDayItem(event) {
    const cal = calendarState();
    const key = calendarItemKey(event);
    const open = cal.selectedItem === key;
    const navigable = CALENDAR_NAVIGABLE[event.source];
    return `<div class="cal-day-entry ${open ? 'open' : ''}">
      <div class="cal-day-item" data-cal-item="${esc(key)}">
        <i class="cal-swatch ${CALENDAR_SOURCES[event.source].className}"></i>
        <div>
          ${navigable
            ? `<button class="cal-item-title link" data-cal-open="${esc(key)}" title="Open ${navigable === 'project' ? 'project' : 'task'} details">${esc(event.title)}</button>`
            : `<strong class="cal-item-title">${esc(event.title)}</strong>`}
          <div class="google-snippet">${esc(event.meta || CALENDAR_SOURCES[event.source].label)}</div>
        </div>
        <span class="material-icons-outlined cal-item-chevron">${open ? 'expand_less' : 'expand_more'}</span>
        ${event.link ? `<a class="btn-table-action" href="${esc(event.link)}" target="_blank" rel="noopener" title="Open in ${esc(CALENDAR_SOURCES[event.source].label)}"><span class="material-icons-outlined">open_in_new</span></a>` : ''}
      </div>
      ${open ? `<div class="cal-detail">${renderCalendarDetail(event)}</div>` : ''}
    </div>`;
  }

  function detailRow(label, value) {
    if (value === undefined || value === null || value === '') return '';
    // Outlook notes arrive as multi-line text; collapsing them onto one line
    // would run sentences together.
    return `<div class="cal-detail-row"><span>${esc(label)}</span><b class="detail-multiline">${esc(String(value))}</b></div>`;
  }

  function humanDate(value, withTime) {
    if (!value) return '';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return withTime && String(value).includes('T')
      ? d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
      : d.toLocaleDateString([], { dateStyle: 'medium' });
  }

  function renderCalendarDetail(event) {
    const cal = calendarState();
    const record = event.record || {};
    if (event.source === 'project') {
      const costs = cal.costs?.[event.projectId];
      return `<div class="cal-detail-grid">
        ${detailRow('Project code', record.project_code)}
        ${detailRow('Manager', record.manager)}
        ${detailRow('Status', record.status)}
        ${detailRow('Type', record.type)}
        ${detailRow('Start', humanDate(record.start_date))}
        ${detailRow('End', humanDate(record.end_date))}
        ${detailRow('Total cost', costs ? money(costs.total) : 'Loading…')}
        ${detailRow('Description', record.description)}
      </div>
      <div class="cal-detail-actions">
        <button class="btn btn-secondary btn-sm" data-cal-open="${esc(calendarItemKey(event))}">Open project</button>
      </div>`;
    }
    if (event.source === 'task') {
      return `<div class="cal-detail-grid">
        ${detailRow('Project', event.projectName)}
        ${detailRow('Status', record.status)}
        ${detailRow('Priority', record.priority)}
        ${detailRow('Trade', record.trade)}
        ${detailRow('Assignee', record.assignee)}
        ${detailRow('On site', record.field_worker)}
        ${detailRow('Start', humanDate(record.start_time, true))}
        ${detailRow('End', humanDate(record.end_time, true))}
        ${detailRow('Due', humanDate(record.due_date))}
        ${detailRow('Cost', money(record.cost || 0))}
        ${detailRow('Description', record.description)}
      </div>
      <div class="cal-detail-actions">
        <button class="btn btn-secondary btn-sm" data-cal-open="${esc(calendarItemKey(event))}">Open task</button>
      </div>`;
    }
    // Google / Microsoft event
    const cfg = providerConfig(event.source);
    return `<div class="cal-detail-grid">
      ${detailRow('Calendar', cfg.calendarLabel)}
      ${detailRow('Starts', humanDate(event.start, true))}
      ${detailRow('Ends', humanDate(event.end, true))}
      ${detailRow('Location', record.location)}
      ${detailRow('Organiser', record.organizer?.email || record.organizer)}
      ${event.meetLink ? `<div class="cal-detail-row"><span>${esc(cfg.meetingLabel)}</span><b><a href="${esc(event.meetLink)}" target="_blank" rel="noopener">Join</a></b></div>` : ''}
      ${detailRow('Meeting ID', record.meeting_id)}
      ${detailRow('Passcode', record.meeting_passcode)}
      ${detailRow('Attendees', (record.attendees || []).map(a => a.email).filter(Boolean).join(', '))}
      ${detailRow('Details', record.description)}
    </div>
    <div class="cal-detail-actions">
      <button class="btn btn-primary btn-sm" data-cal-edit="${esc(calendarItemKey(event))}">
        <span class="material-icons-outlined" style="font-size:18px">edit_calendar</span> Edit event</button>
      ${event.meetLink ? `<a class="btn btn-secondary btn-sm" href="${esc(event.meetLink)}" target="_blank" rel="noopener">
        <span class="material-icons-outlined" style="font-size:18px">videocam</span> Join ${esc(cfg.meetingLabel)}</a>` : ''}
      ${event.link ? `<a class="btn btn-secondary btn-sm" href="${esc(event.link)}" target="_blank" rel="noopener">Open in ${esc(cfg.label)}</a>` : ''}
    </div>`;
  }

  /** Split an ISO timestamp into the date and time inputs of the edit form. */
  function splitDateTime(value) {
    if (!value) return { date: '', time: '' };
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return { date: String(value).slice(0, 10), time: '' };
    const pad = n => String(n).padStart(2, '0');
    return {
      date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
      time: String(value).includes('T') ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : ''
    };
  }

  function openCalendarEventEditor(event) {
    const cfg = providerConfig(event.source);
    const record = event.record || {};
    const from = splitDateTime(event.start);
    const to = splitDateTime(event.end);
    const allDay = !from.time;
    DOM.crudModalTitle.textContent = `Edit ${cfg.calendarLabel} event`;
    DOM.crudModalBody.innerHTML = `
      <div class="form-hint" style="margin-bottom:12px">Saving updates the event in <b>${esc(cfg.label)}</b> on the connected account, not just here.</div>
      <div class="form-group"><label class="form-label required-label">Title</label>
        <input class="form-input" id="calEvTitle" value="${esc(event.title)}"></div>
      <div class="form-grid-2">
        <div class="form-group"><label class="form-label">Date</label>
          <input type="date" class="form-input" id="calEvDate" value="${esc(from.date)}"></div>
        <div class="form-group"><label class="form-label">End date</label>
          <input type="date" class="form-input" id="calEvEndDate" value="${esc(to.date || from.date)}"></div>
        <div class="form-group"><label class="form-label">Start time</label>
          <input type="time" class="form-input" id="calEvStart" value="${esc(from.time || '09:00')}"></div>
        <div class="form-group"><label class="form-label">End time</label>
          <input type="time" class="form-input" id="calEvEnd" value="${esc(to.time || '10:00')}"></div>
      </div>
      ${allDay ? '<div class="form-hint">This was an all-day event; saving gives it the times above.</div>' : ''}
      <div class="form-group"><label class="form-label">Location</label>
        <input class="form-input" id="calEvLocation" value="${esc(record.location || '')}"></div>
      <div class="form-group"><label class="form-label">Attendees (comma separated)</label>
        <input class="form-input" id="calEvAttendees" value="${esc((record.attendees || []).map(a => a.email).filter(Boolean).join(', '))}"></div>
      <div class="form-group"><label class="form-label">Description</label>
        <textarea class="form-input" id="calEvDescription" rows="3">${esc(record.description || '')}</textarea></div>`;
    DOM.btnSaveCrud.dataset.crudAction = 'update-calendar-event';
    DOM.btnSaveCrud.dataset.crudId = event.source;
    DOM.btnSaveCrud.dataset.crudExtra = `${event.accountId}|${event.eventId}`;
    DOM.crudModal.classList.add('open');
  }

  /**
   * Create an event on a connected Google or Microsoft calendar.
   *
   * Both providers already accept the same create call, so this is one form
   * with a provider picker rather than two flows; the conferencing checkbox
   * maps to whichever field that provider uses.
   */
  function openCalendarEventCreator() {
    const connected = Object.keys(WORKSPACE_PROVIDERS).filter(id => ws(id).accountId);
    if (!connected.length) {
      showToast('Connect a Google or Microsoft account first', 'warning');
      return;
    }
    const cal = calendarState();
    const preferred = connected.includes(agentProvider()) ? agentProvider() : connected[0];
    const day = cal.selectedDay || isoDay(new Date());
    DOM.crudModalTitle.textContent = 'New calendar event';
    DOM.crudModalBody.innerHTML = `
      <div class="form-group"><label class="form-label">Calendar</label>
        <select class="form-input" id="calNewProvider">
          ${connected.map(id => `<option value="${id}" ${id === preferred ? 'selected' : ''}>${esc(providerConfig(id).calendarLabel)} — ${esc(activeProviderAccount(id)?.email || '')}</option>`).join('')}
        </select></div>
      <div class="form-group"><label class="form-label required-label">Title</label>
        <input class="form-input" id="calNewTitle" placeholder="e.g. Site walkthrough"></div>
      <div class="form-grid-2">
        <div class="form-group"><label class="form-label">Date</label>
          <input type="date" class="form-input" id="calNewDate" value="${esc(day)}"></div>
        <div class="form-group"><label class="form-label">End date</label>
          <input type="date" class="form-input" id="calNewEndDate" value="${esc(day)}"></div>
        <div class="form-group"><label class="form-label">Start time</label>
          <input type="time" class="form-input" id="calNewStart" value="09:00"></div>
        <div class="form-group"><label class="form-label">End time</label>
          <input type="time" class="form-input" id="calNewEnd" value="10:00"></div>
      </div>
      <div class="form-group"><label class="form-label">Location</label>
        <input class="form-input" id="calNewLocation"></div>
      <div class="form-group"><label class="form-label">Attendees (comma separated)</label>
        <input class="form-input" id="calNewAttendees" placeholder="name@example.com, other@example.com"></div>
      <div class="form-group"><label class="form-label">Description</label>
        <textarea class="form-input" id="calNewDescription" rows="3"></textarea></div>
      <label class="cal-meet-toggle"><input type="checkbox" id="calNewMeet" checked>
        <span>Add a <b id="calNewMeetLabel">${esc(providerConfig(preferred).meetingLabel)}</b> link</span></label>
      <div class="form-hint">The event is created on the connected account, so everyone invited sees it in their own calendar.</div>`;
    $('#calNewProvider')?.addEventListener('change', event => {
      const label = $('#calNewMeetLabel');
      if (label) label.textContent = providerConfig(event.target.value).meetingLabel;
    });
    DOM.btnSaveCrud.dataset.crudAction = 'create-calendar-event';
    DOM.crudModal.classList.add('open');
  }

  async function submitCalendarEventCreate() {
    const providerId = $('#calNewProvider')?.value;
    const cfg = providerConfig(providerId);
    if (!cfg) { showToast('Choose a calendar', 'warning'); return; }
    const accountId = ws(providerId).accountId;
    const title = $('#calNewTitle')?.value.trim();
    if (!title) { showToast('Event title is required', 'warning'); return; }
    const date = $('#calNewDate')?.value;
    if (!date) { showToast('Pick a date for the event', 'warning'); return; }
    const start = `${date}T${$('#calNewStart')?.value || '09:00'}:00`;
    const end = `${$('#calNewEndDate')?.value || date}T${$('#calNewEnd')?.value || '10:00'}:00`;
    if (end <= start) { showToast('The event must end after it starts', 'warning'); return; }

    const attendees = ($('#calNewAttendees')?.value || '').split(',').map(v => v.trim()).filter(Boolean);
    const bad = attendees.filter(value => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value));
    if (bad.length) { showToast(`Not valid email addresses: ${bad.join(', ')}`, 'warning', 6000); return; }

    const body = {
      account_id: accountId, summary: title, start, end,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      location: $('#calNewLocation')?.value.trim() || '',
      description: $('#calNewDescription')?.value.trim() || '',
      attendees,
      [cfg.meetingField]: !!$('#calNewMeet')?.checked,
      confirm: true
    };
    const save = DOM.btnSaveCrud;
    save.disabled = true;
    try {
      const response = await apiReq(`${cfg.api}/calendar/events`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      const result = await response.json();
      closeCrudModal();
      await loadCalendar({ force: true });
      const link = result.meet_link;
      showToast(link ? `Created in ${cfg.calendarLabel} with a ${cfg.meetingLabel} link` : `Created in ${cfg.calendarLabel}`, 'success', link ? 6000 : 4000);
    } catch (error) {
      showToast(`Could not create the event: ${error.message}`, 'error', 8000);
    } finally { save.disabled = false; }
  }

  async function submitCalendarEventUpdate(providerId, accountId, eventId) {
    const cfg = providerConfig(providerId);
    const title = $('#calEvTitle')?.value.trim();
    if (!title) { showToast('Event title is required', 'warning'); return; }
    const date = $('#calEvDate')?.value;
    const endDate = $('#calEvEndDate')?.value || date;
    const startTime = $('#calEvStart')?.value || '09:00';
    const endTime = $('#calEvEnd')?.value || '10:00';
    if (!date) { showToast('Pick a date for the event', 'warning'); return; }
    const start = `${date}T${startTime}:00`;
    const end = `${endDate}T${endTime}:00`;
    if (end <= start) { showToast('The event must end after it starts', 'warning'); return; }

    const body = {
      account_id: accountId, summary: title, start, end,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      location: $('#calEvLocation')?.value.trim() || '',
      description: $('#calEvDescription')?.value.trim() || '',
      attendees: ($('#calEvAttendees')?.value || '').split(',').map(v => v.trim()).filter(Boolean),
      confirm: true
    };
    const save = DOM.btnSaveCrud;
    save.disabled = true;
    try {
      await apiReq(`${cfg.api}/calendar/events/${encodeURIComponent(eventId)}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      closeCrudModal();
      // Re-read from the provider so the grid shows what the calendar now holds.
      await loadCalendar({ force: true });
      showToast(`Updated in ${cfg.calendarLabel}`, 'success');
    } catch (error) {
      showToast(`Could not update the event: ${error.message}`, 'error', 7000);
    } finally { save.disabled = false; }
  }

  /** Project totals are only needed once a project row is expanded. */
  async function ensureCalendarProjectCost(projectId) {
    const cal = calendarState();
    cal.costs = cal.costs || {};
    if (cal.costs[projectId]) return;
    try {
      const res = await apiReq(`/api/projects/${projectId}/costs`);
      cal.costs[projectId] = await res.json();
      renderPage();
    } catch (error) { /* the row simply shows no total */ }
  }

  function bindCalendarEvents() {
    const cal = calendarState();
    const shift = delta => {
      const next = new Date(cal.year, cal.month + delta, 1);
      cal.year = next.getFullYear();
      cal.month = next.getMonth();
      cal.selectedDay = null;
      renderPage();
      // Connected-calendar windows follow the month being viewed.
      loadCalendar({ force: true });
    };
    $('#btnCalPrev')?.addEventListener('click', () => shift(-1));
    $('#btnCalNext')?.addEventListener('click', () => shift(1));
    $('#btnCalToday')?.addEventListener('click', () => {
      const today = new Date();
      cal.year = today.getFullYear(); cal.month = today.getMonth(); cal.selectedDay = null;
      renderPage(); loadCalendar({ force: true });
    });
    $('#btnCalRefresh')?.addEventListener('click', () => loadCalendar({ force: true }));
    $('#btnCalCreate')?.addEventListener('click', openCalendarEventCreator);
    $('#btnCalCloseDay')?.addEventListener('click', () => { cal.selectedDay = null; renderPage(); });
    $$('[data-cal-source]').forEach(box => box.addEventListener('change', () => {
      cal.show[box.dataset.calSource] = box.checked;
      renderPage();
    }));
    $$('[data-cal-day]').forEach(cell => cell.addEventListener('click', () => {
      cal.selectedDay = cal.selectedDay === cell.dataset.calDay ? null : cell.dataset.calDay;
      cal.selectedItem = null;
      renderPage();
    }));

    const byKey = key => cal.events.find(e => calendarItemKey(e) === key);

    // Clicking the row toggles its detail popover.
    $$('[data-cal-item]').forEach(row => row.addEventListener('click', event => {
      if (event.target.closest('[data-cal-open]') || event.target.closest('a')) return;
      const key = row.dataset.calItem;
      cal.selectedItem = cal.selectedItem === key ? null : key;
      renderPage();
      const opened = byKey(key);
      if (cal.selectedItem && opened?.source === 'project') ensureCalendarProjectCost(opened.projectId);
    }));

    // The title (and the button inside the popover) navigates.
    $$('[data-cal-open]').forEach(button => button.addEventListener('click', async event => {
      event.stopPropagation();
      const item = byKey(button.dataset.calOpen);
      if (!item) return;
      if (item.source === 'task') { await openTaskInBoard(item.projectId, item.taskId); return; }
      state.activeProjectId = item.projectId;
      state._dashTab = 'overview';
      resetProjectTabData(item.projectId);
      await Promise.all([fetchProjectTasks(item.projectId), fetchProjectSources(item.projectId)]);
      navigateTo('project-details');
    }));

    $$('[data-cal-edit]').forEach(button => button.addEventListener('click', event => {
      event.stopPropagation();
      const item = byKey(button.dataset.calEdit);
      if (item) openCalendarEventEditor(item);
    }));
  }

  // ═══ Deadline notifications ═══
  //
  // Anything on the calendar -- a project, a task, or an event from a
  // connected Google or Microsoft account -- that finishes inside the next two
  // days. The window is measured from the current clock every time it is
  // asked for, so the list stays true without the page being reloaded.

  const NOTIFICATION_WINDOW_MS = 2 * 24 * 60 * 60 * 1000;

  /**
   * When an entry actually finishes.
   *
   * A date with no clock time covers the whole of that day, so it finishes at
   * midnight rather than at 00:00 -- otherwise something due today would look
   * as though it had already passed.
   */
  function entryEndsAt(entry) {
    const raw = entry.end || entry.start;
    if (!raw) return null;
    const when = new Date(raw);
    if (Number.isNaN(when.getTime())) return null;
    if (!String(raw).includes('T')) when.setHours(23, 59, 59, 999);
    return when;
  }

  /**
   * Where an entry sits relative to the window.
   *
   * A timed event is judged on its own finish time. An all-day one is judged
   * from the start of the day it finishes on, so a deadline dated two days out
   * appears now rather than only once the clock passes its 23:59.
   */
  function windowAnchor(entry, endsAt) {
    const raw = entry.end || entry.start;
    if (String(raw).includes('T')) return endsAt;
    const dayStart = new Date(endsAt);
    dayStart.setHours(0, 0, 0, 0);
    return dayStart;
  }

  function notificationItems(now = new Date()) {
    const horizon = new Date(now.getTime() + NOTIFICATION_WINDOW_MS);
    return calendarState().events
      .map(entry => ({ entry, endsAt: entryEndsAt(entry) }))
      .filter(row => row.endsAt
        && row.endsAt >= now
        && windowAnchor(row.entry, row.endsAt) <= horizon)
      .sort((a, b) => a.endsAt - b.endsAt);
  }

  /** "in 3 hours", "tomorrow", "in 2 days" -- how close the deadline is. */
  function untilLabel(endsAt, now = new Date(), entry = null) {
    // An all-day item is counted in whole days. Measuring its 23:59 finish in
    // hours would report something dated two days out as three.
    const allDay = entry && !String(entry.end || entry.start).includes('T');
    if (allDay) {
      const midnight = d => { const c = new Date(d); c.setHours(0, 0, 0, 0); return c; };
      const days = Math.round((midnight(endsAt) - midnight(now)) / 86400000);
      if (days <= 0) return 'today';
      return days === 1 ? 'tomorrow' : `in ${days} days`;
    }
    const minutes = Math.round((endsAt - now) / 60000);
    if (minutes < 60) return minutes <= 1 ? 'due now' : `in ${minutes} minutes`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return hours === 1 ? 'in an hour' : `in ${hours} hours`;
    const days = Math.round(hours / 24);
    return days === 1 ? 'tomorrow' : `in ${days} days`;
  }

  function renderNotificationBadge() {
    if (!DOM.notifBadge) return;
    const count = state.session ? notificationItems().length : 0;
    DOM.notifBadge.textContent = count > 9 ? '9+' : String(count);
    DOM.notifBadge.hidden = count === 0;
    DOM.btnNotifications?.classList.toggle('has-alerts', count > 0);
  }

  function renderNotificationPanel() {
    if (!DOM.notifPanel) return;
    const now = new Date();
    const rows = notificationItems(now);
    DOM.notifPanel.innerHTML = `
      <div class="notif-head">
        <strong>Finishing soon</strong>
        <span class="form-hint">Next 2 days</span>
      </div>
      ${rows.length ? `<div class="notif-list">${rows.map(({ entry, endsAt }) => `
        <button class="notif-item" data-notif-key="${esc(calendarItemKey(entry))}">
          <i class="cal-swatch ${CALENDAR_SOURCES[entry.source].className}"></i>
          <span class="notif-item-body">
            <span class="notif-item-title">${esc(entry.title)}</span>
            <span class="notif-item-meta">${esc(CALENDAR_SOURCES[entry.source].label)} · ends ${esc(humanDate(endsAt.toISOString(), true))}</span>
          </span>
          <span class="notif-when">${esc(untilLabel(endsAt, now, entry))}</span>
        </button>`).join('')}</div>`
        : '<div class="notif-empty">Nothing finishes in the next two days.</div>'}
      ${calendarState().loaded ? '' : '<div class="notif-empty">Loading your calendar…</div>'}`;

    DOM.notifPanel.querySelectorAll('[data-notif-key]').forEach(button =>
      button.addEventListener('click', () => openNotification(button.dataset.notifKey)));
  }

  /** Take the user to whatever the notification refers to. */
  async function openNotification(key) {
    const entry = calendarState().events.find(item => calendarItemKey(item) === key);
    closeNotifications();
    if (!entry) return;
    if (entry.source === 'task') { await openTaskInBoard(entry.projectId, entry.taskId); return; }
    if (entry.source === 'project') {
      state.activeProjectId = entry.projectId;
      state._dashTab = 'overview';
      resetProjectTabData(entry.projectId);
      await Promise.all([fetchProjectTasks(entry.projectId), fetchProjectSources(entry.projectId)]);
      navigateTo('project-details');
      return;
    }
    // A Google or Outlook event: open the calendar on its day, with it expanded.
    const cal = calendarState();
    const endsAt = entryEndsAt(entry) || new Date();
    cal.year = endsAt.getFullYear();
    cal.month = endsAt.getMonth();
    cal.selectedDay = isoDay(entry.start) || isoDay(endsAt);
    cal.selectedItem = key;
    navigateTo('calendar');
  }

  function closeNotifications() {
    state.notificationsOpen = false;
    if (DOM.notifPanel) DOM.notifPanel.hidden = true;
    DOM.btnNotifications?.setAttribute('aria-expanded', 'false');
  }

  async function toggleNotifications() {
    if (state.notificationsOpen) { closeNotifications(); return; }
    state.notificationsOpen = true;
    DOM.notifPanel.hidden = false;
    DOM.btnNotifications?.setAttribute('aria-expanded', 'true');
    renderNotificationPanel();
    // The calendar is normally only fetched when its page is opened, so make
    // sure there is something to notify about.
    if (!calendarState().loaded && !calendarState().loading) {
      await loadCalendar();
      if (state.notificationsOpen) renderNotificationPanel();
      renderNotificationBadge();
    }
  }

  /** Keep the count honest as the clock moves past each deadline. */
  function startNotificationPolling() {
    clearInterval(state._notificationTimer);
    state._notificationTimer = setInterval(() => {
      if (!state.session) return;
      renderNotificationBadge();
      if (state.notificationsOpen) renderNotificationPanel();
    }, 60000);
  }

  // Connected workspaces (Google + Microsoft) -------------------------------
  //
  // Both providers expose the same three capabilities -- files, mail, calendar
  // -- over the same request/response shapes, so one set of renderers and
  // handlers drives both. A descriptor supplies the labels and the API prefix;
  // element ids are prefixed with the provider key, which keeps every existing
  // Google id (googleDriveSearch, btnGoogleConnect, ...) exactly as it was.

  const WORKSPACE_PROVIDERS = {
    google: {
      id: 'google',
      label: 'Google Workspace',
      api: '/api/google',
      mailPath: 'gmail',
      filesLabel: 'Drive',
      mailLabel: 'Gmail',
      calendarLabel: 'Google Calendar',
      // The conferencing this provider can attach to an event, and the route
      // that schedules one conversationally.
      meetingLabel: 'Google Meet',
      meetingField: 'add_meet',
      meetingPath: 'meet/schedule',
      filesIcon: 'cloud',
      mailIcon: 'mail',
      subtitle: 'Index Drive files and email, compose Gmail messages, and use Calendar events with Marshal.',
      mailSearchHint: 'Gmail query, e.g. from:client has:attachment',
      connectBlurb: 'BuildMarshal will request read-only Drive and Gmail access, Gmail compose access, and Calendar event access. It never returns your refresh token to this browser.',
      connectLabel: 'Continue with Google',
      configHint: 'Google OAuth is not configured in the backend. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_TOKEN_ENCRYPTION_KEY, and GOOGLE_ALLOWED_ORIGINS.'
    },
    microsoft: {
      id: 'microsoft',
      label: 'Microsoft 365',
      api: '/api/microsoft',
      mailPath: 'mail',
      filesLabel: 'OneDrive',
      mailLabel: 'Outlook Mail',
      calendarLabel: 'Outlook Calendar',
      meetingLabel: 'Teams meeting',
      meetingField: 'add_online_meeting',
      meetingPath: 'meeting/schedule',
      filesIcon: 'cloud_queue',
      mailIcon: 'alternate_email',
      subtitle: 'Index OneDrive files and Outlook mail, compose messages, and use Outlook Calendar events with Marshal.',
      mailSearchHint: 'Search Outlook, e.g. project handover',
      connectBlurb: 'BuildMarshal will request read-only OneDrive and Outlook Mail access, mail send access, and Calendar event access. It never returns your refresh token to this browser.',
      connectLabel: 'Continue with Microsoft',
      configHint: 'Microsoft OAuth is not configured in the backend. Set MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_TENANT_ID, and MICROSOFT_ALLOWED_ORIGINS.'
    }
  };

  function emptyProviderState() {
    return {
      config: null, accounts: [], accountId: '', tab: 'files', loading: false,
      files: [], messages: [], events: [],
      selectedFiles: new Set(), selectedMessages: new Set(),
      emailDraft: { to: '', cc: '', subject: '', body: '', instruction: '' },
      taskProjectId: ''
    };
  }

  function ws(providerId) {
    if (!state.providers[providerId]) state.providers[providerId] = emptyProviderState();
    return state.providers[providerId];
  }

  function providerConfig(providerId) { return WORKSPACE_PROVIDERS[providerId]; }

  function activeProviderAccount(providerId) {
    const slice = ws(providerId);
    return slice.accounts.find(account => account.id === slice.accountId) || null;
  }

  /** The provider a chat command should act through when several are linked. */
  function agentProvider() {
    const preferred = state.activeWorkspaceProvider;
    if (preferred && ws(preferred).accountId) return preferred;
    return Object.keys(WORKSPACE_PROVIDERS).find(id => ws(id).accountId) || null;
  }

  function providerProjectOptions(selected = '') {
    return `<option value="">Global documents (no project)</option>${state.projects.map(project =>
      `<option value="${esc(project.id)}" ${project.id === selected ? 'selected' : ''}>${esc(project.name)}</option>`
    ).join('')}`;
  }

  function renderWorkspacePage(providerId) {
    const cfg = providerConfig(providerId);
    const slice = ws(providerId);
    const account = activeProviderAccount(providerId);
    const enabled = slice.config?.enabled;
    const accountOptions = slice.accounts.map(item =>
      `<option value="${item.id}" ${item.id === slice.accountId ? 'selected' : ''}>${esc(item.email)}</option>`
    ).join('');
    const other = Object.values(WORKSPACE_PROVIDERS).filter(p => p.id !== providerId && ws(p.id).accountId);
    return `${notConnectedMsg()}
      <div class="page-header google-page-header">
        <div><h1 class="page-title">${esc(cfg.label)}</h1><p class="page-subtitle">${esc(cfg.subtitle)}</p></div>
        <div class="header-actions">
          ${slice.accounts.length ? `<select class="form-input google-account-select" id="${providerId}AccountSelect">${accountOptions}</select>` : ''}
          <button class="btn btn-secondary" id="btn${cap(providerId)}Connect"><span class="material-icons-outlined">add</span>Add account</button>
          ${account ? `<button class="btn btn-ghost" id="btn${cap(providerId)}Disconnect" title="Disconnect ${esc(account.email)}"><span class="material-icons-outlined">link_off</span></button>` : ''}
        </div>
      </div>
      ${other.length ? `<div class="provider-crosslink">${other.map(p => `<span class="material-icons-outlined">link</span>${esc(p.label)} is also connected as <strong>${esc(activeProviderAccount(p.id)?.email || '')}</strong>`).join('')}</div>` : ''}
      ${slice.config && !enabled ? `<div class="connection-banner warning"><span class="material-icons-outlined">warning</span><span>${esc(cfg.configHint)}</span></div>` : ''}
      ${!account ? `<div class="google-connect-card"><span class="material-icons-outlined">account_circle</span><h3>Connect a ${esc(cfg.label)} account</h3><p>${esc(cfg.connectBlurb)}</p><button class="btn btn-primary" id="btn${cap(providerId)}ConnectEmpty" ${!enabled ? 'disabled' : ''}>${esc(cfg.connectLabel)}</button></div>` : `
        <div class="google-account-chip">${account.picture ? `<img src="${esc(account.picture)}" alt="">` : `<span class="user-avatar-badge">${esc((account.name || account.email || '?').slice(0,2))}</span>`}<div><strong>${esc(account.name || account.email)}</strong><span>${esc(account.email)}</span></div></div>
        <div class="tab-strip google-tabs">
          ${[['files', cfg.filesIcon, cfg.filesLabel], ['mail', cfg.mailIcon, cfg.mailLabel], ['calendar', 'event', 'Calendar']].map(([tab, icon, label]) =>
            `<button class="tab-btn ${slice.tab === tab ? 'active' : ''}" data-provider="${providerId}" data-provider-tab="${tab}"><span class="material-icons-outlined">${icon}</span>${esc(label)}</button>`
          ).join('')}
        </div>
        <div class="google-tab-content">${slice.tab === 'files' ? renderProviderFilesTab(providerId) : slice.tab === 'mail' ? renderProviderMailTab(providerId) : renderProviderCalendarTab(providerId)}</div>
      `}`;
  }

  function cap(value) { return value.charAt(0).toUpperCase() + value.slice(1); }

  function renderProviderFilesTab(providerId) {
    const cfg = providerConfig(providerId);
    const slice = ws(providerId);
    const P = providerId;
    return `<div class="workspace-toolbar">
      <div class="filter-group grow"><label class="filter-label">Search ${esc(cfg.filesLabel)}</label><input class="filter-input" id="${P}DriveSearch" placeholder="File name"></div>
      <div class="filter-group"><label class="filter-label">Index under project</label><select class="filter-input" id="${P}DriveProject">${providerProjectOptions()}</select></div>
      <button class="btn btn-secondary" id="btn${cap(P)}DriveRefresh"><span class="material-icons-outlined">search</span>Load files</button>
      <button class="btn btn-primary" id="btn${cap(P)}DriveImport" ${slice.selectedFiles.size ? '' : 'disabled'}><span class="material-icons-outlined">library_add</span>Index selected (${slice.selectedFiles.size})</button>
    </div>
    <div class="data-table-container"><table class="data-table google-table"><thead><tr><th class="check-col"><input type="checkbox" id="${P}DriveAll"></th><th>Name</th><th>Type</th><th>Modified</th><th></th></tr></thead><tbody>
      ${slice.files.length ? slice.files.map(file => `<tr><td>${file.is_folder ? '' : `<input type="checkbox" class="provider-file-check" data-provider="${P}" value="${esc(file.id)}" ${slice.selectedFiles.has(file.id) ? 'checked' : ''}>`}</td><td><div class="google-item-title"><span class="material-icons-outlined">${file.is_folder ? 'folder' : 'description'}</span>${esc(file.name)}</div></td><td>${esc(String(file.mimeType || '').replace('application/vnd.google-apps.', 'Google ').replace('application/vnd.openxmlformats-officedocument.', 'Office '))}</td><td>${file.modifiedTime ? new Date(file.modifiedTime).toLocaleString() : '—'}</td><td>${file.webViewLink ? `<a class="btn-table-action" href="${esc(file.webViewLink)}" target="_blank" rel="noopener"><span class="material-icons-outlined">open_in_new</span></a>` : ''}</td></tr>`).join('') : `<tr><td colspan="5" class="td-empty">Click Load files to see documents in this ${esc(cfg.filesLabel)}.</td></tr>`}
    </tbody></table></div>`;
  }

  function renderProviderMailTab(providerId) {
    const cfg = providerConfig(providerId);
    const slice = ws(providerId);
    const draft = slice.emailDraft;
    const P = providerId;
    return `<div class="workspace-section">
      <div class="workspace-toolbar">
        <div class="filter-group grow"><label class="filter-label">Search ${esc(cfg.mailLabel)}</label><input class="filter-input" id="${P}MailSearch" placeholder="${esc(cfg.mailSearchHint)}"></div>
        <div class="filter-group"><label class="filter-label">Index under project</label><select class="filter-input" id="${P}MailProject">${providerProjectOptions()}</select></div>
        <button class="btn btn-secondary" id="btn${cap(P)}MailRefresh">Load emails</button>
        <button class="btn btn-primary" id="btn${cap(P)}MailImport" ${slice.selectedMessages.size ? '' : 'disabled'}>Index selected (${slice.selectedMessages.size})</button>
      </div>
      <div class="data-table-container"><table class="data-table google-table"><thead><tr><th class="check-col"><input type="checkbox" id="${P}MailAll"></th><th>Subject</th><th>From</th><th>Date</th></tr></thead><tbody>
        ${slice.messages.length ? slice.messages.map(message => `<tr><td><input type="checkbox" class="provider-message-check" data-provider="${P}" value="${esc(message.id)}" ${slice.selectedMessages.has(message.id) ? 'checked' : ''}></td><td><strong>${esc(message.subject)}</strong><div class="google-snippet">${esc(message.snippet || '')}</div></td><td>${esc(message.from)}</td><td>${esc(message.date)}</td></tr>`).join('') : '<tr><td colspan="4" class="td-empty">Click Load emails to see messages. Only checked messages are indexed.</td></tr>'}
      </tbody></table></div>
    </div>
    <div class="workspace-section compose-card"><div class="section-heading"><div><h3>Compose with Marshal</h3><p>Generate a draft, save it to ${esc(cfg.mailLabel)}, or send it after confirmation.</p></div><span class="material-icons-outlined">edit_note</span></div>
      <div class="google-form-grid"><div class="form-group"><label class="form-label">To</label><input class="form-input" id="${P}EmailTo" value="${esc(draft.to)}" placeholder="recipient@example.com"></div><div class="form-group"><label class="form-label">Cc</label><input class="form-input" id="${P}EmailCc" value="${esc(draft.cc)}"></div><div class="form-group full"><label class="form-label">Instruction for Marshal</label><textarea class="form-input" id="${P}EmailInstruction" rows="2" placeholder="Write a concise progress update asking for approval...">${esc(draft.instruction)}</textarea></div><div class="form-group full"><label class="form-label">Subject</label><input class="form-input" id="${P}EmailSubject" value="${esc(draft.subject)}"></div><div class="form-group full"><label class="form-label">Body</label><textarea class="form-input email-body" id="${P}EmailBody" rows="9">${esc(draft.body)}</textarea></div></div>
      <div class="form-actions"><button class="btn btn-secondary" id="btn${cap(P)}EmailGenerate"><span class="material-icons-outlined">auto_awesome</span>Generate</button><button class="btn btn-secondary" id="btn${cap(P)}EmailDraft">Create ${esc(cfg.mailLabel)} draft</button><button class="btn btn-primary danger-confirm" id="btn${cap(P)}EmailSend"><span class="material-icons-outlined">send</span>Send now</button></div>
    </div>`;
  }

  function renderProviderCalendarTab(providerId) {
    const cfg = providerConfig(providerId);
    const slice = ws(providerId);
    const P = providerId;
    const localValue = value => new Date(value - new Date(value).getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    const defaultStart = localValue(Date.now() + 3600000);
    const defaultEnd = localValue(Date.now() + 7200000);
    const now = Date.now();
    return `<div class="workspace-toolbar" style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <button class="btn btn-secondary" id="btn${cap(P)}CalendarRefresh"><span class="material-icons-outlined">refresh</span>Load / Refresh Events</button>
        ${slice.events.length ? `<span class="badge" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);color:var(--text-secondary,#999);padding:4px 10px;border-radius:12px;font-size:12px;">${slice.events.length} events loaded</span>` : ''}
      </div>
    </div>
      <div class="calendar-event-list">${slice.events.length ? slice.events.map(event => {
        const start = event.start?.dateTime || event.start?.date || '';
        const startTime = start ? new Date(start).getTime() : 0;
        const isPast = startTime > 0 && startTime < now;
        return `<div class="calendar-event-card" style="${isPast ? 'opacity:0.85;' : ''}"><div class="calendar-date">${start ? new Date(start).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '—'}</div><div style="flex:1;"><strong>${esc(event.summary || '(Untitled event)')}</strong> ${isPast ? '<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(255,255,255,0.08);color:var(--text-muted,#888);margin-left:6px;">Past</span>' : '<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(34,197,94,0.15);color:#22c55e;margin-left:6px;">Upcoming</span>'}<p>${start ? new Date(start).toLocaleString() : ''}</p>${event.description ? `<span>${esc(event.description).slice(0, 180)}</span>` : ''}</div>${event.htmlLink ? `<a href="${esc(event.htmlLink)}" target="_blank" rel="noopener" title="Open in ${esc(cfg.calendarLabel)}"><span class="material-icons-outlined">open_in_new</span></a>` : ''}</div>`;
      }).join('') : `<div class="empty-inline">Click "Load / Refresh Events" to fetch events from your ${esc(cfg.calendarLabel)}.</div>`}</div>
      <div class="workspace-section compose-card"><div class="section-heading"><div><h3>Add event or project task</h3><p>Select a task to copy its title, then review every field before adding it to ${esc(cfg.calendarLabel)}.</p></div><span class="material-icons-outlined">event_available</span></div>
        <div class="google-form-grid"><div class="form-group"><label class="form-label">Project</label><select class="form-input" id="${P}TaskProject"><option value="">No project task</option>${state.projects.map(p => `<option value="${p.id}" ${p.id === slice.taskProjectId ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div><div class="form-group"><label class="form-label">Task</label><select class="form-input" id="${P}TaskSelect"><option value="">Choose task</option>${state.projectTasks.map(t => `<option value="${t.id}">${esc(t.name || t.title)}</option>`).join('')}</select></div><div class="form-group full"><label class="form-label">Event title</label><input class="form-input" id="${P}EventSummary"></div><div class="form-group"><label class="form-label">Start</label><input type="datetime-local" class="form-input" id="${P}EventStart" value="${defaultStart}"></div><div class="form-group"><label class="form-label">End</label><input type="datetime-local" class="form-input" id="${P}EventEnd" value="${defaultEnd}"></div><div class="form-group full"><label class="form-label">Description</label><textarea class="form-input" id="${P}EventDescription" rows="3"></textarea></div><div class="form-group full"><label class="form-label">Attendees (comma separated)</label><input class="form-input" id="${P}EventAttendees"></div>${P === 'google' ? `<div class="form-group full meet-toggle"><label class="form-label" for="${P}EventMeet"><input type="checkbox" id="${P}EventMeet" checked> Add a Google Meet link</label></div>` : ''}</div>
        <div class="form-actions"><button class="btn btn-primary" id="btn${cap(P)}CalendarCreate"><span class="material-icons-outlined">event</span>Add to ${esc(cfg.calendarLabel)}</button></div>
      </div>`;
  }

  async function loadWorkspaceProvider(providerId) {
    const cfg = providerConfig(providerId);
    const slice = ws(providerId);
    if (!getApiUrl() || !state.session || slice.loading) return;
    slice.loading = true;
    try {
      const [configResponse, accountsResponse] = await Promise.all([
        apiReq(`${cfg.api}/config`), apiReq(`${cfg.api}/accounts`)
      ]);
      slice.config = await configResponse.json();
      slice.accounts = (await accountsResponse.json()).accounts || [];
      if (!slice.accounts.some(item => item.id === slice.accountId)) {
        slice.accountId = slice.accounts[0]?.id || '';
      }
      if (slice.accountId) {
        localStorage.setItem(accountScopedKey(`bmarshal_${providerId}_account`), slice.accountId);
      }
      if (state.currentPage === `${providerId}-workspace`) renderPage();
    } catch (error) {
      showToast(`${cfg.label}: ${error.message}`, 'error');
    } finally { slice.loading = false; }
  }

  /** Google Identity Services popup -> authorization code -> backend. */
  async function connectGoogleAccount() {
    const slice = ws('google');
    if (!slice.config) await loadWorkspaceProvider('google');
    if (!slice.config?.enabled) { showToast('Configure Google OAuth in the backend first.', 'warning'); return; }
    if (window.location.protocol === 'file:') { showToast('Google sign-in cannot run from file://. Serve the frontend on localhost or HTTPS.', 'error', 7000); return; }
    if (!window.google?.accounts?.oauth2) { showToast('Google sign-in script is still loading. Try again in a moment.', 'warning'); return; }
    const client = google.accounts.oauth2.initCodeClient({
      client_id: slice.config.client_id,
      scope: slice.config.scopes.join(' '),
      ux_mode: 'popup',
      select_account: true,
      callback: async response => {
        if (response.error) { showToast(`Google sign-in failed: ${response.error}`, 'error'); return; }
        try {
          await apiReq('/api/google/oauth/code', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XmlHttpRequest' }, body: JSON.stringify({ code: response.code, redirect_uri: window.location.origin }) });
          await loadWorkspaceProvider('google');
          renderPage();
          showToast('Google account connected.', 'success');
        } catch (error) { showToast(error.message, 'error', 7000); }
      }
    });
    client.requestCode();
  }

  /**
   * Microsoft authorization-code flow with PKCE.
   *
   * The backend mints the state and the code verifier and returns a ready-made
   * authorize URL, so this browser never handles the client secret. The popup
   * lands on oauth-callback.html, which posts the code back to this window.
   */
  async function connectMicrosoftAccount() {
    const slice = ws('microsoft');
    if (!slice.config) await loadWorkspaceProvider('microsoft');
    if (!slice.config?.enabled) { showToast('Configure Microsoft OAuth in the backend first.', 'warning'); return; }
    if (window.location.protocol === 'file:') { showToast('Microsoft sign-in cannot run from file://. Serve the frontend on localhost or HTTPS.', 'error', 7000); return; }

    const redirectUri = `${window.location.origin}/oauth-callback.html`;
    let start;
    try {
      const response = await apiReq('/api/microsoft/oauth/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ redirect_uri: redirectUri })
      });
      start = await response.json();
    } catch (error) { showToast(error.message, 'error', 7000); return; }

    const popup = window.open(start.authorize_url, 'buildmarshal-microsoft-oauth', 'width=520,height=680');
    if (!popup) { showToast('Allow popups for this site to connect a Microsoft account.', 'warning', 7000); return; }

    await new Promise(resolve => {
      let settled = false;
      const finish = () => { if (settled) return; settled = true; window.removeEventListener('message', onMessage); clearInterval(closedTimer); resolve(); };

      const onMessage = async event => {
        // Only trust messages from this exact origin and from our callback page.
        if (event.origin !== window.location.origin) return;
        const data = event.data || {};
        if (data.source !== 'buildmarshal-oauth' || data.provider !== 'microsoft') return;
        if (data.state !== start.state) return;
        finish();
        if (data.error) { showToast(`Microsoft sign-in failed: ${data.errorDescription || data.error}`, 'error', 7000); return; }
        try {
          await apiReq('/api/microsoft/oauth/code', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: data.code, state: data.state, redirect_uri: redirectUri })
          });
          await loadWorkspaceProvider('microsoft');
          renderPage();
          showToast('Microsoft account connected.', 'success');
        } catch (error) { showToast(error.message, 'error', 7000); }
      };

      window.addEventListener('message', onMessage);
      // The user may simply close the popup; stop listening when they do.
      const closedTimer = setInterval(() => { if (popup.closed) finish(); }, 700);
    });
  }

  function connectProvider(providerId) {
    return providerId === 'microsoft' ? connectMicrosoftAccount() : connectGoogleAccount();
  }

  function renderProjectSourcesSection() {
    if (!state.projectSources.length) {
      return `<div class="empty-msg">No PDF sources are linked to this project yet. Click <b>Upload Source</b> to add one.</div>`;
    }
    return `<div class="doc-cards-grid">${state.projectSources.map(d => {
      const ext = getExt(d.name || 'source.pdf');
      const sourceType = (d.source_type || 'reference').replaceAll('_', ' ');
      return `<div class="doc-card" data-doc-id="${d.id}" data-name="${esc(d.name)}">
        <div class="doc-card-icon ${getFileClass(ext)}">${getFileIcon(ext)}</div>
        <div class="doc-card-info">
          <div class="doc-card-name">${esc(d.name)}</div>
          <div class="doc-card-meta">${d.pages || 0} pages Â· ${esc(sourceType)} Â· <span class="badge ${d.status === 'indexed' ? 'badge-active' : 'badge-inactive'}" style="font-size:0.68rem">${esc(d.status || 'indexed')}</span></div>
        </div>
        <div class="doc-card-actions">
          <button class="btn-table-action" data-action="preview-doc" data-id="${d.id}" data-name="${esc(d.name)}" title="Preview"><span class="material-icons-outlined">visibility</span></button>
          <button class="btn-table-action delete" data-action="delete-doc" data-id="${d.id}" title="Delete"><span class="material-icons-outlined">delete</span></button>
        </div>
      </div>`;
    }).join('')}</div>`;
  }

  function renderProjectTasksSection() {
    if (!state.projectTasks.length)
      return `<div class="empty-msg">No tasks yet. Click <b>Add Task</b> to create one.</div>`;
    const visible = state.projectTasks.filter(t => !t.archived);
    if (!visible.length)
      return `<div class="empty-msg">All tasks for this project are archived. Open <b>Tasks</b> to review them.</div>`;
    return visible.map(t => `
      <div class="task-row clickable" data-task-id="${esc(t.id)}" title="Open in Task Manager">
        <span class="material-icons-outlined task-expand-icon">chevron_right</span>
        <span class="task-status-icon ${t.status === 'Completed' ? 'task-done' : ''}">
          <span class="material-icons-outlined">${t.status === 'Completed' ? 'check_circle' : 'radio_button_unchecked'}</span>
        </span>
        <span class="task-name">${esc(t.name)}</span>
        ${t.trade ? `<span class="task-chip">${esc(t.trade)}</span>` : ''}
        ${t.assignee ? `<span class="task-chip">${esc(t.assignee)}</span>` : ''}
        <span class="task-status-chip ${taskStatusClass(t.status)}">${esc(t.status)}</span>
      </div>`).join('');
  }

  // ── Project Modal (Create / Edit) ───────────────────────────────────────────
  /** The project form.
   *
   * `seed` prefills a new project from something already understood -- a chat
   * sentence, say -- and `missing` names the fields that still have to be
   * filled, so the form can point at them instead of leaving them to be found.
   */
  function openProjectModal(pid = null, seed = null, missing = []) {
    const p = pid ? state.projects.find(x => x.id === pid) : seed;
    const title = pid ? 'Edit Project' : 'New Project';
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
            ${projectTypeNames().map(t => `<option value="${esc(t)}" ${p?.type === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}
            ${p?.type && !projectTypeNames().includes(p.type) ? `<option value="${esc(p.type)}" selected>${esc(p.type)} (retired)</option>` : ''}
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
    markMissingFields({ name: 'projFName', project_code: 'projFCode', manager: 'projFMgr',
                        type: 'projFType', status: 'projFStatus', start_date: 'projFStart',
                        end_date: 'projFEnd', description: 'projFDesc' }, missing);
  }

  /** Ring the fields still to be filled, and put the caret in the first.
   *
   * The form already says which fields are required; this says which ones are
   * required *and still empty right now*, which is the only question the person
   * in front of it has.
   */
  function markMissingFields(idsByField, missing) {
    const wanted = (missing || []).map(row => (typeof row === 'string' ? row : row.name));
    let first = null;
    wanted.forEach(field => {
      const element = idsByField[field] && $(`#${idsByField[field]}`);
      if (!element) return;
      element.classList.add('field-needed');
      element.closest('.form-group')?.classList.add('is-needed');
      if (!first) first = element;
    });
    if (first) setTimeout(() => first.focus(), 60);
  }


  function openDocumentGenerationModal(projectId) {
    const project = state.projects.find(p => p.id === projectId);
    if (!project) { showToast('Project not found', 'error'); return; }
    DOM.crudModalTitle.textContent = 'Generate Project Document';
    DOM.crudModalBody.innerHTML = `
      <div class="form-group">
        <label class="form-label required">Document Type</label>
        <select class="form-input" id="docGenKind">
          <option value="tender_summary">Tender Summary</option>
          <option value="project_brief">Project Brief</option>
          <option value="schedule_summary">Schedule Summary</option>
          <option value="addendum_summary">Addendum Summary</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Title</label>
        <input class="form-input" id="docGenTitle" placeholder="Auto-generated when blank">
      </div>
      <div class="form-group">
        <label class="form-label">Additional Instructions</label>
        <textarea class="form-input" id="docGenInstructions" rows="4" placeholder="Example: Focus on revised deadlines and commercial allowances"></textarea>
      </div>
      <div class="form-group">
        <label class="form-label">Evidence pages per section</label>
        <input class="form-input" id="docGenTopK" type="number" min="1" max="12" value="6">
        <div class="form-hint">Each section runs a separate project-filtered retrieval query.</div>
      </div>`;
    DOM.btnSaveCrud.textContent = 'Generate PDF';
    DOM.btnSaveCrud.dataset.crudAction = 'generate-project-document';
    DOM.btnSaveCrud.dataset.crudId = projectId;
    DOM.crudModal.classList.add('open');
  }

  async function downloadGeneratedDocument(metadata) {
    const response = await apiReq(metadata.download_url);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(metadata.title || 'BuildMarshal_Document').replace(/[^a-z0-9._-]+/gi, '_')}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  // ═══ Authentication & Account ═══
  //
  // The app shell renders nothing until `applySession` has installed a
  // verified session.  Signing out or losing the session tears down every
  // piece of account state in memory and in this browser's cache, so a second
  // account signing in on the same machine starts from an empty client.

  const SESSION_KEY = APP_CONFIG.STORAGE_KEYS.SESSION;

  function readStoredSession() {
    try {
      const raw = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null');
      return raw && raw.token ? raw : null;
    } catch (e) { return null; }
  }

  function writeStoredSession(session) {
    try {
      if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      else localStorage.removeItem(SESSION_KEY);
    } catch (e) { }
  }

  function clearAccountState() {
    state.session = null;
    state.currentUser = null;
    state.account = null;
    state.settings = {};
    state.chats = {};
    state.activeChatId = null;
    state.conversationsLoaded = false;
    state.uploadedDocs = [];
    state.trades = [];
    state.vendors = [];
    state.teamMembers = [];
    state.users = [];
    state.projects = [];
    state.projectTasks = [];
    state.projectSources = [];
    state.taskBoard = null;
    state.taskTypes = [];
    state.projectTypes = [];
    state.userRoles = [];
    state.rolesEditable = false;
    state.permissionGroups = [];
    state.myPermissions = [];
    state.todo = null;
    state.catalogsEditable = false;
    state.company = null;
    state.projectTab = null;
    state.calendar = null;
    closeNotifications();
    state.activeProjectId = null;
    state.providers = {};
    state.activeWorkspaceProvider = 'google';
    state.userDropdownOpen = false;
    state.pendingMeet = null;
    state.pendingEventEdit = null;
    clearTimeout(state._conversationSaveTimer);
    // Blob URLs hold decoded page images from the outgoing account.
    releaseObjectUrls();
    // Connected external accounts are per BuildMarshal account; never carry
    // the remembered selection over to another one.
    try {
      Object.keys(WORKSPACE_PROVIDERS).forEach(id =>
        localStorage.removeItem(accountScopedKey(`bmarshal_${id}_account`)));
    } catch (e) { }
  }

  function showAuthGate(mode) {
    if (!DOM.authGate) return;
    DOM.authGate.classList.add('open');
    document.body.classList.add('auth-locked');
    if (DOM.authApiUrlInput) DOM.authApiUrlInput.value = getApiUrl() || 'http://127.0.0.1:8000';
    switchAuthTab(mode || 'signin');
    setTimeout(() => {
      const focusTarget = $(mode === 'signup' ? '#signUpName' : '#signInEmail');
      if (focusTarget) focusTarget.focus();
    }, 40);
  }

  function hideAuthGate() {
    if (!DOM.authGate) return;
    DOM.authGate.classList.remove('open');
    document.body.classList.remove('auth-locked');
  }

  function switchAuthTab(mode) {
    const isSignUp = mode === 'signup';
    if (DOM.tabBtnSignIn) {
      DOM.tabBtnSignIn.classList.toggle('active', !isSignUp);
      DOM.tabBtnSignIn.setAttribute('aria-selected', String(!isSignUp));
    }
    if (DOM.tabBtnSignUp) {
      DOM.tabBtnSignUp.classList.toggle('active', isSignUp);
      DOM.tabBtnSignUp.setAttribute('aria-selected', String(isSignUp));
    }
    if (DOM.formSignIn) DOM.formSignIn.style.display = isSignUp ? 'none' : 'flex';
    if (DOM.formSignUp) DOM.formSignUp.style.display = isSignUp ? 'flex' : 'none';
    const heading = $('#authGateHeading');
    if (heading) heading.textContent = isSignUp ? 'Create your workspace' : 'Sign in to your workspace';
    setAuthError(DOM.signInError, '');
    setAuthError(DOM.signUpError, '');
  }

  function setAuthError(el, message) {
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('visible', Boolean(message));
  }

  function persistAuthApiUrl() {
    const url = (DOM.authApiUrlInput && DOM.authApiUrlInput.value.trim()) || 'http://127.0.0.1:8000';
    APP_CONFIG.API_URL = url;
    localStorage.setItem(APP_CONFIG.STORAGE_KEYS.API_URL, url);
    // Typed by hand, so it outranks the port the launcher announces.
    localStorage.setItem('bmarshal_api_url_pinned', '1');
    return url;
  }

  async function applySession(payload) {
    state.session = { token: payload.token };
    state.currentUser = payload.user || null;
    state.account = payload.account || null;
    applyAccountSettings(payload.settings);
    state.providers = {};
    Object.keys(WORKSPACE_PROVIDERS).forEach(id => {
      try { ws(id).accountId = localStorage.getItem(accountScopedKey(`bmarshal_${id}_account`)) || ''; }
      catch (e) { ws(id).accountId = ''; }
    });
    writeStoredSession({
      token: payload.token,
      user: payload.user,
      account: payload.account
    });
    hideAuthGate();
    renderUserProfileHeader();
    await loadConversations();
    renderChatMessages();
    renderChatHistory();
    navigateTo('all-projects');
    await checkConnection();
    await fetchAllData();
    // Load the connected workspaces up front rather than when their page is
    // first opened, so chat commands ("schedule a Google Meet...") know which
    // accounts are linked from the first message.
    Object.keys(WORKSPACE_PROVIDERS).forEach(id => { loadWorkspaceProvider(id); });
    // Deadlines are useful on every page, not only once Calendar is opened.
    loadCalendar().then(renderNotificationBadge);
    startNotificationPolling();
  }

  async function restoreSession() {
    const stored = readStoredSession();
    if (!stored) { showAuthGate('signin'); return; }
    // Trust the stored token only as far as the backend confirms it.
    state.session = { token: stored.token };
    try {
      const res = await apiReq('/api/auth/me', { skipAuthRedirect: true });
      await applySession({ ...(await res.json()), token: stored.token });
    } catch (e) {
      clearAccountState();
      writeStoredSession(null);
      renderUserProfileHeader();
      showAuthGate('signin');
    }
  }

  function handleSessionExpired() {
    if (!state.session) return;
    clearAccountState();
    writeStoredSession(null);
    renderUserProfileHeader();
    DOM.contentArea.innerHTML = '';
    DOM.chatMessages.innerHTML = '';
    setConn('disconnected');
    showAuthGate('signin');
    showToast('Your session has ended. Please sign in again.', 'warning');
  }

  async function submitSignIn(event) {
    event.preventDefault();
    persistAuthApiUrl();
    setAuthError(DOM.signInError, '');
    const email = $('#signInEmail').value.trim();
    const password = $('#signInPassword').value;
    if (!email || !password) { setAuthError(DOM.signInError, 'Enter your email and password.'); return; }

    DOM.btnSignInSubmit.disabled = true;
    DOM.btnSignInSubmit.textContent = 'Signing in…';
    try {
      const res = await apiReq('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        skipAuthRedirect: true
      });
      $('#signInPassword').value = '';
      await applySession(await res.json());
      showToast(`Signed in as ${state.currentUser.name}`, 'success');
    } catch (e) {
      setAuthError(DOM.signInError, e.message);
    } finally {
      DOM.btnSignInSubmit.disabled = false;
      DOM.btnSignInSubmit.textContent = 'Sign in';
    }
  }

  async function submitSignUp(event) {
    event.preventDefault();
    persistAuthApiUrl();
    setAuthError(DOM.signUpError, '');
    const name = $('#signUpName').value.trim();
    const email = $('#signUpEmail').value.trim();
    const accountName = $('#signUpAccount').value.trim();
    const password = $('#signUpPassword').value;
    const confirm = $('#signUpConfirm').value;

    if (!name) { setAuthError(DOM.signUpError, 'Enter your name.'); return; }
    if (!email) { setAuthError(DOM.signUpError, 'Enter your email address.'); return; }
    if (password.length < 8) { setAuthError(DOM.signUpError, 'Password must be at least 8 characters.'); return; }
    if (password !== confirm) { setAuthError(DOM.signUpError, 'The two passwords do not match.'); return; }

    DOM.btnSignUpSubmit.disabled = true;
    DOM.btnSignUpSubmit.textContent = 'Creating account…';
    try {
      const res = await apiReq('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password, account_name: accountName, company: accountName }),
        skipAuthRedirect: true
      });
      $('#signUpPassword').value = '';
      $('#signUpConfirm').value = '';
      await applySession(await res.json());
      showToast('Workspace created. Everything you add stays private to this account.', 'success', 6000);
    } catch (e) {
      setAuthError(DOM.signUpError, e.message);
    } finally {
      DOM.btnSignUpSubmit.disabled = false;
      DOM.btnSignUpSubmit.textContent = 'Create account';
    }
  }

  async function signOut() {
    try { await apiReq('/api/auth/logout', { method: 'POST', skipAuthRedirect: true }); } catch (e) { }
    clearAccountState();
    writeStoredSession(null);
    renderUserProfileHeader();
    DOM.contentArea.innerHTML = '';
    DOM.chatMessages.innerHTML = '';
    renderChatHistory();
    updateDocBadge();
    setConn('disconnected');
    showAuthGate('signin');
    showToast('Signed out', 'info');
  }

  function initials(name) {
    return String(name || '?').trim().split(/\s+/).slice(0, 2).map(part => part[0] || '').join('') || '?';
  }

  function renderUserProfileHeader() {
    const host = DOM.userProfileHeader;
    if (!host) return;
    const user = state.currentUser;
    if (!user) { host.innerHTML = ''; return; }

    const dropdown = state.userDropdownOpen ? `
      <div class="user-profile-dropdown" id="userDropdown">
        <div class="dropdown-user-header">
          <div class="dropdown-user-name">${esc(user.name)}</div>
          <div class="dropdown-user-email">${esc(user.email)}</div>
          <span class="dropdown-user-badge">${esc(state.account ? state.account.name : user.role)}</span>
        </div>
        <button class="dropdown-item" data-action="account">
          <span class="material-icons-outlined" style="font-size:18px">manage_accounts</span> My Account
        </button>
        <button class="dropdown-item" data-action="members">
          <span class="material-icons-outlined" style="font-size:18px">group</span> Account Members
        </button>
        <button class="dropdown-item" data-action="settings">
          <span class="material-icons-outlined" style="font-size:18px">tune</span> Settings
        </button>
        <div class="dropdown-divider"></div>
        <button class="dropdown-item danger" data-action="signout">
          <span class="material-icons-outlined" style="font-size:18px">logout</span> Sign out
        </button>
      </div>` : '';

    host.innerHTML = `
      <button class="user-profile-pill" id="userProfilePill" aria-haspopup="true" aria-expanded="${state.userDropdownOpen}">
        <span class="user-avatar-badge">${esc(initials(user.name))}</span>
        <span class="user-pill-info">
          <span class="user-pill-name">${esc(user.name)}</span>
          <span class="user-pill-role">${esc(user.role || 'User')}</span>
        </span>
      </button>${dropdown}`;

    const pill = $('#userProfilePill');
    if (pill) pill.addEventListener('click', (event) => {
      event.stopPropagation();
      state.userDropdownOpen = !state.userDropdownOpen;
      renderUserProfileHeader();
    });
    host.querySelectorAll('.dropdown-item').forEach(item => {
      item.addEventListener('click', (event) => {
        event.stopPropagation();
        state.userDropdownOpen = false;
        renderUserProfileHeader();
        const action = item.dataset.action;
        if (action === 'signout') signOut();
        else if (action === 'settings') openSettings();
        else if (action === 'members') navigateTo('users');
        else navigateTo('account');
      });
    });
  }

  // ── Account page ───────────────────────────────────────────────────────────

  async function renderAccountPage() {
    const user = state.currentUser;
    if (!user) return;
    DOM.contentArea.innerHTML = `<div class="page-header"><h1 class="page-title">My Account</h1></div>
      <div class="empty-state"><p>Loading account…</p></div>`;

    let usage = {};
    let account = state.account || {};
    try {
      const data = await (await apiReq('/api/account')).json();
      account = data.account || account;
      usage = data.usage || {};
      state.account = account;
    } catch (e) { /* fall back to what the session already knows */ }

    const isOwner = Boolean(user.is_owner);
    const canRename = isOwner || SYSTEM_ROLES.includes(user.role);
    const usageItems = [
      ['Documents', usage.documents], ['Indexed pages', usage.indexed_pages],
      ['Members', usage.members], ['Projects', usage.projects],
      ['Conversations', usage.conversations]
    ].filter(([, value]) => value !== undefined);

    DOM.contentArea.innerHTML = `
      <div class="page-header"><h1 class="page-title">My Account</h1></div>
      <div class="account-cards">
        <div class="account-card">
          <h2>Workspace</h2>
          <p class="account-card-hint">Documents, indexes, projects, settings, conversations, and connected
            Google accounts belong to this workspace and are not visible to any other account.</p>
          <div class="account-usage">
            ${usageItems.map(([label, value]) => `<div class="account-usage-item">
              <div class="account-usage-value">${esc(String(value))}</div>
              <div class="account-usage-label">${esc(label)}</div>
            </div>`).join('')}
          </div>
          <div class="form-group" style="margin-top:16px">
            <label class="form-label" for="acctName">Workspace name</label>
            <input class="form-input" id="acctName" value="${esc(account.name || '')}" ${canRename ? '' : 'disabled'}>
          </div>
          ${canRename ? '<button class="btn btn-primary" id="btnSaveAccountName">Save workspace name</button>' : ''}
        </div>

        <div class="account-card">
          <h2>Your profile</h2>
          <p class="account-card-hint">Your sign-in email is ${esc(user.email)}.</p>
          <div class="form-group">
            <label class="form-label" for="acctFullName">Name</label>
            <input class="form-input" id="acctFullName" value="${esc(user.name || '')}">
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label" for="acctPhone">Phone</label>
              <input class="form-input" id="acctPhone" value="${esc(user.phone || '')}">
            </div>
            <div class="form-group">
              <label class="form-label" for="acctCompany">Company</label>
              <input class="form-input" id="acctCompany" value="${esc(user.company || '')}">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label" for="acctAddress">Address</label>
            <input class="form-input" id="acctAddress" value="${esc(user.address || '')}">
          </div>
          <button class="btn btn-primary" id="btnSaveProfile">Save profile</button>
        </div>

        <div class="account-card">
          <h2>Password</h2>
          <p class="account-card-hint">Changing your password signs out every other session on this account.</p>
          <div class="form-group">
            <label class="form-label" for="acctCurrentPw">Current password</label>
            <input class="form-input" type="password" id="acctCurrentPw" autocomplete="current-password">
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label" for="acctNewPw">New password</label>
              <input class="form-input" type="password" id="acctNewPw" autocomplete="new-password" minlength="8">
            </div>
            <div class="form-group">
              <label class="form-label" for="acctConfirmPw">Confirm new password</label>
              <input class="form-input" type="password" id="acctConfirmPw" autocomplete="new-password" minlength="8">
            </div>
          </div>
          <button class="btn btn-primary" id="btnChangePassword">Change password</button>
        </div>

        ${isOwner ? `<div class="account-card danger">
          <h2>Delete this workspace</h2>
          <p class="account-card-hint">Permanently removes every document, page image, vector index, project,
            conversation, setting, and connected Google account for this workspace, along with all of its
            member logins. This cannot be undone.</p>
          <button class="btn btn-danger" id="btnDeleteAccount">Delete workspace permanently</button>
        </div>` : ''}
      </div>`;

    const btnName = $('#btnSaveAccountName');
    if (btnName) btnName.addEventListener('click', async () => {
      const name = $('#acctName').value.trim();
      if (!name) { showToast('Workspace name is required', 'warning'); return; }
      try {
        const data = await (await apiReq('/api/account', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name })
        })).json();
        state.account = data.account;
        const stored = readStoredSession();
        if (stored) writeStoredSession({ ...stored, account: data.account });
        renderUserProfileHeader();
        showToast('Workspace renamed', 'success');
      } catch (e) { showToast(e.message, 'error'); }
    });

    $('#btnSaveProfile').addEventListener('click', async () => {
      try {
        const data = await (await apiReq('/api/auth/profile', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: $('#acctFullName').value.trim(),
            phone: $('#acctPhone').value.trim(),
            company: $('#acctCompany').value.trim(),
            address: $('#acctAddress').value.trim()
          })
        })).json();
        state.currentUser = data.user;
        const stored = readStoredSession();
        if (stored) writeStoredSession({ ...stored, user: data.user });
        renderUserProfileHeader();
        showToast('Profile updated', 'success');
      } catch (e) { showToast(e.message, 'error'); }
    });

    $('#btnChangePassword').addEventListener('click', async () => {
      const current = $('#acctCurrentPw').value;
      const next = $('#acctNewPw').value;
      if (next.length < 8) { showToast('New password must be at least 8 characters', 'warning'); return; }
      if (next !== $('#acctConfirmPw').value) { showToast('The two passwords do not match', 'error'); return; }
      try {
        const data = await (await apiReq('/api/auth/password', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ current_password: current, new_password: next })
        })).json();
        // The old session was revoked; adopt the replacement issued with it.
        state.session = { token: data.token };
        const stored = readStoredSession() || {};
        writeStoredSession({ ...stored, token: data.token });
        $('#acctCurrentPw').value = $('#acctNewPw').value = $('#acctConfirmPw').value = '';
        showToast('Password changed. Other sessions were signed out.', 'success');
      } catch (e) { showToast(e.message, 'error'); }
    });

    const btnDelete = $('#btnDeleteAccount');
    if (btnDelete) btnDelete.addEventListener('click', async () => {
      const name = (state.account && state.account.name) || 'this workspace';
      if (!confirm(`Delete "${name}" and everything in it? This cannot be undone.`)) return;
      if (!confirm('Last check: all documents, indexes, projects, and conversations will be erased.')) return;
      try {
        await apiReq('/api/account', { method: 'DELETE' });
        clearAccountState();
        writeStoredSession(null);
        renderUserProfileHeader();
        DOM.contentArea.innerHTML = '';
        showAuthGate('signup');
        showToast('Workspace deleted', 'info');
      } catch (e) { showToast(e.message, 'error'); }
    });
  }

  function bindAuthEvents() {
    if (DOM.formSignIn) DOM.formSignIn.addEventListener('submit', submitSignIn);
    if (DOM.formSignUp) DOM.formSignUp.addEventListener('submit', submitSignUp);
    if (DOM.tabBtnSignIn) DOM.tabBtnSignIn.addEventListener('click', () => switchAuthTab('signin'));
    if (DOM.tabBtnSignUp) DOM.tabBtnSignUp.addEventListener('click', () => switchAuthTab('signup'));
    if (DOM.linkSwitchToSignUp) DOM.linkSwitchToSignUp.addEventListener('click', (e) => { e.preventDefault(); switchAuthTab('signup'); });
    if (DOM.linkSwitchToSignIn) DOM.linkSwitchToSignIn.addEventListener('click', (e) => { e.preventDefault(); switchAuthTab('signin'); });
    document.addEventListener('click', () => {
      if (state.userDropdownOpen) { state.userDropdownOpen = false; renderUserProfileHeader(); }
    });
  }

  // ═══ User Management ═══

  // Mirrors ACCOUNT_ROLES in backend/accounts.py. Administration is a
  // system-level role; everything else describes what a person does.
  // Only these two exist without being created; see the User Roles page.
  const SYSTEM_ROLES = ['Super Admin', 'System Admin'];

  /** Every assignable role: the built-ins plus whatever this account created. */
  function assignableRoles() {
    const names = state.userRoles.map(role => role.name).filter(Boolean);
    return names.length ? names : [...SYSTEM_ROLES];
  }

  function roleOptions(selected = '') {
    return assignableRoles().map(name =>
      `<option value="${esc(name)}" ${name === selected ? 'selected' : ''}>${esc(name)}</option>`
    ).join('');
  }
  const DEPARTMENTS = ['Management', 'Construction / Site Operations', 'Engineering', 'Finance', 'HR', 'IT', 'Sales', 'Operations'];
  const DESIGNATIONS = ['Project Manager', 'Site Supervisor', 'Engineer', 'Estimator', 'Coordinator', 'Director', 'Analyst', 'Developer'];
  const TIME_ZONES = ['UTC', 'UTC-8 (PST)', 'UTC-7 (MST)', 'UTC-6 (CST)', 'UTC-5 (EST)', 'UTC+0 (GMT)', 'UTC+5:30 (IST)', 'UTC+8 (CST/HKT)', 'UTC+10 (AEST)'];

  function roleBadgeClass(role) {
    return {
      'Guest': 'badge-role-guest', 'User': 'badge-role-user',
      'Super Admin': 'badge-role-super', 'System Admin': 'badge-role-system',
      'Project Manager': 'badge-role-admin', 'Site Supervisor': 'badge-role-admin',
      'HR': 'badge-role-blue', 'Sales Representative': 'badge-role-blue',
      'Accountant': 'badge-role-blue', 'Procurement Officer': 'badge-role-blue',
      'Estimator': 'badge-role-blue'
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
        <div>
          <h1 class="page-title">User</h1>
          <div class="form-hint">People who can sign in to
            ${esc((state.account && state.account.name) || 'this workspace')}. They share its documents,
            projects, and settings, and cannot see any other account.</div>
        </div>
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
              ${roleOptions()}
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
    tbody.innerHTML = filtered.length ? filtered.map(u => `<tr data-id="${u.id}" >
      <td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${esc(u.phone || '')}</td>
      <td>${esc(u.address || '')}</td>
      <td><span class="badge ${u.status === 'Active' ? 'badge-active' : 'badge-inactive'}">${u.status}</span></td>
      <td><span class="badge ${roleBadgeClass(u.role)}">${u.role}</span></td>
      <td>${u.department ? `<span class="badge badge-dept">${esc(u.department)}</span>` : '—'}</td>
      <td><div class="table-actions"><button class="btn-table-action" data-action="edit-user" data-id="${u.id}" title="Edit"><span class="material-icons-outlined">edit</span></button></div></td>
    </tr> `).join('') : ` <tr > <td colspan="8" class="td-empty">No users match filters</td></tr> `;
    tbody.querySelectorAll('[data-action]').forEach(el => el.addEventListener('click', handleAction));
  }

  function clearUserFilters() {
    ['userNameFilter', 'userEmailFilter'].forEach(id => { const el = $(`#${id} `); if (el) el.value = ''; });
    ['userStatusFilter', 'userRoleFilter', 'userDeptFilter'].forEach(id => { const el = $(`#${id} `); if (el) el.value = ''; });
    applyUserFilters();
  }

  /** The fields a new user is made of.
   *
   * One definition, used by the Create User page and by the dialog chat opens,
   * so the two can never drift apart -- and the element ids are shared, so one
   * submit function serves both.
   */
  function userFormFields(seed = null) {
    return `
          <div class="user-form-grid">
            <div class="form-group">
              <label class="form-label required-label">Name</label>
              <input class="form-input" id="ufName" placeholder="Full name" value="${esc(seed?.name || '')}">
            </div>
            <div class="form-group">
              <label class="form-label required-label">Email</label>
              <input class="form-input" id="ufEmail" type="email" placeholder="email@example.com" value="${esc(seed?.email || '')}">
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
              <input class="form-input" id="ufPhone" placeholder="Phone number" value="${esc(seed?.phone || '')}">
            </div>
            <div class="form-group">
              <label class="form-label">Address</label>
              <input class="form-input" id="ufAddress" placeholder="Address" value="${esc(seed?.address || '')}">
            </div>
            <div class="form-group">
              <label class="form-label required-label">Role</label>
              <select class="form-input" id="ufRole">
                <option value="">Select role...</option>
                ${roleOptions(seed?.role || '')}
              </select>
            </div>
          </div>`;
  }

  /** Show/hide on every password field currently on screen. */
  function bindPasswordToggles() {
    $$('.pw-toggle').forEach(button => {
      if (button.dataset.bound) return;
      button.dataset.bound = '1';
      button.addEventListener('click', () => {
        const field = button.previousElementSibling;
        if (!field) return;
        field.type = field.type === 'password' ? 'text' : 'password';
        button.querySelector('span.material-icons-outlined').textContent =
          field.type === 'password' ? 'visibility_off' : 'visibility';
      });
    });
  }

  function renderCreateUserPage() {
    DOM.contentArea.innerHTML = `
    <div class="user-form-page" >
        <div class="page-header" style="margin-bottom:24px">
          <h1 class="page-title">Create User</h1>
        </div>
        <div class="user-form-card">
          ${userFormFields()}
          <div class="user-form-actions">
            <button class="btn btn-primary" id="btnCreateUserSubmit">Create</button>
            <button class="btn btn-secondary" id="btnCancelCreate">Cancel</button>
          </div>
        </div>
      </div> `;
  }

  async function submitCreateUser({ onDone = null } = {}) {
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
    if (pw.length < 8) { showToast('Password must be at least 8 characters', 'warning'); return; }
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
      if (onDone) onDone({ name, email, role });
      else navigateTo('users');
    } catch (err) { showToast(err.message, 'error'); }
  }

  function renderEditUserPage(userId) {
    const user = state.users.find(u => u.id === userId);
    if (!user) { navigateTo('users'); return; }

    const isActive = user.status === 'Active';
    DOM.contentArea.innerHTML = `
    <div class="user-form-page" >
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
                      ${roleOptions(user.role)}
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
      await apiReq(`/api/users/${id}`, {
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
    const btnUD = $('#btnUploadDocs'); if (btnUD) btnUD.addEventListener('click', () => openUploadPanel(null));

    // Company Settings
    $('#btnCompanyEdit')?.addEventListener('click', () => { state._companyEditing = true; renderPage(); });
    $('#btnCompanyCancel')?.addEventListener('click', () => { state._companyEditing = false; renderPage(); });
    $('#btnCompanySave')?.addEventListener('click', saveCompanyProfile);
    $$('[data-type-add]').forEach(el => el.addEventListener('click', () =>
      openCrudModal(`${el.dataset.typeAdd}-type`)));
    $$('[data-type-edit]').forEach(el => el.addEventListener('click', () =>
      openCrudModal(`${el.dataset.typeEdit}-type`, el.dataset.id)));
    $$('[data-type-delete]').forEach(el => el.addEventListener('click', () =>
      deleteCatalogEntry(el.dataset.typeDelete, el.dataset.id, el.dataset.name)));
    if (state.currentPage === 'todo-lists') bindTodoEvents();
    if (state.currentPage === 'onboarding') bindOnboardingEvents();
    if (state.currentPage === 'documents') bindStorageEvents();
    $('#btnCreateRole')?.addEventListener('click', () => openRoleModal(null));
    $$('[data-role-edit]').forEach(el => el.addEventListener('click', () =>
      openRoleModal(el.dataset.roleEdit)));
    $$('[data-role-delete]').forEach(el => el.addEventListener('click', () =>
      deleteUserRole(el.dataset.roleDelete, el.dataset.name)));

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

    bindPasswordToggles();

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
          // Re-bind controls created by swapping the tab content.
          content.querySelectorAll('[data-action]').forEach(el => el.addEventListener('click', handleAction));
          const btnOT = $('#btnOpenTasks'); if (btnOT) btnOT.addEventListener('click', () => openCreateTaskModal(state.activeProjectId));
          const btnRT = $('#btnRefreshTasks'); if (btnRT) btnRT.addEventListener('click', async () => { await fetchProjectTasks(state.activeProjectId); const el = $('#projTasksList'); if (el) el.innerHTML = renderProjectTasksSection(); });
          const btnRS = $('#btnRefreshProjectSources'); if (btnRS) btnRS.addEventListener('click', async () => { await fetchProjectSources(state.activeProjectId); const el = $('#projectSourcesList'); if (el) { el.innerHTML = renderProjectSourcesSection(); el.querySelectorAll('[data-action]').forEach(node => node.addEventListener('click', handleAction)); } });
        } else {
          // People / Cost / Timeline / Procurement each load their own slice.
          loadProjectTab(newTab, p.id);
        }
      });
    });

    // Open Tasks button
    const btnOpenTasks = $('#btnOpenTasks');
    if (btnOpenTasks) btnOpenTasks.addEventListener('click', () => openCreateTaskModal(state.activeProjectId));
    // A task row on the project dashboard opens it in the Task Manager.
    $$('#projTasksList .task-row[data-task-id]').forEach(row => row.addEventListener('click', () => {
      openTaskInBoard(state.activeProjectId, row.dataset.taskId);
    }));

    // Refresh Tasks button
    const btnRefTasks = $('#btnRefreshTasks');
    if (btnRefTasks) btnRefTasks.addEventListener('click', async () => {
      await fetchProjectTasks(state.activeProjectId);
      const el = $('#projTasksList');
      if (el) el.innerHTML = renderProjectTasksSection();
    });

    // Refresh PDFs linked to the active project.
    const btnRefSources = $('#btnRefreshProjectSources');
    if (btnRefSources) btnRefSources.addEventListener('click', async () => {
      await fetchProjectSources(state.activeProjectId);
      const el = $('#projectSourcesList');
      if (el) {
        el.innerHTML = renderProjectSourcesSection();
        el.querySelectorAll('[data-action]').forEach(node => node.addEventListener('click', handleAction));
      }
    });

    Object.keys(WORKSPACE_PROVIDERS).forEach(bindWorkspaceEvents);
    if (state.currentPage === 'tasks') bindTasksPageEvents();
    if (state.currentPage === 'calendar') bindCalendarEvents();
  }

  function captureProviderEmailForm(providerId) {
    const P = providerId;
    const slice = ws(P);
    slice.emailDraft = {
      to: $(`#${P}EmailTo`)?.value.trim() || '',
      cc: $(`#${P}EmailCc`)?.value.trim() || '',
      subject: $(`#${P}EmailSubject`)?.value.trim() || '',
      body: $(`#${P}EmailBody`)?.value || '',
      instruction: $(`#${P}EmailInstruction`)?.value.trim() || '',
    };
    return { account_id: slice.accountId, ...slice.emailDraft };
  }

  function updateProviderSelectionButtons(providerId) {
    const slice = ws(providerId);
    const files = $(`#btn${cap(providerId)}DriveImport`);
    if (files) { files.disabled = !slice.selectedFiles.size; files.lastChild.textContent = `Index selected (${slice.selectedFiles.size})`; }
    const mail = $(`#btn${cap(providerId)}MailImport`);
    if (mail) { mail.disabled = !slice.selectedMessages.size; mail.textContent = `Index selected (${slice.selectedMessages.size})`; }
  }

  async function refreshProviderCalendar(providerId) {
    const slice = ws(providerId);
    const response = await apiReq(`${providerConfig(providerId).api}/calendar/events?account_id=${encodeURIComponent(slice.accountId)}`);
    slice.events = (await response.json()).events || [];
  }

  function bindWorkspaceEvents(providerId) {
    const cfg = providerConfig(providerId);
    const slice = ws(providerId);
    const P = providerId;
    const C = cap(P);

    const connect = $(`#btn${C}Connect`); if (connect) connect.addEventListener('click', () => connectProvider(P));
    const connectEmpty = $(`#btn${C}ConnectEmpty`); if (connectEmpty) connectEmpty.addEventListener('click', () => connectProvider(P));

    const accountSelect = $(`#${P}AccountSelect`);
    if (accountSelect) accountSelect.addEventListener('change', () => {
      slice.accountId = accountSelect.value;
      localStorage.setItem(accountScopedKey(`bmarshal_${P}_account`), slice.accountId);
      slice.files = []; slice.messages = []; slice.events = [];
      slice.selectedFiles.clear(); slice.selectedMessages.clear();
      renderPage();
    });

    const disconnect = $(`#btn${C}Disconnect`);
    if (disconnect) disconnect.addEventListener('click', async () => {
      if (!confirm(`Disconnect ${activeProviderAccount(P)?.email || `this ${cfg.label} account`}? Imported indexes will remain.`)) return;
      try {
        await apiReq(`${cfg.api}/accounts/${slice.accountId}`, { method: 'DELETE' });
        slice.accountId = '';
        localStorage.removeItem(accountScopedKey(`bmarshal_${P}_account`));
        await loadWorkspaceProvider(P);
        renderPage();
        showToast(`${cfg.label} account disconnected.`, 'success');
      } catch (error) { showToast(error.message, 'error'); }
    });

    $$(`[data-provider-tab][data-provider="${P}"]`).forEach(button => button.addEventListener('click', async () => {
      slice.tab = button.dataset.providerTab;
      renderPage();
      if (slice.tab === 'calendar' && slice.accountId && !slice.events.length) {
        try { await refreshProviderCalendar(P); renderPage(); } catch (e) { /* the refresh button retries */ }
      }
    }));

    // ── Files ──
    const fileChecks = $$(`.provider-file-check[data-provider="${P}"]`);
    fileChecks.forEach(check => check.addEventListener('change', () => {
      check.checked ? slice.selectedFiles.add(check.value) : slice.selectedFiles.delete(check.value);
      updateProviderSelectionButtons(P);
    }));
    const filesAll = $(`#${P}DriveAll`); if (filesAll) filesAll.addEventListener('change', () => {
      fileChecks.forEach(check => {
        check.checked = filesAll.checked;
        check.checked ? slice.selectedFiles.add(check.value) : slice.selectedFiles.delete(check.value);
      });
      updateProviderSelectionButtons(P);
    });
    const filesRefresh = $(`#btn${C}DriveRefresh`); if (filesRefresh) filesRefresh.addEventListener('click', async () => {
      try {
        filesRefresh.disabled = true;
        const query = $(`#${P}DriveSearch`)?.value.trim() || '';
        const response = await apiReq(`${cfg.api}/drive/files?account_id=${encodeURIComponent(slice.accountId)}&q=${encodeURIComponent(query)}`);
        slice.files = (await response.json()).files || [];
        renderPage();
      } catch (error) { showToast(error.message, 'error'); }
      finally { filesRefresh.disabled = false; }
    });
    const filesImport = $(`#btn${C}DriveImport`); if (filesImport) filesImport.addEventListener('click', async () => {
      const projectId = $(`#${P}DriveProject`)?.value || null;
      try {
        filesImport.disabled = true;
        const response = await apiReq(`${cfg.api}/drive/import`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_id: slice.accountId, item_ids: [...slice.selectedFiles], project_id: projectId })
        });
        const result = await response.json();
        slice.selectedFiles.clear();
        await fetchDocuments();
        if (projectId) await fetchProjectSources(projectId);
        renderPage();
        showToast(`Indexed ${result.total} file(s) from ${cfg.filesLabel}.${result.errors?.length ? ` ${result.errors.length} failed.` : ''}`, result.errors?.length ? 'warning' : 'success');
      } catch (error) { showToast(error.message, 'error'); }
      finally { filesImport.disabled = false; }
    });

    // ── Mail ──
    const messageChecks = $$(`.provider-message-check[data-provider="${P}"]`);
    messageChecks.forEach(check => check.addEventListener('change', () => {
      check.checked ? slice.selectedMessages.add(check.value) : slice.selectedMessages.delete(check.value);
      updateProviderSelectionButtons(P);
    }));
    const mailAll = $(`#${P}MailAll`); if (mailAll) mailAll.addEventListener('change', () => {
      messageChecks.forEach(check => {
        check.checked = mailAll.checked;
        check.checked ? slice.selectedMessages.add(check.value) : slice.selectedMessages.delete(check.value);
      });
      updateProviderSelectionButtons(P);
    });
    const mailRefresh = $(`#btn${C}MailRefresh`); if (mailRefresh) mailRefresh.addEventListener('click', async () => {
      try {
        mailRefresh.disabled = true;
        const query = $(`#${P}MailSearch`)?.value.trim() || '';
        const response = await apiReq(`${cfg.api}/${cfg.mailPath}/messages?account_id=${encodeURIComponent(slice.accountId)}&q=${encodeURIComponent(query)}`);
        slice.messages = (await response.json()).messages || [];
        renderPage();
      } catch (error) { showToast(error.message, 'error'); }
      finally { mailRefresh.disabled = false; }
    });
    const mailImport = $(`#btn${C}MailImport`); if (mailImport) mailImport.addEventListener('click', async () => {
      const projectId = $(`#${P}MailProject`)?.value || null;
      try {
        mailImport.disabled = true;
        const response = await apiReq(`${cfg.api}/${cfg.mailPath}/import`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_id: slice.accountId, item_ids: [...slice.selectedMessages], project_id: projectId })
        });
        const result = await response.json();
        slice.selectedMessages.clear();
        await fetchDocuments();
        if (projectId) await fetchProjectSources(projectId);
        renderPage();
        showToast(`Indexed ${result.total} email(s).${result.errors?.length ? ` ${result.errors.length} failed.` : ''}`, result.errors?.length ? 'warning' : 'success');
      } catch (error) { showToast(error.message, 'error'); }
      finally { mailImport.disabled = false; }
    });

    const emailGenerate = $(`#btn${C}EmailGenerate`); if (emailGenerate) emailGenerate.addEventListener('click', async () => {
      try {
        emailGenerate.disabled = true;
        const response = await apiReq(`${cfg.api}/${cfg.mailPath}/generate`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(captureProviderEmailForm(P))
        });
        const draft = await response.json();
        slice.emailDraft = { ...slice.emailDraft, subject: draft.subject || '', body: draft.body || '' };
        renderPage();
      } catch (error) { showToast(error.message, 'error'); }
      finally { emailGenerate.disabled = false; }
    });
    const emailDraft = $(`#btn${C}EmailDraft`); if (emailDraft) emailDraft.addEventListener('click', async () => {
      const body = captureProviderEmailForm(P);
      try {
        await apiReq(`${cfg.api}/${cfg.mailPath}/draft`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, confirm: true })
        });
        showToast(`Draft created in ${cfg.mailLabel}.`, 'success');
      } catch (error) { showToast(error.message, 'error'); }
    });
    const emailSend = $(`#btn${C}EmailSend`); if (emailSend) emailSend.addEventListener('click', async () => {
      const body = captureProviderEmailForm(P);
      if (!confirm(`Send this email now to ${body.to}? This action cannot be undone.`)) return;
      try {
        emailSend.disabled = true;
        await apiReq(`${cfg.api}/${cfg.mailPath}/send`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, confirm: true })
        });
        showToast('Email sent.', 'success');
      } catch (error) { showToast(error.message, 'error'); }
      finally { emailSend.disabled = false; }
    });

    // ── Calendar ──
    const calendarRefresh = $(`#btn${C}CalendarRefresh`); if (calendarRefresh) calendarRefresh.addEventListener('click', async () => {
      try {
        calendarRefresh.disabled = true;
        await refreshProviderCalendar(P);
        renderPage();
        showToast(`Loaded ${slice.events.length} calendar events.`, 'success');
      } catch (error) { showToast(error.message, 'error'); }
      finally { calendarRefresh.disabled = false; }
    });
    const taskProject = $(`#${P}TaskProject`); if (taskProject) taskProject.addEventListener('change', async () => {
      slice.taskProjectId = taskProject.value;
      if (slice.taskProjectId) await fetchProjectTasks(slice.taskProjectId); else state.projectTasks = [];
      renderPage();
    });
    const taskSelect = $(`#${P}TaskSelect`); if (taskSelect) taskSelect.addEventListener('change', () => {
      const task = state.projectTasks.find(item => String(item.id) === taskSelect.value);
      if (task) {
        $(`#${P}EventSummary`).value = task.name || task.title || '';
        $(`#${P}EventDescription`).value = task.description || '';
      }
    });
    const calendarCreate = $(`#btn${C}CalendarCreate`); if (calendarCreate) calendarCreate.addEventListener('click', async () => {
      const summary = $(`#${P}EventSummary`)?.value.trim() || '';
      const start = $(`#${P}EventStart`)?.value; const end = $(`#${P}EventEnd`)?.value;
      if (!summary || !start || !end) { showToast('Event title, start, and end are required.', 'warning'); return; }
      const payload = {
        account_id: slice.accountId, summary,
        description: $(`#${P}EventDescription`)?.value.trim() || '',
        start: new Date(start).toISOString(), end: new Date(end).toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        attendees: ($(`#${P}EventAttendees`)?.value || '').split(',').map(v => v.trim()).filter(Boolean),
        add_meet: Boolean($(`#${P}EventMeet`)?.checked),
        confirm: true
      };
      if (!confirm(`Add “${summary}” to ${cfg.calendarLabel}?`)) return;
      try {
        const response = await apiReq(`${cfg.api}/calendar/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const created = await response.json();
        showToast(created.meet_link ? 'Calendar event created with a Meet link.' : 'Calendar event created.', 'success');
        calendarRefresh?.click();
      } catch (error) { showToast(error.message, 'error'); }
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
      try {
        await apiReq(`/api/documents/${id}`, { method: 'DELETE' });
        await fetchDocuments();
        if (state.activeProjectId) await fetchProjectSources(state.activeProjectId);
        renderPage();
        showToast('Document deleted', 'info');
      } catch (e) { showToast(e.message, 'error'); }
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
      resetProjectTabData(id);
      await Promise.all([fetchProjectTasks(id), fetchProjectSources(id)]);
      navigateTo('project-details');
    }
    else if (action === 'edit-project') {
      openProjectModal(id);
    }
    else if (action === 'delete-project') {
      if (!confirm('Permanently delete this project and all its tasks?')) return;
      try {
        await apiReq(`/api/projects/${id}`, { method: 'DELETE' });
        if (state.activeProjectId === id) { state.activeProjectId = null; state.projectTasks = []; state.projectSources = []; }
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
    else if (action === 'generate-report') {
      openDocumentGenerationModal(id);
    }
    else if (action === 'project-report') {
      const project = state.projects.find(row => row.id === id);
      if (project) openReportModal(project);
    }
    else if (action === 'upload-project-sources') {
      openUploadPanel(id);
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

  // ═══ Authenticated media ═══
  //
  // Page images, audio, and video come from account-scoped endpoints that
  // require a bearer token, and a browser will not attach one to an <img>,
  // <audio>, or <video> src.  Markup therefore carries `data-authsrc`, and
  // these helpers fetch the bytes through apiReq and swap in an object URL.
  // Object URLs are tracked so closing a modal releases the memory.

  const objectUrls = new Set();

  function releaseObjectUrls(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-object-url]').forEach(el => {
      const url = el.dataset.objectUrl;
      if (objectUrls.has(url)) { URL.revokeObjectURL(url); objectUrls.delete(url); }
      delete el.dataset.objectUrl;
    });
    if (!root) { objectUrls.forEach(url => URL.revokeObjectURL(url)); objectUrls.clear(); }
  }

  async function loadAuthedMedia(el) {
    const endpoint = el.dataset.authsrc;
    if (!endpoint || el.dataset.authState) return;
    el.dataset.authState = 'loading';
    try {
      const res = await apiReq(endpoint);
      const url = URL.createObjectURL(await res.blob());
      objectUrls.add(url);
      el.dataset.objectUrl = url;
      el.dataset.authState = 'loaded';
      if (el.tagName === 'SOURCE') { el.src = url; el.parentElement?.load(); }
      else el.src = url;
    } catch (e) {
      el.dataset.authState = 'error';
      const fallback = el.dataset.authFallback;
      const holder = el.closest('.preview-page, .preview-image-container, .evidence-page-figure') || el.parentElement;
      if (holder) holder.innerHTML = `<div class="preview-error">${esc(fallback || 'Preview unavailable')}</div>`;
    }
  }

  function hydrateAuthedMedia(root) {
    const targets = Array.from((root || document).querySelectorAll('[data-authsrc]'));
    if (!targets.length) return;
    // A long PDF should not fetch every page at once; load them as they scroll
    // into view where the browser supports it.
    if (targets.length > 3 && 'IntersectionObserver' in window) {
      const observer = new IntersectionObserver((entries, obs) => {
        entries.filter(entry => entry.isIntersecting).forEach(entry => {
          obs.unobserve(entry.target);
          loadAuthedMedia(entry.target);
        });
      }, { root: root || null, rootMargin: '400px' });
      targets.forEach(el => observer.observe(el));
      return;
    }
    targets.forEach(loadAuthedMedia);
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
      DOM.docPreviewBody.innerHTML = `<div class="preview-pages" id="previewPages" >
    <div class="preview-loading"><div class="typing-indicator"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div><p>Loading preview...</p></div>
      </div> `;
      // Load page images
      try {
        const meta = state.uploadedDocs.find(d => d.id === docId);
        // Backend returns page_count; uploadFiles stores it as doc.pages — normalise both
        const pageCount = meta?.page_count || meta?.pages || 1;
        let pagesHtml = '';
        for (let i = 1; i <= Math.min(pageCount, 10); i++) {
          pagesHtml += `<div class="preview-page" > <img data-authsrc="/api/pages/${encodeURIComponent(docId)}/${i}" data-auth-fallback="Page ${i} unavailable" alt="Page ${i}"><div class="preview-page-label">Page ${i} of ${pageCount}</div></div>`;
        }
        if (pageCount > 10) pagesHtml += `<div class="preview-more" > Showing first 10 of ${pageCount} pages</div> `;
        const container = document.getElementById('previewPages');
        if (container) { container.innerHTML = pagesHtml; hydrateAuthedMedia(container); }
      } catch (e) {
        const container = document.getElementById('previewPages');
        if (container) container.innerHTML = `<div class="preview-error" > Could not load preview: ${esc(e.message)}</div> `;
      }
    }
    else if (isImage(ext)) {
      DOM.docPreviewBody.innerHTML = `<div class="preview-image-container" > <img data-authsrc="/api/pages/${encodeURIComponent(docId)}/1" data-auth-fallback="Preview unavailable" alt="${esc(name)}"></div>`;
      hydrateAuthedMedia(DOM.docPreviewBody);
    }
    else if (isAudio(ext)) {
      // Map ext → correct MIME type for <source type="">
      const audioMime = { mp3: 'audio/mpeg', wav: 'audio/wav', ogg: 'audio/ogg', m4a: 'audio/mp4', flac: 'audio/flac', aac: 'audio/aac', wma: 'audio/x-ms-wma', opus: 'audio/ogg; codecs=opus' };
      DOM.docPreviewBody.innerHTML = `<div class="preview-audio-container" >
        <div class="audio-visual"><span class="material-icons-outlined" style="font-size:64px;color:var(--brand-blue)">graphic_eq</span></div>
        <audio controls preload="metadata" style="width:100%"><source data-authsrc="/api/pages/${encodeURIComponent(docId)}/1" type="${audioMime[ext] || 'audio/' + ext}">Your browser doesn't support audio.</audio>
        <p class="preview-filename">${esc(name)}</p>
      </div> `;
      hydrateAuthedMedia(DOM.docPreviewBody);
    }
    else if (isVideo(ext)) {
      const videoMime = { mp4: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime', avi: 'video/x-msvideo', mkv: 'video/x-matroska' };
      DOM.docPreviewBody.innerHTML = `<div class="preview-video-container" > <video controls preload="metadata" style="width:100%;max-height:60vh;border-radius:8px"><source data-authsrc="/api/pages/${encodeURIComponent(docId)}/1" type="${videoMime[ext] || 'video/' + ext}">Your browser doesn't support video.</video></div> `;
      hydrateAuthedMedia(DOM.docPreviewBody);
    }
    else if (isText(ext)) {
      // Text files: fetch content from page 1 image path, but since backend renders
      // text files as PNG screenshots, display as an image the same way
      DOM.docPreviewBody.innerHTML = `<div class="preview-image-container" > <img data-authsrc="/api/pages/${encodeURIComponent(docId)}/1" data-auth-fallback="Preview unavailable for this file" alt="${esc(name)}" style="max-width:100%"></div>`;
      hydrateAuthedMedia(DOM.docPreviewBody);
    }
    else {
      DOM.docPreviewBody.innerHTML = `<div class="preview-generic" ><span class="material-icons-outlined" style="font-size:48px;color:var(--text-muted)">description</span><p>Preview not available for .${ext} files</p><p class="preview-hint">This file has been indexed and can be queried via Marshal Chat.</p></div> `;
    }
  }
  function closeDocPreview() {
    DOM.docPreviewModal.classList.remove('open');
    releaseObjectUrls(DOM.docPreviewBody);
    DOM.docPreviewBody.innerHTML = '';
  }

  // ═══ CRUD Modal ═══
  let crudCallback = null;
  function openCrudModal(type, editId, defaultCat) {
    const isEdit = !!editId;
    DOM.crudModalTitle.textContent = isEdit ? `Edit ${type} ` : `Create ${type} `;
    let fields = '';
    if (type === 'trade') {
      const item = isEdit ? state.trades.find(t => t.id === editId) : { name: '', description: '', status: 'Active' };
      if (!item) return;
      fields = `<div class="form-group" ><label class="form-label">Name</label><input class="form-input" id="crudName" value="${esc(item.name)}"></div>
        <div class="form-group"><label class="form-label">Description</label><input class="form-input" id="crudDesc" value="${esc(item.description)}"></div>
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="crudStatus"><option value="Active" ${item.status === 'Active' ? 'selected' : ''}>Active</option><option value="Inactive" ${item.status === 'Inactive' ? 'selected' : ''}>Inactive</option></select></div>`;
      crudCallback = async () => {
        const payload = { name: $('#crudName').value.trim(), description: $('#crudDesc').value.trim() || '-', status: $('#crudStatus').value };
        if (!payload.name) { showToast('Name is required', 'warning'); return false; }
        try {
          if (isEdit) await apiReq(`/api/trades/${editId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          else await apiReq('/api/trades', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          await fetchTrades(); return true;
        } catch (e) { showToast(e.message, 'error'); return false; }
      };
    } else if (type === 'vendor') {
      const item = isEdit ? state.vendors.find(v => v.id === editId) : { name: '', vendorType: 'Material Supplier', trade: '', status: 'Active' };
      if (!item) return;
      fields = `<div class="form-group" ><label class="form-label">Vendor Name</label><input class="form-input" id="crudName" value="${esc(item.name)}"></div>
        <div class="form-group"><label class="form-label">Vendor Type</label><select class="form-input" id="crudType"><option value="Material Supplier" ${item.vendorType === 'Material Supplier' ? 'selected' : ''}>Material Supplier</option><option value="Subcontractor" ${item.vendorType === 'Subcontractor' ? 'selected' : ''}>Subcontractor</option></select></div>
        <div class="form-group"><label class="form-label">Trade</label><select class="form-input" id="crudTrade"><option value="">Select trade...</option>${state.trades.map(t => `<option value="${esc(t.name)}" ${item.trade === t.name ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></div>
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="crudStatus"><option value="Active" ${item.status === 'Active' ? 'selected' : ''}>Active</option><option value="Inactive" ${item.status === 'Inactive' ? 'selected' : ''}>Inactive</option></select></div>`;
      crudCallback = async () => {
        const payload = { name: $('#crudName').value.trim(), vendorType: $('#crudType').value, trade: $('#crudTrade').value, status: $('#crudStatus').value };
        if (!payload.name) { showToast('Name is required', 'warning'); return false; }
        try {
          if (isEdit) await apiReq(`/api/vendors/${editId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          else await apiReq('/api/vendors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          await fetchVendors(); return true;
        } catch (e) { showToast(e.message, 'error'); return false; }
      };
    } else if (type === 'task-type' || type === 'project-type') {
      const kind = type === 'task-type' ? 'task' : 'project';
      const cfg = TYPE_CATALOGS[kind];
      const item = isEdit
        ? (state[cfg.listKey] || []).find(entry => entry.id === editId)
        : { name: '', description: '', status: 'Active' };
      if (!item) return;
      DOM.crudModalTitle.textContent = `${isEdit ? 'Edit' : 'Add'} ${cfg.noun}`;
      fields = `<div class="form-group"><label class="form-label required-label">Name</label>
          <input class="form-input" id="crudName" value="${esc(item.name)}" placeholder="e.g. Handover"></div>
        <div class="form-group"><label class="form-label">Description</label>
          <input class="form-input" id="crudDesc" value="${esc(item.description === '-' ? '' : item.description || '')}"></div>
        <div class="form-group"><label class="form-label">Status</label>
          <select class="form-input" id="crudStatus">
            <option value="Active" ${item.status !== 'Inactive' ? 'selected' : ''}>Active</option>
            <option value="Inactive" ${item.status === 'Inactive' ? 'selected' : ''}>Inactive</option>
          </select></div>`;
      crudCallback = async () => {
        const name = $('#crudName').value.trim();
        if (!name) { showToast('Name is required', 'warning'); return false; }
        const payload = { name, description: $('#crudDesc').value.trim() || '-', status: $('#crudStatus').value };
        try {
          const path = `/api/${cfg.segment}${isEdit ? `/${encodeURIComponent(editId)}` : ''}`;
          await apiReq(path, {
            method: isEdit ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
          });
          await refreshCatalog(kind);
          return true;  // the shared save handler reports success
        } catch (error) {
          // A duplicate name, or a member without permission, lands here.
          showToast(error.message, 'error', 8000);
          return false;
        }
      };
    }
    else if (type === 'team-member') {
      const item = editId ? state.teamMembers.find(m => m.id === editId) : { name: '', email: '', department: '', category: defaultCat || 'internal', company: '', contactName: '' };
      if (!item) return;
      const isVendorCat = (item.category === 'vendor');
      fields = `<div class="form-group" ><label class="form-label">Name</label><input class="form-input" id="crudName" value="${esc(item.name)}"></div>
        <div class="form-group"><label class="form-label">Email</label><input class="form-input" type="email" id="crudEmail" value="${esc(item.email || '')}"></div>
        <div class="form-group"><label class="form-label">Category</label><select class="form-input" id="crudCat"><option value="internal" ${item.category === 'internal' ? 'selected' : ''}>Internal Team</option><option value="contractor" ${item.category === 'contractor' ? 'selected' : ''}>Subcontractor</option><option value="consultant" ${item.category === 'consultant' ? 'selected' : ''}>Consultant</option><option value="vendor" ${item.category === 'vendor' ? 'selected' : ''}>Vendor / Supplier</option></select></div>
        <div class="form-group"><label class="form-label">Department</label><input class="form-input" id="crudDept" value="${esc(item.department || '')}"></div>
        <div class="form-group"><label class="form-label">Company</label><input class="form-input" id="crudCompany" value="${esc(item.company || '')}"></div>
        <div class="form-group"><label class="form-label">Contact Name</label><input class="form-input" id="crudContact" value="${esc(item.contactName || '')}"></div>`;
      crudCallback = async () => {
        const payload = { name: $('#crudName').value.trim(), email: $('#crudEmail').value.trim(), category: $('#crudCat').value, department: $('#crudDept').value.trim() || '—', company: $('#crudCompany').value.trim(), contactName: $('#crudContact').value.trim() };
        if (!payload.name) { showToast('Name is required', 'warning'); return false; }
        try {
          if (editId) await apiReq(`/api/team-members/${editId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          else await apiReq('/api/team-members', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          await fetchTeamMembers(); return true;
        } catch (e) { showToast(e.message, 'error'); return false; }
      };
    }
    DOM.crudModalBody.innerHTML = fields;
    DOM.crudModal.classList.add('open');
  }
  function closeCrudModal() {
    DOM.crudModal.classList.remove('open'); crudCallback = null;
    // The report dialog hides Save; every other user of this modal needs it.
    DOM.btnSaveCrud.hidden = false;
    DOM.btnSaveCrud.textContent = 'Save';
    DOM.btnSaveCrud.disabled = false;
    delete DOM.btnSaveCrud.dataset.crudAction;
    delete DOM.btnSaveCrud.dataset.crudId;
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Project Onboarding

     Read an existing project out of the documents it already has, correct
     what the AI got wrong, choose what is real, and only then create it.

     Everything before the final confirmation is a draft on the server; this
     module never writes a project, task, user, type, or role directly.
     ═══════════════════════════════════════════════════════════════════════ */

  /* The entity definitions come from the server, so the mandatory fields this
     page enforces are the ones the server enforces. Nothing about what a
     project or a task is lives in this file. */
  const ONBOARDING_ICONS = {
    project: 'folder', task: 'task_alt', user: 'person',
    task_type: 'label', project_type: 'category', role_type: 'badge',
    trade: 'handyman', vendor: 'store',
    project_cost: 'payments', task_cost: 'request_quote', procurement: 'local_shipping'
  };

  function onboardingSchema() {
    return onboarding().schema;
  }

  function entitySpec(kind) {
    return (onboardingSchema()?.byKind || {})[kind] || null;
  }

  function onboardingKinds() {
    return onboardingSchema()?.order || [];
  }

  function kindLabel(kind, plural = false) {
    const spec = entitySpec(kind);
    if (!spec) return kind;
    return plural ? spec.plural : spec.label;
  }

  function kindIcon(kind) {
    return ONBOARDING_ICONS[kind] || 'inventory_2';
  }

  function onboarding() {
    if (!state.onboarding) {
      state.onboarding = {
        loaded: false, loading: false, drafts: [],
        draft: null, step: 1,
        // The entity definitions and the live records a reference field
        // may point at, both served by /api/onboarding/schema.
        schema: null, schemaLoading: false,
        instructions: '', pendingFiles: [], uploading: false, analyzing: false,
        plan: null, planLoading: false, result: null, committing: false,
        commandBusy: false, commandLog: [], collapsed: {}, busyItem: ''
      };
    }
    return state.onboarding;
  }

  function onboardingItems(kind) {
    const draft = onboarding().draft;
    if (!draft) return [];
    return draft.items.filter(item => !kind || item.kind === kind);
  }

  function onboardingItem(itemId) {
    return (onboarding().draft?.items || []).find(item => item.id === itemId) || null;
  }

  // ── Server calls ────────────────────────────────────────────────────────

  async function onboardingJson(path, options) {
    const response = await apiReq(`/api/onboarding${path}`, options);
    return response.json();
  }

  function onboardingBody(payload) {
    return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) };
  }

  function adoptDraft(view) {
    const slice = onboarding();
    slice.draft = view;
    // Any plan or result on screen described the draft as it was.
    slice.plan = null;
    return view;
  }

  /**
   * Load the entity definitions and the records a reference field can name.
   *
   * Re-read after a commit, because what was just created is now something
   * the next draft can point at.
   */
  async function fetchOnboardingSchema() {
    const slice = onboarding();
    if (slice.schemaLoading) return;
    slice.schemaLoading = true;
    try {
      const data = await onboardingJson('/schema');
      slice.schema = {
        entities: data.entities || [],
        order: (data.entities || []).map(row => row.kind),
        byKind: Object.fromEntries((data.entities || []).map(row => [row.kind, row])),
        choices: data.choices || {},
        permissions: data.permissions || []
      };
    } catch (error) {
      showToast(`Could not load the entity definitions: ${error.message}`, 'error', 7000);
    } finally {
      slice.schemaLoading = false;
    }
  }

  async function fetchOnboardingDrafts() {
    const slice = onboarding();
    slice.loading = true;
    try {
      const data = await onboardingJson('/drafts');
      slice.drafts = data.drafts || [];
      slice.loaded = true;
    } catch (error) {
      slice.drafts = [];
      slice.loaded = true;
      showToast(error.message, 'error');
    } finally {
      slice.loading = false;
    }
  }

  async function createOnboardingDraft() {
    const name = (prompt('Name this onboarding, so you can come back to it:', 'Project onboarding') || '').trim();
    if (!name) return;
    try {
      const slice = onboarding();
      if (!slice.schema) await fetchOnboardingSchema();
      const view = await onboardingJson('/drafts', onboardingBody({ name }));
      adoptDraft(view);
      slice.step = 1;
      slice.result = null;
      slice.commandLog = [];
      await fetchOnboardingDrafts();
      renderPage();
    } catch (error) { showToast(error.message, 'error'); }
  }

  async function openOnboardingDraft(draftId) {
    const slice = onboarding();
    if (!slice.schema) await fetchOnboardingSchema();
    try {
      const view = await onboardingJson(`/drafts/${draftId}`);
      adoptDraft(view);
      slice.result = view.status === 'committed' ? view.commit : null;
      slice.commandLog = [];
      slice.step = view.status === 'committed' ? 3 : (view.summary.total ? 2 : 1);
      renderPage();
    } catch (error) { showToast(error.message, 'error'); }
  }

  async function deleteOnboardingDraft(draftId, name) {
    if (!confirm(`Delete the draft “${name}”? Nothing that was already onboarded is affected.`)) return;
    try {
      await onboardingJson(`/drafts/${draftId}`, { method: 'DELETE' });
      const slice = onboarding();
      if (slice.draft?.id === draftId) slice.draft = null;
      await fetchOnboardingDrafts();
      renderPage();
      showToast('Draft deleted', 'success');
    } catch (error) { showToast(error.message, 'error'); }
  }

  async function uploadOnboardingFiles(files) {
    const slice = onboarding();
    const draft = slice.draft;
    if (!draft || !files.length) return;
    slice.uploading = true;
    renderPage();
    let uploaded = 0;
    for (const file of files) {
      try {
        const form = new FormData();
        form.append('file', file);
        form.append('doc_id', genId());
        await apiReq(`/api/onboarding/drafts/${draft.id}/documents`, { method: 'POST', body: form });
        uploaded += 1;
      } catch (error) {
        showToast(`${file.name}: ${error.message}`, 'error', 6000);
      }
    }
    slice.uploading = false;
    try { adoptDraft(await onboardingJson(`/drafts/${draft.id}`)); } catch (error) { /* keep what we have */ }
    if (uploaded) showToast(`Indexed ${uploaded} document${uploaded === 1 ? '' : 's'}`, 'success');
    fetchDocuments();
    renderPage();
  }

  async function detachOnboardingDocument(docId) {
    const draft = onboarding().draft;
    if (!draft) return;
    try {
      adoptDraft(await onboardingJson(`/drafts/${draft.id}/documents/${docId}`, { method: 'DELETE' }));
      renderPage();
    } catch (error) { showToast(error.message, 'error'); }
  }

  async function analyzeOnboardingDraft() {
    const slice = onboarding();
    const draft = slice.draft;
    if (!draft || !draft.documents.length) return;
    slice.analyzing = true;
    renderPage();
    try {
      const view = await onboardingJson(`/drafts/${draft.id}/analyze`,
        onboardingBody({ instructions: slice.instructions }));
      adoptDraft(view);
      slice.step = 2;
      const warnings = view.analysis?.warnings || [];
      warnings.forEach(warning => showToast(warning, 'warning', 7000));
      showToast(`Marshal drafted ${view.summary.total} item${view.summary.total === 1 ? '' : 's'}. Nothing has been created yet.`,
        'success', 6000);
    } catch (error) {
      showToast(error.message, 'error', 7000);
    } finally {
      slice.analyzing = false;
      renderPage();
    }
  }

  async function saveOnboardingItem(itemId, payload) {
    const draft = onboarding().draft;
    if (!draft) return null;
    const view = itemId
      ? await onboardingJson(`/drafts/${draft.id}/items/${itemId}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        })
      : await onboardingJson(`/drafts/${draft.id}/items`, onboardingBody(payload));
    adoptDraft(view);
    return view;
  }

  async function deleteOnboardingItem(itemId) {
    const draft = onboarding().draft;
    const item = onboardingItem(itemId);
    if (!draft || !item) return;
    const dependents = item.dependents.length;
    const label = kindLabel(item.kind).toLowerCase();
    const extra = dependents ? ` and ${dependents} item${dependents === 1 ? '' : 's'} under it` : '';
    if (!confirm(`Remove the ${label} “${item.fields.name}”${extra} from the draft?`)) return;
    try {
      adoptDraft(await onboardingJson(`/drafts/${draft.id}/items/${itemId}`, { method: 'DELETE' }));
      renderPage();
    } catch (error) { showToast(error.message, 'error'); }
  }

  /**
   * Send a new selection.
   *
   * Ticking a subtask needs its parent chain, and the server closes over that
   * and says what it added. Unticking a parent is closed here first, so the
   * page never shows a child ticked under an unticked parent even for a frame.
   */
  async function setOnboardingSelection(nextSelection) {
    const slice = onboarding();
    const draft = slice.draft;
    if (!draft) return;
    try {
      const view = await onboardingJson(`/drafts/${draft.id}/selection`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selection: nextSelection })
      });
      const added = view.added_parents || [];
      adoptDraft(view);
      renderPage();
      if (added.length) {
        const names = added.map(id => onboardingItem(id)?.fields.name).filter(Boolean);
        showToast(`Also selected ${names.join(', ')} — a task cannot be created without them.`, 'info', 6000);
      }
    } catch (error) { showToast(error.message, 'error'); }
  }

  function toggleOnboardingItem(itemId, wanted) {
    const item = onboardingItem(itemId);
    if (!item) return;
    const selected = new Set(onboardingItems().filter(row => row.selected).map(row => row.id));
    if (wanted) {
      selected.add(itemId);
    } else {
      selected.delete(itemId);
      // Everything that depends on it has to come off with it.
      item.dependents.forEach(id => selected.delete(id));
    }
    setOnboardingSelection([...selected]);
  }

  function selectAllOnboarding(kind, wanted) {
    const selected = new Set(onboardingItems().filter(row => row.selected).map(row => row.id));
    onboardingItems(kind).forEach(item => {
      if (wanted) selected.add(item.id);
      else {
        selected.delete(item.id);
        item.dependents.forEach(id => selected.delete(id));
      }
    });
    setOnboardingSelection([...selected]);
  }

  async function sendOnboardingCommand() {
    const slice = onboarding();
    const input = $('#onbCommandInput');
    const text = (input?.value || '').trim();
    if (!slice.draft || !text || slice.commandBusy) return;
    slice.commandBusy = true;
    slice.commandLog.push({ role: 'user', text });
    renderPage();
    try {
      const view = await onboardingJson(`/drafts/${slice.draft.id}/command`, onboardingBody({ text }));
      adoptDraft(view);
      slice.commandLog.push({
        role: 'bot', text: view.reply,
        applied: view.applied || [], skipped: view.skipped || []
      });
    } catch (error) {
      slice.commandLog.push({ role: 'bot', text: `Could not apply that: ${error.message}` });
    } finally {
      slice.commandBusy = false;
      renderPage();
      const log = $('#onbCommandLog');
      if (log) log.scrollTop = log.scrollHeight;
      $('#onbCommandInput')?.focus();
    }
  }

  async function loadOnboardingPlan() {
    const slice = onboarding();
    if (!slice.draft) return;
    slice.planLoading = true;
    renderPage();
    try {
      slice.plan = await onboardingJson(`/drafts/${slice.draft.id}/plan`);
    } catch (error) {
      slice.plan = null;
      showToast(error.message, 'error');
    } finally {
      slice.planLoading = false;
      renderPage();
    }
  }

  async function commitOnboardingDraft() {
    const slice = onboarding();
    const draft = slice.draft;
    const plan = slice.plan;
    if (!draft || !plan || slice.committing) return;
    const creating = plan.total_creating;
    if (!creating && !plan.total_reusing) return;
    if (!confirm(`Create ${creating} record${creating === 1 ? '' : 's'} in this workspace now? This cannot be undone from here.`)) return;

    slice.committing = true;
    renderPage();
    try {
      const result = await onboardingJson(`/drafts/${draft.id}/commit`, onboardingBody({ confirm: true }));
      slice.result = result;
      slice.draft = result.draft || slice.draft;
      showToast(`Onboarded ${result.total_created} record${result.total_created === 1 ? '' : 's'}`, 'success', 6000);
      await Promise.all([fetchProjects(), fetchUsers(), fetchTaskTypes(), fetchProjectTypes(),
                         fetchUserRoles(), fetchTrades(), fetchVendors()]);
      // What was just created is now something the next draft can point at.
      await Promise.all([fetchOnboardingSchema(), fetchOnboardingDrafts()]);
    } catch (error) {
      showToast(error.message, 'error', 8000);
    } finally {
      slice.committing = false;
      renderPage();
    }
  }

  // ── Rendering ───────────────────────────────────────────────────────────

  // ── Rendering ───────────────────────────────────────────────────────────

  function onboardingChip(text, tone = '') {
    return `<span class="onb-chip ${tone}">${esc(text)}</span>`;
  }

  function onboardingMoney(value) {
    if (value === '' || value === null || value === undefined) return '';
    const amount = Number(value);
    return Number.isFinite(amount) ? amount.toLocaleString() : String(value);
  }

  /** The few chips worth showing on a row, chosen from the entity's own fields. */
  function onboardingItemMeta(item) {
    const spec = entitySpec(item.kind);
    const fields = item.fields || {};
    const chips = [];
    if (item.kind === 'task_cost' || item.kind === 'project_cost') {
      // A task cost has no name of its own, so the row title is already the
      // figure; repeating it as a chip would say the same thing twice.
      if (fields.name) chips.push(onboardingChip(onboardingMoney(fields.amount), 'money'));
      if (fields.details) chips.push(onboardingChip(fields.details));
    } else if (item.kind === 'user') {
      chips.push(fields.email ? onboardingChip(fields.email) : '');
      if (fields.role) chips.push(onboardingChip(fields.role));
      if (fields.department) chips.push(onboardingChip(fields.department));
    } else if (item.kind === 'role_type') {
      const count = (fields.permissions || []).length;
      chips.push(onboardingChip(`${count} permission${count === 1 ? '' : 's'}`, count ? '' : 'warn'));
    } else if (spec) {
      // Everything else: the first few filled fields that are not the name.
      spec.fields.filter(field => field.name !== 'name' && field.name !== 'description')
        .forEach(field => {
          const value = fields[field.name];
          if (value === '' || value === null || value === undefined) return;
          if (chips.length >= 4) return;
          chips.push(onboardingChip(field.type === 'money' ? onboardingMoney(value) : value));
        });
    }
    if (item.source?.doc_name) chips.push(onboardingChip(`from ${item.source.doc_name}`, 'muted'));
    if (item.origin === 'manual') chips.push(onboardingChip('added by you', 'muted'));
    return chips.filter(Boolean).join('');
  }

  function renderOnboardingRow(item, depth = 0) {
    const blocked = (item.blocked_by || []).length > 0;
    const blockedNames = (item.blocked_by || [])
      .map(id => onboardingItem(id)?.fields.name).filter(Boolean).join(', ');
    const name = item.fields.name || (item.kind === 'task_cost'
      ? onboardingMoney(item.fields.amount) : '(unnamed)');
    const missing = item.missing || [];
    return `<div class="onb-row ${item.selected ? 'is-selected' : ''} ${item.complete ? '' : 'is-incomplete'}"
        data-item-row="${esc(item.id)}" style="--onb-depth:${depth}">
      <label class="onb-check-wrap" title="${item.selected ? 'Selected for onboarding' : 'Not selected'}">
        <input type="checkbox" class="onb-check" data-onb-toggle="${esc(item.id)}" ${item.selected ? 'checked' : ''}>
      </label>
      <span class="material-icons-outlined onb-row-icon" aria-hidden="true">${kindIcon(item.kind)}</span>
      <div class="onb-row-main">
        <div class="onb-row-name">
          ${esc(name)}
          ${item.complete ? '' : '<span class="onb-flag">⚠ Incomplete</span>'}
        </div>
        <div class="onb-row-meta">${onboardingItemMeta(item)}</div>
        ${missing.length ? `<div class="onb-row-missing">
          Missing required field${missing.length === 1 ? '' : 's'}:
          ${missing.map(field => `<button class="onb-missing-chip" data-onb-edit="${esc(item.id)}"
              data-onb-focus="${esc(field.name)}">${esc(field.label)}</button>`).join('')}
        </div>` : ''}
        ${(item.issues || []).length ? `<div class="onb-row-issue">${item.issues.map(esc).join(' · ')}</div>` : ''}
        ${blocked && !item.selected ? `<div class="onb-row-note">Selecting this also selects ${esc(blockedNames)}</div>` : ''}
      </div>
      <div class="onb-row-actions">
        ${onboardingChildActions(item)}
        <button class="btn-table-action" data-onb-edit="${esc(item.id)}" title="Edit"><span class="material-icons-outlined">edit</span></button>
        <button class="btn-table-action delete" data-onb-delete="${esc(item.id)}" title="Remove from draft"><span class="material-icons-outlined">delete</span></button>
      </div>
    </div>`;
  }

  /** "Add a child" buttons for whatever this kind can be a parent of. */
  function onboardingChildActions(item) {
    const children = onboardingKinds().filter(kind => entitySpec(kind)?.parent === item.kind);
    const buttons = children.map(kind => `<button class="btn-table-action"
      data-onb-add-child="${kind}" data-onb-parent="${esc(item.id)}"
      title="Add a ${kindLabel(kind).toLowerCase()}"><span class="material-icons-outlined">${kindIcon(kind)}</span></button>`);
    if (entitySpec(item.kind)?.self_parent) {
      buttons.unshift(`<button class="btn-table-action" data-onb-add-nested="${esc(item.id)}"
        title="Add a sub${kindLabel(item.kind).toLowerCase()}"><span class="material-icons-outlined">subdirectory_arrow_right</span></button>`);
    }
    return buttons.join('');
  }

  /** Everything hanging off one item, recursively: the draft's hierarchy. */
  function renderOnboardingChildren(parentId, depth) {
    const items = onboardingItems();
    const children = items.filter(row => row.parent_ref === parentId);
    // Nested children of the same kind are drawn by their own parent, not here.
    return children.filter(row => !row.parent_id).map(row =>
      renderOnboardingRow(row, depth)
      + renderOnboardingNested(row, depth + 1)
      + renderOnboardingChildren(row.id, depth + 1)).join('');
  }

  function renderOnboardingNested(item, depth) {
    if (!entitySpec(item.kind)?.self_parent) return '';
    return onboardingItems(item.kind)
      .filter(row => row.parent_id === item.id)
      .map(row => renderOnboardingRow(row, depth)
        + renderOnboardingNested(row, depth + 1)
        + renderOnboardingChildren(row.id, depth + 1)).join('');
  }

  function renderOnboardingProjectTree(project) {
    const people = onboardingItems('user').filter(user => (user.project_refs || []).includes(project.id));
    return `${renderOnboardingRow(project, 0)}
      ${renderOnboardingChildren(project.id, 1)}
      ${people.length ? `<div class="onb-subhead" style="--onb-depth:1">People on this project</div>${people.map(user => renderOnboardingRow(user, 1)).join('')}` : ''}`;
  }

  function renderOnboardingGroup(kind) {
    const slice = onboarding();
    const spec = entitySpec(kind);
    const items = onboardingItems(kind);
    if (!items.length || !spec) return '';
    const selected = items.filter(item => item.selected).length;
    const incomplete = items.filter(item => !item.complete).length;
    const collapsed = !!slice.collapsed[kind];

    let body = '';
    let heading = spec.plural;
    if (kind === 'project') {
      body = items.map(renderOnboardingProjectTree).join('');
    } else if (spec.parent) {
      // Drawn inside their parent; only orphans need a section of their own.
      const loose = items.filter(item => !onboardingItem(item.parent_ref));
      if (!loose.length) return '';
      heading = `${spec.plural} with no ${spec.parent_label.toLowerCase()} yet`;
      body = loose.map(item => renderOnboardingRow(item, 0)).join('');
    } else if (kind === 'user') {
      const loose = items.filter(item => !(item.project_refs || []).some(ref => onboardingItem(ref)));
      if (!loose.length) return '';
      heading = 'People not tied to a project';
      body = loose.map(item => renderOnboardingRow(item, 0)).join('');
    } else {
      body = items.map(item => renderOnboardingRow(item, 0)).join('');
    }
    if (!body) return '';

    return `<section class="onb-group ${collapsed ? 'is-collapsed' : ''}">
      <header class="onb-group-head">
        <button class="onb-group-toggle" data-onb-collapse="${kind}" aria-expanded="${!collapsed}">
          <span class="material-icons-outlined">${collapsed ? 'chevron_right' : 'expand_more'}</span>
          <span class="material-icons-outlined onb-group-icon">${kindIcon(kind)}</span>
          <h3>${esc(heading)}</h3>
          <span class="onb-count">${selected}/${items.length} selected</span>
          ${incomplete ? `<span class="onb-flag">${incomplete} incomplete</span>` : ''}
        </button>
        <div class="onb-group-actions">
          <button class="btn btn-ghost btn-sm" data-onb-all="${kind}">Select all</button>
          <button class="btn btn-ghost btn-sm" data-onb-none="${kind}">Clear</button>
          <button class="btn btn-secondary btn-sm" data-onb-add="${kind}"><span class="material-icons-outlined" style="font-size:16px">add</span> Add</button>
        </div>
      </header>
      <div class="onb-group-body">${body}</div>
    </section>`;
  }

  function renderOnboardingStepper() {
    const slice = onboarding();
    const steps = [
      { n: 1, label: 'Upload & analyze' },
      { n: 2, label: 'Review & complete' },
      { n: 3, label: 'Confirm & onboard' }
    ];
    const done = slice.draft?.status === 'committed';
    return `<ol class="onb-stepper">${steps.map(step => `
      <li class="onb-step ${slice.step === step.n ? 'is-active' : ''} ${slice.step > step.n || done ? 'is-done' : ''}">
        <button data-onb-step="${step.n}">
          <span class="onb-step-num">${slice.step > step.n || done ? '<span class="material-icons-outlined" style="font-size:16px">check</span>' : step.n}</span>
          <span class="onb-step-label">${step.label}</span>
        </button>
      </li>`).join('')}</ol>`;
  }

  function renderOnboardingUploadStep() {
    const slice = onboarding();
    const draft = slice.draft;
    const documents = draft.documents || [];
    return `
      <div class="onb-panel">
        <h3 class="onb-panel-title">1 — Upload the project's documents</h3>
        <p class="onb-panel-blurb">Schedules, tender packages, scopes, contact lists, cost sheets — whatever the project already has, at whatever stage it has reached. PDF, Excel, CSV, Word, images, and text are all read. You can also skip this and build the draft by talking to Marshal on the next step.</p>
        <div class="onb-dropzone" id="onbDropZone">
          <span class="material-icons-outlined">cloud_upload</span>
          <p><strong>Drop files here</strong> or click to choose</p>
          <span class="onb-dropzone-hint">Each file is indexed into this workspace, so Marshal can cite it later.</span>
          <input type="file" id="onbFileInput" multiple hidden>
        </div>
        ${slice.uploading ? '<div class="onb-progress">Indexing documents…</div>' : ''}
        ${documents.length ? `<ul class="onb-doc-list">${documents.map(doc => `
          <li class="onb-doc">
            <span class="material-icons-outlined">description</span>
            <div class="onb-doc-main">
              <div class="onb-doc-name">${esc(doc.name)}</div>
              <div class="onb-doc-meta">${doc.pages} page${doc.pages === 1 ? '' : 's'}${doc.analyzed ? ' · analyzed' : ''}</div>
            </div>
            <button class="btn-table-action delete" data-onb-doc-remove="${esc(doc.doc_id)}" title="Remove from this draft"><span class="material-icons-outlined">close</span></button>
          </li>`).join('')}</ul>` : '<div class="onb-empty-inline">No documents attached yet.</div>'}

        <div class="form-group" style="margin-top:16px">
          <label class="form-label" for="onbInstructions">Anything Marshal should know (optional)</label>
          <textarea class="form-input" id="onbInstructions" rows="2" placeholder="e.g. Only onboard the tower package; ignore the sitework schedule.">${esc(slice.instructions)}</textarea>
        </div>
        <div class="onb-actions">
          <button class="btn btn-primary" id="btnOnbAnalyze" ${documents.length && !slice.analyzing ? '' : 'disabled'}>
            <span class="material-icons-outlined">auto_awesome</span>
            ${slice.analyzing ? 'Analyzing…' : 'Analyze documents'}
          </button>
          <button class="btn btn-secondary" data-onb-step="2">
            ${draft.summary.total ? `Back to the draft (${draft.summary.total} items)` : 'Skip — build the draft by hand'}
          </button>
        </div>
        <p class="onb-safety"><span class="material-icons-outlined">lock</span> Analysis only writes to this draft. Nothing is created in the workspace until you confirm at step 3.</p>
      </div>`;
  }

  function renderOnboardingCommandBar() {
    const slice = onboarding();
    const examples = 'Create a project called Website Redesign · Add a task called Database Migration · '
      + 'Set a cost of 50000 on Database Migration · Delete the Sitework project';
    return `<div class="onb-command">
      <div class="onb-command-head">
        <span class="material-icons-outlined">smart_toy</span>
        <div>
          <strong>Create or change anything by asking</strong>
          <span class="onb-command-hint">${esc(examples)}</span>
        </div>
      </div>
      ${slice.commandLog.length ? `<div class="onb-command-log" id="onbCommandLog">${slice.commandLog.slice(-8).map(entry => `
        <div class="onb-command-msg ${entry.role}">
          <div>${entry.role === 'bot' ? mdLite(entry.text) : esc(entry.text)}</div>
          ${(entry.applied || []).length ? `<div class="onb-command-applied">${entry.applied.map(row => onboardingChip(`${row.op} ${row.label || ''} ${row.name || ''}`.trim())).join('')}</div>` : ''}
          ${(entry.skipped || []).length ? `<div class="onb-command-skipped">${entry.skipped.map(row => onboardingChip(row.reason, 'warn')).join('')}</div>` : ''}
        </div>`).join('')}</div>` : ''}
      <div class="onb-command-row">
        <input class="form-input" id="onbCommandInput" placeholder="Tell Marshal what to create or change…" ${slice.commandBusy ? 'disabled' : ''}>
        <button class="btn-icon-only btn-voice" id="onbVoiceBtn" title="Dictate" aria-label="Dictate">
          <span class="material-icons-outlined">mic</span>
        </button>
        <button class="btn btn-primary" id="btnOnbCommand" ${slice.commandBusy ? 'disabled' : ''}>
          <span class="material-icons-outlined">${slice.commandBusy ? 'hourglass_top' : 'send'}</span>
        </button>
      </div>
    </div>`;
  }

  /** Just enough Markdown for the assistant's replies: **bold** and bullets. */
  function mdLite(text) {
    return esc(text || '')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^- (.*)$/gm, '<span class="onb-bullet">$1</span>')
      .replace(/\n/g, '<br>');
  }

  function renderOnboardingDraftStep() {
    const slice = onboarding();
    const draft = slice.draft;
    const summary = draft.summary;
    const kinds = onboardingKinds();
    if (!summary.total) {
      return `<div class="onb-panel"><div class="empty-state">
        <span class="material-icons-outlined">auto_awesome</span>
        <h3>Nothing drafted yet</h3>
        <p>Upload the project's documents and run the analysis, tell Marshal what to create below, or add a record yourself.</p>
        <div class="onb-actions" style="justify-content:center">
          <button class="btn btn-primary" id="btnOnbAddAny"><span class="material-icons-outlined">add</span> Add a record</button>
          <button class="btn btn-secondary" data-onb-step="1">Go to upload</button>
        </div>
      </div></div>${renderOnboardingCommandBar()}`;
    }
    return `
      <div class="onb-summary-bar">
        ${kinds.filter(kind => summary.counts[kind]).map(kind => `
          <div class="onb-summary-tile">
            <span class="onb-summary-num">${summary.selected[kind]}<span class="onb-summary-of">/${summary.counts[kind]}</span></span>
            <span class="onb-summary-label">${esc(kindLabel(kind, true))}</span>
          </div>`).join('')}
        <div class="onb-summary-actions">
          ${summary.incomplete ? `<span class="onb-flag onb-flag-lg">${summary.incomplete} incomplete</span>` : ''}
          <button class="btn btn-ghost btn-sm" data-onb-all="">Select everything</button>
          <button class="btn btn-ghost btn-sm" data-onb-none="">Clear all</button>
          <button class="btn btn-secondary btn-sm" id="btnOnbAddAny"><span class="material-icons-outlined" style="font-size:16px">add</span> Add record</button>
        </div>
      </div>
      ${summary.incomplete_selected ? `<div class="onb-blocked">
        <strong>${summary.incomplete_selected} selected record${summary.incomplete_selected === 1 ? '' : 's'} cannot be onboarded yet</strong>
        <span>Each one is marked below with the required fields it still needs. Fill them in, or clear their checkbox.</span>
      </div>` : ''}
      <div class="onb-draft">${kinds.map(renderOnboardingGroup).join('')}</div>
      ${renderOnboardingCommandBar()}
      <div class="onb-actions">
        <button class="btn btn-secondary" data-onb-step="1"><span class="material-icons-outlined">arrow_back</span> Documents</button>
        <button class="btn btn-primary" data-onb-step="3" ${summary.ready_to_onboard ? '' : 'disabled'}>
          Review ${summary.total_selected} selected record${summary.total_selected === 1 ? '' : 's'}
          <span class="material-icons-outlined">arrow_forward</span>
        </button>
      </div>`;
  }

  function renderOnboardingResult() {
    const result = onboarding().result;
    if (!result) return '';
    const credentials = result.credentials || [];
    return `<div class="onb-panel onb-result">
      <h3 class="onb-panel-title"><span class="material-icons-outlined">check_circle</span> Onboarded</h3>
      <p class="onb-panel-blurb">${result.total_created} record${result.total_created === 1 ? '' : 's'} created, ${result.total_reused} matched to something that already existed${result.memberships ? `, ${result.memberships} project membership${result.memberships === 1 ? '' : 's'} added` : ''}.</p>
      ${credentials.length ? `<div class="onb-credentials">
        <div class="onb-credentials-head">
          <span class="material-icons-outlined">key</span>
          <div><strong>First-login passwords</strong>
          <span>Shown once, and never stored. Pass them on, and have each person change theirs.</span></div>
          <button class="btn btn-secondary btn-sm" id="btnOnbCopyCreds"><span class="material-icons-outlined" style="font-size:16px">content_copy</span> Copy</button>
        </div>
        <div class="data-table-container"><table class="data-table"><thead><tr><th>Name</th><th>Email</th><th>Password</th></tr></thead>
        <tbody>${credentials.map(row => `<tr><td>${esc(row.name)}</td><td>${esc(row.email)}</td><td><code>${esc(row.password)}</code></td></tr>`).join('')}</tbody></table></div>
      </div>` : ''}
      <div class="data-table-container"><table class="data-table"><thead><tr><th>Type</th><th>Name</th><th>Outcome</th></tr></thead><tbody>
        ${(result.created || []).map(row => `<tr><td>${esc(row.label || row.kind)}</td><td>${esc(row.name)}</td><td><span class="badge badge-active">Created</span> <span class="onb-note">${esc(row.detail || '')}</span></td></tr>`).join('')}
        ${(result.reused || []).map(row => `<tr><td>${esc(row.label || row.kind)}</td><td>${esc(row.name)}</td><td><span class="badge badge-blue">Matched existing</span> <span class="onb-note">${esc(row.detail || '')}</span></td></tr>`).join('')}
      </tbody></table></div>
      ${(result.skipped || []).length ? `<div class="onb-blocked">
        <strong>Not created</strong>
        <ul>${result.skipped.map(row => `<li>${esc(row.name)} — ${esc(row.reason)}</li>`).join('')}</ul>
      </div>` : ''}
      <div class="onb-actions">
        <button class="btn btn-primary" data-nav="all-projects">Open Projects</button>
        <button class="btn btn-secondary" id="btnOnbClose">Back to drafts</button>
      </div>
    </div>`;
  }

  function renderOnboardingConfirmStep() {
    const slice = onboarding();
    if (slice.result) return renderOnboardingResult();
    if (slice.planLoading || !slice.plan) {
      return `<div class="onb-panel"><div class="onb-progress">Re-checking the draft against the workspace…</div></div>`;
    }
    const plan = slice.plan;
    const grouped = onboardingKinds()
      .map(kind => ({ kind, rows: plan.rows.filter(row => row.kind === kind) }))
      .filter(group => group.rows.length);
    const roleRows = plan.rows.filter(row => row.kind === 'role_type' && row.action === 'create');
    return `<div class="onb-panel">
      <h3 class="onb-panel-title">3 — Confirm what will be created</h3>
      <p class="onb-panel-blurb">Checked again on the server just now. ${plan.total_creating} record${plan.total_creating === 1 ? '' : 's'} will be created; ${plan.total_reusing} already exist${plan.total_reusing === 1 ? 's' : ''} and will be reused rather than duplicated.</p>

      ${plan.blocked.length ? `<div class="onb-blocked">
        <strong>${plan.blocked.length} selected record${plan.blocked.length === 1 ? '' : 's'} cannot be created</strong>
        <ul>${plan.blocked.map(row => `<li><strong>${esc(row.label || row.kind)}: ${esc(row.name || '(unnamed)')}</strong> — ${esc(row.reason)}${(row.missing || []).length ? `: ${row.missing.map(field => esc(field.label)).join(', ')}` : ''}</li>`).join('')}</ul>
        <span>Nothing is created while any of these are selected. Go back, complete them, or clear their checkbox.</span>
      </div>` : ''}
      ${roleRows.length && !plan.can_create_roles ? `<div class="onb-blocked">
        <strong>Roles need a Super Admin</strong>
        <ul>${roleRows.map(row => `<li>${esc(row.name)} will be skipped</li>`).join('')}</ul>
      </div>` : ''}

      ${grouped.map(group => `
        <h4 class="onb-plan-head">${esc(kindLabel(group.kind, true))}</h4>
        <div class="data-table-container"><table class="data-table"><thead><tr><th>Name</th><th class="hide-mobile">Where</th><th>Outcome</th></tr></thead>
        <tbody>${group.rows.map(row => `<tr>
          <td>${esc(row.name || '(unnamed)')}</td>
          <td class="hide-mobile">${esc([row.parent, row.nested_under].filter(Boolean).join(' › ') || row.stored_in || '—')}</td>
          <td>${row.action === 'create'
            ? '<span class="badge badge-active">Create</span>'
            : `<span class="badge badge-blue">Reuse ${esc(row.match?.label || '')}</span> <span class="onb-note">matched on ${esc(row.match?.on || 'name')}</span>`}</td>
        </tr>`).join('')}</tbody></table></div>`).join('')}

      <div class="onb-actions">
        <button class="btn btn-secondary" data-onb-step="2"><span class="material-icons-outlined">arrow_back</span> Back to the draft</button>
        <button class="btn btn-primary" id="btnOnbCommit" ${slice.committing || !plan.can_commit ? 'disabled' : ''}>
          <span class="material-icons-outlined">rocket_launch</span>
          ${slice.committing ? 'Onboarding…' : `Onboard ${plan.total_creating} record${plan.total_creating === 1 ? '' : 's'}`}
        </button>
      </div>
    </div>`;
  }

  function renderOnboardingDraftList() {
    const slice = onboarding();
    if (slice.loading && !slice.loaded) {
      return '<div class="onb-panel"><div class="onb-progress">Loading drafts…</div></div>';
    }
    if (!slice.drafts.length) {
      return `<div class="empty-state">
        <span class="material-icons-outlined">auto_awesome_motion</span>
        <h3>Onboard a project you already have</h3>
        <p>Upload its documents, or just tell Marshal what to create. Either way it lands in a draft first: you complete it, correct it, pick what is real, and only then is anything created.</p>
        <button class="btn btn-primary" id="btnOnbNew"><span class="material-icons-outlined">add</span> Start an onboarding</button>
      </div>`;
    }
    return `<div class="data-table-container"><table class="data-table">
      <thead><tr><th>Draft</th><th class="hide-mobile">Documents</th><th>Drafted</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>${slice.drafts.map(draft => `<tr>
        <td><button class="onb-link" data-onb-open="${esc(draft.id)}">${esc(draft.name)}</button>
          <div class="onb-row-meta">${esc((draft.created_at || '').slice(0, 10))}${draft.created_by_name ? ` · ${esc(draft.created_by_name)}` : ''}</div></td>
        <td class="hide-mobile">${draft.document_count}</td>
        <td>${draft.summary.total_selected}/${draft.summary.total} selected
          ${draft.summary.incomplete ? `<span class="onb-flag">${draft.summary.incomplete} incomplete</span>` : ''}</td>
        <td><span class="badge ${draft.status === 'committed' ? 'badge-blue' : 'badge-active'}">${draft.status === 'committed' ? 'Onboarded' : 'Draft'}</span></td>
        <td><div class="table-actions">
          <button class="btn-table-action" data-onb-open="${esc(draft.id)}" title="Open"><span class="material-icons-outlined">open_in_new</span></button>
          <button class="btn-table-action delete" data-onb-delete-draft="${esc(draft.id)}" data-name="${esc(draft.name)}" title="Delete draft"><span class="material-icons-outlined">delete</span></button>
        </div></td>
      </tr>`).join('')}</tbody></table></div>`;
  }

  function renderOnboardingPage() {
    const slice = onboarding();
    if (!isAccountAdmin()) {
      return `${notConnectedMsg()}<div class="empty-state">
        <span class="material-icons-outlined">lock</span>
        <h3>Onboarding is an administrator action</h3>
        <p>It creates projects, tasks, people, costs, types, and roles, so only an account administrator can run it.</p>
      </div>`;
    }
    const draft = slice.draft;
    const header = `<div class="page-header">
      <div>
        <h1 class="page-title">${draft ? esc(draft.name) : 'Project Onboarding'}</h1>
        <p class="page-subtitle">${draft
          ? 'A draft of what will be created. Nothing here exists in the workspace until you confirm it.'
          : 'Bring an existing project into BuildMarshal from its documents, or build one by talking to Marshal.'}</p>
      </div>
      <div class="onb-header-actions">
        ${draft ? '<button class="btn btn-secondary" id="btnOnbClose"><span class="material-icons-outlined">arrow_back</span> All drafts</button>' : ''}
        <button class="btn btn-primary" id="btnOnbNew"><span class="material-icons-outlined">add</span> New onboarding</button>
      </div>
    </div>`;

    if (!draft) return `${notConnectedMsg()}${header}${renderOnboardingDraftList()}`;
    if (!slice.schema) return `${notConnectedMsg()}${header}<div class="onb-panel"><div class="onb-progress">Loading the workspace's record definitions…</div></div>`;

    const step = slice.draft.status === 'committed' && slice.result ? 3 : slice.step;
    const body = step === 1 ? renderOnboardingUploadStep()
      : step === 2 ? renderOnboardingDraftStep()
      : renderOnboardingConfirmStep();
    return `${notConnectedMsg()}${header}${renderOnboardingStepper()}${body}`;
  }

  // ── The record editor ───────────────────────────────────────────────────
  //
  // Every control is generated from the entity definition the server sent, so
  // the form offers exactly the fields the application has and marks exactly
  // the ones it will refuse to create without.

  function onboardingChoicesFor(kind) {
    const live = (onboardingSchema()?.choices || {})[kind] || [];
    const drafted = onboardingItems(kind)
      .map(item => ({ id: item.id, label: item.fields.name || '', detail: 'in this draft' }))
      .filter(row => row.label);
    const seen = new Set();
    return [...live, ...drafted].filter(row => {
      const key = row.label.toLowerCase();
      if (!row.label || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function onboardingFieldControl(field, value) {
    const id = `onbField_${field.name}`;
    const required = field.required ? 'data-onb-required="1"' : '';
    if (field.type === 'textarea') {
      return `<textarea class="form-input" id="${id}" data-onb-field="${field.name}" ${required} rows="3">${esc(value)}</textarea>`;
    }
    if (field.type === 'select') {
      return `<select class="form-input" id="${id}" data-onb-field="${field.name}" ${required}>
        <option value=""${value ? '' : ' selected'}>— not set —</option>
        ${field.options.map(option => `<option ${option === value ? 'selected' : ''}>${esc(option)}</option>`).join('')}
      </select>`;
    }
    if (field.type === 'reference') {
      // Only records that actually exist; free text would be a way to invent one.
      const options = onboardingChoicesFor(field.reference);
      const known = options.some(row => row.label === value);
      return `<select class="form-input" id="${id}" data-onb-field="${field.name}" ${required}>
        <option value=""${value ? '' : ' selected'}>— not set —</option>
        ${options.map(row => `<option value="${esc(row.label)}" ${row.label === value ? 'selected' : ''}>${esc(row.label)}${row.detail ? ` — ${esc(row.detail)}` : ''}</option>`).join('')}
        ${value && !known ? `<option value="${esc(value)}" selected>${esc(value)} (not in this workspace)</option>` : ''}
      </select>`;
    }
    const type = field.type === 'date' ? 'date'
      : (field.type === 'money' || field.type === 'number') ? 'number'
      : (field.type === 'datetime' ? 'datetime-local' : 'text');
    const step = field.type === 'money' ? ' step="0.01" min="0"' : '';
    return `<input class="form-input" type="${type}"${step} id="${id}" data-onb-field="${field.name}" ${required} value="${esc(value)}">`;
  }

  /**
   * Edit a draft record, or add a new one.
   *
   * ``preset`` carries the links a new record needs — which project a task
   * joins, which task a cost belongs to — so the hierarchy is set before it is
   * saved.
   */
  function openOnboardingItemModal(kind, itemId, preset = {}) {
    const item = itemId ? onboardingItem(itemId) : null;
    if (itemId && !item) return;
    const actualKind = item ? item.kind : kind;
    const spec = entitySpec(actualKind);
    if (!spec) return;
    const fields = item ? item.fields : {};
    const parentRef = item?.parent_ref ?? preset.parent_ref ?? null;
    const parents = spec.parent ? onboardingItems(spec.parent) : [];
    const nestedChoices = spec.self_parent
      ? onboardingItems(actualKind).filter(row =>
          row.id !== itemId && row.parent_ref === parentRef
          && !(item ? item.dependents.includes(row.id) : false))
      : [];
    const held = new Set(fields.permissions || []);
    const permissionGroups = onboardingSchema()?.permissions || [];
    const grouped = permissionGroups.reduce((acc, entry) => {
      (acc[entry.group] = acc[entry.group] || []).push(entry);
      return acc;
    }, {});

    DOM.crudModalTitle.textContent = item ? `Edit ${spec.label.toLowerCase()}` : `Add ${spec.label.toLowerCase()}`;
    DOM.crudModalBody.innerHTML = `
      <p class="form-hint">This edits the draft only. Nothing is created until you confirm at step 3.</p>

      ${spec.parent ? `<div class="form-group">
        <label class="form-label required-label" for="onbLinkParent">${esc(spec.parent_label)}</label>
        <select class="form-input" id="onbLinkParent">
          <option value="">— choose —</option>
          ${parents.map(row => `<option value="${esc(row.id)}" ${row.id === parentRef ? 'selected' : ''}>${esc(row.fields.name || '(unnamed)')}</option>`).join('')}
        </select>
        ${parents.length ? '' : `<div class="form-hint">Add a ${esc(spec.parent_label.toLowerCase())} to the draft first.</div>`}
      </div>` : ''}

      ${spec.self_parent ? `<div class="form-group">
        <label class="form-label" for="onbLinkNested">Sits under</label>
        <select class="form-input" id="onbLinkNested">
          <option value="">— top level —</option>
          ${nestedChoices.map(row => `<option value="${esc(row.id)}" ${row.id === (item?.parent_id ?? preset.parent_id) ? 'selected' : ''}>${esc(row.fields.name)}</option>`).join('')}
        </select>
        <div class="form-hint">Changing the ${esc((spec.parent_label || 'parent').toLowerCase())} clears this, since it has to stay in the same one.</div>
      </div>` : ''}

      ${spec.fields.filter(field => field.type !== 'permissions').map(field => `
        <div class="form-group">
          <label class="form-label ${field.required ? 'required-label' : ''}" for="onbField_${field.name}">${esc(field.label)}</label>
          ${onboardingFieldControl(field, fields[field.name] ?? '')}
          ${field.help ? `<div class="form-hint">${esc(field.help)}</div>` : ''}
        </div>`).join('')}

      ${actualKind === 'user' && onboardingItems('project').length ? `
        <div class="form-group"><label class="form-label">Projects to join</label>
          ${onboardingItems('project').map(project => `<label class="perm-row">
            <input type="checkbox" class="onb-project-ref" value="${esc(project.id)}" ${(item?.project_refs || preset.project_refs || []).includes(project.id) ? 'checked' : ''}>
            <span><strong class="perm-name">${esc(project.fields.name || '(unnamed)')}</strong></span>
          </label>`).join('')}
          <div class="form-hint">Membership is only added for projects you also select for onboarding.</div></div>` : ''}

      ${spec.fields.some(field => field.type === 'permissions') ? `
        <div class="form-hint" style="margin-bottom:10px">A role grants real authority. Check these before onboarding — Marshal proposes them, it does not decide them.</div>
        ${Object.entries(grouped).map(([group, entries]) => `
          <div class="perm-group">
            <div class="perm-group-head">
              <h4 class="perm-group-title">${esc(group)}</h4>
              <button type="button" class="btn btn-ghost btn-sm" data-perm-group="${esc(group)}">Select all</button>
            </div>
            ${entries.map(entry => `
              <label class="perm-row">
                <input type="checkbox" class="perm-check" value="${esc(entry.key)}" data-group="${esc(group)}" ${held.has(entry.key) ? 'checked' : ''}>
                <span><strong class="perm-name">${esc(entry.name)}</strong>
                <span class="perm-desc">${esc(entry.description)}</span></span>
              </label>`).join('')}
          </div>`).join('')}` : ''}`;

    DOM.crudModalBody.querySelectorAll('[data-perm-group]').forEach(button =>
      button.addEventListener('click', () => {
        const boxes = [...DOM.crudModalBody.querySelectorAll(`.perm-check[data-group="${CSS.escape(button.dataset.permGroup)}"]`)];
        const turnOn = boxes.some(box => !box.checked);
        boxes.forEach(box => { box.checked = turnOn; });
        button.textContent = turnOn ? 'Clear all' : 'Select all';
      }));
    // Moving to another parent cannot keep a nesting from the old one.
    $('#onbLinkParent')?.addEventListener('change', () => {
      const select = $('#onbLinkNested');
      if (select) select.value = '';
    });
    // Open focused on the field the admin clicked in the missing-fields list.
    const focus = preset.focus ? $(`#onbField_${preset.focus}`) : null;
    (focus || DOM.crudModalBody.querySelector('.form-input'))?.focus();

    DOM.btnSaveCrud.dataset.crudAction = 'save-onboarding-item';
    DOM.btnSaveCrud.dataset.crudId = itemId || '';
    DOM.btnSaveCrud.dataset.onbKind = actualKind;
    DOM.btnSaveCrud.dataset.onbPreset = JSON.stringify(preset);
    DOM.crudModal.classList.add('open');
  }

  async function submitOnboardingItem(itemId, kind, preset) {
    const spec = entitySpec(kind);
    if (!spec) return false;
    const fields = {};
    spec.fields.forEach(field => {
      const element = DOM.crudModalBody.querySelector(`[data-onb-field="${field.name}"]`);
      if (element) fields[field.name] = element.value.trim();
    });
    if (spec.fields.some(field => field.type === 'permissions')) {
      fields.permissions = [...DOM.crudModalBody.querySelectorAll('.perm-check:checked')].map(box => box.value);
    }

    const payload = { kind, fields };
    if (spec.parent) payload.parent_ref = $('#onbLinkParent')?.value || preset.parent_ref || null;
    if (spec.self_parent) payload.parent_id = $('#onbLinkNested')?.value || null;
    if (kind === 'user') {
      payload.project_refs = [...DOM.crudModalBody.querySelectorAll('.onb-project-ref:checked')].map(box => box.value);
    }

    try {
      await saveOnboardingItem(itemId, itemId ? {
        fields: payload.fields,
        ...(spec.parent ? { parent_ref: payload.parent_ref || '' } : {}),
        ...(spec.self_parent ? { parent_id: payload.parent_id || '' } : {}),
        ...(kind === 'user' ? { project_refs: payload.project_refs } : {})
      } : payload);
      renderPage();
      return true;
    } catch (error) {
      showToast(error.message, 'error', 6000);
      return false;
    }
  }

  /** Pick a record type to add, when the admin has not already said which. */
  function openOnboardingKindPicker() {
    DOM.crudModalTitle.textContent = 'Add a record to the draft';
    DOM.crudModalBody.innerHTML = `
      <p class="form-hint">Everything lands in the draft. Nothing is created until you confirm at step 3.</p>
      <div class="onb-kind-grid">
        ${onboardingKinds().map(kind => {
          const spec = entitySpec(kind);
          return `<button class="onb-kind-card" data-onb-pick="${kind}">
            <span class="material-icons-outlined">${kindIcon(kind)}</span>
            <strong>${esc(spec.label)}</strong>
            <span>${esc(spec.parent ? `Belongs to a ${spec.parent_label.toLowerCase()}` : spec.stored_in || '')}</span>
          </button>`;
        }).join('')}
      </div>`;
    DOM.crudModalBody.querySelectorAll('[data-onb-pick]').forEach(button =>
      button.addEventListener('click', () => openOnboardingItemModal(button.dataset.onbPick, null)));
    delete DOM.btnSaveCrud.dataset.crudAction;
    DOM.crudModal.classList.add('open');
  }

  // ── Events ──────────────────────────────────────────────────────────────

  function bindOnboardingEvents() {
    const slice = onboarding();

    $('#btnOnbNew')?.addEventListener('click', createOnboardingDraft);
    $('#btnOnbClose')?.addEventListener('click', () => {
      slice.draft = null; slice.plan = null; slice.result = null; slice.commandLog = [];
      fetchOnboardingDrafts().then(renderPage);
    });
    $$('[data-onb-open]').forEach(element =>
      element.addEventListener('click', () => openOnboardingDraft(element.dataset.onbOpen)));
    $$('[data-onb-delete-draft]').forEach(element =>
      element.addEventListener('click', () =>
        deleteOnboardingDraft(element.dataset.onbDeleteDraft, element.dataset.name)));

    $$('[data-onb-step]').forEach(element => element.addEventListener('click', () => {
      const step = Number(element.dataset.onbStep);
      if (step === 3 && !slice.draft?.summary.total_selected) {
        showToast('Select at least one item to onboard', 'warning');
        return;
      }
      slice.step = step;
      renderPage();
      if (step === 3 && !slice.result) loadOnboardingPlan();
    }));

    // Upload
    const dropZone = $('#onbDropZone');
    const fileInput = $('#onbFileInput');
    if (dropZone && fileInput) {
      dropZone.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', () => {
        uploadOnboardingFiles([...fileInput.files]);
        fileInput.value = '';
      });
      ['dragenter', 'dragover'].forEach(name => dropZone.addEventListener(name, event => {
        event.preventDefault(); dropZone.classList.add('is-over');
      }));
      ['dragleave', 'drop'].forEach(name => dropZone.addEventListener(name, event => {
        event.preventDefault(); dropZone.classList.remove('is-over');
      }));
      dropZone.addEventListener('drop', event => uploadOnboardingFiles([...(event.dataTransfer?.files || [])]));
    }
    $('#onbInstructions')?.addEventListener('input', event => { slice.instructions = event.target.value; });
    $('#btnOnbAnalyze')?.addEventListener('click', analyzeOnboardingDraft);
    $$('[data-onb-doc-remove]').forEach(element =>
      element.addEventListener('click', () => detachOnboardingDocument(element.dataset.onbDocRemove)));

    // Draft editing and selection
    $$('[data-onb-toggle]').forEach(element => element.addEventListener('change', () =>
      toggleOnboardingItem(element.dataset.onbToggle, element.checked)));
    $$('[data-onb-all]').forEach(element => element.addEventListener('click', () =>
      selectAllOnboarding(element.dataset.onbAll, true)));
    $$('[data-onb-none]').forEach(element => element.addEventListener('click', () =>
      selectAllOnboarding(element.dataset.onbNone, false)));
    $$('[data-onb-collapse]').forEach(element => element.addEventListener('click', () => {
      slice.collapsed[element.dataset.onbCollapse] = !slice.collapsed[element.dataset.onbCollapse];
      renderPage();
    }));
    $$('[data-onb-edit]').forEach(element => element.addEventListener('click', () =>
      openOnboardingItemModal(null, element.dataset.onbEdit,
        element.dataset.onbFocus ? { focus: element.dataset.onbFocus } : {})));
    $$('[data-onb-delete]').forEach(element => element.addEventListener('click', () =>
      deleteOnboardingItem(element.dataset.onbDelete)));
    $('#btnOnbAddAny')?.addEventListener('click', openOnboardingKindPicker);
    $$('[data-onb-add]').forEach(element => element.addEventListener('click', () =>
      openOnboardingItemModal(element.dataset.onbAdd, null)));
    // Add whatever hangs off this record: a task or a cost on a project, a cost
    // on a task. Which of those is possible comes from the schema.
    $$('[data-onb-add-child]').forEach(element => element.addEventListener('click', () =>
      openOnboardingItemModal(element.dataset.onbAddChild, null,
        { parent_ref: element.dataset.onbParent })));
    $$('[data-onb-add-nested]').forEach(element => element.addEventListener('click', () => {
      const parent = onboardingItem(element.dataset.onbAddNested);
      if (parent) openOnboardingItemModal(parent.kind, null,
        { parent_ref: parent.parent_ref, parent_id: parent.id });
    }));

    // Command bar
    $('#btnOnbCommand')?.addEventListener('click', sendOnboardingCommand);
    $('#onbCommandInput')?.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); sendOnboardingCommand(); }
    });
    const voiceButton = $('#onbVoiceBtn');
    if (voiceButton) {
      voiceButton.addEventListener('click', () => {
        // Point the shared recorder at this box for the length of the take.
        state.voiceTarget = { inputId: 'onbCommandInput', buttonId: 'onbVoiceBtn' };
        toggleVoiceRecording();
      });
    }

    // Confirm and commit
    $('#btnOnbCommit')?.addEventListener('click', commitOnboardingDraft);
    $('#btnOnbCopyCreds')?.addEventListener('click', () => {
      const rows = (slice.result?.credentials || [])
        .map(row => `${row.name}\t${row.email}\t${row.password}`).join('\n');
      navigator.clipboard?.writeText(`Name\tEmail\tFirst-login password\n${rows}`)
        .then(() => showToast('Copied. Share them privately, and have each person change theirs.', 'success', 6000))
        .catch(() => showToast('Could not copy — select the table instead.', 'warning'));
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Charts

     Plain inline SVG — no chart library, in keeping with the rest of the app.

     The series colours are the validated categorical slots, assigned in fixed
     order and never cycled: a ninth series would be indistinguishable from an
     existing one under colour-vision deficiency, so the forms here cap at four
     and fold the tail into "Other". The first thing tried here was the obvious
     one — green for done, red for blocked — and it failed the CVD check
     outright (ΔE 4.1 under deuteranopia: a red-green reader cannot tell them
     apart at all). Hence these hues, plus a label on every mark so identity is
     never carried by colour alone.
     ═══════════════════════════════════════════════════════════════════════ */

  const VIZ = {
    // Categorical slots 1-4, light-surface steps. The app has no dark mode; the
    // matching validated dark steps are #3987e5 #d95926 #199e70 #c98500 for
    // whoever adds one.
    series: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'],
    muted: '#898781',
    grid: '#e1e0d9',
    axis: '#c3c2b7',
    ink: '#52514e'
  };

  // Status -> slot, so a status is the same colour in every chart that draws it.
  const VIZ_STATUS = { 'Open': 0, 'In Progress': 1, 'Blocked': 2, 'Completed': 3 };

  function vizColor(index) { return VIZ.series[index % VIZ.series.length]; }

  /** Escape for an SVG/HTML attribute used as tooltip text. */
  function tip(text) { return `data-viz-tip="${esc(String(text))}"`; }

  function vizEmpty(message) {
    return `<div class="viz-empty">${esc(message)}</div>`;
  }

  function vizLegend(entries) {
    return `<div class="viz-legend">${entries.map(entry => `
      <span class="viz-legend-item">
        <span class="viz-swatch" style="background:${entry.color}"></span>
        ${esc(entry.label)}${entry.value !== undefined ? ` <b>${esc(entry.value)}</b>` : ''}
      </span>`).join('')}</div>`;
  }

  /**
   * A line chart of one or more series over time.
   *
   * Used for the planned-versus-earned value curve, which is the one chart an
   * earned-value report is really about.
   */
  function vizLine(points, series, options = {}) {
    if (!points.length) return vizEmpty(options.empty || 'Nothing to plot yet.');
    const W = 720, H = 240, padL = 56, padR = 16, padT = 12, padB = 28;
    const values = series.flatMap(s => points.map(p => p[s.key]).filter(v => v !== undefined && v !== null));
    const max = Math.max(1, ...values);
    const xs = index => padL + (index / Math.max(1, points.length - 1)) * (W - padL - padR);
    const ys = value => H - padB - (value / max) * (H - padT - padB);

    const ticks = [0, 0.25, 0.5, 0.75, 1].map(fraction => {
      const value = max * fraction;
      return `<line x1="${padL}" y1="${ys(value)}" x2="${W - padR}" y2="${ys(value)}" stroke="${VIZ.grid}" stroke-width="1"/>
        <text x="${padL - 8}" y="${ys(value) + 4}" text-anchor="end" class="viz-tick">${esc(options.format ? options.format(value) : Math.round(value))}</text>`;
    }).join('');

    const paths = series.map((s, index) => {
      const drawn = points.map((point, i) => ({ point, i }))
        .filter(({ point }) => point[s.key] !== undefined && point[s.key] !== null);
      if (!drawn.length) return '';
      const d = drawn.map(({ point, i }, order) =>
        `${order ? 'L' : 'M'}${xs(i).toFixed(1)} ${ys(point[s.key]).toFixed(1)}`).join(' ');
      return `<path d="${d}" fill="none" stroke="${vizColor(index)}" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"/>`;
    }).join('');

    // One hit target per x position, so the crosshair is easy to hit.
    const hits = points.map((point, i) => {
      const lines = series
        .filter(s => point[s.key] !== undefined && point[s.key] !== null)
        .map(s => `${s.label}: ${options.format ? options.format(point[s.key]) : point[s.key]}`);
      return `<rect x="${(xs(i) - (W / points.length) / 2).toFixed(1)}" y="${padT}"
        width="${(W / points.length).toFixed(1)}" height="${H - padT - padB}" fill="transparent"
        class="viz-hit" ${tip(`${point.date}\n${lines.join('\n')}`)}/>`;
    }).join('');

    const markers = series.map((s, index) => points.map((point, i) =>
      point[s.key] === undefined || point[s.key] === null ? '' :
        `<circle cx="${xs(i).toFixed(1)}" cy="${ys(point[s.key]).toFixed(1)}" r="2.5"
          fill="${vizColor(index)}" opacity="0.9"/>`).join('')).join('');

    const todayIndex = points.findIndex(point => point.date === options.today);
    const todayLine = todayIndex >= 0 ? `
      <line x1="${xs(todayIndex)}" y1="${padT}" x2="${xs(todayIndex)}" y2="${H - padB}"
        stroke="${VIZ.axis}" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="${xs(todayIndex)}" y="${padT - 2}" text-anchor="middle" class="viz-tick">today</text>` : '';

    const first = points[0]?.date || '';
    const last = points[points.length - 1]?.date || '';
    return `${vizLegend(series.map((s, index) => ({ label: s.label, color: vizColor(index) })))}
      <svg viewBox="0 0 ${W} ${H}" class="viz-svg" role="img"
        aria-label="${esc(options.label || 'Line chart')}">
        ${ticks}${todayLine}${paths}${markers}${hits}
        <line x1="${padL}" y1="${H - padB}" x2="${W - padR}" y2="${H - padB}" stroke="${VIZ.axis}" stroke-width="1"/>
        <text x="${padL}" y="${H - 8}" class="viz-tick">${esc(first)}</text>
        <text x="${W - padR}" y="${H - 8}" text-anchor="end" class="viz-tick">${esc(last)}</text>
      </svg>`;
  }

  /** Columns over time — one series, so no legend: the title names it. */
  function vizColumns(rows, options = {}) {
    if (!rows.length) return vizEmpty(options.empty || 'Nothing to plot yet.');
    const W = 720, H = 180, padL = 40, padR = 12, padT = 14, padB = 30;
    const max = Math.max(1, ...rows.map(row => row.value));
    const band = (W - padL - padR) / rows.length;
    // Thin marks: a 2px gap between adjacent fills, and a ceiling so a
    // chart of few weeks draws columns rather than blocks.
    const width = Math.max(4, Math.min(30, band - 6));
    const bars = rows.map((row, index) => {
      const height = (row.value / max) * (H - padT - padB);
      const x = padL + index * band + (band - width) / 2;
      const y = H - padB - height;
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${width.toFixed(1)}"
        height="${Math.max(0, height).toFixed(1)}" rx="3" fill="${vizColor(0)}"
        class="viz-hit" ${tip(`${row.label}: ${row.value}`)}/>
        ${row.value ? `<text x="${(x + width / 2).toFixed(1)}" y="${(y - 4).toFixed(1)}"
          text-anchor="middle" class="viz-value">${row.value}</text>` : ''}`;
    }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" class="viz-svg" role="img"
        aria-label="${esc(options.label || 'Column chart')}">
        <line x1="${padL}" y1="${H - padB}" x2="${W - padR}" y2="${H - padB}" stroke="${VIZ.axis}" stroke-width="1"/>
        ${bars}
        ${rows.map((row, index) => index % Math.ceil(rows.length / 8) ? '' :
          `<text x="${(padL + index * band + band / 2).toFixed(1)}" y="${H - 10}"
            text-anchor="middle" class="viz-tick">${esc(row.short || row.label)}</text>`).join('')}
      </svg>`;
  }

  /** Horizontal bars for comparing magnitude — one hue; length carries the size. */
  function vizBars(rows, options = {}) {
    if (!rows.length) return vizEmpty(options.empty || 'Nothing to show yet.');
    const max = Math.max(1, ...rows.map(row => row.value));
    return `<div class="viz-bars">${rows.map(row => `
      <div class="viz-bar-row" ${tip(`${row.label}: ${options.format ? options.format(row.value) : row.value}`)}>
        <span class="viz-bar-label" title="${esc(row.label)}">${esc(row.label)}</span>
        <span class="viz-bar-track">
          <span class="viz-bar-fill" style="width:${Math.max(1, (row.value / max) * 100)}%;
            background:${row.color || vizColor(0)}"></span>
        </span>
        <span class="viz-bar-value">${esc(options.format ? options.format(row.value) : row.value)}</span>
      </div>`).join('')}</div>`;
  }

  /**
   * One stacked bar for part-to-whole.
   *
   * Every segment is directly labelled, which is what the colour check requires
   * of the lighter slots and what makes the chart readable without the legend.
   */
  function vizStack(segments, options = {}) {
    const total = segments.reduce((sum, row) => sum + row.value, 0);
    if (!total) return vizEmpty(options.empty || 'Nothing to show yet.');
    return `<div class="viz-stack">${segments.filter(row => row.value).map(row => `
      <span class="viz-stack-seg" style="flex-grow:${row.value};background:${row.color}"
        ${tip(`${row.label}: ${row.value} (${Math.round((row.value / total) * 100)}%)`)}>
        <span class="viz-stack-label">${row.value}</span>
      </span>`).join('')}</div>
      ${vizLegend(segments.map(row => ({ label: row.label, color: row.color, value: row.value })))}`;
  }

  /** A single ratio against a limit. A meter, not a two-slice pie. */
  function vizMeter(value, limit, options = {}) {
    const share = limit ? Math.min(1.5, value / limit) : 0;
    const over = share > 1;
    return `<div class="viz-meter" ${tip(`${options.label || ''} ${options.format ? options.format(value) : value} of ${options.format ? options.format(limit) : limit}`)}>
      <div class="viz-meter-track">
        <div class="viz-meter-fill ${over ? 'is-over' : ''}" style="width:${Math.min(100, share * 100)}%"></div>
        ${over ? '<div class="viz-meter-over" style="left:100%"></div>' : ''}
      </div>
      <div class="viz-meter-scale">
        <span>${esc(options.format ? options.format(value) : value)}</span>
        <span class="viz-meter-limit">of ${esc(options.format ? options.format(limit) : limit)}
          ${limit ? `(${Math.round((value / limit) * 100)}%)` : ''}</span>
      </div>
    </div>`;
  }

  /** A shared tooltip, attached once and driven by data-viz-tip. */
  function bindVizTooltips(root) {
    const host = root || document;
    let bubble = document.getElementById('vizTooltip');
    if (!bubble) {
      bubble = document.createElement('div');
      bubble.id = 'vizTooltip';
      bubble.className = 'viz-tooltip';
      bubble.hidden = true;
      document.body.appendChild(bubble);
    }
    const show = event => {
      const target = event.target.closest('[data-viz-tip]');
      if (!target) { bubble.hidden = true; return; }
      bubble.textContent = target.getAttribute('data-viz-tip');
      bubble.hidden = false;
      const width = bubble.offsetWidth;
      bubble.style.left = `${Math.min(window.innerWidth - width - 8, Math.max(8, event.clientX - width / 2))}px`;
      bubble.style.top = `${Math.max(8, event.clientY - bubble.offsetHeight - 12)}px`;
    };
    host.querySelectorAll('[data-viz-tip]').forEach(element => {
      element.addEventListener('mousemove', show);
      element.addEventListener('mouseleave', () => { bubble.hidden = true; });
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Statistics, the report that reads them, and the storage panel
     ═══════════════════════════════════════════════════════════════════════ */

  function statsState() {
    if (!state.stats) {
      state.stats = {
        projectId: null, data: null, loading: false, error: '',
        insights: null, insightsLoading: false,
        rule: 'fixed_50_50', table: false,
        report: { open: false, preview: null, busy: false, result: null, list: [], narrative: true }
      };
    }
    return state.stats;
  }

  function fmtMoney(value) {
    const amount = Number(value || 0);
    const mark = currencyMark();
    if (LAKH_CRORE.has(activeCurrency())) {
      if (Math.abs(amount) >= 10000000) return `${mark}${(amount / 10000000).toFixed(2)} Cr`;
      if (Math.abs(amount) >= 100000) return `${mark}${(amount / 100000).toFixed(1)} L`;
      return `${mark}${groupSouthAsian(amount)}`;
    }
    if (Math.abs(amount) >= 1000000) return `${mark}${(amount / 1000000).toFixed(1)}M`;
    if (Math.abs(amount) >= 1000) return `${mark}${Math.round(amount / 1000)}k`;
    return `${mark}${amount.toLocaleString()}`;
  }

  function fmtPercent(value) {
    return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`;
  }

  const STAT_FORMATS = {
    percent: fmtPercent,
    money: value => (value === null || value === undefined ? '—' : fmtMoney(value)),
    index: value => (value === null || value === undefined ? '—' : Number(value).toFixed(2)),
    number: value => (value === null || value === undefined ? '—' : `${Number(value)}`),
    count: value => (value === null || value === undefined ? '—' : `${Number(value)}`)
  };

  async function loadProjectStatistics(projectId, { force = false } = {}) {
    const slice = statsState();
    if (slice.projectId !== projectId) {
      state.stats = null;
      statsState().projectId = projectId;
    }
    if (!force && statsState().data) return;
    statsState().loading = true;
    statsState().error = '';
    paintDashTab('stats');
    try {
      const response = await apiReq(`/api/projects/${projectId}/statistics?rule=${statsState().rule}`);
      statsState().data = await response.json();
    } catch (error) {
      statsState().error = error.message;
    } finally {
      statsState().loading = false;
      paintDashTab('stats');
    }
  }

  async function loadProjectInsights(projectId) {
    const slice = statsState();
    if (slice.insightsLoading) return;
    slice.insightsLoading = true;
    paintDashTab('stats');
    try {
      const response = await apiReq(`/api/projects/${projectId}/statistics/insights`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule: slice.rule })
      });
      slice.insights = (await response.json()).insights;
    } catch (error) {
      showToast(error.message, 'error', 6000);
    } finally {
      slice.insightsLoading = false;
      paintDashTab('stats');
    }
  }

  // ── Statistics tab ──────────────────────────────────────────────────────

  function renderStatsTab(project) {
    const slice = statsState();
    if (slice.loading && !slice.data) return `<div class="empty-msg">Working out where this project stands…</div>`;
    if (slice.error) {
      return `<div class="connection-banner warning"><span class="material-icons-outlined">warning</span>
        <span>${esc(slice.error)}</span>
        <button class="btn btn-secondary btn-sm" data-stats-retry="1">Retry</button></div>`;
    }
    const data = slice.data;
    if (!data) return `<div class="empty-msg">Loading statistics…</div>`;

    return `
      ${renderStatsHeader(data, slice)}
      ${renderStatsHeadline(data)}
      ${slice.table ? renderStatsTables(data) : renderStatsCharts(data)}
      ${renderStatsRisks(data)}
      ${renderStatsInsights(slice)}`;
  }

  function renderStatsHeader(data, slice) {
    const phase = data.phase || {};
    return `<div class="stats-header">
      <div class="stats-phase">
        <span class="stats-phase-badge">${esc(phase.label || '—')}</span>
        <div>
          <div class="stats-phase-line">Stage ${phase.index} of ${phase.of}</div>
          <div class="stats-phase-reason">${esc(phase.reason || '')}</div>
        </div>
      </div>
      <div class="stats-header-controls">
        <label class="stats-rule">
          <span>Credit progress by</span>
          <select class="filter-input" id="statsRule">
            ${(data.rules || []).map(rule => `<option value="${rule}" ${rule === slice.rule ? 'selected' : ''}>
              ${esc(rule.replace('fixed_', '').replace('_', '/'))} rule</option>`).join('')}
          </select>
        </label>
        <button class="btn btn-ghost btn-sm" id="statsToggleTable">
          <span class="material-icons-outlined" style="font-size:16px">${slice.table ? 'insert_chart' : 'table_rows'}</span>
          ${slice.table ? 'Charts' : 'Table view'}
        </button>
        <button class="btn btn-secondary btn-sm" id="statsRefresh">
          <span class="material-icons-outlined" style="font-size:16px">refresh</span> Refresh
        </button>
        <button class="btn btn-primary btn-sm" id="statsReport">
          <span class="material-icons-outlined" style="font-size:16px">description</span> Generate report
        </button>
      </div>
    </div>
    <div class="stats-asof">Figures as at ${esc(data.as_of || '')}.</div>`;
  }

  function renderStatsHeadline(data) {
    return `<div class="stat-row">${(data.headline || []).map(row => `
      <div class="stat-tile tone-${esc(row.tone || 'muted')}">
        <div class="stat-tile-label">${esc(row.label)}</div>
        <div class="stat-tile-value">${esc((STAT_FORMATS[row.format] || String)(row.value))}</div>
        ${row.note ? `<div class="stat-tile-note">${esc(row.note)}</div>` : ''}
      </div>`).join('')}</div>`;
  }

  function renderStatsCharts(data) {
    const value = data.value || {};
    const cost = data.cost || {};
    const flow = data.flow || {};
    const dist = data.distributions || {};
    const curve = data.curve || { points: [] };

    const statusSegments = (dist.status || []).map(row => ({
      label: row.label, value: row.value, color: vizColor(VIZ_STATUS[row.label] ?? 0)
    }));
    const loadRows = (dist.assignee_load || []).slice(0, 8);

    return `
      <div class="viz-card">
        <div class="viz-head">
          <h3>Planned against earned value</h3>
          <p>What the programme said would be earned by each date, against what has been.
             Earned value stops at today — projecting it forward would be a forecast, not a measurement.</p>
        </div>
        ${vizLine(curve.points || [], [
          { key: 'planned', label: 'Planned value' },
          { key: 'earned', label: 'Earned value' }
        ], { today: curve.today, format: fmtMoney, label: 'Planned against earned value',
             empty: 'No task has dates yet, so there is no curve to draw.' })}
        ${value.caveat ? `<p class="viz-note">${esc(value.caveat)}</p>` : ''}
      </div>

      <div class="viz-grid">
        <div class="viz-card">
          <div class="viz-head"><h3>Where the work stands</h3>
            <p>Every task on this project by status.</p></div>
          ${vizStack(statusSegments, { empty: 'No tasks on this project yet.' })}
        </div>
        <div class="viz-card">
          <div class="viz-head"><h3>Budget and commitment</h3>
            <p>What is committed through procurement against the budget.
               There is no cost performance index: that needs recorded actual spend.</p></div>
          ${vizMeter(cost.committed_procurement || 0, cost.budget || 0,
                     { format: fmtMoney, label: 'Committed against budget' })}
          <div class="viz-split">
            <span>Baseline <b>${fmtMoney(cost.baseline)}</b></span>
            <span>Additional <b>${fmtMoney(cost.additional)}</b></span>
            <span>Tasks <b>${fmtMoney(cost.tasks)}</b></span>
          </div>
        </div>
      </div>

      <div class="viz-card">
        <div class="viz-head"><h3>Tasks completed per week</h3>
          <p>The last eight weeks. The trend is ${esc(flow.throughput_trend || 'flat')}${
            flow.cycle_time_days ? `, and a task takes a median ${flow.cycle_time_days} days once started` : ''}.</p></div>
        ${vizColumns((flow.throughput || []).map(row => ({
          label: row.week_ending, short: row.week_ending.slice(5), value: row.completed
        })), { label: 'Tasks completed per week', empty: 'Nothing finished yet.' })}
        ${flow.caveat ? `<p class="viz-note">${esc(flow.caveat)}</p>` : ''}
      </div>

      <div class="viz-grid">
        <div class="viz-card">
          <div class="viz-head"><h3>Cost by trade</h3>
            <p>Where the priced work sits.</p></div>
          ${vizBars((cost.by_trade || []).slice(0, 8), { format: fmtMoney,
            empty: 'No task carries a cost yet.' })}
        </div>
        <div class="viz-card">
          <div class="viz-head"><h3>Who is carrying the work</h3>
            <p>Open and finished tasks per person.</p></div>
          ${loadRows.length ? `<div class="viz-bars">${loadRows.map(row => {
            const total = row.open + row.done || 1;
            return `<div class="viz-bar-row">
              <span class="viz-bar-label" title="${esc(row.label)}">${esc(row.label)}</span>
              <span class="viz-bar-track">
                <span class="viz-stack" style="height:100%">
                  ${row.open ? `<span class="viz-stack-seg" style="flex-grow:${row.open};background:${vizColor(VIZ_STATUS.Open)}"
                    ${tip(`${row.label} — open: ${row.open}`)}></span>` : ''}
                  ${row.done ? `<span class="viz-stack-seg" style="flex-grow:${row.done};background:${vizColor(VIZ_STATUS.Completed)}"
                    ${tip(`${row.label} — completed: ${row.done}`)}></span>` : ''}
                </span>
              </span>
              <span class="viz-bar-value">${row.open}/${total}</span>
            </div>`;
          }).join('')}</div>
          ${vizLegend([
            { label: 'Open', color: vizColor(VIZ_STATUS.Open) },
            { label: 'Completed', color: vizColor(VIZ_STATUS.Completed) }
          ])}` : vizEmpty('Nobody is assigned yet.')}
        </div>
      </div>`;
  }

  /** The same figures as a table — the accessible view, and the printable one. */
  function renderStatsTables(data) {
    const rows = [
      ['Phase', data.phase?.label],
      ['Budget at completion', fmtMoney(data.value?.budget_at_completion)],
      ['Planned value to date', fmtMoney(data.value?.planned_value)],
      ['Earned value to date', fmtMoney(data.value?.earned_value)],
      ['Schedule variance', fmtMoney(data.value?.schedule_variance)],
      ['Schedule performance index', STAT_FORMATS.index(data.value?.schedule_performance_index)],
      ['Projected finish', data.value?.projected_finish || '—'],
      ['Committed (procurement)', fmtMoney(data.cost?.committed_procurement)],
      ['Tasks completed per week', data.flow?.throughput_per_week],
      ['Cycle time (median days)', data.flow?.cycle_time_days ?? '—'],
      ['Work in progress', data.flow?.work_in_progress],
      ['Blocked', data.flow?.blocked],
      ['Overdue', data.schedule?.overdue_count],
      ['Open tasks with no dates', data.schedule?.unscheduled_count]
    ];
    return `<div class="viz-card"><div class="viz-head"><h3>Every figure</h3>
      <p>The same numbers the charts draw.</p></div>
      <div class="data-table-container"><table class="data-table">
        <thead><tr><th>Measure</th><th>Value</th></tr></thead>
        <tbody>${rows.map(([label, value]) => `<tr><td>${esc(label)}</td>
          <td>${esc(value === undefined || value === null ? '—' : String(value))}</td></tr>`).join('')}</tbody>
      </table></div>
      <div class="data-table-container" style="margin-top:12px"><table class="data-table">
        <thead><tr><th>Status</th><th>Tasks</th></tr></thead>
        <tbody>${(data.distributions?.status || []).map(row =>
          `<tr><td>${esc(row.label)}</td><td>${row.value}</td></tr>`).join('')}</tbody>
      </table></div></div>`;
  }

  function renderStatsRisks(data) {
    const risks = data.risks || [];
    if (!risks.length) {
      return `<div class="viz-card"><div class="viz-head"><h3>Attention</h3></div>
        <div class="viz-empty">Nothing was flagged against this project.</div></div>`;
    }
    return `<div class="viz-card"><div class="viz-head"><h3>Attention</h3>
      <p>Raised from the figures by rule, not by model. Each one names the number behind it.</p></div>
      <ul class="risk-list">${risks.map(row => `
        <li class="risk-row sev-${esc(row.severity)}">
          <span class="risk-dot" aria-hidden="true"></span>
          <div>
            <div class="risk-title">${esc(row.title)}
              <span class="risk-sev">${esc(row.severity)}</span></div>
            <div class="risk-detail">${esc(row.detail)}</div>
          </div>
        </li>`).join('')}</ul></div>`;
  }

  function renderStatsInsights(slice) {
    const insights = slice.insights;
    return `<div class="viz-card insight-card">
      <div class="viz-head">
        <h3><span class="material-icons-outlined">smart_toy</span> Marshal's reading</h3>
        <p>Marshal is given the figures above and asked to explain them. It is told not to
           state a number it was not given, and not to invent a cause.</p>
      </div>
      ${insights ? `
        <p class="insight-summary">${esc(insights.summary || '')}</p>
        ${insights.note ? `<p class="viz-note">${esc(insights.note)}</p>` : ''}
        <div class="insight-cols">
          ${insights.highlights?.length ? `<div><h4>Going well</h4><ul>${
            insights.highlights.map(line => `<li>${esc(line)}</li>`).join('')}</ul></div>` : ''}
          ${insights.concerns?.length ? `<div><h4>To watch</h4><ul>${
            insights.concerns.map(line => `<li>${esc(line)}</li>`).join('')}</ul></div>` : ''}
        </div>
        ${insights.actions?.length ? `<h4>Suggested next steps</h4>
          <ul class="insight-actions">${insights.actions.map(row =>
            `<li><strong>${esc(row.title)}</strong><span>${esc(row.why)}</span></li>`).join('')}</ul>` : ''}
        ${insights.outlook ? `<p class="insight-outlook">${esc(insights.outlook)}</p>` : ''}
        <button class="btn btn-ghost btn-sm" id="statsAskMarshal">
          <span class="material-icons-outlined" style="font-size:16px">refresh</span> Ask again
        </button>`
      : `<button class="btn btn-secondary" id="statsAskMarshal" ${slice.insightsLoading ? 'disabled' : ''}>
          <span class="material-icons-outlined">auto_awesome</span>
          ${slice.insightsLoading ? 'Reading the figures…' : 'Ask Marshal to read the figures'}
        </button>`}
    </div>`;
  }

  function bindStatsEvents(project) {
    const slice = statsState();
    $('#statsRefresh')?.addEventListener('click', () =>
      loadProjectStatistics(project.id, { force: true }));
    $('[data-stats-retry]')?.addEventListener('click', () =>
      loadProjectStatistics(project.id, { force: true }));
    $('#statsToggleTable')?.addEventListener('click', () => {
      slice.table = !slice.table;
      paintDashTab('stats');
    });
    $('#statsRule')?.addEventListener('change', event => {
      slice.rule = event.target.value;
      slice.insights = null;
      loadProjectStatistics(project.id, { force: true });
    });
    $('#statsAskMarshal')?.addEventListener('click', () => loadProjectInsights(project.id));
    $('#statsReport')?.addEventListener('click', () => openReportModal(project));
    bindVizTooltips(document.getElementById('dashTabContent'));
  }

  // ── The report ──────────────────────────────────────────────────────────

  async function openReportModal(project) {
    const slice = statsState().report;
    slice.open = true;
    slice.result = null;
    DOM.crudModalTitle.textContent = 'Generate a project report';
    DOM.crudModalBody.innerHTML = '<div class="empty-msg">Working out what the report would contain…</div>';
    delete DOM.btnSaveCrud.dataset.crudAction;
    DOM.btnSaveCrud.hidden = true;
    DOM.crudModal.classList.add('open');
    try {
      const [preview, listed] = await Promise.all([
        apiReq(`/api/projects/${project.id}/report/preview?rule=${statsState().rule}`).then(r => r.json()),
        apiReq(`/api/projects/${project.id}/reports`).then(r => r.json()).catch(() => ({ reports: [] }))
      ]);
      slice.preview = preview;
      slice.list = listed.reports || [];
      paintReportModal(project);
    } catch (error) {
      DOM.crudModalBody.innerHTML = `<div class="connection-banner warning">
        <span class="material-icons-outlined">warning</span><span>${esc(error.message)}</span></div>`;
    }
  }

  function paintReportModal(project) {
    const slice = statsState().report;
    const preview = slice.preview || {};
    if (slice.result) {
      const result = slice.result;
      DOM.crudModalBody.innerHTML = `
        <div class="report-done">
          <span class="material-icons-outlined">check_circle</span>
          <div>
            <strong>${esc(result.title)}</strong>
            <span>${esc(result.phase_label || '')} · ${result.sections.length} sections ·
              ${Math.round((result.size_bytes || 0) / 1024)} KB</span>
          </div>
        </div>
        ${result.narrative ? '' : `<p class="viz-note">${esc(result.insights?.note
          || 'Written from the figures alone; Marshal was not reachable.')}</p>`}
        <div class="onb-actions">
          <button class="btn btn-primary" id="reportDownload">
            <span class="material-icons-outlined">download</span> Download PDF</button>
          <button class="btn btn-secondary" id="reportAnother">Generate another</button>
        </div>`;
      $('#reportDownload')?.addEventListener('click', () => downloadReport(result.id, result.title));
      $('#reportAnother')?.addEventListener('click', () => {
        slice.result = null;
        paintReportModal(project);
      });
      return;
    }

    DOM.crudModalBody.innerHTML = `
      <p class="form-hint">The report suits the stage the project has reached. Everything in it is
        computed from this workspace's own records; the Basis section says exactly how.</p>
      <div class="report-phase">
        <span class="stats-phase-badge">${esc(preview.phase?.label || '')}</span>
        <span>${esc(preview.phase?.reason || '')}</span>
      </div>
      <div class="form-group">
        <label class="form-label" for="reportTitle">Title</label>
        <input class="form-input" id="reportTitle" value="${esc(preview.title || '')}">
      </div>
      <div class="form-group">
        <label class="form-label">Sections</label>
        <div class="report-sections">${(preview.sections || []).map(row =>
          `<span class="onb-chip">${esc(row.heading)}</span>`).join('')}</div>
        <div class="form-hint">Chosen for this stage. A section with nothing to report is left out.</div>
      </div>
      <div class="form-group">
        <label class="form-label" for="reportInstructions">Anything Marshal should focus on (optional)</label>
        <input class="form-input" id="reportInstructions" placeholder="e.g. explain the glazing delay">
      </div>
      <label class="perm-row">
        <input type="checkbox" id="reportNarrative" ${slice.narrative ? 'checked' : ''}>
        <span><strong class="perm-name">Let Marshal write the commentary</strong>
        <span class="perm-desc">Off writes the report from the figures alone.</span></span>
      </label>
      ${slice.list.length ? `<h4 class="onb-plan-head">Earlier reports</h4>
        <div class="data-table-container"><table class="data-table">
          <thead><tr><th>Report</th><th>Stage</th><th>When</th><th></th></tr></thead>
          <tbody>${slice.list.slice(0, 6).map(row => `<tr>
            <td>${esc(row.title)}</td><td>${esc(row.phase_label || '—')}</td>
            <td>${esc((row.generated_at || '').slice(0, 10))}</td>
            <td><button class="btn-table-action" data-report-download="${esc(row.id)}"
              data-title="${esc(row.title)}" title="Download">
              <span class="material-icons-outlined">download</span></button></td>
          </tr>`).join('')}</tbody></table></div>` : ''}
      <div class="onb-actions">
        <button class="btn btn-primary" id="reportGenerate" ${slice.busy ? 'disabled' : ''}>
          <span class="material-icons-outlined">${slice.busy ? 'hourglass_top' : 'description'}</span>
          ${slice.busy ? 'Writing…' : 'Generate report'}
        </button>
      </div>`;

    $('#reportGenerate')?.addEventListener('click', () => generateReport(project));
    $$('[data-report-download]').forEach(button => button.addEventListener('click', () =>
      downloadReport(button.dataset.reportDownload, button.dataset.title)));
  }

  async function generateReport(project) {
    const slice = statsState().report;
    slice.busy = true;
    slice.narrative = !!$('#reportNarrative')?.checked;
    const payload = {
      title: $('#reportTitle')?.value.trim() || '',
      instructions: $('#reportInstructions')?.value.trim() || '',
      rule: statsState().rule,
      narrative: slice.narrative
    };
    paintReportModal(project);
    try {
      const response = await apiReq(`/api/projects/${project.id}/report`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      slice.result = await response.json();
      showToast('Report ready', 'success');
    } catch (error) {
      showToast(error.message, 'error', 7000);
    } finally {
      slice.busy = false;
      paintReportModal(project);
    }
  }

  /** Fetch through apiReq so the download carries the session, then save it. */
  async function downloadReport(reportId, title) {
    try {
      const response = await apiReq(`/api/generated-documents/${reportId}/download`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${(title || 'project-report').replace(/[^A-Za-z0-9._-]+/g, '_')}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (error) {
      showToast(error.message, 'error', 6000);
    }
  }

  // ── Document storage ────────────────────────────────────────────────────

  function storageState() {
    if (!state.storage) {
      state.storage = { data: null, loading: false, error: '', busy: false,
                        chosen: ['orphans'], open: false };
    }
    return state.storage;
  }

  async function loadStorage({ force = false } = {}) {
    const slice = storageState();
    if (slice.loading || (slice.data && !force)) return;
    slice.loading = true;
    try {
      slice.data = await apiReq('/api/storage').then(response => response.json());
      slice.error = '';
    } catch (error) {
      slice.error = error.message;
    } finally {
      slice.loading = false;
      if (state.currentPage === 'documents') renderPage();
    }
  }

  function renderStoragePanel() {
    const slice = storageState();
    if (!slice.open) {
      return `<div class="storage-teaser">
        <span class="material-icons-outlined">hard_drive</span>
        <div>
          <strong>Document storage</strong>
          <span>${slice.data
            ? `${esc(slice.data.total_human)} used${slice.data.reclaimable_bytes
                ? ` · ${esc(slice.data.reclaimable_human)} reclaimable` : ''}`
            : 'See what the indexed documents cost, and reclaim what is no longer needed.'}</span>
        </div>
        <button class="btn btn-secondary btn-sm" id="btnStorageOpen">Manage</button>
      </div>`;
    }
    if (slice.error) {
      return `<div class="connection-banner warning"><span class="material-icons-outlined">warning</span>
        <span>${esc(slice.error)}</span>
        <button class="btn btn-secondary btn-sm" id="btnStorageRefresh">Retry</button></div>`;
    }
    const data = slice.data;
    if (!data) return '<div class="storage-panel"><div class="empty-msg">Measuring the workspace…</div></div>';

    const areas = (data.areas || []).filter(row => row.bytes > 0);
    const largest = Math.max(1, ...areas.map(row => row.bytes));
    const canEdit = isAccountAdmin();

    return `<div class="storage-panel">
      <div class="storage-head">
        <div>
          <h3>Document storage</h3>
          <p>Indexing a page costs far more than the page: an original, a rendered image,
             a ColPali vector, a pooled vector and often a tile. This is where that has gone.</p>
        </div>
        <div class="storage-head-actions">
          <button class="btn btn-ghost btn-sm" id="btnStorageRefresh">
            <span class="material-icons-outlined" style="font-size:16px">refresh</span> Refresh</button>
          <button class="btn btn-ghost btn-sm" id="btnStorageClose">Close</button>
        </div>
      </div>

      <div class="stat-row">
        <div class="stat-tile"><div class="stat-tile-label">Used</div>
          <div class="stat-tile-value">${esc(data.total_human)}</div></div>
        <div class="stat-tile ${data.over_budget ? 'tone-bad' : ''}">
          <div class="stat-tile-label">Budget</div>
          <div class="stat-tile-value">${esc(data.budget_human)}</div>
          <div class="stat-tile-note">${data.budget_used !== null
            ? `${Math.round(data.budget_used * 100)}% used` : 'no budget set'}</div></div>
        <div class="stat-tile ${data.reclaimable_bytes ? 'tone-good' : ''}">
          <div class="stat-tile-label">Reclaimable</div>
          <div class="stat-tile-value">${esc(data.reclaimable_human)}</div></div>
        <div class="stat-tile"><div class="stat-tile-label">Documents</div>
          <div class="stat-tile-value">${data.document_count}</div></div>
      </div>

      <div class="viz-card">
        <div class="viz-head"><h3>Where the space is</h3>
          <p>Only the rebuildable areas can be reclaimed; an original upload never is.</p></div>
        <div class="viz-bars">${areas.map(row => `
          <div class="viz-bar-row" ${tip(`${row.label}: ${row.human} across ${row.files} file(s). ${row.detail}`)}>
            <span class="viz-bar-label" title="${esc(row.detail)}">${esc(row.label)}</span>
            <span class="viz-bar-track">
              <span class="viz-bar-fill" style="width:${Math.max(1, (row.bytes / largest) * 100)}%;
                background:${row.reclaimable ? vizColor(2) : vizColor(0)}"></span>
            </span>
            <span class="viz-bar-value">${esc(row.human)}</span>
          </div>`).join('')}</div>
        ${vizLegend([
          { label: 'Cannot be rebuilt', color: vizColor(0) },
          { label: 'Rebuildable — safe to reclaim', color: vizColor(2) }
        ])}
      </div>

      <div class="viz-card">
        <div class="viz-head"><h3>Reclaim space</h3>
          <p>Nothing is removed until you confirm, and the confirmation lists exactly what goes.</p></div>
        <div class="sweep-actions">${(data.plan?.actions || []).map(action => `
          <label class="perm-row">
            <input type="checkbox" class="sweep-action" value="${esc(action.key)}"
              ${slice.chosen.includes(action.key) ? 'checked' : ''} ${canEdit ? '' : 'disabled'}>
            <span>
              <strong class="perm-name">${esc(action.label)}
                ${action.safe ? '<span class="onb-chip">always safe</span>' : ''}</strong>
              <span class="perm-desc">Would reclaim ${esc(action.human)}${
                action.count ? ` across ${action.count} item(s)` : ''}.${
                action.detail?.note ? ` ${esc(action.detail.note)}` : ''}</span>
            </span>
          </label>`).join('')}</div>
        ${canEdit ? `<div class="onb-actions">
          <button class="btn btn-primary" id="btnStorageSweep" ${slice.busy ? 'disabled' : ''}>
            <span class="material-icons-outlined">cleaning_services</span>
            ${slice.busy ? 'Reclaiming…' : 'Review and reclaim'}
          </button>
        </div>` : '<p class="viz-note">Only an administrator can reclaim space.</p>'}
      </div>

      ${canEdit ? `<div class="viz-card">
        <div class="viz-head"><h3>Policy</h3>
          <p>What "too big" and "cold" mean for this workspace.</p></div>
        <div class="storage-policy">
          <label class="form-group"><span class="form-label">Budget (MB)</span>
            <input class="form-input" type="number" min="0" id="policyBudget"
              value="${data.policy.budget_mb}"></label>
          <label class="form-group"><span class="form-label">Keep warm (days)</span>
            <input class="form-input" type="number" min="0" id="policyWarm"
              value="${data.policy.keep_warm_days}"></label>
          <label class="form-group"><span class="form-label">Page max edge (px)</span>
            <input class="form-input" type="number" min="256" max="4096" id="policyEdge"
              value="${data.policy.page_max_edge}"></label>
          <label class="form-group"><span class="form-label">Page quality</span>
            <input class="form-input" type="number" min="30" max="100" id="policyQuality"
              value="${data.policy.page_quality}"></label>
        </div>
        <label class="perm-row">
          <input type="checkbox" id="policyDedupe" ${data.policy.deduplicate ? 'checked' : ''}>
          <span><strong class="perm-name">Reuse an identical upload</strong>
          <span class="perm-desc">The same file uploaded twice is matched by content
            and the existing copy is reused, rather than indexed again.</span></span>
        </label>
        <div class="onb-actions"><button class="btn btn-secondary" id="btnStoragePolicy">Save policy</button></div>
      </div>` : ''}

      ${(data.documents || []).length ? `<div class="viz-card">
        <div class="viz-head"><h3>Largest documents</h3></div>
        <div class="data-table-container"><table class="data-table">
          <thead><tr><th>Document</th><th>Pages</th><th>Total</th>
            <th class="hide-mobile">Rebuildable</th><th class="hide-mobile">Last read</th></tr></thead>
          <tbody>${data.documents.slice(0, 12).map(row => `<tr>
            <td>${esc(row.name)}</td><td>${row.pages}</td><td>${esc(row.human)}</td>
            <td class="hide-mobile">${esc(humanBytesJs(row.reclaimable))}</td>
            <td class="hide-mobile">${esc((row.last_used || '').slice(0, 10) || '—')}</td>
          </tr>`).join('')}</tbody></table></div>
      </div>` : ''}
    </div>`;
  }

  function humanBytesJs(size) {
    let value = Number(size || 0);
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let index = 0;
    while (Math.abs(value) >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
    return index === 0 ? `${Math.round(value)} B` : `${value.toFixed(1)} ${units[index]}`;
  }

  async function sweepStorage() {
    const slice = storageState();
    const actions = [...document.querySelectorAll('.sweep-action:checked')].map(box => box.value);
    if (!actions.length) { showToast('Choose at least one thing to reclaim', 'warning'); return; }
    slice.chosen = actions;
    slice.busy = true;
    renderPage();
    try {
      const plan = await apiReq('/api/storage/sweep', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actions })
      }).then(response => response.json());

      const lines = (plan.actions || [])
        .filter(row => row.bytes || row.count)
        .map(row => `• ${row.label}: ${row.human}${row.count ? ` (${row.count} item(s))` : ''}`);
      if (!lines.length) { showToast('There is nothing to reclaim right now', 'info'); return; }
      if (!confirm(`This will reclaim ${plan.human}:\n\n${lines.join('\n')}\n\nOriginal uploads are never touched. Continue?`)) return;

      const done = await apiReq('/api/storage/sweep', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actions, confirm: true })
      }).then(response => response.json());
      slice.data = done.storage;
      showToast(`Reclaimed ${done.human}`, 'success', 6000);
      fetchDocuments();
    } catch (error) {
      showToast(error.message, 'error', 7000);
    } finally {
      slice.busy = false;
      renderPage();
    }
  }

  async function saveStoragePolicy() {
    try {
      await apiReq('/api/storage/policy', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          budget_mb: Number($('#policyBudget')?.value || 0),
          keep_warm_days: Number($('#policyWarm')?.value || 0),
          page_max_edge: Number($('#policyEdge')?.value || 1400),
          page_quality: Number($('#policyQuality')?.value || 82),
          deduplicate: !!$('#policyDedupe')?.checked
        })
      });
      showToast('Policy saved', 'success');
      loadStorage({ force: true });
    } catch (error) {
      showToast(error.message, 'error', 6000);
    }
  }

  function bindStorageEvents() {
    const slice = storageState();
    $('#btnStorageOpen')?.addEventListener('click', () => {
      slice.open = true;
      renderPage();
      loadStorage();
    });
    $('#btnStorageClose')?.addEventListener('click', () => { slice.open = false; renderPage(); });
    $('#btnStorageRefresh')?.addEventListener('click', () => loadStorage({ force: true }));
    $('#btnStorageSweep')?.addEventListener('click', sweepStorage);
    $('#btnStoragePolicy')?.addEventListener('click', saveStoragePolicy);
    bindVizTooltips(DOM.contentArea);
  }

  // ── Creating a project or a user from a chat sentence ───────────────────
  //
  // The sentence is read by the server, which knows the schema; this side only
  // shows what came back and lets the ordinary create routes do the creating.

  /** A cheap superset of the server's own create verbs.
   *
   * Only here to avoid a round trip on every document question -- the server
   * decides what is really a creation request.
   */
  const MIGHT_CREATE = /\b(?:creat\w*|add|make|set\s*up|setup|register|open|start|new)\b/i;

  /** A temporary password for a brand-new account, generated in the browser.
   *
   * Shown to the administrator to pass on, never stored here, and meant to be
   * changed on first sign-in.
   */
  function temporaryPassword() {
    const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
    const bytes = new Uint32Array(16);
    crypto.getRandomValues(bytes);
    return [...bytes].map(value => alphabet[value % alphabet.length]).join('');
  }

  //: The record being collected, while any mandatory field is still missing.
  //: Null the rest of the time, and every message goes through it while it is
  //: not: that is what lets "October 1" be read as an answer to a question.
  let entityCollection = null;

  const GIVE_UP = /^\s*(?:cancel|stop|never\s*mind|nevermind|forget\s+it|abort|leave\s+it)\b/i;

  /** The question to ask for what is still outstanding.
   *
   * `moved` says whether the last message added anything. Repeating a question
   * verbatim after a reply that was not understood reads as if the reply never
   * arrived, so that case says so instead.
   */
  function askForMissing(result, moved, collecting) {
    const rows = result.chat_missing || [];
    const labels = rows.map(row => `**${esc(row.label)}**`);
    const list = labels.length > 1
      ? `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`
      : labels[0];

    // A reference is answered with the name of a record that exists, so the
    // ones that exist are offered rather than left to be guessed at.
    const choices = result.choices || {};
    const hints = rows.map(row => {
      const rowsFor = row.name === result.parent_field
        ? ((result.parent && result.parent.options) || [])
        : (choices[row.name] || []);
      if (!rowsFor.length || rowsFor.length > 8) return '';
      return `\n- **${esc(row.label)}** — one of: ${
        rowsFor.map(one => esc(one.label)).join(', ')}`;
    }).filter(Boolean).join('');

    const opening = moved ? 'Got it.'
      : collecting ? 'I did not catch that.'
      : `Sure — I can create a ${esc(String(result.label).toLowerCase())}.`;
    const settled = result.summary ? `\n\nSo far: ${esc(result.summary)}` : '';
    return `${opening} I still need ${list}.${settled}${hints}`;
  }

  async function handleEntityCreateRequest(text) {
    const collecting = !!entityCollection;
    if (!collecting && (!text || !MIGHT_CREATE.test(text))) return null;

    if (collecting && GIVE_UP.test(text)) {
      const what = String(entityCollection.label || 'record').toLowerCase();
      entityCollection = null;
      return `Stopped — no ${esc(what)} was created. Nothing was saved.`;
    }

    const payload = collecting
      ? { text, kind: entityCollection.kind, known: entityCollection.known,
          asking: entityCollection.asking, parent_id: entityCollection.parentId }
      : { text, parent_id: state.activeProjectId || '' };

    let result;
    try {
      const response = await apiReq('/api/assistant/entities/interpret', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      result = await response.json();
    } catch (error) {
      // A refusal here is about permission, and saying so beats a document search.
      if (/permission|administrator|Sign in/i.test(error.message)) {
        entityCollection = null;
        return error.message;
      }
      return null;
    }

    if (!result.supported) {
      if (result.reason === 'use_onboarding') {
        entityCollection = null;
        return `A **${esc(result.label || result.kind)}** belongs to a draft you can review ` +
          `first — open **Onboarding**, start one, and tell me the same thing there and I ` +
          `will build it with everything it depends on.`;
      }
      return null;   // not a creation request; let the document search answer
    }

    const fields = result.fields || {};
    const parentId = (result.parent && result.parent.id) || '';
    const known = entityCollection ? entityCollection.known : {};
    const moved = Object.keys(fields).length > Object.keys(known).length
      || (!!parentId && parentId !== (entityCollection && entityCollection.parentId));

    if (!result.ready) {
      // A message that answered nothing, and is a question of its own, belongs
      // to the document search — a half-filled form must not swallow it.
      if (collecting && !moved && /\?\s*$/.test(text)) {
        entityCollection = null;
        return null;
      }
      entityCollection = {
        kind: result.kind, label: result.label, known: fields, parentId,
        asking: (result.chat_missing || []).map(row => row.name),
      };
      return askForMissing(result, collecting && moved, collecting);
    }

    entityCollection = null;
    if (result.kind === 'project') openChatProjectForm(result);
    else if (result.kind === 'user') openChatUserForm(result);
    else openChatEntityForm(result);

    const understood = result.summary
      ? `That is everything — **${esc(result.label)}**\n\n${esc(result.summary)}`
      : `That is everything I need for a **${esc(String(result.label).toLowerCase())}**.`;
    return `${understood}\n\nI have opened the form with it all filled in. ` +
      `Check it over and press Create.`;
  }

  function openChatProjectForm(result) {
    openProjectModal(null, { ...result.fields, status: result.fields.status || 'Active' },
                     result.missing);
  }

  function openChatUserForm(result) {
    const seed = result.fields || {};
    DOM.crudModalTitle.textContent = 'Create User';
    DOM.crudModalBody.innerHTML = `
      <p class="viz-note" style="margin-bottom:12px">Marshal filled in what your message gave.
        A temporary password has been generated — copy it now, it is not shown again, and
        the person should change it when they first sign in.</p>
      ${userFormFields(seed)}`;
    DOM.btnSaveCrud.hidden = false;
    DOM.btnSaveCrud.textContent = 'Create user';
    DOM.btnSaveCrud.dataset.crudAction = 'save-chat-user';
    DOM.btnSaveCrud.dataset.crudId = '';
    DOM.crudModal.classList.add('open');

    // A new account still needs a first password; generating one is kinder than
    // asking an administrator to invent it, and it is visible so it can be passed on.
    const generated = temporaryPassword();
    const password = $('#ufPassword');
    const confirmField = $('#ufConfirmPassword');
    if (password && confirmField) {
      password.value = generated;
      confirmField.value = generated;
      password.type = 'text';
      confirmField.type = 'text';
    }
    bindPasswordToggles();
    markMissingFields({ name: 'ufName', email: 'ufEmail', role: 'ufRole',
                        phone: 'ufPhone', address: 'ufAddress' }, result.missing);
  }

  // ═══ Creating any other record from chat ═══════════════════════════════
  //
  // One form for every kind that is not a project or a user, built from the
  // schema the server sends rather than from a layout written per kind: eight
  // bespoke forms would be eight places to forget a field when the schema
  // gains one. Nothing here decides what is mandatory — the server says which
  // fields are missing and the create route has the final word.

  /** Where each kind is written. `parent` is the chosen parent row, whose
   *  `detail` carries the project a task belongs to. */
  const CHAT_ENTITY_ROUTES = {
    task:         parent => ({ path: `/api/projects/${parent.id}/tasks` }),
    project_cost: parent => ({ path: `/api/projects/${parent.id}/costs` }),
    procurement:  parent => ({ path: `/api/projects/${parent.id}/procurement` }),
    // A task's cost is a field of the task, not a record of its own, so it is
    // written by updating the task it belongs to.
    task_cost:    parent => ({ path: `/api/projects/${parent.detail}/tasks/${parent.id}`,
                               method: 'PUT' }),
    task_type:    () => ({ path: '/api/task-types' }),
    project_type: () => ({ path: '/api/project-types' }),
    trade:        () => ({ path: '/api/trades' }),
    vendor:       () => ({ path: '/api/vendors' }),
    role_type:    () => ({ path: '/api/user-roles' }),
  };

  /** Kinds whose form fields are not the create route's field names. */
  const CHAT_ENTITY_PAYLOAD = {
    task_cost: body => ({ cost: body.amount }),
  };

  /** What to reload once the record exists, so the rest of the app catches up. */
  const CHAT_ENTITY_REFRESH = {
    task_type: () => fetchTaskTypes(),
    project_type: () => fetchProjectTypes(),
    role_type: () => fetchUserRoles(),
    trade: () => fetchTrades(),
    vendor: () => fetchVendors(),
  };

  //: Held here rather than on a data attribute: the reply carries every
  //: reference list, which is far more than an attribute should hold.
  let pendingChatEntity = null;

  const chatFieldId = name => `ce_${String(name).replace(/[^\w]/g, '')}`;

  /** A datetime input needs a time; a date read from a sentence has none. */
  function forDateTimeInput(value) {
    const text = String(value || '');
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return `${text}T09:00`;
    return text.replace(' ', 'T').slice(0, 16);
  }

  function chatFieldControl(field, value, choices) {
    const id = chatFieldId(field.name);
    if (field.type === 'textarea') {
      return `<textarea class="form-input" id="${id}" rows="3">${esc(value || '')}</textarea>`;
    }
    if (field.type === 'select' || field.type === 'reference') {
      const rows = field.type === 'reference'
        ? (choices[field.name] || []).map(row => String(row.label))
        : (field.options || []);
      const chosen = String(value == null ? '' : value);
      const options = rows.map(row =>
        `<option value="${esc(row)}"${chosen === String(row) ? ' selected' : ''}>${esc(row)}</option>`).join('');
      // An empty reference list is stated, not left as a blank dropdown that
      // looks broken. Nothing can be invented to fill it.
      const empty = (field.type === 'reference' && !rows.length)
        ? '<option value="" disabled>none exist yet — add one first</option>' : '';
      return `<select class="form-input" id="${id}">` +
        `<option value="">${field.required ? 'Select…' : '—'}</option>${empty}${options}</select>`;
    }
    const inputType = { number: 'number', money: 'number',
                        date: 'date', datetime: 'datetime-local' }[field.type] || 'text';
    const shown = field.type === 'datetime' ? forDateTimeInput(value) : (value == null ? '' : value);
    const step = field.type === 'money' ? ' step="0.01"' : '';
    return `<input class="form-input" type="${inputType}" id="${id}" value="${esc(shown)}"${step}>`;
  }

  function chatEntityFormHtml(result) {
    const fields = ((result.spec && result.spec.fields) || [])
      // A permission set is chosen in the role editor, which is built for it.
      .filter(field => field.type !== 'permissions');
    const values = result.fields || {};
    const choices = result.choices || {};
    const parent = result.parent;

    const parentRow = parent ? `
      <div class="form-group">
        <label class="form-label required-label">${esc(parent.label)}</label>
        <select class="form-input" id="ce_parent">
          <option value="">Select…</option>
          ${(parent.options || []).map(row => `<option value="${esc(row.id)}" data-detail="${
            esc(row.detail || '')}"${row.id === parent.id ? ' selected' : ''}>${esc(row.label)}${
            // A task's detail is the id of its project, which is not a label.
            (row.detail && parent.kind !== 'task') ? ` — ${esc(row.detail)}` : ''
          }</option>`).join('')}
        </select>
      </div>` : '';

    const rows = fields.map(field => `
      <div class="form-group">
        <label class="form-label${field.required ? ' required-label' : ''}">${esc(field.label)}</label>
        ${chatFieldControl(field, values[field.name], choices)}
        ${field.help ? `<p class="form-hint">${esc(field.help)}</p>` : ''}
      </div>`).join('');

    const note = (result.spec || {}).kind === 'role_type'
      ? `<p class="viz-note" style="margin-bottom:12px">Marshal filled in what your message gave.
           The role is created with no permissions — set those in
           <strong>Company Settings → User Roles</strong>.</p>`
      : `<p class="viz-note" style="margin-bottom:12px">Marshal filled in what your message gave.
           Anything it was not told is blank rather than guessed — check it and press Create.</p>`;

    return `${note}<div class="user-form-grid">${parentRow}${rows}</div>`;
  }

  function openChatEntityForm(result) {
    pendingChatEntity = result;
    DOM.crudModalTitle.textContent = `Create ${result.label}`;
    DOM.crudModalBody.innerHTML = chatEntityFormHtml(result);
    DOM.btnSaveCrud.hidden = false;
    DOM.btnSaveCrud.textContent = `Create ${String(result.label).toLowerCase()}`;
    DOM.btnSaveCrud.dataset.crudAction = 'save-chat-entity';
    DOM.btnSaveCrud.dataset.crudId = '';
    DOM.crudModal.classList.add('open');

    // Everything the server said was missing is highlighted, including the
    // parent, and the first of them takes the cursor.
    const ids = {};
    ((result.spec && result.spec.fields) || []).forEach(field => {
      ids[field.name] = chatFieldId(field.name);
    });
    if (result.parent_field) ids[result.parent_field] = 'ce_parent';
    markMissingFields(ids, result.missing);
  }

  async function submitChatEntity() {
    const result = pendingChatEntity;
    if (!result) return;
    const build = CHAT_ENTITY_ROUTES[result.kind];
    if (!build) { showToast(`I cannot create a ${result.label} yet`, 'error'); return; }

    const fields = ((result.spec && result.spec.fields) || [])
      .filter(field => field.type !== 'permissions');
    const body = {};
    fields.forEach(field => {
      const element = document.getElementById(chatFieldId(field.name));
      if (!element) return;
      const value = String(element.value || '').trim();
      if (value !== '') body[field.name] = value;
    });

    const parentSelect = document.getElementById('ce_parent');
    const parentId = parentSelect ? String(parentSelect.value || '') : '';
    const chosen = parentSelect && parentSelect.selectedOptions[0];
    const parent = { id: parentId, detail: chosen ? (chosen.dataset.detail || '') : '' };

    // The server decides what is mandatory; this only avoids a round trip that
    // would come back saying the same thing.
    const short = fields.filter(field => field.required && !body[field.name])
                        .map(field => field.label);
    if (result.parent && !parentId) short.unshift(result.parent.label);
    if (short.length) {
      showToast(`${short.join(', ')} ${short.length > 1 ? 'are' : 'is'} required`, 'warning');
      return;
    }

    DOM.btnSaveCrud.disabled = true;
    const label = DOM.btnSaveCrud.textContent;
    DOM.btnSaveCrud.textContent = 'Creating…';
    try {
      const target = build(parent);
      const shape = CHAT_ENTITY_PAYLOAD[result.kind];
      await apiReq(target.path, {
        method: target.method || 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(shape ? shape(body) : body),
      });
      const refresh = CHAT_ENTITY_REFRESH[result.kind];
      if (refresh) { try { await refresh(); } catch (e) { /* the record exists either way */ } }
      if (parentId && parentId === state.activeProjectId) {
        try { await fetchProjectTasks(parentId); } catch (e) { /* as above */ }
      }
      closeCrudModal();
      pendingChatEntity = null;
      const where = result.stored_in ? ` It is in **${esc(result.stored_in)}**.` : '';
      addMessage('bot', `Created **${esc(body.name || result.label)}**.${where}`);
      renderChatMessages();
      renderPage();
      showToast(`${result.label} created`, 'success');
    } catch (error) {
      DOM.btnSaveCrud.disabled = false;
      DOM.btnSaveCrud.textContent = label;
      showToast(error.message, 'error', 8000);
    }
  }

  // ═══ Chat Panel — window states (minimized ↔ docked ↔ full screen) ═══
  const CHAT_STATE_KEY = 'bm_chat_window_state';
  const CHAT_WINDOW_STATES = ['normal', 'minimized', 'maximized'];
  let chatWindowState = 'normal';

  function readSavedChatWindowState() {
    try {
      const saved = localStorage.getItem(CHAT_STATE_KEY);
      return CHAT_WINDOW_STATES.includes(saved) ? saved : 'normal';
    } catch (e) { return 'normal'; }
  }

  // Single place that maps a window state onto the DOM.
  function applyChatWindowState(next, persist = true) {
    if (!CHAT_WINDOW_STATES.includes(next)) next = 'normal';
    const panel = DOM.chatPanel;
    if (!panel) return;
    chatWindowState = next;

    panel.classList.toggle('chat-minimized', next === 'minimized');
    panel.classList.toggle('chat-maximized', next === 'maximized');
    document.body.classList.toggle('chat-pill-open', next === 'minimized');
    if (next !== 'minimized') panel.classList.remove('has-unread');

    // The dimming overlay only belongs to the docked slide-over state
    if (next === 'normal' && panel.classList.contains('visible')) DOM.chatOverlay.classList.add('open');
    else DOM.chatOverlay.classList.remove('open');

    // History dropdown has nowhere to go inside a 56px pill
    if (next === 'minimized') closeChatHistory();

    const btnMax = $('#btnChatMaximize');
    const iconMax = $('#btnChatMaximizeIcon');
    if (iconMax) iconMax.textContent = next === 'maximized' ? 'close_fullscreen' : 'open_in_full';
    if (btnMax) {
      const label = next === 'maximized' ? 'Exit full screen' : 'Full screen';
      btnMax.title = label;
      btnMax.setAttribute('aria-label', label);
      btnMax.setAttribute('aria-pressed', String(next === 'maximized'));
    }
    const title = $('#chatPanelTitle');
    if (title) {
      title.title = next === 'minimized' ? 'Click to restore' : 'Double-click to toggle full screen';
      title.setAttribute('aria-label', next === 'minimized' ? 'Restore chat' : 'Marshal chat');
    }

    if (persist) { try { localStorage.setItem(CHAT_STATE_KEY, next); } catch (e) { /* storage disabled */ } }
    if (next !== 'minimized') scrollChatBottom();
  }

  function openChatPanel() { DOM.chatPanel.classList.add('visible'); DOM.chatPanel.classList.remove('collapsed'); }

  function showChat() {
    openChatPanel();
    // Reopening from the pill should give back a usable panel
    applyChatWindowState(chatWindowState === 'minimized' ? 'normal' : chatWindowState);
  }
  function hideChat() {
    DOM.chatPanel.classList.remove('visible');
    DOM.chatPanel.classList.add('collapsed');
    DOM.chatOverlay.classList.remove('open');
    // Closing always resets the window state so the next open is predictable
    if (chatWindowState !== 'normal') applyChatWindowState('normal');
  }
  function toggleChat() { DOM.chatPanel.classList.contains('collapsed') ? showChat() : hideChat(); }

  function minimizeChat() { openChatPanel(); applyChatWindowState('minimized'); }
  function restoreChat() { openChatPanel(); applyChatWindowState('normal'); }
  function maximizeChat() { openChatPanel(); applyChatWindowState('maximized'); }
  function toggleChatMaximize() {
    // On phones the docked panel already fills the screen, so this control
    // only ever expands the pill back out.
    if (window.innerWidth <= 768 && chatWindowState !== 'maximized') { restoreChat(); return; }
    chatWindowState === 'maximized' ? restoreChat() : maximizeChat();
  }

  function initChatWindowControls() {
    const panel = DOM.chatPanel;
    if (!panel) return;

    const btnMin = $('#btnChatMinimize');
    const btnMax = $('#btnChatMaximize');
    const title = $('#chatPanelTitle');

    if (btnMin) btnMin.addEventListener('click', e => { e.stopPropagation(); minimizeChat(); });
    if (btnMax) btnMax.addEventListener('click', e => { e.stopPropagation(); toggleChatMaximize(); });

    if (title) {
      title.addEventListener('click', () => { if (chatWindowState === 'minimized') restoreChat(); });
      title.addEventListener('dblclick', () => { if (chatWindowState !== 'minimized') toggleChatMaximize(); });
      title.addEventListener('keydown', e => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        chatWindowState === 'minimized' ? restoreChat() : toggleChatMaximize();
      });
    }

    // Clicking anywhere on the collapsed pill brings the panel back
    panel.addEventListener('click', e => {
      if (chatWindowState !== 'minimized') return;
      if (e.target.closest('.chat-header-actions')) return;
      restoreChat();
    });

    // Esc leaves full screen before it reaches the modal handlers
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && chatWindowState === 'maximized') restoreChat();
    });

    // Only rehydrate where the panel is docked open by default; below that
    // breakpoint the chat starts closed and a stray pill would be confusing.
    // Skip the transition so a saved state doesn't visibly animate on load.
    panel.classList.add('chat-no-anim');
    applyChatWindowState(window.innerWidth > 1200 ? readSavedChatWindowState() : 'normal', false);
    requestAnimationFrame(() => requestAnimationFrame(() => panel.classList.remove('chat-no-anim')));
  }

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
      // Only on desktop (> 1200px), and only while docked
      if (window.innerWidth <= 1200 || chatWindowState !== 'normal') return;
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
      return `<div class="chat-history-item ${isActive ? 'active' : ''}" data-chat-id="${chat.id}" >
        <span class="material-icons-outlined chat-history-icon">chat_bubble_outline</span>
        <div class="chat-history-info">
          <div class="chat-history-title">${esc(chat.title || 'New Chat')}</div>
          <div class="chat-history-meta"><span>${msgCount} message${msgCount !== 1 ? 's' : ''}</span><span>${dateStr}</span></div>
        </div>
        <button class="chat-history-delete" data-delete-id="${chat.id}" title="Delete chat">
          <span class="material-icons-outlined">delete_outline</span>
        </button>
      </div> `;
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

  function regexEscape(value) { return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  function highlightEvidence(text, terms) {
    const useful = [...new Set((terms || []).filter(Boolean))].sort((a, b) => b.length - a.length);
    if (!useful.length) return esc(text || 'No extractable text was found on this page.');
    const matcher = new RegExp(`(\\b(?:${useful.map(regexEscape).join('|')})\\b)`, 'gi');
    return String(text || '').split(matcher).map(part =>
      useful.some(term => term.toLowerCase() === part.toLowerCase())
        ? `<mark>${esc(part)}</mark>`
        : esc(part)
    ).join('');
  }

  function renderEvidenceBody(source, detail = {}) {
    const page = detail.page || source.page || 1;
    const docId = detail.doc_id || source.doc_id;
    const imageEndpoint = detail.image_endpoint || `/api/pages/${encodeURIComponent(docId)}/${page}`;
    // The chat reply already embeds the page as a data URI, so use it when it
    // is there; otherwise the image is fetched with the session token, because
    // an <img src> cannot carry an Authorization header.
    const inlineImage = source.image_url && String(source.image_url).startsWith('data:')
      ? source.image_url : '';
    const score = Math.max(0, Math.min(1, Number(source.score || 0)));
    const breakdown = source.score_breakdown || {};
    const bars = [
      ['Text match', breakdown.text, 'text_fields'],
      ['ColPali visual', breakdown.colpali, 'image_search'],
      ['Vector candidate', breakdown.vector, 'hub']
    ].filter(([, value]) => Number.isFinite(Number(value)));
    const matchedTerms = detail.matched_terms?.length ? detail.matched_terms : (source.matched_terms || []);
    const evidenceText = detail.evidence_text || source.evidence_text || 'No extractable text was found on this page. Inspect the page image directly.';
    const method = source.retrieval_method || 'Hybrid retrieval';

    DOM.evidenceBody.innerHTML = `<div class="evidence-layout">
      <section class="evidence-page-panel">
        <div class="evidence-page-toolbar">
          <span class="evidence-rank">Source ${source.rank || '?'}</span>
          <span class="evidence-score">${Math.round(score * 100)}% relevance</span>
          <button class="btn btn-ghost btn-sm" id="btnZoomEvidence"><span class="material-icons-outlined">zoom_in</span> Enlarge</button>
        </div>
        <div class="evidence-page-canvas evidence-page-figure">${inlineImage
          ? `<img id="evidencePageImage" src="${esc(inlineImage)}" alt="${esc(source.doc_name || 'Document')} page ${page}">`
          : `<img id="evidencePageImage" data-authsrc="${esc(imageEndpoint)}" data-auth-fallback="Page image unavailable" alt="${esc(source.doc_name || 'Document')} page ${page}">`}</div>
      </section>
      <aside class="evidence-inspector">
        <div class="evidence-section">
          <div class="evidence-section-label">Why this page was selected</div>
          <div class="retrieval-method"><span class="material-icons-outlined">verified</span>${esc(method)}</div>
          ${bars.length ? `<div class="evidence-score-bars">${bars.map(([label, value, icon]) => {
            const normalized = Math.max(0, Math.min(1, Number(value || 0)));
            return `<div class="evidence-score-row"><span class="material-icons-outlined">${icon}</span><span>${label}</span><div class="evidence-score-track"><i style="width:${Math.round(normalized * 100)}%"></i></div><b>${Math.round(normalized * 100)}%</b></div>`;
          }).join('')}</div>` : ''}
        </div>
        ${matchedTerms.length ? `<div class="evidence-section"><div class="evidence-section-label">Matched terms</div><div class="evidence-terms">${matchedTerms.map(term => `<span>${esc(term)}</span>`).join('')}</div></div>` : ''}
        <div class="evidence-section evidence-excerpt-section">
          <div class="evidence-section-label">Relevant page text</div>
          <div class="evidence-excerpt">${highlightEvidence(evidenceText, matchedTerms)}</div>
        </div>
        <div class="evidence-page-meta"><span>${esc(detail.source_type || source.source_type || 'project document')}</span><span>Page ${page} of ${detail.page_count || '?'}</span></div>
      </aside>
    </div>`;
    hydrateAuthedMedia(DOM.evidenceBody);
    const pageImage = $('#evidencePageImage');
    const zoom = $('#btnZoomEvidence');
    // Enlarge reuses whatever the page image resolved to, so it works for both
    // the inline data URI and the fetched object URL.
    const enlarge = () => {
      const current = pageImage && pageImage.getAttribute('src');
      if (current) openImagePreview(current);
      else showToast('The page image is still loading.', 'info');
    };
    if (zoom) zoom.addEventListener('click', enlarge);
    if (pageImage) pageImage.addEventListener('click', enlarge);
  }

  async function openEvidenceViewer(source, messageId) {
    if (!source?.doc_id || !source?.page) {
      showToast('This older citation has no exact page reference.', 'warning');
      return;
    }
    state.activeEvidence = source;
    state.activeEvidenceMessageId = messageId || null;
    DOM.evidenceTitle.textContent = source.doc_name || 'Source page';
    DOM.evidenceSubtitle.textContent = `Page ${source.page} · ${Math.round(Number(source.score || 0) * 100)}% relevance`;
    DOM.evidenceBody.innerHTML = '<div class="preview-loading"><div class="typing-indicator"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div><p>Loading exact source page…</p></div>';
    DOM.evidenceModal.classList.add('open');
    $$('.evidence-feedback-btn').forEach(button => {
      button.disabled = false;
      button.classList.toggle('selected', source.feedback === button.dataset.rating);
    });
    try {
      const query = encodeURIComponent(source.query || '');
      const response = await apiReq(`/api/evidence/${encodeURIComponent(source.doc_id)}/${source.page}?query=${query}`);
      renderEvidenceBody(source, await response.json());
    } catch (error) {
      renderEvidenceBody(source, {});
      showToast(`Evidence details unavailable: ${error.message}`, 'warning', 5000);
    }
  }

  function closeEvidenceViewer() {
    DOM.evidenceModal.classList.remove('open');
    releaseObjectUrls(DOM.evidenceBody);
    DOM.evidenceBody.innerHTML = '';
    state.activeEvidence = null;
    state.activeEvidenceMessageId = null;
  }

  async function submitEvidenceFeedback(rating) {
    const source = state.activeEvidence;
    if (!source) return;
    try {
      $$('.evidence-feedback-btn').forEach(button => { button.disabled = true; });
      await apiReq('/api/evidence/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          doc_id: source.doc_id,
          page: source.page,
          rating,
          query: source.query || '',
          message_id: state.activeEvidenceMessageId,
          score: Number(source.score || 0)
        })
      });
      source.feedback = rating;
      saveChats();
      $$('.evidence-feedback-btn').forEach(button => {
        button.disabled = false;
        button.classList.toggle('selected', button.dataset.rating === rating);
      });
      showToast('Evidence feedback saved.', 'success');
    } catch (error) {
      $$('.evidence-feedback-btn').forEach(button => { button.disabled = false; });
      showToast(error.message, 'error');
    }
  }

  function addMessage(role, content, sources = null, attachments = null) {
    let chat = getActiveChat();
    if (!chat) { createNewChat(); chat = getActiveChat(); }
    const msg = { id: genId(), role, content, sources, attachments, timestamp: Date.now() };
    chat.messages.push(msg);
    if (role === 'bot' && chatWindowState === 'minimized') DOM.chatPanel.classList.add('has-unread');
    if (role === 'user' && chat.messages.filter(m => m.role === 'user').length === 1) {
      chat.title = content.slice(0, 50) + (content.length > 50 ? '…' : '');
    }
    saveChats(); return msg;
  }

  function renderChatMessages() {
    const chat = getActiveChat();
    if (!chat || chat.messages.length === 0) {
      DOM.chatMessages.innerHTML = `<div class="chat-welcome" >
        <div class="chat-welcome-icon"><span class="material-icons-outlined">smart_toy</span></div>
        <h3>Ask Marshal anything</h3>
        <p>Upload documents, audio files, or images and ask questions.</p>
        <div class="chat-suggestions">
          <button class="suggestion-chip" data-q="Summarize the uploaded documents">📝 Summarize docs</button>
          <button class="suggestion-chip" data-q="What are the key findings?">🔍 Key findings</button>
          <button class="suggestion-chip" data-q="List all action items">✅ Action items</button>
        </div>
      </div> `;
      DOM.chatMessages.querySelectorAll('.suggestion-chip').forEach(c => {
        c.addEventListener('click', () => { DOM.chatInput.value = c.dataset.q; sendChatMessage(); });
      });
      return;
    }
    DOM.chatMessages.innerHTML = chat.messages.map(msg => {
      let attachHtml = '';
      if (msg.attachments && msg.attachments.length > 0) {
        attachHtml = `<div class="msg-attachments" > ${msg.attachments.map(a => {
          const ext = getExt(a.name);
          return `<div class="msg-attachment-chip"><span>${getFileIcon(ext)}</span><span class="att-name">${esc(a.name)}</span><span class="att-size">${fmtSize(a.size)}</span></div>`;
        }).join('')
          }</div> `;
      }
      let srcHtml = '';
      if (msg.sources && msg.sources.length > 0) {
        const cards = msg.sources.map((s, sourceIndex) => {
          const prev = s.image_url ? `<img src="${esc(s.image_url)}" alt="Preview" loading="lazy" > ` : ` <span class="material-icons-outlined" style="font-size:20px;color:var(--text-muted)" > description</span> `;
          const method = String(s.retrieval_method || 'Evidence').replace(' + vector candidate', '');
          return `<button class="citation-card" type="button" data-message-id="${msg.id}" data-source-index="${sourceIndex}" aria-label="Open source ${sourceIndex + 1}: ${esc(s.doc_name || 'Document')}, page ${s.page || '?'}">
            <span class="citation-number">${sourceIndex + 1}</span>
            <div class="card-preview">${prev}</div>
            <div class="card-info"><div class="card-doc-name">${esc(s.doc_name || 'Document')}</div><div class="card-page">Page ${s.page || '?'}</div>${Number.isFinite(Number(s.score)) ? `<div class="card-score">${(Number(s.score) * 100).toFixed(0)}%</div>` : ''}<div class="card-method">${esc(method)}</div></div>
          </button> `;
        }).join('');
        srcHtml = `<div class="source-citations" ><div class="citations-label"><span class="material-icons-outlined">fact_check</span> Evidence</div><div class="citation-cards">${cards}</div></div> `;
      }
      let messageHtml = renderMd(msg.content);
      if (msg.sources?.length) {
        messageHtml = messageHtml.replace(/\[(\d+)\]/g, (match, number) => {
          const index = Number(number) - 1;
          if (index < 0 || index >= msg.sources.length) return match;
          return `<button class="inline-citation" type="button" data-message-id="${msg.id}" data-source-index="${index}" title="Open evidence ${number}">[${number}]</button>`;
        });
      }
      return `<div class="chat-msg ${msg.role === 'user' ? 'user' : 'bot'}" data-msg-id="${msg.id}" >
    ${attachHtml} <div class="message-text">${messageHtml}</div>${srcHtml}
  <div class="chat-msg-time">${fmtTime(msg.timestamp)}</div>
      </div> `;
    }).join('');
    DOM.chatMessages.querySelectorAll('.citation-card, .inline-citation').forEach(c => {
      c.addEventListener('click', () => {
        const active = getActiveChat();
        const message = active?.messages.find(item => item.id === c.dataset.messageId);
        const source = message?.sources?.[Number(c.dataset.sourceIndex)];
        if (source) openEvidenceViewer(source, message.id);
      });
    });
    scrollChatBottom();
  }
  function scrollChatBottom() { requestAnimationFrame(() => { DOM.chatMessages.scrollTop = DOM.chatMessages.scrollHeight; }); }

  async function exportChatPdf() {
    const chat = getActiveChat();
    if (!chat || chat.messages.length === 0) {
      showToast('No chat messages to export', 'warning');
      return;
    }
    try {
      showToast('Generating PDF...', 'info');
      const apiUrl = getApiUrl();
      if (!apiUrl) throw new Error('API URL not set');
      const res = await fetch(`${apiUrl}/api/chat/export-pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
        body: JSON.stringify({ 
          title: chat.title || 'Marshal Chat', 
          messages: chat.messages.map(m => ({ role: m.role, content: m.content })) 
        })
      });
      if (!res.ok) {
          const errText = await res.text();
          throw new Error(`Failed to export chat: ${errText || res.statusText}`);
      }
      
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'Marshal_Chat_Export.pdf';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      showToast('PDF downloaded', 'success');
    } catch (e) {
      showToast(e.message, 'error');
    }
  }

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
      return `<div class="pending-file" ><span>${getFileIcon(ext)}</span><span class="pf-name">${esc(f.name.length > 20 ? f.name.slice(0, 18) + '…' : f.name)}</span><button class="pf-remove" data-idx="${i}" title="Remove">×</button></div> `;
    }).join('');
    DOM.chatAttachments.querySelectorAll('.pf-remove').forEach(btn => {
      btn.addEventListener('click', () => { state.pendingFiles.splice(parseInt(btn.dataset.idx), 1); renderPendingFiles(); });
    });
  }

  // Google-aware chat bridge. Read operations enrich normal Q&A with live
  // Calendar context; write operations are proposed and confirmed separately.
  // ── Online meeting scheduling from chat ───────────────────────────────────
  //
  // Runs as a short conversation: the backend answers each turn with either a
  // follow-up question, a proposal to confirm, or the created meeting. The
  // partial answers live in state.pendingMeet, so a reply like "3pm tomorrow"
  // is understood as an answer to the question just asked. Google Meet and
  // Teams share this flow; only the provider route differs.

  const MEET_PATTERN = /\b(google\s*meet|teams\s*meeting|microsoft\s*teams|meet\s+link|online\s+meeting|video\s+(call|meeting|conference)|conference\s+call)\b/i;
  const MEET_SCHEDULE_PATTERN = /\b(schedule|set\s*up|setup|arrange|book|create|organi[sz]e|start)\b/i;
  const CANCEL_PATTERN = /^\s*(cancel|stop|never\s*mind|forget\s+it|abort)\b/i;
  const AFFIRM_PATTERN = /^\s*(yes|yep|yeah|ok|okay|confirm|do it|go ahead|sure|please do)\b/i;

  function wantsMeet(text) {
    return MEET_PATTERN.test(text) && MEET_SCHEDULE_PATTERN.test(text);
  }

  /**
   * Which calendar a message is about.
   *
   * An explicit mention wins, so "book a Teams meeting" reaches Outlook even
   * while the Google page is the one most recently opened; otherwise the
   * usual active-provider rule applies.
   */
  const MICROSOFT_WORDS = /\b(teams|outlook|microsoft|office\s*365|o365|m365)\b/i;
  const GOOGLE_WORDS = /\b(google|gmail|g-?suite|meet)\b/i;

  /**
   * Which calendar a chat message should act on.
   *
   * Naming a provider picks it. Saying nothing means Google, which stays the
   * default however recently the Microsoft page happened to be opened — a
   * message should not change meaning because of where the user browsed last.
   */
  function calendarProviderFor(text) {
    const named = MICROSOFT_WORDS.test(text) ? 'microsoft'
      : GOOGLE_WORDS.test(text) ? 'google' : null;
    if (named) return ws(named).accountId ? named : { unlinked: named };
    if (ws('google').accountId) return 'google';
    return Object.keys(WORKSPACE_PROVIDERS).find(id => ws(id).accountId) || null;
  }

  /**
   * Make sure the linked-account list has actually loaded.
   *
   * applySession kicks these off without awaiting, and a load that raced the
   * backend coming up (or failed while it was restarting) leaves the slice
   * empty. Without this a scheduling request silently became a document
   * question, which reads as the feature being broken.
   */
  async function ensureProvidersLoaded() {
    const pending = Object.keys(WORKSPACE_PROVIDERS)
      .filter(id => !ws(id).config && !ws(id).loading)
      .map(id => loadWorkspaceProvider(id));
    if (pending.length) await Promise.all(pending);
  }

  /** The reviewable summary of a proposed meeting.
   *
   * Tolerates a partial proposal: a provider that answers with less than
   * expected should read as a thinner summary, never as a thrown error in
   * the middle of a conversation.
   */
  function formatMeetSummary(proposal) {
    const meeting = proposal || {};
    const start = new Date(meeting.start);
    const end = new Date(meeting.end);
    const when = Number.isNaN(start.getTime())
      ? (meeting.start || 'a time I could not read')
      : `${start.toLocaleString()} – ${Number.isNaN(end.getTime()) ? '' : end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    const guests = meeting.attendees?.length ? meeting.attendees.join(', ') : 'no other attendees';
    const parts = [`**${meeting.summary || 'Untitled meeting'}**`, ''];
    parts.push(`- **When:** ${when}${meeting.timezone ? ` (${meeting.timezone})` : ''}`);
    if (meeting.duration_minutes) parts.push(`- **Duration:** ${meeting.duration_minutes} minutes`);
    parts.push(`- **Attendees:** ${guests}`);
    return parts.join('\n');
  }

  /**
   * Advance the Meet conversation by one turn.
   * Returns a chat reply, or null when this message is not part of a Meet flow.
   */
  async function handleMeetRequest(text) {
    const pending = state.pendingMeet;
    if (!pending && !wantsMeet(text)) return null;

    if (pending && CANCEL_PATTERN.test(text)) {
      state.pendingMeet = null;
      return 'Cancelled. No meeting was scheduled.';
    }

    // A conversation already under way stays on the calendar it started on.
    const providerId = pending?.providerId || calendarProviderFor(text);
    if (!providerId || !ws(providerId).accountId) {
      state.pendingMeet = null;
      return 'To schedule an online meeting I need a connected Google or Microsoft account. Open **Google Workspace** or **Microsoft 365** and choose **Add account**.';
    }
    const cfg = providerConfig(providerId);
    const slice = ws(providerId);

    // An affirmative reply to the confirmation step commits the booking.
    const confirming = pending?.stage === 'confirming' && AFFIRM_PATTERN.test(text);

    let response;
    try {
      response = await apiReq(`${cfg.api}/${cfg.meetingPath}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: slice.accountId,
          query: confirming ? '' : text,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          known: pending?.known || {},
          confirm: confirming
        })
      });
    } catch (error) {
      state.pendingMeet = null;
      return `I could not schedule that meeting: ${error.message}`;
    }

    // From here on, anything unexpected in the reply ends the conversation
    // rather than leaving it pending and hijacking the next message.
    try {
    const result = await response.json();

    if (result.status === 'needs_input') {
      state.pendingMeet = { providerId, known: result.known, stage: 'collecting' };
      return result.question;
    }

    if (result.status === 'confirm') {
      state.pendingMeet = { providerId, known: result.known, stage: 'confirming' };
      return `Here is the meeting I will create in **${cfg.calendarLabel}** with a ${cfg.meetingLabel} link:\n\n${formatMeetSummary(result.proposal)}\n\nReply **yes** to schedule it, or tell me what to change.`;
    }

    if (result.status === 'created') {
      state.pendingMeet = null;
      const event = result.event || {};
      const proposal = result.proposal || {};
      const title = event.summary || proposal.summary || 'the meeting';
      const lines = [`Scheduled **${title}** in ${cfg.calendarLabel}.`, '', formatMeetSummary(proposal)];
      if (result.meet_link) {
        lines.push('', `- **${cfg.meetingLabel}:** ${result.meet_link}`);
      } else if (result.meet_unavailable) {
        lines.push('', `- **${cfg.meetingLabel}:** the event was created, but this account is not permitted to add a conferencing link. Open the event in ${cfg.calendarLabel} to add one.`);
      }
      const link = event.html_link || event.htmlLink;
      if (link) lines.push(`- **Calendar:** ${link}`);
      // The Calendar page must not keep showing the state before the booking.
      if (calendarState().loaded) loadCalendar({ force: true });
      return lines.join('\n');
    }

    state.pendingMeet = null;
    return 'I could not schedule that meeting. Try again with a title, a date, and a time.';
    } catch (error) {
      state.pendingMeet = null;
      return `I could not read the scheduling reply: ${error.message}. `
        + 'Nothing was booked — try again with a title, a date and a time.';
    }
  }

  // ── Editing a calendar event from chat ────────────────────────────────────

  const EVENT_EDIT_PATTERN = /\b(reschedule|re-?schedule|postpone|move|push|shift|bring\s+forward|rename|change|update|edit)\b/i;
  const EVENT_RENAME_PATTERN = /\b(rename|call\s+it|retitle|change\s+the\s+(title|name))\b/i;

  /** Score an event title against the words in the request. */
  function eventTitleScore(title, text) {
    const words = String(title || '').toLowerCase().match(/[a-z0-9]+/g) || [];
    if (!words.length) return 0;
    const haystack = text.toLowerCase();
    const hits = words.filter(word => word.length > 2 && haystack.includes(word));
    return hits.length / words.length;
  }

  /**
   * Find the event a request refers to.
   *
   * A quoted title is taken literally; otherwise the upcoming events are
   * scored on how much of their title the message repeats. An ambiguous match
   * is returned as a list so the user can choose rather than have the wrong
   * event silently edited.
   */
  function matchCalendarEvent(events, text) {
    const quoted = text.match(/["“”']([^"“”']{2,})["“”']/);
    if (quoted) {
      const needle = quoted[1].trim().toLowerCase();
      const exact = events.filter(e => String(e.summary || '').toLowerCase().includes(needle));
      if (exact.length) return exact;
    }
    const scored = events
      .map(event => ({ event, score: eventTitleScore(event.summary, text) }))
      .filter(entry => entry.score >= 0.5)
      .sort((a, b) => b.score - a.score);
    if (!scored.length) return [];
    const best = scored[0].score;
    return scored.filter(entry => entry.score === best).map(entry => entry.event);
  }

  function eventWhen(event) {
    const value = event.start?.dateTime || event.start?.date;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value || '') : date.toLocaleString();
  }

  /**
   * Advance an event edit by one turn.
   * Returns a chat reply, or null when this message is not an edit request.
   */
  async function handleCalendarEditRequest(text) {
    const pending = state.pendingEventEdit;

    if (pending) {
      if (CANCEL_PATTERN.test(text)) {
        state.pendingEventEdit = null;
        return 'Cancelled. The event was left as it was.';
      }
      if (!AFFIRM_PATTERN.test(text)) {
        // Anything other than yes/no restarts the search with the new wording.
        state.pendingEventEdit = null;
      } else {
        const cfg = providerConfig(pending.providerId);
        try {
          await apiReq(`${cfg.api}/calendar/events/${encodeURIComponent(pending.eventId)}`, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...pending.patch, account_id: pending.accountId, confirm: true })
          });
        } catch (error) {
          state.pendingEventEdit = null;
          return `I could not update that event: ${error.message}`;
        }
        state.pendingEventEdit = null;
        if (calendarState().loaded) loadCalendar({ force: true });
        return `Updated **${pending.title}** in ${cfg.calendarLabel}. The change is on the connected account, so everyone invited sees it.`;
      }
    }

    if (!EVENT_EDIT_PATTERN.test(text) || !/\b(event|meeting|appointment|calendar|invite)\b/i.test(text)) return null;

    const providerId = calendarProviderFor(text);
    if (!providerId || !ws(providerId).accountId) {
      return 'To change a calendar event I need a connected Google or Microsoft account. Open **Google Workspace** or **Microsoft 365** and choose **Add account**.';
    }
    const cfg = providerConfig(providerId);
    const accountId = ws(providerId).accountId;

    let events;
    try {
      const listed = await apiReq(`${cfg.api}/calendar/events?account_id=${encodeURIComponent(accountId)}&max_results=100`);
      events = (await listed.json()).events || [];
    } catch (error) {
      return `I could not read your ${cfg.calendarLabel}: ${error.message}`;
    }
    if (!events.length) return `There are no events in your ${cfg.calendarLabel} to change.`;

    const matches = matchCalendarEvent(events, text);
    if (!matches.length) {
      return `I could not find that event in your ${cfg.calendarLabel}. Tell me its exact title in quotes, for example: reschedule "Site walkthrough" to Friday at 2pm.`;
    }
    if (matches.length > 1) {
      const list = matches.slice(0, 5).map(e => `- **${e.summary}** — ${eventWhen(e)}`).join('\n');
      return `Several events match. Which one did you mean?\n\n${list}\n\nReply with the title in quotes.`;
    }

    const target = matches[0];
    // Reuse the provider's own interpreter rather than parsing dates here.
    let proposal;
    try {
      const interpreted = await apiReq(`${cfg.api}/assistant/interpret`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accountId, query: text,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
        })
      });
      proposal = (await interpreted.json()).proposal || {};
    } catch (error) {
      return `I could not work out the change: ${error.message}`;
    }

    const patch = {};
    const changes = [];
    const start = new Date(proposal.start);
    if (proposal.start && !Number.isNaN(start.getTime())) {
      patch.start = proposal.start;
      patch.end = proposal.end || proposal.start;
      patch.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      changes.push(`- **When:** ${start.toLocaleString()}`);
    }
    // The interpreter echoes the event's own title back, so only treat it as a
    // rename when the user actually asked for one.
    if (EVENT_RENAME_PATTERN.test(text) && proposal.summary && proposal.summary !== target.summary) {
      patch.summary = proposal.summary;
      changes.push(`- **Title:** ${proposal.summary}`);
    }
    if (!changes.length) {
      return `I found **${target.summary}** (${eventWhen(target)}) but could not tell what to change. Try "reschedule \"${target.summary}\" to Friday at 2pm".`;
    }

    state.pendingEventEdit = {
      providerId, accountId, eventId: target.id, title: target.summary, patch
    };
    return `I will change **${target.summary}** in ${cfg.calendarLabel}:\n\n${changes.join('\n')}\n\nIt is currently ${eventWhen(target)}. Reply **yes** to apply this, or tell me what to change.`;
  }

  /**
   * Let a chat message act on a connected workspace.
   *
   * Works through whichever provider is linked; when both Google and Microsoft
   * are connected it uses the one whose page was opened most recently, so the
   * user controls where an email or event lands.
   */
  const CALENDAR_WORDS = /\b(calendar|calender|event|meeting|schedule|appointment|invite)\b/i;
  const CALENDAR_VERBS = /\b(add|create|book|schedule|set\s*up|setup|arrange|organi[sz]e|put)\b/i;

  async function handleWorkspaceAgentRequest(text) {
    if (!text) return { handled: false, query: text };

    // A connected account may not have finished loading yet; find out before
    // deciding this message is not a calendar request.
    const looksLikeCalendar = CALENDAR_WORDS.test(text);
    if (looksLikeCalendar || wantsMeet(text)) await ensureProvidersLoaded();

    // A Meet conversation in progress owns the next message, so a bare reply
    // like "tomorrow at 10" is not mistaken for a document question.
    const meetReply = await handleMeetRequest(text);
    if (meetReply !== null) return { handled: true, response: meetReply };

    // Likewise for an edit awaiting a yes/no.
    const editReply = await handleCalendarEditRequest(text);
    if (editReply !== null) return { handled: true, response: editReply };

    // "Create a project called ..." used to fall through to document search and
    // report that it could not be found, while the same sentence worked on the
    // Onboarding page. It is answered here now.
    const createReply = await handleEntityCreateRequest(text);
    if (createReply !== null) return { handled: true, response: createReply };

    const routed = calendarProviderFor(text);

    // The user named a provider that is not connected. Say so, rather than
    // quietly booking on the other one or searching the documents.
    if (routed && routed.unlinked) {
      const wanted = providerConfig(routed.unlinked);
      return { handled: true, response: `You asked for **${wanted.calendarLabel}**, but no ${wanted.label} account is connected. Open **${wanted.label}** in the sidebar and choose **Add account**, then ask me again.` };
    }

    const providerId = routed;
    if (!providerId) {
      // Falling through to document search here produced "no information in
      // the project documents", which does not explain the real problem.
      if (looksLikeCalendar && CALENDAR_VERBS.test(text)) {
        return { handled: true, response: 'To schedule anything I need a connected calendar. Open **Google Workspace** or **Microsoft 365** in the sidebar and choose **Add account**, then ask me again.' };
      }
      return { handled: false, query: text };
    }
    const cfg = providerConfig(providerId);
    const slice = ws(providerId);
    const accountId = slice.accountId;

    const emailRequest = /\b(write|compose|draft|send)\b[\s\S]*\b(e-?mail|gmail|outlook|mail)\b|\b(e-?mail|gmail|outlook)\b[\s\S]*\b(write|compose|draft|send)\b/i.test(text);
    if (emailRequest) {
      const recipient = (text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i) || [''])[0];
      const payload = { account_id: accountId, to: recipient, cc: '', subject: '', body: '', instruction: text };
      const response = await apiReq(`${cfg.api}/${cfg.mailPath}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const draft = await response.json();
      slice.emailDraft = { ...payload, subject: draft.subject || '', body: draft.body || '' };
      if (/\bsend\b/i.test(text) && recipient && confirm(`Marshal prepared “${draft.subject}”. Send it now to ${recipient} from ${cfg.label}?`)) {
        await apiReq(`${cfg.api}/${cfg.mailPath}/send`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...slice.emailDraft, confirm: true }) });
        return { handled: true, response: `Email sent to **${recipient}** from **${cfg.label}** with subject **${draft.subject}**.` };
      }
      return { handled: true, response: `I prepared this email for review.

**Subject:** ${draft.subject}

${draft.body}

Open **${cfg.label} → ${cfg.mailLabel}** to edit it, save a draft, or send it.` };
    }

    const calendarWords = CALENDAR_WORDS.test(text);
    const createCalendar = calendarWords && CALENDAR_VERBS.test(text);
    if (createCalendar) {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const interpreted = await apiReq(`${cfg.api}/assistant/interpret`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_id: accountId, query: text, timezone }) });
      const result = await interpreted.json();
      if (!result.supported) return { handled: true, response: `I could not identify a complete calendar event. Include a title, date, and time, or use **${cfg.label} → Calendar**.` };
      const event = result.proposal;
      const start = new Date(event.start);
      if (!event.summary || Number.isNaN(start.getTime())) return { handled: true, response: 'I need a clear event title, date, and time before I can add it.' };
      if (!confirm(`Add “${event.summary}” to ${cfg.calendarLabel} on ${start.toLocaleString()}?`)) return { handled: true, response: 'Calendar creation cancelled. No event was added.' };
      const payload = { account_id: accountId, summary: event.summary, description: event.description || '', start: event.start, end: event.end, timezone, attendees: Array.isArray(event.attendees) ? event.attendees : [], confirm: true };
      const created = await apiReq(`${cfg.api}/calendar/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const createdEvent = await created.json();
      if (calendarState().loaded) loadCalendar({ force: true });
      const joinLine = createdEvent.meet_link ? `\n\n- **${cfg.meetingLabel}:** ${createdEvent.meet_link}` : '';
      return { handled: true, response: `Added **${event.summary}** to ${cfg.calendarLabel} for ${start.toLocaleString()}.${joinLine}` };
    }
    if (calendarWords) {
      const response = await apiReq(`${cfg.api}/calendar/events?account_id=${encodeURIComponent(accountId)}&max_results=30`);
      const events = (await response.json()).events || [];
      const context = events.map(event => ({ summary: event.summary, start: event.start?.dateTime || event.start?.date, end: event.end?.dateTime || event.end?.date, description: event.description || '' }));
      return { handled: false, query: `${text}

${cfg.calendarLabel} context (live; use it when answering):
${JSON.stringify(context)}` };
    }
    return { handled: false, query: text };
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
      const workspaceResult = await handleWorkspaceAgentRequest(text);
      if (workspaceResult.handled) {
        const el = document.getElementById('typingIndicator'); if (el) el.remove();
        addMessage('bot', workspaceResult.response); renderChatMessages();
        return;
      }
      const chat = getActiveChat();
      const history = chat.messages.filter(m => m.role === 'user' || m.role === 'bot').slice(-10).map(m => ({ role: m.role === 'bot' ? 'assistant' : m.role, content: m.content }));
      history.pop();
      const res = await apiReq('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: workspaceResult.query || 'Analyze the attached files',
          history,
          model: APP_CONFIG.MODEL,
          top_k: APP_CONFIG.TOP_K,
          project_id: state.currentPage === 'project-details' ? (state.activeProjectId || null) : null
        })
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
    const el = DOM.chatMessages.querySelector(`[data-msg-id="${msgId}"] .message-text`);
    if (el) el.innerHTML = renderMd(content);
  }

  // ═══ Upload Panel ═══
  function openUploadPanel(projectId = null) {
    state.uploadProjectId = typeof projectId === 'string' ? projectId : null;
    const title = DOM.uploadPanel.querySelector('.upload-panel-header h2');
    if (title) title.textContent = state.uploadProjectId ? '📁 Upload Project PDF Sources' : '📁 Upload Files';
    DOM.uploadPanel.classList.add('open'); DOM.uploadPanelOverlay.classList.add('open'); fetchDocuments();
  }
  function closeUploadPanel() {
    DOM.uploadPanel.classList.remove('open'); DOM.uploadPanelOverlay.classList.remove('open');
    state.uploadProjectId = null;
  }


  async function uploadFiles(files) {
    const projectId = state.uploadProjectId;
    for (const file of Array.from(files)) {
      if (file.size > APP_CONFIG.MAX_FILE_SIZE) { showToast(`Too large: ${file.name} `, 'warning'); continue; }
      const docId = genId();
      const doc = { id: docId, name: file.name, type: getExt(file.name), size: file.size, status: 'uploading', pages: 0 };
      state.uploadedDocs.push(doc); renderDocList();
      try {
        const fd = new FormData(); fd.append('file', file); fd.append('doc_id', docId);
        const endpoint = projectId
          ? `/api/projects/${projectId}/source-documents`
          : '/api/upload';
        const res = await apiReq(endpoint, { method: 'POST', body: fd });
        const data = await res.json();
        doc.status = 'indexed'; doc.pages = data.pages || 0; doc.project_id = data.project_id || null;
      } catch (e) { doc.status = 'error'; renderDocList(); showToast(`Upload failed: ${file.name} `, 'error'); }
    }
    updateDocBadge();
    if (projectId) await fetchProjectSources(projectId);
    if (state.currentPage === 'documents' || (state.currentPage === 'project-details' && state.activeProjectId === projectId)) renderPage();
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
      item.innerHTML = `<div class="doc-icon ${tc}" > ${icon}</div><div class="doc-info"><div class="doc-name">${esc(doc.name)}</div><div class="doc-meta">${fmtSize(doc.size || 0)}${doc.pages ? ' · ' + doc.pages + ' pg' : ''}</div></div><span class="doc-status ${doc.status}">${sLabel}</span><button class="doc-delete" title="Remove">🗑</button>`;
      item.querySelector('.doc-delete').addEventListener('click', async () => {
        try { await apiReq(`/api/documents/${doc.id}`, { method: 'DELETE' }); state.uploadedDocs = state.uploadedDocs.filter(d => d.id !== doc.id); renderDocList(); updateDocBadge(); showToast('Removed', 'info'); } catch (e) { showToast('Delete failed', 'error'); }
      });
      container.appendChild(item);
    });
    DOM.docTotalCount.textContent = `${state.uploadedDocs.length} file${state.uploadedDocs.length !== 1 ? 's' : ''} `;
  }

  // ═══ Settings ═══
  function openSettings() {
    DOM.apiUrlInput.value = getApiUrl() || 'http://127.0.0.1:8000';
    DOM.voiceApiUrlInput.value = getVoiceApiUrl();
    DOM.modelSelect.value = APP_CONFIG.MODEL;
    DOM.topKInput.value = APP_CONFIG.TOP_K;
    DOM.settingsModal.classList.add('open');
  }
  function closeSettings() { DOM.settingsModal.classList.remove('open'); }
  async function saveSettings() {
    const url = DOM.apiUrlInput.value.trim() || 'http://127.0.0.1:8000';
    const voiceUrl = DOM.voiceApiUrlInput.value.trim();
    APP_CONFIG.API_URL = url;
    APP_CONFIG.VOICE_API_URL = voiceUrl;
    APP_CONFIG.MODEL = DOM.modelSelect.value;
    APP_CONFIG.TOP_K = Math.max(1, Math.min(20, parseInt(DOM.topKInput.value) || 5));
    // The backend URL is a property of this browser, not of the account, so it
    // stays local.  Everything else is account configuration and is stored
    // server-side with the account that owns it.
    localStorage.setItem(APP_CONFIG.STORAGE_KEYS.API_URL, url);
    // Typed by hand, so it outranks the port the launcher announces.
    localStorage.setItem('bmarshal_api_url_pinned', '1');
    closeSettings();
    if (state.session) {
      try {
        const res = await apiReq('/api/account/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: APP_CONFIG.MODEL, top_k: APP_CONFIG.TOP_K, voice_api_url: voiceUrl
          })
        });
        applyAccountSettings((await res.json()).settings);
        showToast('Settings saved!', 'success');
      } catch (e) { showToast(e.message, 'error'); }
    }
    checkConnection();
    fetchAllData();
  }

  function applyAccountSettings(settings) {
    state.settings = settings || {};
    if (state.settings.model) APP_CONFIG.MODEL = state.settings.model;
    if (state.settings.top_k) APP_CONFIG.TOP_K = state.settings.top_k;
    APP_CONFIG.VOICE_API_URL = state.settings.voice_api_url || '';
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
    const btnEC = $('#btnExportChat'); if (btnEC) btnEC.addEventListener('click', exportChatPdf);
    DOM.btnChatHistory.addEventListener('click', toggleChatHistory);
    DOM.btnCloseHistory.addEventListener('click', closeChatHistory);

    // Chat panel window controls (minimize / full screen) + resize
    initChatWindowControls();
    initChatResize();

    // Chat input — auto-resize textarea
    DOM.chatInput.addEventListener('input', () => autoResize(DOM.chatInput));
    DOM.chatInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); } });
    DOM.btnChatSend.addEventListener('click', sendChatMessage);
    DOM.btnVoiceInput.addEventListener('click', toggleVoiceRecording);

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
    DOM.btnNotifications?.addEventListener('click', event => {
      event.stopPropagation();
      toggleNotifications();
    });
    DOM.notifPanel?.addEventListener('click', event => event.stopPropagation());
    document.addEventListener('click', () => { if (state.notificationsOpen) closeNotifications(); });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && state.notificationsOpen) closeNotifications();
    });

    DOM.btnCloseCrud.addEventListener('click', closeCrudModal);
    DOM.btnCancelCrud.addEventListener('click', closeCrudModal);
    DOM.btnSaveCrud.addEventListener('click', async () => {
      const crudAct = DOM.btnSaveCrud.dataset.crudAction;
      const crudId = DOM.btnSaveCrud.dataset.crudId;

      if (crudAct === 'generate-project-document') {
        const body = {
          doc_kind: $('#docGenKind')?.value || 'tender_summary',
          title: $('#docGenTitle')?.value.trim() || null,
          instructions: $('#docGenInstructions')?.value.trim() || '',
          top_k_per_section: Math.max(1, Math.min(12, parseInt($('#docGenTopK')?.value || '6', 10))),
        };
        DOM.btnSaveCrud.disabled = true;
        DOM.btnSaveCrud.textContent = 'Generating…';
        try {
          const response = await apiReq(`/api/projects/${crudId}/documents`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
          });
          const metadata = await response.json();
          closeCrudModal();
          await downloadGeneratedDocument(metadata);
          showToast(`Generated ${metadata.title}`, 'success');
        } catch (error) {
          DOM.btnSaveCrud.disabled = false;
          DOM.btnSaveCrud.textContent = 'Generate PDF';
          showToast(error.message, 'error');
        }
        return;
      }

      if (crudAct === 'create-calendar-event') { await submitCalendarEventCreate(); return; }
      if (crudAct === 'save-chat-user') {
        await submitCreateUser({
          onDone: ({ name, role }) => {
            closeCrudModal();
            addMessage('bot', `Created **${esc(name)}**${role ? ` as **${esc(role)}**` : ''}. ` +
              `They are in **Company Settings → User**, and the temporary password you saw ` +
              `should be changed at first sign-in.`);
            renderChatMessages();
          }
        });
        return;
      }
      if (crudAct === 'save-chat-entity') { await submitChatEntity(); return; }
      if (crudAct === 'save-user-role') { await submitUserRole(crudId); return; }
      if (crudAct === 'save-onboarding-item') {
        const kind = DOM.btnSaveCrud.dataset.onbKind;
        let preset = {};
        try { preset = JSON.parse(DOM.btnSaveCrud.dataset.onbPreset || '{}'); } catch (e) { preset = {}; }
        if (await submitOnboardingItem(crudId, kind, preset)) closeCrudModal();
        return;
      }

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
          const created = await apiReq('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json());
          await fetchProjects();
          closeCrudModal();
          renderPage();
          showToast('Project created', 'success');
          // When the chat asked for it, the chat should say it happened.
          if (DOM.chatPanel?.classList.contains('visible')) {
            addMessage('bot', `Created **${esc(name)}** (${esc(project_code)}). ` +
              `Open it from **Projects → All Projects**.`);
            renderChatMessages();
          }
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
          await apiReq(`/api/projects/${crudId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
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
      const crudExtra = DOM.btnSaveCrud.dataset.crudExtra || '';
      if (crudAct === 'update-calendar-event') {
        const [accountId, eventId] = crudExtra.split('|');
        await submitCalendarEventUpdate(crudId, accountId, eventId);
        return;
      }
      if (crudAct === 'add-project-members') { await submitAddMembers(crudId); return; }
      if (crudAct === 'add-project-cost') { await submitProjectCost(crudId, ''); return; }
      if (crudAct === 'update-project-cost') { await submitProjectCost(crudId, crudExtra); return; }
      if (crudAct === 'add-procurement') { await submitProcurement(crudId, ''); return; }
      if (crudAct === 'update-procurement') { await submitProcurement(crudId, crudExtra); return; }
      if (crudAct === 'create-task') {
        await submitCreateTask(crudId);
        return;
      }

      // Existing trade/vendor/team-member pattern
      if (crudCallback && await crudCallback()) { closeCrudModal(); renderPage(); showToast('Saved', 'success'); }
    });
    DOM.crudModal.addEventListener('click', e => { if (e.target === DOM.crudModal) closeCrudModal(); });

    // Doc Preview
    DOM.btnCloseDocPreview.addEventListener('click', closeDocPreview);
    DOM.docPreviewModal.addEventListener('click', e => { if (e.target === DOM.docPreviewModal) closeDocPreview(); });

    // Evidence viewer
    DOM.btnCloseEvidence.addEventListener('click', closeEvidenceViewer);
    DOM.evidenceModal.addEventListener('click', e => { if (e.target === DOM.evidenceModal) closeEvidenceViewer(); });
    $$('.evidence-feedback-btn').forEach(button => button.addEventListener('click', () => submitEvidenceFeedback(button.dataset.rating)));

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
    document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeImagePreview(); closeSettings(); closeCrudModal(); closeUploadPanel(); closeDocPreview(); closeEvidenceViewer(); } });

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
  async function init() {
    bindAuthEvents();
    initEvents();
    updateNavGroups();
    renderUserProfileHeader();
    await restoreSession();
    setInterval(() => { if (state.session) checkConnection(); }, 30000);
  }

  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', init) : init();
})();
