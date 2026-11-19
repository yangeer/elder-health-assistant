import {setupScanner, showPhoto, scanStatus} from './scan.js';

const $ = id => document.getElementById(id);
const boundary = '仅作健康常识整理，不替代执业医师诊断与处方调整。';

function append(parent, tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  parent.append(element);
  return element;
}

function downloadCard(title, lines, filename) {
  const canvas = document.createElement('canvas');
  canvas.width = 900;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('当前浏览器无法导出图片。');
  const content = [];
  let height = 172;
  for (const {text, style = 'body'} of lines) {
    const size = style === 'lead' ? 40 : style === 'note' ? 27 : 34;
    ctx.font = (style === 'lead' ? 'bold ' : '') + size + 'px "Microsoft YaHei", sans-serif';
    let line = '';
    for (const char of text) {
      if (line && ctx.measureText(line + char).width > 772) {
        content.push({line, size, style, y: height});
        height += size + 12;
        line = '';
      }
      line += char;
    }
    if (line) {
      content.push({line, size, style, y: height});
      height += size + 22;
    }
  }
  canvas.height = height + 45;
  ctx.fillStyle = '#fcfcf5';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#184e3d';
  ctx.fillRect(0, 0, canvas.width, 123);
  ctx.textBaseline = 'top';
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 52px "Microsoft YaHei", sans-serif';
  ctx.fillText(title, 64, 34);
  for (const {line, size, style, y} of content) {
    ctx.fillStyle = style === 'note' ? '#486155' : '#163d31';
    ctx.font = (style === 'lead' ? 'bold ' : '') + size + 'px "Microsoft YaHei", sans-serif';
    ctx.fillText(line, 64, y);
  }
  canvas.toBlob(blob => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const download = document.createElement('a');
    download.href = url;
    download.download = filename;
    download.click();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }, 'image/png');
}

export function setupReport(knowledge) {
  const metrics = new Map(knowledge.metrics.map(metric => [metric.id, metric]));
  const resultsPanel = $('scan-report-results');
  const original = $('report-original');
  const saveArea = $('report-save-area');
  const reviewed = $('report-reviewed');
  const save = $('save-report');
  let draft;

  function reset() {
    draft = undefined;
    resultsPanel.replaceChildren();
    resultsPanel.hidden = true;
    original.hidden = true;
    original.open = false;
    saveArea.hidden = true;
    reviewed.checked = false;
    save.disabled = true;
    $('report-status').textContent = '';
  }

  function showMetric(row, metric) {
    const card = document.createElement('article');
    card.className = 'panel report-card';
    resultsPanel.append(card);
    const result = [row.value, row.unit, row.flag].filter(Boolean).join(' ');
    append(card, 'h2', metric.name);
    append(card, 'p', result, 'report-result');
    append(card, 'p', '报告参考范围：' + row.range, 'report-range');
    append(card, 'p', metric.plain, 'report-plain');

    const details = document.createElement('details');
    details.className = 'reading-source';
    card.append(details);
    append(details, 'summary', '更多说明与识别原文');
    append(details, 'p', metric.context, 'report-copy');
    append(details, 'h3', '日常提醒');
    append(details, 'p', metric.habit, 'report-copy');
    append(details, 'p', row.source, 'report-range');
    const source = knowledge.sources.find(item => item.id === metric.source);
    if (source && /^https:\/\//.test(source.url)) {
      const link = append(details, 'a', '参考：' + source.title);
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
    return [
      {text: metric.name + '  ' + result, style: 'lead'},
      {text: '报告参考范围：' + row.range},
      {text: metric.plain}, {text: metric.context},
      {text: '日常提醒：' + metric.habit},
    ];
  }

  setupScanner({
    kind: 'report', inputs: ['report-camera', 'report-photo'],
    example: 'scan-report-demo', status: 'report-scan-status', onStart: reset,
    onResult(results, image, demo) {
      showPhoto($('report-preview'), image);
      original.hidden = false;
      const readable = results.filter(row => metrics.has(row.metric));
      if (!readable.length) {
        scanStatus('report-scan-status', '这张还没读清。请靠近拍摄指标表，同一行保留「项目、数值、单位、参考范围」，避免反光和模糊。', 'error');
        return;
      }
      const badge = demo ? '虚构示例 · 识别待核对' : '照片识别 · 待核对';
      append(resultsPanel, 'p', badge, 'card-eyebrow');
      draft = [
        {text: demo ? '虚构示例' : '照片识别 · 请保留原报告', style: 'note'},
        ...readable.flatMap(row => showMetric(row, metrics.get(row.metric))),
        {text: boundary, style: 'note'},
      ];
      append(resultsPanel, 'p', boundary, 'fine-print');
      resultsPanel.hidden = false;
      saveArea.hidden = false;
      requestAnimationFrame(() => resultsPanel.scrollIntoView({block: 'start'}));
      scanStatus('report-scan-status', (demo ? '虚构示例 · ' : '') + '已读到 ' + readable.length + ' 项完整指标。未显示的项目，请拍清整行再试。', 'success');
    },
  });
  reviewed.addEventListener('change', () => { save.disabled = !reviewed.checked; });
  save.addEventListener('click', () => {
    if (draft && reviewed.checked) {
      downloadCard('体检大字卡', draft, '体检大字卡.png');
      $('report-status').textContent = '大字卡已生成，请在浏览器下载中查看。';
    }
  });
}

function visibleMedicationRows(rows) {
  return rows.slice().sort((a, b) => Number(b.allowed) - Number(a.allowed)
    || (a.time || '').localeCompare(b.time || ''));
}

export function renderMedicationCard(rows) {
  const card = $('med-card-rows');
  card.replaceChildren();
  for (const row of visibleMedicationRows(rows)) {
    const wrapper = append(card, 'div', '', 'row');
    const head = append(wrapper, 'div', '', 'row-head');
    append(head, 'strong', row.name);
    append(head, 'span', row.allowed ? row.time : '待确认', row.allowed ? 'med-time' : 'waiting');
    append(wrapper, 'small', row.allowed
      ? [row.label, row.dose, row.source].filter(Boolean).join(' · ')
      : [row.label, row.reason, row.source].filter(Boolean).join(' · '));
    if (row.allowed && row.diet) append(wrapper, 'small', '饮食原文：' + row.diet);
  }
}

export function saveMedicationCard(rows, demo) {
  const lines = [{text: demo ? '虚构示例' : '按已核对信息整理 · 请对照现行医嘱', style: 'note'}];
  for (const row of visibleMedicationRows(rows)) {
    lines.push({text: row.allowed ? row.time + '  ' + row.name : '待确认  ' + row.name, style: 'lead'});
    lines.push({text: (row.allowed ? [row.label, row.dose, row.source] : [row.reason, row.source])
      .filter(Boolean).join(' · ')});
    if (row.allowed && row.diet) lines.push({text: '饮食原文：' + row.diet});
  }
  lines.push({text: boundary, style: 'note'});
  downloadCard('每日用药大字卡', lines, '每日用药大字卡.png');
}
