import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {server} from './paths.mjs';
try{
 const state=JSON.parse(readFileSync(resolve(server,'robot_system/runtime/server/launch.json'),'utf8'));
 const health=await (await fetch(`http://127.0.0.1:${state.runtimePort}/api/health`,{signal:AbortSignal.timeout(2000)})).json();
 if(health.instance_id!==state.instanceId)throw new Error('Saved PID does not match this runtime; refusing to stop an unrelated process.');
 if(process.argv[2]==='stop'){process.kill(state.pid,'SIGTERM');console.log('Server shutdown requested.');}
 else console.log(`Shared IDE server running: http://localhost:${state.port}`);
}catch(error){console.error('Server not running or unavailable: '+error.message);process.exitCode=1;}
