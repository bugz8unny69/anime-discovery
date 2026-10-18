"""Fail-closed approved-dispatch verification before external acquisition.

This module deliberately does not perform network calls or submit torrents.
"""
from anime_identity_rejection_gate import resolve_notification

def approved_dispatch(db, notification_id):
    if type(notification_id) is not int or notification_id<=0:
        raise ValueError("Invalid notification")
    series_id=resolve_notification(db,notification_id)
    row=db.execute("""SELECT d.series_id,d.season,d.episode,d.state,
        q.decision,q.season,q.episode
        FROM episode_dispatch d JOIN episode_approval_queue q
        ON q.notification_id=d.notification_id
        WHERE d.notification_id=?""",(notification_id,)).fetchone()
    if row is None:
        raise ValueError("No approved dispatch")
    sid,season,episode,state,decision,approved_season,approved_episode=row
    if sid!=series_id or decision!="AUTO_APPROVED" or state!="CLAIMED":
        raise ValueError("Dispatch is not authorized")
    if (season,episode)!=(approved_season,approved_episode):
        raise ValueError("Dispatch episode differs from approval")
    if type(season) is not int or season<=0 or type(episode) is not int or episode<=0:
        raise ValueError("Invalid episode")
    verified=db.execute("""SELECT verified,evidence_json FROM episode_verification_v16
        WHERE notification_id=?""",(notification_id,)).fetchone()
    if verified is None or verified[0]!=1:
        raise ValueError("Episode verification missing")
    return {"notification_id":notification_id,"series_id":sid,
            "season":season,"episode":episode}
