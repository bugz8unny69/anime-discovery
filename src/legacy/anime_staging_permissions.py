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

def parse_mode(value, *, directory):
    """Four-digit POSIX octal; only setgid is accepted for directories."""
    if not isinstance(value,str) or not re.fullmatch(r"[0-7]{4}",value):
        raise ValueError("Staging mode must be four octal digits")
    mode=int(value,8)
    if directory:
        if mode & ~0o2777 or mode & 0o700 != 0o700:
            raise ValueError("Directory mode requires owner rwx; only setgid special bit is allowed")
    else:
        if mode & ~0o777 or mode & 0o600 != 0o600:
            raise ValueError("File mode requires owner read/write; special bits are forbidden")
    return mode

def apply_directory(path, *, gid=None, mode="2770"):
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Unsafe staged directory")
    target=parse_mode(mode,directory=True)
    if gid is not None and path.stat().st_gid!=gid:
        os.chown(path,-1,gid)
    os.chmod(path,target)
    st=path.stat()
    if (gid is not None and st.st_gid!=gid) or stat.S_IMODE(st.st_mode)!=target:
        raise PermissionError("Staged directory owner/group/mode does not match settings")

def apply_file(path, *, uid=None,gid=None,mode="0640"):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unsafe staged media file")
    target=parse_mode(mode,directory=False)
    if uid is not None or gid is not None:
        os.chown(path,uid if uid is not None else -1,
                 gid if gid is not None else -1)
    os.chmod(path,target)
    st=path.stat()
    if ((uid is not None and st.st_uid!=uid) or
            (gid is not None and st.st_gid!=gid) or
            stat.S_IMODE(st.st_mode)!=target):
        raise PermissionError("Staged file owner/group/mode does not match settings")
