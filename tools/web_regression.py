"""Run bounded normal-control regression cases against admitted web exports."""
import json
import math
from pathlib import Path
import re
import threading

import playcheck_browser


MAX_CASE_BYTES = 16 * 1024
MAX_STEPS = 16
KEYS = {'Enter', 'Space', 'Tab', 'Escape', 'Backspace', 'Delete',
        'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'}
ASSERTIONS = {'expect_text', 'expect_control', 'expect_layout', 'expect_page'}
FAULTS = {
    'setup': {'browser_start', 'browser_page', 'viewport', 'server_start', 'browser_close'},
    'navigation': {'navigation_failed', 'unexpected_origin', 'unsafe_control'},
    'resource': {'http_failure', 'inventory_mismatch'},
    'page': {'page_error', 'console_error'},
    'action': {'control_missing', 'control_hidden', 'control_disabled', 'selector_ambiguous', 'action_failed'},
    'runner': {'evaluation_failed', 'invalid_result'},
    'transport': {'transport_failed'},
    'export': {'export_admission', 'export_changed'},
}


class RegressionOperationalError(ValueError):
    """Bounded diagnostics safe for reports, without browser messages or URLs."""
    def __init__(self, diagnostic):
        if not isinstance(diagnostic, dict):
            diagnostic = {}
        category, fault = diagnostic.get('category'), diagnostic.get('fault')
        if (not isinstance(category, str) or not isinstance(fault, str)
                or category not in FAULTS or fault not in FAULTS[category]):
            category, fault = 'runner', 'invalid_result'
        step = diagnostic.get('step')
        self.diagnostic = {'category': category, 'fault': fault,
                           'step': step if type(step) is int and 0 <= step < MAX_STEPS else None}
        resource = diagnostic.get('resource')
        if (isinstance(resource, str) and 0 < len(resource) <= 240
                and all(part not in ('', '.', '..') for part in resource.split('/'))
                and not any(ord(c) < 32 or c in ':?#%\\' for c in resource)):
            self.diagnostic['resource'] = resource
        observed = diagnostic.get('observed')
        if isinstance(observed, dict):
            safe = {key: observed[key] for key in ('found', 'visible', 'enabled')
                    if type(observed.get(key)) is bool}
            if type(observed.get('count')) is int and 0 <= observed['count'] <= 10000:
                safe['count'] = observed['count']
            rect = observed.get('rect')
            if (isinstance(rect, dict) and set(rect) == {'x', 'y', 'width', 'height'}
                    and all(type(value) in (int, float) and math.isfinite(value)
                            and abs(value) <= 1000000 for value in rect.values())):
                safe['rect'] = rect
            if safe:
                self.diagnostic['observed'] = safe
        label = 'Invalid regression browser result' if fault == 'invalid_result' else 'Regression ' + category + '/' + fault
        super().__init__(label + '; no assertion verdict')


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
    if (not isinstance(case, dict) or not {'schema_version', 'steps'} <= set(case)
            or set(case) - {'schema_version', 'steps', 'viewport'}
            or type(case['schema_version']) is not int or case['schema_version'] != 1
            or not isinstance(case['steps'], list) or not 1 <= len(case['steps']) <= MAX_STEPS):
        raise ValueError('Expected schema_version 1 and 1..16 steps')
    if 'viewport' in case:
        viewport = case['viewport']
        if (not isinstance(viewport, dict) or set(viewport) != {'width', 'height'}
                or any(type(value) is not int or not 240 <= value <= 4096 for value in viewport.values())):
            raise ValueError('Expected viewport width and height integers in 240..4096')
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
        elif action == 'expect_control':
            valid = (isinstance(value, dict) and set(value) == {'selector', 'state'}
                     and selector(value['selector']) and isinstance(value['state'], str)
                     and value['state'] in {'visible', 'hidden', 'enabled', 'disabled'})
        elif action == 'expect_layout':
            valid = (isinstance(value, dict) and isinstance(value.get('relation'), str)
                     and ((value['relation'] == 'inside_viewport' and set(value) == {'selector', 'relation'})
                          or (value['relation'] == 'separate' and set(value) == {'selector', 'relation', 'other'}
                              and selector(value['other'])))
                     and selector(value['selector']))
        elif action == 'expect_page':
            valid = isinstance(value, str) and value in {'fits_viewport', 'respects_hidden'}
        else:
            valid = False
        if not valid:
            raise ValueError('Expected bounded click, press, text, control or layout step')
    if not ASSERTIONS.intersection(case['steps'][-1]):
        raise ValueError('Final regression step must be an assertion')
    return case


