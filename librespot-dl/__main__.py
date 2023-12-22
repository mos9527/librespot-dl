import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
import enum
import json
import os
import sys, argparse
import re

from logging import exception, getLogger, basicConfig
from threading import Thread
import typing


from librespot.audio import SuperAudioFormat, CdnManager
from librespot.proto import Metadata_pb2 as Metadata
from librespot.audio.decoders import AudioQuality, AudioQualityPicker
from librespot.core import Session
from librespot.metadata import TrackId, AlbumId, PlaylistId
from tqdm.std import tqdm

session : Session
args : argparse.Namespace
logger = getLogger("librespot-dl")
progress = tqdm(bar_format="{desc}: {percentage:.1f}%|{bar}| {n:.2f}/{total_fmt} {elapsed}<{remaining}")
pool = ThreadPoolExecutor(16)

class QualityPreference(enum.Enum):
    PREFER_BEST_QUALITY = 0x00
    PREFER_WORST_QUALITY = 0x01

class QualityPicker(AudioQualityPicker):    
    preferred : QualityPreference

    def __init__(self, preferred: QualityPreference):
        self.preferred = preferred

    @staticmethod
    def get_vorbis_file(files: typing.List[Metadata.AudioFile]):

        for file in files:
            if file.HasField("format") and SuperAudioFormat.get(
                    file.format) == SuperAudioFormat.VORBIS:
                return file
        return None

    def get_file(self, files: typing.List[Metadata.AudioFile]):
        ffiles = [file for file in files if file.HasField("format")]
        ffiles = sorted(ffiles,key=lambda f: {AudioQuality.NORMAL : 0, AudioQuality.HIGH : 1, AudioQuality.VERY_HIGH : 2}[AudioQuality.get_quality(f.format)])
        if self.preferred == QualityPreference.PREFER_BEST_QUALITY:
            return ffiles[len(ffiles) - 1]
        if self.preferred == QualityPreference.PREFER_WORST_QUALITY:
            return ffiles[0]

def setup_logging():
    import coloredlogs

    class SemaphoreStdout:
        @staticmethod
        def write(__s):
            # Blocks tqdm's output until write on this stream is done
            # Solves cases where progress bars gets re-rendered when logs
            # spews out too fast
            with tqdm.external_write_mode(file=sys.stdout, nolock=False):
                return sys.stdout.write(__s)

    log_stream = SemaphoreStdout
    coloredlogs.install(
            level=args.log_level,
            fmt="%(asctime)s %(name)s [%(levelname).4s] %(message)s",
            stream=log_stream,
            isatty=True,
        )
    basicConfig(
        level=args.log_level, format="[%(levelname).4s] %(name)s %(message)s", stream=log_stream
    )        

