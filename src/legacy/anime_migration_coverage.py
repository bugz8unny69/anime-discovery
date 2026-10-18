"""Fail-closed, read-only coverage audit for offline legacy migration.

Unknown operational tables are never silently assumed to have migrated.
"""
from anime_migration_inventory import inventory

CORE={"series","episodes","notifications"}
EVIDENCE={"verified_series_identity","confidence_shadow_v15","episode_verification_v16"}
# Queue/history state requires a separately reviewed schema-specific importer.
OPERATIONAL_HINTS=("queue","history","dispatch","rejection","action","torrent","download","claim")

def migration_coverage(controller, inbox, verified, shadow, output):
    sources={"controller":inventory(controller),"inbox":inventory(inbox),
             "verified":inventory(verified),"shadow":inventory(shadow)}
    target=inventory(output)
    missing_core=sorted((CORE & set().union(*(set(v) for v in sources.values())))-set(target))
    missing_evidence=sorted((EVIDENCE & set().union(*(set(v) for v in sources.values())))-set(target))
    unresolved=[]
    for source, tables in sources.items():
        for table,count in tables.items():
            if count and any(hint in table.lower() for hint in OPERATIONAL_HINTS):
                # Count equality is not proof of row-level equivalence.
                unresolved.append({"source":source,"table":table,"rows":count,
                                   "target_rows":target.get(table),
                                   "reason":"Operational state needs row-level reconciliation"})
    return {"source_counts":sources,"target_counts":target,
            "missing_core":missing_core,"missing_evidence":missing_evidence,
            "unresolved_operational":unresolved,
            "ready_for_cutover":not (missing_core or missing_evidence or unresolved)}
