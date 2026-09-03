const api = '';
const ACTIVE_STATUSES = new Set(['understanding_requirement', 'reviewing_requirement', 'generating_draft_cases', 'generating_final_cases', 'generating_automation']);
const state = {requirements: [], cases: [], runs: [], selectedDocument: null, selectedWorkflow: null, selectedRun: null, poll: null};
const labels = {
  overview: ['流程总览', '从需求文档到执行报告的完整状态'],
  requirements: ['需求文档', '上传需求原文并查看 AI 分析进度'],
  review: ['用例与评审', '回答评审问题并检查初版用例'],
  execute: ['执行中心', '配置本地环境并单个或批量运行已批准用例'],
  reports: ['测试报告', '用业务语言查看结果，并获得开发排查线索']
};

const el = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', {hour12: false}) : '-';
const formatDuration = ms => ms == null ? '' : `${Math.max(0, Math.round(ms / 1000))}s`;
const formatSize = bytes => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
const statusText = value => ({approved: '已批准', draft: '草稿', queued: '排队中', running: '执行中', passed: '通过', failed: '失败'})[value] || value || '-';

function showToast(message, error = false) {
  el('toast').textContent = message;
  el('toast').style.background = error ? '#9e2727' : '#17202a';
  el('toast').classList.add('show');
  setTimeout(() => el('toast').classList.remove('show'), 3000);
}

