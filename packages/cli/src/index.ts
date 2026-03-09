import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFile, mkdir } from 'node:fs/promises';
import { ServerManager, type ServerStatus } from '@web-vox/server';

const __dirname = dirname(fileURLToPath(import.meta.url));

function findProjectRoot(): string {
  // Walk up from CLI dist to find the project root
  // In dev: packages/cli/dist -> packages/cli -> packages -> root
  // In installed: node_modules/@web-vox/cli/dist -> ... -> root
  let dir = resolve(__dirname);
  for (let i = 0; i < 10; i++) {
    try {
      const pkg = resolve(dir, 'package.json');
      const fs = require('node:fs') as typeof import('node:fs');
      const data = JSON.parse(fs.readFileSync(pkg, 'utf-8'));
      if (data.workspaces || data.name === 'web-vox') return dir;
    } catch { /* continue */ }
    dir = resolve(dir, '..');
  }
  // Fallback: assume CWD is project root
  return process.cwd();
}

function createManager(projectRoot?: string): ServerManager {
  const root = projectRoot ?? findProjectRoot();
  return ServerManager.fromProjectRoot(root, {
    onLog: (server, line) => {
      if (process.env.WEB_VOX_VERBOSE) {
        console.log(`[${server}] ${line}`);
      }
    },
    onError: (server, err) => {
      console.error(`[${server}] ERROR: ${err.message}`);
    },
  });
}

function formatStatus(statuses: Map<string, ServerStatus>): void {
  const maxNameLen = Math.max(...Array.from(statuses.values()).map(s => s.name.length));

  for (const status of statuses.values()) {
    const name = status.name.padEnd(maxNameLen);
    const icon = status.healthy ? '\x1b[32m●\x1b[0m' : '\x1b[31m○\x1b[0m';
    const port = `port ${status.port}`;
    const pid = status.pid ? `pid ${status.pid}` : '';
    const uptime = status.uptimeMs ? `up ${formatUptime(status.uptimeMs)}` : '';
    const error = status.error ? `\x1b[31m${status.error}\x1b[0m` : '';

    const parts = [icon, name, port, pid, uptime, error].filter(Boolean);
    console.log(`  ${parts.join('  ')}`);
  }
}

