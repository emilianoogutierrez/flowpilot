import { execFileSync } from 'node:child_process';
import { cpSync, mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
rmSync(resolve(root, 'web/dist'), { recursive: true, force: true });
mkdirSync(resolve(root, 'web/dist/assets'), { recursive: true });
execFileSync(process.execPath, [resolve(root, 'node_modules/typescript/bin/tsc'), '-p', 'web/tsconfig.json'], { cwd: root, stdio: 'inherit' });
cpSync(resolve(root, 'web/public'), resolve(root, 'web/dist'), { recursive: true });
console.log('Console built. No runtime packages or external CDN resources are required.');

