"""Narrate, caption and chapter the genuine UI recordings. No generated UI frames."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import textwrap

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/walkthroughs'
FFMPEG=next((ROOT/'artifacts/video-tools/imageio_ffmpeg/binaries').glob('ffmpeg-macos-*'))


def run(args):
    subprocess.run([str(x) for x in args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)


def duration(path):
    result=subprocess.run([str(FFMPEG),'-i',str(path)],capture_output=True,text=True)
    match=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',result.stderr)
    if not match:raise ValueError(f'No duration: {path}')
    h,m,s=map(float,match.groups());return h*3600+m*60+s


def timestamp(t,ass=False):
    h=int(t//3600);m=int(t%3600//60);s=t%60
    return f'{h}:{m:02}:{s:05.2f}' if ass else f'{h:02}:{m:02}:{s:06.3f}'.replace('.',',')


def clean(text):return text.replace('\\','\\\\').replace('{','').replace('}','').replace('\n',' ')


def render(product):
    work=OUT/product/'render';work.mkdir(parents=True,exist_ok=True)
    modes=['business','businessphone'] if product=='business' else [product]
    entries=[]
    for mode in modes:
        for metadata in sorted((OUT/mode).glob('recording-*.json'),key=lambda p:int(p.stem.split('-')[-1])):
            record=json.loads(metadata.read_text())
            for chapter in record['chapters']:
                if not chapter.get('skip') and not chapter.get('error'):
                    entries.append({**chapter,'raw':record['path'],'mode':mode})
    if not entries:raise ValueError('No successful recordings')
    unique = {}
    for entry in entries: unique[entry['title']] = entry
    entries = list(unique.values())
    entries.sort(key=lambda e:e['title'].startswith('Finish:'))
    validation=OUT/'gcp/validation.json'
    native_gpu=product=='gcp' and validation.exists() and json.loads(validation.read_text()).get('status')=='passed'
    title={'web':'RoboDE · Server & browser IDE','desktop':'RoboDE · Native Electron IDE','business':'RoboDE Workspace · Business & mobile features','gcp':'RoboDE · NVIDIA GCP configuration'+(' and native execution' if native_gpu else ' · capacity unavailable')}[product]
    elapsed=0;clips=[];srt=[];bookmarks=[];cue=1
    for i,entry in enumerate(entries,1):
        prefix=work/f'{i:02}'
        voice=prefix.with_suffix('.aiff')
        text=prefix.with_suffix('.txt')
        if text.exists() and text.read_text()!=entry['narration'] and voice.exists():voice.unlink()
        text.write_text(entry['narration'])
        if not voice.exists():run(['/usr/bin/say','-v','Samantha','-r','174','-f',text,'-o',voice])
        voice_seconds=duration(voice)
        # Hold the last useful screen before a modal is dismissed; all frames remain genuine captures.
        trim = {
            'Import a robot into the global library': 3.1,
            'Paste or import a standard LLM function': 3.3,
            'Generate, review, and test a control adapter': 3.2,
            'Reuse an AI-generated SDK draft': 3.2,
            'Pair a project robot with a global adapter': 3.6,
            'Drag and rotate the robot': 2.7,
            'Inspect the robot workspace': 3.3,
            'Isaac Sim on an RTX server': 2.5,
            'Isaac Sim on a GCP VM': 2.5,
            'Import mobile room captures': 2.5,
        }.get(entry['title'], .65)
        raw_seconds=max(.1,entry['end']-entry['start']-trim)
        seconds=math.ceil(max(raw_seconds,voice_seconds+1)*25)/25
        caption_words=entry['narration'].split();chunks=[' '.join(caption_words[j:j+13]) for j in range(0,len(caption_words),13)]
        ass='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Arial,21,&H00EBD9C8,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,100,80,1002,1
Style: Caption,Arial,21,&H00EBE0D9,&H00FFFFFF,&H00100B08,&H00100B08,0,0,0,0,100,100,0,0,1,0,0,2,80,80,12,1
Style: Side,Arial,28,&H00EBE0D9,&H00FFFFFF,&H00100B08,&H00100B08,0,0,0,0,100,100,0,0,1,0,0,7,100,1300,300,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
        ass+=f'Dialogue: 0,0:00:00.00,{timestamp(seconds,True)},Title,,0,0,0,,{i:02} / {len(entries):02}    {clean(entry["title"])}\n'
        for j,chunk in enumerate(chunks):
            a=voice_seconds*j/len(chunks);b=voice_seconds*(j+1)/len(chunks)
            ass+=f'Dialogue: 0,{timestamp(a,True)},{timestamp(b,True)},Caption,,0,0,0,,{clean(chunk)}\n'
            srt.append(f'{cue}\n{timestamp(elapsed+a)} --> {timestamp(elapsed+b)}\n{chunk}\n');cue+=1
        if entry['mode']=='businessphone':
            ass+=f'Dialogue: 0,0:00:00.00,{timestamp(seconds,True)},Side,,0,0,0,,RoboDE Workspace\\N\\NMobile feature preview\\N\\NTouch controls\\NEditable commands\\NRoom capture options\\N\\NNo command execution\\NNo camera recording\n'
        ass_path=prefix.with_suffix('.ass');ass_path.write_text(ass)
        clip=prefix.with_suffix('.mp4');clips.append(clip)
        if entry['mode']=='businessphone':
            video='scale=430:900,pad=1920:1080:1190:40:color=0x080b10'
        else:
            video=('crop=iw:ih-10:0:0,' if entry['mode']=='desktop' else '')+'scale=1760:990,pad=1920:1080:80:0:color=0x080b10'
        filters=f"[0:v]{video},tpad=stop_mode=clone:stop_duration={max(0,seconds-raw_seconds)+1},subtitles='{ass_path}'[v];[1:a]apad[a]"
        print(f'{product} {i}/{len(entries)} {entry["title"]}: {seconds:.1f}s',flush=True)
        cache=prefix.with_suffix('.cache.json')
        cache_key={'entry':entry,'count':len(entries),'seconds':seconds,'render_version':3}
        if not clip.exists() or not cache.exists() or json.loads(cache.read_text())!=cache_key:
            try:run([FFMPEG,'-y','-ss',max(0,entry['start']),'-t',raw_seconds,'-i',entry['raw'],'-i',voice,
                '-filter_complex_threads','2','-filter_complex',filters,'-map','[v]','-map','[a]','-t',seconds,'-r','25','-c:v','libx264','-threads','4','-preset','fast','-crf','20','-pix_fmt','yuv420p',
                '-c:a','aac','-b:a','128k','-ar','48000','-ac','2',clip])
            except subprocess.CalledProcessError as error:
                print(error.stderr.decode()[-5000:]);raise
            cache.write_text(json.dumps(cache_key))
        bookmarks.append({'title':entry['title'],'start':round(elapsed,3),'end':round(elapsed+seconds,3),'raw_start':entry['start'],'raw_end':entry['end'],'narration':entry['narration'],'source':entry['raw']})
        elapsed+=seconds
    concat=work/'concat.txt';concat.write_text(''.join(f"file '{p}'\n" for p in clips))
    scope=('Actual UI walkthrough; Samantha narration; native Isaac physics on a real GCP GPU. No physical hardware or native editor streaming.' if native_gpu else 'Actual GCP configuration and rejected cloud startup attempts. GPU capacity unavailable; no native physics execution demonstrated.') if product=='gcp' else 'Actual UI walkthrough; Samantha narration; GPU and physical operation are not demonstrated.'
    metadata=';FFMETADATA1\ntitle='+title+'\nartist=RoboDE\ncomment='+scope+'\n'
    for bookmark in bookmarks:
        metadata+=f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(bookmark['start']*1000)}\nEND={round(bookmark['end']*1000)}\ntitle={bookmark['title']}\n"
    meta=work/'chapters.ffmetadata';meta.write_text(metadata)
    destination=OUT/f'RoboDE-{product}-walkthrough.mp4'
    run([FFMPEG,'-y','-f','concat','-safe','0','-i',concat,'-i',meta,'-map_metadata','1','-map_chapters','1','-c','copy','-movflags','+faststart',destination])
    (OUT/f'RoboDE-{product}-walkthrough.srt').write_text('\n'.join(srt))
    (OUT/f'RoboDE-{product}-chapters.json').write_text(json.dumps({'title':title,'duration_seconds':elapsed,'chapters':bookmarks},indent=2))
    print(f'SAVED {destination} · {elapsed/60:.1f} min',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('product',choices=['desktop','web','business','gcp']);args=parser.parse_args();render(args.product)
