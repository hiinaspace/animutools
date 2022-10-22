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

### chilloutVR workarounds

For some reason chilloutVR's AVPro configuration has severe problems with the
usual progressive mp4s. On initial load, it makes a huge burst of range requests
throughout the file, like it's looking for something. This burst seems to throw
off the audio sync, as the video gets delayed a few seconds, and you have to
toggle the network sync on and off to get AVPro to reload the video and (hopefully)
sync the audio correctly. I did some more research on the [feedback board thread][0].

[0]: https://feedback.abinteractive.net/p/disable-avpro-s-use-low-latency-by-default-expose-as-toggle

However, I did find a workaround by encoding videos as segmented .TS files with
HLS playlists, which work fine. Use the `--hls` option with `fenc` and specify
your output as `somefile.m3u8`, and you'll get both the playlist and a
similarly named `.ts` file in the same directory. If you serve both over HTTP and
paste the .m3u8 file into the CVR video player, it should work.

It is more annoying since there are two files, and if you just want to test the
file beforehand, you'll have to use VLC or mpv (can't just stick the m3u8 url
into your browser). But better than broken playback I guess.

The HLS encode only has a single resolution, no other source sets. TODO it
might be nice to try encoding like a 360p version along with the original
though, for the internet-challenged among us.

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
