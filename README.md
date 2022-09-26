# animutools

tools for running an animu club in vrchat.

## fenc

encoding script based on ffmpeg-python . usually does the right thing as far as
bitrate and stuff for playing in vrchat's AVPro or unity player, i.e.

- baked hardsubs from embedded mkv
- h264/aac
- "fast start"/web optimized
- bit-capped 1pass CRF encoding
  - and commented out 2pass encoding which I don't really think helps; the
    lore on the internet for properly encoding streaming h264 is very
    inconclusive.
- attempts to detect the jp language and eng subs for annoying EraiRaws rips.
  You may still need to specify the ``--subtitle_index` still.

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
