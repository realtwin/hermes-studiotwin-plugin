# Video frame timing (V05 B1)

Native video frame-step controls use MP4 presentation timestamps, not a guessed or average fps. The shared VideoViewer inspects the same resolved URL used by playback, so registered tool-media cards, completed TaskCards, and standalone video directives use the same behavior without caller-supplied fps. MP4Box.js 2.3.0 (BSD-3-Clause, pinned in package-lock.json) supplies sample composition timestamps and edit-list metadata. Sample order is sorted by presentation time, accounting for a simple rate-1 edit's media offset (including B-frame reordering).

Stepping selects the adjacent presentation sample relative to the currently displayed interval, clamps at either end, and pauses playback. It seeks one microsecond inside a nonzero boundary to avoid browser currentTime quantization decoding the preceding frame. The timeline remains a continuous seconds-based scrubber for native video. Native-video fps props are not treated as evidence of exact sample timing.

Explicit image sequences retain their supplied fps and indexed timing. Sequences without a valid supplied rate show the first image and disable timed playback, scrubbing, and stepping rather than inventing a rate.

## Intentional limits

Timing inspection is an additional optional fetch of the playback URL, bounded to 32 MiB and 10 seconds and aborted on scope invalidation/unmount. It does not replace native/host Range streaming for playback. CORS restrictions, host-only protocols that do not support fetch, larger files, unsupported containers, fragmented MP4, multiple video tracks, and complex edit lists can leave timing unavailable. In those cases, native playback, scrubbing and capture remain available, but both frame-step buttons are disabled and the card states that exact frame timing is unavailable. The parser deliberately rejects ambiguous timing rather than estimating an fps. No backend gateway, IPC service, custom credit ledger, URL rewriting, or paid call is added.

## Verification

The Chromium test mounts the actual registerVideoCards render callback, without an fps prop, and a completed TaskCard video. It exercises both 6-fps and 10-fps MP4s, observes requestVideoFrameCallback mediaTime, checks that forward stepping changes decoded pixels, and checks that reverse stepping restores the initial pixels. The same browser test preserves explicit 4-fps image-sequence coverage and checks playback with disabled stepping after timing inspection is denied.

The second fixture was generated locally:

    ffmpeg -y -f lavfi -i testsrc=size=32x32:rate=10:duration=1 -c:v libx264 -pix_fmt yuv420p -movflags +faststart tests/fixtures/video-timing/testsrc-32-10fps.mp4

ffprobe confirms r_frame_rate=10/1, avg_frame_rate=10/1, nb_frames=10. The existing 6-fps fixture is unchanged. Timing unit tests cover both files, presentation-order stepping at variable intervals, invalid input, HTTP failure and download-size bounds.

RED: replacing the original manually configured browser VideoCard with the registered render callback failed at 0.041666 seconds versus 1/6 seconds. Regression sensitivity: temporarily restoring delta/24 seeking in the fixed viewer made both browser-rate cases fail (0.041666 versus 1/6 and 1/10). The mutation was removed before final committed-HEAD verification. Raw review/run evidence is retained under .review-evidence/ in the worktree; the original Salt report and probe are unchanged.
