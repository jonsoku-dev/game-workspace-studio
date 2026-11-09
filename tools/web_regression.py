"""Run bounded normal-control regression cases against admitted web exports."""
import json
from pathlib import Path
import re
import threading

import playcheck_browser


MAX_CASE_BYTES = 16 * 1024
MAX_STEPS = 16
KEYS = {'Enter', 'Space', 'Tab', 'Escape', 'Backspace', 'Delete',
        'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'}


def parse_case(data: bytes) -> dict:
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_CASE_BYTES:
        raise ValueError('Regression case must be 1..16384 bytes')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate regression case field')
            result[key] = value
        return result
    try:
        case = json.loads(data, object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError('Invalid regression case JSON') from error
    if (not isinstance(case, dict) or set(case) != {'schema_version', 'steps'}
            or type(case['schema_version']) is not int or case['schema_version'] != 1
            or not isinstance(case['steps'], list) or not 1 <= len(case['steps']) <= MAX_STEPS):
        raise ValueError('Expected schema_version 1 and 1..16 steps')
    def text(value, limit):
        return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
                and not any(ord(c) < 32 or ord(c) == 127 for c in value))
    def selector(value):
        return (text(value, 240) and re.match(r'[a-zA-Z#.*\[]', value)
                and not any(token in value for token in ('>>', '://', 'javascript:', 'xpath=', 'css=')))
    for step in case['steps']:
        if not isinstance(step, dict) or len(step) != 1:
            raise ValueError('Expected one action per regression step')
        action, value = next(iter(step.items()))
        if action == 'click':
            valid = selector(value)
        elif action == 'press':
            valid = (isinstance(value, dict) and set(value) == {'selector', 'key'}
                     and selector(value['selector']) and isinstance(value['key'], str)
                     and (value['key'] in KEYS or re.fullmatch(r'[a-zA-Z0-9]', value['key'])))
        elif action == 'expect_text':
            valid = (isinstance(value, dict) and set(value) == {'selector', 'contains'}
                     and selector(value['selector']) and text(value['contains'], 512))
        else:
            valid = False
        if not valid:
            raise ValueError('Expected bounded click, press or expect_text step')
    if 'expect_text' not in case['steps'][-1]:
        raise ValueError('Final regression step must assert nonempty text')
    return case


_RUN = r"""
const target = await context.newPage();
let faults = 0;
const observations = [];
let failed = null;
try {
  target.on('pageerror', () => { faults++; });
  target.on('console', message => { if (message.type() === 'error') faults++; });
  await target.goto(origin + '/index.html', {waitUntil: 'load', timeout: 5000});
  async function healthy() {
    if (faults || new URL(await target.url()).origin !== origin) throw Error('Page or resource failure');
  }
  const served = await target.evaluate(async paths => {
    const out = {};
    for (const path of paths) {
      const response = await fetch('/' + path);
      if (!response.ok) throw Error('Export resource unavailable');
      const bytes = await response.arrayBuffer();
      out[path] = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
        .map(value => value.toString(16).padStart(2, '0')).join('');
    }
    return out;
  }, Object.keys(pins));
  if (JSON.stringify(served) !== JSON.stringify(pins)) throw Error('Served inventory mismatch');
  for (let index = 0; index < steps.length; index++) {
    await healthy();
    const step = steps[index];
    if (step.click !== undefined || step.press !== undefined) {
      await target.evaluate(({selector, origin}) => {
        const elements = document.querySelectorAll(selector);
        if (elements.length !== 1) return;
        const element = elements[0];
        const anchor = element.closest('a[href]');
        const form = element.form || element.closest('form');
        for (const node of [anchor, form].filter(Boolean)) {
          const address = node === anchor ? node.href
            : element.hasAttribute('formaction') ? element.formAction : node.action;
          const destination = element.formTarget || node.target || document.querySelector('base[target]')?.target;
          if (new URL(address, document.baseURI).origin !== origin
              || (destination && destination !== '_self')) throw Error('Unsafe navigation control');
        }
      }, {selector: step.click ?? step.press.selector, origin});
    }
    if (step.click !== undefined) {
      await target.locator('css=' + step.click).click({timeout: 2000});
      observations.push({step: index, action: 'click', completed: true});
    } else if (step.press !== undefined) {
      await target.locator('css=' + step.press.selector).press(step.press.key, {timeout: 2000});
      observations.push({step: index, action: 'press', completed: true});
    } else {
      const assertion = step.expect_text;
      const until = Date.now() + 2000;
      let observed;
      do {
        observed = await target.evaluate(assertion => {
          const nodes = document.querySelectorAll(assertion.selector);
          if (nodes.length > 1) throw Error('Assertion selector must be unique');
          const element = nodes[0];
          const visible = !!element && !!element.getClientRects().length
            && getComputedStyle(element).visibility !== 'hidden';
          const text = visible ? (element.innerText ?? element.textContent ?? '') : '';
          return {found: !!element, visible, matched: visible && text.includes(assertion.contains),
                  text: text.slice(0, 1024)};
        }, assertion);
        if (observed.matched) break;
        await target.waitForTimeout(75);
      } while (Date.now() < until);
      const record = {step: index, action: 'expect_text', ...assertion, observed};
      observations.push(record);
      if (!observed.matched) { await healthy(); failed = record; break; }
    }
    await healthy();
  }
  await target.waitForTimeout(100);
  await healthy();
  return {passed: failed === null, status: failed === null ? 'passed' : 'assertion_failed',
          observations, failed_assertion: failed, browser_observed_hashes: served};
} finally {
  await target.close();
}
"""


