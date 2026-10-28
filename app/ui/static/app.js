import { parseSSE } from "/static/sse.js";

const $ = selector => document.querySelector(selector);
const PAGE_SIZE = 20;
const EXAMPLES = [
  'What caused the March payments incidents?',
  'Which documents disagree about the payments rollback?',
  'Were Marie Curie and Albert Einstein born in the same country?',
  'What were the root cause and follow-up actions in the post-mortem?',
  'What will our revenue be in 2040?',
];
const TOOL_LABELS = {
  search_documents: 'Searched documents',
  get_document: 'Opened document',
  find_related: 'Followed related documents',
  timeline: 'Built a timeline',
};

let answer = '', citations = [], evidenceCount = 0, controller;
let offset = 0;

// Helpers

function node(tag, content, className) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  for (const child of [content].flat()) {
    if (child === undefined || child === null || child === false) continue;
    element.append(child instanceof Node ? child : String(child));
  }
  return element;
}

function button(label, className, onclick) {
  const element = node('button', label, className);
  element.type = 'button';
  if (onclick) element.onclick = onclick;
  return element;
}

const admin = () => sessionStorage.getItem('adminToken') || '';
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
const ms = value => value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value || 0)} ms`;

function shorten(text, length) {
  text = String(text ?? '');
  return text.length > length ? text.slice(0, length - 3) + '...' : text;
}

function number(value) {
  if (typeof value !== 'number') return value;
  return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(3);
}

function when(value) {
  if (!value) return 'Undated';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const hasTime = String(value).length > 10 && !/T00:00:00/.test(value);
  return date.toLocaleString(undefined, hasTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' });
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail : '';
    throw Error(data.error?.message || detail || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

let toastTimer;
function report(error) {
  const toast = $('#global-status');
  toast.textContent = error.message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
}
$('#global-status').onclick = () => { $('#global-status').hidden = true; };

function keyValues(entries) {
  const list = node('dl', null, 'kv');
  for (const [key, value] of entries) {
    if (value === undefined || value === null || value === '') continue;
    list.append(node('dt', key), node('dd', typeof value === 'object' ? JSON.stringify(value) : String(value)));
  }
  return list;
}

function fold(title, ...children) {
  const element = node('details', node('summary', title), 'fold');
  element.append(...children);
  return element;
}

function table(headers, rows) {
  return node('table', [
    node('thead', node('tr', headers.map(h => node('th', h)))),
    node('tbody', rows.map(cells => node('tr', cells.map(c => node('td', c))))),
  ], 'table');
}

function clickableRow(cells, onclick) {
  const row = node('tr', cells, 'clickable');
  row.tabIndex = 0;
  row.onclick = onclick;
  row.onkeydown = event => { if (event.key === 'Enter') onclick(); };
  return row;
}

function fillTable(body, rows, emptyText, columns) {
  if (rows.length) return body.replaceChildren(...rows);
  const cell = node('td', emptyText, 'empty');
  cell.colSpan = columns;
  body.replaceChildren(node('tr', cell));
}

function openDrawer(...children) {
  $('#drawer-content').replaceChildren(...children);
  if (!$('#drawer').open) $('#drawer').showModal();
  $('#drawer').scrollTop = 0;
}
$('#close-drawer').onclick = () => $('#drawer').close();
$('#drawer').onclick = event => { if (event.target === $('#drawer')) $('#drawer').close(); };

// Tabs and settings

function showTab(name) {
  for (const section of document.querySelectorAll('main > section')) section.hidden = section.id !== name;
  for (const tab of document.querySelectorAll('[data-tab]')) {
    if (tab.dataset.tab === name) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  }
  if (name === 'documents') loadDocuments().catch(report);
  if (name === 'system') loadSystem().catch(report);
}
for (const tab of document.querySelectorAll('[data-tab]')) tab.onclick = () => showTab(tab.dataset.tab);

$('#settings').onclick = () => {
  $('#admin-token').value = admin();
  $('#settings-dialog').showModal();
};
$('#save-settings').onclick = () => {
  sessionStorage.setItem('adminToken', $('#admin-token').value);
  loadDocuments().catch(report);
};

// Date picker. The hidden input keeps the YYYY-MM-DD value that filters() sends.

const pad = value => String(value).padStart(2, '0');
const toIso = date => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
const pickers = [];

function fromIso(value) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function datePicker(root) {
  const input = root.querySelector('input');
  const labelId = root.closest('.field').querySelector('.field-label').id;
  const text = node('span', 'Any date');
  text.id = `${input.id}-value`;
  const trigger = button(text, 'date-trigger');
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.setAttribute('aria-labelledby', `${labelId} ${text.id}`);
  const calendar = node('div', null, 'calendar');
  calendar.hidden = true;
  calendar.setAttribute('role', 'dialog');
  calendar.setAttribute('aria-labelledby', labelId);
  root.append(trigger, calendar);
  let view = new Date();

  function set(value) {
    input.value = value;
    text.textContent = value
      ? fromIso(value).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
      : 'Any date';
    trigger.classList.toggle('empty', !value);
    for (const other of pickers) other.render();
  }

  function dayButton(date, month, today) {
    const value = toIso(date);
    const from = $('#date-from').value, to = $('#date-to').value;
    const day = button(date.getDate(), 'day', () => { set(value); close(); });
    day.dataset.date = value;
    day.tabIndex = -1;
    day.setAttribute('aria-label', date.toLocaleDateString(undefined, { dateStyle: 'full' }));
    day.classList.toggle('outside', date.getMonth() !== month);
    day.classList.toggle('today', value === today);
    day.classList.toggle('selected', value === input.value);
    day.classList.toggle('in-range', Boolean(from && to && value >= from && value <= to));
    day.classList.toggle('range-start', value === from);
    day.classList.toggle('range-end', value === to);
    return day;
  }

  function render(focus) {
    if (calendar.hidden) return;
    const year = view.getFullYear(), month = view.getMonth();
    const today = toIso(new Date());
    const leading = (new Date(year, month, 1).getDay() + 6) % 7;
    const days = [];
    for (let i = 0; i < 42; i++) days.push(dayButton(new Date(year, month, 1 - leading + i), month, today));

    const inMonth = days.filter(day => !day.classList.contains('outside'));
    const target = days.find(day => day.dataset.date === focus)
      || inMonth.find(day => day.classList.contains('selected'))
      || inMonth.find(day => day.classList.contains('today'))
      || inMonth[0];
    target.tabIndex = 0;

    const move = step => () => { view = new Date(year, month + step, 1); render(); };
    const previous = button(null, 'nav prev', move(-1));
    previous.setAttribute('aria-label', 'Previous month');
    const next = button(null, 'nav next', move(1));
    next.setAttribute('aria-label', 'Next month');
    const title = new Date(year, month, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

    calendar.replaceChildren(
      node('div', [node('strong', title), node('div', [previous, next])], 'calendar-head'),
      node('div', WEEKDAYS.map(day => node('span', day)), 'weekdays'),
      node('div', days, 'days'),
      node('div', [
        button('Clear', 'link', () => { set(''); close(); }),
        button('Today', 'link', () => { set(today); close(); }),
      ], 'calendar-foot'),
    );
    if (focus) target.focus();
  }

  function open() {
    for (const other of pickers) if (other !== picker) other.close(false);
    view = input.value ? fromIso(input.value) : new Date();
    calendar.hidden = false;
    // Open towards the left when there is no room on the right (narrow screens).
    calendar.classList.toggle('align-end', trigger.getBoundingClientRect().left + 312 > window.innerWidth);
    trigger.setAttribute('aria-expanded', 'true');
    render(input.value || toIso(new Date()));
  }

  function close(refocus = true) {
    if (calendar.hidden) return;
    calendar.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    if (refocus) trigger.focus();
  }

  const steps = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
  calendar.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    const current = event.target.dataset?.date;
    if (!current || !(event.key in steps)) return;
    event.preventDefault();
    const date = fromIso(current);
    date.setDate(date.getDate() + steps[event.key]);
    view = new Date(date.getFullYear(), date.getMonth(), 1);
    render(toIso(date));
  });
  trigger.onclick = () => calendar.hidden ? open() : close();
  document.addEventListener('pointerdown', event => { if (!root.contains(event.target)) close(false); });

  const picker = { render: () => render(), close };
  pickers.push(picker);
  set('');
}
for (const root of document.querySelectorAll('.datepicker')) datePicker(root);

// Investigate

for (const question of EXAMPLES) {
  $('#examples').append(node('li', button(question, null, () => {
    $('#question').value = question;
    $('#question').focus();
  })));
}
$('#question').addEventListener('keydown', event => {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) $('#investigate-form').requestSubmit();
});

function filters() {
  const result = {};
  const types = [...document.querySelectorAll('#doc-types :checked')].map(input => input.value);
  if (types.length) result.doc_types = types;
  if ($('#date-from').value) result.date_from = $('#date-from').value;
  if ($('#date-to').value) result.date_to = $('#date-to').value;
  const services = $('#services').value.split(',').map(s => s.trim()).filter(Boolean);
  if (services.length) result.services = services;
  return result;
}

function setStatus(text, state = '') {
  $('#status').textContent = text;
  $('#status').className = state;
}

function renderAnswer() {
  if (window.marked && window.DOMPurify) $('#answer').innerHTML = window.DOMPurify.sanitize(window.marked.parse(answer));
  else $('#answer').textContent = answer;
  linkCitations($('#answer'));
}

function citationButton(id) {
  const citation = citations.find(c => c.evidence_id === id);
  if (!citation) return null;
  const chip = button(id, 'citation', () => showEvidence(citation));
  chip.title = citation.title;
  chip.setAttribute('aria-label', `Evidence ${id}: ${citation.title}`);
  return chip;
}

function linkCitations(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const text of texts) {
    if (text.parentElement.closest('code,pre,a,button')) continue;
    const pattern = /\[(E\d+)\]/g;
    let last = 0, match;
    const fragment = document.createDocumentFragment();
    while ((match = pattern.exec(text.textContent))) {
      fragment.append(text.textContent.slice(last, match.index));
      fragment.append(citationButton(match[1]) || match[0]);
      last = pattern.lastIndex;
    }
    if (last) {
      fragment.append(text.textContent.slice(last));
      text.replaceWith(fragment);
    }
  }
}

function explanation(explain = {}) {
  const parts = [
    ['Dense rank', explain.dense_rank],
    ['Keyword rank', explain.sparse_rank],
    ['RRF', explain.rrf_score],
    ['Rerank', explain.rerank_score],
    ['Boost', explain.boost !== 1 ? explain.boost : null],
  ].filter(([, value]) => value !== null && value !== undefined);
  if (!parts.length) return null;
  return node('div', parts.map(([label, value]) => node('span', [`${label} `, node('b', number(value))])), 'explain');
}

function showEvidence(citation) {
  const why = explanation(citation.explain);
  openDrawer(
    node('span', citation.evidence_id, 'citation'),
    node('h2', citation.title || citation.doc_id),
    keyValues([['Document', citation.doc_id], ['Source', citation.source], ['Date', when(citation.created_at)]]),
    node('div', citation.text || citation.snippet, 'excerpt'),
    why && fold('Why this was retrieved', why),
  );
}

function addActivity(step, detail) {
  if (typeof detail === 'string') detail = node('span', detail, 'detail');
  $('#activity').append(node('li', [node('span', step, 'step'), detail]));
  $('#activity-count').textContent = `(${$('#activity').children.length})`;
}

function describeArguments(args = {}) {
  if (typeof args === 'string') return args;
  return args.query || args.doc_id || args.entity || Object.values(args).filter(v => typeof v === 'string').join(', ');
}

function agentEvent(type, data) {
  if (type === 'answer_delta') {
    answer += typeof data === 'string' ? data : '';
    renderAnswer();
    setStatus('Writing the answer', 'busy');
  } else if (type === 'final') {
    renderResult(data);
  } else if (type === 'error') {
    throw Error(data?.error || 'Investigation failed');
  } else if (type === 'plan') {
    const steps = data.sub_questions || [];
    const title = data.complexity === 'multi_hop' ? 'Planned a multi-step investigation' : 'Planned a direct lookup';
    addActivity(title, steps.length ? node('ul', steps.map(s => node('li', s))) : null);
    setStatus('Planning', 'busy');
  } else if (type === 'tool_call') {
    const label = TOOL_LABELS[data.name] || data.name;
    addActivity(label, describeArguments(data.arguments));
    setStatus(label, 'busy');
  } else if (type === 'evidence') {
    evidenceCount++;
    setStatus(`Collected ${plural(evidenceCount, 'evidence chunk')}`, 'busy');
  } else if (type === 'verification') {
    const removed = data.removed_citations?.length || 0;
    const unsupported = data.unsupported_sentences?.length || 0;
    const summary = removed || unsupported
      ? `${plural(unsupported, 'unsupported sentence')}, ${plural(removed, 'citation')} removed`
      : 'All cited claims checked';
    addActivity('Verified claims against the evidence', summary);
    setStatus('Verifying claims', 'busy');
  }
}

function callout(title, body, kind) {
  return node('div', [node('h3', title), body], `callout ${kind}`);
}

function sourceCard(citation) {
  const meta = citation.created_at ? `${citation.source}, ${when(citation.created_at)}` : citation.source;
  return node('li', button([
    node('span', citation.evidence_id, 'tag'),
    node('strong', citation.title || citation.doc_id),
    node('small', meta),
    node('span', citation.snippet, 'snippet'),
  ], 'source', () => showEvidence(citation)));
}

function renderResult(result) {
  if (evidenceCount) addActivity(`Collected ${plural(evidenceCount, 'evidence chunk')}`);
  citations = result.citations || [];
  answer = result.answer || '';
  renderAnswer();

  const confidence = result.confidence || 'low';
  const badges = [node('span', `${confidence} confidence`, `badge ${confidence}`)];
  if (result.abstained) badges.push(node('span', 'Abstained', 'badge warn'));
  if (result.contradictions?.length) badges.push(node('span', plural(result.contradictions.length, 'conflict'), 'badge bad'));
  if (result.cached) badges.push(node('span', 'Cached', 'badge'));
  $('#badges').replaceChildren(...badges);

  const info = [];
  if (result.abstained) {
    info.push(callout('Not enough evidence',
      node('p', 'The engine could not find support for a confident answer and declined to guess.'), 'warn'));
  }
  if (result.contradictions?.length) {
    info.push(callout('Sources disagree', node('ul', result.contradictions.map(c => node('li', [
      c.description, ' ',
      ...(c.evidence || []).map(id => citationButton(id) || `[${id}]`),
      c.resolution && node('span', c.resolution, 'resolution'),
    ]))), 'bad'));
  }
  if (result.missing?.length) {
    info.push(callout('Missing information', node('ul', result.missing.map(m => node('li', m))), 'info'));
  }
  const usage = result.usage || {};
  const tokens = (usage.prompt_tokens || 0) + (usage.completion_tokens || 0);
  info.push(node('p', [
    node('span', ms(result.timings_ms?.total)),
    node('span', `${tokens.toLocaleString()} tokens`),
    node('span', `$${Number(usage.estimated_cost || 0).toFixed(4)} estimated cost`),
    node('span', plural(citations.length, 'source')),
  ], 'meta-line'));
  $('#result-info').replaceChildren(...info);

  const sources = citations.length ? citations.map(sourceCard) : [node('li', 'No sources were cited.', 'empty')];
  $('#citations').replaceChildren(...sources);
  setStatus(result.error || 'Investigation complete', result.error ? 'error' : '');
}

$('#investigate-form').onsubmit = async event => {
  event.preventDefault();
  controller = new AbortController();
  answer = '';
  citations = [];
  evidenceCount = 0;
  $('#run').hidden = false;
  for (const id of ['#answer', '#activity', '#result-info', '#badges']) $(id).replaceChildren();
  $('#citations').replaceChildren(node('li', 'Sources appear once the answer is ready.', 'empty'));
  $('#activity-count').textContent = '';
  setStatus('Starting investigation', 'busy');
  $('#cancel').hidden = false;
  const submit = event.target.querySelector('[type=submit]');
  submit.disabled = true;
  try {
    const response = await fetch('/api/investigate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        question: $('#question').value,
        filters: filters(),
        retrieval: { mode: $('#mode').value, rerank: $('#rerank').checked, mmr: $('#mmr').checked },
      }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw Error(data.error?.message || `Request failed (${response.status})`);
    }
    await parseSSE(response.body, agentEvent);
  } catch (error) {
    if (error.name === 'AbortError') {
      setStatus('Investigation stopped');
    } else {
      setStatus(error.message, 'error');
      report(error);
    }
  } finally {
    submit.disabled = false;
    $('#cancel').hidden = true;
  }
};
$('#cancel').onclick = () => controller?.abort();

// Search

function searchResult(chunk, index) {
  const card = node('article', [
    node('div', [
      node('strong', `${index + 1}. ${chunk.payload.title || chunk.doc_id}`),
      node('span', number(chunk.score), 'score'),
    ], 'result-head'),
    node('p', chunk.text),
    explanation(chunk.explain),
  ], 'result');
  card.onclick = () => card.classList.toggle('open');
  return card;
}

$('#search-form').onsubmit = async event => {
  event.preventDefault();
  try {
    const result = await api('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: $('#search-query').value,
        mode: $('#search-mode').value,
        rerank: $('#search-rerank').checked,
      }),
    });
    const cards = result.chunks.map(searchResult);
    $('#search-results').replaceChildren(
      node('p', `${plural(result.chunks.length, 'result')} in ${ms(result.timings_ms.total)}`, 'summary-line'),
      ...(cards.length ? cards : [node('p', 'Nothing matched this query.', 'muted')]),
    );
  } catch (error) {
    report(error);
  }
};

// Documents

async function uploads(files) {
  for (const file of files) {
    const status = node('li', [node('span', file.name), node('span', 'Uploading')]);
    $('#upload-status').append(status);
    const data = new FormData();
    data.append('file', file);
    try {
      const result = await api('/api/documents', { method: 'POST', body: data });
      status.lastChild.textContent = `${result.status.replace('_', ' ')}, ${plural(result.chunk_count, 'chunk')}`;
    } catch (error) {
      status.lastChild.textContent = error.message;
      status.className = 'error';
    }
  }
  await loadDocuments();
}
$('#upload').onchange = event => uploads(event.target.files).catch(report);
$('#drop').ondragover = event => {
  event.preventDefault();
  $('#drop').classList.add('over');
};
$('#drop').ondragleave = () => $('#drop').classList.remove('over');
$('#drop').ondrop = event => {
  event.preventDefault();
  $('#drop').classList.remove('over');
  uploads(event.dataTransfer.files).catch(report);
};

function chunkView(chunk) {
  const section = [chunk.section_path || []].flat().join(' / ');
  const meta = [`#${chunk.index}`, section, `${chunk.token_count ?? '?'} tokens`].filter(Boolean).join(', ');
  return node('div', [node('small', meta, 'muted'), node('div', chunk.text, 'excerpt')]);
}

