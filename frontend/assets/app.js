import { createApi, formatBytes, normalizeSearch } from './api.js';
import { createLegalWorkspace, reviewLabel, validityLabel, sourceLabel } from './legal.js';

const $ = id => document.getElementById(id);
const api = createApi();
const state = {
  documents: [], loaded: false, mode: 'search', view: 'chat', filter: 'all', scope: new Set(),
  busy: false, uploading: false, messages: [], lastSources: [], pendingDelete: null,
  generation: false, capabilitiesLoaded: false, authRequired: false, refreshing: false,
  pdfUrl: null, pageUrl: null, previewId: null, previewFilename: null, page: 1, pageCount: 1, previewRequest: 0, signature: null, polling: null,
};
const statuses = {
  ready: 'Đã xử lý', queued: 'Chờ xử lý', processing: 'Đang xử lý', failed: 'Cần kiểm tra', deleting: 'Đang xóa',
};
const readyDocuments = () => state.documents.filter(doc => doc.status === 'ready' && doc.review_status === 'approved');
const activeDocuments = () => state.documents.filter(doc => ['queued', 'processing'].includes(doc.status));
const node = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'icon'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(svg.namespaceURI, 'use'); use.setAttribute('href', `#i-${name}`);
  svg.append(use); return svg;
}
function actionButton(label, symbol, handler, className = 'icon-button') {
  const button = node('button', className);
  button.type = 'button'; button.title = label; button.setAttribute('aria-label', label);
  if (symbol) button.append(icon(symbol));
  button.addEventListener('click', handler); return button;
}
function toast(message, error = false) {
  const item = node('div', `toast${error ? ' error' : ''}`);
  item.append(icon(error ? 'info' : 'check'), node('span', '', message));
  item.append(actionButton('Đóng thông báo', 'close', () => item.remove()));
  $('toasts').append(item); setTimeout(() => item.remove(), error ? 9500 : 5500);
}
function showError(error) {
  if (error.status === 401) {
    state.authRequired = true;
    setConnection('pending', 'Cần API key');
    $('ai-availability').textContent = 'Nhập Backend API key để truy cập tài liệu và kiểm tra tính năng AI.';
  }
  toast(error.message || 'Có lỗi xảy ra. Vui lòng thử lại.', true);
}
function setConnection(type, label) {
  $('connection-status').className = `connection-status ${type}`;
  $('connection-label').textContent = label;
}
function navigate(view) {
  state.view = view;
  $('view-chat').hidden = view !== 'chat'; $('view-documents').hidden = view !== 'documents';
  $('breadcrumb-current').textContent = view === 'chat' ? 'Tra cứu' : 'Kho tài liệu';
  document.querySelectorAll('[data-view]').forEach(button => {
    const current = button.dataset.view === view;
    button.classList.toggle('active', current);
    if (current) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  document.title = `${view === 'chat' ? 'Tra cứu' : 'Kho tài liệu'} · Legal RAG`;
}
function renderComposer() {
  const ready = readyDocuments().length > 0;
  $('question-input').disabled = !ready || state.busy || state.authRequired;
  $('submit-question').disabled = !ready || state.busy || !$('question-input').value.trim() || state.authRequired;
  $('mode-ask').disabled = !state.generation || state.busy;
  $('mode-ask').lastChild.textContent = state.generation ? 'Hỏi đáp AI' : 'AI chưa bật';
  $('mode-search').disabled = state.busy;
  $('new-session').disabled = state.busy || !state.messages.length;
  $('question-input').placeholder = ready ? 'Đặt câu hỏi về tài liệu của bạn…'
    : activeDocuments().length ? 'Tài liệu đang được xử lý. Sẵn sàng trong giây lát…' : 'Thêm tài liệu và duyệt nguồn để bắt đầu tra cứu…';
  $('mode-search').classList.toggle('active', state.mode === 'search');
  $('mode-ask').classList.toggle('active', state.mode === 'ask');
  $('mode-description').textContent = state.mode === 'search' ? 'Tìm trực tiếp trong nội dung tài liệu.' : 'Mỗi câu hỏi được tra cứu độc lập.';
  $('scope-label').textContent = state.scope.size ? `${state.scope.size} tài liệu đã chọn` : 'Toàn bộ kho';
  const welcome = $('welcome');
  welcome.hidden = !!state.messages.length;
  if (!state.messages.length) {
    $('welcome-description').textContent = ready ? 'Kho tài liệu đã sẵn sàng. Đặt câu hỏi bên dưới để tìm nội dung và đối chiếu nguồn.'
      : activeDocuments().length ? 'Tài liệu đang được xử lý. Bạn có thể theo dõi tiến độ trong Kho tài liệu.'
      : 'Tải PDF, mở Hồ sơ và duyệt nguồn trước khi tra cứu. Mỗi phiên bản cần được duyệt riêng.';
    welcome.querySelector('[data-go-documents]').lastChild.textContent = ready ? 'Quản lý tài liệu' : activeDocuments().length ? 'Xem tiến độ xử lý' : state.documents.length ? 'Kiểm tra và duyệt nguồn' : 'Thêm tài liệu đầu tiên';
  }
}
function renderDocuments() {
  const docs = state.documents;
  const ready = readyDocuments();
  for (const id of [...state.scope]) if (!ready.some(doc => doc.id === id)) state.scope.delete(id);
  $('nav-document-count').textContent = state.loaded ? docs.length : '—';
  $('ready-count').textContent = state.loaded ? ready.length : '—';
  $('page-count').textContent = state.loaded ? ready.reduce((sum, doc) => sum + doc.page_count, 0).toLocaleString('vi') : '—';
  $('stat-total').textContent = state.loaded ? docs.length : '—';
  $('stat-ready').textContent = state.loaded ? ready.length : '—';
  $('stat-processing').textContent = state.loaded ? activeDocuments().length : '—';
  $('filter-all-count').textContent = docs.length;
  const search = normalizeSearch($('document-search').value);
  const filtered = docs.filter(doc => {
    const status = state.filter === 'all' || (state.filter === 'processing' ? ['queued', 'processing', 'deleting'].includes(doc.status) : state.filter === 'ready' ? doc.status === 'ready' && doc.review_status === 'approved' : state.filter === 'draft' ? doc.review_status !== 'approved' : doc.status === state.filter);
    return status && normalizeSearch([doc.filename,doc.document_code,doc.title,doc.version].join(' ')).includes(search);
  });
  $('documents-body').replaceChildren();
  for (const doc of filtered) {
    const row = node('tr'); row.dataset.documentId = doc.id;
    const fileCell = node('td'); const file = node('div', 'file-cell');
    const fileIcon = node('span', 'file-cell-icon'); fileIcon.append(icon('file'));
    const content = node('div');
    const filename = node('button', 'file-name', doc.filename); filename.type = 'button'; filename.title = doc.filename;
    filename.addEventListener('click', () => preview(doc.id, doc.filename));
    content.append(filename, node('span', 'file-subtitle', `${doc.document_code || 'Chưa có mã'} · bản ${doc.version} · ${formatBytes(doc.size_bytes)}`));
    content.append(node('span','file-subtitle',validityLabel(doc.validity_status)));
    if (doc.error) content.append(node('span', 'file-error', doc.error));
    file.append(fileIcon, content); fileCell.append(file);
    const statusCell = node('td'); const badge = node('span', `status-badge ${doc.status}`);
    badge.append(node('span', 'status-dot'), document.createTextNode(statuses[doc.status] || doc.status)); statusCell.append(badge, node('div','file-subtitle',reviewLabel(doc.review_status)));
    const numbers = node('td', '', doc.status === 'ready' ? `${doc.page_count} trang / ${doc.chunk_count} đoạn` : '—');
    const date = node('td', '', new Date(doc.created_at).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' }));
    const actionsCell = node('td'); const actions = node('div', 'row-actions');
    actions.append(actionButton('Hồ sơ và duyệt nguồn', 'settings', () => legalWorkspace.open(doc.id)));
    actions.append(actionButton('Xem PDF gốc', 'eye', () => preview(doc.id, doc.filename)));
    if (doc.status === 'failed') actions.append(actionButton('Thử xử lý lại', 'refresh', () => retry(doc.id)));
    actions.append(actionButton('Xóa tài liệu', 'trash', () => confirmDelete(doc), 'icon-button delete-button'));
    actionsCell.append(actions); row.append(fileCell, statusCell, numbers, date, actionsCell); $('documents-body').append(row);
  }
  $('documents-empty').hidden = filtered.length > 0 || !state.loaded;
  $('documents-empty-title').textContent = docs.length ? 'Không tìm thấy tài liệu phù hợp' : 'Kho tài liệu đang trống';
  $('documents-empty-description').textContent = docs.length ? 'Thử thay đổi từ khóa hoặc bộ lọc trạng thái.' : 'Tải lên PDF đầu tiên để xây dựng nguồn tra cứu của bạn.';
  $('empty-upload').hidden = docs.length > 0;
  $('table-summary').textContent = state.loaded ? `${filtered.length} / ${docs.length} tài liệu` : 'Đang tải danh sách tài liệu…';
  renderComposer();
}
async function refreshDocuments({ announce = false } = {}) {
  if (state.refreshing || state.authRequired) return;
  state.refreshing = true;
  try {
    const docs = await api.documents();
    const signature = JSON.stringify(docs);
    if (signature !== state.signature || !state.loaded) {
      state.documents = docs; state.loaded = true; state.signature = signature; renderDocuments();
    }
    if (announce) toast('Đã cập nhật danh sách tài liệu.');
    setConnection('', 'Đã kết nối');
  } catch (error) {
    if (error.status === 401) showError(error);
    else { setConnection('error', 'Mất kết nối'); if (announce || !state.loaded) showError(error); }
  } finally { state.refreshing = false; }
}
async function initialize() {
  try {
    await api.health();
    const capabilities = await api.capabilities();
    state.authRequired = false;
    state.generation = capabilities.generation_available;
    if (!state.capabilitiesLoaded) state.mode = state.generation ? 'ask' : 'search';
    state.capabilitiesLoaded = true;
    if (!state.generation) state.mode = 'search';
    $('upload-limit').textContent = `· Tối đa ${formatBytes(capabilities.max_upload_bytes)} / tệp`;
    $('ai-availability').textContent = state.generation ? 'Hỏi đáp AI đã được cấu hình. Bạn có thể dùng cả hai chế độ tra cứu.'
      : 'Hỏi đáp AI chưa được bật trên backend. Bạn vẫn có thể dùng Tìm đoạn gốc. Để bật AI, cấu hình OPENAI_API_KEY trên máy chủ rồi khởi động lại dịch vụ.';
    $('mode-ask').title = state.generation ? 'Tổng hợp câu trả lời có nguồn' : 'Chưa cấu hình dịch vụ AI. Xem Cài đặt kết nối.';
    await refreshDocuments(); renderComposer();
  } catch (error) { setConnection(error.status === 401 ? 'pending' : 'error', error.status === 401 ? 'Cần API key' : 'Không kết nối'); showError(error); renderComposer(); }
}
async function uploadFiles(files) {
  files = Array.from(files);
  if (state.uploading || !files.length) return;
  state.uploading = true; $('pick-files').disabled = true; $('dropzone').disabled = true;
  $('upload-progress').hidden = false;
  let accepted = 0;
  try {
    for (const [index, file] of [...files].entries()) {
      $('upload-progress').textContent = `Đang tải ${index + 1}/${files.length}: ${file.name}`;
      if (!file.name.toLocaleLowerCase().endsWith('.pdf')) { toast(`${file.name}: chỉ hỗ trợ tài liệu PDF.`, true); continue; }
      try {
        const result = await api.upload(file);
        accepted += 1;
        toast(result.duplicate ? `${file.name} đã có trong kho.` : `Đã nhận ${file.name}. Tài liệu đang được xử lý.`);
        await refreshDocuments();
      } catch (error) { showError(error); if (error.status === 401) break; }
    }
    $('upload-progress').textContent = accepted ? `Đã nhận ${accepted}/${files.length} tệp. Trạng thái xử lý sẽ tự cập nhật bên dưới.` : 'Chưa có tài liệu mới được nhận. Kiểm tra thông báo và thử lại.';
  } finally {
    state.uploading = false; $('pick-files').disabled = false; $('dropzone').disabled = false; $('file-input').value = '';
    await refreshDocuments();
  }
}
async function retry(id) {
  try { await api.retry(id); toast('Đã đưa tài liệu vào hàng đợi xử lý lại.'); await refreshDocuments(); } catch (error) { showError(error); }
}
function confirmDelete(doc) {
  state.pendingDelete = doc; $('delete-filename').textContent = doc.filename; $('delete-dialog').showModal();
}
async function deleteDocument() {
  if (!state.pendingDelete) return;
  const doc = state.pendingDelete; $('confirm-delete').disabled = true;
  try {
    await api.remove(doc.id); $('delete-dialog').close(); state.scope.delete(doc.id);
    state.lastSources = state.lastSources.filter(source => source.document_id !== doc.id); renderSources(state.lastSources);
    toast(`Đã xóa ${doc.filename}.`); await refreshDocuments();
  } catch (error) { showError(error); } finally { $('confirm-delete').disabled = false; if (!$('delete-dialog').open) state.pendingDelete = null; }
}
const legalWorkspace = createLegalWorkspace({api, refresh:refreshDocuments, getDocuments:()=>state.documents, preview, showError, toast});
async function preview(id, filename, page = 1, source = null) {
  const request = ++state.previewRequest;
  const reusePdf = state.previewId === id && state.pdfUrl;
  state.previewId = id; state.previewFilename = filename;
  $('pdf-title').textContent = filename;
  $('pdf-evidence').hidden = !source;
  $('pdf-evidence-label').textContent = source ? sourceLabel(source) : '';
  $('pdf-evidence-text').textContent = source?.text || '';
  $('pdf-evidence-id').textContent = source ? `Đoạn ${source.chunk_id} · SHA-256 ${source.sha256} · hồ sơ lần sửa ${source.document_revision}` : '';
  $('pdf-page-label').textContent = `TÀI LIỆU GỐC · TRANG ${page}`;
  $('pdf-loading').hidden = false; $('pdf-loading').textContent = 'Đang tải trang tài liệu…';
  $('pdf-image').hidden = true; $('pdf-previous').disabled = true; $('pdf-next').disabled = true;
  if (!$('pdf-dialog').open) $('pdf-dialog').showModal();
  try {
    const [image, pdf] = await Promise.all([api.page(id, page, source?.chunk_id), reusePdf ? Promise.resolve(null) : api.file(id)]);
    if (request !== state.previewRequest) return;
    if (pdf) {
      if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl);
      state.pdfUrl = URL.createObjectURL(pdf);
      $('pdf-download').href = state.pdfUrl; $('pdf-download').download = filename;
    }
    if (state.pageUrl) URL.revokeObjectURL(state.pageUrl);
    state.pageUrl = URL.createObjectURL(image.blob);
    state.page = page; state.pageCount = image.pageCount;
    $('pdf-image').alt = `${filename} — trang ${page} trên ${image.pageCount}`;
    $('pdf-image').src = state.pageUrl; $('pdf-image').hidden = false; $('pdf-loading').hidden = true;
    $('pdf-position').textContent = `Trang ${page} / ${image.pageCount}`;
    $('pdf-previous').disabled = page <= 1; $('pdf-next').disabled = page >= image.pageCount;
  } catch (error) {
    if (request !== state.previewRequest) return;
    $('pdf-loading').textContent = error.message; showError(error);
  }
}
function renderSources(sources) {
  state.lastSources = sources; $('source-count').textContent = sources.length;
  const container = $('sources'); container.replaceChildren();
  if (!sources.length) {
    const empty = node('div', 'sources-empty');
    empty.append(icon('file'), node('h3', '', 'Chưa có nguồn để đối chiếu'), node('p', '', 'Nguồn của mỗi lần tra cứu sẽ hiển thị tại đây.'));
    container.append(empty); return;
  }
  for (const source of sources) {
    const card = node('article', 'source-card');
    const heading = node('div', 'source-card-heading');
    heading.append(node('span', 'source-index', source.citation_id), node('h3', '', source.filename));
    card.append(heading, node('div', 'source-meta', sourceLabel(source)));
    const details = node('details'); details.append(node('summary', '', 'Đọc đoạn trích'), node('p', '', source.text));
    const button = actionButton(`Xem trang ${source.page}`, 'external', () => preview(source.document_id, source.filename, source.page, source), 'text-button');
    button.append(document.createTextNode('Mở trang gốc'));
    card.append(node('p','field-help',`${reviewLabel(source.review_status)} · ${validityLabel(source.validity_status)}`));
    if (source.original_source_url) {
      const link=node('a','text-button','Nguồn công bố'); link.href=source.original_source_url; link.target='_blank';link.rel='noopener noreferrer'; card.append(link);
    }
    card.append(details, button); container.append(card);
  }
}
function appendCitedText(container, text, sources) {
  const known = new Map(sources.map(source => [String(source.citation_id), source]));
  let cursor = 0;
  for (const match of text.matchAll(/\[(\d+)\]/g)) {
    container.append(document.createTextNode(text.slice(cursor, match.index)));
    const source = known.get(match[1]);
    if (source) {
      const button = node('button', 'inline-citation', `[${match[1]}]`);
      button.type = 'button'; button.title = `${source.filename} · Trang ${source.page}`;
      button.addEventListener('click', () => { renderSources(sources); preview(source.document_id, source.filename, source.page, source); });
      container.append(button);
    } else container.append(document.createTextNode(match[0]));
    cursor = match.index + match[0].length;
  }
  container.append(document.createTextNode(text.slice(cursor)));
}
function addMessage(message) {
  state.messages.push(message); $('welcome').hidden = true;
  const item = node('article', `message ${message.role}${message.error ? ' error' : ''}`);
  const header = node('div', 'message-header');
  header.append(node('span', 'message-avatar', message.role === 'user' ? 'B' : 'L'), document.createTextNode(message.role === 'user' ? 'Bạn' : message.mode === 'search' ? 'Kết quả tra cứu' : 'Legal RAG'));
  const content = node('div', 'message-content');
  appendCitedText(content, message.text, message.sources || []);
  item.append(header, content);
  if (message.mode === 'search') {
    for (const source of (message.sources || [])) {
      const excerpt = node('div', 'search-excerpt'); const heading = node('header');
      heading.append(node('span', '', `[${source.citation_id}] ${source.filename}`), node('span', '', sourceLabel(source)));
      excerpt.append(heading, node('p', '', source.text));
      const open = actionButton('Mở PDF tại trang nguồn', 'external', () => { renderSources(message.sources); preview(source.document_id, source.filename, source.page, source); }, '');
      open.append(document.createTextNode('Xem trong tài liệu gốc')); excerpt.append(open); item.append(excerpt);
    }
  } else if (message.sources?.length) {
    const links = node('div', 'message-source-links');
    for (const source of message.sources) {
      const button = node('button', 'source-chip', `[${source.citation_id}] ${source.filename} · tr. ${source.page}`);
      button.title = `${source.article || 'Nguồn'} · Trang ${source.page}`;
      button.addEventListener('click', () => { renderSources(message.sources); preview(source.document_id, source.filename, source.page, source); }); links.append(button);
    }
    item.append(links);
  }
  $('messages').append(item); scrollConversation();
}
function scrollConversation() { $('conversation-body').scrollTop = $('conversation-body').scrollHeight; }
async function submitQuestion(event) {
  event.preventDefault();
  const input = $('question-input'); const question = input.value.trim();
  if (!question || state.busy || !readyDocuments().length || state.authRequired) return;
  state.busy = true; const mode = state.mode; const scope = [...state.scope];
  addMessage({ role: 'user', text: question }); input.value = ''; renderComposer();
  const loading = node('div', 'thinking'); loading.setAttribute('role', 'status'); loading.setAttribute('aria-label', 'Đang tra cứu tài liệu');
  for (let i = 0; i < 3; i++) loading.append(node('span')); $('messages').append(loading); scrollConversation();
  try {
    const result = await api.query(mode, question, scope);
    const sources = mode === 'ask' ? result.citations : result.sources;
    const text = mode === 'ask' ? result.answer : sources.length ? `Tìm thấy ${sources.length} đoạn tài liệu liên quan. Bạn có thể đọc nội dung và mở trang gốc bên dưới.` : 'Chưa tìm thấy đoạn tài liệu đủ liên quan. Thử dùng từ khóa cụ thể hơn hoặc mở rộng phạm vi tra cứu.';
    loading.remove(); addMessage({ role: 'assistant', text, mode, sources }); renderSources(sources);
  } catch (error) {
    loading.remove(); addMessage({ role: 'assistant', text: error.message, error: true });
    if (error.status === 401) showError(error);
  } finally { state.busy = false; renderComposer(); input.focus(); scrollConversation(); }
}
function openScope() {
  const options = $('scope-options'); options.replaceChildren();
  const docs = readyDocuments();
  if (!docs.length) options.append(node('p', 'dialog-description', 'Chưa có tài liệu sẵn sàng. Thêm tài liệu và chờ xử lý xong để chọn nguồn.'));
  for (const doc of docs) {
    const label = node('label', 'scope-option'); const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = doc.id; checkbox.checked = state.scope.has(doc.id);
    label.append(checkbox, node('span', '', doc.filename)); options.append(label);
  }
  $('scope-dialog').showModal();
}

// All user-provided content is inserted as text nodes, never as HTML.
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.view)));
document.querySelectorAll('[data-go-documents]').forEach(button => button.addEventListener('click', () => navigate('documents')));
document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$('open-settings').addEventListener('click', () => $('settings-dialog').showModal());
$('connection-status').addEventListener('click', () => $('settings-dialog').showModal());
$('settings-form').addEventListener('submit', async event => {
  event.preventDefault(); api.setKey($('api-key').value); $('api-key').value = ''; state.authRequired = false; state.signature = null;
  $('settings-dialog').close(); await initialize();
});
$('pdf-dialog').addEventListener('close', () => {
  state.previewRequest += 1; $('pdf-image').removeAttribute('src');
  if (state.pageUrl) URL.revokeObjectURL(state.pageUrl); state.pageUrl = null; state.previewId = null;
  if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl); state.pdfUrl = null; $('pdf-download').removeAttribute('href');
});
$('pdf-previous').addEventListener('click', () => preview(state.previewId, state.previewFilename, state.page - 1));
$('pdf-next').addEventListener('click', () => preview(state.previewId, state.previewFilename, state.page + 1));
$('pick-files').addEventListener('click', () => $('file-input').click());
$('empty-upload').addEventListener('click', () => $('file-input').click());
$('dropzone').addEventListener('click', () => $('file-input').click());
$('file-input').addEventListener('change', event => uploadFiles(event.target.files));
for (const name of ['dragenter', 'dragover']) $('dropzone').addEventListener(name, event => { event.preventDefault(); $('dropzone').classList.add('dragging'); });
for (const name of ['dragleave', 'drop']) $('dropzone').addEventListener(name, event => { event.preventDefault(); $('dropzone').classList.remove('dragging'); });
$('dropzone').addEventListener('drop', event => uploadFiles(event.dataTransfer.files));
// Prevent dropping a PDF outside the dropzone from navigating away from the workspace.
window.addEventListener('dragover', event => { if ([...event.dataTransfer.types].includes('Files')) event.preventDefault(); });
window.addEventListener('drop', event => { if ([...event.dataTransfer.types].includes('Files')) event.preventDefault(); });
$('refresh-documents').addEventListener('click', () => refreshDocuments({ announce: true }));
$('document-search').addEventListener('input', renderDocuments);
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  state.filter = button.dataset.filter; document.querySelectorAll('[data-filter]').forEach(item => item.classList.toggle('active', item === button)); renderDocuments();
}));
$('confirm-delete').addEventListener('click', deleteDocument);
$('question-form').addEventListener('submit', submitQuestion);
$('question-input').addEventListener('input', renderComposer);
$('question-input').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('question-form').requestSubmit(); } });
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => { if (!state.busy) { state.mode = button.dataset.mode; renderComposer(); } }));
$('new-session').addEventListener('click', () => { if (state.busy) return; state.messages = []; $('messages').replaceChildren(); renderSources([]); renderComposer(); });
$('open-scope').addEventListener('click', openScope);
$('scope-all').addEventListener('click', () => { state.scope.clear(); $('scope-dialog').close(); renderComposer(); });
$('save-scope').addEventListener('click', () => { state.scope = new Set([...$('scope-options').querySelectorAll('input:checked')].map(input => input.value)); $('scope-dialog').close(); renderComposer(); });
let lastHealthCheck = Date.now();
async function poll() {
  if (!document.hidden && !state.authRequired) {
    if (Date.now() - lastHealthCheck > 60000) { lastHealthCheck = Date.now(); await initialize(); }
    else await refreshDocuments();
  }
  state.polling = setTimeout(poll, activeDocuments().length ? 3000 : 10000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && !state.authRequired) refreshDocuments(); });
window.addEventListener('beforeunload', () => { clearTimeout(state.polling); if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl); if (state.pageUrl) URL.revokeObjectURL(state.pageUrl); });
await initialize();
state.polling = setTimeout(poll, 3000);
