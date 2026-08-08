# Riesz pyramid phase-based magnification (branch feature/riesz)

Faithful CPU port of MIT pseudocode (Wadhwa 2014). New Method "Riesz (beta)" next to
Linear/Phase. Luma-only, color preserved via delta-add.

Pipeline (per frame): Laplacian pyramid (5x5 gaussian, ~5 levels) -> approx Riesz
(3-tap [.5,0,-.5] x/y) per non-lowpass level -> quaternionic phase difference
(acos(qRe/|q|), split into phiCos/phiSin) -> accumulate (unwrap) -> IIR temporal
bandpass (RBJ biquad from center/width + fps, Direct-Form-II-transposed registers)
-> amplitude-weighted gaussian blur -> quaternion-exp phase shift (real part) ->
collapse. alpha=gain, band=center/width sliders, rho=Smoothing(denoiseR).

Validated standalone: 0.57px synthetic oscillation -> 5.9px out (~10x at alpha=15),
no NaN, bounded. Math is correct.

Test: Method=Riesz, GPU OFF (CPU-only), Amplified, LOW Detail (heavy). gain~20,
center~3Hz width~2Hz. Subtle motion should amplify cleanly with far less brightness
noise than Linear. Heavy on CPU (builds pyramid + blurs each frame) -> keep Detail low.

Next: tune, then GPU port (all ops are linear filters/elementwise -> maps to passes).
Also the future offline video-upload feature can reuse this engine.