_RUN = r"""
let target, result, step = null;
let pending = {category: 'setup', fault: 'browser_page', step};
let fault = null;
const observations = [];
let failed = null;
function fail(category, name, extra = {}) {
  throw {diagnostic: {category, fault: name, step, ...extra}};
}
async function healthy() {
  if (fault) fail('page', fault);
  if (new URL(await target.url()).origin !== origin) fail('navigation', 'unexpected_origin');
}
function inspect({selector, other, contains}) {
  function lookup(selector) {
    const nodes = document.querySelectorAll(selector);
    if (nodes.length > 1) return {found: true, count: Math.min(nodes.length, 10000), ambiguous: true};
    const element = nodes[0];
    if (!element) return {found: false, count: 0, visible: false, enabled: false,
                          rect: null, text: '', matched_text: false};
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const visible = !!element.getClientRects().length && box.width > 0 && box.height > 0
      && style.display !== 'none' && !['hidden', 'collapse'].includes(style.visibility);
    const enabled = !element.matches(':disabled') && !element.closest('[aria-disabled="true"]');
    const bounded = value => Math.max(-1000000, Math.min(1000000, Math.round(value * 100) / 100));
    const text = visible && contains !== undefined ? (element.innerText ?? element.textContent ?? '') : '';
    return {found: true, count: 1, visible, enabled,
      rect: {x: bounded(box.x), y: bounded(box.y), width: bounded(box.width), height: bounded(box.height)},
      raw: {left: box.left, right: box.right, top: box.top, bottom: box.bottom},
      text: text.slice(0, 1024), matched_text: contains !== undefined && visible && text.includes(contains)};
  }
  const first = lookup(selector);
  const second = other === undefined ? null : lookup(other);
  return {first, second, viewport_width: document.documentElement.clientWidth};
}
function inspectPage(check) {
  const root = document.documentElement;
  const bound = value => Math.max(-1000000, Math.min(1000000, Math.round(value * 100) / 100));
  const observed = {matched: true, viewport_width: bound(root.clientWidth), scroll_width: bound(root.scrollWidth)};
  function rendered(element) {
    const box = element.getBoundingClientRect(), style = getComputedStyle(element);
    return element.getClientRects().length && box.width > 0 && box.height > 0
      && style.display !== 'none' && !['hidden', 'collapse'].includes(style.visibility) ? box : null;
  }
  function hint(element, box) {
    const parts = [];
    for (let node = element; node && parts.length < 3; node = node.parentElement) {
      if (/^[-_a-zA-Z][-_a-zA-Z0-9]{0,63}$/.test(node.id ?? '')) {
        parts.unshift('#' + node.id); break;
      }
      const tag = node.tagName.toLowerCase();
      let index = 1;
      for (let sibling = node.previousElementSibling; sibling; sibling = sibling.previousElementSibling)
        if (sibling.tagName === node.tagName) index++;
      parts.unshift(tag + ':nth-of-type(' + index + ')');
    }
    observed.selector = parts.join(' > ').slice(0, 240);
    observed.rect = {x: bound(box.x), y: bound(box.y), width: bound(box.width), height: bound(box.height)};
  }
  if (check === 'respects_hidden') {
    for (const element of document.querySelectorAll('[hidden]')) {
      if (element.getAttribute('hidden')?.toLowerCase() === 'until-found'
          && getComputedStyle(element).contentVisibility === 'hidden') continue;
      const box = rendered(element);
      if (box) { observed.matched = false; hint(element, box); break; }
    }
  } else {
    observed.matched = root.scrollWidth <= root.clientWidth;
    if (!observed.matched) {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
      let element = walker.currentNode;
      while (element) {
        const box = rendered(element);
        if (box && (box.left < 0 || box.right > root.clientWidth)) { hint(element, box); break; }
        element = walker.nextNode();
      }
    }
  }
  return observed;
}
try {
  target = await context.newPage();
  target.on('pageerror', () => { fault = 'page_error'; });
  target.on('console', message => { if (message.type() === 'error') fault = 'console_error'; });
  if (viewport !== null) {
    pending = {category: 'setup', fault: 'viewport', step};
    await target.setViewportSize(viewport);
  }
  pending = {category: 'navigation', fault: 'navigation_failed', step};
  await target.goto(origin + '/index.html', {waitUntil: 'load', timeout: 5000});
  pending = {category: 'runner', fault: 'evaluation_failed', step};
  const inventory = await target.evaluate(async paths => {
    const hashes = {};
    for (const path of paths) {
      try {
        const response = await fetch('/' + path);
        if (!response.ok) return {resource: path};
        const bytes = await response.arrayBuffer();
        hashes[path] = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
          .map(value => value.toString(16).padStart(2, '0')).join('');
      } catch { return {resource: path}; }
    }
    return {hashes};
  }, Object.keys(pins));
  if (inventory.resource !== undefined) fail('resource', 'http_failure', {resource: inventory.resource});
  const served = inventory.hashes;
  if (JSON.stringify(served) !== JSON.stringify(pins)) fail('resource', 'inventory_mismatch');
  for (let index = 0; index < steps.length; index++) {
    step = index;
    pending = {category: 'runner', fault: 'evaluation_failed', step};
    await healthy();
    const current = steps[index];
    const action = Object.keys(current)[0];
    if (action === 'click' || action === 'press') {
      const selector = action === 'click' ? current.click : current.press.selector;
      const until = Date.now() + 2000;
      let state;
      do {
        state = (await target.evaluate(inspect, {selector})).first;
        if (state.ambiguous) fail('action', 'selector_ambiguous', {observed: state});
        if (state.found && state.visible && state.enabled) break;
        await healthy();
        await target.waitForTimeout(75);
      } while (Date.now() < until);
      const observed = {found: state.found, count: state.count, visible: state.visible,
                        enabled: state.enabled, rect: state.rect};
      if (!state.found) fail('action', 'control_missing', {observed});
      if (!state.visible) fail('action', 'control_hidden', {observed});
      if (!state.enabled) fail('action', 'control_disabled', {observed});
      const safe = await target.evaluate(({selector, origin}) => {
        const element = document.querySelector(selector);
        const anchor = element?.closest('a[href]');
        const form = element?.form || element?.closest('form');
        return [anchor, form].filter(Boolean).every(node => {
          const address = node === anchor ? node.href
            : element.hasAttribute('formaction') ? element.formAction : node.action;
          const destination = element.formTarget || node.target || document.querySelector('base[target]')?.target;
          return new URL(address, document.baseURI).origin === origin && (!destination || destination === '_self');
        });
      }, {selector, origin});
      if (!safe) fail('navigation', 'unsafe_control', {observed});
      pending = {category: 'action', fault: 'action_failed', step, observed};
      if (action === 'click') await target.locator('css=' + selector).click({timeout: 1000});
      else await target.locator('css=' + selector).press(current.press.key, {timeout: 1000});
      observations.push({step, action, completed: true});
    } else {
      const assertion = current[action];
      const until = Date.now() + 2000;
      let observed;
      do {
        if (action === 'expect_page') {
          observed = await target.evaluate(inspectPage, assertion);
        } else {
          const state = await target.evaluate(inspect, assertion);
          const first = state.first, second = state.second;
          if (first.ambiguous || second?.ambiguous) fail('action', 'selector_ambiguous');
          const clean = value => ({found: value.found, count: value.count, visible: value.visible,
                                   enabled: value.enabled, rect: value.rect});
          observed = clean(first);
          if (action === 'expect_text') {
            observed.matched = first.matched_text;
            observed.text = first.text.slice(0, 1024);
          } else if (action === 'expect_control') {
            observed.matched = first.found && (assertion.state === 'hidden' ? !first.visible
              : first.visible && (assertion.state === 'visible'
                || (assertion.state === 'enabled' ? first.enabled : !first.enabled)));
          } else {
            observed.viewport_width = state.viewport_width;
            if (assertion.relation === 'inside_viewport') {
              observed.matched = first.visible && first.raw.left >= 0 && first.raw.right <= state.viewport_width;
            } else {
              observed.other = clean(second);
              observed.matched = first.visible && second.visible && (first.raw.right <= second.raw.left
                || second.raw.right <= first.raw.left || first.raw.bottom <= second.raw.top
                || second.raw.bottom <= first.raw.top);
            }
          }
        }
        if (observed.matched) break;
        await healthy();
        await target.waitForTimeout(75);
      } while (Date.now() < until);
      const record = {step, action, ...(action === 'expect_page' ? {check: assertion} : assertion), observed};
      observations.push(record);
      if (!observed.matched) { await healthy(); failed = record; break; }
    }
    await healthy();
  }
  await target.waitForTimeout(100);
  await healthy();
  result = {passed: failed === null, status: failed === null ? 'passed' : 'assertion_failed',
            observations, failed_assertion: failed, browser_observed_hashes: served};
} catch (error) {
  result = {operational_error: error?.diagnostic ?? pending};
} finally {
  if (target) {
    try { await target.close(); }
    catch { result = {operational_error: {category: 'setup', fault: 'browser_close', step}}; }
  }
}
return result;
"""


