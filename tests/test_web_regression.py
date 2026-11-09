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
let now = 0, phase = 0, polls = 0, location = 'about:blank', closed = false, viewportWidth = 1024;
Date.now = () => now;
const events = {}, actions = [];
function nodes(selector) {
  if (selector === 'button#start' && payload.mode === 'missing_start') return [];
  if (selector === '#status') {
    if (phase !== 2) throw Error('Actions out of order');
    polls++;
    if (payload.mode === 'missing') return [];
  }
  if (!['button#start', 'input#control', '#status', '#retry', '#left', '#right', '#overflow', '#vertical'].includes(selector))
    return [];
  const hidden = selector === '#retry' && !['css_override', 'until_found', 'until_found_override'].includes(payload.mode);
  let x = selector === '#right' ? (payload.mode === 'overlap' ? 50 : 120) : selector === '#overflow' ? 350 : 10;
  if (selector === '#overflow' && payload.mode === 'page_overflow') x = viewportWidth - 40;
  const y = selector === '#vertical' ? 2000 : 10;
  const box = {x, y, width: 100, height: 32, left: x, right: x + 100, top: y, bottom: y + 32};
  const controlHidden = selector === 'button#start' && payload.mode === 'hidden_start';
  const element = {
    id: selector.startsWith('#') ? selector.slice(1) : '', tagName: 'DIV',
    parentElement: null, previousElementSibling: null,
    hidden: selector === '#retry',
    getAttribute: name => name === 'hidden' && selector === '#retry'
      ? (['until_found', 'until_found_override'].includes(payload.mode) ? 'until-found' : '') : null,
    getClientRects: () => hidden || controlHidden ? [] : [box],
    getBoundingClientRect: () => box,
    display: hidden || controlHidden ? 'none' : 'block',
    matches: query => query === ':disabled' && ['disabled_start', 'fieldset_disabled'].includes(payload.mode),
    hasAttribute: () => false,
    closest: name => name === '[aria-disabled="true"]' && payload.mode === 'aria_disabled' ? {}
      : name === 'a[href]' && ['external', 'popup'].includes(payload.mode)
        ? {href: payload.mode === 'external' ? 'https://outside.invalid/' : location,
           target: payload.mode === 'popup' ? '_blank' : ''}
        : name === 'form' && payload.mode === 'externalform' ? {action: 'https://outside.invalid/'} : null,
    get innerText() {
      return ['mismatch', 'lateerror'].includes(payload.mode) || polls < 3 ? 'Loading' : 'Ready';
    }
  };
  return payload.mode === 'ambiguous' ? [element, element] : [element];
}
global.NodeFilter = {SHOW_ELEMENT: 1};
global.document = {get baseURI() { return location; }, body: nodes('#left')[0],
  documentElement: {get clientWidth() { return viewportWidth; },
    get scrollWidth() { return viewportWidth + (payload.mode === 'page_overflow' ? 60 : 0); }},
  createTreeWalker: () => {
    let walked = false;
    return {currentNode: document.body, nextNode: () => {
      if (walked) return null;
      walked = true; return nodes('#overflow')[0];
    }};
  },
  querySelector: selector => selector === 'base[target]' ? null : nodes(selector)[0],
  querySelectorAll: selector => selector === '[hidden]' ? nodes('#retry') : nodes(selector)};
global.getComputedStyle = element => ({visibility: 'visible', display: element.display,
  contentVisibility: payload.mode === 'until_found' ? 'hidden' : 'visible'});
const nativeFetch = global.fetch;
global.fetch = async address => payload.mode === 'resource' ? {ok: false}
  : nativeFetch(new URL(address, location));