def run_case(project: Path, export_dir: Path, case: dict) -> dict:
    """Raise on operational failures; only observed mismatches return passed=False."""
    import web_revision
    case = parse_case(json.dumps(case).encode())
    project = Path(project).resolve(strict=True)
    export_dir = Path(export_dir).resolve(strict=True)
    admitted = web_revision.accept_export(project, export_dir.relative_to(project).as_posix())
    prefix = admitted['directory'] + '/'
    if any(not path.startswith(prefix) for path in admitted['pins']):
        raise ValueError('Export inventory escapes admitted directory')
    pins = {path[len(prefix):]: pin['sha256'] for path, pin in admitted['pins'].items()}
    server = playcheck_browser.inventory_server(export_dir, pins, inline=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = None
    try:
        # A new MCP process launches its own local browser; never reuse a caller's page.
        client = playcheck_browser.MCP()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        code = ('const origin = ' + json.dumps(origin) + ';\nconst pins = ' + json.dumps(pins)
                + ';\nconst steps = ' + json.dumps(case['steps']) + ';\n' + _RUN)
        try:
            report = client.run(code)
        except Exception as error:
            raise ValueError('Regression browser execution failed; no assertion verdict') from error
        if (not isinstance(report, dict) or type(report.get('passed')) is not bool
                or report.get('status') != ('passed' if report['passed'] else 'assertion_failed')
                or not isinstance(report.get('observations'), list)
                or (report['passed'] and report.get('failed_assertion') is not None)
                or (not report['passed'] and not isinstance(report.get('failed_assertion'), dict))
                or report.get('browser_observed_hashes') != pins):
            raise ValueError('Invalid regression browser result')
        observations = report['observations']
        if (not observations or len(observations) > len(case['steps'])
                or (report['passed'] and len(observations) != len(case['steps']))
                or not isinstance(observations[-1], dict)
                or observations[-1].get('action') != 'expect_text'
                or not isinstance(observations[-1].get('observed'), dict)
                or observations[-1].get('observed', {}).get('matched') is not report['passed']
                or (not report['passed'] and report['failed_assertion'] != observations[-1])):
            raise ValueError('Invalid regression assertion evidence')
        # Re-admit after execution so a changed receipt/source cannot become evidence.
        if web_revision.accept_export(project, admitted['directory']) != admitted:
            raise ValueError('Export changed during regression execution')
        return {**report, 'driver': 'stagehand-mcp'}
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
