"""P0 workflow/invariant tests, not a legal quality benchmark."""
import json
import sqlite3
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.config import Settings
from backend.documents import Registry
from backend.service import DocumentService
from test_api import stack, upload, pdf_bytes, wait_status, approve_document, TestIndex, Generator


def payload(doc, **changes):
    data = {k:doc[k] for k in ['document_code','title','version','source_url','source_note','effective_from','effective_to','validity_note']}
    return {**data,'expected_revision':doc['revision'],'actor':'Reviewer A','reason':'Check source',**changes}


def decide(client,doc,decision='approved'):
    return client.post(f"/documents/{doc['id']}/review",json={
        'expected_revision':doc['revision'],'decision':decision,'actor':'Reviewer A','note':'Compared with original source'})


def test_draft_gate_metadata_validation_and_revision_conflict(stack):
    c,_,_=stack
    id=upload(c).json()['document']['id']
    draft=wait_status(c,id,approve=False)
    assert draft['review_status']=='draft' and draft['validity_status']=='unknown'
    assert not c.post('/search',json={'question':'capital','max_distance':2}).json()['sources']
    assert c.post('/search',json={'question':'capital','document_ids':[id]}).status_code==409
    assert decide(c,draft).status_code==422
    base=f'/documents/{id}'
    for changes in [dict(source_url='javascript:alert(1)'), dict(effective_from='2026-02-01',effective_to='2025-02-01'),dict(version=' '),dict(effective_from='bad-date')]:
        assert c.patch(base+'/metadata',json=payload(draft,**changes)).status_code==422
    approved=approve_document(c,draft)
    assert approved['review_status']=='approved'
    update=payload(approved,effective_from='2020-01-01',effective_to='2021-01-01')
    changed=c.patch(base+'/metadata',json=update).json()
    assert changed['review_status']=='draft' and changed['validity_status']=='expired'
    assert c.patch(base+'/metadata',json=update).status_code==409
    assert decide(c,approved).status_code==409
    assert decide(c,changed,'rejected').json()['review_status']=='rejected'
    assert not c.post('/search',json={'question':'capital','max_distance':2}).json()['sources']
    history=c.get(base+'/history').json()
    assert {h['event'] for h in history}>={'uploaded','metadata_updated','review_approved','review_rejected'}
    assert history[-1]['snapshot']['document']['revision']==1


def test_version_ingestion_dedup_collision_and_exact_delete(stack):
    c,svc,_=stack
    one=upload(c,pdf_bytes('Version one capital.')).json()['document']['id']
    old=wait_status(c,one)
    content=pdf_bytes('Version two capital. Modified text.')
    meta={'version':'2','document_code':old['document_code'],'title':old['title']}
    def new(data=content,metadata=meta):
        return c.post('/documents?parent_id='+one,data={'metadata':json.dumps(metadata)},files={'file':('v2.pdf',data,'application/pdf')})
    result=new();assert result.status_code==202,result.text
    two=result.json()['document']['id']; newdoc=wait_status(c,two,approve=False)
    assert newdoc['family_id']==old['family_id'] and newdoc['review_status']=='draft'
    assert new().json()['duplicate'] is True
    assert new(pdf_bytes('Different bytes for same version')).status_code==409
    assert new(metadata={'version':'3'}).status_code==409 # same bytes, different version label
    assert c.get(f'/documents/{one}').json()['revision']==old['revision']
    versions=c.get(f'/documents/{one}/versions').json(); assert {d['version'] for d in versions}=={'1','2'}
    assert c.post('/documents',files={'file':('bad.pdf',b'bad','application/pdf')}).status_code==422
    assert c.get(f'/documents/{one}/file').status_code==200
    approve_document(c,newdoc)
    assert c.delete(f'/documents/{two}').status_code==204
    assert c.get(f'/documents/{two}').status_code==404
    assert c.get(f'/documents/{one}/file').status_code==200
    assert c.post('/search',json={'question':'capital','document_ids':[one],'max_distance':2}).json()['sources']
    assert svc.registry.get(two)['status']=='deleted'
    assert c.get(f'/documents/{two}/history').json()[0]['event']=='deleted'
    assert any(d['status']=='deleted' for d in c.get(f'/documents/{one}/versions').json())
    assert not svc.registry.chunks(two)
    assert not list(svc.files.glob('*.upload'))