def parse_args():
    global args
    parser = argparse.ArgumentParser(description="librespot-dl",formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--log-level",help="Logging Level",default="INFO",choices=["DEBUG","INFO","WARNING","ERROR","CRITICAL"])
    group = parser.add_argument_group("Authentication")
    group.add_argument("--load", help="Load credentials from file", default='')
    group.add_argument("--save", help="Save credentials to file", default='')
    group.add_argument("--email", help="Spotify account email address", default='')
    group.add_argument("--password", help="Spotify account password", default='')    
    group = parser.add_argument_group("Download Options")
    group.add_argument("--template","-t", help="Output filename template", default="{artist} - {title}")
    group.add_argument("--output","-o", help="Output directory", default='.')
    group.add_argument("--quality", help="Audio quality", default="BEST", choices=["BEST","WORST"])
    group.add_argument("url",help="Spotify track/album/playlist URL", default='')
    args = parser.parse_args()
    args.load = os.path.expanduser(args.load)
    args.save = os.path.expanduser(args.save)
    args.quality = {"BEST":QualityPreference.PREFER_BEST_QUALITY, "WORST":QualityPreference.PREFER_WORST_QUALITY}[args.quality]

def login():
    global session
    if args.load:
        logger.info("Loading credentials from file %s" % args.load)
        session = Session.Builder().stored_file(args.load).create()
    else:
        session = Session.Builder().user_pass(args.email, args.password).create()
        if args.save:  
            logger.info("Saving credentials to file %s" % args.save)
            with open(args.save, 'w', encoding='utf-8') as f:
                f.write(json.dumps(
                    {
                        "username": args.email,
                        "credentials": base64.b64encode(args.password.encode()).decode(),
                        "type": "AUTHENTICATION_USER_PASS"
                    },
                    indent=4,
                ))

def get_track_metadata(track : Metadata.Track):
    return {
            "title" : [track.name],
            "artist" : [*([art.name for art in track.artist])],
            "albumartist" : [*([art.name for art in track.album.artist])],
            "album" : [track.album.name],
            "tracknumber" :  "%s" % (track.number),
            "date" : [str(track.album.date.year)],
            "copyright": [track.album.label],
            "discnumber" : [str(track.disc_number)],
        }         
def tag_audio(file: str, track : Metadata.Track ,cover_img: bytearray):
    def write_keys(song):
        # Writing metadata
        # Due to different capabilites of containers, only
        # ones that can actually be stored will be written.
        complete_metadata = get_track_metadata(track)     
        for k,v in complete_metadata.items():
            try:
                song[k] = v
            except:
                pass
        try:
            song.save()
        except Exception as e:
            logger.error("Failed to write metadata: %s" % e)

    def mp4():
        from mutagen import easymp4
        from mutagen.mp4 import MP4, MP4Cover

        song = easymp4.EasyMP4(file)
        write_keys(song)
        if len(cover_img):
            song = MP4(file)
            song["covr"] = [MP4Cover(cover_img)]
            song.save()

    def mp3():
        from mutagen.mp3 import EasyMP3,HeaderNotFoundError
        from mutagen.id3 import ID3, APIC
        try:
            song = EasyMP3(file)            
        except HeaderNotFoundError:
            song = EasyMP3()
            song.filename = file
            song.save()
            song = EasyMP3(file)            
        write_keys(song)
        if len(cover_img):
            song = ID3(file)
            song.update_to_v23()  # better compatibility over v2.4
            song.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="",
                    data=cover_img,
                )
            )
            song.save(v2_version=3)

    def flac():
        from mutagen.flac import FLAC, Picture
        from mutagen.mp3 import EasyMP3
        song = FLAC(file)            
        write_keys(song)
        if len(cover_img):
            pic = Picture()
            pic.data = cover_img
            pic.mime = "image/jpeg"
            song.add_picture(pic)   
            song.save()

    def ogg():
        import base64
        from mutagen.flac import Picture
        from mutagen.oggvorbis import OggVorbis

        song = OggVorbis(file)            
        write_keys(song)
        if len(cover_img):
            pic = Picture()
            pic.data = cover_img
            pic.mime = "image/jpeg"
            song["metadata_block_picture"] = [
                base64.b64encode(pic.write()).decode("ascii")
            ]
            song.save()

    format = file.split(".")[-1].upper()
    for ext, method in [
        ({"M4A", "M4B", "M4P", "MP4"}, mp4),
        ({"MP3"}, mp3),
        ({"FLAC"}, flac),
        ({"OGG", "OGV"}, ogg),
    ]:
        try:
            if format in ext:
                return method() or True
        except Exception as e:
            logger.error("Failed to write metadata: %s" % e)            
    return False

def write_bytes(fd,out_fd,size,chunk_sizes=None,chunk_process=None,default_chunksize=65536,desc='Downloading...'):
    bytes_read  = 0
    bytes_wrote = 0    
    while True:       
        chunk_size = next(chunk_sizes) if chunk_sizes else default_chunksize        
        size_to_read = min(chunk_size,size - bytes_read)
        chunk = fd.read(size_to_read)
        if (len(chunk) == 0):
            break
        bytes_read += len(chunk)
        progress.update(len(chunk) / size)
        chunk = chunk if not chunk_process else chunk_process(chunk)                
        bytes_wrote += out_fd.write(chunk)
    out_fd.write(b"\x00" * (size - bytes_wrote))
    return bytes_wrote

