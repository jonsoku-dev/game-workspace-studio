"""Courier criteria and normal-control observations for the installed playcheck."""
import json
import time

CRITERIA = ('move_stop', 'jump_land', 'collect_once', 'denied', 'out_of_range_miss',
            'contact_timing', 'target_hp', 'finisher', 'win', 'reset', 'pause')
STATE = """const s=window.scoutGame?.scene?.scenes[0];return s?.state&&s.actor?{...s.state,action:s.actor.action,actor_elapsed_ms:s.actor.elapsed,cueEvents:s.cueEvents,contactEvents:s.contactEvents,status:document.querySelector('#status').textContent}:null;"""


def contact(bundle):
    meta, rules = bundle['metadata'], bundle.get('playtest', {})
    attack = meta['actions']['attack']
    effect = next((e for e in meta.get('events', []) if e['action'] == 'attack'), None)
    index = rules.get('contact_frame', attack.get('contact_frame'))
    if index is None and effect:
        return effect['start_ms'], effect['at_px']
    return sum(f['duration_ms'] for f in attack['frames'][:index]), rules.get('at_px', attack.get('at_px', effect['at_px'] if effect else None))


def assess_checks(bundle, o):
    required = bundle.get('playtest', {}).get('hits_to_win', 3)
    if type(required) is not int or not 1 <= required <= 20:
        raise ValueError('courier_trial hits_to_win must be 1..20')
    marker, _ = contact(bundle)
    events = lambda s, name: [e for e in s['cueEvents'] if e['event'] == name]
    start, move, stop = (o[k] for k in ('start', 'move', 'stop'))
    jump, land, collect, denied, miss, finisher, win, reset = (o[k] for k in ('jump', 'land', 'collect', 'denied', 'miss', 'finisher', 'win', 'reset'))
    hits = o['hits']
    previous_hp, previous_hits, damage_ok = required * 10, 0, bool(hits)
    for hit in hits:
        expected_damage = min(previous_hp, 15 if hit['combo'] == 2 else 10)
        damage_ok = damage_ok and hit['hits'] == previous_hits + 1 and hit['lastDamage'] == expected_damage and hit['targetHP'] == previous_hp - expected_damage and hit['finished'] is False
        previous_hp, previous_hits = hit['targetHP'], hit['hits']
    contacts = [e for e in finisher['contactEvents'] if e['contact']]
    return {
        'move_stop': move['x'] > start['x'] and abs(stop['x'] - move['x']) < 5 and bool(events(stop, 'move')) and bool(events(stop, 'stop')),
        'jump_land': jump['y'] < 356 and land['y'] == 356 and bool(events(jump, 'jump')) and bool(events(land, 'land')),
        'collect_once': collect['package'] is True and len(events(win, 'collect')) == 1,
        'denied': denied['finished'] is False and denied['package'] is False and bool(events(denied, 'denied')),
        'out_of_range_miss': miss['hits'] == 0 and bool(miss['contactEvents']) and all(e['contact'] is False for e in miss['contactEvents']),
        'contact_timing': bool(contacts) and all(e['start_ms'] == marker and 0 <= e['observed_ms'] - marker <= 100 for e in finisher['contactEvents']),
        'target_hp': start['targetMaxHP'] == required * 10 and start['targetHP'] == required * 10 and damage_ok and previous_hp == 0 and len(contacts) == previous_hits and finisher['hits'] == previous_hits and win['hits'] == previous_hits,
        'finisher': finisher['targetHP'] == 0 and finisher['finished'] is False and len(events(finisher, 'finisher')) == 1,
        'win': win['finished'] is True and win['lost'] is False and win['package'] is True and win['targetHP'] == 0 and abs(win['x'] - 860) < 70 and bool(events(win, 'interact')) and len(events(win, 'win')) == 1,
        'reset': reset['x'] == 150 and reset['y'] == 356 and reset['hp'] == 3 and reset['targetHP'] == required * 10 and reset['package'] is False and reset['hits'] == 0 and reset['finished'] is False and reset['lost'] is False and reset['contactEvents'] == [] and [e['event'] for e in reset['cueEvents']] in ([], ['restart']),
        'pause': o['pause']['paused'] is True and o['paused_later']['paused'] is True and o['pause']['clock'] == o['paused_later']['clock'] and o['resumed']['paused'] is False,
    }


