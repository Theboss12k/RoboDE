import {useEffect,useRef,useState} from 'react';
import {Copy,Eye,EyeOff,KeyRound} from 'lucide-react';
import {desktop} from './desktop';
import Feedback from './ui/Feedback';

export default function WorkspaceAccess(){
  const [code,setCode]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[note,setNote]=useState('');
  const field=useRef<HTMLInputElement>(null),mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{
    if(!code)return;
    const timer=window.setTimeout(()=>{setCode(null);setNote('Access code hidden automatically.');},60000);
    const hide=()=>{if(document.hidden){setCode(null);setNote('');}};
    document.addEventListener('visibilitychange',hide);
    return()=>{clearTimeout(timer);document.removeEventListener('visibilitychange',hide);};
  },[code]);
  const reveal=async()=>{
    setBusy(true);setError('');setNote('');
    try{
      const response=await fetch('/api/workspace/access',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',cache:'no-store'});
      let data:{access_code:string|null};
      if([404,405].includes(response.status) && desktop?.workspaceAccessCode)data=await desktop.workspaceAccessCode();
      else{
        if(!response.ok)throw new Error(response.status===401?'Sign in to this workspace to view its access code.':'Workspace access details could not be loaded.');
        data=await response.json();
      }
      if(!mounted.current)return;
      if(data.access_code)setCode(data.access_code);
      else setNote('This local workspace does not have an access code configured.');
    }catch(e){if(mounted.current)setError((e as Error).message);}
    finally{if(mounted.current)setBusy(false);}
  };
  return <section className="workspace-access config-card" aria-label="Workspace access settings">
    <div className="section-toolbar"><h3><KeyRound size={17}/> Workspace access code</h3><span className="tiny-tag">Shared team workspace</span></div>
    <p>Use this code to sign in to this server's browser IDE. Share it only with teammates who should have full access to this workspace.</p>
    <p className="inline-note">You can view it here after signing in, or from the local desktop IDE. It is hidden by default and automatically hidden after one minute or when you leave this tab.</p>
    {!code?<button className="secondary" disabled={busy} onClick={()=>void reveal()}><Eye size={15}/>{busy?'Loading…':'Show workspace access code'}</button>:<>
      <label className="field">Workspace access code<input ref={field} aria-label="Revealed workspace access code" readOnly value={code} autoComplete="off" spellCheck={false} onFocus={event=>event.target.select()}/></label>
      <div className="section-toolbar workspace-access-actions">
        <button className="primary" onClick={async()=>{try{await navigator.clipboard.writeText(code);setNote('Workspace access code copied.');}catch{field.current?.focus();field.current?.select();setNote('Copy unavailable in this browser. The code is selected; press Ctrl+C or ⌘C.');}}}><Copy size={15}/>Copy access code</button>
        <button className="secondary" onClick={()=>{setCode(null);setNote('');}}><EyeOff size={15}/>Hide access code</button>
      </div>
    </>}
    <Feedback message={error}/>{note&&<p role="status">{note}</p>}
  </section>;
}
