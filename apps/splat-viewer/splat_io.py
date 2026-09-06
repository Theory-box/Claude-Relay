"""
splat_io.py — dependency-free reader for the standard 3D Gaussian Splatting .ply format.
No plyfile / no external deps (numpy only), so it also runs unchanged inside Blender's Python.

The 3DGS .ply (INRIA / most tools) stores per-vertex, RAW (pre-activation):
    x, y, z                      position
    nx, ny, nz                   normal (usually unused / zero)
    f_dc_0..2                    SH degree-0 term  -> base colour
    f_rest_0..(3*(deg+1)^2-3-1)  higher-order SH   -> view-dependent colour (optional)
    opacity                      -> sigmoid()  to get [0,1] alpha
    scale_0..2                   -> exp()      to get world-space gaussian radii
    rot_0..3                     -> normalize  quaternion (w, x, y, z)

load_ply() applies the activations and returns display-ready arrays.
"""
import numpy as np, struct

SH_C0 = 0.28209479177387814  # Y_0^0, the SH DC basis constant

# PLY scalar type -> numpy dtype
_PLY_T = {
    'char':'i1','uchar':'u1','int8':'i1','uint8':'u1',
    'short':'i2','ushort':'u2','int16':'i2','uint16':'u2',
    'int':'i4','uint':'u4','int32':'i4','uint32':'u4',
    'float':'f4','float32':'f4','double':'f8','float64':'f8',
}

def _sigmoid(x): return 1.0 / (1.0 + np.exp(-x))

def _read_header(f):
    """Parse a PLY header from a binary file object. Returns (fmt, count, props[list of (name,type)])."""
    magic = f.readline().strip()
    if magic != b'ply':
        raise ValueError("not a PLY file (bad magic %r)" % magic)
    fmt = None; count = None; props = []; in_vertex = False
    while True:
        line = f.readline()
        if not line: raise ValueError("unexpected EOF in header")
        toks = line.split()
        if not toks: continue
        kw = toks[0]
        if kw == b'format':
            fmt = toks[1].decode()          # ascii | binary_little_endian | binary_big_endian
        elif kw == b'element':
            in_vertex = (toks[1] == b'vertex')
            if in_vertex: count = int(toks[2])
        elif kw == b'property' and in_vertex:
            # 'property <type> <name>'  (splat plys have no list properties on vertex)
            props.append((toks[2].decode(), toks[1].decode()))
        elif kw == b'end_header':
            break
    return fmt, count, props