async function documentDetail(doc) {
  const id = encodeURIComponent(doc.doc_id);
  const [detail, chunks] = await Promise.all([api(`/api/documents/${id}`), api(`/api/documents/${id}/chunks`)]);
  const locked = doc.origin === 'seed' && !admin();

  const replace = node('input');
  replace.type = 'file';
  replace.disabled = locked;
  replace.setAttribute('aria-label', 'Replace document');
  replace.onchange = async () => {
    if (!replace.files.length) return;
    const data = new FormData();
    data.append('file', replace.files[0]);
    try {
      await api(`/api/documents/${id}`, { method: 'PUT', headers: { 'X-Admin-Token': admin() }, body: data });
      await loadDocuments();
      await documentDetail(doc);
    } catch (error) {
      report(error);
    }
  };
  const remove = button('Delete', 'danger', async () => {
    if (!confirm(`Delete "${doc.title}"?`)) return;
    try {
      await api(`/api/documents/${id}`, { method: 'DELETE', headers: { 'X-Admin-Token': admin() } });
      $('#drawer').close();
      await loadDocuments();
    } catch (error) {
      report(error);
    }
  });
  remove.disabled = locked;

  const entities = Object.entries(detail.entities || {}).filter(([, values]) => values?.length);
  const versions = detail.versions || [];

  openDrawer(
    node('h2', doc.title || doc.doc_id),
    keyValues([
      ['ID', doc.doc_id],
      ['Type', doc.doc_type],
      ['Format', doc.format],
      ['Source', doc.source],
      ['Date', doc.created_at && when(doc.created_at)],
      ['Origin', doc.origin],
      ['Version', `v${doc.version}`],
      ['Chunks', `${doc.chunk_count} (${doc.chunk_strategy})`],
      ['Duplicate of', doc.duplicate_of],
      ['Ingested', when(doc.ingested_at)],
    ]),
    entities.length ? fold('Entities', keyValues(entities.map(([key, values]) => [key, values.join(', ')]))) : null,
    versions.length ? fold(`Versions (${versions.length})`, table(['Version', 'Status', 'Updated'],
      versions.map(v => [`v${v.version}`, v.status ?? '', when(v.updated_at || v.ingested_at)]))) : null,
    fold(`Chunks (${chunks.length})`, ...chunks.map(chunkView)),
    node('div', [
      locked && node('small', 'Seed document: add the admin token to modify it.', 'muted'),
      node('label', ['Replace file', replace]),
      remove,
    ], 'danger-zone'),
  );
}

