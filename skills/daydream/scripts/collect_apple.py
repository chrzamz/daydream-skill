#!/usr/bin/env python3
"""Read explicitly selected macOS collections; filter before emitting JSON.

Only the captured subprocess pipe contains unfiltered bodies; they are never
written to disk or echoed. Secret detection is heuristic, not anonymization.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

from collect_signals import contains_secret, record_contains_secret


JXA = r'''
function run(argv) {
  const cfg = JSON.parse(argv[0]);
  const rows = [];
  const seen = new Set();
  const stats = {skipped_title: 0, skipped_locked: 0};
  const cutoff = cfg.days ? Date.now() - cfg.days * 86400000 : null;
  const privateTitle = /(^key$|api[ _-]?key|app[ _-]?secret|password|密钥|密码|凭据|私钥|access[ _-]?token)/i;
  function scan(appName, names, kind) {
    if (!names.length) return;
    const app = Application(appName);
    const collections = kind === 'note' ? app.folders : app.lists;
    for (const name of names) {
      if (/^(recently deleted|最近删除|最近刪除)$/i.test(name)) continue;
      const matches = collections.whose({name: name})();
      if (!matches.length) throw new Error('collection_unavailable');
      if (matches.length !== 1) throw new Error('ambiguous_collection');
      for (const collection of matches) {
        let items = kind === 'note' ? collection.notes : collection.reminders;
        if (kind === 'reminder' && cfg.pending_only) items = items.whose({completed: false});
        const ids = items.id();
        const titles = items.name();
        const dates = items.modificationDate();
        const locked = kind === 'note' ? items.passwordProtected() : ids.map(() => false);
        const completed = kind === 'reminder' ? items.completed() : ids.map(() => false);
        const candidates = ids.map((id, i) => ({id, i, time: dates[i] ? dates[i].getTime() : 0}));
        candidates.sort((a, b) => b.time - a.time);
        let read = 0;
        for (const candidate of candidates) {
          const i = candidate.i;
          if (seen.has(candidate.id)) continue;
          seen.add(candidate.id);
          if (cutoff !== null && candidate.time < cutoff) continue;
          if (privateTitle.test(titles[i])) { stats.skipped_title++; continue; }
          if (locked[i]) { stats.skipped_locked++; continue; }
          if (read >= cfg.limit) break;
          read++;
          const item = items.byId(candidate.id);
          const body = kind === 'note' ? item.plaintext() : (item.body() || '');
          rows.push({id: candidate.id, source: kind === 'note' ? 'apple-notes' : 'apple-reminders',
            collection: name, title: titles[i], text: body,
            timestamp: dates[i] ? dates[i].toISOString() : null,
            status: kind === 'reminder' ? (completed[i] ? 'completed' : 'pending') : null});
        }
      }
    }
  }
  try {
    scan('Notes', cfg.folders, 'note');
    scan('Reminders', cfg.lists, 'reminder');
  } catch (error) {
    const code = ['collection_unavailable', 'ambiguous_collection'].includes(error.message)
      ? error.message : 'application_read_failed';
    return JSON.stringify({error: code});
  }
  return JSON.stringify({records: rows, summary: stats});
}
'''


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def prepare(payload, days=30, limit=30, max_chars=1500, now=None, pending_only=False):
    """Filter full records before truncation; never return raw failures."""
    if not isinstance(payload, dict) or not isinstance(payload.get('records'), list):
        raise ValueError('Expected an object with a records array')
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days else None
    summary = {'skipped_secret': 0, 'skipped_invalid': 0, 'skipped_old': 0, 'skipped_completed': 0,
               'duplicates': 0, 'timestamp_kind': 'application modification date'}
    records = []
    seen = set()
    for row in payload['records']:
        if not isinstance(row, dict):
            summary['skipped_invalid'] += 1
            continue
        title, body = row.get('title', ''), row.get('text', '')
        source = row.get('source')
        if not isinstance(title, str) or not isinstance(body, str) or source not in ('apple-notes', 'apple-reminders'):
            summary['skipped_invalid'] += 1
            continue
        # Inspect every field, including identifiers and collection names.
        if record_contains_secret(row) or contains_secret(body, title=title):
            summary['skipped_secret'] += 1
            continue
        if pending_only and source == 'apple-reminders' and row.get('status') == 'completed':
            summary['skipped_completed'] += 1
            continue
        timestamp = parse_time(row.get('timestamp'))
        if cutoff and (timestamp is None or timestamp < cutoff):
            summary['skipped_old'] += 1
            continue
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier:
            summary['skipped_invalid'] += 1
            continue
        key = (source, identifier)
        if key in seen:
            summary['duplicates'] += 1
            continue
        seen.add(key)
        text = title if not body else (body if body.startswith(title) and title else title + '\n' + body)
        records.append({'id': identifier, 'source': source, 'locator': identifier,
                        'collection': row.get('collection', ''), 'timestamp': row.get('timestamp'),
                        'role': 'source', 'status': row.get('status'), 'text': text[:max_chars]})
    records.sort(key=lambda r: parse_time(r['timestamp']) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    summary['eligible'] = len(records)
    summary['returned'] = min(len(records), limit)
    summary['limit_note'] = 'Live reads inspect at most --limit recent eligible entries per selected collection before final filtering.'
    # The subprocess may provide counters only; never copy arbitrary values.
    raw_summary = payload.get('summary', {})
    if isinstance(raw_summary, dict):
        for key in ('skipped_title', 'skipped_locked'):
            value = raw_summary.get(key)
            if type(value) is int and value >= 0:
                summary[key] = value
    return {'records': records[:limit], 'summary': summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', action='append', default=[], help='Exact Notes folder name; repeat to select more')
    parser.add_argument('--list', dest='lists', action='append', default=[], help='Exact Reminders list name; repeat to select more')
    parser.add_argument('--pending-only', action='store_true', help='Omit completed reminders; default retains their status')
    parser.add_argument('--days', type=int, default=30, help='Modification window; 0 includes old entries')
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--max-chars', type=int, default=1500)
    parser.add_argument('--timeout', type=int, default=45, help='Bounded macOS application read in seconds')
    parser.add_argument('--input-json', type=Path, help='Filter an existing compatible export instead of accessing apps')
    args = parser.parse_args(argv)
    if args.days < 0 or not 1 <= args.limit <= 1000 or args.max_chars < 1 or not 1 <= args.timeout <= 60:
        parser.error('Use nonnegative days, limit 1..1000, positive max-chars, timeout 1..60')
    if args.input_json and (args.folder or args.lists):
        parser.error('--input-json cannot be combined with application collections')
    if not args.input_json and not (args.folder or args.lists):
        parser.error('Select at least one --folder or --list; there is no implicit all-app scan')
    try:
        if args.input_json:
            payload = json.loads(args.input_json.read_text(encoding='utf-8'))
        else:
            if sys.platform != 'darwin':
                raise RuntimeError('Application collection requires macOS')
            config = {'folders': args.folder, 'lists': args.lists, 'pending_only': args.pending_only,
                      'days': args.days, 'limit': args.limit}
            result = subprocess.run(['osascript', '-l', 'JavaScript', '-e', JXA, json.dumps(config)],
                                    capture_output=True, text=True, timeout=args.timeout, check=False)
            if result.returncode:
                raise RuntimeError('Application read failed; check selected collections and macOS Automation permission')
            payload = json.loads(result.stdout)
        if isinstance(payload, dict) and payload.get('error') in (
                'collection_unavailable', 'ambiguous_collection', 'application_read_failed'):
            print('Application read stopped: {}. Select an unambiguous accessible collection or use an authorized export.'.format(payload['error']), file=sys.stderr)
            return 1
        output = prepare(payload, args.days, args.limit, args.max_chars, pending_only=args.pending_only)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except subprocess.TimeoutExpired:
        print('Application read timed out. No partial content was emitted; check macOS authorization or narrow the scope.', file=sys.stderr)
    except (OSError, ValueError, RuntimeError):
        print('Collection failed. Check the selected source, JSON format, platform, and app permissions. Raw output was withheld.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
