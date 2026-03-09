/**
 * Integration tests for @web-vox/server ServerManager.
 *
 * Run with: npx tsx --test packages/server/test/server-manager.test.ts
 *
 * Prerequisites: Some services should already be running for health-check tests.
 * Tests that need specific servers will skip gracefully if unavailable.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { ServerManager } from '../src/ServerManager.js';

const PROJECT_ROOT = resolve(import.meta.dirname, '../../..');

describe('ServerManager', () => {
  describe('construction', () => {
    it('creates from project root', () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      assert.ok(mgr);
    });

    it('creates with custom options', () => {
      const mgr = new ServerManager({
        nativeBridgePath: resolve(PROJECT_ROOT, 'packages/native-bridge'),
        wsPort: 21740,
      });
      assert.ok(mgr);
    });
  });

  describe('config loading', () => {
    it('loads server_registry.json', async () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      const registry = await mgr.loadRegistry();
      assert.ok(registry.servers);
      assert.ok(registry.servers.alignment);
      assert.ok(registry.servers.quality);
      assert.ok(registry.servers.ocr);
      assert.equal(registry.servers.alignment.url, 'http://127.0.0.1:21747');
    });

    it('loads device_config.json', async () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      const config = await mgr.loadDeviceConfig();
      assert.ok(config.alignment);
      assert.equal(config.alignment.device, 'cpu');
    });
  });

  describe('health checks', () => {
    it('checks individual server health', async () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      const status = await mgr.checkHealth('alignment');
      assert.equal(status.name, 'alignment');
      assert.equal(status.port, 21747);
      assert.equal(typeof status.healthy, 'boolean');
    });

    it('checks all server health', async () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      const results = await mgr.checkAllHealth();
      assert.ok(results.size > 0);

      // Should have ws-server and all python servers
      assert.ok(results.has('ws-server'));
      assert.ok(results.has('alignment'));
      assert.ok(results.has('quality'));
      assert.ok(results.has('ocr'));

      for (const [name, status] of results) {
        assert.equal(status.name, name);
        assert.equal(typeof status.port, 'number');
        assert.equal(typeof status.healthy, 'boolean');
      }
    });

    it('returns false for non-existent server', async () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      const status = await mgr.checkHealth('nonexistent');
      assert.equal(status.healthy, false);
    });
  });

  describe('process tracking', () => {
    it('reports no running servers initially', () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      assert.deepEqual(mgr.getRunning(), []);
    });

    it('isRunning returns false for unmanaged servers', () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      assert.equal(mgr.isRunning('ws-server'), false);
      assert.equal(mgr.isRunning('alignment'), false);
    });
  });

  describe('event emitter', () => {
    it('is an EventEmitter', () => {
      const mgr = ServerManager.fromProjectRoot(PROJECT_ROOT);
      assert.equal(typeof mgr.on, 'function');
      assert.equal(typeof mgr.emit, 'function');
    });
  });
});
