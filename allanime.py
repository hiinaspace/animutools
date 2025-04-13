#!/usr/bin/env python3
import ffmpeg
import sys
from more_itertools import chunked

ins = sys.argv[1:-1]
out = sys.argv[-1]

# pure grid
#subs = [ffmpeg.input(f).video.filter('subtitles', filename=f).filter('scale',384,216) for f in ins]
#hstacks = [ffmpeg.filter(chunk, 'hstack', inputs=5) for chunk in chunked(subs, 5)]
#vstack = ffmpeg.filter(hstacks, 'vstack', inputs=len(hstacks))
#audio = ffmpeg.filter([ffmpeg.input(f).audio for f in ins], 'amix', inputs=len(ins))
def singleencode(f, horiz, vert):
    ff = ffmpeg.input(f).video
    # sample weird framerates back to the usual 24000/1001
    ff = ff.filter('fps', fps='ntsc_film')
    if f.endswith('.mkv'):
        ff = ff.filter('subtitles', filename=f)
    return ff.filter('scale',horiz,vert).filter('setsar','1').filter('format', 'yuv420p')

def encode(ins, out):
    columns = 3
    horiz = 1920 / columns
    vert = horiz * 9 / 16
    subs = [singleencode(f, horiz, vert) for f in ins]
    hstacks = [ffmpeg.filter(chunk, 'hstack', inputs=columns) for chunk in chunked(subs, columns)]
    vstack = ffmpeg.filter(hstacks, 'vstack', inputs=len(hstacks))
    audio = [ffmpeg.input(f).audio for f in ins if not f.endswith('.jpg')]
    audio = [a.filter('loudnorm') for a in audio]
    
    opts = {
            'map_chapters': '-1', # don't copy chapters
            'c:v': 'libx264',
            'preset': 'medium',
            'tune': 'animation',
            'movflags': 'faststart',
            # still trying to narrow down weird buffering issue
            # from 'encoding for streaming sites' guide
            'b:v': '2000k',
            'maxrate': '2000k',
            'bufsize': '4000k',
            'g': '50',  # GOP size
            'crf': '28',
            'c:a': 'aac',
            'b:a': '160k',
            'ac': '1',
            # high profile seems to cause the weird unbufferable videos / broken playback in vrchat
            # or maybe not; something weird still occurs on certain inputs and I dunno why.
            #'profile:v': 'main',
            #'t': '60'
            }
    stream = ffmpeg.output(vstack, *audio, out, **opts).global_args('-sn')
    print(f"will run {' '.join(stream.get_args())=}", file=sys.stderr)
    stream.run()

encode(ins, out)