const target = {
  on: (event, listener) => { events[event] = listener; },
  setViewportSize: async size => { viewportWidth = size.width; },
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
      if (selector !== 'css=button#start' || options.timeout !== 1000 || phase !== 0)
        throw Error('Wrong click');
      actions.push('click'); phase = 1;
      if (payload.mode === 'blocked') events.console({type: () => 'error'});
    },
    press: async (key, options) => {
      if (selector !== 'css=input#control' || key !== 'Enter' || options.timeout !== 1000 || phase !== 1)
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
    if (!closed) throw Error('Incomplete lifecycle');
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

    def test_viewport_and_new_assertion_contracts(self):
        valid = [
            {'expect_control': {'selector': '#start', 'state': state}}
            for state in ('visible', 'hidden', 'enabled', 'disabled')]
        valid += [{'expect_layout': {'selector': '#panel', 'relation': 'inside_viewport'}},
                  {'expect_layout': {'selector': '#panel', 'relation': 'separate', 'other': '#controls'}},
                  {'expect_page': 'fits_viewport'}, {'expect_page': 'respects_hidden'}]
        for step in valid:
            case = {'schema_version': 1, 'viewport': {'width': 240, 'height': 4096}, 'steps': [step]}
            self.assertEqual(web_regression.parse_case(json.dumps(case).encode()), case)
        invalid = [
            {'expect_control': {'selector': '#x', 'state': 'absent'}},
            {'expect_control': {'selector': '#x', 'state': []}},
            {'expect_layout': {'selector': '#x', 'relation': 'separate'}},
            {'expect_layout': {'selector': '#x', 'relation': 'inside_viewport', 'other': '#y'}},
            {'expect_layout': {'selector': '#x', 'relation': 'separate', 'other': 'https://outside.invalid'}},
            {'expect_layout': {'selector': '#x', 'relation': 'overlaps'}},
            {'expect_page': 'visible'}, {'expect_page': {'check': 'fits_viewport'}}]
        for step in invalid:
            with self.subTest(step=step), self.assertRaises(ValueError):
                web_regression.parse_case(json.dumps({'schema_version': 1, 'steps': [step]}).encode())
        for viewport in ({'width': 239, 'height': 844}, {'width': 390, 'height': 4097},
                         {'width': True, 'height': 844}, {'width': 390.0, 'height': 844},
                         {'width': 390}, {'width': 390, 'height': 844, 'scale': 2}, None):
            with self.subTest(viewport=viewport), self.assertRaises(ValueError):
                web_regression.parse_case(json.dumps({**CASE, 'viewport': viewport}).encode())

    def test_operational_diagnostic_cannot_copy_untrusted_messages(self):
        error = web_regression.RegressionOperationalError({
            'category': 'action', 'fault': 'control_disabled', 'step': 3,
            'resource': 'https://outside.invalid/secret', 'message': 'secret page text',
            'observed': {'found': True, 'count': 1, 'text': 'secret page text',
                         'rect': {'x': float('inf'), 'y': 0, 'width': 10, 'height': 10}}})
        self.assertEqual(error.diagnostic, {'category': 'action', 'fault': 'control_disabled',
                                          'step': 3, 'observed': {'found': True, 'count': 1}})
        self.assertNotIn('secret', str(error))
        fallback = web_regression.RegressionOperationalError({'category': [], 'fault': 'secret', 'step': True})
        self.assertEqual(fallback.diagnostic, {'category': 'runner', 'fault': 'invalid_result', 'step': None})

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

    def assertion(self, action, value, mode='normal', viewport=None):
        case = {'schema_version': 1, 'steps': [{action: value}]}
        if viewport is not None:
            case['viewport'] = viewport
        return self.execute(mode=mode, case=case)

    def test_hidden_means_rendered_css_state_and_requires_a_matching_element(self):
        assertion = {'selector': '#retry', 'state': 'hidden'}
        self.assertTrue(self.assertion('expect_control', assertion)['passed'])
        report = self.assertion('expect_control', assertion, mode='css_override')
        self.assertFalse(report['passed'])
        self.assertTrue(report['failed_assertion']['observed']['visible'])
        report = self.assertion('expect_control', {'selector': '#typo', 'state': 'hidden'})
        self.assertFalse(report['passed'])
        self.assertFalse(report['failed_assertion']['observed']['found'])

    def test_enabled_and_disabled_require_rendered_native_or_accessibility_state(self):
        for mode in ('disabled_start', 'fieldset_disabled', 'aria_disabled'):
            with self.subTest(mode=mode):
                report = self.assertion('expect_control', {'selector': 'button#start', 'state': 'disabled'}, mode=mode)
                self.assertTrue(report['passed'])
                self.assertFalse(report['observations'][0]['observed']['enabled'])
                self.assertFalse(self.assertion('expect_control', {
                    'selector': 'button#start', 'state': 'enabled'}, mode=mode)['passed'])
        self.assertTrue(self.assertion('expect_control', {'selector': 'button#start', 'state': 'enabled'})['passed'])
        for state in ('visible', 'enabled', 'disabled'):
            self.assertFalse(self.assertion('expect_control', {'selector': '#retry', 'state': state})['passed'])

    def test_horizontal_viewport_fit_ignores_vertical_scroll_and_records_css_rects(self):
        viewport = {'width': 390, 'height': 844}
        report = self.assertion('expect_layout', {'selector': '#vertical', 'relation': 'inside_viewport'}, viewport=viewport)
        self.assertTrue(report['passed'])
        observed = report['observations'][0]['observed']
        self.assertEqual(observed['viewport_width'], 390)
        self.assertEqual(observed['rect'], {'x': 10, 'y': 2000, 'width': 100, 'height': 32})
        assertion = {'selector': '#overflow', 'relation': 'inside_viewport'}
        self.assertFalse(self.assertion('expect_layout', assertion, viewport=viewport)['passed'])
        self.assertTrue(self.assertion('expect_layout', assertion)['passed'])

    def test_separate_requires_two_rendered_nonoverlapping_elements(self):
        assertion = {'selector': '#left', 'relation': 'separate', 'other': '#right'}
        self.assertTrue(self.assertion('expect_layout', assertion)['passed'])
        report = self.assertion('expect_layout', assertion, mode='overlap')
        self.assertFalse(report['passed'])
        self.assertEqual(report['failed_assertion']['observed']['other']['rect']['x'], 50)
        for other in ('#typo', '#retry'):
            self.assertFalse(self.assertion('expect_layout', {**assertion, 'other': other})['passed'])

    def test_page_viewport_uses_scroll_width_and_returns_first_overflow_hint(self):
        viewport = {'width': 390, 'height': 844}
        self.assertTrue(self.assertion('expect_page', 'fits_viewport', viewport=viewport)['passed'])
        report = self.assertion('expect_page', 'fits_viewport', mode='page_overflow', viewport=viewport)
        self.assertFalse(report['passed'])
        self.assertEqual(report['failed_assertion']['check'], 'fits_viewport')
        observed = report['failed_assertion']['observed']
        self.assertEqual((observed['viewport_width'], observed['scroll_width']), (390, 450))
        self.assertEqual(observed['selector'], '#overflow')
        self.assertEqual(observed['rect'], {'x': 350, 'y': 10, 'width': 100, 'height': 32})

    def test_page_hidden_rule_detects_css_overriding_hidden_without_reading_contents(self):
        self.assertTrue(self.assertion('expect_page', 'respects_hidden')['passed'])
        report = self.assertion('expect_page', 'respects_hidden', mode='css_override')
        self.assertFalse(report['passed'])
        self.assertEqual(report['failed_assertion']['observed']['selector'], '#retry')
        self.assertNotIn('text', report['failed_assertion']['observed'])
        self.assertEqual(len(report['failed_assertion']['observed']['rect']), 4)

    def test_page_hidden_rule_respects_until_found_while_contents_remain_hidden(self):
        self.assertTrue(self.assertion('expect_page', 'respects_hidden', mode='until_found')['passed'])
        report = self.assertion('expect_page', 'respects_hidden', mode='until_found_override')
        self.assertFalse(report['passed'])
        self.assertEqual(report['failed_assertion']['observed']['selector'], '#retry')

    def test_page_rules_preserve_operational_health_distinction(self):
        with self.assertRaises(web_regression.RegressionOperationalError) as raised:
            self.assertion('expect_page', 'fits_viewport', mode='console')
        self.assertEqual(raised.exception.diagnostic['category'], 'page')

    def test_missing_hidden_or_disabled_start_are_action_diagnostics(self):
        for mode, fault in (('missing_start', 'control_missing'), ('hidden_start', 'control_hidden'),
                            ('disabled_start', 'control_disabled')):
            with self.subTest(mode=mode), self.assertRaises(web_regression.RegressionOperationalError) as raised:
                self.execute(mode)
            diagnostic = raised.exception.diagnostic
            self.assertEqual((diagnostic['category'], diagnostic['fault'], diagnostic['step']), ('action', fault, 0))
            self.assertEqual(diagnostic['observed']['found'], mode != 'missing_start')
            if mode != 'missing_start':
                self.assertEqual(diagnostic['observed']['rect']['width'], 100)

    def test_diagnostics_identify_safe_resource_and_failed_step_without_page_text(self):
        for mode, category, fault, step in [
            ('resource', 'resource', 'http_failure', None),
            ('pageerror', 'page', 'page_error', 0),
            ('navigation', 'navigation', 'navigation_failed', None),
            ('unexpected', 'navigation', 'unexpected_origin', 1),
            ('action', 'action', 'action_failed', 0),
            ('external', 'navigation', 'unsafe_control', 0),
            ('ambiguous', 'action', 'selector_ambiguous', 0)]:
            with self.subTest(mode=mode), self.assertRaises(web_regression.RegressionOperationalError) as raised:
                self.execute(mode)
            diagnostic = raised.exception.diagnostic
            self.assertEqual((diagnostic['category'], diagnostic['fault'], diagnostic['step']), (category, fault, step))
            self.assertNotIn('secret', json.dumps(diagnostic))
            self.assertNotIn('outside.invalid', str(raised.exception))
            if mode == 'resource':
                self.assertEqual(diagnostic['resource'], 'index.html')

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
