// Static copy of what serve.mjs serves, for GitHub Pages or any static host: node scripts/build_site.mjs [out=_site]
import {cpSync, rmSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {routes} from './serve.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const out = resolve(process.argv[2] ?? '_site');
rmSync(out, {recursive: true, force: true});
for (const [path, [file]] of routes) if (path !== '/') cpSync(resolve(root, file), resolve(out, '.' + path));
console.log(`${routes.size - 1} files -> ${out}`);