function formatUptime(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ${mins % 60}m`;
}

async function commandStart(args: string[]): Promise<void> {
  const servers = args.length > 0 ? args : undefined;
  const manager = createManager();

  console.log('Starting web-vox servers...\n');
  const results = servers
    ? await (async () => {
        const map = new Map<string, ServerStatus>();
        for (const name of servers) {
          const status = await manager.start(name);
          map.set(name, status);
        }
        return map;
      })()
    : await manager.startAll();

  formatStatus(results);

  const healthy = Array.from(results.values()).filter(s => s.healthy).length;
  const total = results.size;
  console.log(`\n${healthy}/${total} servers started successfully.`);

  if (healthy > 0) {
    console.log('\nPress Ctrl+C to stop all servers.');
    process.on('SIGINT', async () => {
      console.log('\nStopping servers...');
      await manager.stopAll();
      process.exit(0);
    });
    process.on('SIGTERM', async () => {
      await manager.stopAll();
      process.exit(0);
    });
    // Keep process alive
    await new Promise(() => {});
  }
}

async function commandStop(): Promise<void> {
  // Try to find any running servers by health-checking known ports
  const manager = createManager();
  console.log('Checking for running servers...\n');
  const health = await manager.checkAllHealth();
  const running = Array.from(health.values()).filter(s => s.healthy);
  if (running.length === 0) {
    console.log('No servers are currently running.');
    return;
  }
  formatStatus(health);
  console.log(`\nNote: "stop" only affects servers started by this process.`);
  console.log('To stop external servers, use their own shutdown mechanisms.');
}

async function commandStatus(): Promise<void> {
  const manager = createManager();
  console.log('web-vox server status:\n');
  const health = await manager.checkAllHealth();
  formatStatus(health);

  const healthy = Array.from(health.values()).filter(s => s.healthy).length;
  const total = health.size;
  console.log(`\n${healthy}/${total} servers healthy.`);
}

async function commandSynth(args: string[]): Promise<void> {
  if (args.length === 0) {
    console.error('Usage: web-vox synth "text to speak" [--voice <id>] [--rate <n>] [--output <file>]');
    process.exit(1);
  }

  let text = '';
  let voice: string | undefined;
  let rate = 1.0;
  let output = 'output.wav';

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--voice' && args[i + 1]) { voice = args[++i]; }
    else if (args[i] === '--rate' && args[i + 1]) { rate = parseFloat(args[++i]); }
    else if (args[i] === '--output' && args[i + 1]) { output = args[++i]; }
    else { text += (text ? ' ' : '') + args[i]; }
  }

  if (!text) {
    console.error('No text provided.');
    process.exit(1);
  }

  // Use WebSocket transport directly (Node.js has WebSocket since v21, or use ws)
  const { WebSocketTransport, NativeBridgeEngine } = await import('@web-vox/core');
  const transport = new WebSocketTransport();
  const engine = new NativeBridgeEngine(transport);

  try {
    await engine.initialize();
  } catch {
    console.error('Cannot connect to web-vox server. Is it running? (web-vox start)');
    process.exit(1);
  }

  console.log(`Synthesizing: "${text.substring(0, 80)}${text.length > 80 ? '...' : ''}"`);
  if (voice) console.log(`Voice: ${voice}`);
  console.log(`Rate: ${rate}x`);

  const result = await engine.synthesize(text, { voice, rate });

  // Write WAV file
  const wavBuffer = encodeWav(result.samples, result.sampleRate, result.channels);
  await mkdir(dirname(resolve(output)), { recursive: true }).catch(() => {});
  await writeFile(output, wavBuffer);

  console.log(`\nSaved: ${output}`);
  console.log(`Duration: ${(result.totalDurationMs / 1000).toFixed(2)}s`);
  console.log(`Words: ${result.wordTimestamps.length}`);
  console.log(`Sample rate: ${result.sampleRate} Hz`);

  engine.dispose();
}

async function commandVoices(): Promise<void> {
  const { WebSocketTransport, NativeBridgeEngine } = await import('@web-vox/core');
  const transport = new WebSocketTransport();
  const engine = new NativeBridgeEngine(transport);

  try {
    await engine.initialize();
  } catch {
    console.error('Cannot connect to web-vox server. Is it running? (web-vox start)');
    process.exit(1);
  }

  const voices = await engine.getVoices();
  if (voices.length === 0) {
    console.log('No voices available.');
    engine.dispose();
    return;
  }

  // Group by engine
  const grouped = new Map<string, typeof voices>();
  for (const v of voices) {
    const engine = v.engine ?? 'unknown';
    if (!grouped.has(engine)) grouped.set(engine, []);
    grouped.get(engine)!.push(v);
  }

  for (const [engineName, engineVoices] of grouped) {
    console.log(`\n\x1b[1m${engineName}\x1b[0m (${engineVoices.length} voices)`);
    for (const v of engineVoices) {
      const lang = v.language ? `[${v.language}]` : '';
      const gender = v.gender ? `(${v.gender})` : '';
      console.log(`  ${v.id.padEnd(40)} ${v.name} ${lang} ${gender}`);
    }
  }

  console.log(`\nTotal: ${voices.length} voices`);
  engine.dispose();
}

function encodeWav(samples: Float32Array, sampleRate: number, channels: number): Buffer {
  const bytesPerSample = 2; // 16-bit PCM
  const dataLength = samples.length * bytesPerSample;
  const buffer = Buffer.alloc(44 + dataLength);

  // RIFF header
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + dataLength, 4);
  buffer.write('WAVE', 8);

  // fmt chunk
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);          // chunk size
  buffer.writeUInt16LE(1, 20);           // PCM format
  buffer.writeUInt16LE(channels, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * channels * bytesPerSample, 28); // byte rate
  buffer.writeUInt16LE(channels * bytesPerSample, 32);              // block align
  buffer.writeUInt16LE(16, 34);          // bits per sample

  // data chunk
  buffer.write('data', 36);
  buffer.writeUInt32LE(dataLength, 40);

  // Write PCM data
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    const int16 = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
    buffer.writeInt16LE(Math.round(int16), 44 + i * 2);
  }

  return buffer;
}

// -- Main CLI entry point --

const [command, ...args] = process.argv.slice(2);

const HELP = `
\x1b[1mweb-vox\x1b[0m — CLI for web-vox-pro intelligent reading engine

\x1b[1mUsage:\x1b[0m
  web-vox <command> [options]

\x1b[1mCommands:\x1b[0m
  start [servers...]     Start all or specific servers
  stop                   Show running server status
  status                 Health-check all servers
  synth "text"           Synthesize text to WAV file
  voices                 List available voices
  help                   Show this help message

\x1b[1mSynth Options:\x1b[0m
  --voice <id>           Voice identifier
  --rate <n>             Speech rate multiplier (default: 1.0)
  --output <file>        Output WAV file (default: output.wav)

\x1b[1mEnvironment:\x1b[0m
  WEB_VOX_VERBOSE=1      Show server log output
  WEB_VOX_ROOT=<path>    Override project root detection

\x1b[1mExamples:\x1b[0m
  web-vox start                              Start all servers
  web-vox start ws-server kokoro alignment   Start specific servers
  web-vox status                             Check server health
  web-vox synth "Hello world"                Quick synthesis
  web-vox voices                             List all voices
`;

switch (command) {
  case 'start':
    commandStart(args);
    break;
  case 'stop':
    commandStop();
    break;
  case 'status':
    commandStatus();
    break;
  case 'synth':
  case 'synthesize':
    commandSynth(args);
    break;
  case 'voices':
    commandVoices();
    break;
  case 'help':
  case '--help':
  case '-h':
  case undefined:
    console.log(HELP);
    break;
  default:
    console.error(`Unknown command: ${command}`);
    console.log(HELP);
    process.exit(1);
}
