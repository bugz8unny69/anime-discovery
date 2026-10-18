"""Read-only coverage audit requiring row-level operational reconciliation."""
from anime_migration_inventory import inventory
from anime_migration_row_audit import compare_operational_table

CORE={"series","episodes","notifications"}
EVIDENCE={"verified_series_identity","confidence_shadow_v15","episode_verification_v16"}
OPERATIONAL_HINTS=("queue","history","dispatch","rejection","action","torrent","download","claim")

def migration_coverage(controller, inbox, verified, shadow, output):
    paths={"controller":controller,"inbox":inbox,"verified":verified,"shadow":shadow}
    sources={name:inventory(path) for name,path in paths.items()}
    target=inventory(output)
    names=set().union(*(set(tables) for tables in sources.values()))
    missing_core=sorted((CORE & names)-set(target))
    missing_evidence=sorted((EVIDENCE & names)-set(target))
    unresolved=[]
    verified_operational=[]
    for source,tables in sources.items():
        for table,count in tables.items():
            if count and any(hint in table.lower() for hint in OPERATIONAL_HINTS):
                comparison=compare_operational_table(paths[source],output,table)
                item={"source":source,**comparison}
                if comparison["equal"]:
                    verified_operational.append(item)
                else:
                    unresolved.append(item)
    # Presence-only checks do not prove that core or evidence records survived.
    # Keep cutover blocked until explicit row-level mapping audits cover them.
    unverified_core_evidence=sorted((CORE | EVIDENCE) & names)
    return {"source_counts":sources,"target_counts":target,
            "unverified_core_evidence":unverified_core_evidence,
            "missing_core":missing_core,"missing_evidence":missing_evidence,
            "unresolved_operational":unresolved,
            "verified_operational":verified_operational,
            "ready_for_cutover":False,
            "cutover_blocker":"Core/evidence row-level reconciliation and all-table coverage not yet verified"}
