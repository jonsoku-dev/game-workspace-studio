"""Installed combat starter inventory and local, brief-driven class artwork."""
import io
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile

MOTIFS = ('blade', 'brawler', 'astral', 'rail')
ATLAS_IDS = ('sword-cut', 'sword-wheel', 'sword-cleave', 'fist-rise', 'fist-quake',
             'impact', 'land', 'storm', 'detonation','star-volley','star-seal','star-rain','gun-flash','gun-plasma')
ROOT = 'starter/combat/'
def inventory():
    # Pin every distributable file, including upstream notices. Never copy a whole working tree.
    return (['genre.json','game/art-profile.json', 'game/index.html', 'game/game.mjs', 'game/style.css', 'game/jobs.mjs',
             'game/timing.mjs','game/motif-ms.mjs','game/combat-fx.mjs','game/combat-motion.mjs','game/motion/manifest.mjs', 'game/art/bell-tower.jpg', 'game/fx/credits.json',
             'game/fx/manifest.mjs', 'game/art/credits.json']
            + [f'game/art/{k}-{pose}.webp' for k in (*MOTIFS, 'warden') for pose in ('idle', 'attack')]
            + [f'game/fx/{k}.webp' for k in ('sword', 'fist', 'star', 'gun')]
            + [f'game/fx/{k}.png' for k in ATLAS_IDS]
            + [f'game/motion/{k}.{ext}' for k in (*MOTIFS,'warden') for ext in ('json','webp')])

