import {spawn} from 'node:child_process';
import {existsSync,mkdirSync,writeFileSync,unlinkSync,readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {root,server,python,pythonEnv,npm} from './paths.mjs';
const built=process.argv.includes('--built'),web=process.argv.includes('--web'),hosted=process.argv.includes('--server');
const runtimePort=Number(process.env.ROBOT_IDE_RUNTIME_PORT||8765),port=Number(process.env.ROBOT_IDE_PORT||8081);
if(!Number.isInteger(runtimePort)||runtimePort<1024||runtimePort>65535||!Number.isInteger(port)||port<1024||port>65535)throw new Error('Use ports between 1024 and 65535');
const upstream=`http://127.0.0.1:${runtimePort}`;
if(!existsSync(python))throw new Error('Run npm run setup:server (browser server) or npm run setup (Electron) first.');
if(built&&!existsSync(resolve(root,'SERVER_CLIENT/client/dist/index.html')))throw new Error('Run npm run server:build first.');
const children=[];let stopping=false;
const instanceId=randomUUID();
const directory=resolve(server,'robot_system/runtime/server'),statePath=resolve(directory,'launch.json');
function stop(code=0){
 if(stopping)return;stopping=true;
 for(const child of children)child.kill('SIGTERM');
 const deadline=setTimeout(()=>{for(const child of children)if(child.exitCode===null)child.kill('SIGKILL');process.exit(code);},65000);
 Promise.all(children.map(child=>child.exitCode!==null?Promise.resolve():new Promise(r=>child.once('exit',r)))).then(()=>{clearTimeout(deadline);if(hosted)try{if(JSON.parse(readFileSync(statePath,'utf8')).instanceId===instanceId)unlinkSync(statePath);}catch{}process.exit(code);});
}
function start(command,args,options={}){
 const child=spawn(command,args,{cwd:root,stdio:'inherit',env:{...pythonEnv,ROBOT_IDE_UPSTREAM:upstream,ROBOT_IDE_INSTANCE_ID:instanceId},shell:process.platform==='win32'&&command===npm,...options});
 children.push(child);child.on('error',e=>{console.error(e.message);stop(1);});child.on('exit',code=>{if(!stopping)stop(code??0);});return child;
}
async function ready(url){
 const deadline=Date.now()+30000;
 while(Date.now()<deadline&&!stopping){try{if((await fetch(url,{signal:AbortSignal.timeout(1000)})).ok)return;}catch{}await new Promise(r=>setTimeout(r,250));}
 throw new Error('Service did not start: '+url);
}
process.on('SIGINT',()=>stop());process.on('SIGTERM',()=>stop());
try{
 let occupied=false;try{await fetch(upstream+'/api/health',{signal:AbortSignal.timeout(700)});occupied=true;}catch{}
 if(occupied)throw new Error(`Port ${runtimePort} is in use. Stop that runtime before launching another: projects and robot ownership must have one server authority.`);
 start(python,['-m','uvicorn','services.api.main:app','--host','127.0.0.1','--port',String(runtimePort),'--workers','1']);
 await ready(upstream+'/api/health');
 if(hosted){
  start(python,['-m','web.serve','--host',process.env.ROBOT_IDE_HOST||'0.0.0.0','--port',String(port)]);
  await ready(`http://127.0.0.1:${port}/login`);
  mkdirSync(directory,{recursive:true,mode:0o700});writeFileSync(statePath,JSON.stringify({pid:process.pid,instanceId,runtimePort,port,host:process.env.ROBOT_IDE_HOST||'0.0.0.0'},null,2),{mode:0o600});
  console.log(`Shared React IDE ready on port ${port}. Open http://SERVER_IP:${port} from another computer. Calculations run on this server.`);
 }else{
  if(!built){start(npm,['run','dev','--workspace','SERVER_CLIENT/client']);await ready('http://127.0.0.1:5173');}
  if(web)console.log('Robot IDE development UI: http://127.0.0.1:5173');
  else start(npm,['run','electron','--workspace','ELECTRON_APP'],{env:{...pythonEnv,ROBOT_IDE_DEV:built?'0':'1',ROBOT_IDE_ORIGIN:built?upstream:'http://127.0.0.1:5173'}});
 }
}catch(error){console.error(error.message);stop(1);}
