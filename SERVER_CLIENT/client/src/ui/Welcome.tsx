import {useEffect, useRef, useState, type ReactNode} from 'react';
import RobotLogo from '../branding/RobotLogo';
import './welcome.css';

/** Per-document welcome: desktop launch and every browser reload, never workspace navigation. */
export default function Welcome({children, business = false}: {children: ReactNode; business?: boolean}) {
  const [phase, setPhase] = useState<'hello' | 'leaving' | 'done'>('hello');
  const continueButton = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => {
    continueButton.current?.focus({preventScroll: true});
    const timer = window.setTimeout(() => setPhase('leaving'), 1800);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    if (phase !== 'leaving') return;
    const timer = window.setTimeout(() => {
      setPhase('done');
    }, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 320);
    return () => window.clearTimeout(timer);
  }, [phase]);
  useEffect(() => {
    if (phase === 'done') content.current?.focus({preventScroll: true});
  }, [phase]);
  return <>
    <div className="welcome-content" ref={content} tabIndex={-1} inert={phase !== 'done'}>{children}</div>
    {phase !== 'done' && <div className={`welcome-screen welcome-${phase}`} role="dialog" aria-modal="true" aria-labelledby="welcome-title" aria-describedby="welcome-description"
      onKeyDown={event => {
        if (event.key === 'Escape' || event.key === 'Enter') { event.preventDefault(); setPhase('leaving'); }
        if (event.key === 'Tab') { event.preventDefault(); continueButton.current?.focus(); }
      }}>
      <div className="welcome-glow" aria-hidden="true" />
      <div className="welcome-card">
        <div className="welcome-logo"><RobotLogo /></div>
        <span className="welcome-product">{business ? 'RoboDE Workspace' : 'RoboDE'}</span>
        <h1 id="welcome-title" aria-label="Hello.">Hello<span aria-hidden="true">.</span></h1>
        <p id="welcome-description">Plan, control and command your robot.</p>
        <button ref={continueButton} className="welcome-continue" onClick={() => setPhase('leaving')}>Continue <span aria-hidden="true">→</span></button>
      </div>
      <span className="welcome-caption">{business ? 'See your space. Make things happen.' : 'Robots · Environments · Plans'}</span>
    </div>}
  </>;
}
