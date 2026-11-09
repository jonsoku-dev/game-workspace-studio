import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import web_regression


CASE = {'schema_version': 1, 'steps': [
    {'click': 'button#start'}, {'press': {'selector': 'input#control', 'key': 'Enter'}},
    {'expect_text': {'selector': '#status', 'contains': 'Ready'}}]}

# Execute the actual generated runner against a browser-shaped deterministic DOM.
NODE_STUB = r"""
const fs = require('node:fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
global.crypto = require('node:crypto').webcrypto;
let now = 0, phase = 0, polls = 0, location = 'about:blank', closed = false;
Date.now = () => now;
const events = {}, actions = [];
const element = {getClientRects: () => [1], get innerText() {
  return ['mismatch', 'lateerror'].includes(payload.mode) || polls < 3 ? 'Loading' : 'Ready';
}};
global.document = {get baseURI() { return location; }, querySelector: () => null,
querySelectorAll: selector => {
  if (selector === 'button#start' || selector === 'input#control') return [{
    hasAttribute: () => false,
    closest: name => name === 'a[href]' && ['external', 'popup'].includes(payload.mode)
      ? {href: payload.mode === 'external' ? 'https://outside.invalid/' : location,
         target: payload.mode === 'popup' ? '_blank' : ''}
      : name === 'form' && payload.mode === 'externalform' ? {action: 'https://outside.invalid/'} : null
  }];
  if (selector !== '#status') throw Error('Unexpected selector');
  if (phase !== 2) throw Error('Actions out of order');
  polls++;
  return payload.mode === 'missing' ? [] : [element];
}};
global.getComputedStyle = () => ({visibility: 'visible'});
const nativeFetch = global.fetch;
global.fetch = async address => payload.mode === 'resource' ? {ok: false}
  : nativeFetch(new URL(address, location));
const target = {
  on: (event, listener) => { events[event] = listener; },
  goto: async address => {
    if (payload.mode === 'navigation') throw Error('Navigation timeout');
    location = address;
    if (payload.mode === 'pageerror') events.pageerror(Error('secret page content'));
    if (payload.mode === 'console') events.console({type: () => 'error'});
  },
  evaluate: async (callback, argument) => callback(argument),
  locator: selector => ({
    click: async options => {
      if (payload.mode === 'action') throw Error('Control unavailable');
      if (selector !== 'css=button#start' || options.timeout !== 2000 || phase !== 0)
        throw Error('Wrong click');
      actions.push('click'); phase = 1;
      if (payload.mode === 'blocked') events.console({type: () => 'error'});
    },
    press: async (key, options) => {
      if (selector !== 'css=input#control' || key !== 'Enter' || options.timeout !== 2000 || phase !== 1)
        throw Error('Wrong press');
      actions.push('press'); phase = 2;
      if (payload.mode === 'unexpected') location = 'https://outside.invalid/';
    }
  }),
  waitForTimeout: async delay => {
    now += delay;
    if (payload.mode === 'lateerror' && phase === 2 && now >= 2000) events.pageerror(Error('Late failure'));
  },
  url: () => location,
  close: async () => { closed = true; }
};
const context = {newPage: async () => target};
(async () => {
  try {
    const run = new (Object.getPrototypeOf(async function() {}).constructor)('context', payload.code);
    const report = await run(context);
    if (!closed || !actions.includes('press') || polls < 3) throw Error('Incomplete lifecycle');
    process.stdout.write(JSON.stringify({report}));
  } catch (error) {
    process.stdout.write(JSON.stringify({error: error.message, closed}));
  }
})();
"""


class CaseTests(unittest.TestCase):
    def test_minimal_case_and_actions(self):
        self.assertEqual(web_regression.parse_case(json.dumps(CASE).encode()), CASE)
        case = {'schema_version': 1, 'steps': [CASE['steps'][-1]]}
        self.assertEqual(web_regression.parse_case(json.dumps(case).encode()), case)

    def test_invalid_or_unbounded_cases(self):
        invalid = [b'', b'{}', b'[]', b'\xff', b'x' * 16385,
                   b'{"schema_version":1,"schema_version":1,"steps":[]}',
                   json.dumps({'schema_version': True, 'steps': CASE['steps']}).encode()]
        for step in [{'click': 'https://outside.invalid'}, {'evaluate': 'alert(1)'},
                     {'click': 'xpath=//*'}, {'click': '#x >> text=ok'},
                     {'press': {'selector': '#x', 'key': 'Control+L'}},
                     {'expect_text': {'selector': '#x', 'contains': ' '}},
                     {'expect_text': {'selector': '#x', 'contains': 'x' * 513}},
                     {'click': '#x', 'press': {'selector': '#x', 'key': 'a'}},
                     {'click': '#' + 'x' * 241}]:
            invalid.append(json.dumps({'schema_version': 1, 'steps': [step, CASE['steps'][-1]]}).encode())
        invalid.extend(json.dumps(case).encode() for case in [
            {'schema_version': 1, 'steps': [{'click': '#x'}]},
            {'schema_version': 1, 'steps': CASE['steps'] * 6},
            {**CASE, 'url': 'https://outside.invalid'}])
        for data in invalid:
            with self.subTest(data=data[:100]), self.assertRaises(ValueError):
                web_regression.parse_case(data)

    def test_inline_policy_is_explicit_and_retains_local_resource_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = b'<style>body{color:red}</style><script>document.title="Game"</script>'
            (root / 'index.html').write_bytes(data)
            pins = {'index.html': hashlib.sha256(data).hexdigest()}
            for inline in (False, True):
                server = web_regression.playcheck_browser.inventory_server(root, pins, inline=inline)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with urlopen('http://127.0.0.1:' + str(server.server_port), timeout=3) as response:
                        self.assertEqual(response.read(), data)
                        policy = response.headers['Content-Security-Policy']
                        self.assertEqual("'unsafe-inline'" in policy, inline)
                        self.assertIn("connect-src 'self'", policy)
                        self.assertIn("base-uri 'none'", policy)
                        if inline:
                            self.assertIn('sandbox allow-scripts allow-same-origin', policy)
                            self.assertIn("worker-src 'none'", policy)
                            self.assertIn("form-action 'self'", policy)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)


