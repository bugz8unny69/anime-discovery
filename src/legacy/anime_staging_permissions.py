"""Optional POSIX owner/group policy for verified Anime-Trial staging.

Preserve the unprivileged service model: never sudo or elevate. Resolve
configured principals locally, enforce permissions before publishing media,
and fail if the NAS/OS denies chown/chgrp/chmod. Avoid touching source torrents.
"""
import os
import pwd
import grp
import re
import stat

_PRINCIPAL=re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*[$]?|[0-9]{1,10}")

def _identity(value, *, group):
    if value is None or value=="":
        return None
    if not isinstance(value,str) or not _PRINCIPAL.fullmatch(value):
        raise ValueError("Invalid staged "+("group" if group else "owner"))
    if value.isdecimal():
        number=int(value)
        if number>4294967294:
            raise ValueError("Staged numeric owner/group out of range")
        return number
    try:
        return grp.getgrnam(value).gr_gid if group else pwd.getpwnam(value).pw_uid
    except (KeyError,OverflowError) as exc:
        raise ValueError("Configured staged owner/group does not exist") from exc

def resolve_policy(owner="",group=""):
    uid=_identity(owner,group=False)
    gid=_identity(group,group=True)
    if uid is not None and os.geteuid()!=0 and uid!=os.geteuid():
        raise PermissionError("Staged owner differs from service UID; elevated ownership is not available")
    if gid is not None and os.geteuid()!=0 and gid not in set(os.getgroups())|{os.getegid()}:
        raise PermissionError("Configured staged group is not assigned to the service account")
    return uid,gid

def apply_directory(path, *, gid=None):
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Unsafe staged directory")
    # Do not remove existing owner/group/other permissions. Ensure that
    # the configured media group can traverse series and season folders.
    if gid is not None:
        if path.stat().st_gid!=gid:
            os.chown(path,-1,gid)
        current=stat.S_IMODE(path.stat().st_mode)
        os.chmod(path,current|0o070)
        if path.stat().st_gid!=gid or not (stat.S_IMODE(path.stat().st_mode)&0o050)==0o050:
            raise PermissionError("Staged directory is not accessible to configured group")

def apply_file(path, *, uid=None,gid=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unsafe staged media file")
    if uid is not None or gid is not None:
        os.chown(path,uid if uid is not None else -1,
                 gid if gid is not None else -1)
    # Always provide owner read/write and group read, never world access.
    os.chmod(path,0o640)
    current=path.stat()
    if ((uid is not None and current.st_uid!=uid) or
            (gid is not None and current.st_gid!=gid) or
            stat.S_IMODE(current.st_mode)&0o640 != 0o640):
        raise PermissionError("Cannot publish staged file without required permissions")