def painted_sheet(data, suffix):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        if im.format != {'.png':'PNG','.webp':'WEBP'}[suffix] or im.width > 3072 or im.height > 2048:
            raise ValueError('Expected bounded PNG/WebP of six frames')
        if im.width % 3 or im.height % 2 or im.width // 3 != im.height // 2:
            raise ValueError('Expected 3 by 2 equal square cells')
        im = im.convert('RGBA')
        if im.getchannel('A').getextrema()[0] != 0:
            raise ValueError('Expected transparent background')
        cell = im.width // 3
        frames = [im.crop((i%3*cell,i//3*cell,(i%3+1)*cell,(i//3+1)*cell)) for i in range(6)]
        if not all(f.getbbox() for f in frames) or len({f.tobytes() for f in frames}) != 6:
            raise ValueError('Paint six distinct nonempty spell exposures')

def make_impact(destination, index, colors):
    if (not isinstance(colors, list) or not 3 <= len(colors) <= 8
            or not all(isinstance(c,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',c) for c in colors)
            or len(set(c.lower() for c in colors)) != len(colors)):
        raise ValueError('palette needs 3..8 distinct #RRGGBB colors from shadow to core')
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        request = {'schema_version':1,'preset':'impact','size':64,'seed':17+index,'palette':colors}
        (tmp/'request.json').write_text(json.dumps(request))
        subprocess.run(['pixel-asset','effect','--request',str(tmp/'request.json'),'--out',str(tmp/'result')],
                       check=True, timeout=45, stdout=subprocess.DEVNULL)
        result = tmp/'result'
        meta = json.loads((result/'sheet.json').read_bytes())
        image = f'job-impact-{index}.png'
        (destination/image).write_bytes((result/'sheet.png').read_bytes())
        return {'image':'./fx/'+image,'pivot':meta['pivot_px_from_top_left'],
                'frames':[{**f['rect'],'ms':f['duration_ms']} for f in meta['frames']]}

def make_clip(destination, index, root, path, read):
    request_data = read(root,path)
    if len(request_data)>65536:
        raise ValueError('Clip request exceeds 64 KiB')
    request = json.loads(request_data)
    if not isinstance(request,dict) or not isinstance(path,str):
        raise ValueError('Expected a local effect-clip request')
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        # Snapshot only admitted relative files; the producer never receives user-controlled paths.
        for key,target in [('source','input.gif'),('license','LICENSE'),('notice','NOTICE')]:
            relative=request.get(key)
            if not isinstance(relative,str):
                raise ValueError('Missing clip source or attribution')
            data=read(root,(Path(path).parent/relative).as_posix())
            if len(data)>(16*1024*1024 if key=='source' else 1024*1024):
                raise ValueError('Oversized clip input')
            (tmp/target).write_bytes(data)
            request[key]=target
        (tmp/'request.json').write_text(json.dumps(request))
        out=tmp/'result'
        subprocess.run(['pixel-asset','effect-clip','--request',str(tmp/'request.json'),'--out',str(out)],
                       check=True,timeout=60,stdout=subprocess.DEVNULL)
        name=f'job-clip-{index}'
        (destination/(name+'.png')).write_bytes((out/'sheet.png').read_bytes())
        meta=json.loads((out/'sheet.json').read_bytes())
        (destination/(name+'.json')).write_bytes((out/'sheet.json').read_bytes())
        credit={'license':(out/'LICENSE').read_text(),'notice':(out/'NOTICE').read_text(),
                'producer':json.loads((out/'effect-clip.json').read_bytes())}
        (destination/(name+'-credit.json')).write_text(json.dumps(credit,ensure_ascii=False))
        frames=[{**f['frame'],'ms':f['duration']} for f in meta['frames']]
        phases={tag['name']:frames[tag['from']:tag['to']+1] for tag in meta['meta']['frameTags']}
        return {'image':'./fx/'+name+'.png','pivot':meta['meta']['pixelfx']['pivot'],'phases':phases}


def attach_actor(stage, index, root, path, read):
    from PIL import Image
    if not isinstance(path,str):
        raise ValueError('Expected a compiled motion metadata path')
    raw=read(root,path)
    if len(raw)>65536:
        raise ValueError('Oversized motion manifest')
    actor=json.loads(raw)
    required={'image','pivot','bodyHeight','actions','frames'}
    states={'idle','move','windup','release','follow','recover','hurt','evade','heavy'}
    if (not isinstance(actor,dict) or (not required<=set(actor) or set(actor)-required-{'action_ms'}) or not isinstance(actor['image'],str)
            or Path(actor['image']).name!=actor['image'] or not actor['image'].endswith('.webp')
            or not isinstance(actor['frames'],list) or not 1<=len(actor['frames'])<=64
            or not isinstance(actor['actions'],dict) or not states<=actor['actions'].keys()
            or type(actor['bodyHeight']) not in (int,float) or not 1<=actor['bodyHeight']<=512):
        raise ValueError('Invalid authored motion atlas')
    data=read(root,(Path(path).parent/actor['image']).as_posix())
    if len(data)>8*1024*1024:
        raise ValueError('Motion atlas exceeds 8 MiB')
    with Image.open(io.BytesIO(data)) as im:
        if im.format!='WEBP' or im.width*im.height>16777216:
            raise ValueError('Expected bounded WebP motion atlas')
        for f in actor['frames']:
            if (not isinstance(f,dict) or any(type(f.get(k)) is not int for k in ('x','y','w','h','ms'))
                    or not 0<=f['x']<f['x']+f['w']<=im.width or not 0<=f['y']<f['y']+f['h']<=im.height
                    or not 1<=f['ms']<=60000 or not 1<=f['w']<=512 or not 1<=f['h']<=512):
                raise ValueError('Invalid motion frame')
            sockets=f.get('sockets',{})
            if (not isinstance(sockets,dict) or len(sockets)>16 or
                    any(not isinstance(name,str) or not re.fullmatch('[a-z][a-z0-9-]{0,47}',name) or
                        not isinstance(point,list) or len(point)!=2 or
                        any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=f[key]
                            for v,key in zip(point,('w','h'))) for name,point in sockets.items())):
                raise ValueError('Invalid motion sockets')
        pivot=actor['pivot']
        if (not isinstance(pivot,list) or len(pivot)!=2 or
                any(type(v) is not int or not 0<=v<=actor['frames'][0][key] for v,key in zip(pivot,('w','h')))):
            raise ValueError('Invalid foot pivot')
        if any(not isinstance(seq,list) or not 1<=len(seq)<=64 or
               any(type(n) is not int or not 0<=n<len(actor['frames']) for n in seq) for seq in actor['actions'].values()):
            raise ValueError('Invalid action sequence')
        overrides=actor.get('action_ms',{})
        if (not isinstance(overrides,dict) or not overrides.keys()<=actor['actions'].keys() or
                any(not isinstance(ms,list) or len(ms)!=len(actor['actions'][key])
                    or any(type(v) is not int or not 1<=v<=60000 for v in ms) or sum(ms)>60000
                    for key,ms in overrides.items())):
            raise ValueError('Invalid per-action exposure timing')
        im.load()
        idle=actor['frames'][actor['actions']['idle'][0]]
        thumb=im.crop((idle['x'],idle['y'],idle['x']+idle['w'],idle['y']+idle['h'])).convert('RGBA')
        bbox=thumb.getbbox()
        if not bbox:
            raise ValueError('Invisible idle frame')
        thumb.crop(bbox).save(stage/f'game/art/job-{index}-idle.webp',quality=93)
    key=f'job-{index}';name=key+'.webp';actor['image']=name
    (stage/'game/motion'/name).write_bytes(data)
    (stage/'game/motion'/(key+'.json')).write_text(json.dumps(actor))
    return key,actor


def customize(stage, brief_path, read):
    # read() admits bounded, single-link local files through O_NOFOLLOW on every component.
    data = read(brief_path.parent, brief_path.name)
    if len(data) > 65536:
        raise ValueError('Brief exceeds 64 KiB')
    brief = json.loads(data)
    if (not isinstance(brief,dict) or set(brief) != {'schema_version','title','jobs'}
            or type(brief['schema_version']) is not int or brief['schema_version'] != 1
            or not isinstance(brief['title'],str) or not 1 <= len(brief['title'].strip()) <= 100
            or not isinstance(brief['jobs'],list) or not 1 <= len(brief['jobs']) <= 8):
        raise ValueError('Expected title and 1..8 jobs')
    jobs = {}
    actors = {}
    for i, job in enumerate(brief['jobs']):
        required={'id','name','skill','motif'}
        if (not isinstance(job,dict) or not required <= set(job) or set(job)-required-{'sheet','palette','clip','actor'}
                or not isinstance(job['id'],str) or not re.fullmatch('[a-z][a-z0-9-]{0,39}',job['id'])
                or job['id'] == 'constructor' or job['id'] in jobs or job['motif'] not in MOTIFS
                or any(not isinstance(job[k],str) or not 1 <= len(job[k].strip()) <= 64 for k in ('name','skill'))):
            raise ValueError(f'Invalid combat job {i+1}')
        spec = jobs[job['id']] = {key:job[key] for key in ('name','skill','motif')}
        if 'actor' in job:
            key,actor=attach_actor(stage,i,brief_path.parent,job['actor'],read)
            spec['actor']=key;actors[key]=actor
        if 'sheet' in job:
            if not isinstance(job['sheet'],str):
                raise ValueError('Expected relative sheet path')
            suffix=Path(job['sheet']).suffix.lower()
            if suffix not in ('.png','.webp'):
                raise ValueError('Expected PNG or WebP sheet')
            sheet=read(brief_path.parent, job['sheet'])
            if len(sheet)>8*1024*1024:
                raise ValueError('Custom sheet exceeds 8 MiB')
            painted_sheet(sheet,suffix)
            name=f'custom-{i}{suffix}'
            (stage/'game/fx'/name).write_bytes(sheet)
            spec['sheet']='./fx/'+name
        if 'clip' in job:
            if not isinstance(job['clip'],str):
                raise ValueError('Expected relative clip request path')
            spec['clip']=make_clip(stage/'game/fx',i,brief_path.parent,job['clip'],read)
        if 'palette' in job:
            spec['impact']=make_impact(stage/'game/fx',i,job['palette'])
    if actors:
        folder=stage/'game/motion'
        (folder/'manifest.mjs').rename(folder/'default.mjs')
        (folder/'manifest.mjs').write_text("import base from './default.mjs';\nexport default {...base,..."+
                                          json.dumps(actors,ensure_ascii=False)+"};\n")
    (stage/'game/jobs.mjs').write_text('export const JOBS = '+json.dumps(jobs,ensure_ascii=False)+';\n')
    genre=json.loads((stage/'genre.json').read_text())
    genre['title']=brief['title']
    (stage/'genre.json').write_text(json.dumps(genre,ensure_ascii=False,indent=2)+'\n')
    (stage/'combat-brief.json').write_bytes(data)