def test_relationships_cycles_remove_and_review_reset(stack):
    c,_,_=stack
    docs=[]
    for i in range(3):
        id=upload(c,pdf_bytes(f'Document {i} capital.')).json()['document']['id'];docs.append(wait_status(c,id))
    a,b,d=docs
    def relate(source,target,kind='replaces'):
        return c.post(f"/documents/{source['id']}/relationships",json={
            'expected_revision':source['revision'],'target_id':target['id'],'kind':kind,
            'effective_on':'2025-01-01','note':'Only this stated scope','actor':'Reviewer A'})
    assert relate(a,a).status_code==422
    a=relate(a,b).json(); assert a['review_status']=='draft'
    b=relate(b,d,'amends').json()
    assert relate(d,a).status_code==409
    relation=a['relationships'][0]
    body={'expected_revision':a['revision'],'actor':'Reviewer A','note':'Correct mistaken relation','decision':'draft'}
    assert c.request('DELETE',f"/documents/{b['id']}/relationships/{relation['id']}",json={**body,'expected_revision':b['revision']}).status_code==404
    result=c.request('DELETE',f"/documents/{a['id']}/relationships/{relation['id']}",json=body)
    assert result.status_code==200 and not result.json()['relationships']


def unicode_pdf():
    font=Path('/System/Library/Fonts/Supplemental/Arial.ttf')
    if not font.exists(): pytest.skip('Unicode font not present')
    with pymupdf.open() as pdf:
        for text in ['Điều 1. Yêu cầu\n1. Ngân hàng phải duy trì vốn phù hợp.\na) Bảo mật thông tin khách hàng.\n2. Kiểm tra hồ sơ trước khi duyệt.',
                     'Tiếp tục khoản hai.\nĐiều 2. Quy định khác\n1. Đối chiếu nguồn tài liệu gốc.']:
            p=pdf.new_page();p.insert_font(fontname='arial',fontfile=str(font));p.insert_text((50,70),text,fontname='arial')
        return pdf.tobytes()


def test_exact_article_clause_point_offsets_highlight_and_claims(stack,monkeypatch):
    c,svc,_=stack
    content=unicode_pdf();id=upload(c,content).json()['document']['id'];wait_status(c,id)
    chunks=c.get(f'/documents/{id}/chunks').json()
    assert any(e['article']=='Điều 1' and e['clause']=='1' and e['point']=='a' for e in chunks)
    assert any(e['page']==2 and e['article']=='Điều 1' and e['clause']=='2' for e in chunks)
    with pymupdf.open(stream=content,filetype='pdf') as pdf:
        for e in chunks:
            assert pdf[e['page']-1].get_text('text',sort=True)[e['start_char']:e['end_char']]==e['text']
    hits=c.post('/search',json={'question':'capital','max_distance':2,'top_k':20}).json()['sources']
    assert hits and hits[0]['sha256']==id and hits[0]['review_status']=='approved'
    source=hits[0]
    assert c.get(f"/documents/{id}/chunks/{source['chunk_id'].split(':')[-1]}").json()['text']==source['text']
    normal=c.get(f"/documents/{id}/pages/{source['page']}")
    highlighted=c.get(f"/documents/{id}/pages/{source['page']}",params={'chunk_id':source['chunk_id']})
    assert highlighted.status_code==200 and normal.content!=highlighted.content
    assert c.get(f'/documents/{id}/pages/2',params={'chunk_id':chunks[0]['chunk_id']}).status_code==422
    other=upload(c,pdf_bytes('Other source')).json()['document']['id'];wait_status(c,other)
    assert c.get(f'/documents/{other}/pages/1',params={'chunk_id':source['chunk_id']}).status_code==404
    monkeypatch.setattr(svc.generator,'answer',lambda q,s:{'claims':[{'citation_id':'1','quote':s[0]['text']}],'answer':'Injected unsupported prose','insufficient_evidence':False})
    answer=c.post('/ask',json={'question':'capital','max_distance':2}).json()
    assert not answer['insufficient_evidence'] and answer['claims']
    assert 'Injected unsupported' not in answer['answer']
    for claim in [{'citation_id':'1','quote':'Fabricated source text'}, {'citation_id':'999','quote':source['text']}, {'citation_id':'1','quote':''}]:
        monkeypatch.setattr(svc.generator,'answer',lambda *_,claim=claim:{'claims':[claim],'insufficient_evidence':False})
        assert c.post('/ask',json={'question':'capital','max_distance':2}).json()['insufficient_evidence']


