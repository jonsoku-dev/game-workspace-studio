#!/usr/bin/env python3
"""Create a local first slice; inspect its graph and print the next real command."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

import graph
import runtime_inputs
import scene

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'starter'
FILES = {'2d': ('master.png', 'motion.json', 'LICENSE.txt', 'NOTICE.md'),
         '3d': ('scene.json', 'requests/lantern.json', 'requests/embers.json')}
TEXT = {
    'ko': {'goal': '표적을 향해 이동한 뒤 유효한 공격을 {hits}회 명중시키세요.',
           'controls': '←/→ 또는 A/D: 이동 · Space: 공격 · R: 다시 시작. 화면 버튼도 사용 가능합니다.',
           'criteria': ['표적에서 멀리 공격하면 점수가 오르지 않는다.', '표적을 바라보고 접촉 프레임에 명중해야 1점 오른다.', '{hits}회 명중 전에 완료되지 않고, {hits}회에 완료된다.', 'R로 점수와 캐릭터 위치를 초기화한다.'],
           'next': '다음 명령', 'scope': '아이디어는 원문으로 보존합니다. 첫 슬라이스는 이동·표적 명중 규칙으로 제한합니다. 임의 게임 규칙을 자동 해석하지 않습니다.',
           'observe': '등불과 부모에 부착된 3D 불티를 관찰합니다. 플레이 규칙이 없는 첫 3D 장면입니다.',
           'ready': '로컬 게임 준비 완료. 아래 서버를 실행하고 주소를 여세요. 파일 생성은 실제 플레이 검증과 다릅니다.',
           'blocked': '산출물이 있지만 성공한 그래프 핀과 일치하지 않습니다. 자동으로 덮어쓰지 않습니다. 그래프와 파일을 먼저 검사하세요.'},
    'ja': {'goal': '標的に向かって移動し、有効な攻撃を{hits}回当ててください。',
           'controls': '←/→ または A/D: 移動 · Space: 攻撃 · R: リスタート。画面のボタンも利用できます。',
           'criteria': ['標的から離れた攻撃では得点しない。', '標的を向き、接触フレームで命中すると1点加算する。', '{hits}回の命中前には完了せず、{hits}回で完了する。', 'Rで得点とキャラクター位置が初期化する。'],
           'next': '次のコマンド', 'scope': 'アイデアの原文を保存します。最初のスライスは移動と標的への命中に限定します。任意のゲーム規則を自動解釈しません。',
           'observe': 'ランタンと親に付着した3D火の粉を観察します。ゲーム規則のない最初の3Dシーンです。',
           'ready': 'ローカルゲームの準備ができました。下のサーバーを実行し、URLを開いてください。ファイル生成と実際のプレイ検証は別です。',
           'blocked': '出力が存在しますが、成功したグラフのピンと一致しません。自動で上書きしません。グラフとファイルを確認してください。'}
}


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(project, label, paths, used=()):
    return graph.record_work(project, {'id': uuid.uuid4().hex, 'label': label,
        'agent': 'studio-starter', 'status': 'complete', 'used': list(used),
        'generated': [{'path': p.relative_to(project).as_posix(), 'sha256': digest(p)} for p in paths]})


COURIER = {
    'ko': {
        'goal': '소포를 찾아 장애물을 넘고 봉인을 깨뜨린 뒤 우편함에 배달하세요.',
        'controls': '←/→ 또는 A/D 이동 · ↑ 또는 W 점프 · Space 공격 · E 배달 · P 일시정지 · R 재시작',
        'criteria': ['빈손으로 배달하면 이유를 표시하고 완료하지 않는다.', '소포를 한 번만 획득하고 착지할 때 먼지가 나타난다.',
                     '장애물에 닿으면 체력이 줄고, 소진되면 재시작할 수 있다.', '봉인을 열고 우편함에 배달하면 완료된다.',
                     '피드백을 꺼도 획득·체력·배달 규칙은 같다.'],
    },
    'ja': {
        'goal': '荷物を拾い、障害物を越えて封印を壊し、ポストに届けてください。',
        'controls': '←/→ または A/D 移動 · ↑ または W ジャンプ · Space 攻撃 · E 配達 · P 一時停止 · R やり直し',
        'criteria': ['荷物がないときは配達を完了せず理由を表示する。','荷物を一度だけ取得し、着地時に砂ぼこりが出る。',
                     '障害物で体力が減り、尽きたらやり直せる。','封印を開きポストに配達すると完了する。',
                     'フィードバックを切っても取得・体力・配達のルールは同じ。'],
    },
}


def courier_effects(stage, scene):
    palette = ['#543748', '#b65c69', '#ffcf87', '#fff3c2']
    events = {'step':'step', 'land':'land', 'pickup':'pickup', 'hit':'impact',
              'attack':'slash', 'interact':'confirm', 'denied':'deny'}
    scene['feedback'] = {'schema_version': 1, 'effects': {}}
    for event, preset in events.items():
        asset = 'cue-' + preset
        path = 'requests/' + asset + '.json'
        write(stage / path, {'schema_version':1, 'preset':preset, 'size':32, 'palette':palette, 'seed':17})
        scene['assets'].append({'id':asset, 'producer':'pixel-effect', 'request':path})
        scene['feedback']['effects'][event] = asset


def create(output, idea, title, language='ko', hits=3, kind='2d', mode='land_hits'):
    if not idea.strip() or not title.strip() or len(idea) > 4000 or len(title) > 120:
        raise ValueError('Provide a concrete idea (1..4000 characters) and title (1..120 characters)')
    if type(hits) is not int or not 1 <= hits <= 20:
        raise ValueError('hits must be in 1..20')
    if mode not in ('land_hits','courier_trial') or mode == 'courier_trial' and kind != '2d':
        raise ValueError('Courier trial is a 2D first slice')
    text = TEXT[language]
    with runtime_inputs.output_stage(output) as stage:
        for name in FILES[kind]:
            source = TEMPLATES / kind / name
            if source.is_symlink() or not source.is_file():
                raise ValueError('Missing regular starter input: ' + name)
            target = stage / ('requests/' + name if kind == '2d' else name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        brief = {'title': title, 'idea': idea, 'goal': text['goal'].format(hits=hits) if kind == '2d' else text['observe'],
                 'controls': text['controls'] if kind == '2d' else text['observe']}
        criteria = [c.format(hits=hits) for c in text['criteria']] if kind == '2d' else [text['observe']]
        if mode == 'courier_trial':
            brief.update(goal=COURIER[language]['goal'], controls=COURIER[language]['controls'])
            criteria = COURIER[language]['criteria']
        plan = {'schema_version': 1, 'language': language, 'kind': kind, 'brief': brief,
                'constraints': {'offline': True, 'engine': 'phaser' if kind == '2d' else 'scene-preview',
                                'rule': mode if kind == '2d' else 'observation_only', 'hits_to_win': hits if kind == '2d' else None},
                'acceptance_criteria': criteria}
        write(stage / 'first-slice.json', plan)
        if kind == '2d':
            spec = {'schema_version': 1, 'id': 'first-slice', 'brief': brief,
                'coordinates': {'units': 'meters', 'up': '+Y', 'handedness': 'right'},
                'playtest': {'mode': mode, 'hits_to_win': hits, 'target_x': 650, 'target_y': 300,
                             'contact_frame': 2, 'at_px': [32, 20]},
                'assets': [{'id': 'hero', 'producer': 'pixel-action-set', 'request': 'requests/motion/action-set.request.json'}],
                'nodes': [{'id': 'hero', 'asset': 'hero', 'action': 'attack', 'position': [0, 0, 0],
                           'rotation_degrees': [0, 0, 0], 'scale': [1, 1, 1], 'size_m': 1}]}
            if mode == 'courier_trial':
                courier_effects(stage, spec)
        else:
            spec = json.loads((stage / 'scene.json').read_text())
            spec['brief'] = brief
        write(stage / 'scene.json', spec)
        write(stage / 'workspace.json', {'schema_version': 1, 'workspace_id': str(uuid.uuid4()), 'projects': ['.']})
        scope = text['scope'] if kind == '2d' else text['observe']
        if mode == 'courier_trial':
            scope = 'Courier trial · Phaser'
        (stage / 'README.md').write_text(f"# {title}\n\n{idea}\n\n{brief['goal']}\n\n{brief['controls']}\n\n{scope}\n\n" + '\n'.join('- ' + c for c in criteria) + '\n', encoding='utf-8')
        record(stage, 'Pin first-slice idea, constraints and original starter inputs', sorted(p for p in stage.rglob('*') if p.is_file()))
    return status(Path(output))


def pinned(project, path):
    if not path.is_file() or path.is_symlink():
        return False
    name = path.relative_to(project).as_posix()
    return any(n.get('path') == name and n.get('sha256') == digest(path)
               for n in graph.export_graph(project)['@graph'])


def status(project):
    project = project.resolve(strict=True)
    plan = json.loads((project / 'first-slice.json').read_text())
    text = TEXT[plan['language']]
    base = [sys.executable, str(Path(__file__).resolve())]
    nodes = {n['@id']: n for n in graph.export_graph(project)['@graph']}
    exports = []
    for receipt in project.glob('play/*/engine-export.json'):
        if pinned(project, receipt):
            data = json.loads(receipt.read_text())
            if data.get('engine') == 'phaser' and all(
                    (path := graph._local(receipt.parent, f['path'])).is_file() and not path.is_symlink()
                    and path.stat().st_size == f['byteCount'] and digest(path) == f['sha256']
                    for f in data['files']):
                name = receipt.relative_to(project).as_posix()
                recorded = max((nodes[a].get('recordedAt', '')
                    for n in nodes.values() if n.get('path') == name and n.get('sha256') == digest(receipt)
                    for a in n.get('wasGeneratedBy', [])), default='')
                exports.append((recorded, receipt.parent))
    runs = [r for r in graph.history(project) if r.get('status') == 'ready' and r.get('runtime')]
    if exports:
        output = max(exports)[1]
        state = 'playable_export'
        command = [sys.executable, '-m', 'http.server', '8937', '--bind', '127.0.0.1', '--directory', str(output)]
        guidance = text['ready']
    elif plan['kind'] == '3d' and runs:
        state = 'scene_ready'
        command = [sys.executable, str(ROOT / 'tools/visualize.py'), '--project', str(project)]
        guidance = text['observe']
    else:
        motion = project / 'requests/motion/action-set.request.json'
        blocked_motion = (project / 'requests/motion').exists() and (
            not pinned(project, motion) or not pinned(project, motion.parent / 'inspection.json')
            or not all(pinned(project, p) for p in motion.parent.rglob('*') if p.is_file())
            or not json.loads((motion.parent / 'inspection.json').read_text()).get('passed'))
        blocked_source = plan['kind'] == '2d' and not all(
            pinned(project, project / 'requests' / name) for name in FILES['2d'])
        blocked = blocked_motion or blocked_source
        state = 'blocked_source' if blocked_source else 'blocked_motion' if blocked_motion else 'build_required'
        command = [sys.executable, str(ROOT / 'tools/graph.py'), 'history', '--project', str(project)] if blocked else base + ['build', str(project)]
        guidance = text['blocked'] if blocked else text['scope'] if plan['kind'] == '2d' else text['observe']
        if not blocked and plan['constraints']['rule'] == 'courier_trial':
            guidance = plan['brief']['goal']
    return {'state': state, 'title': plan['brief']['title'], 'goal': plan['brief']['goal'],
            'controls': plan['brief']['controls'], 'acceptance_criteria': plan['acceptance_criteria'],
            'guidance': guidance, 'next_label': text['next'], 'next_command': shlex.join(command),
            'url': 'http://127.0.0.1:8937/' if exports else None}


def build(project, phaser_package=None):
    project = project.resolve(strict=True)
    plan = json.loads((project / 'first-slice.json').read_text())
    if plan['kind'] == '2d':
        motion = project / 'requests/motion'
        if not motion.exists():
            launcher = shutil.which('pixel-asset')
            if not launcher:
                raise ValueError('Install the local pixel-asset CLI with motion support before build')
            sources = [project / 'requests' / n for n in FILES['2d']]
            if not all(pinned(project, p) for p in sources):
                raise ValueError('Starter source changed; record and approve the replacement before building')
            command = [launcher, 'motion', '--request', str(project / 'requests/motion.json'), '--out', str(motion)]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                graph.record_work(project, {'id': uuid.uuid4().hex, 'label': 'Starter motion failed', 'agent': 'studio-starter',
                    'status': 'error', 'verification': {'passed': False, 'checks': ['pixel-asset motion returned nonzero; verify CLI motion support and request']}})
                raise ValueError('pixel-asset motion failed; check local CLI motion support and requests/motion.json')
            if not all(pinned(project, p) for p in sources):
                raise ValueError('Starter sources changed during motion; inspect input and output before retrying')
            used = [n['@id'] for n in graph.export_graph(project)['@graph'] if n.get('path') in [p.relative_to(project).as_posix() for p in sources[:2]]]
            record(project, 'Produce articulated starter motion with pixel-asset motion', sorted(p for p in motion.rglob('*') if p.is_file()), used)
            if not json.loads((motion / 'inspection.json').read_text()).get('passed'):
                raise ValueError('Motion technical inspection failed; inspect the authored rig before scene build')
        elif (not pinned(project, motion / 'action-set.request.json')
                or not all(pinned(project, p) for p in motion.rglob('*') if p.is_file())
                or not json.loads((motion / 'inspection.json').read_text()).get('passed')):
            raise ValueError('Existing motion output is unpinned or changed; inspect it before retrying')
    run = 'build/run-' + uuid.uuid4().hex
    result = scene.build(project, run, 300)
    if result['status'] != 'ready':
        raise ValueError('Scene build did not become ready; inspect graph history')
    if plan['kind'] == '2d':
        import export_game
        export_game.export_game('phaser', '.', project / 'workspace.json', [('.', result['files']['scene'])],
                                'play/run-' + uuid.uuid4().hex, phaser_package=phaser_package)
    return status(project)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        '한국어: new로 새 폴더를 만들고 출력된 다음 명령을 실행하세요. '
        '日本語: newで新規フォルダーを作り、表示された次のコマンドを実行してください。 '
        'Example: new ./my-game --idea \"forest robot target practice\" --title \"Forest Dojo\" --language ja --hits 3'))
    sub = parser.add_subparsers(dest='command', required=True)
    new = sub.add_parser('new', help='한국어/日本語: 새 폴더에 첫 슬라이스 생성 / 新規フォルダーに作成')
    new.add_argument('project', type=Path)
    new.add_argument('--idea', required=True)
    new.add_argument('--title', required=True)
    new.add_argument('--language', choices=TEXT, default='ko')
    new.add_argument('--hits', type=int, default=3)
    new.add_argument('--kind', choices=FILES, default='2d')
    new.add_argument('--mode', choices=('land_hits','courier_trial'), default='land_hits')
    for name in ('status', 'inspect', 'resume', 'build'):
        command = sub.add_parser(name)
        command.add_argument('project', type=Path)
        if name == 'build':
            command.add_argument('--phaser-package', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'new':
            result = create(args.project, args.idea, args.title, args.language, args.hits, args.kind, args.mode)
        elif args.command == 'build':
            result = build(args.project, args.phaser_package)
        else:
            result = status(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'{type(error).__name__}: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
