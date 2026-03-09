import { spawn, type ChildProcess } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { EventEmitter } from 'node:events';
import http from 'node:http';

export interface ServerDef {
  name: string;
  type: 'rust' | 'python';
  command: string;
  args: string[];
  port: number;
  healthEndpoint: string;
  cwd?: string;
}

export interface ServerStatus {
  name: string;
  port: number;
  healthy: boolean;
  pid?: number;
  uptimeMs?: number;
  error?: string;
}

export interface ServerRegistry {
  servers: Record<string, { mode: string; url: string }>;
}

export interface DeviceConfig {
  [key: string]: { device: string; [k: string]: unknown };
}

export interface ServerManagerOptions {
  /** Path to the native-bridge package directory */
  nativeBridgePath: string;
  /** Path to the Python virtual environment (default: <nativeBridgePath>/../../tts-venv) */
  venvPath?: string;
  /** Path to the Rust binary (default: auto-detected from cargo target) */
  rustBinaryPath?: string;
  /** WebSocket server port (default: 21740) */
  wsPort?: number;
  /** Only start these servers (by name). If omitted, starts all. */
  servers?: string[];
  /** Log output handler */
  onLog?: (server: string, line: string) => void;
  /** Error handler */
  onError?: (server: string, error: Error) => void;
}

const PYTHON_SERVERS: ServerDef[] = [
  { name: 'kokoro', type: 'python', command: 'kokoro_server.py', args: [], port: 21742, healthEndpoint: '/health' },
  { name: 'chatterbox', type: 'python', command: 'chatterbox_server.py', args: [], port: 21741, healthEndpoint: '/health' },
  { name: 'coqui', type: 'python', command: 'coqui.py', args: [], port: 21743, healthEndpoint: '/health' },
  { name: 'qwen', type: 'python', command: 'qwen_tts_server.py', args: [], port: 21744, healthEndpoint: '/health' },
  { name: 'coqui_xtts', type: 'python', command: 'coqui_xtts_server.py', args: [], port: 21745, healthEndpoint: '/health' },
  { name: 'qwen_clone', type: 'python', command: 'qwen_tts_clone_server.py', args: [], port: 21746, healthEndpoint: '/health' },
  { name: 'alignment', type: 'python', command: 'alignment_server.py', args: [], port: 21747, healthEndpoint: '/health' },
  { name: 'quality', type: 'python', command: 'quality_server.py', args: [], port: 21748, healthEndpoint: '/health' },
  { name: 'document_analyzer', type: 'python', command: 'document_analyzer_server.py', args: [], port: 21750, healthEndpoint: '/health' },
  { name: 'ocr', type: 'python', command: 'ocr_server.py', args: [], port: 21751, healthEndpoint: '/health' },
];

export class ServerManager extends EventEmitter {
  private processes = new Map<string, { proc: ChildProcess; startedAt: number }>();
  private options: Required<Omit<ServerManagerOptions, 'servers' | 'onLog' | 'onError'>> & Pick<ServerManagerOptions, 'servers' | 'onLog' | 'onError'>;

  constructor(options: ServerManagerOptions) {
    super();
    const nativeBridgePath = resolve(options.nativeBridgePath);
    this.options = {
      nativeBridgePath,
      venvPath: options.venvPath ?? resolve(nativeBridgePath, '../../tts-venv'),
      rustBinaryPath: options.rustBinaryPath ?? '',
      wsPort: options.wsPort ?? 21740,
      servers: options.servers,
      onLog: options.onLog,
      onError: options.onError,
    };
  }

  /** Auto-detect the project root from a @web-vox/server install location */
  static fromProjectRoot(projectRoot: string, options?: Partial<ServerManagerOptions>): ServerManager {
    return new ServerManager({
      nativeBridgePath: join(projectRoot, 'packages/native-bridge'),
      ...options,
    });
  }

  /** Get the Rust binary path, searching common locations */
  private async getRustBinaryPath(): Promise<string> {
    if (this.options.rustBinaryPath) return this.options.rustBinaryPath;

    const projectRoot = resolve(this.options.nativeBridgePath, '../..');
    const candidates = [
      join(projectRoot, 'target/release/web-vox-server'),
      join(projectRoot, 'target/debug/web-vox-server'),
    ];
    for (const candidate of candidates) {
      try {
        const { stat } = await import('node:fs/promises');
        await stat(candidate);
        return candidate;
      } catch { /* continue */ }
    }
    throw new Error(
      'Rust binary not found. Build it with: cargo build --release\n'
      + `Searched: ${candidates.join(', ')}`
    );
  }

  /** Get the Python interpreter from the venv */
  private getPythonPath(): string {
    return join(this.options.venvPath, 'bin/python');
  }

