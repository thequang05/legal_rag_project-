/** Same-origin API client. Secrets never enter localStorage or URLs. */
export class ApiError extends Error {
  constructor(status, message) { super(message); this.name = 'ApiError'; this.status = status; }
}

export function createApi(fetcher = (...args) => fetch(...args)) {
  let key = '';
  async function request(path, { method = 'GET', body, binary = false, pageImage = false, timeout = 180000 } = {}) {
    const headers = new Headers();
    if (key) headers.set('X-API-Key', key);
    if (body && !(body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetcher(path, {
        method, headers, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
        signal: controller.signal, credentials: 'same-origin', cache: 'no-store',
      });
      if (!response.ok) {
        let detail;
        try { detail = (await response.json()).detail; } catch { /* Non-JSON gateway error. */ }
        const message = typeof detail === 'string' ? detail : response.status === 401
          ? 'Backend yêu cầu API key hợp lệ. Mở Cài đặt kết nối để nhập key.'
          : response.status === 413 ? 'Tài liệu vượt quá dung lượng cho phép.'
          : `Không thực hiện được yêu cầu (${response.status}). Vui lòng thử lại.`;
        throw new ApiError(response.status, message);
      }
      if (response.status === 204) return null;
      if (pageImage) return { blob: await response.blob(), pageCount: Number(response.headers.get("X-Page-Count") || 1) };
      return binary ? response.blob() : response.json();
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error.name === 'AbortError') throw new ApiError(0, 'Yêu cầu mất quá nhiều thời gian. Hãy kiểm tra trạng thái trước khi thử lại.');
      throw new ApiError(0, 'Không kết nối được backend. Kiểm tra dịch vụ rồi thử lại.');
    } finally { clearTimeout(timer); }
  }
  return {
    setKey(value) { key = value.trim(); },
    health: () => request('/health', { timeout: 8000 }),
    capabilities: () => request('/capabilities', { timeout: 10000 }),
    async documents() {
      const documents = [];
      for (let offset = 0; ; offset += 500) {
        const page = await request(`/documents?limit=500&offset=${offset}`, { timeout: 15000 });
        documents.push(...page);
        if (page.length < 500) return documents;
      }
    },
    upload(file, metadata = null, parentId = null) {
      const body = new FormData(); body.append('file', file);
      if (metadata) body.append('metadata', JSON.stringify(metadata));
      return request('/documents' + (parentId ? `?parent_id=${encodeURIComponent(parentId)}` : ''), { method:'POST', body });
    },
    document: id => request(`/documents/${encodeURIComponent(id)}`),
    metadata: (id, body) => request(`/documents/${encodeURIComponent(id)}/metadata`, {method:'PATCH',body}),
    review: (id, body) => request(`/documents/${encodeURIComponent(id)}/review`, {method:'POST',body}),
    versions: id => request(`/documents/${encodeURIComponent(id)}/versions`),
    history: id => request(`/documents/${encodeURIComponent(id)}/history`),
    relate: (id, body) => request(`/documents/${encodeURIComponent(id)}/relationships`, {method:'POST',body}),
    unrelate: (id, relation, body) => request(`/documents/${encodeURIComponent(id)}/relationships/${relation}`, {method:'DELETE',body}),
    chunks: (id, offset=0) => request(`/documents/${encodeURIComponent(id)}/chunks?limit=50&offset=${offset}`),
    retry: id => request(`/documents/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
    remove: id => request(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    page: (id, page, chunkId=null) => request(`/documents/${encodeURIComponent(id)}/pages/${page}` + (chunkId ? `?chunk_id=${encodeURIComponent(chunkId)}` : ''), { pageImage: true }),
    file: id => request(`/documents/${encodeURIComponent(id)}/file`, { binary: true }),
    query: (mode, question, documentIds) => request(mode === 'ask' ? '/ask' : '/search', {
      method: 'POST', body: { question, document_ids: documentIds },
    }),
  };
}

export const formatBytes = value => {
  if (value < 1024) return `${value} B`;
  if (value < 1048576) return `${(value / 1024).toFixed(0)} KB`;
  return `${(value / 1048576).toFixed(1)} MB`;
};
export const normalizeSearch = value => value.toLocaleLowerCase('vi').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');
