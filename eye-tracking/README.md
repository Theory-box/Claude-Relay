# Gaze Demo (webcam eye tracking)

A minimal WebGazer-based webcam gaze prototype wrapped as a native macOS
(Apple Silicon) app. The app embeds the demo page, serves it on a local
`127.0.0.1` port (a secure context, so the camera works), and opens your
default browser to it.

## Run
1. Download and unzip `GazeDemo-mac.zip`.
2. Double-click `GazeDemo.app`.
3. If macOS blocks it (unsigned): System Settings > Privacy & Security >
   scroll to the GazeDemo notice > "Open Anyway".
   Or, from Terminal: `xattr -dr com.apple.quarantine /path/to/GazeDemo.app`
4. Allow camera access in the browser. Calibrate (click the 9 dots), then
   read the validation number and try the 3x3 dwell heatmap.
5. Quit from the Dock when done.

## Build from source (needs Go)
    GOOS=darwin GOARCH=arm64 CGO_ENABLED=0 go build -o GazeDemo .

Then wrap `GazeDemo` in `GazeDemo.app/Contents/MacOS/`.

## Notes
- Apple Silicon (arm64) only. Ping for an Intel/universal build if needed.
- Accuracy ceiling for a single RGB webcam is ~1.5-3 degrees of visual angle;
  expect region-level (3x3 / 4x4 grid) reliability, not a pixel cursor.
