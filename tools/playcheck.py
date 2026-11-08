"""Pin and assess observations collected through normal browser game controls.

This assessor never claims to launch a browser. Supply Stagehand observations,
then retain the report beside the project's graph-recorded evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path


def hashes(export):
    return {str(p.relative_to(export)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(export.rglob('*')) if p.is_file()}


def assess(export, run_id, observations):
    export = Path(export)
    bundle = json.loads((export / 'game.json').read_text())
    rules = bundle.get('playtest', {})
    if rules.get('mode') == 'courier_trial':
        import courier_playcheck
        checks = courier_playcheck.assess_checks(bundle, observations)
        return {'schema_version': 1, 'run_id': run_id,
                'runtime_sha256': bundle['runtime_pin']['sha256'],
                'export_dir': str(export.resolve()), 'export_hashes': hashes(export), 'driver': 'observation-import',
                'criteria': {key: {'pass': bool(value)} for key, value in checks.items()},
                'observations': observations, 'passed': all(checks.values())}
    required = rules.get('hits_to_win', 3)
    metadata = bundle['metadata']
    effects = [e for e in metadata.get('events', []) if e['action'] == 'attack']
    attack = metadata['actions']['attack']
    marker = effects[0]['start_ms'] if effects and 'contact_frame' not in rules and 'contact_frame' not in attack else sum(f['duration_ms'] for f in attack['frames'][:rules.get('contact_frame', attack.get('contact_frame'))])
    miss, win, reset = (observations[key] for key in ('miss', 'win', 'reset'))
    events = win['contactEvents']
    contacts = [e for e in events if e['contact']]
    checks = {
        'out_of_range_miss': miss['hits'] == 0 and bool(miss['contactEvents']) and all(not e['contact'] for e in miss['contactEvents']),
        'contact_timing': bool(contacts) and all(e['start_ms'] == marker and 0 <= e['observed_ms'] - marker <= 100 for e in events),
        'win': win['hits'] == required and win['finished'] is True and len(contacts) == required,
        'reset': reset['hits'] == 0 and reset['finished'] is False and reset['contactEvents'] == [] and reset['x'] == 210,
    }
    if observations.get('fx_onset') is not None:
        onset = observations['fx_onset']
        checks['fx_before_damage'] = bool(onset['effects']) and onset['hits'] == 0 and not onset['contactEvents'] and onset['actor_elapsed_ms'] < marker
        impact = observations['impact']
        def visible_frame(observed):
            effect = next((e for e in effects if e['start_ms'] == observed['start_ms']), None)
            if not effect:
                return False
            elapsed = impact['actor_elapsed_ms'] - effect['start_ms']
            index = 0
            remaining = elapsed
            while index < len(effect['frames'])-1 and remaining >= effect['frames'][index]['duration_ms']:
                remaining -= effect['frames'][index]['duration_ms']
                index += 1
            return abs(observed['elapsed_ms']-elapsed) < .01 and observed['frame'] == str(index)
        active = [e for e in effects if e['start_ms'] <= impact['actor_elapsed_ms'] < e['start_ms'] + sum(f['duration_ms'] for f in e['frames'])]
        current = [e for e in impact['effects'] if abs(e['elapsed_ms'] - (impact['actor_elapsed_ms']-e['start_ms'])) < .01]
        checks['fx_frame_at_contact'] = impact['hits'] == 1 and len(current) == len(active) and all(visible_frame(e) for e in current)
    if 'facing_away' in observations:
        away = observations['facing_away']
        checks['facing_away'] = (rules.get('target_x', 650)-away['x'])*away['facing'] <= 0 and away['hits'] == 0 and away['contactEvents'][-1]['contact'] is False
    if 'before_win' in observations and required > 1:
        previous = observations['before_win']
        checks['before_win'] = previous is not None and previous['hits'] == required-1 and previous['finished'] is False
    return {'schema_version': 1, 'run_id': run_id,
            'runtime_sha256': bundle['runtime_pin']['sha256'],
            'export_dir': str(export.resolve()), 'export_hashes': hashes(export), 'driver': 'observation-import',
            'criteria': {key: {'pass': bool(value)} for key, value in checks.items()},
            'observations': observations, 'passed': all(checks.values())}


def verify(report, export):
    expected = assess(Path(export), report['run_id'], report['observations'])
    for field in ('export_dir', 'export_activity', 'browser_activity', 'driver'):
        if field in report:
            expected[field] = report[field]
    if report.get('driver') == 'stagehand-mcp':
        if report.get('browser_observed_hashes') != expected['export_hashes']:
            raise ValueError('Browser served bytes differ from export')
        expected['browser_observed_hashes'] = report['browser_observed_hashes']
    if report != expected:
        raise ValueError('Playcheck evidence or exported files changed')
    if not expected['passed']:
        raise ValueError('Gameplay criteria failed')
    return expected


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'run':
        from playcheck_browser import main
        raise SystemExit(main(sys.argv[2:]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = assess(args.export, args.run_id, json.loads(args.observations.read_text()))
    with args.output.open('x') as file:
        json.dump(report, file, indent=2)
    raise SystemExit(0 if report['passed'] else 1)