async function loadDocuments() {
  const params = new URLSearchParams({
    offset,
    limit: PAGE_SIZE,
    q: $('#document-query').value,
    doc_type: $('#document-type').value,
    origin: $('#document-origin').value,
  });
  const result = await api('/api/documents?' + params);
  const rows = result.items.map(doc => clickableRow([
    node('td', [doc.title || doc.doc_id, node('span', doc.source, 'sub')]),
    node('td', doc.doc_type),
    node('td', [doc.origin, doc.origin === 'seed' && !admin() && node('span', ' (locked)', 'lock')]),
    node('td', `v${doc.version}`, 'num'),
    node('td', doc.chunk_count, 'num'),
  ], () => documentDetail(doc).catch(report)));
  fillTable($('#document-list'), rows, 'No documents found.', 5);
  const first = result.total ? offset + 1 : 0;
  const last = Math.min(offset + PAGE_SIZE, result.total);
  $('#page').textContent = `${first}-${last} of ${result.total.toLocaleString()}`;
  $('#previous').disabled = offset === 0;
  $('#next').disabled = offset + PAGE_SIZE >= result.total;
}
$('#document-filter').onsubmit = event => {
  event.preventDefault();
  offset = 0;
  loadDocuments().catch(report);
};
$('#previous').onclick = () => {
  offset = Math.max(0, offset - PAGE_SIZE);
  loadDocuments().catch(report);
};
$('#next').onclick = () => {
  offset += PAGE_SIZE;
  loadDocuments().catch(report);
};