def get_image(self : CdnManager, file_id: bytes, stream=True):
    response = self._CdnManager__session.client() \
        .get(self._CdnManager__session.get_user_attribute("image-url")
                .replace("{file_id}", binascii.hexlify(file_id).decode()), stream=stream)
    if response.status_code != 200:
        raise IOError("{}".format(response.status_code))
    return response

def download_track(tid : TrackId, blocking = True):
    def worker_job():
        cf = session.content_feeder()
        cdn = session.cdn()
        audio_stream = session.content_feeder().load(tid,QualityPicker(args.quality), False, None)
        audio_format = audio_stream.input_stream._Streamer__audio_format

        cover_art_fid = audio_stream.track.album.cover_group.image[0].file_id
        cover_art = get_image(cdn, cover_art_fid, stream=False)
        meta = {k:v if (type(v) == str) else ",".join([str(i) for i in v]) for k,v in get_track_metadata(audio_stream.track).items()}
        save_as = os.path.join(args.output.format(**meta),args.template.format(**meta))
        ext = {SuperAudioFormat.AAC:'.aac',SuperAudioFormat.VORBIS:'.ogg',SuperAudioFormat.MP3:'.mp3'}[audio_format]
        save_as += ext

        os.makedirs(os.path.dirname(save_as),exist_ok=True)
        logger.info("Downloading %s", save_as)
        with open(save_as, 'wb') as f:
            size = audio_stream.input_stream.stream().size()
            write_bytes(audio_stream.input_stream.stream(),f,size)
        tag_audio(save_as, audio_stream.track, cover_art.content)
    if blocking:
        for _ in range(0,5):
            try:
                worker_job()
                return
            except Exception as e:
                logger.error("Failed #%d attempt. Retrying: %s" % (_,e))
        logger.fatal("Giving up after %d tries" % _)
    else:
        pool.submit(worker_job)

def download(url):
    REGEX = re.compile(r"(?P<Type>track|album|playlist)\/(?P<ID>[a-zA-Z0-9]*)")
    iid = None
    itype = None
    try:
        find = next(REGEX.finditer(url))
        find = find.groupdict()
        iid = find["ID"]
        itype = find["Type"]
    except Exception as e:
        logger.fatal("Invalid URL %s (%s)" % (url,e))
    if (itype == "track"):
        progress.total = 1
        download_track(TrackId.from_base62(iid))
    elif (itype == "album"):
        aid = AlbumId.from_base62(iid)
        resp = session.api().get_metadata_4_album(aid)
        logger.info("Album | %s", resp.name)
        progress.total = 0
        for disc in resp.disc:
            logger.info("Disc %d | %d tracks", disc.number, len(disc.track))
            progress.total += len(disc.track)
            for track in disc.track:
                tid = TrackId(binascii.hexlify(track.gid).decode())
                download_track(tid)
    elif (itype == "playlist"):
        pid = PlaylistId(iid)
        resp = session.api().get_playlist(pid)
        logger.info("Playlist | %s", resp.attributes.name)
        logger.info("%s" % resp.attributes.description)
        logger.info("Tracks: %s" % len(resp.contents.items))
        progress.total = len(resp.contents.items)
        for item in resp.contents.items:
            tid = TrackId.from_base62(item.uri.split(':')[-1], True)
            download_track(tid)
    else:
        logger.fatal("Unspported type %s" % itype)            
    pass

def __main__():
    parse_args()
    setup_logging()
    login()
    download(args.url)
    pool.shutdown(wait=True)
if __name__ == "__main__":
    __main__()
    sys.exit(0)