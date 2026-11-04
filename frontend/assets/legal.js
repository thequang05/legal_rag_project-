/** Version/review workspace. Backend revisions guard concurrent edits. */
const el = (tag, text, cls) => {
  const n = document.createElement(tag); if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls; return n;
};
export const reviewLabel = status => ({draft:'Chờ duyệt',approved:'Đã duyệt nguồn',rejected:'Từ chối'}[status] || status);
export const validityLabel = status => ({unknown:'Chưa xác định ngày hiệu lực',not_yet_effective:'Chưa đến ngày hiệu lực',expired:'Đã đến ngày hết hiệu lực',within_recorded_dates:'Trong khoảng ngày đã ghi nhận'}[status] || status);
export const sourceLabel = source => [source.document_code, `bản ${source.version || '1'}`, source.article,
  source.clause ? `Khoản ${source.clause}` : '', source.point ? `Điểm ${source.point}` : '', `Trang ${source.page}`].filter(Boolean).join(' · ');

export function createLegalWorkspace({api, refresh, getDocuments, preview, showError, toast}) {
  const dialog = el('dialog',undefined,'dialog legal-dialog');
  dialog.setAttribute('aria-label','Hồ sơ văn bản'); document.body.append(dialog);
  let current = null, generation = 0, busy = false;
  const field = (form, name, label, value='', type='text', required=false) => {
    const wrap = el('label',undefined,'legal-field'); wrap.append(el('span',label));
    const input = el(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    input.name = name; input.value = value || ''; input.required = required;
    input.className = 'text-input'; input.maxLength = type === 'textarea' ? 2000 : 500;
    wrap.append(input); form.append(wrap); return input;
  };
  const button = (text, action, cls='button secondary') => {
    const b=el('button',text,cls); b.type='button'; b.addEventListener('click',action); return b;
  };
  const run = async operation => {
    if (busy) return;
    busy=true; dialog.querySelectorAll('button').forEach(b=>b.disabled=true);
    try { const next = await operation(); await refresh(); await open(next?.id || current.id); }
    catch(error) { showError(error); }
    finally { busy=false; dialog.querySelectorAll('button').forEach(b=>b.disabled=false); }
  };
  async function open(id) {
    const request=++generation;
    dialog.replaceChildren(el('p','Đang tải hồ sơ…'));
    if (!dialog.open) dialog.showModal();
    try {
      const [doc, versions, history] = await Promise.all([api.document(id),api.versions(id),api.history(id)]);
      if (request !== generation || !dialog.open) return;
      current=doc; render(doc,versions,history);
    } catch(error) { dialog.replaceChildren(el('p',error.message),button('Đóng',()=>dialog.close())); showError(error); }
  }
  function render(doc, versions, history) {
    dialog.replaceChildren();
    const heading=el('div',undefined,'dialog-heading');
    heading.append(el('h2',doc.title || doc.filename),button('Đóng hồ sơ',()=>dialog.close())); dialog.append(heading);
    dialog.append(el('p',`${reviewLabel(doc.review_status)} · ${validityLabel(doc.validity_status)} · lần sửa hồ sơ ${doc.revision}`,'dialog-description'));
    const warning=el('p','Duyệt nguồn là xác nhận của người vận hành. Tên người duyệt được tự khai theo API key dùng chung; chưa phải tài khoản phân quyền. Ngày để trống nghĩa là chưa xác định. Ngày hết hiệu lực là ngày đầu tiên không còn áp dụng.','field-help'); dialog.append(warning);
    const form=el('form',undefined,'legal-grid');
    field(form,'document_code','Mã văn bản',doc.document_code,'text',true);
    field(form,'title','Tên văn bản',doc.title,'text',true);
    field(form,'version','Phiên bản',doc.version,'text',true);
    field(form,'source_url','URL nguồn đối chiếu',doc.source_url,'url',true);
    field(form,'effective_from','Ngày có hiệu lực',doc.effective_from,'date');
    field(form,'effective_to','Ngày hết hiệu lực',doc.effective_to,'date');
    field(form,'source_note','Căn cứ / xuất xứ nguồn',doc.source_note,'textarea',true);
    field(form,'validity_note','Căn cứ hiệu lực / lý do chưa xác định',doc.validity_note,'textarea',true);
    field(form,'actor','Người thao tác','','text',true);
    field(form,'reason','Lý do sửa hồ sơ','','textarea',true);
    const save=el('button','Lưu hồ sơ → chờ duyệt','button primary'); save.type='submit'; form.append(save);
    form.addEventListener('submit',event=>{event.preventDefault(); const data=Object.fromEntries(new FormData(form));
      data.effective_from ||= null; data.effective_to ||= null;
      run(()=>api.metadata(doc.id,{...data,expected_revision:doc.revision})); });
    dialog.append(el('h3','Hồ sơ và hiệu lực'),form);
    const review=el('form',undefined,'legal-grid');
    field(review,'actor','Người duyệt','','text',true); field(review,'note','Ghi chú quyết định','','textarea',true);
    const decision=el('select'); decision.name='decision'; decision.className='text-input';
    for (const [value,label] of [['approved','Duyệt nguồn'],['rejected','Từ chối nguồn'],['draft','Rút duyệt / chờ duyệt']]) {
      const option=el('option',label); option.value=value; decision.append(option);
    }
    const decisionLabel=el('label',undefined,'legal-field');decisionLabel.append(el('span','Quyết định'),decision);review.append(decisionLabel);
    const submit=el('button','Ghi nhận quyết định','button primary');submit.type='submit';review.append(submit);
    review.addEventListener('submit',event=>{event.preventDefault();run(()=>api.review(doc.id,{...Object.fromEntries(new FormData(review)),expected_revision:doc.revision}));});
    dialog.append(el('h3','Duyệt nguồn'),el('p',doc.reviewed_by ? `Lần quyết định gần nhất: ${doc.reviewed_by} · ${doc.review_note}` : 'Chưa có quyết định duyệt.','field-help'),review);
    const relationForm=el('form',undefined,'legal-grid');
    const target=el('select');target.name='target_id';target.className='text-input';target.required=true;
    const placeholder=el('option','Chọn đúng phiên bản đích');placeholder.value='';target.append(placeholder);
    for(const other of getDocuments().filter(d=>d.id!==doc.id)) {const o=el('option',`${other.document_code || other.filename} · bản ${other.version}`);o.value=other.id;target.append(o);}
    const targetLabel=el('label',undefined,'legal-field');targetLabel.append(el('span','Văn bản / phiên bản đích'),target);relationForm.append(targetLabel);
    const kind=el('select');kind.name='kind';kind.className='text-input';
    for(const [value,label] of [['amends','Sửa đổi / bổ sung'],['replaces','Thay thế']]) {const o=el('option',label);o.value=value;kind.append(o);}
    const kindLabel=el('label',undefined,'legal-field');kindLabel.append(el('span','Bản đang mở có quan hệ'),kind);relationForm.append(kindLabel);
    field(relationForm,'effective_on','Ngày quan hệ bắt đầu (nếu biết)','','date');
    field(relationForm,'actor','Người ghi nhận quan hệ','','text',true);
    field(relationForm,'note','Phạm vi / căn cứ sửa đổi, thay thế','','textarea',true);
    const relate=el('button','Thêm quan hệ → chờ duyệt','button secondary');relate.type='submit';relationForm.append(relate);
    relationForm.addEventListener('submit',event=>{event.preventDefault();const data=Object.fromEntries(new FormData(relationForm)); data.effective_on ||= null;
      run(()=>api.relate(doc.id,{...data,expected_revision:doc.revision}));});
    dialog.append(el('h3','Sửa đổi / thay thế'),el('p','Quan hệ không tự thay đổi ngày hiệu lực hay nội dung bản cũ. Ghi rõ phạm vi sửa đổi; cập nhật hồ sơ đích khi có căn cứ.','field-help'));
    for(const r of doc.relationships) {
      const item=el('div',undefined,'legal-relation');
      const outgoing=r.source_id===doc.id;
      const peer=getDocuments().find(d=>d.id===(outgoing?r.target_id:r.source_id));
      item.append(el('p',`${outgoing?'Bản này':'Bản '+(peer?.version || r.source_id.slice(0,10))} ${r.kind==='replaces'?'thay thế':'sửa đổi'} ${outgoing?((peer?.document_code || r.target_id)+' · bản '+(peer?.version || 'đã xóa')):'bản này'} · ${r.effective_on || 'ngày chưa xác định'} · ${r.note}`));
      if(outgoing) item.append(button('Gỡ quan hệ',()=>{
        if(!relationForm.elements.actor.reportValidity() || !relationForm.elements.note.reportValidity()) { toast('Điền người thao tác và ghi chú trong biểu mẫu quan hệ để ghi nhận việc gỡ.',true); return; }
        const data=Object.fromEntries(new FormData(relationForm));
        run(()=>api.unrelate(doc.id,r.id,{expected_revision:doc.revision,decision:'draft',actor:data.actor,note:data.note}));
      }));
      dialog.append(item);
    }
    dialog.append(relationForm);
    const versionList=el('div',undefined,'legal-version-list');
    for(const version of versions) {
      const entry=el('div',undefined,'legal-relation'); entry.append(el('span',`Bản ${version.version} · ${version.filename} · ${version.status==='deleted'?'Đã xóa':reviewLabel(version.review_status)}`));
      if(version.id!==doc.id && version.status!=='deleted') entry.append(button('Mở hồ sơ phiên bản',()=>open(version.id)));versionList.append(entry);
    }
    const newVersion=el('form',undefined,'legal-grid');
    field(newVersion,'version','Mã phiên bản mới','','text',true);
    const file=field(newVersion,'file','PDF của phiên bản mới','','file',true);file.accept='.pdf,application/pdf';
    const create=el('button','Nạp phiên bản mới','button secondary');create.type='submit';newVersion.append(create);
    newVersion.addEventListener('submit',event=>{event.preventDefault();run(async()=>{
      const result=await api.upload(file.files[0],{version:newVersion.elements.version.value,document_code:doc.document_code,title:doc.title},doc.id);
      toast(result.duplicate?'Nội dung đã tồn tại; hồ sơ không bị ghi đè.':'Đã nhận phiên bản mới, cần cập nhật nguồn và duyệt riêng.');
      return result.document;
    });});
    dialog.append(el('h3','Các phiên bản cùng văn bản'),versionList,newVersion);
    const chunkList=el('div',undefined,'legal-evidence');let offset=0;
    const load=button('Xem các đoạn gốc để duyệt',async()=>{
      load.disabled=true;
      try {const chunks=await api.chunks(doc.id,offset); offset+=chunks.length;
        for(const chunk of chunks) {const detail=el('details');detail.append(el('summary',sourceLabel(chunk)),el('pre',chunk.text));
          detail.append(button('Mở trang có đánh dấu',()=>preview(doc.id,doc.filename,chunk.page,chunk)));chunkList.append(detail);}
        load.textContent=chunks.length<50?'Đã tải hết đoạn gốc':'Tải thêm 50 đoạn'; load.hidden=chunks.length<50;
      } catch(error){showError(error);} finally{load.disabled=false;}
    });
    dialog.append(el('h3','Đối chiếu PDF và đoạn gốc'),button('Mở PDF gốc',()=>preview(doc.id,doc.filename)),chunkList,load);
    dialog.append(el('h3','Lịch sử hồ sơ'));
    for(const item of history) {
      const details=el('details');details.append(el('summary',`${new Date(item.at).toLocaleString('vi-VN')} · ${item.event} · ${item.actor}`),el('p',item.reason));
      details.append(el('pre',JSON.stringify(item.snapshot,null,2)));dialog.append(details);
    }
  }
  dialog.addEventListener('close',()=>{generation++;});
  return {open};
}
