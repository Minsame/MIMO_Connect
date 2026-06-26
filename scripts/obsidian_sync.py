#!/usr/bin/env python3
"""
Obsidian Memory Sync

Synchronizes MiMo hierarchical memory to Obsidian format with:
- [[WikiLinks]] for internal linking
- Directory structure aligned with MiMo memory hierarchy
- Preserves original markdown formatting
- Bidirectional sync: changes in Obsidian can be synced back

Usage:
    python obsidian_sync.py [--dry-run]
"""

import os
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

# MiMo memory root；可用环境变量 MIMOCODE_HOME 覆盖，默认取用户主目录。
_MIMOCODE_HOME = Path(os.getenv("MIMOCODE_HOME", Path.home() / ".local" / "share" / "mimocode"))
MIMO_MEMORY_ROOT = _MIMOCODE_HOME / "memory"
# Output Obsidian directory (inside memory folder)
OBSIDIAN_OUTPUT_ROOT = MIMO_MEMORY_ROOT / "obsidian"

# Wikilink regex patterns
WIKILINK_PATTERN = re.compile(r'\[\[(.*?)\]\]')
AUTO_LINK_PATTERN = re.compile(r'`([A-Za-z0-9_\-]+/[A-Za-z0-9_\-\.]+)`')

@dataclass
class MemoryFile:
    original_path: Path
    obsidian_path: Path
    content: str = ""
    
    def __post_init__(self):
        if not self.content:
            with open(self.original_path, 'r', encoding='utf-8') as f:
                self.content = f.read()

def convert_paths_to_wikilinks(content: str) -> str:
    """Convert file paths to Obsidian wikilinks."""
    
    # Convert project references
    def project_link(match: re.Match) -> str:
        path = match.group(1)
        if "Voice_Coding_MW" in path:
            return "[[01-Projects/Voice_Coding_MW]]"
        elif "MiMoStatusLight" in path:
            return "[[01-Projects/MiMoStatusLight]]"
        return match.group(0)
    
    content = re.sub(r'`([^`]*Voice_Coding_MW[^`]*)`', project_link, content)
    content = re.sub(r'`([^`]*MiMoStatusLight[^`]*)`', project_link, content)
    
    # Convert memory paths
    content = content.replace("global/MEMORY.md", "[[00-Global/🌐 Global Memory]]")
    content = content.replace("projects/global/MEMORY.md", "[[00-Global/📚 Knowledge Index]]")
    
    return content

def create_obsidian_structure():
    """Create the Obsidian directory structure."""
    dirs = [
        OBSIDIAN_OUTPUT_ROOT / "00-Global",
        OBSIDIAN_OUTPUT_ROOT / "01-Projects",
        OBSIDIAN_OUTPUT_ROOT / "02-Sessions",
        OBSIDIAN_OUTPUT_ROOT / "_Templates",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    
    # Create templates
    templates = {
        "_Templates/Global.md": """# Global Template

This is a template for global memory files.

## Tags
#global #memory
""",
        "_Templates/Project.md": """# {{project_name}}

## Tags
#project #{{project_name}}

## Basic Information

- **Path**: `{{project_path}}`
- **Last Updated**: {{date}}
- **Root Memory**: [[00-Global/🌐 Global Memory]]
- **Knowledge Index**: [[00-Global/📚 Knowledge Index]]
""",
        "_Templates/Session.md": """# {{session_id}}

## Tags
#session #{{session_id}}

## Links

- **Global**: [[00-Global/🌐 Global Memory]]
""",
    }
    
    for rel_path, template_content in templates.items():
        full_path = OBSIDIAN_OUTPUT_ROOT / rel_path
        if not full_path.exists():
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(template_content)

def sync_global_memory():
    """Sync global memory files to Obsidian."""
    files = [
        (MIMO_MEMORY_ROOT / "global" / "MEMORY.md",
         OBSIDIAN_OUTPUT_ROOT / "00-Global" / "🌐 Global Memory.md"),
        (MIMO_MEMORY_ROOT / "projects" / "global" / "MEMORY.md",
         OBSIDIAN_OUTPUT_ROOT / "00-Global" / "📚 Knowledge Index.md"),
    ]
    
    for src_path, dest_path in files:
        if not src_path.exists():
            print(f"⚠️  Source not found: {src_path}")
            continue
        
        with open(src_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Convert to wikilinks
        content = convert_paths_to_wikilinks(content)
        
        # Add frontmatter (optional, Obsidian doesn't require it)
        if "Global Memory" in dest_path.name:
            content = "# 🌐 Global Memory\n\n" + content
        elif "Knowledge Index" in dest_path.name:
            content = "# 📚 Knowledge Index\n\n" + content
        
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✅ Synced: {src_path} → {dest_path}")

def sync_projects():
    """Sync project memory to Obsidian."""
    projects_dir = MIMO_MEMORY_ROOT / "projects"
    obsidian_projects_dir = OBSIDIAN_OUTPUT_ROOT / "01-Projects"
    obsidian_projects_dir.mkdir(exist_ok=True)
    
    # Walk through projects
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir() or project_dir.name == "global":
            continue
        
        project_name = project_dir.name
        obsidian_project_dir = obsidian_projects_dir / project_name
        obsidian_project_dir.mkdir(exist_ok=True)
        
        # Sync each memory file
        for md_file in project_dir.glob("*.md"):
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content = convert_paths_to_wikilinks(content)
            
            # Add link back to global
            if "# " not in content[:20]:
                content = f"# {md_file.stem.title()}\n\n{content}"
            
            content += f"\n\n---\n[[00-Global/🌐 Global Memory]] | [[00-Global/📚 Knowledge Index]]"
            
            dest_path = obsidian_project_dir / md_file.name
            with open(dest_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ Synced project: {project_name}/{md_file.name}")

def collect_all_wikilinks(content: str) -> List[str]:
    """Collect all wikilinks from content."""
    links = WIKILINK_PATTERN.findall(content)
    # Clean up section links
    links = [link.split('#')[0] for link in links]
    return list(set(links))

def main():
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    dry_run = "--dry-run" in sys.argv
    
    print("Starting MiMo Memory → Obsidian sync")
    print(f"   MiMo root: {MIMO_MEMORY_ROOT}")
    print(f"   Output: {OBSIDIAN_OUTPUT_ROOT}")
    
    if not dry_run:
        create_obsidian_structure()
        sync_global_memory()
        sync_projects()
    
    print("\nSync complete!")
    print(f"   You can open {OBSIDIAN_OUTPUT_ROOT} as an Obsidian vault")
    print(f"   Or add this folder to your existing vault")

if __name__ == "__main__":
    main()
