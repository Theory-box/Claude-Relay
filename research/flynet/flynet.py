"""
flynet.py — turn the real FlyWire connectome (v783) into a runnable recurrent net.

The connectome is a directed, signed, weighted graph:
    139k neurons, 15.1M edges. Each edge = (pre -> post, synapse_count, sign).
We build a sparse weight matrix W where W[post, pre] = sign * synapse_count,
then run rate dynamics:   x_{t+1} = (1-leak)*x_t + leak * phi(gain * W @ x_t + u_t)
phi = tanh (bounded, keeps the recurrent system from exploding).

This is the "connectome-constrained network" idea: topology is FIXED by biology,
we only choose the global gain / leak / nonlinearity.
"""
import numpy as np
import pandas as pd
import scipy.sparse as sp

DATA = "/home/claude/Drosophila_brain_model"


def load_connectome(verbose=True):
    conn = pd.read_parquet(f"{DATA}/Connectivity_783.parquet")
    # index columns are already 0..N-1 into the neuron list
    pre  = conn["Presynaptic_Index"].to_numpy(np.int32)
    post = conn["Postsynaptic_Index"].to_numpy(np.int32)
    w    = conn["Excitatory x Connectivity"].to_numpy(np.float32)  # signed synapse count
    n = int(max(pre.max(), post.max())) + 1
    # W[post, pre] so that (W @ x)[post] = sum_pre W[post,pre]*x[pre]
    W = sp.csr_matrix((w, (post, pre)), shape=(n, n), dtype=np.float32)
    ids = conn.groupby("Presynaptic_Index")["Presynaptic_ID"].first()
    if verbose:
        exc = (conn["Excitatory"] > 0).mean()
        print(f"neurons: {n:,}   edges: {len(w):,}   excitatory fraction: {exc:.1%}")
    return W, n, conn


def io_by_structure(W, conn):
    """Find sensory-like (source) and motor-like (sink) neurons from graph structure.
    Sensory input carries info INTO the brain: little in-brain input, lots of output.
    Motor output is the opposite. No cell-type labels required."""
    n = W.shape[0]
    indeg  = np.asarray((W != 0).sum(axis=1)).ravel()   # partners feeding INTO neuron
    outdeg = np.asarray((W != 0).sum(axis=0)).ravel()    # partners neuron feeds
    # sources: low in, high out ; sinks: high in, low out
    source_score = outdeg / (indeg + 1)
    sink_score   = indeg / (outdeg + 1)
    sources = np.argsort(source_score)[::-1]
    sinks   = np.argsort(sink_score)[::-1]
    return sources, sinks, indeg, outdeg


def normalize_gain(W, target_radius=0.9, n_iter=40):
    """Estimate the spectral radius via power iteration on |W| and rescale so the
    linearized system sits just below instability (edge of chaos = richest dynamics)."""
    A = abs(W).astype(np.float32)
    v = np.random.default_rng(0).standard_normal(A.shape[0]).astype(np.float32)
    v /= np.linalg.norm(v)
    lam = 0.0
    for _ in range(n_iter):
        w = A @ v
        lam = np.linalg.norm(w)
        if lam == 0:
            break
        v = w / lam
    gain = target_radius / lam if lam > 0 else 1.0
    return gain, lam


def run(W, u_series, gain, leak=0.5, x0=None, nonlin=np.tanh, record=None):
    """Run rate dynamics. u_series: (T, N) dense external input. record: indices to log."""
    n = W.shape[0]
    x = np.zeros(n, np.float32) if x0 is None else x0.copy()
    T = u_series.shape[0]
    rec = np.zeros((T, n if record is None else len(record)), np.float32)
    for t in range(T):
        drive = gain * (W @ x) + u_series[t]
        x = (1 - leak) * x + leak * nonlin(drive)
        rec[t] = x if record is None else x[record]
    return rec, x


def run_sparse(W, T, inj_idx, inj_vals, gain, leak=0.5, nonlin=np.tanh, record=None):
    """Same dynamics but external input injected only into inj_idx neurons.
    inj_vals: (T, len(inj_idx)) — avoids allocating a dense (T,N) input."""
    n = W.shape[0]
    x = np.zeros(n, np.float32)
    rec = np.zeros((T, n if record is None else len(record)), np.float32)
    for t in range(T):
        drive = gain * (W @ x)
        drive[inj_idx] += inj_vals[t]
        x = (1 - leak) * x + leak * nonlin(drive)
        rec[t] = x if record is None else x[record]
    return rec, x