@unittest.skipUnless(shutil.which('node'), 'Node required for browser-shaped runner stub')
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.export = self.project / 'build/play'
        self.export.mkdir(parents=True)
        self.files = {'index.html': b'<p id="status">Loading</p>'}
        for path, data in self.files.items():
            (self.export / path).write_bytes(data)
        self.admitted = {'directory': 'build/play', 'pins': {
            'build/play/' + path: {'sha256': hashlib.sha256(data).hexdigest(), 'byteCount': len(data)}
            for path, data in self.files.items()}}
        self.admit = patch.dict(sys.modules, {'web_revision': types.SimpleNamespace(
            accept_export=lambda project, directory: self.admitted)})
        self.admit.start()
        self.addCleanup(self.admit.stop)

    def execute(self, mode='normal', case=None):
        test = self
        class Client:
            closed = False
            def run(self, code):
                result = subprocess.run(['node', '-e', NODE_STUB], input=json.dumps({
                    'code': code, 'mode': mode}),
                    text=True, capture_output=True, timeout=5, check=True)
                response = json.loads(result.stdout)
                if 'error' in response:
                    test.assertTrue(response['closed'])
                    raise ValueError(response['error'])
                return response['report']
            def close(self):
                self.closed = True
        client = Client()
        with patch.object(web_regression.playcheck_browser, 'MCP', return_value=client):
            try:
                return web_regression.run_case(self.project, self.export, case or CASE)
            finally:
                self.assertTrue(client.closed)

    def test_async_transition_action_sequence_and_inventory(self):
        report = self.execute()
        self.assertTrue(report['passed'])
        self.assertEqual(report['status'], 'passed')
        self.assertIsNone(report['failed_assertion'])
        self.assertEqual([o['action'] for o in report['observations']], ['click', 'press', 'expect_text'])
        self.assertEqual(report['observations'][-1]['observed']['text'], 'Ready')

    def test_text_timeout_and_missing_target_are_observed_mismatches(self):
        for mode in ('mismatch', 'missing'):
            with self.subTest(mode=mode):
                report = self.execute(mode)
                self.assertFalse(report['passed'])
                self.assertEqual(report['status'], 'assertion_failed')
                self.assertEqual(report['failed_assertion']['step'], 2)
                self.assertFalse(report['failed_assertion']['observed']['matched'])

    def test_assertion_quotes_are_data(self):
        case = json.loads(json.dumps(CASE))
        case['steps'][-1]['expect_text']['contains'] = "Ready'; throw Error('injected')"
        report = self.execute(case=case)
        self.assertEqual(report['status'], 'assertion_failed')
        self.assertEqual(report['failed_assertion']['contains'], case['steps'][-1]['expect_text']['contains'])

    def test_operational_errors_never_count_as_reproduction(self):
        for mode in ('resource', 'pageerror', 'console', 'navigation', 'external', 'action', 'lateerror',
                     'externalform', 'popup', 'unexpected', 'blocked'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'no assertion verdict'):
                self.execute(mode)

    def test_transport_and_bad_result_are_operational_errors(self):
        from unittest.mock import Mock
        for result in ({'passed': False}, None):
            client = Mock()
            client.run.return_value = result
            with patch.object(web_regression.playcheck_browser, 'MCP', return_value=client):
                with self.assertRaisesRegex(ValueError, 'Invalid regression'):
                    web_regression.run_case(self.project, self.export, CASE)
            client.close.assert_called_once()
        client = Mock()
        client.run.side_effect = TimeoutError('transport unavailable')
        with patch.object(web_regression.playcheck_browser, 'MCP', return_value=client):
            with self.assertRaisesRegex(ValueError, 'no assertion verdict'):
                web_regression.run_case(self.project, self.export, CASE)
        client.close.assert_called_once()

    def test_changed_bytes_rejected_before_browser(self):
        (self.export / 'index.html').write_text('changed')
        with patch.object(web_regression.playcheck_browser, 'MCP') as client:
            with self.assertRaisesRegex(ValueError, 'changed'):
                web_regression.run_case(self.project, self.export, CASE)
        client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
