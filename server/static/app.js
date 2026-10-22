'use strict';
const $ = s => document.querySelector(s);
let files = [], status = {}, filter = 'all', view = 'files', refreshTimer;
const sizes = n => n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : n < 1073741824 ? (n / 1048576).toFixed(1) + ' MB' : (n / 1073741824).toFixed(2) + ' GB';
function notify(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => $('#toast').hidden = true, 6500); }
function lock() { clearInterval(refreshTimer); $('#app').hidden = true; $('#login-screen').hidden = false; files = []; $('#file-rows').replaceChildren(); $('#session-list').replaceChildren(); }
async function api(path, options = {}) {
 const response = await fetch('/api' + path, { ...options, credentials: 'same-origin', headers: { 'X-AwanVault': '1', ...options.headers } });
 if (response.status === 401) { lock(); }
 if (!response.ok) { let message = 'Request failed (' + response.status + ')'; try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; } catch {} throw new Error(message); }
 return response.json();
}
function post(path, data = {}) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }); }
function showView(next) { view = next; document.querySelectorAll('.view').forEach(el => el.hidden = el.id !== 'view-' + next); document.querySelectorAll('nav button').forEach(el => el.classList.toggle('active', el.dataset.view === next)); $('#page-label').textContent = ({files:'MY FILES',sync:'SYNC & CONNECTIONS',recovery:'RECOVERY',security:'SECURITY'})[next]; if (next === 'security') sessions().catch(e => notify(e.message)); }
function node(tag, text, cls) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; }
function render() {
 $('#stat-files').textContent = files.length; $('#stat-size').textContent = sizes(files.reduce((a, f) => a + f.size, 0)); $('#stat-mirrored').textContent = status.counts?.mirrored || 0;
 $('#stat-recovery').textContent = status.recovery_online ? 'Available' : 'Offline';
 const detail = [(status.telegram_linked ? 'Account linked' : 'Not linked — run link-telegram on your server'), status.telegram_paused ? 'Uploads paused' : 'Uploads enabled', status.telegram_blocked || status.telegram_status];
 if (status.telegram_wait_until > Date.now() / 1000) detail.push('Waiting until ' + new Date(status.telegram_wait_until * 1000).toLocaleString());
 $('#telegram-detail').textContent = detail.join('\n'); $('#pause-telegram').textContent = status.telegram_paused ? 'Resume Telegram uploads' : 'Pause Telegram uploads'; $('#pause-telegram').disabled = !status.telegram_linked || !!status.telegram_blocked;
 const query = $('#search').value.toLocaleLowerCase();
 const selected = files.filter(f => (filter === 'all' || (filter === 'photos' ? f.media_type.startsWith('image/') : !f.media_type.startsWith('image/'))) && (f.name + ' ' + f.source).toLocaleLowerCase().includes(query));
 const tbody = $('#file-rows'); tbody.replaceChildren();
 for (const f of selected) {
  const tr = node('tr'), first = node('td'), wrap = node('div', undefined, 'filename'), text = node('div');
  wrap.append(node('span', f.media_type.startsWith('image/') ? '▧' : '▤', 'file-icon')); text.append(node('strong', f.name), node('small', f.source)); wrap.append(text); first.append(wrap); tr.append(first, node('td', sizes(f.size)), node('td', new Date(f.created * 1000).toLocaleDateString()));
  const state = node('td'); state.append(node('span', ({mirrored:'Uploaded',queued:'Queued',attention:'Needs attention'})[f.state] || f.state, 'pill' + (f.state === 'mirrored' ? '' : ' pending'))); tr.append(state);
  const actionCell = node('td'), actions = node('div', undefined, 'row-actions'), download = node('a', 'Download ↓'); download.href = '/api/files/' + encodeURIComponent(f.id) + '/download'; download.setAttribute('download', f.name); actions.append(download);
  if (f.state === 'mirrored') { const restore = node('button', 'Restore'); restore.title = 'Restore server and recovery copies from Telegram'; restore.onclick = async () => { restore.disabled = true; try { await post('/files/' + f.id + '/restore'); notify('Verified Telegram copy restored. You can download it now.'); } catch(e) { notify(e.message); } finally { restore.disabled = false; } }; actions.append(restore); }
  actionCell.append(actions); tr.append(actionCell); tbody.append(tr);
 }
 $('#empty').hidden = selected.length !== 0; $('#file-count').textContent = selected.length + ' items';
}
async function refresh() { [files, status] = await Promise.all([api('/files'), api('/status')]); render(); }
async function unlock() { await refresh(); $('#login-screen').hidden = true; $('#app').hidden = false; clearInterval(refreshTimer); refreshTimer = setInterval(() => refresh().catch(e => notify(e.message)), 30000); }
async function sessions() {
 const items = await api('/sessions'), target = $('#session-list'); target.replaceChildren();
 for (const item of items) { const row = node('div', undefined, 'session'), info = node('div'); info.append(node('strong', (item.kind === 'device' ? 'Android companion' : 'Browser') + (item.current ? ' · This session' : '')), node('small', 'Expires ' + new Date(item.expires * 1000).toLocaleString())); const revoke = node('button', 'Revoke'); revoke.onclick = async () => { try { await api('/sessions/' + item.id, {method:'DELETE'}); if (item.current) lock(); else await sessions(); } catch(e) { notify(e.message); } }; row.append(info, revoke); target.append(row); }
}
$('#login-form').onsubmit = async event => { event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true; $('#login-error').textContent = ''; try { await post('/auth/login', Object.fromEntries(new FormData(form))); form.reset(); await unlock(); } catch(e) { $('#login-error').textContent = e.message; } finally { button.disabled = false; } };
document.querySelectorAll('[data-view]').forEach(el => el.onclick = () => showView(el.dataset.view)); document.querySelectorAll('[data-go]').forEach(el => el.onclick = () => showView(el.dataset.go));
document.querySelectorAll('[data-filter]').forEach(el => el.onclick = () => { filter = el.dataset.filter; document.querySelectorAll('[data-filter]').forEach(b => b.classList.toggle('selected', b === el)); render(); }); $('#search').oninput = render;
$('#logout').onclick = async () => { try { await post('/auth/logout'); lock(); } catch(e) { notify(e.message); } };
$('#pause-telegram').onclick = async () => { try { await post('/telegram/pause', {paused: !status.telegram_paused}); await refresh(); } catch(e) { notify(e.message); } };
$('#retry').onclick = async () => { try { await post('/telegram/retry'); await refresh(); notify('Files needing attention returned to the queue.'); } catch(e) { notify(e.message); } };
$('#refresh-recovery').onclick = async () => { try { await refresh(); notify(status.recovery_online ? 'Recovery target is reachable. Test an offline restore to verify recoverability.' : 'Recovery target is offline. New backups will not be accepted.'); } catch(e) { notify(e.message); } };
$('#file-picker').onchange = async event => {
 const picker = event.target, selected = Array.from(picker.files); picker.disabled = true; let done = 0;
 try { for (const file of selected) { if (file.size > 64 * 1024 * 1024) throw new Error(file.name + ' exceeds the 64 MiB first-version limit.'); notify('Backing up ' + file.name + '… (' + (done + 1) + '/' + selected.length + ')'); const meta = JSON.stringify({name: file.name, source: 'Browser', media_type: file.type || 'application/octet-stream'}); const encoded = btoa(Array.from(new TextEncoder().encode(meta), b => String.fromCharCode(b)).join('')); await api('/files', {method:'PUT', headers:{'Content-Type':'application/octet-stream','X-File-Metadata': encoded}, body:file}); done++; } notify(done + ' files backed up with verified recovery copies.'); }
 catch(e) { notify(done + ' completed. ' + e.message); }
 finally { picker.value = ''; picker.disabled = false; await refresh().catch(e => notify(e.message)); }
};
unlock().catch(() => lock());