def test_revocation_during_generation_discards_answer(stack,monkeypatch):
    c,svc,_=stack
    id=upload(c).json()['document']['id'];doc=wait_status(c,id)
    def generate(q,s):
        assert decide(c,doc,'draft').status_code==200
        return {'claims':[{'citation_id':'1','quote':s[0]['text']}],'insufficient_evidence':False}
    monkeypatch.setattr(svc.generator,'answer',generate)
    assert c.post('/ask',json={'question':'capital','max_distance':2}).json()['insufficient_evidence']


def test_old_registry_and_chunk_schema_migrate_without_pdf_loss(tmp_path):
    root=tmp_path; (root/'files').mkdir()
    content=pdf_bytes('Legacy PDF capital.')
    import hashlib
    id=hashlib.sha256(content).hexdigest(); (root/'files'/f'{id}.pdf').write_bytes(content)
    with sqlite3.connect(root/'registry.sqlite3') as db:
        db.execute('''CREATE TABLE documents (id TEXT PRIMARY KEY,filename TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE,
        size_bytes INTEGER NOT NULL,status TEXT NOT NULL,page_count INTEGER NOT NULL DEFAULT 0,chunk_count INTEGER NOT NULL DEFAULT 0,
        error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
        db.execute("INSERT INTO documents VALUES(?,?,?,?,'ready',1,1,NULL,'2020','2020')",(id,'legacy.pdf',id,len(content)))
    settings=Settings(data_dir=root)
    (root/'index_config.json').write_text(json.dumps({'embedding_model':settings.embedding_model,'chunk_schema':2}))
    svc=DocumentService(settings,index=TestIndex(root/'chroma','test'),generator=Generator())
    with TestClient(create_app(settings,svc)) as c:
        doc=wait_status(c,id,approve=False)
        assert doc['family_id']==id and doc['review_status']=='draft'
        assert (root/'files'/f'{id}.pdf').read_bytes()==content
        assert c.get(f'/documents/{id}/chunks').json()
        assert not c.post('/search',json={'question':'capital'}).json()['sources']
        assert json.loads((root/'index_config.json').read_text())['chunk_schema']==5


def test_reupload_deleted_bytes_restores_same_version_as_draft(stack):
    c,svc,_=stack
    content=pdf_bytes('Restore this exact version capital.')
    id=upload(c,content).json()['document']['id']; original=wait_status(c,id)
    assert c.delete(f'/documents/{id}').status_code==204
    response=upload(c,content,'different-name.pdf')
    assert response.status_code==202,response.text
    restored=wait_status(c,id,approve=False)
    assert restored['family_id']==original['family_id'] and restored['version']==original['version']
    assert restored['filename']==original['filename'] and restored['document_code']==original['document_code']
    assert restored['review_status']=='draft' and restored['revision']>original['revision']
    assert svc.index.collection.count()==1
    assert not c.post('/search',json={'question':'capital','max_distance':2}).json()['sources']
    assert c.get(f'/documents/{id}/history').json()[0]['event']=='restored'


def test_p0_routes_require_api_key(tmp_path):
    settings=Settings(data_dir=tmp_path,api_key='secret')
    svc=DocumentService(settings,index=TestIndex(tmp_path/'chroma','test'),generator=Generator())
    with TestClient(create_app(settings,svc)) as c:
        for method,url in [('PATCH','/documents/x/metadata'),('POST','/documents/x/review'),
                           ('POST','/documents/x/relationships'),('DELETE','/documents/x/relationships/1'),
                           ('GET','/documents/x/versions'),('GET','/documents/x/history'),
                           ('GET','/documents/x/chunks'),('GET','/documents/x/chunks/0')]:
            assert c.request(method,url,json={} if method in ('POST','PATCH','DELETE') else None).status_code==401


def test_partial_metadata_update_preserves_other_fields_and_validates_merged_dates(stack):
    c,_,_=stack
    id=upload(c).json()['document']['id']; doc=wait_status(c,id)
    doc=c.patch(f'/documents/{id}/metadata',json=payload(doc,effective_from='2025-01-01')).json()
    changed=c.patch(f'/documents/{id}/metadata',json={
        'expected_revision':doc['revision'],'actor':'Reviewer','reason':'Fix title','title':'Corrected title'})
    assert changed.status_code==200
    new=changed.json()
    assert new['title']=='Corrected title' and new['source_url']==doc['source_url'] and new['document_code']==doc['document_code']
    assert new['effective_from']=='2025-01-01'
    assert c.patch(f'/documents/{id}/metadata',json={
        'expected_revision':new['revision'],'actor':'Reviewer','reason':'Wrong date','effective_to':'2020-01-01'}).status_code==422
