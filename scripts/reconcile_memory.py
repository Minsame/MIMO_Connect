"""
Memory FTS reconciliation script for scheduled task.
Run this periodically to keep memory_fts index populated.
"""
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

# MiMo Code 用户级记忆根目录；可用环境变量 MIMOCODE_HOME 覆盖。
_MIMOCODE_HOME = Path(os.getenv("MIMOCODE_HOME", Path.home() / ".local" / "share" / "mimocode"))
MEMORY_ROOT = _MIMOCODE_HOME / "memory"
DB_PATH = _MIMOCODE_HOME / "mimocode.db"

def reconcile():
    if not DB_PATH.exists():
        return
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Get existing entries
    cur.execute("SELECT path, fingerprint FROM memory_fts")
    existing = {row[0]: row[1] for row in cur.fetchall()}
    
    inserted = 0
    updated = 0
    
    for md_file in MEMORY_ROOT.rglob('*.md'):
        rel_path = str(md_file.relative_to(MEMORY_ROOT))
        
        try:
            content = md_file.read_text(encoding='utf-8')
        except:
            continue
        
        fingerprint = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        if rel_path in existing:
            if existing[rel_path] != fingerprint:
                # Update
                scope, scope_id = classify_scope(rel_path)
                mem_type = classify_type(rel_path)
                cur.execute("""
                    UPDATE memory_fts 
                    SET scope=?, scope_id=?, type=?, body=?, fingerprint=?, last_indexed_at=?
                    WHERE path=?
                """, (scope, scope_id, mem_type, content, fingerprint, 
                      int(os.path.getmtime(md_file) * 1000), rel_path))
                updated += 1
        else:
            # Insert
            scope, scope_id = classify_scope(rel_path)
            mem_type = classify_type(rel_path)
            cur.execute("""
                INSERT INTO memory_fts (path, scope, scope_id, type, body, fingerprint, last_indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (rel_path, scope, scope_id, mem_type, content, fingerprint,
                  int(os.path.getmtime(md_file) * 1000)))
            inserted += 1
    
    conn.commit()
    conn.close()

def classify_type(path):
    path_lower = path.lower()
    if 'checkpoint' in path_lower:
        return 'checkpoint'
    elif 'progress' in path_lower:
        return 'task_progress'
    elif 'notes' in path_lower:
        return 'notes'
    return 'memory'

def classify_scope(path):
    parts = Path(path).parts
    if 'global' in parts:
        return 'global', ''
    elif 'projects' in parts:
        idx = parts.index('projects')
        return 'projects', parts[idx + 1] if idx + 1 < len(parts) else ''
    elif 'sessions' in parts:
        idx = parts.index('sessions')
        return 'sessions', parts[idx + 1] if idx + 1 < len(parts) else ''
    return 'global', ''

if __name__ == '__main__':
    reconcile()
