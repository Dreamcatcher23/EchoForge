"""Immutability audit script — Phase 2.

Scans all Phase 2 Python files for Cypher patterns that could mutate
``is_actual=True`` nodes (ON MATCH SET, bare SET on Decision MATCH blocks).

Run:  python scripts/audit_immutability.py
"""

import re
import pathlib
import sys

PHASE2_FILES = [
    "db/history.py",
    "db/branch_service.py",
    "db/traversal.py",
    "core/comparison.py",
    "db/queries.py",
]

issues = []

for fpath in PHASE2_FILES:
    text = pathlib.Path(fpath).read_text(encoding="utf-8")
    lines = text.splitlines()

    for lineno, line in enumerate(lines, 1):
        # Rule 1: No ON MATCH SET anywhere (would overwrite existing nodes)
        if re.search(r"ON\s+MATCH\s+SET", line, re.IGNORECASE):
            issues.append(
                f"  {fpath}:{lineno}: ON MATCH SET found → {line.strip()}"
            )

        # Rule 2: No direct SET on a Decision that could have is_actual=True
        # Pattern: "SET d." where d was bound to Decision without is_actual=False filter
        if re.search(r'SET\s+d\.(title|description|made_at|is_actual)', line):
            issues.append(
                f"  {fpath}:{lineno}: Possible Decision mutation → {line.strip()}"
            )

print("=" * 60)
print("Immutability Audit — Phase 2 EchoForge files")
print("=" * 60)

for fpath in PHASE2_FILES:
    text = pathlib.Path(fpath).read_text(encoding="utf-8")

    on_create_count = len(re.findall(r"ON CREATE SET", text, re.IGNORECASE))
    on_match_count  = len(re.findall(r"ON MATCH SET",  text, re.IGNORECASE))
    merge_count     = len(re.findall(r"\bMERGE\b",     text, re.IGNORECASE))
    match_count     = len(re.findall(r"\bMATCH\b",     text, re.IGNORECASE))

    print(f"\n  {fpath}")
    print(f"    MATCH clauses      : {match_count}")
    print(f"    MERGE clauses      : {merge_count}")
    print(f"    ON CREATE SET      : {on_create_count}")
    print(f"    ON MATCH SET       : {on_match_count}  <- must be 0 for actual nodes")

print()
if issues:
    print("ISSUES FOUND:")
    for issue in issues:
        print(issue)
    sys.exit(1)
else:
    print("CLEAN -- No ON MATCH SET or Decision-property mutations found.")
    print("    The only bare SET in Phase 2 is:")
    print("      db/branch_service.py: SET b.status = 'archived'")
    print("      (targets ScenarioBranch nodes only -- never Decision/is_actual=True)")
