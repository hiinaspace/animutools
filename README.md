# animutools

tools for running an animu club in vrchat/chilloutVR.

## fenc

encoding script based on ffmpeg-python . usually does the right thing as far as
bitrate and stuff for playing in AVPro or unity player, i.e.

- baked hardsubs from embedded mkv
- h264/aac
- "fast start"/web optimized
- bit-capped 1pass CRF encoding
  - and commented out 2pass encoding which I don't really think helps; the
    lore on the internet for properly encoding streaming h264 is very
    inconclusive.
- attempts to detect the jp language and eng subs for annoying EraiRaws rips.
  You may still need to specify the `--subtitle_index` still.

### AVPro progressive mp4 buffering problem and workarounds

For some reason AVPro has severe problems with the usual progressive mp4s. On
initial load, it makes a very quick burst of range requests throughout the file
then continues to make very tiny powers of two byte ranges rather than proper
chunked streaming.

This burst of requests and its usual latency as the origin struggles to serve
them throws off the audio sync, as the video gets delayed a few seconds. If
your mp4 files are proxied by cloudflare, the initial latency on load (and thus
the audio desync) is made even worse, up to CVR's 5 second loading timeout
triggering and breaking playback completely. In CVR, you have to toggle the
network sync on and off to get AVPro to reload the video and (hopefully) sync
the audio correctly. VRChat seems to handle the problem a bit better. If the
overall bitrate of the stream is low enough (<1500kbps or so), video playback
is generally okay, but that's a restrictive bitrate for e.g. 1080p.

This problem occurs in both ChilloutVR, VRChat, and AVPro's standalone
unitypackage trial version, so I think it is actually AVPro's fault. I did some
more research on the [feedback board thread][0].

[0]: https://feedback.abinteractive.net/p/disable-avpro-s-use-low-latency-by-default-expose-as-toggle

However, I did find a workaround by encoding videos as an HLS vod playlists,
which work fine. If you use the `--hls` option and/or specify your output as
`somefile.m3u8`, then `fenc` will create a directory `somefile.m3u8.ts`, encode
your video into small segments, and output the m3u8 file. If you both the .ts
segment dir and the playlist over HTTP and paste the .m3u8 file into the CVR/VRC
video player, it should work.

It is more annoying since there are a bunch of segment files, and if you just
want to test the file beforehand, you'll have to use VLC or mpv (can't just
stick the m3u8 url into your browser). But better than broken playback I guess.

The HLS encode only has a single resolution, no other source sets. TODO it
might be nice to try encoding like a 360p version along with the original
though, for the internet-challenged among us.

Another workaround I tried was using .mkv muxing instead of .mp4. This somehow
sidesteps the bad buffering behavior. However, if the .mkv is proxied by
cloudflare, its agressive edge cache will request and load the entire file
first, generally triggering the same audio desync. So the least bad solution
still seems to be multi-file HLS.

The usual trick of using dropbox public file hosting seems to also sidestep
this issue. Maybe their http servers are just better configured than mine. I
swear this all worked better with my exact same nginx configuration and
encoding settings before though. It's all so tiresome.

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
