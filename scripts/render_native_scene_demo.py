"""Narrate genuine RoboDE footage, with the native camera from the same recorded run."""
from pathlib import Path
from datetime import datetime
import json,math,re,subprocess,shutil
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
OUT=Path((ROOT/'artifacts/native-demo-current.txt').read_text().strip())
FF=imageio_ffmpeg.get_ffmpeg_exe()
WORK=OUT/'render';WORK.mkdir(exist_ok=True)
report=json.loads((OUT/'demo-validation.json').read_text())
assert report['status']=='passed' and report['worker']['engine']=='isaac_sim'
assert json.loads((OUT/'shutdown-verification.json').read_text())['status']=='TERMINATED'
chapters=json.loads((OUT/'chapters.json').read_text())
texts=[
 'RoboDE is connected to NVIDIA Isaac Sim six point two on a Google Cloud NVIDIA L four GPU.',
 'In Environment, choose the native camera position, seven twenty p video, and ten frames per second. Then start scene recording.',
 'This plan contains eighteen tasks. Every task names its robot, its joint target and its dependencies. Independent robots can execute together.',
 'The inset shows native Isaac Sim camera footage from this same run. Both simulated arms raise, sweep their base joints in opposite directions, rotate their wrists, and return to the starting configuration. RoboDE tracks each task using observed articulation feedback. The run passes, and both robots report stopped.',
 'Finally, stop the recording and download the native MP four.',
]

