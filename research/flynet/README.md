# flynet — fly connectome as a motion/vibration engine

Exploring whether the FlyWire connectome (v783, 138,639 neurons, 15.1M signed synapses)
can serve as a motion-amplification front-end: a direction-selective alpha-map that gates
an Eulerian Video Magnification (EVM) renderer, amplifying real directional vibration while
suppressing non-directional flicker, sensor noise, and opposite-direction motion.

## Files
- `flynet.py`     — load the real connectome as a sparse signed recurrent net; rate dynamics;
                    structural I/O detection (sensory=source, motor=sink); spectral gain control.
- `amptest.py`    — primitive test #1: Reichardt (direction-selective) vs motion-energy alpha-map,
                    signal vs flicker.
- `amptest2.py`   — primitive test #2: adds an opposite-direction patch (opponency check).
- `robustness.py` — feasibility sweep: energy vs ideal-HR vs biologically-degraded-HR, AUC vs noise.

## Key results (synthetic 1D space x time)
- Motion-energy CANNOT separate signal from flicker (AUC ~0.0-0.4, below chance).
- Ideal Reichardt: AUC 0.98 at low noise, degrades to 0.57 at high noise (multiplication amplifies noise).
- BIOLOGICAL Reichardt (photoreceptor blur + temporal low-pass + saturation + neural noise):
  AUC 0.99 -> 0.84 across the noise sweep — MORE robust than the ideal, because the fly front-end
  filtering acts as a noise-reduction stage. This is the argument for copying the real circuit.

## Reservoir sanity checks (flynet.py)
- Full connectome runs stably as a recurrent net (no explosion), 60% excitatory.
- Short-term memory: perfect recall at t-1, ~0.87 at t-2 (delay-line = motion primitive).
- Solves directional-change (0.74) but NOT XOR/parity (chance) with a linear readout:
  good linear delay line, poor nonlinear mixer -> great motion sensor, poor language substrate.

## Open / next
- Replace modeled front-end with the actual flyvis connectome-constrained motion network.
- 2D synthetic video demo: side-by-side energy-magnified vs fly-gated-magnified (minimal from-scratch EVM).
- Same-direction global shake is NOT rejected by direction-selectivity (needs stabilization upstream).
- Data: connectome parquet from philshiu/Drosophila_brain_model (not committed; ~200MB).
