import {spawn} from 'node:child_process';
import {root,python,pythonEnv} from './paths.mjs';
const child=spawn(python,process.argv.slice(2),{cwd:root,env:pythonEnv,stdio:'inherit'});
child.on('error',error=>{console.error(error.message);process.exitCode=1;});
child.on('exit',code=>{process.exitCode=code??1;});
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>child.kill(signal));
