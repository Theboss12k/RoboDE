import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import {root,server,python} from './paths.mjs';
import {resolve} from 'node:path';
function run(cmd,args){const r=spawnSync(cmd,args,{cwd:root,stdio:'inherit'});if(r.status!==0)process.exit(r.status??1);}
if(!existsSync(python))run(process.platform==='win32'?'python':'python3',['-m','venv',resolve(root,'.venv')]);
run(python,['-m','pip','install','-r',resolve(server,'requirements.txt')]);
run(python,['-m','pip','install','--no-deps','-e',server]);
if(!process.argv.includes('--server'))run('node',[resolve(root,'node_modules/electron/install.js')]);
console.log('Setup complete. Browser server: npm run server:build && npm run server:start. Desktop: npm run dev.');
