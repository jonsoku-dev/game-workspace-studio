"""Review a combat project's actual source snapshot against the installed example."""
import hashlib
import html
import json
from pathlib import Path
import uuid

import graph
from runtime_inputs import output_stage

REFERENCE = 'starter/asset-reference/'
COPIES = ('jobs.mjs', 'motion/job-0.json', 'motion/manifest.mjs', 'art/job-0-idle.webp',
          'fx/job-clip-0.json', 'fx/job-clip-0.png', 'fx/job-clip-0-credit.json',
          'fx/job-impact-0.png', 'fx/job-impact-1.png')
STAGE_FILES = tuple(REFERENCE + Path(name).name for name in COPIES) + (REFERENCE + 'reference.json',)


def applicable(sources):
    markers={'game/combat-fx.mjs','game/combat-motion.mjs','game/jobs.mjs','game/motion/manifest.mjs'}
    return 'game/art-profile.json' in sources or markers <= sources.keys()


def reference_sources(root, read, load_sources):
    _, base = load_sources(root/'starter/combat')
    base['game/motion/default.mjs'] = base['game/motion/manifest.mjs']
    for name in COPIES:
        base['game/'+name] = read(root,REFERENCE+Path(name).name)
    for dest, source in [('motion/job-0.webp','bell-knight.webp'),('fx/custom-0.webp','resonance.webp')]:
        base['game/'+dest] = read(root,'starter/combat-brief/'+source)
    pins=json.loads(read(root,REFERENCE+'reference.json'))['sha256']
    if any(hashlib.sha256(base['game/'+name]).hexdigest()!=digest for name,digest in pins.items()):
        raise ValueError('Installed asset reference differs from its recorded pixels')
    return base


MOTIF_BRIEF = {
    'blade':'검이 어깨 뒤로 넘어가며 몸통이 먼저 비틀린다. 칼끝이 사선을 그려 닿고, 검이 표적 너머로 빠진 뒤 발을 회수한다.',
    'brawler':'무게가 뒷발에 실리며 어깨가 내려간다. 앞발을 박고 주먹을 보내고, 접촉 뒤 팔꿈치와 상체에 반동이 전해진다.',
    'astral':'손이나 도구에 힘이 모인다. 표적에 조준한 형상이 이동하고 도착할 때에만 중심이 열리며, 잔광은 먼저 터진 핵 주변에서 사라진다.',
    'rail':'두 발을 벌려 조준한다. 총구에서 선형 궤적이 뻗고, 팔과 옷자락이 뒤늦게 밀리며 표적의 접촉점에서 파편이 튄다.',
}


def _prose(value):
    text=' '.join(str(value).split())
    return html.escape(text,quote=False).replace('[','\\[').replace(']','\\]').replace('!','\\!')