def run_case(project: Path, export_dir: Path, case: dict) -> dict:
    """Raise on operational failures; only observed mismatches return passed=False."""
    import web_revision
    case = parse_case(json.dumps(case).encode())
    try:
        project = Path(project).resolve(strict=True)
        export_dir = Path(export_dir).resolve(strict=True)
        admitted = web_revision.accept_export(project, export_dir.relative_to(project).as_posix())
    except Exception:
        raise RegressionOperationalError({'category': 'export', 'fault': 'export_admission'}) from None
    prefix = admitted['directory'] + '/'
    if any(not path.startswith(prefix) for path in admitted['pins']):
        raise RegressionOperationalError({'category': 'export', 'fault': 'export_admission'})
    pins = {path[len(prefix):]: pin['sha256'] for path, pin in admitted['pins'].items()}
    try:
        server = playcheck_browser.inventory_server(export_dir, pins, inline=True)
    except ValueError:
        raise RegressionOperationalError({'category': 'export', 'fault': 'export_changed'}) from None
    except Exception:
        raise RegressionOperationalError({'category': 'setup', 'fault': 'server_start'}) from None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = None
    try:
        # A new MCP process launches its own local browser; never reuse a caller's page.
        try:
            client = playcheck_browser.MCP()
        except Exception:
            raise RegressionOperationalError({'category': 'setup', 'fault': 'browser_start'}) from None
        origin = 'http://127.0.0.1:' + str(server.server_port)
        code = ('const origin = ' + json.dumps(origin) + ';\nconst pins = ' + json.dumps(pins)
                + ';\nconst steps = ' + json.dumps(case['steps'])
                + ';\nconst viewport = ' + json.dumps(case.get('viewport')) + ';\n' + _RUN)
        try:
            report = client.run(code)
        except Exception:
            raise RegressionOperationalError({'category': 'transport', 'fault': 'transport_failed'}) from None
        if isinstance(report, dict) and 'operational_error' in report:
            error = RegressionOperationalError(report['operational_error'])
            if error.diagnostic.get('resource') not in pins:
                error.diagnostic.pop('resource', None)
            raise error
        if (not isinstance(report, dict) or type(report.get('passed')) is not bool
                or report.get('status') != ('passed' if report['passed'] else 'assertion_failed')
                or not isinstance(report.get('observations'), list)
                or (report['passed'] and report.get('failed_assertion') is not None)
                or (not report['passed'] and not isinstance(report.get('failed_assertion'), dict))
                or report.get('browser_observed_hashes') != pins):
            raise RegressionOperationalError({'category': 'runner', 'fault': 'invalid_result'})
        observations = report['observations']
        if (not observations or len(observations) > len(case['steps'])
                or (report['passed'] and len(observations) != len(case['steps']))
                or not isinstance(observations[-1], dict)
                or observations[-1].get('action') not in ASSERTIONS
                or not isinstance(observations[-1].get('observed'), dict)
                or observations[-1].get('observed', {}).get('matched') is not report['passed']
                or (not report['passed'] and report['failed_assertion'] != observations[-1])):
            raise RegressionOperationalError({'category': 'runner', 'fault': 'invalid_result'})
        # Re-admit after execution so a changed receipt/source cannot become evidence.
        try:
            unchanged = web_revision.accept_export(project, admitted['directory']) == admitted
        except Exception:
            unchanged = False
        if not unchanged:
            raise RegressionOperationalError({'category': 'export', 'fault': 'export_changed'})
        return {**report, 'driver': 'stagehand-mcp'}
    finally:
        try:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    raise RegressionOperationalError({'category': 'setup', 'fault': 'browser_close'}) from None
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