def load_ply(path):
    """Load a 3DGS .ply. Returns a dict of numpy arrays with activations applied."""
    with open(path, 'rb') as f:
        fmt, n, props = _read_header(f)
        names = [p[0] for p in props]
        if fmt == 'ascii':
            raw = np.loadtxt(f, dtype=np.float64, max_rows=n)
            if raw.ndim == 1: raw = raw[None, :]
            data = {nm: raw[:, i].astype(np.float32) for i, nm in enumerate(names)}
        else:
            little = (fmt == 'binary_little_endian')
            types = [t for _, t in props]
            # Fast path: all properties same float type -> one contiguous read + column views
            # (avoids 60+ strided structured-array copies; ~30x faster on standard splat plys).
            if len(set(types)) == 1 and _PLY_T[types[0]] in ('f4', 'f8'):
                fdt = ('<' if little else '>') + _PLY_T[types[0]]
                raw = np.frombuffer(f.read(n * len(props) * np.dtype(fdt).itemsize),
                                    dtype=fdt).reshape(n, len(props)).astype(np.float32, copy=False)
                data = {nm: raw[:, i] for i, nm in enumerate(names)}
            else:
                dt = np.dtype([(nm, ('<' if little else '>') + _PLY_T[t]) for nm, t in props])
                arr = np.frombuffer(f.read(n * dt.itemsize), dtype=dt, count=n)
                data = {nm: arr[nm].astype(np.float32) for nm in names}

    def col(*keys):
        return np.stack([data[k] for k in keys], axis=1)

    xyz = col('x', 'y', 'z')
    # colour: base SH DC term -> RGB
    if all(k in data for k in ('f_dc_0', 'f_dc_1', 'f_dc_2')):
        color = 0.5 + SH_C0 * col('f_dc_0', 'f_dc_1', 'f_dc_2')
    elif all(k in data for k in ('red', 'green', 'blue')):
        color = col('red', 'green', 'blue') / 255.0
    else:
        color = np.full((len(xyz), 3), 0.7, np.float32)
    color = np.clip(color, 0.0, 1.0).astype(np.float32)

    opacity = _sigmoid(data['opacity']) if 'opacity' in data else np.ones(len(xyz), np.float32)
    if all(k in data for k in ('scale_0', 'scale_1', 'scale_2')):
        scale = np.exp(col('scale_0', 'scale_1', 'scale_2'))
    else:
        ext = np.linalg.norm(xyz.max(0) - xyz.min(0)) or 1.0
        scale = np.full((len(xyz), 3), ext / max(len(xyz), 1) ** (1/3) * 0.5, np.float32)
    if all(k in data for k in ('rot_0', 'rot_1', 'rot_2', 'rot_3')):
        quat = col('rot_0', 'rot_1', 'rot_2', 'rot_3')
        quat = quat / (np.linalg.norm(quat, axis=1, keepdims=True) + 1e-9)
    else:
        quat = np.tile(np.array([1, 0, 0, 0], np.float32), (len(xyz), 1))

    rest = [k for k in names if k.startswith('f_rest_')]
    sh_rest = col(*sorted(rest, key=lambda s: int(s.split('_')[-1]))) if rest else None

    return dict(count=len(xyz), xyz=xyz.astype(np.float32), color=color,
                opacity=opacity.astype(np.float32), scale=scale.astype(np.float32),
                quat=quat.astype(np.float32), sh_rest=sh_rest,
                sh_degree=_sh_degree(len(rest)))

def _sh_degree(n_rest):
    # n_rest = 3 * ((deg+1)^2 - 1)
    per = n_rest // 3
    for deg in range(0, 4):
        if (deg + 1) ** 2 - 1 == per: return deg
    return 0

# ---------------------------------------------------------------- synthetic (for CPU testing)
def save_ply(path, xyz, f_dc, opacity_raw, scale_raw, rot):
    """Write a minimal binary_little_endian 3DGS ply (RAW values, pre-activation)."""
    n = len(xyz)
    props = ['x','y','z','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2',
             'rot_0','rot_1','rot_2','rot_3']
    hdr = ("ply\nformat binary_little_endian 1.0\nelement vertex %d\n" % n +
           "".join("property float %s\n" % p for p in props) + "end_header\n")
    dt = np.dtype([(p, '<f4') for p in props])
    a = np.zeros(n, dt)
    for i, k in enumerate(['x','y','z']): a[k] = xyz[:, i]
    for i, k in enumerate(['f_dc_0','f_dc_1','f_dc_2']): a[k] = f_dc[:, i]
    a['opacity'] = opacity_raw
    for i, k in enumerate(['scale_0','scale_1','scale_2']): a[k] = scale_raw[:, i]
    for i, k in enumerate(['rot_0','rot_1','rot_2','rot_3']): a[k] = rot[:, i]
    with open(path, 'wb') as f:
        f.write(hdr.encode()); f.write(a.tobytes())

def synth_cloud(n=5000, seed=0):
    """A test splat cloud: a coloured sphere shell, RAW (pre-activation) values."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3)); v /= np.linalg.norm(v, axis=1, keepdims=True)
    xyz = v.astype(np.float32)
    f_dc = ((v * 0.5 + 0.5) - 0.5) / SH_C0            # colour == normal, inverted through DC
    opacity_raw = np.full(n, 2.0, np.float32)          # sigmoid(2)=~0.88
    scale_raw = np.log(np.full((n, 3), 0.03, np.float32))
    rot = np.tile(np.array([1, 0, 0, 0], np.float32), (n, 1))
    return xyz, f_dc.astype(np.float32), opacity_raw, scale_raw, rot