  /** Load server_registry.json */
  async loadRegistry(): Promise<ServerRegistry> {
    const registryPath = join(this.options.nativeBridgePath, 'server_registry.json');
    const data = await readFile(registryPath, 'utf-8');
    return JSON.parse(data) as ServerRegistry;
  }

  /** Load device_config.json */
  async loadDeviceConfig(): Promise<DeviceConfig> {
    const configPath = join(this.options.nativeBridgePath, 'device_config.json');
    const data = await readFile(configPath, 'utf-8');
    return JSON.parse(data) as DeviceConfig;
  }

  /** Get the list of server definitions to manage, filtered by options.servers */
  private getServerDefs(): ServerDef[] {
    const wsServer: ServerDef = {
      name: 'ws-server',
      type: 'rust',
      command: '', // resolved dynamically
      args: [],
      port: this.options.wsPort,
      healthEndpoint: '', // WebSocket, not HTTP
    };

    const allDefs = [wsServer, ...PYTHON_SERVERS];
    if (this.options.servers) {
      return allDefs.filter(d => this.options.servers!.includes(d.name));
    }
    return allDefs;
  }

  /** Start all configured servers */
  async startAll(): Promise<Map<string, ServerStatus>> {
    const defs = this.getServerDefs();
    const results = new Map<string, ServerStatus>();

    // Start the WS server first (other servers depend on it for discovery)
    const wsDef = defs.find(d => d.name === 'ws-server');
    if (wsDef) {
      const status = await this.startRustServer(wsDef);
      results.set('ws-server', status);
    }

    // Start Python servers in parallel
    const pythonDefs = defs.filter(d => d.type === 'python');
    const pythonResults = await Promise.allSettled(
      pythonDefs.map(d => this.startPythonServer(d))
    );

    pythonDefs.forEach((def, i) => {
      const result = pythonResults[i];
      if (result.status === 'fulfilled') {
        results.set(def.name, result.value);
      } else {
        results.set(def.name, {
          name: def.name,
          port: def.port,
          healthy: false,
          error: result.reason?.message ?? 'Failed to start',
        });
      }
    });

    return results;
  }

  /** Start a specific server by name */
  async start(name: string): Promise<ServerStatus> {
    if (name === 'ws-server') {
      const def: ServerDef = {
        name: 'ws-server',
        type: 'rust',
        command: '',
        args: [],
        port: this.options.wsPort,
        healthEndpoint: '',
      };
      return this.startRustServer(def);
    }

    const def = PYTHON_SERVERS.find(d => d.name === name);
    if (!def) throw new Error(`Unknown server: ${name}`);
    return this.startPythonServer(def);
  }