async function request(path, options) {
  if (options?.headers?.['X-Filename']) options.headers['X-Filename'] = encodeURIComponent(options.headers['X-Filename']);
  const response = await fetch(api + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`);
  return data;
}

function showView(name) {
  document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.id === `view-${name}`));
  document.querySelectorAll('.nav button').forEach(node => node.classList.toggle('active', node.dataset.view === name));
  el('pageTitle').textContent = labels[name][0];
  el('pageDesc').textContent = labels[name][1];
  if (name === 'reports') loadRuns();
}

function statusBadge(item) {
  const active = ACTIVE_STATUSES.has(item.status);
  const duration = active ? `（${formatDuration(item.current_stage_duration_ms)}）` : '';
  return `<span class="badge ${active ? 'running' : esc(item.status)}">${esc(item.status_label || statusText(item.status))}${duration}</span>`;
}

async function refreshAll() {
  try {
    const [summary, requirements, cases, runs] = await Promise.all([request('/summary'), request('/requirements'), request('/cases'), request('/runs')]);
    state.requirements = requirements.requirements;
    state.cases = cases.cases;
    state.runs = runs.runs;
    el('apiDot').classList.add('online'); el('apiText').textContent = '后端服务正常';
    el('statRequirements').textContent = summary.requirements.total;
    el('statCases').textContent = summary.cases.total;
    el('statApproved').textContent = summary.cases.approved;
    el('statFailed').textContent = summary.runs.failed;
    renderRequirements(); renderExecutionCases(); renderRuns(); renderRecentRuns();
    if (state.selectedWorkflow) await loadWorkflow(state.selectedWorkflow, false);
    updatePolling();
  } catch (error) {
    el('apiDot').classList.remove('online'); el('apiText').textContent = '后端连接失败'; showToast(error.message, true);
  }
}

function chooseRequirement(file) {
  state.selectedDocument = file || null;
  el('selectedDocument').textContent = file ? `${file.name} · ${formatSize(file.size)}` : '尚未选择文件';
  el('uploadButton').disabled = !file;
}

async function uploadRequirement() {
  const file = state.selectedDocument;
  if (!file) return;
  el('uploadButton').disabled = true; el('uploadButton').textContent = '上传中...'; el('uploadZone').classList.add('uploading');
  try {
    const workflow = await request('/requirements', {method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-Filename': file.name}, body: file});
    chooseRequirement(null); el('requirementFile').value = '';
    state.selectedWorkflow = workflow.id;
    showView('review'); await loadRequirements(); await loadWorkflow(workflow.id);
  } catch (error) { showToast(error.message, true); }
  finally { el('uploadButton').textContent = '上传并开始分析'; el('uploadButton').disabled = !state.selectedDocument; el('uploadZone').classList.remove('uploading'); }
}

async function loadRequirements() {
  state.requirements = (await request('/requirements')).requirements;
  renderRequirements(); updatePolling();
}

function renderRequirements() {
  el('requirementList').innerHTML = state.requirements.length ? `<div class="table-wrap"><table><thead><tr><th>文档</th><th>大小</th><th>上传时间</th><th>当前状态</th><th></th></tr></thead><tbody>${state.requirements.map(item => `<tr class="clickable"><td><b>${esc(item.name)}</b></td><td>${formatSize(item.size)}</td><td>${formatTime(item.uploaded_at)}</td><td>${statusBadge(item)}</td><td>${item.id ? `<button class="btn" data-open-workflow="${esc(item.id)}">查看</button>${item.status === 'failed' ? ` <button class="btn" data-retry-workflow="${esc(item.id)}">重试</button>` : ''}` : '-'}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">还没有需求文档，请先上传原始需求</div>';
}

async function loadWorkflow(id, notify = true) {
  try {
    const workflow = await request(`/requirements/${encodeURIComponent(id)}`);
    state.selectedWorkflow = id; renderWorkflow(workflow); updatePolling(workflow);
  } catch (error) { if (notify) showToast(error.message, true); }
}

function listBlock(title, items, formatter = item => esc(item)) {
  return `<div class="analysis-block"><h3>${esc(title)}</h3>${items?.length ? `<ul>${items.map(item => `<li>${formatter(item)}</li>`).join('')}</ul>` : '<span class="subtle">无</span>'}</div>`;
}

function renderWorkflow(workflow) {
  el('reviewEmpty').hidden = true; el('reviewWorkspace').hidden = false;
  el('reviewTitle').textContent = workflow.filename;
  el('reviewMeta').textContent = `上传于 ${formatTime(workflow.created_at)}`;
  el('reviewStatus').className = `status-pill ${ACTIVE_STATUSES.has(workflow.status) ? 'active' : 'waiting'}`;
  el('reviewStatus').textContent = `${workflow.status_label}${ACTIVE_STATUSES.has(workflow.status) ? `（${formatDuration(workflow.current_stage_duration_ms)}）` : ''}`;
  el('stageStrip').innerHTML = (workflow.stages || []).map(stage => `<div class="stage-item ${stage.finished_at ? 'done' : 'current'}"><b>${esc(stage.label)}</b><span>${stage.finished_at ? `完成 · ${formatDuration(stage.duration_ms)}` : `进行中 · ${formatDuration(workflow.current_stage_duration_ms)}`}</span></div>`).join('') || '<span class="subtle">等待开始分析</span>';
  renderAnalysis(workflow.analysis);
  renderQuestions(workflow);
  renderDraft(workflow.draft_cases || []);
  if (workflow.error) el('questionsContent').innerHTML = `<div class="diagnosis failed"><h3>AI 处理失败</h3><p>${esc(workflow.error)}</p><button class="btn" data-retry-workflow="${esc(workflow.id)}">重新分析</button></div>`;
}

function renderAnalysis(analysis) {
  if (!analysis) { el('analysisContent').innerHTML = '<div class="empty">AI 正在阅读需求文档和服务器代码</div>'; return; }
  const coverage = analysis.coverage_scope || {};
  el('analysisContent').innerHTML = `<p>${esc(analysis.summary)}</p><div class="analysis-grid">${listBlock('已读取范围', coverage.read)}${listBlock('缺失信息', coverage.missing)}${listBlock('业务规则', analysis.business_rules, item => `<b>${esc(item.category)}</b>：${esc(item.statement)} <span class="subtle">${esc(item.source)}</span>`)}${listBlock('服务器处理流程', analysis.server_flow, item => `<b>${esc(item.layer)}</b>：${esc(item.behavior)}<br><span class="subtle">${esc((item.evidence || []).join('；'))}</span>`)}${listBlock('风险', analysis.risks, item => `<b class="danger">${esc(item.severity)}</b> ${esc(item.title)}<br><span class="subtle">${esc((item.evidence || []).join('；'))}</span>`)}${listBlock('待确认项', analysis.unknowns)}</div>`;
}

function renderQuestions(workflow) {
  el('reviewConclusion').textContent = workflow.review_conclusion || 'AI 完成需求评审后会在这里提出待确认问题';
  const questions = workflow.review_questions || [];
  if (workflow.status === 'waiting_review_answers') {
    el('questionsContent').innerHTML = `${questions.map(question => `<div class="question"><div class="question-head"><span class="severity">${esc(question.severity)}</span><b>${esc(question.location)}</b></div><p><b>${esc(question.question)}</b></p><p class="subtle">影响：${esc(question.impact || '未说明')}</p><p class="subtle">需要确认：${esc(question.confirmation_needed || '请按实际口径回答')}</p><textarea data-question-id="${esc(question.id)}" placeholder="输入测试口径或产品确认结果"></textarea></div>`).join('')}<button class="btn primary" id="submitAnswers">${questions.length ? '提交全部回答并生成初版' : '确认无待回答问题并生成初版'}</button>`;
    el('submitAnswers').onclick = submitAnswers;
  } else if (questions.length) {
    el('questionsContent').innerHTML = questions.map(question => `<div class="question"><div class="question-head"><span class="severity">${esc(question.severity)}</span><b>${esc(question.location)}</b></div><p><b>${esc(question.question)}</b></p><p>已对齐口径：${esc(question.answer || '等待回答')}</p></div>`).join('');
  } else {
    el('questionsContent').innerHTML = `<div class="empty">${ACTIVE_STATUSES.has(workflow.status) ? 'AI 正在评审需求' : '没有评审问题'}</div>`;
  }
}

async function submitAnswers() {
  const inputs = [...document.querySelectorAll('[data-question-id]')];
  const answers = Object.fromEntries(inputs.map(input => [input.dataset.questionId, input.value.trim()]));
  const empty = inputs.find(input => !input.value.trim());
  if (empty) { empty.focus(); return showToast('请回答全部评审问题', true); }
  el('submitAnswers').disabled = true;
  try {
    const workflow = await request(`/requirements/${encodeURIComponent(state.selectedWorkflow)}/events`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({event: 'answers_submitted', answers})});
    renderWorkflow(workflow); updatePolling(workflow); showToast('回答已提交，正在生成初版用例');
  } catch (error) { showToast(error.message, true); el('submitAnswers').disabled = false; }
}

function groupDraft(cases) {
  const tree = {};
  cases.forEach(item => { const module = item.module || '未分类模块', feature = item.feature || '未分类功能', scenario = item.scenario || '默认场景'; (((tree[module] ||= {})[feature] ||= {})[scenario] ||= []).push(item); });
  return tree;
}

function draftBranch(label, children, count) {
  return `<li><button class="tree-node draft-branch"><span class="tree-toggle">+</span><span class="tree-label">${esc(label)}</span><span class="tree-count">${count}</span></button><ul class="tree-collapsed">${children}</ul></li>`;
}

function renderDraft(cases) {
  el('draftSummary').textContent = cases.length ? `${cases.length} 条初版用例，默认收起；点击节点展开` : '回答评审问题后由 AI 生成';
  el('draftTree').innerHTML = Object.entries(groupDraft(cases)).map(([module, features]) => draftBranch(module, Object.entries(features).map(([feature, scenarios]) => draftBranch(feature, Object.entries(scenarios).map(([scenario, items]) => draftBranch(scenario, items.map(item => `<li><button class="tree-node case-leaf" data-draft-case="${esc(item.id)}"><span class="tree-label">${esc(item.name)}</span></button></li>`).join(''), items.length)).join(''), Object.values(scenarios).flat().length)).join(''), Object.values(features).flatMap(value => Object.values(value).flat()).length)).join('') || '<li class="empty">尚未生成初版用例</li>';
  el('draftCaseDetail').innerHTML = '';
  el('draftTree').querySelectorAll('.draft-branch').forEach(button => button.onclick = () => { const branch = button.nextElementSibling; const closed = branch.classList.toggle('tree-collapsed'); button.querySelector('.tree-toggle').textContent = closed ? '+' : '−'; });
  el('draftTree').querySelectorAll('[data-draft-case]').forEach(button => button.onclick = () => showDraftDetail(cases.find(item => item.id === button.dataset.draftCase)));
}

function detailList(title, values) { return `<h3>${esc(title)}</h3>${values?.length ? `<ul>${values.map(value => `<li>${esc(value)}</li>`).join('')}</ul>` : '<p class="subtle">无</p>'}`; }
function showDraftDetail(item) {
  if (!item) return;
  const evidence = item.server_evidence || {};
  el('draftCaseDetail').innerHTML = `<div class="case-detail-box"><h3>${esc(item.name)}</h3><div class="kv"><b>测试目标</b><span>${esc(item.objective)}</span><b>自动化可行性</b><span>${esc(item.automation?.status)}：${esc(item.automation?.reason)}</span><b>数据影响</b><span>${esc(item.data_impact)}</span><b>清理方式</b><span>${esc(item.cleanup)}</span></div>${detailList('前置条件', item.preconditions)}${detailList('执行步骤', item.steps)}${detailList('预期结果', item.expected_results)}${detailList('来源依据', item.source_refs)}${detailList('服务器证据', Object.entries(evidence).flatMap(([key, values]) => (values || []).map(value => `${key}: ${value}`)))}</div>`;
}

function renderExecutionCases() {
  const cases = state.cases.filter(item => item.review_status === 'approved');
  el('executionCases').innerHTML = cases.length ? `<div class="table-wrap"><table><thead><tr><th></th><th>模块 / 功能 / 用例</th><th>活动</th><th>规模</th><th>评审版本</th></tr></thead><tbody>${cases.map(item => `<tr><td><input class="case-check" type="checkbox" value="${esc(item.file)}"></td><td>${esc(item.module)} / ${esc(item.feature)} / <b>${esc(item.name)}</b></td><td>${esc(item.activity_id || '-')}</td><td>${item.step_count} 步 / ${item.assertion_count} 个断言</td><td>第 ${item.review_iteration} 版</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">没有已批准的用例</div>';
  document.querySelectorAll('.case-check').forEach(box => box.onchange = updateSelection); updateSelection();
}
function updateSelection() { el('selectionCount').textContent = `已选择 ${document.querySelectorAll('.case-check:checked').length} 个用例`; }
function toggleCases(selected) { document.querySelectorAll('.case-check').forEach(box => box.checked = selected); updateSelection(); }
function envPayload() { return {UID_VALUE: el('uid').value.trim(), GATE_HOST: el('host').value.trim(), GATE_PORT: el('port').value.trim(), NETWORK: el('network').value.trim(), REDIS_CONTAINER: el('redis').value.trim(), GARDEN_CONTAINER: el('garden').value.trim(), BUILD: el('build').value, PREPARE_SID: el('prepareSid').value}; }

async function runSelected() {
  const cases = [...document.querySelectorAll('.case-check:checked')].map(box => box.value);
  if (!cases.length) return showToast('请至少选择一个用例', true);
  if (!el('uid').value.trim() || !el('host').value.trim() || !el('port').value.trim()) return showToast('请填写 UID 和 Gate 地址端口', true);
  el('runSelectedButton').disabled = true;
  try { const result = await request('/runs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...envPayload(), cases})}); showView('reports'); await loadRuns(); if (result.run_ids[0]) selectRun(result.run_ids[0]); }
  catch (error) { showToast(error.message, true); }
  finally { el('runSelectedButton').disabled = false; }
}

function caseName(file) { return state.cases.find(item => item.file === file)?.name || file; }
function runsTable(items, limit) {
  const rows = limit ? items.slice(0, limit) : items;
  return rows.length ? `<div class="table-wrap"><table><thead><tr><th>状态</th><th>用例</th><th>创建时间</th><th></th></tr></thead><tbody>${rows.map(item => `<tr><td><span class="badge ${esc(item.status)}">${esc(statusText(item.status))}</span></td><td>${esc(caseName(item.case))}<br><span class="subtle">${esc(item.id.slice(0, 8))}</span></td><td>${formatTime(item.created_at)}</td><td><button class="btn" data-run-id="${esc(item.id)}">查看</button></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">暂无执行记录</div>';
}
function bindRunButtons(root) { root.querySelectorAll('[data-run-id]').forEach(button => button.onclick = () => { showView('reports'); selectRun(button.dataset.runId); }); }
function renderRecentRuns() { el('recentRuns').innerHTML = runsTable(state.runs, 5); bindRunButtons(el('recentRuns')); }
function renderRuns() { const filter = el('runFilter').value; const runs = state.runs.filter(item => filter === 'all' || (filter === 'active' ? ['queued', 'running'].includes(item.status) : item.status === filter)); el('runList').innerHTML = runsTable(runs); bindRunButtons(el('runList')); }
async function loadRuns() { state.runs = (await request('/runs')).runs; renderRuns(); renderRecentRuns(); updatePolling(); }
async function selectRun(id) { state.selectedRun = id; try { const run = await request(`/runs/${id}`); el('reportTime').textContent = formatTime(run.finished_at || run.created_at); ['queued', 'running'].includes(run.status) ? el('reportDetail').innerHTML = `<div class="diagnosis"><h3>${esc(statusText(run.status))}</h3><p>任务正在执行，页面会自动更新结果。</p></div>` : renderReport(run); updatePolling(); } catch (error) { el('reportDetail').innerHTML = `<div class="empty danger">${esc(error.message)}</div>`; } }
function renderReport(run) { const diagnosis = run.diagnosis || {}, report = run.report || {}; const events = (report.events || []).map(item => `<div class="event"><span class="mark ${esc(item.status)}"></span><b>${esc(item.step)}</b><span>${esc(item.status === 'PASSED' ? '执行成功' : item.details?.error || statusText(item.status))}</span></div>`).join('') || '<div class="empty">无步骤数据</div>'; const assertions = (report.assertions || []).map(item => `<div class="assertion"><span class="badge ${item.passed ? 'passed' : 'failed'}">${item.passed ? '通过' : '失败'}</span><b>${esc(item.name)}</b><span>实际 ${esc(item.actual)}，期望 ${esc(item.op)} ${esc(item.expected)}</span></div>`).join('') || '<div class="empty">执行未进入断言阶段</div>'; el('reportDetail').innerHTML = `<div class="diagnosis ${esc(run.status)}"><h3>${esc(diagnosis.title || statusText(run.status))}</h3><div class="kv"><b>定位阶段</b><span>${esc(diagnosis.stage || '-')}</span><b>问题说明</b><span>${esc(diagnosis.cause || '-')}</span><b>开发排查</b><span>${esc(diagnosis.developer_hint || '-')}</span><b>报告文件</b><span>${esc(run.report_path || '-')}</span></div></div><h3>执行步骤</h3>${events}<h3>断言结果</h3>${assertions}<details><summary>查看原始执行日志</summary><pre>${esc(run.logs?.client)}\n${esc(run.logs?.error)}</pre></details>`; }

function updatePolling(workflow) {
  const workflowActive = workflow ? ACTIVE_STATUSES.has(workflow.status) : state.requirements.some(item => ACTIVE_STATUSES.has(item.status));
  const runsActive = state.runs.some(item => ['queued', 'running'].includes(item.status));
  if ((workflowActive || runsActive) && !state.poll) state.poll = setInterval(async () => { await loadRequirements(); if (state.selectedWorkflow) await loadWorkflow(state.selectedWorkflow, false); if (state.runs.some(item => ['queued', 'running'].includes(item.status))) { await loadRuns(); if (state.selectedRun) await selectRun(state.selectedRun); } }, 1000);
  if (!workflowActive && !runsActive && state.poll) { clearInterval(state.poll); state.poll = null; }
}

document.querySelectorAll('.nav button').forEach(button => button.onclick = () => showView(button.dataset.view));
document.querySelectorAll('[data-go]').forEach(button => button.onclick = () => showView(button.dataset.go));
el('refreshButton').onclick = refreshAll; el('refreshRequirements').onclick = loadRequirements;
el('uploadZone').onclick = () => el('requirementFile').click(); el('requirementFile').onchange = event => chooseRequirement(event.target.files[0]); el('uploadButton').onclick = uploadRequirement;
el('uploadZone').ondragover = event => { event.preventDefault(); el('uploadZone').classList.add('dragging'); };
el('uploadZone').ondragleave = () => el('uploadZone').classList.remove('dragging');
el('uploadZone').ondrop = event => { event.preventDefault(); el('uploadZone').classList.remove('dragging'); chooseRequirement(event.dataTransfer.files[0]); };
el('requirementList').onclick = async event => { const open = event.target.closest('[data-open-workflow]'), retry = event.target.closest('[data-retry-workflow]'); if (open) { state.selectedWorkflow = open.dataset.openWorkflow; showView('review'); await loadWorkflow(state.selectedWorkflow); } if (retry) { await request(`/requirements/${retry.dataset.retryWorkflow}/analyze`, {method: 'POST'}); await loadWorkflow(retry.dataset.retryWorkflow); } };
el('reviewWorkspace').onclick = async event => { const retry = event.target.closest('[data-retry-workflow]'); if (retry) { await request(`/requirements/${retry.dataset.retryWorkflow}/analyze`, {method: 'POST'}); await loadWorkflow(retry.dataset.retryWorkflow); } };
el('expandDraft').onclick = () => { el('draftTree').querySelectorAll('ul').forEach(node => node.classList.remove('tree-collapsed')); el('draftTree').querySelectorAll('.tree-toggle').forEach(node => node.textContent = '−'); };
el('collapseDraft').onclick = () => { el('draftTree').querySelectorAll('ul').forEach(node => node.classList.add('tree-collapsed')); el('draftTree').querySelectorAll('.tree-toggle').forEach(node => node.textContent = '+'); };
el('selectAllCases').onclick = () => toggleCases(true); el('clearCases').onclick = () => toggleCases(false); el('runSelectedButton').onclick = runSelected; el('runFilter').onchange = renderRuns;
refreshAll();
