#!/usr/bin/env python3
"""Patch only the inbox's receive boundary; no database or torrent modifications."""
from pathlib import Path
import ast, shutil, sys, time
p = Path('/opt/anime-discovery/autobrr_discovery_inbox.py')
s = p.read_text()
if 'anime_v19_rejection_guard' in s:
    print('ALREADY_INSTALLED'); sys.exit(0)
needle = "        with self.lock:\n            with self.connect() as db:\n"
assert s.count(needle) == 1, 'Unexpected inbox source layout: refusing patch'
replacement = "        from anime_v19_rejection_guard import blocked\n        if blocked(infohash):\n            return 'rejected_blocked'\n" + needle
s2 = s.replace(needle, replacement)
error_needle = '            except (ValueError, UnicodeError, sqlite3.Error) as exc:'
assert s2.count(error_needle) == 1, 'Unexpected error handler layout'
s2 = s2.replace(error_needle, "            except RuntimeError:\n                return self.reply(503, 'REJECTION_STATE_UNAVAILABLE')\n" + error_needle)
ast.parse(s2)
backup = p.with_name(p.name + '.pre-v19-' + time.strftime('%Y%m%d-%H%M%S'))
shutil.copy2(p, backup)
p.write_text(s2)
print('BACKUP', backup)
print('PATCH_INSTALLED')
