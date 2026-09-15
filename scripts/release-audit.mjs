#!/usr/bin/env node

/**
 * A dependency-free, conservative audit for material that must not enter a
 * public release. It is a guardrail, not a substitute for human review or a
 * secret scanner maintained by a security team.
 */

import { lstat, readFile, readdir, realpath } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import path from 'node:path';
import process from 'node:process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

const execFileAsync = promisify(execFile);

const MAX_TEXT_BYTES = 2 * 1024 * 1024;

const SKIPPED_DIRECTORY_NAMES = new Set([
  '.git',
  '.hg',
  '.svn',
  '.pnpm-store',
  '.tox',
  '.venv',
  '.yarn',
  'bower_components',
  'node_modules',
  'venv',
]);

const TEXT_EXTENSIONS = new Set([
  '', '.c', '.conf', '.cpp', '.css', '.csv', '.env', '.go', '.h', '.html',
  '.ini', '.java', '.js', '.json', '.jsonl', '.jsx', '.md', '.mjs', '.py',
  '.rb', '.rs', '.sh', '.sql', '.svg', '.toml', '.ts', '.tsx', '.txt',
  '.xml', '.yaml', '.yml',
]);

const RISKY_FILE_PATTERNS = [
  ['RISKY_ENV_FILE', /(^|\/)(?:\.env(?:\..+)?|credentials?|secrets?)(?:$|\.)/i,
    'environment or credential file'],
  ['RISKY_PRIVATE_KEY', /\.(?:key|pem|p12|pfx|jks)$/i, 'private-key container'],
  ['RISKY_DATASTORE', /\.(?:db|sqlite|sqlite3|mdb)$/i, 'local datastore'],
  ['RISKY_LOG', /\.(?:log|jsonl|har)$/i, 'log, event stream, or browser archive'],
  ['RISKY_APPLICATION_RECORD', /(^|\/)(?:applications?|submissions?)(?:[-_.][^/]*|\/[^/]+)\.(?:csv|json|jsonl|ndjson|ya?ml)$/i,
    'candidate or application record'],
  ['RISKY_SCREENSHOT', /(^|\/)(?:screenshots?|captures?|recordings?)(?:\/|[-_.])|(?:^|\/).*screenshot.*\.(?:png|jpe?g|webp|gif)$/i,
    'screen capture or recording'],
  ['RISKY_RESUME_EXPORT', /(^|\/)(?:resume|cv|cover[-_ ]?letter)[-_ ].*\.(?:pdf|docx?|odt|rtf)$/i,
    'candidate document export'],
  ['RISKY_ARCHIVE', /\.(?:7z|rar|tar|tgz|zip)$/i, 'archive that needs explicit review'],
  ['RISKY_GENERATED_FILE', /(^|\/)(?:__pycache__\/|\.DS_Store$|Thumbs\.db$)|\.(?:py[co]|swp|swo|tmp|bak)$/i,
    'generated cache, editor, or backup file'],
];

