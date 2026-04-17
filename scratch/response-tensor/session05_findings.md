# Response Tensor Research — Session 05 Findings

## Question

Can a network write something to its future self and have that actually shape behavior? This is the cleanest form of "network actively manipulating its unified object" — the one conceptual piece sessions 1-4 didn't touch.

## Architecture tested

Tied-weight message channel:
```
Read:   z1 = W1 x + b1 + W_m · m_{t-1}          [m_{t-1} stop-grad]
        h  = tanh(z1)
        y  = W_out h + b_out
Write:  m_t = W_m^T · mean(h) + b_m
```

One matrix W_m does double duty (read direction + write via transpose). The implicit hope: gradient on W_m from reading will simultaneously shape what gets written, since the same weights govern both. Mini-batch training so messages encode batch-to-batch signal. No BPTT.

Five conditions × 5 seeds: no_memory, self_write, random_prev, frozen_random, other_write.

## Stage A — memoryless task (sessions 5A)

All conditions tied at test loss 0.0014. The message effect (RMS output change when message is zeroed) was 0.001 for self_write — essentially zero. The task is IID per-batch, so there's nothing useful to communicate across time. Correct behavior: ignore the channel. Expected negative result.

## Stage B — task with hidden temporal structure (5B)

Added a sinusoidal drift to the teacher output (period 400 steps, amplitude 0.6) not visible in x. To perform well, the network must track where in the drift cycle it is — which requires memory.

```
                  test (mean)     msg_effect
no_memory         0.0506           0.000
self_write        0.0506           0.001       ← still zero!
other_write       0.0506           0.000
random_prev       0.0491           0.016
frozen_random     0.0469           0.027
```

self_write STILL doesn't work. Identical to no_memory. Per-phase loss:

```
                  step 0     step 100    step 200    step 300
no_memory         0.006      0.056       0.006       0.136
self_write        0.006      0.056       0.006       0.135
```

The network produces a drift-agnostic prediction (essentially teacher(x) with no phase correction) across all conditions. FFT of self_write messages shows no peak at the drift frequency — messages are noise.

## Stage C — oracle probe (5C)

To isolate whether the failure is architectural or about optimization, fed the network a hand-crafted signal through the same memory channel.

```
                    mean test    step 0    step 100    step 200    step 300
no_memory           0.0506        0.006     0.056       0.006       0.136
self_write          0.0506        0.006     0.056       0.006       0.135
oracle_sin_cos      0.0152        0.026     0.027       0.001       0.006
oracle_drift        0.0285        0.003     0.034       0.003       0.073
```

**Oracle signals produce 3.3× improvement.** Phase losses become much flatter — the network learns to counteract the drift using the memory signal. This proves the architecture is capable of using memory.

## Diagnosis

- Architecture: **works** — demonstrated by oracle conditions
- Optimization: **fails** — the network cannot discover useful memory content to write

This is a classic credit-assignment / bootstrap problem. The implicit write mechanism (write gets trained only via the gradient on reading, through weight-tying) requires the messages to already carry signal before the gradient can shape them further. At initialization m ≈ 0 and reading is a tiny perturbation, so there's no signal to bootstrap.

Every architecture that successfully uses memory — RNN/LSTM/Transformer/NTM — has one of:
- Backprop through time (gradient flows directly from "this read helped" back into "so this write mattered")
- Explicit memory supervision (auxiliary loss on m)
- Attention-based read (amplifies weak initial signals into discoverable gradients)
- Warm initialization of memory content

The implicit-via-weight-tying design has none of these. Predictably it fails.

## Connection to the broader question

The user's framing through several turns was "get the network to manipulate its unified object / self-modify." Session 5's finding:

Gradient descent on weights IS already a self-modification mechanism with a working credit-assignment path (∂L/∂θ directly tells the network what to change). Any ADDITIONAL self-modification mechanism layered on top needs its own credit-assignment path. Without one, it's dead code.

So the "network manipulating itself" intuition has two meanings:
1. Weight updates during training — already happening, this is what training is
2. Auxiliary channels where the network writes to its future self — viable only with extra machinery (BPTT, supervision, or attention)

Sessions 1-4 were about reading/structure of the self-object. Session 5 is about writing, and shows the writing-without-BPTT version collapses to inaction. This isn't a failure; it's a concrete answer about what would be required.

## Confidence

- Message channel dormant on IID task (5A): **high** — correct behavior
- Self-written memory doesn't bootstrap on drift task (5B): **high** — replicated across 5 seeds
- Architecture can use memory if given a good signal (5C): **high** — 3.3× improvement, 5 seeds
- General claim about bootstrap requiring BPTT/supervision: **medium-high** — consistent with all existing literature on memory-augmented architectures

## Files

- `scratch/response-tensor/session05_write_future.py` — memoryless task (5A)
- `scratch/response-tensor/session05b_drift.py` — drift task (5B)
- `scratch/response-tensor/session05c_oracle.py` — oracle probe (5C)

## What session 6 could test

1. **Add BPTT** (short window, 3-5 steps) and rerun the drift task. This directly tests whether the bootstrap failure is the whole story — with credit assignment, does self_write catch up to oracle?
2. **Warm-init memory** to encode approximate phase at start of training, see if the self_write trajectory holds onto it and improves.
3. **Move on.** Sessions 1-5 have covered reading, structural comparison, passive self-feedback, active gating, and writing. The broader picture is coherent enough. Further sessions might be diminishing returns vs. switching to a different question entirely.

My honest lean is option 3. The shape of the answer is now clear: self-reference is real but constrained, self-knowledge is about type not identity, and self-modification beyond gradient descent requires explicit credit assignment. Any of those could be deepened but the high-level picture is stable.
