#!/usr/bin/env node
import { scanA16zSpeedrun } from '../src/sourcing/index.mjs';

const USAGE = `Usage: chironjp-sourcing [options]

Emits one normalized job per line as NDJSON. It does not write application data.

Options:
  --query TEXT              Server-side full-text query
  --keyword TEXT            Query word; repeatable, used when --query is absent
  --max-pages N             Page budget (default: 6; 50 jobs per page)
  --positive TEXT           Required title substring; repeatable
  --negative TEXT           Blocked title substring; repeatable
  --allow-location TEXT     Allowed location substring; repeatable
  --block-location TEXT     Blocked location substring; repeatable
  --max-age-days N          Exclude jobs older than N days when a date exists
  --detail-concurrency N    Concurrent detail requests (default: 4, max: 16)
  --remote                  Ask the feed for remote-open roles only
  --help                    Show this help
`;

function take(args, index, flag) {
  const value = args[index + 1];
  if (!value || value.startsWith('--')) throw new Error(`${flag} requires a value`);
  return value;
}

export function parseArgs(args) {
  const options = {
    keywords: [],
    titleFilter: { positive: [], negative: [] },
    locationFilter: { allow: [], block: [] },
  };
  for (let index = 0; index < args.length; index += 1) {
    const flag = args[index];
    if (flag === '--help') return { help: true };
    if (flag === '--remote') { options.remote = true; continue; }
    const value = take(args, index, flag);
    index += 1;
    if (flag === '--query') options.q = value;
    else if (flag === '--keyword') options.keywords.push(value);
    else if (flag === '--max-pages') options.maxPages = Number(value);
    else if (flag === '--positive') options.titleFilter.positive.push(value);
    else if (flag === '--negative') options.titleFilter.negative.push(value);
    else if (flag === '--allow-location') options.locationFilter.allow.push(value);
    else if (flag === '--block-location') options.locationFilter.block.push(value);
    else if (flag === '--max-age-days') options.maxPostingAgeDays = Number(value);
    else if (flag === '--detail-concurrency') options.detailConcurrency = Number(value);
    else throw new Error(`Unknown option: ${flag}`);
  }
  for (const key of ['maxPages', 'maxPostingAgeDays', 'detailConcurrency']) {
    if (options[key] !== undefined && (!Number.isInteger(options[key]) || options[key] <= 0)) {
      throw new Error(`--${key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)} must be a positive integer`);
    }
  }
  return options;
}

export async function main(args = process.argv.slice(2)) {
  const options = parseArgs(args);
  if (options.help) {
    process.stdout.write(USAGE);
    return;
  }
  const jobs = await scanA16zSpeedrun(options, {
    onWarning: (message) => process.stderr.write(`warning: ${message}\n`),
  });
  for (const job of jobs) process.stdout.write(`${JSON.stringify(job)}\n`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    process.stderr.write(`chironjp-sourcing: ${error?.message ?? error}\n`);
    process.exitCode = 1;
  });
}