def run(args):
 p=subprocess.run([str(x) for x in args],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
 if p.returncode:raise RuntimeError(p.stderr[-4000:])

def duration(p):
 result=subprocess.run([FF,'-i',str(p)],capture_output=True,text=True)
 match=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',result.stderr)
 if not match:raise ValueError(str(p))
 h,m,s=map(float,match.groups());return h*3600+m*60+s

def stamp(t):return f'{int(t//3600)}:{int(t%3600//60):02}:{t%60:05.2f}'

def ass_file(path,title,seconds,voice_seconds,text,inset=False,outro=False):
 s='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Arial,23,&H00EFE6DA,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,50,50,20,1
Style: Caption,Arial,23,&H00EFE6DA,&H00FFFFFF,&H00100B08,&H00100B08,0,0,0,0,100,100,0,0,1,0,0,2,80,80,18,1
Style: Inset,Arial,21,&H0000B976,&H00FFFFFF,&H00100B08,&H00100B08,0,0,0,0,100,100,0,0,1,0,0,7,1100,30,526,1
Style: End,Arial,54,&H00EFE6DA,&H00FFFFFF,&H00100B08,&H00100B08,0,0,0,0,100,100,0,0,1,0,0,5,70,70,30,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
 s+=f'Dialogue: 0,0:00:00.00,{stamp(seconds)},Title,,0,0,0,,RoboDE  |  NVIDIA Isaac Sim  |  {title}\n'
 if inset:s+=f'Dialogue: 0,0:00:00.00,{stamp(seconds)},Inset,,0,0,0,,NATIVE ISAAC CAMERA · SAME RUN\n'
 if outro:s+=f'Dialogue: 0,0:00:00.00,{stamp(seconds)},End,,0,0,0,,18 / 18 tasks completed\\N\\NGPU virtual machine stopped\n'
 words=text.split();parts=[' '.join(words[i:i+12]) for i in range(0,len(words),12)]
 for i,part in enumerate(parts):s+=f'Dialogue: 0,{stamp(voice_seconds*i/len(parts))},{stamp(voice_seconds*(i+1)/len(parts))},Caption,,0,0,0,,{part}\n'
 path.write_text(s)

clips=[];times=[];elapsed=0
for i,(chapter,text) in enumerate(zip(chapters,texts),1):
 stem=WORK/f'{i:02}';txt=stem.with_suffix('.txt');voice=stem.with_suffix('.aiff');subtitle=stem.with_suffix('.ass');clip=stem.with_suffix('.mp4')
 txt.write_text(text)
 run(['/usr/bin/say','-v','Samantha','-r','184','-f',txt,'-o',voice])
 voice_seconds=duration(voice);raw_seconds=chapter['end']-chapter['start'];seconds=math.ceil(max(raw_seconds,voice_seconds+.5)*25)/25
 ass_file(subtitle,chapter['title'],seconds,voice_seconds,text,inset=i==4)
 args=[FF,'-hide_banner','-loglevel','error','-y','-ss',chapter['start'],'-t',raw_seconds,'-i',report['browser_video'],'-i',voice]
 filters=f'[0:v]setpts=PTS-STARTPTS,scale=1510:944,pad=1920:1080:205:68:color=0x0b1019,tpad=stop_mode=clone:stop_duration={max(0,seconds-raw_seconds)+.1},fps=25[ui];'
 if i==4:
  motion_offset=max(0,(datetime.fromisoformat(report['run']['started_at'])-datetime.fromisoformat(report['recording']['created_at'])).total_seconds()-.75)
  args+=['-ss',motion_offset,'-i',OUT/'RoboDE-NVIDIA-Isaac-Sim-native.mp4']
  filters+='[2:v]setpts=PTS-STARTPTS,scale=768:432,pad=772:436:2:2:color=0x76b900,tpad=stop_mode=clone:stop_duration=5[native];[ui][native]overlay=1100:556:shortest=1[combined];'
  filters+=f'[combined]ass={subtitle}[v]'
 else:filters+=f'[ui]ass={subtitle}[v]'
 args+=['-filter_complex',filters,'-map','[v]','-map','1:a','-af','loudnorm=I=-16:TP=-1.5:LRA=11,apad','-t',seconds,'-c:v','libx264','-preset','fast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',clip]
 run(args);clips.append(clip);times.append({'title':chapter['title'],'start':elapsed,'duration':seconds});elapsed+=seconds
 print('Rendered:',chapter['title'],flush=True)
text='All eighteen tasks passed. The virtual machine is now stopped.'
voice=WORK/'outro.aiff';txt=WORK/'outro.txt';txt.write_text(text);run(['/usr/bin/say','-v','Samantha','-r','174','-f',txt,'-o',voice]);vs=duration(voice);seconds=math.ceil(max(5,vs+.5)*25)/25
subtitle=WORK/'outro.ass';ass_file(subtitle,'Run complete · compute stopped',seconds,vs,text,outro=True);clip=WORK/'outro.mp4'
run([FF,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i',f'color=c=0x0b1019:s=1920x1080:r=25:d={seconds}','-i',voice,'-vf',f'ass={subtitle}','-af','loudnorm=I=-16:TP=-1.5:LRA=11,apad','-t',seconds,'-c:v','libx264','-preset','fast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',clip]);clips.append(clip);times.append({'title':'Run complete · GPU stopped','start':elapsed,'duration':seconds});elapsed+=seconds
listing=WORK/'concat.txt';listing.write_text(''.join(f"file '{clip}'\n" for clip in clips))
metadata=WORK/'chapters.ffmeta';metadata.write_text(';FFMETADATA1\ntitle=RoboDE - NVIDIA Isaac Sim native execution demo\n'+''.join(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(c['start']*1000)}\nEND={round((c['start']+c['duration'])*1000)}\ntitle={c['title']}\n" for c in times))
dest=ROOT/'artifacts/walkthroughs/RoboDE-NVIDIA-Isaac-Sim-demo.mp4';dest.parent.mkdir(exist_ok=True)
run([FF,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',listing,'-i',metadata,'-map_metadata','1','-map_chapters','1','-c','copy','-movflags','+faststart',dest])
shutil.copy2(OUT/'RoboDE-NVIDIA-Isaac-Sim-native.mp4',ROOT/'artifacts/walkthroughs/RoboDE-NVIDIA-Isaac-Sim-native.mp4')
(OUT/'render-validation.json').write_text(json.dumps({'status':'passed','duration':duration(dest),'native_capture_fps':report['recording']['settings']['fps'],'source_run':report['run_id'],'native_inset':'recorded footage from the same run; illustrative alignment, not a latency measurement','chapters':times},indent=2))
print(dest,flush=True)
