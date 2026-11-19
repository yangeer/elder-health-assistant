import {nextReminder} from './schedule.mjs';

const clips = new Map();
const limit = 8;
const cacheName = 'care-reminder-qwen-audio-v1';
const maxAge = 7 * 24 * 60 * 60 * 1000;

async function localAudioCache(words) {
  if (!globalThis.caches || !globalThis.crypto?.subtle) return null;
  try {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(words));
    const key = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
    const request = new URL('/_reminder-audio-cache/' + key, location.origin);
    const cache = await caches.open(cacheName);
    return {cache, request};
  } catch {
    return null;
  }
}

async function cachedAudio(storage) {
  if (!storage) return null;
  try {
    const response = await storage.cache.match(storage.request);
    if (!response) return null;
    const savedAt = Number(response.headers.get('X-Care-Saved-At'));
    if (!savedAt || Date.now() - savedAt >= maxAge) {
      await storage.cache.delete(storage.request);
      return null;
    }
    return await response.blob();
  } catch {
    return null;
  }
}

async function rememberAudio(storage, audio) {
  if (!storage) return;
  try {
    await storage.cache.delete(storage.request);
    await storage.cache.put(storage.request, new Response(audio, {
      headers: {'Content-Type': 'audio/wav', 'X-Care-Saved-At': String(Date.now())},
    }));
    const keys = await storage.cache.keys();
    for (const key of keys.slice(0, Math.max(keys.length - limit, 0))) {
      await storage.cache.delete(key);
    }
  } catch {
    // Some browsers and privacy modes do not allow saving media across reloads.
  }
}

export function reminderWords(rows) {
  return rows.map(row => {
    const [hour, minute] = row.time.split(':').map(Number);
    const time = hour + '点' + (minute ? minute + '分' : '');
    const meal = row.label + (row.offset ? row.offset + '分钟' : '');
    return '您设置的提醒时间是' + time + '。' + [row.name, meal, row.dose ? '每次' + row.dose : ''].filter(Boolean).join('，')
      + '。' + (row.diet ? '药袋或说明书提示：' + row.diet.replace(/[。！]+$/, '') + '。' : '');
  }).join('');
}

export function prepareVoice(words) {
  if (!words || words.length > 180) return Promise.resolve(null);
  if (clips.has(words)) {
    const found = clips.get(words);
    clips.delete(words);
    clips.set(words, found);
    return found;
  }
  if (clips.size >= limit) clips.delete(clips.keys().next().value);
  const pending = (async () => {
    const storage = await localAudioCache(words);
    const existing = await cachedAudio(storage);
    if (existing) return existing;
    try {
      const response = await fetch('/api/reminder/voice', {method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Care-Voice': '1'},
        body: JSON.stringify({text: words}), signal: AbortSignal.timeout(75_000)});
      if (!response.ok || !response.headers.get('Content-Type')?.startsWith('audio/wav')) return null;
      const audio = await response.blob();
      await rememberAudio(storage, audio);
      return audio;
    } catch {
      return null;
    }
  })();
  clips.set(words, pending);
  pending.then(clip => {
    if (!clip && clips.get(words) === pending) clips.delete(words);
  });
  return pending;
}

export function warmPlan(rows, now = Date.now()) {
  const next = nextReminder({rows}, now);
  if (!next) return;
  const group = rows.filter(row => row.time === next.time);
  if (group.every(row => row.cloudVoice)) void prepareVoice(reminderWords(group));
}
