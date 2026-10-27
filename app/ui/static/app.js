import { parseSSE } from "/static/sse.js";
const $ = s => document.querySelector(s);
const node = (tag, text, cls) => { const e = document.createElement(tag); if(text !== undefined) e.textContent = text; if(cls) e.className = cls; return e; };
let answer = '', offset = 0, total = 0, controller;
let citations = [], evidenceCount = 0;
const admin = () => sessionStorage.getItem('adminToken') || '';
async function api(path, options = {}) { const r = await fetch(path, options); if(!r.ok) { const data = await r.json().catch(() => ({})); throw Error(data.error?.message || data.detail?.toString() || `Request failed (${r.status})`); } return r.status === 204 ? null : r.json(); }
function report(e) { $('#global-status').textContent = e.message; $('#status').textContent = e.message; $('#status').className = 'error'; }
function jsonView(value) { return node('pre', JSON.stringify(value, null, 2)); }
function details(title, value) { const e = node('details'); e.append(node('summary', title), jsonView(value)); return e; }
function openDrawer(...children) { $('#drawer-content').replaceChildren(...children); if(!$('#drawer').open) $('#drawer').showModal(); }
$('#close-drawer').onclick = () => $('#drawer').close();
$('#settings').onclick = () => { $('#admin-token').value = admin(); $('#settings-dialog').showModal(); };
$('#save-settings').onclick = () => { sessionStorage.setItem('adminToken', $('#admin-token').value); loadDocuments().catch(report); };
for(const button of document.querySelectorAll('[data-tab]')) button.onclick = () => { for(const section of document.querySelectorAll('main>section')) section.hidden = section.id !== button.dataset.tab; for(const b of document.querySelectorAll('[data-tab]')) b.removeAttribute('aria-current'); button.setAttribute('aria-current','page'); if(button.dataset.tab === 'documents') loadDocuments().catch(report); if(button.dataset.tab === 'system') loadSystem().catch(report); };
const examples = ['What caused the March payments incidents?', 'Were Marie Curie and Albert Einstein born in the same country?', 'What will our revenue be in 2040?', 'Which documents disagree about the payments rollback?', 'What were the root cause and follow-up actions in the post-mortem?'];
for(const q of examples) { const b = node('button', q); b.type = 'button'; b.onclick = () => { $('#question').value = q; $('#question').focus(); }; $('#examples').append(b); }
function filters() { const f = {}; const types = [...$('#doc-types').selectedOptions].map(o=>o.value); if(types.length) f.doc_types = types; for(const [id,key] of [['date-from','date_from'],['date-to','date_to']]) if($('#'+id).value) f[key] = $('#'+id).value; const services = $('#services').value.split(',').map(s=>s.trim()).filter(Boolean); if(services.length) f.services = services; return f; }
function markdown() { if(window.marked && window.DOMPurify) $('#answer').innerHTML = window.DOMPurify.sanitize(window.marked.parse(answer)); else $('#answer').textContent = answer; }
async function evidence(citation) {
  openDrawer(node('h2', citation.title),
    node('p', `${citation.doc_id} ? ${citation.source} ? ${citation.created_at || 'Undated'}`),
    node('pre', citation.text || citation.snippet),
    details('Retrieval explanation', citation.explain || {}));
}
function linkCitations() {
  const walker = document.createTreeWalker($('#answer'), NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const text of texts) {
    if (text.parentElement.closest('code,pre,a,button')) continue;
    const pattern = /\[(E\d+)\]/g;
    let last = 0, match;
    const fragment = document.createDocumentFragment();
    while ((match = pattern.exec(text.textContent))) {
      fragment.append(document.createTextNode(text.textContent.slice(last, match.index)));
      const citation = citations.find(c => c.evidence_id === match[1]);
      if (citation) {
        const button = node('button', match[0], 'citation');
        button.setAttribute('aria-label', `Evidence ${match[1]}: ${citation.title}`);
        button.onclick = () => evidence(citation);
        fragment.append(button);
      } else fragment.append(document.createTextNode(match[0]));
      last = pattern.lastIndex;
    }
    if (last) {
      fragment.append(document.createTextNode(text.textContent.slice(last)));
      text.replaceWith(fragment);
    }
  }
}
function renderResult(result) { citations = result.citations; answer = result.answer; markdown(); linkCitations(); $('#citations').replaceChildren(); for(const c of result.citations) { const b = node('button',`[${c.evidence_id}] ${c.title}`); b.onclick=()=>evidence(c); $('#citations').append(b); } const info = $('#result-info'); info.replaceChildren(); if(result.abstained) info.append(node('p','Insufficient evidence to provide a supported answer.','banner')); info.append(node('span',`Confidence: ${result.confidence}`,'badge')); info.append(details('Contradictions',result.contradictions.length ? result.contradictions : ['None detected'])); info.append(details('Missing information',result.missing.length ? result.missing : ['None reported'])); info.append(node('p',`Tokens: ${(result.usage.prompt_tokens||0)+(result.usage.completion_tokens||0)} ? Est. cost: $${Number(result.usage.estimated_cost||0).toFixed(6)} ? Latency: ${Math.round(result.timings_ms.total||0)} ms ? Cached: ${result.cached ? 'yes':'no'}`)); $('#copy').hidden=false; $('#status').textContent='Investigation complete'; }
$('#copy').onclick=()=>navigator.clipboard.writeText(answer).catch(report);
function agentEvent(type,data) { if(type==='answer_delta') { answer += typeof data === 'string' ? data : ''; markdown(); } else if(type==='final') renderResult(data); else if(type==='error') throw Error(data.error || 'Investigation failed'); else { if(type==='evidence') evidenceCount++; $('#activity').append(node('li',`${type}: ${JSON.stringify(data)}`)); $('#status').textContent=`Working: ${type} ? ${evidenceCount} evidence chunks`; } }
$('#investigate-form').onsubmit=async e=>{e.preventDefault(); controller=new AbortController(); answer='';citations=[];evidenceCount=0;$('#answer').replaceChildren();$('#activity').replaceChildren();$('#citations').replaceChildren();$('#result-info').replaceChildren();$('#copy').hidden=true;$('#global-status').textContent='';$('#status').className='';$('#status').textContent='Starting investigation?';$('#cancel').hidden=false; const submit=e.target.querySelector('[type=submit]');submit.disabled=true;try {const r=await fetch('/api/investigate/stream',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({question:$('#question').value,filters:filters(),retrieval:{mode:$('#mode').value,rerank:$('#rerank').checked,mmr:$('#mmr').checked}})});if(!r.ok){const d=await r.json();throw Error(d.error?.message||`Request failed (${r.status})`);}await parseSSE(r.body,agentEvent);}catch(e){if(e.name==='AbortError')$('#status').textContent='Investigation stopped';else report(e);}finally{submit.disabled=false;$('#cancel').hidden=true;}};
$('#cancel').onclick=()=>controller?.abort();
$('#search-form').onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:$('#search-query').value,mode:$('#search-mode').value,rerank:$('#search-rerank').checked})});const table=node('table'),head=node('tr');for(const s of ['Document','Score','Dense rank','Sparse rank','Rerank','Boost'])head.append(node('th',s));table.append(head);for(const c of r.chunks){const row=node('tr');const title=node('td');title.append(details(c.payload.title||c.doc_id,c.text));row.append(title);for(const v of [c.score,c.explain.dense_rank,c.explain.sparse_rank,c.explain.rerank_score,c.explain.boost])row.append(node('td',v??'?'));table.append(row);}$('#search-results').replaceChildren(node('p',`${r.chunks.length} results ? ${Math.round(r.timings_ms.total)} ms`),table);}catch(e){report(e);}};
async function uploads(files){for(const file of files){const status=node('li',`${file.name}: uploading?`);$('#upload-status').append(status);const data=new FormData();data.append('file',file);try{const r=await api('/api/documents',{method:'POST',body:data});status.textContent=`${file.name}: ${r.status}`;}catch(e){status.textContent=`${file.name}: ${e.message}`;status.className='error';}}await loadDocuments();}
$('#upload').onchange=e=>uploads(e.target.files).catch(report);$('#drop').ondragover=e=>e.preventDefault();$('#drop').ondrop=e=>{e.preventDefault();uploads(e.dataTransfer.files).catch(report);};
async function documentDetail(doc){const id=encodeURIComponent(doc.doc_id);const [d,chunks]=await Promise.all([api(`/api/documents/${id}`),api(`/api/documents/${id}/chunks`)]);const replace=node('input');replace.type='file';replace.disabled=doc.origin==='seed'&&!admin();replace.setAttribute('aria-label','Replace document');replace.onchange=async()=>{if(!replace.files.length)return;const data=new FormData();data.append('file',replace.files[0]);try{await api(`/api/documents/${id}`,{method:'PUT',headers:{'X-Admin-Token':admin()},body:data});await loadDocuments();await documentDetail(doc);}catch(e){report(e);}};const del=node('button','Delete document');del.disabled=replace.disabled;del.onclick=async()=>{if(!confirm(`Delete ${doc.title}?`))return;try{await api(`/api/documents/${id}`,{method:'DELETE',headers:{'X-Admin-Token':admin()}});$('#drawer').close();await loadDocuments();}catch(e){report(e);}};openDrawer(node('h2',doc.title),details('Metadata and entities',d.metadata),details('Versions',d.versions),...chunks.map(c=>details(`Chunk ${c.index}`,c)),node('label','Replace file'),replace,del);}
async function loadDocuments(){const params=new URLSearchParams({offset,limit:20,q:$('#document-query').value,doc_type:$('#document-type').value,origin:$('#document-origin').value});const r=await api('/api/documents?'+params);total=r.total;$('#document-list').replaceChildren();for(const d of r.items){const b=node('button',`${d.origin==='seed'&&!admin()?'?? ':''}${d.title} ? ${d.doc_type} ? v${d.version}`);b.onclick=()=>documentDetail(d).catch(report);const row=node('p');row.append(b);$('#document-list').append(row);}$('#page').textContent=`${total?offset+1:0}?${Math.min(offset+20,total)} of ${total}`;$('#previous').disabled=offset===0;$('#next').disabled=offset+20>=total;}
$('#document-filter').onsubmit=e=>{e.preventDefault();offset=0;loadDocuments().catch(report);};$('#previous').onclick=()=>{offset=Math.max(0,offset-20);loadDocuments().catch(report);};$('#next').onclick=()=>{offset+=20;loadDocuments().catch(report);};
async function loadSystem(){const [stats,traces]=await Promise.all([api('/api/stats'),api('/api/traces')]);$('#stats').replaceChildren(jsonView(stats));$('#traces').replaceChildren(...traces.map(t=>details(`${t.created_at} ? ${t.question}`,t)));}$('#refresh').onclick=()=>loadSystem().catch(report);
