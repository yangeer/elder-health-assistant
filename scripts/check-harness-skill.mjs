import { homedir } from 'node:os';
/** Check discovery and loading with the installed official filesystem provider. */
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
const cli = process.env.DSH_CLI ?? resolve(homedir(), '.local/share/elder-dsh/node_modules/@deepseek-ai/dsh/lib/bin.js');
const require = createRequire(resolve(cli));
const { FileSystemSkillProvider } = await import(require.resolve('@deepseek-ai/dsh-skill-filesystem'));
// No virtual filesystem service: exercise the provider's actual host filesystem path.
const context = { get() { return undefined; }, logger: { warn: console.error } };
const provider = new FileSystemSkillProvider(context,
  { invalidate() {}, signal: new AbortController().signal }, { watch: false });
try {
  const observed = await provider.list({ cwd: process.cwd() });
  const candidates = Array.isArray(observed) ? observed : observed.candidates;
  const skill = candidates.find(row => row.name === 'elder-health-cards');
  assert.ok(skill, 'Project skill must be discoverable');
  assert.equal(skill.source, 'project-dsh');
  assert.equal(skill.invocation.modelInvocable, true);
  const loaded = await provider.get(skill, { cwd: process.cwd() });
  assert.ok(loaded.content.includes('references/harness-tools.md'));
  console.log(JSON.stringify({ name: skill.name, source: skill.source,
    path: skill.path, loaded: true, invocation: skill.invocation }, null, 2));
} finally {
  await provider.dispose();
}
