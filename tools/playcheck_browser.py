"""Execute a pinned Phaser first slice through the configured local Stagehand MCP."""
import argparse
import hashlib
import http.server
import json
import mimetypes
from urllib.parse import unquote, urlsplit
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
try:
    import tomllib
except ImportError:  # Python 3.10 can still use the observation assessor.
    tomllib = None
import uuid

import graph
import playcheck
import courier_playcheck


class MCP:
    def __init__(self):
        if tomllib is None:
            raise ValueError('Browser playcheck requires Python 3.11+ for Codex TOML configuration')
        codex = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        config = tomllib.loads((codex / 'config.toml').read_text())['mcp_servers']['stagehand']
        if config.get('enabled') is False or config.get('env', {}).get('STAGEHAND_BROWSER') != 'local':
            raise ValueError('Enabled local Stagehand MCP required')
        self.proc = subprocess.Popen([config['command'], *config.get('args', [])], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     env={**os.environ, **config.get('env', {})})
        self.messages = queue.Queue()
        def reader():
            for line in self.proc.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    continue
        threading.Thread(target=reader, daemon=True).start()
        self.counter = 0
        try:
            self.call('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'studio-playcheck', 'version': '1'}})
        except Exception:
            self.close()
            raise
        self.proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        self.proc.stdin.flush()

    def call(self, method, params):
        self.counter += 1
        ident = self.counter
        self.proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}) + '\n')
        self.proc.stdin.flush()
        until = time.monotonic() + 90
        while time.monotonic() < until:
            response = self.messages.get(timeout=max(.01, until-time.monotonic()))
            if response.get('id') == ident:
                if 'error' in response:
                    raise ValueError('Stagehand MCP request failed')
                return response['result']
        raise TimeoutError('Stagehand response timeout')

    def run(self, code):
        result = self.call('tools/call', {'name': 'run', 'arguments': {'code': code}})
        if result.get('isError'):
            raise ValueError('Stagehand browser action failed')
        text = next(c['text'] for c in result['content'] if c['type'] == 'text')
        return json.loads(text)

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


STATE = "const s=window.scoutGame?.scene?.scenes[0]; return s?.actor ? {hits:s.hits,finished:s.finished,x:s.actor.x,facing:s.actor.facing,actor_elapsed_ms:s.actor.elapsed,effects:s.actor.effects.map(f=>({start_ms:f.event.start_ms,elapsed_ms:f.elapsed,frame:String(f.image.frame.name)})),contactEvents:s.contactEvents,status:document.querySelector('#status').textContent}:null;"


def inventory_server(export, pins, *, inline=False):
    """Serve only verified immutable bytes, never a live filesystem directory."""
    export = Path(export).resolve()
    files = {}
    for relative, digest in pins.items():
        path = (export / relative).resolve(strict=True)
        path.relative_to(export)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Export changed before HTTP snapshot')
        files['/' + relative] = data

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond(False)

        def do_HEAD(self):
            self.respond(True)

        def respond(self, head):
            hosts = self.headers.get_all('Host', [])
            allowed = {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)}
            try:
                url = urlsplit(self.path)
                path = unquote(url.path, errors='strict')
                valid_url = not url.scheme and not url.netloc and not url.fragment
            except (ValueError, UnicodeError):
                path, valid_url = '', False
            if len(hosts) != 1 or hosts[0].lower() not in allowed or not valid_url:
                status, data = 400, b''
            else:
                if path == '/':
                    path = '/index.html'
                data = files.get(path)
                status = 200 if data is not None else 404
                data = data if data is not None else b''
            self.send_response(status)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Type', mimetypes.guess_type(path)[0] or 'application/octet-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Referrer-Policy', 'no-referrer')
            local = "'self' 'unsafe-inline'" if inline else "'self'"
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src " + local + "; style-src " + local + "; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'" + ("; worker-src 'none'; form-action 'self'; sandbox allow-scripts allow-same-origin" if inline else ""))
            self.end_headers()
            if not head:
                self.wfile.write(data)

    return http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)


