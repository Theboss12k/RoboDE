import {useEffect} from 'react';

/** Only deliberate interaction keeps a cloud session awake; idle tabs do not. */
export function useCloudActivity(active:boolean,business=false) {
 useEffect(()=>{
  if(!active)return;
  let last=0;
  const activity=(event:Event)=>{
   if(!event.isTrusted||document.visibilityState!=='visible'||Date.now()-last<30000)return;
   last=Date.now();
   void fetch(business?'/api/business/session/activity':'/api/session/activity',{method:'POST',credentials:'same-origin'}).catch(()=>{});
  };
  document.addEventListener('pointerdown',activity,true);document.addEventListener('keydown',activity,true);
  return()=>{document.removeEventListener('pointerdown',activity,true);document.removeEventListener('keydown',activity,true)};
 },[active,business]);
}
