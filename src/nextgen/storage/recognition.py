"""Verified season-level Recognized Names memory.

Only a successfully persisted, exact episode verification can seed identity
memory. Aliases are hints for identity reuse, never episode authorization.
"""
from src.nextgen.providers.parsing import norm, release_title
from src.nextgen.providers.http import json_object
from src.nextgen.providers.errors import ProviderInvalidResponse

class RecognitionConflict(ValueError):
    pass


def _alias(text):
    if type(text) is not str or not 1 <= len(text) <= 512:
        return None
    key = norm(text)
    return key if 3 <= len(key) <= 256 else None


def remember_verified_release(db, *, verification_id, source, season):
    """Within the release-verification transaction, never from webhook hints alone."""
    if not db.in_transaction:
        raise ValueError("Verification transaction required")
    if type(season) is not int or season < 0:
        raise ValueError("Invalid season")
    proof = db.execute(
        "SELECT v.anidb_id,v.tvdb_series_id,v.tvdb_season,v.verified_at_ms,a.title "
        "FROM release_verifications v JOIN identified_anime a ON a.anidb_id=v.anidb_id "
        "WHERE v.verification_id=?", (verification_id,)).fetchone()
    if proof is None or proof[:3] != (source.anidb_id, source.tvdb_series_id, season):
        raise RecognitionConflict("Verification provenance mismatch")
    aid,tid,_,when,title = proof
    if not 1 <= len(title.strip()) <= 512:
        raise RecognitionConflict("Unsafe verified title")
    existing = db.execute(
        "SELECT anidb_id FROM recognized_seasons WHERE tvdb_series_id=? AND tvdb_season=?",
        (tid, season)).fetchone()
    if existing and existing[0] != aid:
        raise RecognitionConflict("Conflicting season identity")
    db.execute(
        "INSERT OR IGNORE INTO recognized_seasons "
        "(tvdb_series_id,tvdb_season,anidb_id,display_title,evidence_verification_id,recognized_at_ms) "
        "VALUES(?,?,?,?,?,?)",(tid,season,aid,title,verification_id,when))
    aliases = [title]
    try:
        document=json_object(source.raw_body)
        release=document.get("release_name")
        if type(release) is str:
            parsed,_ = release_title(release)
            if parsed:
                aliases.append(parsed[0])
    except (ValueError,TypeError,ProviderInvalidResponse):
        pass
    for text in aliases:
        key=_alias(text)
        if key is None:
            continue
        owner=db.execute(
            "SELECT tvdb_series_id,anidb_id FROM recognized_aliases WHERE alias_key=? AND tvdb_season=?",
            (key,season)).fetchone()
        if owner and owner!=(tid,aid):
            # Do not poison or replace prior verified mappings on a common name.
            continue
        db.execute(
            "INSERT OR IGNORE INTO recognized_aliases(alias_key,tvdb_season,tvdb_series_id,anidb_id) "
            "VALUES(?,?,?,?)",(key,season,tid,aid))


def recognized_for_release(db, name, *, season=None):
    """Exact normalized lookup. Ambiguity fails closed; never guesses seasons."""
    aliases,_=release_title(name)
    if not aliases:
        return None
    key=_alias(aliases[0])
    if key is None:
        return None
    if season is not None and (type(season) is not int or season<0):
        return None
    rows=db.execute(
        "SELECT s.tvdb_series_id,s.tvdb_season,s.anidb_id,s.display_title "
        "FROM recognized_aliases a JOIN recognized_seasons s "
        "ON s.tvdb_series_id=a.tvdb_series_id AND s.tvdb_season=a.tvdb_season "
        "WHERE a.alias_key=?" + (" AND a.tvdb_season=?" if season is not None else ""),
        (key,season) if season is not None else (key,)).fetchall()
    if len(rows)!=1:
        return None
    tid,selected_season,aid,title=rows[0]
    return {"tvdb_series_id":tid,"tvdb_season":selected_season,
            "anidb_id":aid,"title":title}
