import json, engine, os, time
D=json.load(open("/tmp/real_full.json"))
path="/home/claude/mck/Mckinney Model.blend"
g=[x for x in D["groups"] if 10<=x["count"]<=40][:3]
plan={"merges":[{"label":x["name"][:40],"names":x["names"]} for x in g],"deletes":[]}
# DEFAULTS as the app sends them: full model + un-merge tags
t=time.time()
res=engine.execute_plan(path,plan,version="4.4",out_path="/home/claude/mck/_fm.blend",
      overwrite=False,open_after=False,include_untouched=True,tag_materials=True)
print("FULL MODEL + TAGS, 3 small merges: %.1fs"%(time.time()-t))
print("  merge_time %.1fs, untouched appended %s, remaining %s"%(res.get('merge_time'),res.get('untouched'),res.get('remaining')))
if os.path.exists(res['out']): os.remove(res['out'])
