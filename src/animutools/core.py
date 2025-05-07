#!/usr/bin/env python3
import ffmpeg
import sys
import os
if os.name == 'posix':
    import fcntl
import tempfile

def probe_video(infile):
    """Probe a video file and return audio/subtitle track information."""
    probe = ffmpeg.probe(infile)
    audio_track = 0
    audio_count = 0
    audio_stream = None
    sub_count = 0
    sub_track = 0
    sub_type = 'text'
    found_eng_sub_track = False

    # XXX clean up spaghetti logic through here
    for stream in probe['streams']:
        # try to select jpn audio over english
        if stream['codec_type'] == 'audio' and 'tags' in stream:
            tags = stream['tags']
            if tags and 'language' in tags and tags['language'] == 'jpn':
                audio_track = audio_count
                audio_stream = stream
            audio_count += 1
        if stream['codec_type'] == 'subtitle':
            # try to select default stream
            if 'disposition' in stream and 'default' in stream['disposition'] and stream['disposition']['default'] == 1:
                sub_track = sub_count
                if stream['codec_name'] == 'dvd_subtitle' or stream['codec_name'] == 'hdmv_pgs_subtitle':
                    sub_type = 'dvd'
            # try to select the first english sub track, which at least for these awful
            # cyberpunk rips seems to be the japanese tl track and not the dubtitles.
            # it is unfortunately completely ambiguous though.
            if 'tags' in stream and 'language' in stream['tags'] and stream['tags']['language'] == "eng":
                if not found_eng_sub_track:
                    sub_track = sub_count
                    found_eng_sub_track = True
                    print(f"found first english sub track at {sub_track}", file=sys.stderr)
                    if stream['codec_name'] == 'dvd_subtitle' or stream['codec_name'] == 'hdmv_pgs_subtitle':
                        sub_type = 'dvd'
            sub_count += 1

    return {
        'probe': probe,
        'audio_track': audio_track,
        'audio_stream': audio_stream,
        'sub_track': sub_track,
        'sub_type': sub_type,
        'audio_count': audio_count,
        'sub_count': sub_count,
    }

def process_video(infile, outfile, options):
    """Process a video according to the provided options."""
    # Get video information
    video_info = probe_video(infile)
    probe = video_info['probe']
    audio_track = video_info['audio_track']
    audio_stream = video_info['audio_stream']
    sub_track = video_info['sub_track']
    sub_type = video_info['sub_type']

    if options.probe:
        import pprint
        pprint.pprint(probe)
        sys.exit(0)

    if options.subtitle_index is not None:
        print(f"overriding sub track from {sub_track=} to {options.subtitle_index=}", file=sys.stderr)
        sub_track = options.subtitle_index

    print(f"selecting {audio_track=} {audio_stream=}", file=sys.stderr)
    print(f"selecting {sub_track=}", file=sys.stderr)

    # Set up ffmpeg inputs and filters
    ffin = ffmpeg.input(infile)
    ffv = ffin.video.filter('format', 'yuv420p')
    if options.downscale_720p:
        ffv = ffv.filter('scale', '1280','-1')

    # assume subtitle track matches the audio track
    if sub_type == 'text':
        subfile = infile
        if options.subtitle_file:
            subfile = options.subtitle_file

        ffv = ffv.filter('subtitles', filename=subfile, stream_index=sub_track)
    else:
        # burn the dvd subs on the image
        subs = ffin[f's:{sub_track}']
        s2r = ffmpeg.filter_multi_output([subs, ffv], 'scale2ref')
        ffv = s2r[1].overlay(s2r[0])

    # cap bufsize based on expected buffer duration, so there aren't
    # bitrate spikes above it and thus buffer underruns during playback.
    bufsize = int(options.target_bitrate * options.buffer_duration)

    opts = {
            'c:v': 'libx264',
            # I'm not sure this is entirely necessary, but all devices support
            # high profile by now, so it doesn't seem harmful to do.
            'profile:v': 'high',
            'preset': 'medium',
            'tune': 'animation',
            'crf': '18',
            #'b:v': '2500K',
            'maxrate': f"{options.target_bitrate}K",
            # try and cap the bitrate, it'll decrease the crf to compensate
            'bufsize': f"{bufsize}K",
            #'c:a': 'copy', TODO ideally we'd just copy existing AAC
            # but need to modify the ffprobe stuff to detect.
            'c:a': 'aac',
            'b:a': '160k',
            'ac': '2',
            #'f': 'mp4',
            }

    # if remuxing, don't need the other stuff, restart
    if options.remux:
        opts = { 'c': 'copy' }

    if options.hls or os.path.splitext(outfile)[1] == ".m3u8":
        # encode as HLS, a bunch of .ts segment files + .m3u8 playlist,
        # which works around MediaFoundation's poor behavior (see README.md)

        # i'm not sure how necessary it is to make the keyframes nice and tidy
        # kind of annoying to have to guess the output framerate.
        # https://superuser.com/questions/908280/what-is-the-correct-way-to-fix-keyframes-in-ffmpeg-for-dash/908325#908325
        #framerate = 30
        #interval = 2
        #keyframes_per_segment = 3

        #opts['r'] = framerate
        #opts['g'] = framerate * interval
        #opts['keyint_min'] = framerate * interval
        #opts['hls_time'] = interval * keyframes_per_segment
        # https://teddit.net/r/ffmpeg/comments/nam6hg/mp4_to_hls_how_to_set_time_segments_properly/
        # not sure if necessary, according to that other superuser post
        # opts['force_key_frames:v'] = 'expr:gte(t,n_forced*2)'
        opts['f'] = 'hls'
        opts['hls_playlist_type'] = 'vod'
        opts['hls_time'] = options.hls_time
        opts['hls_list_size'] = 0

        # store chunks in a directory alongside the m3u8 playlist for convenience
        if not options.dry_run:
            os.makedirs(f"{outfile}.ts", exist_ok=True)
        opts['hls_base_url'] = f"{os.path.basename(outfile)}.ts/"
        opts['hls_segment_filename'] = f"{outfile}.ts/%04d.ts"
    else:
        opts['movflags'] = 'faststart'

    if options.test:
        # just encode a bit to test
        opts['t'] = 60

    audio = ffin[f'a:{audio_track}']

    if options.remux:
        output = ffmpeg.overwrite_output(ffmpeg.output(ffin, outfile, **opts))
    else:
        output = ffmpeg.overwrite_output(ffmpeg.output(ffv, audio, outfile, **opts))

    if options.dry_run:
        for a in output.get_args():
            if a.startswith('-'):
                print(a, file=sys.stderr, end=" ")
            else:
                print(f"'{a}' \\", file=sys.stderr)
        print("", file=sys.stderr)
    else:
        # basic flock queueing for multiple invocations
        if os.name == 'posix':
            with open("/tmp/vrcencode", "w+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                output.run()
        else:
            # no fnctl on windows
            output.run()

    return True