  /** Stop a specific server */
  async stop(name: string): Promise<void> {
    const entry = this.processes.get(name);
    if (!entry) return;
    entry.proc.kill('SIGTERM');
    // Wait up to 5s for graceful shutdown
    await new Promise<void>(resolve => {
      const timer = setTimeout(() => {
        entry.proc.kill('SIGKILL');
        resolve();
      }, 5000);
      entry.proc.on('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
    this.processes.delete(name);
  }

  /** Stop all servers */
  async stopAll(): Promise<void> {
    const names = Array.from(this.processes.keys());
    // Stop Python servers first, then the WS server
    const pythonNames = names.filter(n => n !== 'ws-server');
    await Promise.all(pythonNames.map(n => this.stop(n)));
    if (this.processes.has('ws-server')) {
      await this.stop('ws-server');
    }
  }

  /** Restart a specific server */
  async restart(name: string): Promise<ServerStatus> {
    await this.stop(name);
    return this.start(name);
  }

  /** Health-check a single HTTP server */
  async checkHealth(name: string): Promise<ServerStatus> {
    const def = PYTHON_SERVERS.find(d => d.name === name);
    if (!def && name !== 'ws-server') {
      return { name, port: 0, healthy: false, error: 'Unknown server' };
    }

    const port = def?.port ?? this.options.wsPort;
    const entry = this.processes.get(name);

    if (name === 'ws-server') {
      // Check WebSocket availability
      const healthy = await this.probeWebSocket(port);
      return {
        name,
        port,
        healthy,
        pid: entry?.proc.pid,
        uptimeMs: entry ? Date.now() - entry.startedAt : undefined,
      };
    }

    const healthy = await this.probeHttp(port, def!.healthEndpoint);
    return {
      name,
      port,
      healthy,
      pid: entry?.proc.pid,
      uptimeMs: entry ? Date.now() - entry.startedAt : undefined,
    };
  }

  /** Health-check all configured servers */
  async checkAllHealth(): Promise<Map<string, ServerStatus>> {
    const defs = this.getServerDefs();
    const results = new Map<string, ServerStatus>();
    const checks = await Promise.allSettled(
      defs.map(d => this.checkHealth(d.name))
    );
    defs.forEach((def, i) => {
      const result = checks[i];
      if (result.status === 'fulfilled') {
        results.set(def.name, result.value);
      } else {
        results.set(def.name, { name: def.name, port: def.port, healthy: false, error: result.reason?.message });
      }
    });
    return results;
  }

  /** Get list of running server names */
  getRunning(): string[] {
    return Array.from(this.processes.keys());
  }

  /** Check if a server is running (has a managed process) */
  isRunning(name: string): boolean {
    return this.processes.has(name);
  }

  private async startRustServer(def: ServerDef): Promise<ServerStatus> {
    if (this.processes.has(def.name)) {
      return this.checkHealth(def.name);
    }

    const binaryPath = await this.getRustBinaryPath();
    const proc = spawn(binaryPath, [], {
      cwd: this.options.nativeBridgePath,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env },
    });

    this.wireProcessOutput(def.name, proc);
    this.processes.set(def.name, { proc, startedAt: Date.now() });

    // Wait for WebSocket to become available
    const healthy = await this.waitForWebSocket(def.port, 15000);
    return {
      name: def.name,
      port: def.port,
      healthy,
      pid: proc.pid,
      error: healthy ? undefined : 'Timed out waiting for WebSocket server',
    };
  }

  private async startPythonServer(def: ServerDef): Promise<ServerStatus> {
    if (this.processes.has(def.name)) {
      return this.checkHealth(def.name);
    }

    const pythonPath = this.getPythonPath();
    const scriptPath = join(this.options.nativeBridgePath, def.command);
    const proc = spawn(pythonPath, [scriptPath, ...def.args], {
      cwd: this.options.nativeBridgePath,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env },
    });

    this.wireProcessOutput(def.name, proc);
    this.processes.set(def.name, { proc, startedAt: Date.now() });

    // Wait for HTTP health endpoint
    const healthy = await this.waitForHttp(def.port, def.healthEndpoint, 30000);
    return {
      name: def.name,
      port: def.port,
      healthy,
      pid: proc.pid,
      error: healthy ? undefined : `Timed out waiting for ${def.name} on port ${def.port}`,
    };
  }

  private wireProcessOutput(name: string, proc: ChildProcess): void {
    proc.stdout?.on('data', (data: Buffer) => {
      const line = data.toString().trim();
      if (line) {
        this.options.onLog?.(name, line);
        this.emit('log', name, line);
      }
    });

    proc.stderr?.on('data', (data: Buffer) => {
      const line = data.toString().trim();
      if (line) {
        this.options.onLog?.(name, `[stderr] ${line}`);
        this.emit('log', name, `[stderr] ${line}`);
      }
    });

    proc.on('exit', (code, signal) => {
      this.processes.delete(name);
      const msg = `Server ${name} exited (code=${code}, signal=${signal})`;
      this.options.onLog?.(name, msg);
      this.emit('exit', name, code, signal);
    });

    proc.on('error', (err) => {
      this.options.onError?.(name, err);
      this.emit('error', name, err);
    });
  }

  private probeHttp(port: number, path: string): Promise<boolean> {
    return new Promise(resolve => {
      const req = http.get({ hostname: '127.0.0.1', port, path, timeout: 3000 }, (res) => {
        resolve(res.statusCode === 200);
        res.resume();
      });
      req.on('error', () => resolve(false));
      req.on('timeout', () => { req.destroy(); resolve(false); });
    });
  }

  private probeWebSocket(port: number): Promise<boolean> {
    return new Promise(resolve => {
      // Use an HTTP request to the port — the WS server will reject it but we'll know it's up
      const req = http.get({ hostname: '127.0.0.1', port, path: '/', timeout: 2000 }, (res) => {
        res.resume();
        resolve(true);
      });
      req.on('error', (err: NodeJS.ErrnoException) => {
        // ECONNREFUSED means nothing is listening; other errors mean something is
        resolve(err.code !== 'ECONNREFUSED');
      });
      req.on('timeout', () => { req.destroy(); resolve(false); });
    });
  }

  private async waitForHttp(port: number, path: string, timeoutMs: number): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await this.probeHttp(port, path)) return true;
      await new Promise(r => setTimeout(r, 500));
    }
    return false;
  }

  private async waitForWebSocket(port: number, timeoutMs: number): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await this.probeWebSocket(port)) return true;
      await new Promise(r => setTimeout(r, 500));
    }
    return false;
  }
}
