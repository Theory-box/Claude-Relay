import ablation as A, json, numpy as np, torch
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt

d = json.load(open('/tmp/sweep.json'))
base = d.pop('__base__')
ranked = sorted(d.items(), key=lambda kv: -kv[1])

def keep_only(keep_types):
    keep = set(keep_types)
    drop = torch.tensor(np.where(~np.isin(A.TYPES, list(keep)))[0])
    A.net._state_hooks=()
    def hook(state): state.nodes.activity[..., drop]=0.0; return state
    A.net.register_state_hook(hook)
    scores=[]
    for s in range(0, A.HEXV.shape[0], A.MAXB):
        act=A.net.simulate(A.HEXV[s:s+A.MAXB], A.DT); scores.append(A.flow_inband(act)); del act
    A.net._state_hooks=()
    sc=np.concatenate(scores)
    return float(np.log((sc[A.LABELS==1].mean()+1e-9)/(sc[A.LABELS==0].mean()+1e-9)))

def ncells(types): return int(np.isin(A.TYPES, list(types)).sum())

print(f'INTACT discriminability = {base:.3f}  (full network: {len(A.TYPES)} cells, 65 types)')
print('\nTOP 20 cell types by ablation impact:')
for c,v in ranked[:20]:
    print(f'  {c:12s} {v:+.3f}')

# sufficiency: keep only the top-K types, delete the other ~45, re-measure
print('\nKEEP-ONLY-CORE (delete everything else, does the task survive?):')
for K in [8, 12, 16, 20]:
    core=[c for c,_ in ranked[:K]]
    perf=keep_only(core)
    print(f'  top-{K:2d} types ({ncells(core):5d} cells): discriminability={perf:.3f}  ({100*perf/base:.0f}% of intact)')

# chart
top=ranked[:20]
fig,ax=plt.subplots(figsize=(7,5))
names=[c for c,_ in top][::-1]; vals=[v for _,v in top][::-1]
cols=['#B4B2A9' if v<0.5 else '#D85A30' if v<1.0 else '#1D9E75' for v in vals]
ax.barh(names, vals, color=cols)
ax.axvline(0, color='#888', lw=0.5); ax.set_xlabel('ablation impact (drop in vibration-vs-clutter discriminability)')
ax.set_title('What the real fly connectome uses for motion/vibration\n(green=critical, orange=moderate, gray=minor)')
plt.tight_layout(); fig.savefig('/home/claude/flynet/ablation_ranking.png', dpi=110)
print('\nwrote ablation_ranking.png')