// System

function tile(label, value, { hint, text = false } = {}) {
  return node('div', [node('small', label), node('b', value, text ? 'text' : null), hint && node('span', hint)], 'tile');
}

function breakdown(title, heading, counts) {
  const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
  const rows = table([heading, 'Documents'], entries.map(([key, count]) => [key, count.toLocaleString()]));
  for (const cell of rows.querySelectorAll('tr > :last-child')) cell.className = 'num';
  return node('div', [node('h3', title), rows], 'card scroll');
}

function showTrace(trace) {
  const usage = trace.usage || {};
  openDrawer(
    node('h2', trace.question),
    keyValues([
      ['When', when(trace.created_at)],
      ['Outcome', trace.error ? 'Error' : trace.abstained ? 'Abstained' : 'Answered'],
      ['Citations', trace.citations_count],
      ['Contradictions', trace.contradictions_count],
      ['Tokens', (usage.prompt_tokens || 0) + (usage.completion_tokens || 0)],
      ...Object.entries(trace.timings || {}).map(([stage, value]) => [`${stage} time`, ms(value)]),
      ['Error', trace.error],
    ]),
    trace.answer_excerpt ? node('div', trace.answer_excerpt, 'excerpt') : null,
    fold('Raw trace', node('pre', JSON.stringify(trace.trace, null, 2))),
  );
}

