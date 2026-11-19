import {prepareVoice, reminderWords, warmPlan} from './voice.js';
import {setupScanner, showPhoto, scanStatus} from './scan.js';
import {setupReport, renderMedicationCard, saveMedicationCard} from './cards.js';
import {mealLabels, readResult, buildRows, dueReminders, nextReminder} from './schedule.mjs';

const byId = id => document.getElementById(id);
const put = (id, value) => {
  const element = byId(id);
  if (element.textContent !== value) element.textContent = value;
};
const mealsIds = Object.keys(mealLabels);
const storageKey = 'elder-voice-reminders-v1';
const audio = byId('audio');
let customAudioUrl;
let activePlayback;
let activeSpeech;
let audioSource = '';
let cloudAudioUrl;
let playbackSequence = 0;
const trialWords = '到提醒时间了，请看看今天的提醒卡。';
let scannedMedication;
const usingDemo = () => ['当前使用虚构示例', '虚构扫描示例'].includes(byId('source').textContent);
let state = {};
try { state = JSON.parse(localStorage.getItem(storageKey)) || {}; } catch { /* fresh session */ }
let entries = Array.isArray(state.entries) ? state.entries : [];
let overrides = state.overrides || {};
let plan = state.plan || null;
let seen = new Set(state.seen || []);

const headings = {home: 'home-head', report: 'report-head', meds: 'meds-head',
  reminder: 'listen-head'};

