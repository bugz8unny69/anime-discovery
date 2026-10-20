"""Bridge approved dispatch, completed torrent evidence and trial staging.

This does not claim that a file is Shoko-recognized or mark a dispatch DONE.
"""
from anime_acquisition_gate import approved_dispatch
from anime_media_completion import verified_media
from anime_trial_staging import stage_verified
from anime_audio_verification import confirmed_jp_en

def stage_claimed(db, notification_id, torrent, download_root, trial_root,
                  *, title, tvdb_id, english_title=None, staged_owner="", staged_group="", staged_directory_mode="2770", staged_file_mode="0640"):
    if db.in_transaction:
        raise ValueError("Autocommit required")
    approval=approved_dispatch(db,notification_id)
    notification=db.execute("SELECT info_hash FROM notifications WHERE id=?",
                            (notification_id,)).fetchone()
    if notification is None or not notification[0]:
        raise ValueError("Missing notification infohash")
    expected=str(notification[0]).lower()
    actual=torrent.get("hash") if isinstance(torrent,dict) else None
    if not isinstance(actual,str) or actual.lower()!=expected:
        raise ValueError("Torrent identity differs from approved notification")
    bound=db.execute("SELECT tvdb_id FROM verified_series_identity WHERE notification_id=?",
                     (notification_id,)).fetchone()
    if bound is None or str(bound[0])!=str(tvdb_id):
        raise ValueError("Staging series identity mismatch")
    source=verified_media(torrent,download_root)
    # Reject before copying: inspect actual source audio, not release labels.
    if not confirmed_jp_en(source):
        raise ValueError("Source must contain Japanese and English audio")
    return stage_verified(source,trial_root,title=title,tvdb_id=tvdb_id,
                          series_id=approval["series_id"],
                          season=approval["season"],episode=approval["episode"],english_title=english_title,
                          staged_owner=staged_owner,staged_group=staged_group,
            staged_directory_mode=staged_directory_mode,staged_file_mode=staged_file_mode)
