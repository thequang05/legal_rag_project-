import test from 'node:test';
import assert from 'node:assert/strict';
import { createApi, ApiError, formatBytes, normalizeSearch } from '../frontend/assets/api.js';

test('authenticated pagination loads every document without putting the key in URLs', async () => {
  const calls = [];
  const api = createApi(async (path, options) => {
    calls.push({ path, options });
    return Response.json(path.includes('offset=0') ? Array.from({ length: 500 }, (_, i) => ({ id: String(i) })) : [{ id: 'last' }]);
  });
  api.setKey(' secret ');
  const documents = await api.documents();
  assert.equal(documents.length, 501);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.headers.get('X-API-Key'), 'secret');
  assert.ok(calls.every(call => !call.path.includes('secret')));
});

test('upload is multipart, query retains scope and delete handles 204', async () => {
  const calls = [];
  const api = createApi(async (path, options) => {
    calls.push({ path, options });
    return options.method === 'DELETE' ? new Response(null, { status: 204 }) : Response.json({ ok: true });
  });
  await api.upload(new File(['%PDF'], 'law.pdf', { type: 'application/pdf' }));
  assert.ok(calls[0].options.body instanceof FormData);
  assert.equal(calls[0].options.headers.has('Content-Type'), false);
  await api.query('search', 'câu hỏi', ['abc']);
  assert.equal(calls[1].path, '/search');
  assert.deepEqual(JSON.parse(calls[1].options.body), { question: 'câu hỏi', document_ids: ['abc'] });
  assert.equal(await api.remove('abc'), null);
});

test('structured and non-JSON failures produce user-readable errors', async () => {
  const api = createApi(async () => Response.json({ detail: 'API key không hợp lệ.' }, { status: 401 }));
  await assert.rejects(api.documents(), error => error instanceof ApiError && error.status === 401);
  const gateway = createApi(async () => new Response('gateway error', { status: 502 }));
  await assert.rejects(gateway.health(), error => error.status === 502 && !error.message.includes('gateway error'));
});

test('network failures and authenticated PDF access', async () => {
  const offline = createApi(async () => { throw new TypeError('network'); });
  await assert.rejects(offline.health(), error => error.status === 0 && error.message.includes('Không kết nối'));
  const api = createApi(async (path, options) => {
    assert.equal(options.headers.get('X-API-Key'), 'key');
    assert.equal(path, '/documents/document/file');
    return new Response('%PDF', { headers: { 'Content-Type': 'application/pdf' } });
  });
  api.setKey('key');
  assert.equal(await (await api.file('document')).text(), '%PDF');
});

test('Vietnamese filename search ignores accents and formats actual file sizes', () => {
  assert.equal(normalizeSearch('Luật ĐẤT ĐAI.pdf'), 'luat dat dai.pdf');
  assert.equal(formatBytes(1048576), '1.0 MB');
});

test('page preview preserves image bytes and actual page count', async () => {
  const api = createApi(async path => {
    assert.equal(path, '/documents/id/pages/2');
    return new Response('image bytes', { headers: { 'Content-Type': 'image/png', 'X-Page-Count': '7' } });
  });
  const page = await api.page('id', 2);
  assert.equal(page.pageCount, 7);
  assert.equal(await page.blob.text(), 'image bytes');
});

test('version upload sends parent ID and metadata separately from file bytes', async () => {
  const api=createApi(async (url,options)=>{
    assert.equal(url,'/documents?parent_id=parent%3Aid');
    assert.equal(options.body.get('file').name,'v2.pdf');
    assert.deepEqual(JSON.parse(options.body.get('metadata')),{version:'2'});
    return Response.json({document:{id:'new'},duplicate:false});
  });
  assert.equal((await api.upload(new File(['PDF'],'v2.pdf'),{version:'2'},'parent:id')).document.id,'new');
});

test('legal mutations preserve revision and highlight requests bind to exact chunk', async () => {
  const calls=[];
  const api=createApi(async (url,options)=>{
    calls.push({url,...options});
    return url.includes('/pages/')?new Response('PNG',{headers:{'X-Page-Count':'2'}}):Response.json({id:'id'});
  });
  await api.metadata('id',{expected_revision:3,actor:'reviewer',reason:'source changed'});
  assert.equal(calls[0].method,'PATCH');
  assert.equal(JSON.parse(calls[0].body).expected_revision,3);
  await api.review('id',{expected_revision:4,decision:'approved',actor:'reviewer',note:'checked'});
  await api.relate('id',{target_id:'other',expected_revision:5,kind:'replaces'});
  await api.unrelate('id',2,{expected_revision:6,decision:'draft',actor:'reviewer',note:'fix'});
  assert.equal(calls[3].method,'DELETE');
  assert.equal(JSON.parse(calls[3].body).expected_revision,6);
  await api.page('id',1,'id:7');
  assert.equal(calls[4].url,'/documents/id/pages/1?chunk_id=id%3A7');
});
