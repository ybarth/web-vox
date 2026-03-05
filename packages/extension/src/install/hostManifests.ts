/**
 * Generate per-browser native messaging host manifests.
 * Used during installation to register the native host binary.
 */

import { platform, homedir } from 'os';
import { join } from 'path';

interface HostManifest {
  name: string;
  description: string;
  path: string;
  type: 'stdio';
  allowed_origins?: string[];
  allowed_extensions?: string[];
}

const HOST_NAME = 'com.webvox.native_host';

export function generateChromeManifest(binaryPath: string, extensionId: string): HostManifest {
  return {
    name: HOST_NAME,
    description: 'Web Vox native TTS bridge',
    path: binaryPath,
    type: 'stdio',
    allowed_origins: [`chrome-extension://${extensionId}/`],
  };
}

export function generateFirefoxManifest(binaryPath: string, extensionId: string): HostManifest {
  return {
    name: HOST_NAME,
    description: 'Web Vox native TTS bridge',
    path: binaryPath,
    type: 'stdio',
    allowed_extensions: [extensionId],
  };
}

export function getManifestInstallPath(browser: 'chrome' | 'firefox' | 'edge'): string {
  const home = homedir();
  const os = platform();

  switch (browser) {
    case 'chrome':
      if (os === 'darwin') return join(home, 'Library/Application Support/Google/Chrome/NativeMessagingHosts');
      if (os === 'linux') return join(home, '.config/google-chrome/NativeMessagingHosts');
      return join(home, 'AppData/Local/Google/Chrome/User Data/NativeMessagingHosts');
    case 'firefox':
      if (os === 'darwin') return join(home, 'Library/Application Support/Mozilla/NativeMessagingHosts');
      if (os === 'linux') return join(home, '.mozilla/native-messaging-hosts');
      return join(home, 'AppData/Local/Mozilla/NativeMessagingHosts');
    case 'edge':
      if (os === 'darwin') return join(home, 'Library/Application Support/Microsoft Edge/NativeMessagingHosts');
      if (os === 'linux') return join(home, '.config/microsoft-edge/NativeMessagingHosts');
      return join(home, 'AppData/Local/Microsoft/Edge/User Data/NativeMessagingHosts');
  }
}
