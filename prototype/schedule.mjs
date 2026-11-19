const MINUTE = 60_000;
const DAY = 86_400_000;
const ZONE = 8 * 60 * MINUTE; // Asia/Shanghai
const MAX_DELAY = 15 * MINUTE;

export const mealLabels = {breakfast: '早餐', lunch: '午餐', dinner: '晚餐'};
const hasMeal = value => Object.hasOwn(mealLabels, value);
const format = value => /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
const parts = value => value.split(':').map(Number);
const minutes = value => {
  const [h, m] = parts(value);
  return h * 60 + m;
};
const validOffset = value => Number.isInteger(value) && value >= 1 && value <= 180;

export function readResult(data) {
  if (!data || !Array.isArray(data.reminders) || !data.reminders.length || data.reminders.length > 30) {
    throw new Error('请选择包含 1～30 条 reminders 的 JSON 文件。');
  }
  return data.reminders.map((item, index) => {
    const {name, source, confirmed, meal, relation, dose, demo, diet, cloudVoice, minutes: offset} = item ?? {};
    if (typeof name !== 'string' || !name.trim() || name.length > 80) {
      throw new Error('第 ' + (index + 1) + ' 条缺少有效的显示名称。');
    }
    return {id: index, name, source: typeof source === 'string' ? source.trim().slice(0, 160) : '',
      confirmed: confirmed === true, demo: demo === true, cloudVoice: cloudVoice === true,
      diet: typeof diet === 'string' ? diet.trim().slice(0, 55) : '', meal, relation, dose: typeof dose === 'string' ? dose.trim().slice(0, 70) : '', offset: validOffset(offset) ? offset : null};
  });
}

export function buildRows(entries, meals, overrides = {}) {
  return entries.map(entry => {
    const override = overrides[entry.id];
    if (!entry.confirmed || !entry.source || !hasMeal(entry.meal)
      || !['before', 'after', 'at'].includes(entry.relation) || !format(meals[entry.meal])) {
      return {...entry, allowed: false, reason: '用法或餐次待核对'};
    }
    const label = entry.relation === 'at' ? mealLabels[entry.meal] + '随餐'
      : mealLabels[entry.meal] + (entry.relation === 'before' ? '前' : '后');
    const mealTime = minutes(meals[entry.meal]);
    if (entry.relation !== 'at' && entry.offset == null) {
      if (!format(override)) return {...entry, label, needsTime: true, allowed: false, reason: '请确认提醒钟点'};
      const time = minutes(override);
      if ((entry.relation === 'after' && time <= mealTime)
        || (entry.relation === 'before' && time >= mealTime)) {
        return {...entry, label, needsTime: true, allowed: false, reason: '所选钟点与餐前后关系不符'};
      }
      return {...entry, label, needsTime: true, time: override, allowed: true};
    }
    const elapsed = entry.relation === 'at' ? 0 : entry.offset * (entry.relation === 'before' ? -1 : 1);
    const minuteOfDay = (mealTime + elapsed + 1440) % 1440;
    const time = [Math.floor(minuteOfDay / 60), minuteOfDay % 60].map(n => String(n).padStart(2, '0')).join(':');
    return {...entry, label, time, allowed: true};
  });
}

export function dueReminders(plan, now, seen) {
  const first = Math.max(plan.since, now - MAX_DELAY);
  const today = Math.floor((now + ZONE) / DAY) * DAY - ZONE;
  return plan.rows.flatMap(row => [today - DAY, today].flatMap(day => {
    const at = day + minutes(row.time) * MINUTE;
    const key = plan.since + ':' + row.id + ':' + at;
    return at > Math.max(first, row.startedAt || 0) && at <= now && !seen.has(key) ? [{...row, at, key}] : [];
  })).sort((a,b) => a.at - b.at);
}

export function nextReminder(plan, now) {
  const today = Math.floor((now + ZONE) / DAY) * DAY - ZONE;
  return plan.rows.map(row => {
    const todayAt = today + minutes(row.time) * MINUTE;
    return {...row, at: todayAt > now ? todayAt : todayAt + DAY, tomorrow: todayAt <= now};
  }).sort((a, b) => a.at - b.at)[0];
}
