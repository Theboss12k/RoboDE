import {useEffect,useRef,useState} from 'react';
import {Download,X} from 'lucide-react';
interface InstallPrompt extends Event {prompt:()=>Promise<void>;userChoice:Promise<{outcome:string}>}
export default function InstallApp(){
  const [open,setOpen]=useState(false),[prompt,setPrompt]=useState<InstallPrompt|null>(null),[message,setMessage]=useState('');
  const dialog=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!open)return;
    const opener=document.activeElement as HTMLElement|null;
    dialog.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();setOpen(false)}
      if(event.key==='Tab'){
        const items=dialog.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
        if(!items?.length)return;
        const first=items[0],last=items[items.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
      }
    };
    document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('keydown',key);opener?.focus()};
  },[open]);
  useEffect(()=>{
    const available=(event:Event)=>{event.preventDefault();setPrompt(event as InstallPrompt)};
    const installed=()=>{setPrompt(null);setMessage('RoboDE Business is installed on this device.')};
    window.addEventListener('beforeinstallprompt',available);window.addEventListener('appinstalled',installed);
    return()=>{window.removeEventListener('beforeinstallprompt',available);window.removeEventListener('appinstalled',installed)};
  },[]);
  async function install(){
    const event=prompt;if(!event)return;
    try{await event.prompt();const choice=await event.userChoice;setMessage(choice.outcome==='accepted'?'Installation requested. Follow your browser’s confirmation.':'Installation cancelled. You can try again from the browser menu.');setPrompt(null)}
    catch{setMessage('Use your browser’s Install app or Add to Home Screen command.');setPrompt(null)}
  }
  return <>
    <button aria-label="Install Business App" onClick={()=>setOpen(true)}><Download size={18}/><span>Install app</span></button>
    {open&&<div className="install-overlay" onClick={e=>{if(e.target===e.currentTarget)setOpen(false)}}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="install-title" className="install-dialog" tabIndex={-1}>
        <div className="install-heading"><h2 id="install-title">Install RoboDE Business</h2><button aria-label="Close install instructions" onClick={()=>setOpen(false)}><X size={20}/></button></div>
        <p>Keep your workspace on your Home Screen or in its own app window.</p>
        {prompt&&<button onClick={()=>void install()}><Download size={18}/>Install on this device</button>}
        <ul><li><strong>Android:</strong> Chrome menu → Install app or Add to Home screen.</li><li><strong>iPhone / iPad:</strong> Safari Share → Add to Home Screen.</li><li><strong>Desktop:</strong> Chrome or Edge menu → Install app. In macOS Safari, File → Add to Dock.</li></ul>
        <p className="install-note">Your RoboDE server must be running for workspace commands. Use HTTPS for phone camera and voice. Offline room capture can be exported and uploaded manually to the IDE.</p>
        {message&&<p role="status">{message}</p>}
        <button onClick={()=>setOpen(false)}>Done</button>
      </div>
    </div>}
  </>;
}
