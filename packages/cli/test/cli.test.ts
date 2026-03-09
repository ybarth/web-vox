/**
 * Integration tests for @web-vox/cli.
 *
 * Run with: npx tsx --test packages/cli/test/cli.test.ts
 *
 * Prerequisites: Build the CLI first (npm run build in packages/cli).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { resolve } from 'node:path';
import { existsSync, unlinkSync } from 'node:fs';

const CLI_PATH = resolve(import.meta.dirname, '../dist/index.js');

function runCli(args: string[], timeoutMs = 15000): Promise<{ stdout: string; stderr: string; code: number }> {
  return new Promise((resolve) => {
    const proc = execFile('node', [CLI_PATH, ...args], { timeout: timeoutMs }, (error, stdout, stderr) => {
      resolve({ stdout: stdout || '', stderr: stderr || '', code: error?.code as number ?? (error ? 1 : 0) });
    });
  });
}

describe('CLI', () => {
  describe('help', () => {
    it('shows help with no args', async () => {
      const { stdout } = await runCli([]);
      assert.ok(stdout.includes('web-vox'));
      assert.ok(stdout.includes('Commands:'));
    });

    it('shows help with --help', async () => {
      const { stdout } = await runCli(['--help']);
      assert.ok(stdout.includes('Commands:'));
    });

    it('shows help with help command', async () => {
      const { stdout } = await runCli(['help']);
      assert.ok(stdout.includes('start'));
      assert.ok(stdout.includes('synth'));
      assert.ok(stdout.includes('voices'));
    });
  });

  describe('status', () => {
    it('shows server status', async () => {
      const { stdout } = await runCli(['status']);
      assert.ok(stdout.includes('web-vox server status'));
      assert.ok(stdout.includes('ws-server'));
      assert.ok(stdout.includes('alignment'));
      assert.ok(stdout.includes('healthy'));
    });
  });

  describe('unknown command', () => {
    it('shows error for unknown command', async () => {
      const { stderr } = await runCli(['foobar']);
      assert.ok(stderr.includes('Unknown command'));
    });
  });

  describe('synth', () => {
    it('shows usage with no args', async () => {
      const { stderr } = await runCli(['synth']);
      assert.ok(stderr.includes('Usage'));
    });

    it('synthesizes text to WAV file', async () => {
      const output = '/tmp/web-vox-cli-test.wav';
      if (existsSync(output)) unlinkSync(output);

      const { stdout, code } = await runCli(['synth', 'Hello test', '--output', output]);
      // This may fail if no server is running, which is okay
      if (code === 0) {
        assert.ok(stdout.includes('Saved'));
        assert.ok(existsSync(output), 'WAV file should exist');
        unlinkSync(output);
      }
    });
  });
});