function traceRow(trace) {
  const [outcome, kind] = trace.error ? ['Error', 'bad'] : trace.abstained ? ['Abstained', 'warn'] : ['Answered', 'ok'];
  return clickableRow([
    node('td', shorten(trace.question, 90)),
    node('td', node('span', outcome, `badge ${kind}`)),
    node('td', trace.citations_count, 'num'),
    node('td', ms(trace.timings?.total), 'num'),
    node('td', when(trace.created_at)),
  ], () => showTrace(trace));
}

async function loadSystem() {
  const [stats, traces] = await Promise.all([api('/api/stats'), api('/api/traces')]);
  const cache = stats.cache || {};
  const cacheHits = (cache.answer_hits || 0) + (cache.llm_hits || 0);
  $('#stats').replaceChildren(
    node('div', [
      tile('Documents', stats.documents.total.toLocaleString()),
      tile('Chunks', stats.chunks.toLocaleString(), { hint: `collection: ${stats.collection}` }),
      tile('Embedding model', stats.embedding_model.split('/').pop(), { text: true, hint: `chunking: ${stats.chunk_strategy}` }),
      tile('LLM providers', stats.llm_providers.join(', ') || 'none configured', { text: true, hint: 'in fallback order' }),
      tile('Cache hits', cacheHits.toLocaleString(), { hint: `${cache.answer_entries || 0} answers, ${cache.llm_entries || 0} LLM responses cached` }),
    ], 'card tiles'),
    node('div', [
      breakdown('By document type', 'Type', stats.documents.by_doc_type),
      breakdown('By dataset', 'Dataset', stats.documents.by_dataset),
    ], 'breakdowns'),
  );
  fillTable($('#traces'), traces.map(traceRow), 'No investigations yet.', 5);
}
$('#refresh').onclick = () => loadSystem().catch(report);
