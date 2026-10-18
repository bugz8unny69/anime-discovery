"""Validate a reviewed legacy-to-unified operational table mapping offline.

This checks structural compatibility only. It does not import rows or authorize
a cutover. A mapping must be explicitly supplied for every nonempty source
operational table.
"""
from anime_legacy_schema_report import operational_schema_report
from anime_migration_row_audit import compare_operational_table

def validate_operational_mapping(source_path, target_path, mapping):
    if not isinstance(mapping,dict):
        raise ValueError("Explicit table mapping required")
    source=operational_schema_report(source_path)["tables"]
    target={item["table"]:item for item in operational_schema_report(target_path)["tables"]}
    results=[]
    for item in source:
        name=item["table"]
        if not item["rows"]:
            continue
        dest=mapping.get(name)
        if not isinstance(dest,str) or not dest:
            results.append({"source":name,"target":None,"verified":False,
                            "reason":"Nonempty operational table is unmapped"})
            continue
        if dest!=name:
            # Renamed tables require a dedicated, reviewed transformation.
            results.append({"source":name,"target":dest,"verified":False,
                            "reason":"Renamed operational table needs reviewed transformation"})
            continue
        if dest not in target:
            results.append({"source":name,"target":dest,"verified":False,
                            "reason":"Destination table missing"})
            continue
        comparison=compare_operational_table(source_path,target_path,name)
        results.append({"source":name,"target":dest,"verified":comparison["equal"],
                        "reason":comparison["reason"]})
    unknown=set(mapping)-{item["table"] for item in source}
    if unknown:
        raise ValueError("Mapping refers to absent source tables")
    return {"results":results,"all_verified":all(row["verified"] for row in results),
            "writes_enabled":False}
