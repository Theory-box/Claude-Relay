import json, os, time, ablation as A

PATH = '/tmp/sweep.json'
res = json.load(open(PATH)) if os.path.exists(PATH) else {}
if '__base__' not in res:
    res['__base__'] = A.performance(None); json.dump(res, open(PATH,'w'))
base = res['__base__']
t0 = time.time()
for c in A.UNIQ:
    if c in res:
        continue
    res[c] = base - A.performance(c)
    json.dump(res, open(PATH,'w'))
    print(f'{c:12s} impact={res[c]:+.3f}')
    if time.time() - t0 > 240:
        print('...pausing (time budget)'); break
done = all(c in res for c in A.UNIQ)
print('SWEEP COMPLETE' if done else f'remaining: {sum(c not in res for c in A.UNIQ)}')