def collect(client, bundle):
    def state():
        return client.run('return await page.evaluate(()=>{' + STATE + '});')
    def wait(predicate, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            value = state()
            if value and predicate(value):
                return value
            time.sleep(.06)
        raise TimeoutError('Unable: courier condition unreachable through normal controls; last=' + json.dumps(value, ensure_ascii=False))
    def click(name):
        client.run('await page.locator(' + json.dumps('#' + name) + ').click();return true;')
    def hold(direction, delay):
        key = 'ArrowRight' if direction == 'right' else 'ArrowLeft'
        client.run('await page.keyboard.press(' + json.dumps(key) + ',{delay:' + str(delay) + '});return true;')
    def move_to(target):
        for _ in range(70):
            value = state()
            if abs(value['x'] - target) < 5:
                return value
            direction = 'right' if value['x'] < target else 'left'
            # Hold the normal movement key, then observe its released position.
            delay = max(16, min(100, abs(value['x'] - target) / .24))
            hold(direction, delay)
        raise ValueError('Unable to reach courier geometry through normal movement: target=' + str(target) + '; last=' + json.dumps(value, ensure_ascii=False))
    o = {'start': wait(lambda s: True)}
    click('interact')
    o['denied'] = wait(lambda s: any(e['event'] == 'denied' for e in s['cueEvents']))
    click('attack')
    o['miss'] = wait(lambda s: bool(s['contactEvents']))
    wait(lambda s: s['action'] != 'attack')
    click('pause')
    o['pause'] = wait(lambda s: s['paused'])
    time.sleep(.15)
    o['paused_later'] = state()
    click('pause')
    o['resumed'] = wait(lambda s: not s['paused'])
    o['move'] = move_to(310)
    time.sleep(.15)
    o['stop'] = state()
    click('jump')
    o['jump'] = wait(lambda s: s['y'] < 356)
    # Cross continuously: observation round trips must not consume the jump mid-gap.
    hold('right', 630)
    move_to(470)
    o['land'] = wait(lambda s: s['y'] == 356)
    move_to(510)
    o['collect'] = wait(lambda s: s['package'])
    _, at = contact(bundle)
    meta = bundle['metadata']
    scale = 144 / meta['actions']['idle']['frames'][0]['rect']['w']
    offset = (at[0] - meta['pivot_px_from_top_left'][0]) * scale
    y = 356 + (at[1] - meta['pivot_px_from_top_left'][1]) * scale
    # Left-side reachable interval for a forward strike; the barrier stops x at 600.
    lower, upper = max(455, 650 - offset - 61), min(600, 650 - offset + 61)
    if lower > upper or abs(y - 300) >= 74:
        raise ValueError('Unable: courier attack geometry is unreachable from the approach')
    desired = (lower + upper) / 2
    move_to(desired)
    # Moving right is the approach, so face the barrier even after a correction.
    if state()['facing'] != 1:
        move_to(desired - 12)
        move_to(desired)
    o['hits'] = []
    for _ in range(20):
        before = wait(lambda s: s['action'] != 'attack')
        if before['targetHP'] == 0:
            break
        old = len(before['contactEvents'])
        click('attack')
        current = wait(lambda s: len(s['contactEvents']) > old)
        if current['hits'] != before['hits'] + 1:
            raise ValueError('Unable: normal courier strike did not contact the barrier')
        o['hits'].append(current)
    o['finisher'] = wait(lambda s: s['targetHP'] == 0)
    move_to(840)
    click('interact')
    o['win'] = wait(lambda s: s['finished'])
    click('restart')
    o['reset'] = wait(lambda s: s['hits'] == 0 and not s['contactEvents'] and s['x'] == 150)
    return o
