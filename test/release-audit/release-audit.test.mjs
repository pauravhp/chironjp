import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { audit } from '../../scripts/release-audit.mjs';

const fixtureRoot = new URL('./fixtures/', import.meta.url);

test('accepts an intentionally public fixture', async () => {
  const result = await audit(new URL('safe/', fixtureRoot));
  assert.deepEqual(result.findings, []);
});

test('finds release-blocking classes in a runtime-only unsafe fixture', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'chiron-release-audit-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(path.join(root, 'LICENSE'), 'MIT\n');
  const privateSource = [['job', 'pipe'].join(''), 'chiron'].join('-');
  const privateSourceAliases = [
    [['job', 'pipe'].join(''), 'chiron'].join(' '),
    [['job', 'pipe'].join(''), 'chiron'].join('_'),
    [['job', 'pipe'].join(''), 'chiron'].join('-'),
    ['job', 'pipe', 'chiron'].join(''),
  ];
  const forbiddenAliases = [
    ['intern', 'insider'].join(' '),
    ['intern', 'insider'].join('_'),
    ['intern', 'insider'].join('-'),
    ['intern', 'insider'].join(''),
  ];
  const unsafeText = [
    ['Copied from /', ['home', 'alice', 'private-work', privateSource, 'config.json'].join('/')].join(''),
    `Private source aliases: ${privateSourceAliases.join(', ')}`,
    ['Private endpoint ', ['192', '168', '10', '22'].join('.'), ':8080'].join(''),
    `Aliases: ${forbiddenAliases.join(', ')}`,
    ['Contact ', ['recruiting-person', 'real-company.co'].join('@'), ' or ', ['+49', '30', '1234', '5678'].join(' ')].join(''),
    [['full', 'name'].join('_'), ' = "Private Candidate"'].join(''),
    ['AWS_ACCESS_KEY_ID=', ['AKIA', 'IOSFODNN7EXAMPLE'].join('')].join(''),
    [["pass", "word"].join(''), '=', ['correct', 'horse', 'battery', 'staple'].join('-')].join(''),
    [['OP', 'CONNECT', 'TOKEN'].join('_'), ['live', 'connect', 'credential', 'value'].join('-')].join('='),
    [['OP', 'SERVICE', 'ACCOUNT', 'TOKEN'].join('_'), ['live', 'service', 'credential', 'value'].join('-')].join('='),
    [['CHIRONJP', 'REVIEW', 'PASSWORD', 'HASH'].join('_'), ['live', 'review', 'password', 'digest'].join('-')].join('='),
    ['Source: ', ['https:/', 'github.com', 'acme', 'private-adapter'].join('/')].join(''),
  ].join('\n');
  await writeFile(path.join(root, 'private-notes.txt'), unsafeText);
  await writeFile(path.join(root, 'session.log'), 'application state must not be published\n');
  await writeFile(path.join(root, 'form-screenshot.png'), 'runtime detector fixture\n');
  await mkdir(path.join(root, '__pycache__'));
  await writeFile(path.join(root, '__pycache__', 'candidate.pyc'), 'runtime detector fixture\n');

  const result = await audit(root);
  const codes = new Set(result.findings.map((finding) => finding.code));

  for (const expected of [
    'AWS_ACCESS_KEY',
    'EMAIL_ADDRESS',
    'FORBIDDEN_PRIVATE_SOURCE',
    'FORBIDDEN_PRODUCT_NAME',
    'IDENTITY_VALUE',
    'MISSING_UPSTREAM_NOTICE',
    'PHONE_NUMBER',
    'PRIVATE_HOME_PATH',
    'PRIVATE_IPV4',
    'RISKY_GENERATED_FILE',
    'RISKY_LOG',
    'RISKY_SCREENSHOT',
    'SECRET_ASSIGNMENT',
  ]) {
    assert.ok(codes.has(expected), `expected ${expected}; got ${[...codes].join(', ')}`);
  }
  assert.equal(
    result.findings.filter((finding) => finding.code === 'FORBIDDEN_PRODUCT_NAME').length,
    4,
  );
  assert.equal(
    result.findings.filter((finding) => finding.code === 'FORBIDDEN_PRIVATE_SOURCE').length,
    5,
  );
  assert.ok(
    result.findings.filter((finding) => finding.code === 'SECRET_ASSIGNMENT').length >= 4,
  );
});

test('flags a symlink that escapes the release root', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'chiron-release-audit-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(path.join(root, 'LICENSE'), 'MIT\n');
  await symlink('/etc/hosts', path.join(root, 'host-link'));

  const result = await audit(root);
  assert.ok(result.findings.some((finding) => finding.code === 'EXTERNAL_SYMLINK'));
});

test('does not descend into dependency or VCS directories', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'chiron-release-audit-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(path.join(root, 'LICENSE'), 'MIT\n');
  for (const directory of ['.git', 'node_modules', '.venv']) {
    await mkdir(path.join(root, directory));
    await writeFile(path.join(root, directory, 'secret.env'), ['password', 'not-a-public-secret-value'].join('='));
  }

  const result = await audit(root);
  assert.deepEqual(result.findings, []);
});

test('requires each declared direct upstream in an existing notice', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'chiron-release-audit-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(path.join(root, 'LICENSE'), 'MIT\n');
  await writeFile(path.join(root, 'README.md'), ['Derived', 'from', 'acme/upstream.'].join(' '));
  await writeFile(path.join(root, 'THIRD_PARTY_NOTICES.md'), 'Unrelated project notice.\n');

  const result = await audit(root);
  assert.ok(result.findings.some((finding) => finding.code === 'MISSING_UPSTREAM_ATTRIBUTION'));
});
