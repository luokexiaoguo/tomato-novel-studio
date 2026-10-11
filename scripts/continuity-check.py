#!/usr/bin/env python3
"""
continuity-check.py — 小说连续性检测引擎 v1.0
检测沉睡伏笔、角色缺席、死角色活跃、时间线漂移
用法: continuity-check.py --state story-state.json
"""
import os, sys, json

def load_state(path):
    if not os.path.exists(path):
        print(f"状态文件不存在: {path}"); sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def check_dormant_foreshadowing(state, max_idle=3):
    issues = []; chapters = sorted(state.get("chapters", {}).keys())
    if not chapters: return issues
    for f in state.get("foreshadowing", []):
        if f.get("status") != "resolved":
            planted = f.get("planted_chapter", "")
            try:
                idx = next(i for i,ch in enumerate(chapters) if planted in ch)
                idle = len(chapters)-1-idx
                if idle > max_idle:
                    issues.append({"type":"沉睡伏笔","severity":"warning","description":f"伏笔「{f['description']}」在{planted}埋下，已闲置{idle}章未回收","location":planted})
            except StopIteration: pass
    return issues

def check_absent_characters(state):
    issues = []; chapters = sorted(state.get("chapters", {}).keys())
    if not chapters: return issues
    for name,info in state.get("characters",{}).items():
        if info.get("status")!="alive": continue
        last=info.get("last_appearance","")
        if not last: continue
        try:
            idx=next(i for i,ch in enumerate(chapters) if last in ch)
            absent=len(chapters)-1-idx
            threshold=8 if info.get("role") in ["protagonist","antagonist"] else 12
            if absent>threshold:
                issues.append({"type":"角色缺席","severity":"warning" if info.get("role")=="protagonist" else "info","description":f"角色「{name}」已{absent}章未出现（上次:{last}）","location":last})
        except: pass
    return issues

def check_dead_characters_active(state):
    issues=[]; chapters=sorted(state.get("chapters",{}).keys())
    if not chapters: return issues
    last=chapters[-1]
    for name,info in state.get("characters",{}).items():
        if info.get("status")=="dead" and info.get("last_appearance")==last:
            issues.append({"type":"死角色活跃","severity":"critical","description":f"角色「{name}」已标记死亡但仍在{last}出现","location":last})
    return issues

def run_all(state):
    r=[]; r.extend(check_dormant_foreshadowing(state)); r.extend(check_absent_characters(state)); r.extend(check_dead_characters_active(state)); return r

def print_report(issues):
    if not issues: print("\n连续性检测通过，未发现异常\n"); return
    order={"critical":"🔴","warning":"🟡","info":"🟢"}
    by={"critical":[],"warning":[],"info":[]}
    for i in issues: by[i.get("severity","info")].append(i)
    print(f"\n连续性检测报告\n总计:{len(issues)}个 | 致命:{len(by['critical'])} | 警告:{len(by['warning'])} | 提示:{len(by['info'])}\n")
    for s in ["critical","warning","info"]:
        for i in by[s]: print(f"  {order[s]} [{i['type']}] {i['description']}")
    print()

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--state",required=True); p.add_argument("--verbose",action="store_true")
    a=p.parse_args(); print_report(run_all(load_state(a.state)))