import { useEffect, useState } from 'react';
import { Circle, Square, Download, RefreshCw, Video } from 'lucide-react';
import NvidiaLogo from './branding/NvidiaLogo';
import { api, post } from './api';

type Recording = {
  id: string; status: 'recording'|'finalizing'|'ready'|'failed'|'interrupted';
  created_at: string; frames: number; duplicated_frames: number;
  duration_seconds?: number; byte_length?: number; error?: string; cached?: boolean;
  settings: {resolution: string; fps: number; duration_seconds: number};
};
type Capability = {available: boolean; reason?: string};
const active = (r: Recording) => r.status === 'recording' || r.status === 'finalizing';

export default function SceneRecordingPanel({projectId, connected, onActiveChange}: {
  projectId: string; connected: boolean; onActiveChange: (active: boolean) => void;
}) {
  const base = `/projects/${encodeURIComponent(projectId)}/recordings`;
  const [records, setRecords] = useState<Recording[]>([]);
  const [capability, setCapability] = useState<Capability>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [resolution, setResolution] = useState('1280x720');
  const [fps, setFps] = useState(15);
  const [duration, setDuration] = useState(60);
  const [position, setPosition] = useState([2, 2, 1.5]);
  const [lookAt, setLookAt] = useState([0, .5, .3]);
  const current = records.find(active);
  useEffect(() => { onActiveChange(!!current); }, [!!current, onActiveChange]);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    setCapability(undefined); setRecords([]); setError('');
    const update = async () => {
      try {
        const [list, available] = await Promise.all([
          api<Recording[]>(base), api<Capability>(base+'/capabilities'),
        ]);
        if (!disposed) {setRecords(list); setCapability(available);}
      } catch (e) { if (!disposed) setError((e as Error).message); }
      if (!disposed) timer = setTimeout(update, 1500);
    };
    void update();
    return () => {disposed = true; clearTimeout(timer);};
  }, [base, connected]);
  const run = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try {await operation(); setRecords(await api<Recording[]>(base));}
    catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  };
  const downloadVideo = async (record: Recording) => {
    const response = await fetch(`/api${base}/${record.id}/file`);
    if (!response.ok) {
      const data = await response.json().catch(()=>({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Video download failed; sign in again or recover the worker history.');
    }
    if (!response.headers.get('content-type')?.startsWith('video/mp4')) throw new Error('The server did not return an MP4 video.');
    if (Number(response.headers.get('content-length')) > 256*1024*1024) throw new Error('Video exceeds the 256 MB download limit.');
    const blob = await response.blob();
    if (blob.size > 256*1024*1024) throw new Error('Video exceeds the 256 MB download limit.');
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = `RoboDE-scene-${record.id}.mp4`; anchor.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return <section className="config-card scene-recording-panel" aria-label="Scene recording">
    <div className="section-toolbar">
      <div className="nvidia-tool-heading"><NvidiaLogo/><h3><Video size={16}/> Scene recording</h3></div>
      <span className="tiny-tag">MP4 · NATIVE CAMERA</span>
    </div>
    <p>Record the rendered Isaac Sim scene. Start a recording, then use robot controls or run a plan. Recording observes the camera without commanding robot motion.</p>
    {!capability?.available && <p className="inline-note" role="status">{capability?.reason ?? 'Checking recording support…'}</p>}
    <fieldset disabled={busy || !!current} className="recording-settings">
      <legend>Camera recording settings</legend>
      <div className="recording-settings-row">
        <label>Resolution<select aria-label="Recording resolution" value={resolution} onChange={e=>setResolution(e.target.value)}>
          {['640x360','1280x720','1920x1080'].map(r=><option key={r}>{r}</option>)}
        </select></label>
        <label>Frames / second<select aria-label="Recording frame rate" value={fps} onChange={e=>setFps(Number(e.target.value))}>
          {[5,10,15,30].map(f=><option key={f}>{f}</option>)}
        </select></label>
        <label>Limit (seconds)<input aria-label="Recording duration" type="number" min={1} max={300} value={duration} onChange={e=>setDuration(Number(e.target.value))}/></label>
      </div>
      <details className="recording-camera"><summary>Camera position and look-at point</summary>
        <p>World coordinates in metres; Z points up. Camera settings apply only to this video.</p>
        {[{name:'Camera',values:position,set:setPosition},{name:'Look at',values:lookAt,set:setLookAt}].map(group=><div key={group.name} className="recording-settings-row">
          {['X','Y','Z'].map((axis,i)=><label key={axis}>{group.name} {axis} (m)<input aria-label={`${group.name} ${axis} (m)`} type="number" step=".1" min={-1000} max={1000} value={group.values[i]} onChange={e=>group.set(group.values.map((v,j)=>i===j?Number(e.target.value):v))}/></label>)}
        </div>)}
      </details>
    </fieldset>
    <div className="recording-buttons">
      <button disabled={busy || !!current || !capability?.available} onClick={()=>void run(async()=>{
        await post(base,{resolution,fps,duration_seconds:duration,position,look_at:lookAt});
      })}><Circle size={14}/> Start scene recording</button>
      {current && <button className="secondary" disabled={busy || current.status==='finalizing'} onClick={()=>void run(()=>post(`${base}/${current.id}/stop`))}><Square size={14}/> Stop recording</button>}
      <button className="secondary" disabled={busy || !connected || !!current || !capability?.available} onClick={()=>void run(()=>post(base+'/recover'))}><RefreshCw size={14}/> Recover worker history</button>
    </div>
    {current && <p className="recording-live" role="status"><span className="recording-dot"/>{current.status==='recording' ? `Recording · ${current.frames} ${current.frames===1?'frame':'frames'} · auto-stops at ${current.settings.duration_seconds}s` : 'Finishing MP4 and downloading to RoboDE…'}</p>}
    <p className="recording-help">Up to 5 minutes / 256 MB per video. Native rendering shares GPU resources and may slow a simulation. Stop recording and wait for export before resetting or disconnecting. Saved downloads remain available with the VM stopped.</p>
    {error && <p role="alert" className="inline-error">{error}</p>}
    <div className="recording-history" aria-label="Recorded videos">
      {records.length===0 && <small>No scene videos recorded for this project yet.</small>}
      {records.map(record=><article className="recording-item" key={record.id}>
        <div><strong>{new Date(record.created_at).toLocaleString()}</strong><small>{record.settings.resolution} · {record.settings.fps} fps · {record.status}{record.duration_seconds!==undefined && ` · ${record.duration_seconds.toFixed(1)}s`}{record.duplicated_frames>0 && ` · ${record.duplicated_frames} repeated frames`}</small></div>
        {record.cached && <button className="recording-download secondary" disabled={busy} onClick={()=>void run(()=>downloadVideo(record))}><Download size={15}/> MP4</button>}
        {record.status==='ready'&&!record.cached && <small>On worker · recover to download</small>}
        {record.error && <p className="inline-error" role="alert">{record.error}</p>}
      </article>)}
    </div>
  </section>;
}
