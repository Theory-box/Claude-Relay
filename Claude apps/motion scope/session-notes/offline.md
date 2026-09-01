# Offline video upload/processing (branch feature/offline, from main)

Open video file -> loads into the SAME <video> element (video.src=objectURL, loop, muted) ->
existing GPU/CPU pipeline processes it. attachStream refactored -> onSourceReady() shared by
camera + file. Controls: play/pause, restart, playback speed [0.1,0.25,0.5,1]x.

Frame-accurate: loop gates on newFrame (set per requestVideoFrameCallback), so each real frame
is processed once (no rAF dupes). Effective sampling rate procFps = ΔpresentedFrames/ΔmediaTime
(frames per MEDIA-second, from rVFC metadata) -> used as sampleFps for temporal-filter coeffs
(replaces render fps; cap raised 120->240) AND shown in readout (capFps=procFps for files). So
slowing a 120fps clip to 0.5x on a 60Hz display makes procFps climb toward 120 -> Nyquist
"resolves <= X Hz" rises -> fast vibration becomes visible. All processed in-browser (local file,
no upload). Record output: MediaRecorder on the visible output canvas.captureStream(60) -> .webm
download (works live or offline). stop() revokes URL, clears src, stops recorder, hides ctrls.

TEST: Open video file -> MIT demo or own clip -> plays+processes. Slow high-fps clips to 0.5x/lower
(watch resolves-Hz climb). Record output -> downloads .webm.
LIMITS/v2: export captures live output at display rate (not a deterministic full-quality render);
true frame-by-frame export-to-file could be v2. Frame gating needs rVFC (Chrome/Brave ok).
