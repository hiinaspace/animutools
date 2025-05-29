# animutools

tools for running an animu club in vrchat/chilloutVR.

## fenc

encoding script based on ffmpeg-python . usually does the right thing as far as
bitrate and stuff for playing in AVPro or unity player, i.e.

- baked hardsubs from embedded mkv
- h264/aac
- packaging as HLS playlist and individual segment files, which works around
  poor HTTP buffering behavior with plain "progressive" mp4 playback
  in MediaFoundation / AVPro.
- "fast start"/web optimized
- bit-capped 1pass CRF encoding
  - and commented out 2pass encoding which I don't really think helps; the
    lore on the internet for properly encoding streaming h264 is very
    inconclusive.
- attempts to detect the jp language and eng subs for annoying EraiRaws rips.
  You may still need to specify the `--subtitle_index` still.

### Audio Normalization

VRChat's video players are mostly used to play stuff from YouTube, and stuff
on YouTube usually has its audio mastered to -14 LUFS integrated (AFAICT, YouTube's
audio normalization practices are weirdly cryptic). Thus, this script also
normalizes the audio of its output files to -14 LUFS using ffmpeg's `loudnorm`
filter in 2-pass mode.

### AVPro / MediaFoundation progressive mp4 streaming problems

MediaFoundation is Microsoft's newish library and API for loading videos from
HTTP media streams. AVPro is a unity library/asset that uses MediaFoundation,
and is in turn used by both VRChat and ChilloutVR's video players.

Unfortunately, MediaFoundation has really bad buffering behavior with mp4 files
transferred over HTTP with byte Range requests, aka progressive streaming. The
client will make hundreds of tiny HTTP range requests with small powers of two,
e.g. from nginx logs where the 3rd field is the byte size (and 206 is the HTTP
Partial Content response code):

```
"GET /test.mp4?a HTTP/1.1" 206 458196 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 1228244 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 966100 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 196052 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 589268 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 16384 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 8192 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 24576 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 16384 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 16384 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 24576 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 24576 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 40960 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
"GET /test.mp4?a HTTP/1.1" 206 146900 "-" "NSPlayer/12.00.19041.2251 WMFSDK/12.00.19041.2251"
```

I can roughly guess this is because MediaFoundation tries to access the file
through some sort of virtual filesystem API which can be backed by a local disk
or HTTP (through range requests). Tiny reads like this would be fine on a local
disk usually (with OS caching) but when each read turns into a whole HTTP
request, the HTTP server can bog down trying to serve all the individual
requests. It gets even worse with multiple clients (all trying to stream the
same video file).

While MediaFoundation is waiting for the HTTP responses, its output video
frames will stutter and freeze. AVPro mostly handles this gracefully, but if
the bitrate of the video is high enough, the output can stall long enough for
AVPro to just give up. Even if it does catch up, the audio stream can get out
of sync. And then when you try to resync/restart playback, MediaFoundation
again makes hundreds of little requests trying to seek to the right part of the
video.

Some additional research is in:

- https://github.com/RenderHeads/UnityPlugin-AVProVideo/issues/1370
- https://feedback.abinteractive.net/p/disable-avpro-s-use-low-latency-by-default-expose-as-toggle

### HLS workaround

If you instead remux the progressive mp4 into individual segments addressed
with an HLS vod playlist, MediaFoundation and AVPro behave fine (i.e. like a
proper client); whatever weird VFS layer that makes the tiny requests is
replaced with reasonable HTTP requests to the segments.

Thus, if you use the `--hls` option and/or specify your output as
`somefile.m3u8`, then `fenc` will create a directory `somefile.m3u8.ts`, encode
your video into small segments, and output the m3u8 playlist file.

Then, upload both the .ts segment dir and the playlist to whatever server setup
you have, and paste the .m3u8 file into the CVR/VRC video player. It'll work
far better than any progressive mp4 file.

It is more annoying since there are a bunch of segment files, and if you want
to test the file beforehand, you'll have to use VLC or mpv (can't just stick
the m3u8 url into your browser). But it is better than broken playback.

The HLS encode only has a single resolution, no other source sets i.e. adaptive
bitrate streaming. I don't know if AVPro even supports that, but if it becomes
useful, it should be easy to add.

#### Alternatives Considered

Another workaround I tried was using .mkv muxing instead of .mp4. This somehow
sidesteps the bad buffering behavior. However, if the .mkv is proxied by
cloudflare, its agressive edge cache will request and load the entire file
first, generally triggering the same audio desync. So the least bad solution
still seems to be HLS.

At one point I thought that forcing the h264 high profile also fixed the
buffering behavior, but it turns out that was wrong too.

## allanime.py

a mysterious ffmpeg-python script for packing 6 videos into a grid, which each
original video's audio as a separate mono track. unity's native player can
play each track simultaneously as a separate AudioSource, so with a simple shader
you can play all 6 videos simultaneously.

For some reason the video output by the script is practically unplayable, where
most decoders (mpv, ffplay, firefox) will refuse to buffer the input for more
that 1 second. I have no idea why it does this. Somebody with deeper mp4 or
h264 knowledge might be able to tell why. My guess is it is some sort of buffer
underrun when reading from 6 inputs at the same time that screws up x264. In
the meantime you can work around it by reencoding the video with e. e.g.

```sh
ffmpeg -i input.mp4 \
  -map 0:0 -map 0:1 -map 0:2 -map 0:3 -map 0:4 -map 0:5 -map 0:6 \
  -c:a copy -c:v libx264 -preset medium -tune animation \
  -movflags faststart -crf 28 output.mp4
```

## config.yml

an example flexget config for downloading seasonal trash from nyaa and into my
twisted server setup, automatically encoding stuff using `fenc` above into
guessable filenames.