function openScreen(name, focus = false) {
  for (const screen of Object.keys(headings)) byId(screen + '-screen').hidden = screen !== name;
  for (const button of document.querySelectorAll('[data-screen]')) {
    const selected = button.dataset.screen === name;
    if (selected) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (focus) {
    window.scrollTo(0, 0);
    byId(headings[name]).focus({preventScroll: true});
  }
}
for (const button of document.querySelectorAll('[data-screen]')) {
  button.addEventListener('click', () => openScreen(button.dataset.screen, true));
}

for (const button of document.querySelectorAll('[data-go]')) {
  button.addEventListener('click', () => openScreen(button.dataset.go, true));
}

function meals() {
  return Object.fromEntries(mealsIds.map(id => [id, byId(id).value]));
}
function save() {
  try {
    localStorage.setItem(storageKey, JSON.stringify({
      entries, overrides, plan, meals: meals(), seen: [...seen].slice(-100),
      source: byId('source').textContent,
    }));
  } catch {
    put('error', '浏览器未能保存设置，刷新前请记录提醒时间。');
  }
}
function rows() { return buildRows(entries, meals(), overrides); }

function renderRows() {
  const list = byId('rows');
  list.replaceChildren();
  for (const row of rows()) {
    const article = document.createElement('article');
    article.className = 'row';
    const header = document.createElement('div');
    header.className = 'row-head';
    const name = document.createElement('strong');
    name.textContent = row.name;
    const status = document.createElement(row.allowed ? 'time' : 'span');
    status.textContent = row.allowed ? row.time : row.reason;
    if (!row.allowed) status.className = 'waiting';
    header.append(name, status);
    const source = document.createElement('small');
    source.textContent = [row.label, row.source].filter(Boolean).join(' · ');
    article.append(header, source);
    if (row.needsTime) {
      const label = document.createElement('label');
      label.textContent = '手动确认提醒钟点';
      const input = document.createElement('input');
      input.type = 'time';
      input.value = overrides[row.id] || '';
      input.setAttribute('aria-label', row.name + '的提醒钟点');
      input.addEventListener('change', () => {
        overrides[row.id] = input.value;
        invalidatePlan();
        renderRows();
      });
      label.append(input);
      article.append(label);
    }
    list.append(article);
  }
  byId('enable').disabled = !entries.length;
  byId('enable').hidden = !entries.length;
  byId('agree').parentElement.hidden = !entries.length;
  byId('reminder-empty').hidden = Boolean(entries.length);
  byId('med-empty').hidden = Boolean(entries.length);
  byId('med-plan').hidden = !entries.length;
  byId('save-meds').disabled = !entries.length;
  renderMedicationCard(rows());
}

function showNext(now = Date.now()) {
  const next = plan && nextReminder(plan, now);
  put('home-next', next ? next.time : '提醒未开启');
  put('home-next-detail', next ? (next.tomorrow ? '明天 · ' : '今天 · ') + next.name : '先拍用药单，核对用法后开启。');
  if (byId('alert').classList.contains('active')) return;
  byId('alert').dataset.state = next ? 'on' : 'off';
  put('reminder-label', next ? (next.demo ? '虚构示例 · 下次提醒' : '下次提醒') : '提醒状态');
  put('alert-title', next ? next.time : '提醒未开启');
  put('alert-detail', next
    ? (next.tomorrow ? '明天 · ' : '今天 · ') + next.name
    : '先拍用药单，识别药名和用法，再核对开启。');
}

function showPlan() {
  playbackSequence++;
  audio.pause();
  window.speechSynthesis?.cancel();
  activePlayback = undefined;
  byId('alert').classList.remove('active');
  byId('reminder-start').hidden = Boolean(plan);
  put('reminder-start', entries.length ? '核对时间，重新开启提醒' : '拍用药单，开启提醒');
  byId('reminder-sound').hidden = !plan;
  byId('play').lastChild.textContent = '听听提醒内容';
  byId('voice-transcript').hidden = true;
  put('audio-status', '');
  byId('stop').hidden = !plan;
  put('plan-status', plan
    ? '已开启 ' + plan.rows.length + ' 条每日提醒。'
    : '提醒未开启。');
  showNext();
  showVoiceOptions();
}
function invalidatePlan() {
  if (plan) {
    plan = null;
    put('error', '安排已修改，原提醒已暂停。请重新核对并开启。');
  }
  byId('agree').checked = false;
  showPlan();
  save();
}

function playbackForRows(rows) {
  return {
    demo: rows.every(row => row.demo),
    words: rows.some(row => row.dose) ? reminderWords(rows) : '',
    cloud: rows.every(row => row.cloudVoice),
    fallback: rows.length === 1 && rows[0].demo && rows[0].name === '演示胶囊'
      && rows[0].diet === '服药期间请勿饮酒' ? '/scan-demo.wav' : '',
  };
}

const trial = {words: trialWords, cloud: true, fallback: '/demo.mp3'};

function nextPlayback() {
  if (activePlayback) return activePlayback;
  if (!plan?.rows.length) return trial;
  const next = nextReminder(plan, Date.now());
  return playbackForRows(plan.rows.filter(row => row.time === next.time));
}

function showVoiceOptions() {
  put('voice-mode-description', customAudioUrl
    ? '到点将播放你选择的录音。可以先听一遍，确认内容和音量。'
    : '到点会自动读出药名、每次用量和用法。可以先听一遍，确认声音听得清。');
  byId('clear-voice').hidden = !customAudioUrl;
  byId('cloud-approval').hidden = !plan?.rows.some(row => row.dose && !row.cloudVoice);
}

async function play() {
  const {words, cloud, fallback} = nextPlayback();
  const sequence = ++playbackSequence;
  window.speechSynthesis?.cancel();
  audio.pause();
  byId('voice-transcript').hidden = !words || Boolean(customAudioUrl);
  put('voice-transcript', words);
  let cloudFailed = false;
  if (cloud && words && !customAudioUrl) {
    put('audio-status', '正在准备千问语音…');
    const clip = await prepareVoice(words);
    if (sequence !== playbackSequence) return;
    if (clip) {
      if (cloudAudioUrl) URL.revokeObjectURL(cloudAudioUrl);
      cloudAudioUrl = URL.createObjectURL(clip);
      audio.src = cloudAudioUrl;
      audioSource = '千问合成语音';
      try {
        await audio.play();
        if (sequence === playbackSequence) put('audio-status', '正在播放千问合成语音。');
      } catch {
        if (sequence === playbackSequence) put('audio-status', '千问语音已就绪，请点提醒声音里的播放按钮。');
      }
      return;
    }
    cloudFailed = true;
  }

  const fallbackPrefix = cloudFailed ? '千问语音不可用。' : '';
  if (words && !customAudioUrl && !fallback) {
    const synth = window.speechSynthesis;
    const voice = synth?.getVoices().find(candidate => candidate.localService
      && /^zh(?:-|_)/i.test(candidate.lang));
    if (!voice || !window.SpeechSynthesisUtterance) {
      put('audio-status', fallbackPrefix + '本机中文语音不可用，请查看提醒文稿。');
      return;
    }
    const speech = new SpeechSynthesisUtterance(words);
    activeSpeech = speech;
    speech.lang = voice.lang;
    speech.voice = voice;
    speech.rate = .85;
    speech.onstart = () => {
      if (sequence === playbackSequence) put('audio-status', fallbackPrefix + '正在使用本机语音播报。');
    };
    speech.onend = () => {
      if (activeSpeech === speech) activeSpeech = undefined;
      if (sequence === playbackSequence) put('audio-status', '本机语音已播完。');
    };
    speech.onerror = event => {
      if (sequence === playbackSequence && !['canceled', 'interrupted'].includes(event.error)) {
        put('audio-status', '语音未能播放，请点提醒声音里的播放按钮重试。');
      }
    };
    synth.speak(speech);
    return;
  }

  const file = customAudioUrl || fallback;
  if (!file) {
    put('audio-status', '这条提醒缺少已核对的用法，请重新拍照确认。');
    return;
  }
  if (audio.src !== new URL(file, location.href).href) audio.src = file;
  audioSource = customAudioUrl ? '手动选择的音频' : '备用示例音频';
  try {
    audio.currentTime = 0;
    await audio.play();
    if (sequence === playbackSequence) put('audio-status', fallbackPrefix + '正在播放' + audioSource + '。');
  } catch {
    if (sequence === playbackSequence) put('audio-status', fallbackPrefix + '请点提醒声音里的播放按钮重试。');
  }
}

function showAlert(title, detail, playback) {
  activePlayback = playback;
  if (byId('reminder-screen').hidden) openScreen('reminder', true);
  put('reminder-label', '用药叮嘱');
  put('alert-title', title);
  put('alert-detail', detail);
  byId('alert').classList.add('active');
  byId('reminder-sound').hidden = false;
  byId('play').lastChild.textContent = '再听一遍提醒';
  put('reminder-label', (playback?.demo ? '虚构示例 · 到提醒时间了' : '现在到点了 · 请查看用药安排'));
  play();
}

function tick() {
  if (!plan) return;
  const now = Date.now();
  const due = dueReminders(plan, now, seen);
  if (!due.length) {
    showNext(now);
    return;
  }
  for (const occurrence of due) seen.add(occurrence.key);
  save();
  const details = due.map(row => [row.time, row.name, row.label, row.dose].filter(Boolean).join('，'));
  showAlert('到提醒时间了', details.join('。'), playbackForRows(due));
  if (!customAudioUrl) warmPlan(plan.rows, now);
}

byId('plan-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!byId('agree').checked) return;
  const ready = rows().filter(row => row.allowed);
  if (!ready.length) {
    put('error', '没有可开启的提醒。请先核对用法和提醒钟点。');
    return;
  }
  put('error', '');
  plan = {since: Date.now(), rows: ready};
  seen.clear();
  save();
  showPlan();
  warmPlan(plan.rows);
  openScreen('reminder', true);
});
byId('stop').addEventListener('click', () => {
  plan = null;
  byId('agree').checked = false;
  showPlan();
  save();
});
for (const id of mealsIds) {
  if (state.meals?.[id]) byId(id).value = state.meals[id];
  byId(id).addEventListener('change', () => {
    invalidatePlan();
    renderRows();
  });
}
byId('reminder-start').addEventListener('click', () => {
  if (!entries.length) { openScreen('meds', true); return; }
  byId('reminder-settings').open = true;
  byId('reminder-settings').scrollIntoView({block: 'start'});
});
byId('play').addEventListener('click', play);
audio.addEventListener('ended', () => put('audio-status', audioSource + '已播完。'));
byId('voice').addEventListener('change', event => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 15_000_000) {
    put('audio-status', '请选择不超过 15 MB 的音频。');
    event.target.value = '';
    return;
  }
  playbackSequence++;
  audio.pause();
  window.speechSynthesis?.cancel();
  if (customAudioUrl) URL.revokeObjectURL(customAudioUrl);
  customAudioUrl = URL.createObjectURL(file);
  audio.src = customAudioUrl;
  put('audio-status', '已选好录音，到点将播放这段录音。');
  showVoiceOptions();
});
byId('clear-voice').addEventListener('click', () => {
  playbackSequence++;
  audio.pause();
  if (customAudioUrl) URL.revokeObjectURL(customAudioUrl);
  customAudioUrl = undefined;
  byId('voice').value = '';
  put('audio-status', '已恢复自动语音，可点「听听提醒内容」试听。');
  showVoiceOptions();
});
byId('approve-cloud').addEventListener('click', () => {
  if (!plan) return;
  const approved = new Set(plan.rows.filter(row => row.dose).map(row => row.id));
  entries = entries.map(row => approved.has(row.id) ? {...row, cloudVoice: true} : row);
  plan = {...plan, rows: plan.rows.map(row => approved.has(row.id) ? {...row, cloudVoice: true} : row)};
  save();
  showVoiceOptions();
  warmPlan(plan.rows);
  put('audio-status', '已开启千问语音，可点「听听提醒内容」试听。');
});
const scanDialog = byId('reminder-confirm');
function showDailySummary() {
  if (!scannedMedication) return;
  const draft = readResult({reminders: [{...scannedMedication, confirmed: true}]});
  const row = buildRows(draft, meals(), {0: byId('scan-reminder-time').value})[0];
  put('scan-daily-summary', row.allowed
    ? '每天 ' + row.time + ' · 按上方用法提醒'
    : '选好钟点，确认后每天提醒。');
}
byId('scan-reminder-time').addEventListener('input', showDailySummary);
setupScanner({kind: 'medication', inputs: ['med-camera', 'med-photo'],
  example: 'scan-med-demo', status: 'med-scan-status',
  onStart() {
    scannedMedication = undefined;
    byId('med-draft').hidden = true;
    byId('med-original').hidden = true;
    byId('med-original').open = false;
  },
  onResult(result, image, demo) {
    showPhoto(byId('med-preview'), image);
    byId('med-original').hidden = false;
    if (!result.complete) {
      scanStatus('med-scan-status', '还没读全，暂不开启提醒。请拍清「药名、每天几次、每次几片或几粒、哪餐前后」。只有药盒规格，不能确定每次用量。', 'error');
      return;
    }
    scannedMedication = {...result, demo};
    scanStatus('med-scan-status', (demo ? '虚构示例 · ' : '') + '已读出药名和用法，请核对。', 'success');
    put('med-draft-summary', result.name + ' · ' + result.source);
    byId('med-draft').hidden = false;
    showPhoto(byId('confirm-photo'), image);
    byId('confirm-photo').parentElement.open = false;
    put('confirm-intro', '按识别到的用法，每天到点提醒你。');
    put('scan-drug-name', result.name);
    put('scan-drug-instruction', '每天' + mealLabels[result.meal]
      + (result.relation === 'at' ? '随餐' : result.relation === 'before' ? '前' : '后')
      + (result.minutes ? ' ' + result.minutes + ' 分钟' : '') + ' · ' + result.dose);
    put('scan-drug-source', '识别原文：' + result.source);
    put('scan-diet', result.diet
      ? '饮食提示（请对照原文）：' + result.diet
      : '未识别到明确饮食禁忌，不加入播报。');
    const draft = readResult({reminders: [{...result, confirmed: true}]});
    const suggestion = buildRows(draft, meals())[0];
    byId('scan-reminder-time').value = suggestion.time || '';
    byId('scan-reminder-time').readOnly = Boolean(suggestion.time);
    put('scan-time-hint', suggestion.time
      ? '按' + mealLabels[result.meal] + ' ' + meals()[result.meal] + ' 和识别用法计算。可在提醒页的「提醒设置」修改三餐时间。'
      : '当前' + mealLabels[result.meal] + ' ' + meals()[result.meal] + '，原文未写明间隔，请选提醒钟点。');
    showDailySummary();
    byId('scan-approved').checked = false;
    put('scan-approval-label', demo ? '我已核对这条虚构示例' : '我已核对本人当前用法及上面的饮食提示');
    put('scan-confirm-error', '');
    if (!scanDialog.open) scanDialog.showModal();
  }
});
byId('resume-confirm').addEventListener('click', () => { if (scannedMedication) { scanDialog.showModal(); scanDialog.scrollTop = 0; } });
byId('close-scan-reminder').addEventListener('click', () => scanDialog.close());
byId('scan-reminder-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!scannedMedication || !byId('scan-approved').checked) return;
  try {
    const keep = Boolean(entries.length) && !usingDemo();
    if (keep && scannedMedication.demo) throw new Error('当前已有录入记录。请在独立浏览器会话试用虚构示例。');
    const previous = keep ? entries.map(entry => ({...entry, minutes: entry.offset})) : [];
    const nextEntries = readResult({reminders: [...previous, {...scannedMedication, confirmed: true, cloudVoice: true}]});
    const id = nextEntries.length - 1;
    const nextOverrides = {...(keep ? overrides : {}), [id]: byId('scan-reminder-time').value};
    const row = buildRows(nextEntries, meals(), nextOverrides)[id];
    if (!row.allowed) throw new Error(row.reason);
    const running = keep ? (plan?.rows || []) : [];
    entries = nextEntries;
    overrides = nextOverrides;
    plan = {since: plan?.since && running.length ? plan.since : Date.now(), rows: [...running, {...row, startedAt: Date.now()}]};
    put('source', scannedMedication.demo ? '虚构扫描示例' : '拍照识别 · 已核对');
    put('error', '');
    save();
    renderRows();
    showPlan();
    scanDialog.close();
    byId('med-draft').hidden = true;
    openScreen('reminder', true);
    put('audio-status', '已加入每天提醒，每天 ' + row.time + ' 到点播报。');
    const group = plan.rows.filter(item => item.time === row.time);
    if (group.every(item => item.cloudVoice)) void prepareVoice(reminderWords(group));
  } catch (error) {
    put('scan-confirm-error', error.message);
  }
});
byId('save-meds').addEventListener('click', () => {
  if (entries.length) saveMedicationCard(rows(), usingDemo());
});
function initialize() {
  if (state.source) put('source', state.source);
  renderRows();
  showPlan();
  if (plan) warmPlan(plan.rows);
  tick();
}
put('home-date', new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', weekday: 'long'
}).format(new Date()));
initialize();
fetch('/knowledge.json').then(response => {
  if (!response.ok) throw new Error('体检知识库加载失败，请刷新后重试。');
  return response.json();
}).then(setupReport).catch(error => put('report-status', error.message));
setInterval(tick, 500);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) tick();
});
