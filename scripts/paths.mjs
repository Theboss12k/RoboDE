import {fileURLToPath} from 'node:url';
import {resolve,delimiter} from 'node:path';
import {existsSync} from 'node:fs';
export const root=fileURLToPath(new URL('../',import.meta.url));
export const server=resolve(root,'SERVER_CLIENT/server');
if(existsSync(resolve(server,'.env')))process.loadEnvFile(resolve(server,'.env'));
export const python=process.env.ROBOT_IDE_PYTHON||resolve(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
export const pythonEnv={...process.env,PYTHONPATH:[server,root,process.env.PYTHONPATH].filter(Boolean).join(delimiter)};
export const npm=process.platform==='win32'?'npm.cmd':'npm';
