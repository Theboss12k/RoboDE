import { useEffect } from "react";

/** Keep nested setup dialogs keyboard-contained and return focus to their opener. */
export function useDialogAccessibility() {
  useEffect(() => {
    let current: HTMLElement | null = null;
    let frame = 0;
    const openers = new WeakMap<HTMLElement, HTMLElement>();
    let lastFocused=document.activeElement instanceof HTMLElement ? document.activeElement : document.body;
    const focus=(event: FocusEvent)=>{
      if(!(event.target instanceof HTMLElement))return;
      const dialog=event.target.closest<HTMLElement>('.ide-v3 [role="dialog"][aria-modal="true"]');
      if(dialog && !openers.has(dialog))openers.set(dialog,lastFocused);
      lastFocused=event.target;
    };
    document.addEventListener('focusin',focus);
    const visible = (el: HTMLElement) => !!el.getClientRects().length && !el.closest('[hidden],[inert]');
    const controls = (dialog: HTMLElement) => Array.from(dialog.querySelectorAll<HTMLElement>(
      'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"],summary',
    )).filter(el => visible(el) && el.tabIndex >= 0);
    const sync = () => {
      const dialogs=Array.from(document.querySelectorAll<HTMLElement>('.ide-v3 [role="dialog"][aria-modal="true"]')).filter(visible);
      const next=dialogs.at(-1) ?? null;
      if(next===current)return;
      const previous=current;
      if(previous && !previous.isConnected) {
        const opener=openers.get(previous);
        if(opener?.isConnected && (!next || next.contains(opener)))opener.focus({preventScroll:true});
      }
      current=next;
      if(next) {
        if(!openers.has(next) && document.activeElement instanceof HTMLElement)openers.set(next,document.activeElement);
        if(!next.contains(document.activeElement))controls(next)[0]?.focus({preventScroll:true});
      }
    };
    const observer=new MutationObserver(()=>{
      cancelAnimationFrame(frame);frame=requestAnimationFrame(sync);
    });
    observer.observe(document.body,{childList:true,subtree:true});
    const key=(event: KeyboardEvent)=>{
      sync();
      if(!current || event.defaultPrevented)return;
      if(event.key==='Escape') {
        const close=current.querySelector<HTMLButtonElement>('button[aria-label^="Close"]:not(:disabled)');
        if(close){event.preventDefault();event.stopPropagation();close.click();}
      }
      if(event.key==='Tab') {
        const items=controls(current),first=items[0],last=items.at(-1);
        if(!first){event.preventDefault();return;}
        if(!current.contains(document.activeElement) || (event.shiftKey && document.activeElement===first)){
          event.preventDefault();(event.shiftKey?last:first)?.focus();
        }else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
      }
    };
    document.addEventListener('keydown',key);
    return()=>{observer.disconnect();cancelAnimationFrame(frame);document.removeEventListener('keydown',key);document.removeEventListener('focusin',focus);};
  },[]);
}
