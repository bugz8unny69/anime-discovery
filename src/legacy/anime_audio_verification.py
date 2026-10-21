"""Probe audio streams before allowing source cleanup.

ffprobe must inspect the actual staged file. Release names and torrent
metadata are not acceptable evidence of Japanese/English dual audio.
"""
import json
import subprocess

class DualAudioRejected(ValueError):
    """Actual media probe completed but Japanese + English are not both present."""

def audio_languages(path, *, runner=subprocess.run):
    result=runner(["ffprobe","-v","error","-select_streams","a",
                   "-show_entries","stream=index:stream_tags=language",
                   "-of","json",str(path)],
                  capture_output=True,text=True,check=True,timeout=30)
    data=json.loads(result.stdout)
    streams=data.get("streams")
    if not isinstance(streams,list):
        raise ValueError("Missing ffprobe audio stream data")
    languages=set()
    for stream in streams:
        if not isinstance(stream,dict):
            raise ValueError("Invalid audio stream")
        lang=stream.get("tags",{}).get("language","")
        if isinstance(lang,str):
            languages.add(lang.lower())
    return languages

def confirmed_jp_en(path, *, runner=subprocess.run):
    languages=audio_languages(path,runner=runner)
    return bool(languages & {"ja","jpn"}) and bool(languages & {"en","eng"})
