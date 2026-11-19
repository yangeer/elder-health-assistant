import { execFile } from 'node:child_process';
import { lstat } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);
const markerPattern = /^\[\[elder-health-audio:([a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12})\]\]$/;
const maximumDelayMs = 5000;

export const name = 'elder-audio-reminders';
export const inject = ['schedule'];

export async function playWav(file) {
  const options = { timeout: 65000, windowsHide: true };
  if (process.platform === 'win32' || process.env.WSL_DISTRO_NAME) {
    const path = process.platform === 'win32'
      ? file
      : (await run('wslpath', ['-w', file], { timeout: 5000 })).stdout.trim();
    const encodedPath = Buffer.from(path, 'utf8').toString('base64');
    const script = "$ErrorActionPreference = 'Stop'; " +
      `$file = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${encodedPath}')); ` +
      '$player = New-Object System.Media.SoundPlayer($file); ' +
      'try { $player.Load(); $player.PlaySync() } finally { $player.Dispose() }';
    const command = Buffer.from(script, 'utf16le').toString('base64');
    await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-EncodedCommand', command], options);
    return;
  }
  try {
    await run('paplay', [file], options);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    await run('aplay', ['-q', file], options);
  }
}

export function apply(ctx) {
  const directory = join(process.cwd(), 'outputs', 'harness', 'reminder-audio');
  const startedAt = Date.now();
  const played = new Map();
  let observed = new Map();
  let stopped = false;
  let polling = false;

  async function scan() {
    if (stopped || polling) return;
    polling = true;
    try {
      const tasks = await ctx.schedule.entries();
      const now = Date.now();
      for (const [id, time] of played) {
        if (now - time > maximumDelayMs) played.delete(id);
      }
      for (const task of tasks) {
        if (stopped) return;
        if (task.status === 'paused') continue;
        const marker = markerPattern.exec(task.prompt.split('\n', 1)[0]);
        if (!marker) continue;
        // A task may advance before this poll. Its receipt carries the previous
        // occurrence. Manual runs may have a different time and only a matching
        // observed occurrence is eligible.
        const scheduled = Date.parse(task.scheduledAt);
        const previous = Date.parse(task.lastDelivery?.scheduledAt);
        const candidate = task.status === 'active' && scheduled <= now
          ? scheduled : previous;
        if (!Number.isFinite(candidate) || candidate < startedAt ||
            candidate > now || now - candidate > maximumDelayMs ||
            played.get(task.id) === candidate) continue;
        // Run-now writes a receipt for the manual invocation time. The scheduled
        // record is tracked below so an unrelated receipt can never play audio.
        if (candidate !== scheduled && observed.get(task.id) !== candidate) continue;
        if (candidate === scheduled && task.status !== 'active' && observed.get(task.id) !== candidate) continue;
        played.set(task.id, candidate);
        const file = join(directory, marker[1] + '.wav');
        void lstat(file).then(async (stat) => {
          if (!stat.isFile()) throw new Error('Expected a regular WAV file');
          if (stopped) return;
          await playWav(file);
          if (!stopped) console.info(`elder-audio: played task ${task.id}`);
        }).catch((error) => {
          ctx.logger.warn(`elder-audio: playback failed for ${task.id} (${error.code ?? error.name})`);
        });
      }
      observed = new Map(tasks.filter((task) => task.status === 'active')
        .map((task) => [task.id, Date.parse(task.scheduledAt)]));
    } catch (error) {
      if (!stopped) ctx.logger.warn(`elder-audio: could not read schedule (${error.name})`);
    } finally {
      polling = false;
    }
  }

  ctx.effect(() => {
    const dispose = ctx.on('schedule/changed', () => { void scan(); });
    const timer = setInterval(() => { void scan(); }, 250);
    console.info('elder-audio: ready');
    void scan();
    return () => {
      stopped = true;
      clearInterval(timer);
      dispose();
    };
  });
}