const SECRET_PATTERNS = [
  ['PRIVATE_KEY', /-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----/g,
    'private-key material'],
  ['AWS_ACCESS_KEY', /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g, 'AWS access key'],
  ['GITHUB_TOKEN', /\b(?:gh[opusr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b/g,
    'GitHub access token'],
  ['SLACK_TOKEN', /\bxox[baprs]-[A-Za-z0-9-]{20,}\b/g, 'Slack token'],
  ['BEARER_TOKEN', /\bBearer\s+[A-Za-z0-9._~+\/-]{20,}={0,2}\b/gi, 'bearer token'],
  ['SECRET_ASSIGNMENT', /\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|secret[_-]?key)\b\s*[:=]\s*["']?([^\s"'`,;}{]{12,})/gi,
    'hard-coded credential-like value'],
];

const PRIVATE_PATH_PATTERNS = [
  ['PRIVATE_HOME_PATH', /(?:^|[\s"'`(=])\/(?:home|Users)\/[A-Za-z0-9._-]+\//gm,
    'absolute user-home path'],
  ['WINDOWS_USER_PATH', /\b[A-Za-z]:\\Users\\[^\\\s"']+\\/g,
    'absolute Windows user-home path'],
  ['PRIVATE_IPV4', /\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})\b/g,
    'private or carrier-grade NAT address'],
  ['MAC_ADDRESS', /\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b/g, 'machine MAC address'],
];

const IDENTITY_PATTERNS = [
  ['EMAIL_ADDRESS', /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, 'non-example email address'],
  ['PHONE_NUMBER', /(?:^|[^\w])(?:\+|00)\d{1,3}[ .()-]?\d{2,4}(?:[ .()-]?\d{2,4}){2,4}\b/g,
    'international phone number'],
  ['IDENTITY_VALUE', /["']?(?:full[_ -]?name|legal[_ -]?name|date[_ -]?of[_ -]?birth|birth[_ -]?date|street[_ -]?address|home[_ -]?address)["']?\s*[:=]\s*["']([^"'\n]{3,})["']/gi,
    'candidate identity field with a populated value'],
];

const FORBIDDEN_SOURCE_NAMES = [
  ['FORBIDDEN_PRIVATE_SOURCE', new RegExp(['jobpipe', 'chiron'].join('-'), 'gi'),
    'private source-tree name'],
  ['FORBIDDEN_PRODUCT_NAME', new RegExp(['intern', 'insider'].join('[\\s_-]*'), 'gi'),
    'forbidden private product/source name'],
];

const LICENSE_REVIEW_PATTERN = new RegExp(
  `\\b(?:${[['A', 'GPL'], ['Aff', 'ero'], ['GPL', '-[23]'], ['SS', 'PL'], ['BU', 'SL'], ['Business', ' Source License']]
    .map((parts) => parts.join('')).join('|')})\\b`,
  'gi',
);
const UPSTREAM_SOURCE_PATTERN = /github\.com\/(?!features(?:\/|\b)|sponsors(?:\/|\b)|security(?:\/|\b))[^\s)>'"]+\/[^\s)>'"#]+/gi;
const UPSTREAM_SHORTHAND_PATTERN = /\b(?:adapted|derived|copied)\s+(?:in\s+part\s+)?(?:from|of)\s+([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)/gi;
const NOTICE_FILE_PATTERN = /^(?:THIRD_PARTY_NOTICES?|NOTICE)(?:\.|$)/i;

function repositorySlug(reference) {
  return reference
    .replace(/^https?:\/\/github\.com\//i, '')
    .split(/[/?#]/)
    .slice(0, 2)
    .join('/')
    .replace(/\.git$/i, '');
}

function isPlaceholder(value) {
  const normalized = value.toLowerCase();
  return /^(?:changeme|dummy|example|fake|placeholder|redacted|replace[_-]?me|test|your[_-]?)/.test(normalized)
    || /^(?:x+|\*+|<[^>]+>|\$\{[^}]+\})$/i.test(value);
}

function isExampleEmail(value) {
  const domain = value.toLowerCase().split('@').at(-1);
  return domain === 'example.com' || domain === 'example.org' || domain === 'example.net'
    || domain === 'example.invalid' || domain.endsWith('.example.invalid')
    || domain === 'localhost' || domain === 'users.noreply.github.com';
}

function isReservedPhone(value) {
  const digits = value.replace(/\D/g, '');
  return /^1\d{3}55501\d{2}$/.test(digits) || digits === '15551234567' || /^447700900\d{3}$/.test(digits);
}

function lineNumber(text, index) {
  return text.slice(0, index).split('\n').length;
}

function redactMatch(code, match) {
  if (code === 'EMAIL_ADDRESS') {
    const [local, domain] = match.split('@');
    return `${local.slice(0, 1)}…@${domain}`;
  }
  if (code === 'PRIVATE_HOME_PATH' || code === 'WINDOWS_USER_PATH') return '[private path]';
  if (code.includes('TOKEN') || code.includes('KEY') || code === 'SECRET_ASSIGNMENT') return '[credential-like value]';
  return match.length > 80 ? `${match.slice(0, 77)}…` : match;
}

function addMatches(findings, relativePath, text, definitions, filter = () => true) {
  for (const [code, pattern, message] of definitions) {
    pattern.lastIndex = 0;
    for (const match of text.matchAll(pattern)) {
      const value = match[1] ?? match[0];
      if (!filter(code, value, match)) continue;
      findings.push({
        code,
        path: relativePath,
        line: lineNumber(text, match.index ?? 0),
        message,
        evidence: redactMatch(code, value.trim()),
      });
    }
  }
}

function shouldSkip(relativePath) {
  const parts = relativePath.split('/');
  if (parts.some((part) => SKIPPED_DIRECTORY_NAMES.has(part))) return true;
  return false;
}

function isProbablyText(buffer, extension) {
  if (TEXT_EXTENSIONS.has(extension)) return true;
  const sample = buffer.subarray(0, Math.min(buffer.length, 8192));
  return !sample.includes(0);
}

async function collectFiles(root, rootRealPath, useGitIndex) {
  const files = [];

  if (useGitIndex) {
    let stdout;
    try {
      ({ stdout } = await execFileAsync(
        'git',
        ['-C', root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
        { encoding: 'buffer', maxBuffer: 16 * 1024 * 1024 },
      ));
    } catch {
      // A source archive can contain a literal .git directory. Fall back to
      // walking the tree while retaining the normal .git exclusion.
    }
    if (stdout) {
      const candidates = stdout.toString('utf8').split('\0').filter(Boolean).sort();
      for (const gitPath of candidates) {
        const relativePath = gitPath.split(path.sep).join('/');
        if (shouldSkip(relativePath)) continue;
        const absolutePath = path.join(root, gitPath);
        const stat = await lstat(absolutePath);
        if (stat.isSymbolicLink()) {
          const target = await realpath(absolutePath).catch(() => null);
          files.push({ absolutePath, relativePath, stat, symlinkTarget: target, rootRealPath });
        } else if (stat.isFile()) {
          files.push({ absolutePath, relativePath, stat, rootRealPath });
        }
      }
      return files;
    }
  }

  async function visit(absolutePath, relativePath) {
    if (relativePath && shouldSkip(relativePath)) return;
    const stat = await lstat(absolutePath);
    if (stat.isSymbolicLink()) {
      const target = await realpath(absolutePath).catch(() => null);
      files.push({ absolutePath, relativePath, stat, symlinkTarget: target });
      return;
    }
    if (stat.isDirectory()) {
      const entries = await readdir(absolutePath);
      entries.sort();
      for (const entry of entries) {
        await visit(path.join(absolutePath, entry), relativePath ? `${relativePath}/${entry}` : entry);
      }
      return;
    }
    if (stat.isFile()) files.push({ absolutePath, relativePath, stat });
  }

  await visit(root, '');
  return files.filter((file) => file.relativePath).map((file) => ({ ...file, rootRealPath }));
}

export async function audit(rootArgument = '.') {
  const root = rootArgument instanceof URL ? fileURLToPath(rootArgument) : path.resolve(rootArgument);
  const rootRealPath = await realpath(root);
  const rootEntries = new Set(await readdir(root));
  const findings = [];
  const files = await collectFiles(root, rootRealPath, rootEntries.has('.git'));

  if (!rootEntries.has('LICENSE') && !rootEntries.has('LICENSE.md') && !rootEntries.has('COPYING')) {
    findings.push({ code: 'MISSING_LICENSE', path: '.', line: 1, message: 'repository has no root license file' });
  }

  let noticeText = '';
  const upstreamReferences = [];
  const directUpstreams = [];
  for (const file of files) {
    const relativePath = file.relativePath;
    for (const [code, pattern, message] of RISKY_FILE_PATTERNS) {
      if (!pattern.test(relativePath)) continue;
      if (code === 'RISKY_ENV_FILE' && /(^|\/)\.env\.(?:example|sample|template)$/i.test(relativePath)) continue;
      findings.push({ code, path: relativePath, line: 1, message });
    }

    if (file.symlinkTarget !== undefined) {
      if (!file.symlinkTarget || (file.symlinkTarget !== rootRealPath && !file.symlinkTarget.startsWith(`${rootRealPath}${path.sep}`))) {
        findings.push({ code: 'EXTERNAL_SYMLINK', path: relativePath, line: 1, message: 'symlink resolves outside the audit root' });
      }
      continue;
    }

    if (file.stat.size > MAX_TEXT_BYTES) {
      findings.push({ code: 'LARGE_FILE', path: relativePath, line: 1, message: `file exceeds ${MAX_TEXT_BYTES} bytes and was not content-scanned` });
      continue;
    }

    const buffer = await readFile(file.absolutePath);
    if (!isProbablyText(buffer, path.extname(relativePath).toLowerCase())) continue;
    const text = buffer.toString('utf8');
    if (NOTICE_FILE_PATTERN.test(relativePath)) {
      noticeText += `\n${text}`;
    } else {
      UPSTREAM_SOURCE_PATTERN.lastIndex = 0;
      for (const match of text.matchAll(UPSTREAM_SOURCE_PATTERN)) {
        const reference = match[0];
        upstreamReferences.push({ reference, path: relativePath, line: lineNumber(text, match.index ?? 0) });
        const start = Math.max(0, (match.index ?? 0) - 300);
        const context = text.slice(start, (match.index ?? 0) + reference.length + 80);
        if (/\b(?:adapted|derived|copied|based)\b/i.test(context)) {
          directUpstreams.push({ slug: repositorySlug(reference), path: relativePath, line: lineNumber(text, match.index ?? 0) });
        }
      }
      UPSTREAM_SHORTHAND_PATTERN.lastIndex = 0;
      for (const match of text.matchAll(UPSTREAM_SHORTHAND_PATTERN)) {
        directUpstreams.push({ slug: repositorySlug(match[1]), path: relativePath, line: lineNumber(text, match.index ?? 0) });
      }
    }

    addMatches(findings, relativePath, text, SECRET_PATTERNS, (code, value) => {
      if (isPlaceholder(value)) return false;
      if (code === 'SECRET_ASSIGNMENT' && /^(?:process\.)?env(?:\.|\[)/i.test(value)) return false;
      return true;
    });
    addMatches(findings, relativePath, text, PRIVATE_PATH_PATTERNS);
    addMatches(findings, relativePath, text, IDENTITY_PATTERNS, (code, value) => {
      if (code === 'EMAIL_ADDRESS') return !isExampleEmail(value);
      if (code === 'PHONE_NUMBER') return !isReservedPhone(value);
      return !/^(?:example|sample|fictional|test|redacted|<|\$\{)/i.test(value.trim())
        && !/\bExample$/i.test(value.trim());
    });
    addMatches(findings, relativePath, text, FORBIDDEN_SOURCE_NAMES);
    addMatches(findings, relativePath, text, [['RESTRICTIVE_LICENSE_REVIEW', LICENSE_REVIEW_PATTERN,
      'license term needs explicit compatibility review']]);
  }

  const hasNotice = [...rootEntries].some((entry) => NOTICE_FILE_PATTERN.test(entry));
  if (upstreamReferences.length > 0 && !hasNotice) {
    findings.push({
      code: 'MISSING_UPSTREAM_NOTICE',
      path: '.',
      line: 1,
      message: 'upstream source reference found but no root NOTICE or THIRD_PARTY_NOTICE file exists',
      evidence: upstreamReferences[0].reference,
    });
  }
  if (hasNotice) {
    const seen = new Set();
    for (const upstream of directUpstreams) {
      const slug = upstream.slug.toLowerCase();
      if (!slug || seen.has(slug) || noticeText.toLowerCase().includes(slug)) continue;
      seen.add(slug);
      findings.push({
        code: 'MISSING_UPSTREAM_ATTRIBUTION',
        path: upstream.path,
        line: upstream.line,
        message: 'derived/adapted upstream is absent from the root third-party notice',
        evidence: upstream.slug,
      });
    }
  }

  findings.sort((a, b) => a.path.localeCompare(b.path) || a.line - b.line || a.code.localeCompare(b.code));
  return { root, scannedFiles: files.length, findings };
}

function printHuman(result) {
  if (result.findings.length === 0) {
    console.log(`release-audit: PASS (${result.scannedFiles} files scanned)`);
    return;
  }
  console.error(`release-audit: FAIL (${result.findings.length} finding(s), ${result.scannedFiles} files scanned)`);
  for (const finding of result.findings) {
    const evidence = finding.evidence ? ` [${finding.evidence}]` : '';
    console.error(`${finding.path}:${finding.line} ${finding.code}: ${finding.message}${evidence}`);
  }
}

async function main() {
  const args = process.argv.slice(2);
  const json = args.includes('--json');
  const positional = args.filter((arg) => arg !== '--json');
  if (positional.length > 1 || args.includes('--help') || args.includes('-h')) {
    console.log('Usage: node scripts/release-audit.mjs [root] [--json]');
    process.exit(positional.length > 1 ? 2 : 0);
  }

  try {
    const result = await audit(positional[0] ?? '.');
    if (json) console.log(JSON.stringify(result, null, 2));
    else printHuman(result);
    process.exitCode = result.findings.length === 0 ? 0 : 1;
  } catch (error) {
    console.error(`release-audit: ERROR: ${error.message}`);
    process.exitCode = 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
