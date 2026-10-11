#!/usr/bin/env python3
"""
story-state.py — 小说持久化状态管理器 v1.0

功能：
  1. 从章节正文自动提取角色状态、伏笔、时间线
  2. 维护中央 state.json 文件，供所有子Agent共享
  3. 每次快刀写完一章后自动更新状态

用法：
  story-state.py --init --title "书名" --genre "题材"
  story-state.py --update --file 章节.md
  story-state.py --show
  story-state.py --export
"""

import os, re, sys, json
from datetime import datetime

STATE_FILE = "story-state.json"

DEFAULT_STATE = {
    "project": {"title": "", "author": "", "genre": "", "created": "", "updated": ""},
    "chapters": {},
    "characters": {},
    "plot_threads": {},
    "foreshadowing": [],
    "timeline": {},
    "world_rules": [],
    "quality_scores": {}
}

def load_state(path=None):
    path = path or STATE_FILE
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return dict(DEFAULT_STATE)

def save_state(state, path=None):
    path = path or STATE_FILE
    state["project"]["updated"] = datetime.now().isoformat()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"✅ 状态已保存: {path}")

def extract_chapter_number(text):
    m = re.search(r'(第[一二三四五六七八九十百千\d]+章)', text[:200])
    return m.group(1) if m else "未知章节"

def extract_characters(text):
    known = {
        "夜岚": ["夜岚", "月神之女"],
        "苍炎": ["苍炎", "狼王", "暴风狼王"],
        "雪薇": ["雪薇", "白狐千金"],
        "凌霄": ["凌霄", "独眼老人"],
        "月牙": ["月牙", "短发狼女"],
        "白崖": ["白崖", "银月族长"],
        "白狐族长": ["白狐族长", "雪薇之父"],
        "铁牙": ["铁牙"],
        "月瑶": ["月瑶", "夜澜", "上代月神"],
    }
    found = {}
    for name, aliases in known.items():
        for alias in aliases:
            if alias in text:
                found[name] = found.get(name, 0) + text.count(alias)
                break
    return found

def extract_plot_progress(text, chapter):
    progress = []
    if re.search(r'(捏碎|打飞|碾压|踩脸|击杀|斩杀)', text): progress.append("战斗冲突")
    if re.search(r'(觉醒|突破|解锁|激活)', text): progress.append("能力突破")
    if re.search(r'(跪下|臣服|跪伏|匍匐)', text): progress.append("权力反转")
    if re.search(r'(退婚|决裂|背叛|原谅|和解)', text): progress.append("关系变化")
    if re.search(r'(揭示|真相|秘密|原来)', text): progress.append("信息揭示")
    if re.search(r'(会议|议会|谈判|结盟)', text): progress.append("政治事件")
    return progress

def cmd_init(args):
    state = dict(DEFAULT_STATE)
    state["project"]["title"] = args.get("title", "")
    state["project"]["genre"] = args.get("genre", "")
    state["project"]["author"] = args.get("author", "")
    state["project"]["created"] = datetime.now().isoformat()
    save_state(state, args.get("path"))
    print(f"📖 项目已初始化: {state['project']['title']}")

def cmd_update(args):
    filepath = args.get("file")
    if not filepath or not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        return
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    state = load_state(args.get("path"))
    chapter = extract_chapter_number(text)
    words = len(re.sub(r'\s+', '', text))
    state["chapters"][chapter] = {
        "status": "draft", "words": words,
        "summary": text[:100].replace('\n', ' ').strip()[:80] + "...",
        "key_events": extract_plot_progress(text, chapter)
    }
    chars_found = extract_characters(text)
    for name, count in chars_found.items():
        if name not in state["characters"]:
            state["characters"][name] = {
                "role": "unknown", "status": "alive",
                "last_appearance": chapter, "emotional_state": "",
                "knowledge": [], "relationships": {}
            }
        state["characters"][name]["last_appearance"] = chapter
    if chapter not in state["timeline"]:
        state["timeline"][chapter] = {"in_story_time": "", "events": extract_plot_progress(text, chapter)}
    else:
        existing = state["timeline"][chapter]["events"]
        for e in extract_plot_progress(text, chapter):
            if e not in existing: existing.append(e)
    save_state(state, args.get("path"))
    print(f"✅ 已更新: {chapter} ({words}字) | 角色: {', '.join(chars_found.keys())}")

def cmd_show(args):
    state = load_state(args.get("path"))
    print(f"\n📖 {state['project']['title']} ({state['project']['genre']})")
    print(f"   章节: {len(state['chapters'])}章 | 角色: {len(state['characters'])}个 | 伏笔: {len(state['foreshadowing'])}个\n")
    if state['chapters']:
        print("📋 章节状态:")
        for ch, info in sorted(state['chapters'].items()):
            icon = {'draft': '📝', 'reviewed': '🔍', 'approved': '✅'}.get(info['status'], '📝')
            print(f"   {icon} {ch}: {info['words']}字 {', '.join(info['key_events'])}")
    if state['characters']:
        print("\n👥 角色:")
        for name, info in sorted(state['characters'].items()):
            icon = '✅' if info['status'] == 'alive' else '💀'
            print(f"   {icon} {name} ({info['role']}) - 最近: {info['last_appearance']}")

def cmd_export(args):
    state = load_state(args.get("path"))
    output = args.get("output", "状态报告.md")
    lines = [f"# 状态报告：{state['project']['title']}\n\n"]
    lines.append(f"| 章节 | {len(state['chapters'])} | 角色 | {len(state['characters'])} |\n")
    with open(output, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    print(f"✅ 报告已导出: {output}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--init", action="store_true")
    p.add_argument("--update", action="store_true")
    p.add_argument("--show", action="store_true")
    p.add_argument("--export", action="store_true")
    p.add_argument("--file"); p.add_argument("--path"); p.add_argument("--output")
    p.add_argument("--title"); p.add_argument("--genre"); p.add_argument("--author")
    a = p.parse_args()
    d = {k: v for k, v in vars(a).items() if v is not None}
    if a.init: cmd_init(d)
    elif a.update: cmd_update(d)
    elif a.show: cmd_show(d)
    elif a.export: cmd_export(d)
    else: p.print_help()