def run(project, export):
    project = Path(project).resolve()
    export = Path(export).resolve()
    relative = export.relative_to(project).as_posix()
    nodes = graph.export_graph(project)['@graph']
    receipt_path = relative + '/engine-export.json'
    receipt_bytes = (export / 'engine-export.json').read_bytes()
    receipt = next(n for n in nodes if n.get('path') == receipt_path and n.get('sha256') == hashlib.sha256(receipt_bytes).hexdigest())
    export_activity = receipt['wasGeneratedBy'][0]
    bundle = json.loads((export / 'game.json').read_text())
    runtime = bundle['runtime_pin']['@id']
    # The same admission used by review prevents transplanted runtime pins and invented exports.
    import review
    envelope = {'export_dir': relative, 'export_activity': export_activity, 'runtime_sha256': bundle['runtime_pin']['sha256']}
    review._export_anchor(project, {'runtime': bundle['runtime_pin']}, envelope)
    by_id = {n['@id']: n for n in nodes}
    work = by_id[export_activity]
    if runtime not in work.get('used', []) or work.get('status') != 'complete':
        raise ValueError('Export does not use this project runtime')
    inventory = json.loads(receipt_bytes)['files']
    before = playcheck.hashes(export)
    if set(before) != {i['path'] for i in inventory} | {'engine-export.json'} or any(before[i['path']] != i['sha256'] for i in inventory):
        raise ValueError('Registered export inventory drift')
    for path in export.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink export rejected')
    server = inventory_server(export, before)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = None
    key = 'browser-' + uuid.uuid4().hex
    activity = graph.project_id(project) + ':work:' + key
    try:
        client = MCP()
        url = 'http://127.0.0.1:' + str(server.server_port)
        client.run('await page.goto(' + json.dumps(url) + '); return true;')
        def state():
            return client.run('return await page.evaluate(()=>{' + STATE + '});')
        def wait(predicate, timeout=10):
            until = time.monotonic() + timeout
            while time.monotonic() < until:
                value = state()
                if value and predicate(value):
                    return value
                time.sleep(.08)
            raise TimeoutError('Game state did not reach expected condition')
        wait(lambda s: True)
        served = client.run('return await page.evaluate(async paths=>{const out={};for(const p of paths){const r=await fetch(p);if(!r.ok)throw Error("Missing export");const b=await r.arrayBuffer();out[p]=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",b))).map(x=>x.toString(16).padStart(2,"0")).join("");}return out;},' + json.dumps(list(before)) + ');')
        if served != before:
            raise ValueError('Served bytes differ from admitted export')
        def click(name):
            client.run('await page.locator(' + json.dumps('#'+name) + ').click();return true;')
        if bundle.get('playtest', {}).get('mode') == 'courier_trial':
            observations = courier_playcheck.collect(client, bundle)
        else:
            click('attack')
            effects = [e for e in bundle['metadata'].get('events', []) if e['action'] == 'attack']
            explicit = 'contact_frame' in bundle.get('playtest', {}) or 'contact_frame' in bundle['metadata']['actions']['attack']
            contact_index = bundle.get('playtest', {}).get('contact_frame', bundle['metadata']['actions']['attack'].get('contact_frame'))
            contact_ms = sum(f['duration_ms'] for f in bundle['metadata']['actions']['attack']['frames'][:contact_index]) if explicit else 0
            fx_onset = wait(lambda s: bool(s['effects'])) if effects and explicit and min(e['start_ms'] for e in effects) < contact_ms else None
            miss = wait(lambda s: bool(s['contactEvents']))
            duration = bundle['metadata']['actions']['attack']['duration_ms'] / 1000
            time.sleep(duration + .05)
            target = bundle.get('playtest', {}).get('target_x', 650)
            meta = bundle['metadata']
            event = next((e for e in meta.get('events', []) if e['action'] == 'attack'), None)
            explicit = 'contact_frame' in bundle.get('playtest', {}) or 'contact_frame' in meta['actions']['attack']
            at = bundle.get('playtest', {}).get('at_px', meta['actions']['attack'].get('at_px', event['at_px'] if event else None)) if explicit or not event else event['at_px']
            offset = (at[0] - meta['pivot_px_from_top_left'][0]) * 3
            desired = target - offset
            for _ in range(min(26, round(abs(desired-210)/32))):
                click('right' if desired >= 210 else 'left')
            # Face away using normal movement, observe a rejected attack, then reset.
            away = None
            position = state()['x']
            if target > position:
                click('right')
                click('left')
            else:
                click('left')
                click('right')
            old = len(state()['contactEvents'])
            click('attack')
            away = wait(lambda s: len(s['contactEvents']) > old)
            time.sleep(duration + .05)
            click('restart')
            wait(lambda s: not s['contactEvents'])
            for _ in range(min(26, round(abs(desired-210)/32))):
                click('right' if desired >= 210 else 'left')
            required = bundle.get('playtest', {}).get('hits_to_win', 3)
            before_win = None
            impact = None
            for index in range(required):
                old = len(state()['contactEvents'])
                click('attack')
                current = wait(lambda s: len(s['contactEvents']) > old)
                if index == 0:
                    impact = current
                if index == required-2:
                    before_win = current
                time.sleep(duration + .05)
            win = state()
            click('restart')
            reset = wait(lambda s: s['hits'] == 0 and not s['contactEvents'])
            observations = {'miss': miss, 'win': win, 'reset': reset, 'before_win': before_win, 'facing_away': away, 'fx_onset': fx_onset, 'impact': impact}
        report = playcheck.assess(export, bundle['runtime_pin']['wasGeneratedBy'][0], observations)
        report.update(browser_observed_hashes=served, export_dir=relative, export_activity=export_activity, browser_activity=activity, driver='stagehand-mcp')
        if playcheck.hashes(export) != before:
            raise ValueError('Export changed during browser execution')
        output = project / 'checks' / (key + '.json')
        output.parent.mkdir(exist_ok=True)
        with output.open('x') as file:
            json.dump(report, file, indent=2)
        graph.record_work(project, {'id': key, 'agent': 'stagehand-browser', 'label': 'Normal-controls Phaser browser playcheck',
            'status': 'complete', 'used': [runtime, receipt['@id']],
            'generated': [{'path': output.relative_to(project).as_posix(), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}],
            'verification': {'passed': report['passed'], 'checks': list(report['criteria'])}})
        return output
    except Exception as error:
        # Preserve a failed execution as evidence without attributing unobserved outcomes.
        output = project / 'checks' / (key + '.json')
        if not output.exists():
            output.parent.mkdir(exist_ok=True)
            failure = {'schema_version': 1, 'run_id': bundle['runtime_pin']['wasGeneratedBy'][0],
                       'runtime_sha256': bundle['runtime_pin']['sha256'], 'export_dir': relative,
                       'export_activity': export_activity, 'browser_activity': activity,
                       'driver': 'stagehand-mcp', 'passed': False,
                       'error': type(error).__name__, 'detail': str(error), 'criteria': {name: {'pass': False, 'status': 'unverified'}
                       for name in (courier_playcheck.CRITERIA if bundle.get('playtest', {}).get('mode') == 'courier_trial' else ('out_of_range_miss', 'contact_timing', 'win', 'reset', 'facing_away', 'before_win'))}}
            with output.open('x') as file:
                json.dump(failure, file, indent=2)
            graph.record_work(project, {'id': key, 'agent': 'stagehand-browser', 'label': 'Failed normal-controls browser playcheck',
                'status': 'error', 'used': [runtime, receipt['@id']],
                'generated': [{'path': output.relative_to(project).as_posix(), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}],
                'verification': {'passed': False, 'checks': ['Browser execution failed: ' + type(error).__name__]}})
        raise
    finally:
        if client:
            client.close()
        server.shutdown()
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--export', required=True, help='Project-relative graph-registered Phaser export')
    args = parser.parse_args(argv)
    relative = Path(args.export)
    if relative.is_absolute() or '..' in relative.parts:
        parser.error('export must be project-relative')
    try:
        output = run(args.project, args.project / relative)
    except Exception as error:
        parser.exit(2, 'Browser playcheck failed (' + type(error).__name__ + '); inspect the project graph/checks.\n')
    print(output)
    return 0 if json.loads(output.read_text())['passed'] else 1
