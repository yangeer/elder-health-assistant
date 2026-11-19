const $ = id => document.getElementById(id);

export function scanStatus(id, message, state = 'success') {
  const element = $(id);
  element.textContent = message;
  element.classList.toggle('error', state === 'error');
  element.dataset.state = state;
  element.closest('.capture-panel').dataset.state = state;
  const retry = element.parentElement.querySelector('.retry-scan');
  if (retry) retry.hidden = state !== 'error';
}

export function setupScanner({kind, inputs, example, status, onStart, onResult}) {
  const feedback = $(status);
  const exampleButton = $(example);
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'retry-scan wide';
  retry.textContent = kind === 'report' ? '重新拍清指标表' : '重新拍清药名和用法';
  retry.hidden = true;
  retry.addEventListener('click', () => $(inputs[0]).click());
  feedback.after(retry);
  let controller;
  async function scan(getFile, demo = false) {
    controller?.abort();
    const current = new AbortController();
    controller = current;
    scanStatus(status, '正在本地识别，请稍等…', 'loading');
    feedback.setAttribute('aria-busy', 'true');
    exampleButton.disabled = true;
    onStart?.();
    try {
      const image = await getFile(current.signal);
      if (!image || current.signal.aborted) return;
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(image.type) || image.size > 12_000_000) {
        throw new Error('请选择不超过 12 MB 的 JPG、PNG 或 WebP。');
      }
      const response = await fetch('/api/scan/' + kind, {
        method: 'POST', headers: {'Content-Type': image.type}, body: image, signal: current.signal
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '识别失败，请重拍。');
      if (!current.signal.aborted) {
        scanStatus(status, '识别完成', 'success');
        onResult(data.result, image, demo);
      }
    } catch (error) {
      if (!current.signal.aborted) scanStatus(status, (error.message || '无法读取照片。') + (kind === 'report' ? ' 请拍清指标表的项目、数值、单位和参考范围。' : ' 请拍清个人用药单或现行医嘱上的药名和每次用量、用法。'), 'error');
    } finally {
      if (!current.signal.aborted) {
        feedback.setAttribute('aria-busy', 'false');
        exampleButton.disabled = false;
      }
    }
  }
  for (const id of inputs) $(id).addEventListener('change', event => {
    const file = event.target.files[0];
    if (file) scan(async () => file);
    event.target.value = '';
  });
  exampleButton.addEventListener('click', () => scan(async signal => {
    const response = await fetch(kind === 'report' ? '/demo-report-photo.png' : '/demo-med-photo.png', {signal});
    if (!response.ok) throw new Error('未能读取示例照片。');
    return response.blob();
  }, true));
}

export function showPhoto(element, image) {
  if (element.dataset.previewUrl) URL.revokeObjectURL(element.dataset.previewUrl);
  const url = URL.createObjectURL(image);
  element.dataset.previewUrl = url;
  element.src = url;
  element.hidden = false;
}