def production_brief(sources, report=None):
    from combat_quality import jobs_for
    title=_prose(json.loads(sources['genre.json'])['title'])
    lines=[f'# {title} · 에셋 제작 지시서', '',
           '첫 전투 화면에서 구별해야 할 요소는 플레이어 얼굴·무기, 적의 예고 자세, 실제 접촉점이다. '
           '먼저 한 직업의 완성 원화를 전투 크기로 줄여 보고, 같은 기준으로 나머지 세트를 제작한다.', '']
    try:
        jobs=jobs_for(sources)
    except (KeyError,ValueError,TypeError,UnicodeError,AttributeError,RecursionError):
        jobs={}
    for key,job in jobs.items():
        name=_prose(job.get('name',key)); skill=_prose(job.get('skill','강공격'))
        lines.extend([f'## {name} · {skill}','',MOTIF_BRIEF.get(job.get('motif'),'이 직업의 준비, 도착, 빗나감, 회수 실루엣을 각각 정한다.'),
          f'외형 기준: {name}의 얼굴, 주무기, 의상 색면, 좌우 비대칭 특징을 먼저 한 장에서 정한다. '
          '그림마다 머리 크기와 신체 비율을 유지하고, 무기 끝과 옷자락까지 투명 셀 안에 남긴다.',
          '저작 경로: 몸은 combat_motion.py로 같은 발 피벗에 정렬한다. 달리기는 접지 → 눌림 → 반대 발 접지 → 밀어내기로 그린다. '
          '준비와 회수의 두 자세에는 action_ms를 지정해 대기용 긴 시간이 공격에 섞이지 않게 한다.',
          f'기술 원화: {skill}의 모임 → 이동 → 첫 충돌 → 최대 확산 → 파편 → 소멸을 3×2 셀로 그린다. '
          '실제 클립을 사용하면 charge/travel/impact의 노출을 나누고 명중과 빗나감을 각각 재생한다.', ''])
    lines.extend(['## 무대와 확인 순서','',
      '무대는 전투 발선과 지평선을 먼저 맞춘다. 캐릭터 얼굴 뒤의 명도와 공격 예고 뒤의 색 대비를 확인한다. '
      '초상화는 선택 크기에서 얼굴과 무기 특징이 남는 크롭을 고른다.',
      '① review.html에서 원속도와 느린 재생으로 발·무기·잔광을 비교한다. ② 실제 게임에서 명중·빗나감·피격·밝은 배경을 확인한다. '
      '③ 부족한 셀만 새 파일에 다시 그리고 같은 입력으로 재검사한다. 기술 기준 통과와 미술 채택은 별개다.'])
    if report and report['findings']:
        lines.extend(['','## 이번 판에서 먼저 고칠 부분',''])
        lines.extend(f"- {_prose(f['asset'])} · {_prose(f['repair'])}" for f in report['findings'])
    return '\n'.join(lines)+'\n'


def inspect(project, sources, root, read, load_sources):
    # Imported here so unrelated static exports keep their original dependencies.
    from combat_quality import assess
    from asset_board import write_board
    if not applicable(sources):
        raise ValueError('Asset comparison requires a class combat project; see ASSET-ART.md for other art styles.')
    report = assess(sources)
    if 'game/art-profile.json' in sources:
        try:
            profile=json.loads(sources['game/art-profile.json'])
        except (ValueError,UnicodeError,RecursionError):
            profile=None
        if profile!={'schema_version':1,'reference':'resonance-knight-v1'}:
            report['status']='failed'
            report['findings'].append({'asset':'game/art-profile.json','code':'invalid-profile','repair':'설치본의 공명기사 기준 프로필을 복원하세요.'})
    ref = reference_sources(root, read, load_sources)
    checks = project/'checks'
    if checks.is_symlink() or (checks.exists() and not checks.is_dir()):
        raise ValueError('Expected local checks directory')
    key='asset-review-'+uuid.uuid4().hex
    rel='checks/'+key
    with output_stage(project/rel) as stage:
        report['source_pins']={name:hashlib.sha256(data).hexdigest() for name,data in sorted(sources.items())}
        report['reference']='resonance-knight-v1'
        (stage/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        write_board(stage/'review.html',sources,report,ref)
        (stage/'art-direction.md').write_text(production_brief(sources, report),encoding='utf-8')
    paths=[rel+'/report.json',rel+'/review.html',rel+'/art-direction.md']
    passed = report['status']=='passed'
    activity=graph.record_work(project,{
        'id':key,'agent':'studio-asset-review','label':'Check playable combat artwork against reference',
        'status':'complete' if passed else 'error',
        'generated':[{'path':p,'sha256':hashlib.sha256((project/p).read_bytes()).hexdigest()} for p in paths],
        'verification':{'passed':passed,'checks':['Technical asset floor: '+report['status'],
          'Visual comparison available; artistic acceptance pending']}})
    return {'status':report['status'],'artistic_acceptance':'pending','reference':report['reference'],
            'report':paths[0],'board':paths[1],'art_direction':paths[2],'findings':report['findings'],'activity':activity}


class AssetFloorError(ValueError):
    def __init__(self, review):
        self.review=review
        super().__init__('Asset floor failed: '+review['report'])
