#!/usr/bin/env python3
"""
ss-check — 短故事爆款结构检测工具 v1.0

与 wn-check（长篇质检）完全不同：
  wn-check = 机械层/叙事层/跨章衔接（缺字/引号/时间线/称呼）
  ss-check = 结构层/节奏层/情绪层（钩子/爽点/情绪曲线/人设逻辑）

用法：
  ss-check --file 短篇正文.txt          # 检测单篇短故事
  ss-check --file 短篇正文.txt --full    # 全量检测（默认）
  ss-check --file 短篇正文.txt --module S2,S4  # 只跑指定模块
  ss-check --file 短篇正文.txt --summary-only # 只出综合评分

检测模块：
  S1: 黄金三章结构   — 前300字钩子 + 前三章结构完整性
  S2: 每章结构       — 四段式节奏（钩子→冲突→爽点→新钩子）
  S3: 章末钩子质量   — 四种钩子类型识别 + 强度评分
  S4: 情绪节奏       — 爽点间隔 / 虐爽比例 / 情绪曲线
  S5: 人设逻辑       — 反派动机 / 女主清醒度 / 情感转变依据
  S6: 爆款综合指标   — 综合评分 + 修改建议
  S7: 叙事质量       — AI句式/副词/全知视角/心理总结/时间锚违规/场景跳转
  S8: 对话格式       — 引号配对/对话碎片检测
  S9: 文字层检测     — 缺字/标点/命名规范（移植自wn-check A1/A2/I）
"""

import os, re, sys, json
from collections import defaultdict, Counter

# ══════════════════════════════════════════
#  配置
# ══════════════════════════════════════════

CHAPTER_SIZE_MIN = 1000       # 单章最少字数
CHAPTER_SIZE_OPT = (2000, 3000)  # 黄金字数区间
HOOK_PER_500_TARGET = 1.0    # 每500字理想钩子密度
MAX_PLAIN_CHAPTERS = 3       # 最长连续无爽点章节数
DIALOG_RATIO_MIN = 0.40      # 对话占比下限
SENTENCE_MAX = 25            # 句子最大字数
PARA_MAX = 3                 # 段落最大行数

LQ = '\u201c'
RQ = '\u201d'
LQ_ALT = '\u300c'  # 「
RQ_ALT = '\u300d'  # 」
LQ_STRAIGHT = '\u0022'  # " ASCII直引号
RQ_STRAIGHT = '\u0022'  # "

# ══════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════

def load_file(path):
    """读取文件，返回文本"""
    if not os.path.exists(path):
        print(f"❌ 文件不存在: {path}")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def split_chapters(text):
    """按章节标记分割，返回 [(章号, 文本), ...]"""
    # 支持多种章节标题格式：第1章、## 第1章、### Ch1 等
    ch_pattern = r'^(?:#+\s*)?(?:第[一二三四五六七八九十百千\d]+章[^\n]*|[Cc]hapter\s+\d+)'
    lines = text.split('\n')
    chapters = []
    current_title = None
    current_lines = []
    
    for line in lines:
        stripped = line.strip()
        if re.match(ch_pattern, stripped):
            if current_title:
                chapters.append((current_title, '\n'.join(current_lines).strip()))
            current_title = stripped
            current_lines = []
        else:
            if current_title:  # 只有在已进入章节后才收集
                current_lines.append(line)
    
    if current_title:
        chapters.append((current_title, '\n'.join(current_lines).strip()))
    
    return chapters

def extract_dialog(text):
    """提取对话部分文本（支持“”、「」和ASCII直引号）"""
    # 标准弯引号
    dialogs = re.findall(f'{LQ}[^{RQ}]*{RQ}', text)
    # 直角引号
    alt_dialogs = re.findall(f'{LQ_ALT}[^{RQ_ALT}]*{RQ_ALT}', text)
    # ASCII直引号（配对检测：找成对的"中间的内容）
    straight_dialogs = re.findall(r'\u0022[^\u0022]*\u0022', text)
    total_dialog = sum(len(d) for d in dialogs) + sum(len(d) for d in alt_dialogs) + sum(len(d) for d in straight_dialogs)
    # 也统计对话标记附近的动作
    dialog_action = re.findall(f'[^。，！？\\n]*{LQ}[^{RQ}]*{RQ}[^。，！？\\n]*', text)
    alt_action = re.findall(f'[^。，！？\\n]*{LQ_ALT}[^{RQ_ALT}]*{RQ_ALT}[^。，！？\\n]*', text)
    straight_action = re.findall(r'[^。，！？\\n]*\u0022[^\u0022]*\u0022[^。，！？\\n]*', text)
    total_with_context = sum(len(d) for d in dialog_action) + sum(len(d) for d in alt_action) + sum(len(d) for d in straight_action)
    return total_dialog, total_with_context

def count_sentences(text):
    """计数句子"""
    sents = re.split(r'[。！？!?\n]', text)
    return [s.strip() for s in sents if s.strip()]

def count_paragraphs(text):
    """按换行分段"""
    paras = text.split('\n')
    return [p.strip() for p in paras if p.strip()]

def clean_text(text):
    """清理文本用于字数统计"""
    return re.sub(r'\s+', '', text)

# ══════════════════════════════════════════
#  S1: 黄金三章结构检测
# ══════════════════════════════════════════

def scan_S1(data):
    """黄金三章结构检测"""
    issues = []
    text = data['text']
    cleaned = clean_text(text)

    # 1.1 前300字是否有钩子
    opening = text[:500]  # 多取一点确保完整句子
    hook_patterns = [
        # 事件钩子（原有）
        r'(突然|忽然|没想到|万万没想到|竟然|居然|怎么可能)',
        r'(死|杀|捅|刺|跪|哭|尖叫|崩溃|完了)',
        r'(重生|穿越|醒来|睁开眼|回到)',
        f'({LQ}.*?[！？!?]{RQ})',
        f'({LQ_STRAIGHT}.*?[！？!?]{RQ_STRAIGHT})',
        r'(这不是|怎么可能|不对劲|出事了)',
        # 情感钩子（新增 — 重生复仇类专用）
        r'(上一世|前世|上辈子|含恨|含冤|冤枉|冤死|不甘心)',
        r'(背叛|出卖|欺骗|欺骗|陷害|构陷|诬陷|栽赃)',
        r'(恨|复仇|报仇|血债|满门|灭门|抄家|家破人亡)',
        r'(再睁眼|再睁开眼|回到|重来|再一次)',
        # 穿书类钩子（新增 — 现代脑洞类专用）
        r'(穿书|穿越|穿成|穿到|穿进|醒来|一睁眼|一睁眼发现)',
        r'(系统|弹幕|直播间|评论区|攻略|任务)',
        r'(离婚协议|签字离婚|民政局|离婚证|结婚证)',
        # 对比类钩子（新增 — 前后世反差）
        r'(上一世[^。，！？]{0,20}这一世)',
        r'(曾经[^。，！？]{0,15}如今)',
        r'(我以为[^。，！？]{0,15}却)',
        # ====== 新增：通用对比结构 ======
        r'\d+年前[^。，！？]{0,15}如今',
        r'\d+年前[^。，！？]{0,15}现在',
        r'(当年[^。，！？]{0,10}如今)',
        # ====== 新增：冲突动词（西幻/都市通用）=====
        r'(撕碎|捏碎|踩碎|咬碎)',
        r'(退婚|分手|决裂|割袍|断义|绝交)',
        r'(逐出|废除|贬为|剥夺|收回)',
        r'(吐血|断骨|碎甲|穿胸|斩首)',
        # ====== 新增：强情绪词 ======
        r'(冷笑|讥笑|嘲讽|鄙夷|蔑视)',
        r'(颤抖|发抖|哆嗦|痉挛|抽搐)',
        r'(绝望|崩溃|疯狂|疯魔|癫狂)',
        # ====== 新增：权力/身份反转 ======
        r'(跪下|跪伏|臣服|匍匐|叩首)',
        r'(觉醒|解锁|激活|解封|复苏)',
        r'(女王|王者|主宰|霸主|至尊)',
    ]
    hook_found = []
    for i, pat in enumerate(hook_patterns):
        m = re.search(pat, opening[:300])
        if m:
            hook_found.append(m.group())
    
    if len(hook_found) >= 2:
        hook_score = '🟢'
        hook_detail = f'检测到{len(hook_found)}个钩子信号'
    elif len(hook_found) == 1:
        hook_score = '🟡'
        hook_detail = f'仅1个钩子信号，需增强'
    else:
        hook_score = '🔴'
        hook_detail = '前300字无钩子信号'

    issues.append({
        'module': 'S1',
        'check': '前300字钩子',
        'score': hook_score,
        'detail': hook_detail + ': ' + ', '.join(hook_found[:3]) if hook_found else hook_detail
    })

    # 1.2 前300字是否有异常事件/冲突
    conflict_markers = [
        r'(冲突|对峙|威胁|逼迫|羞辱|欺|骂|打|砸|毁)',
        r'(危|险|救|命|逃|追|杀|刺|毒)',
        r'(哭|跪|求|伤|血|痛|疼)',
        r'(摔|砸|撞|撕|扯)',
        # 情感冲突（新增 — 女频古言专用）
        r'(恨|仇|冤|冤枉|陷害|背叛|出卖|欺骗|构陷)',
        r'(灭门|抄家|满门|死|亡|毒酒|冷宫|枭首|乱箭)',
        r'(不甘|含恨|含冤|心寒|心冷|觉醒|清醒)',
        # 情感冲突（新增 — 现代情感专用）
        r'(离婚|分手|背叛|出轨|小三|白月光|逼|跪|求)',
    ]
    conflict_count = sum(len(re.findall(p, opening[:300])) for p in conflict_markers)
    if conflict_count >= 3:
        conflict_score = '🟢'
        conflict_detail = f'冲突密集（{conflict_count}处）'
    elif conflict_count >= 1:
        conflict_score = '🟡'
        conflict_detail = f'有冲突但偏少（{conflict_count}处）'
    else:
        conflict_score = '🔴'
        conflict_detail = '前300字无冲突'

    issues.append({
        'module': 'S1',
        'check': '开篇冲突',
        'score': conflict_score,
        'detail': conflict_detail
    })

    # 1.3 第一章结尾是否有钩子
    chapters = data.get('chapters', [])
    if chapters:
        ch1_text = chapters[0][1]
        ch1_end = ch1_text[-200:] if len(ch1_text) > 200 else ch1_text
        end_hook_patterns = [
            # 事件悬念（原有）
            r'(突然|这时|就在这时|正在这时|没想到|正在)',
            r'(出现了|来了|走了进来|走了进来|出现在)',
            r'(怎么回事|什么情况|这是|难道)',
            r'(明天的|接下来|下一|即将)',
            r'(门|窗|外|脚步声|敲门|电话响|消息)',
            r'(完了|不好|糟糕|不妙)',
            # 情绪钩子（新增）
            r'(恨|恨意|冷笑|笑了|抬眼|抬眼看他|抬头)',
            r'(这一世|这辈子|这一回|这一次)',
            r'(我不会再|再也不|决不会|休想)',
            r'(跪|求饶|认输|认罪|颤抖|发抖)',
            r'(等着|走着瞧|你等着)',
            # 对话宣言式（新增 — 女频常用）
            f'{LQ}[^。，！？\\\\n]{{10,50}}[！？]{RQ}',
            f'{LQ_ALT}[^{RQ_ALT}。，！？\\\\n]{{10,50}}[！？]{RQ_ALT}',
            f'{LQ_STRAIGHT}[^。，！？\\\\n]{{10,50}}[！？]{RQ_STRAIGHT}',
            # 金句式收尾
            r'(不过是|不过是把|不过是枚|不过是个)',
            r'(棋子|翻面|反手|还回去|拿回来)',
        ]
        end_hook_found = [p for p in end_hook_patterns if re.search(p, ch1_end)]
        if len(end_hook_found) >= 2:
            end_score = '🟢'
            end_detail = '章尾有强钩子，读者会想看下一章'
        elif len(end_hook_found) == 1:
            end_score = '🟡'
            end_detail = '章尾钩子偏弱'
        else:
            end_score = '🔴'
            end_detail = '章尾无钩子，读者可能弃书'
        issues.append({
            'module': 'S1',
            'check': '第一章尾钩子',
            'score': end_score,
            'detail': end_detail
        })
    else:
        issues.append({
            'module': 'S1',
            'check': '第一章尾钩子',
            'score': '⚠️',
            'detail': '未检测到章节分割，跳过'
        })

    return issues

# ══════════════════════════════════════════
#  S2: 每章结构检测（四段式节奏）
# ══════════════════════════════════════════

def scan_S2(data):
    """每章结构检测：字数/段落/句子/对话比"""
    issues = []
    text = data['text']
    chapters = data.get('chapters', [])

    # 2.1 单章字数检测
    if chapters:
        for title, ctext in chapters:
            clen = len(clean_text(ctext))
            if clen < CHAPTER_SIZE_MIN:
                issues.append({
                    'module': 'S2',
                    'check': f'{title} 字数',
                    'score': '🔴',
                    'detail': f'{clen}字 < 最低{CHAPTER_SIZE_MIN}字'
                })
            elif clen < CHAPTER_SIZE_OPT[0]:
                issues.append({
                    'module': 'S2',
                    'check': f'{title} 字数',
                    'score': '🟡',
                    'detail': f'{clen}字 < 黄金区间{CHAPTER_SIZE_OPT[0]}-{CHAPTER_SIZE_OPT[1]}'
                })
            elif clen > CHAPTER_SIZE_OPT[1]:
                issues.append({
                    'module': 'S2',
                    'check': f'{title} 字数',
                    'score': '🟡',
                    'detail': f'{clen}字 > 黄金区间上限{CHAPTER_SIZE_OPT[1]}'
                })

        # 汇总
        under_min = sum(1 for t,c in chapters if len(clean_text(c)) < CHAPTER_SIZE_MIN)
        under_opt = sum(1 for t,c in chapters if CHAPTER_SIZE_MIN <= len(clean_text(c)) < CHAPTER_SIZE_OPT[0])
        over_opt = sum(1 for t,c in chapters if len(clean_text(c)) > CHAPTER_SIZE_OPT[1])
        in_opt = len(chapters) - under_min - under_opt - over_opt
        
        if in_opt >= len(chapters) * 0.6:
            s2_score = '🟢'
            s2_detail = f'{in_opt}/{len(chapters)}章在黄金字数区间'
        elif in_opt >= len(chapters) * 0.3:
            s2_score = '🟡'
            s2_detail = f'仅{in_opt}/{len(chapters)}章符合黄金字数，建议调整'
        else:
            s2_score = '🔴'
            s2_detail = f'多数章节字数偏离黄金区间'

    else:
        # 无章节分割，按整体检测
        clen = len(clean_text(text))
        if clen < 10000:
            s2_score = '🟡'
            s2_detail = f'全文{clen}字，偏短（短故事建议3-5万字）'
        elif clen < 30000:
            s2_score = '🟢'
            s2_detail = f'全文{clen}字，适合短故事（3-5万字最佳）'
        elif clen <= 50000:
            s2_score = '🟢'
            s2_detail = f'全文{clen}字，黄金字数区间'
        else:
            s2_score = '🟡'
            s2_detail = f'全文{clen}字，偏长篇'

    issues.append({
        'module': 'S2',
        'check': '字数控制',
        'score': s2_score,
        'detail': s2_detail
    })

    # 2.2 句子长度
    sentences = count_sentences(text)
    long_sents = [s for s in sentences if len(s) > SENTENCE_MAX]
    if long_sents:
        ratio = len(long_sents) / len(sentences) if sentences else 0
        if ratio > 0.3:
            s2b_score = '🔴'
        elif ratio > 0.15:
            s2b_score = '🟡'
        else:
            s2b_score = '🟢'
    else:
        s2b_score = '🟢'
    issues.append({
        'module': 'S2',
        'check': '句子长度（≤25字）',
        'score': s2b_score,
        'detail': f'{len(long_sents)}/{len(sentences)}句超{SENTENCE_MAX}字' if long_sents else '全部合格'
    })

    # 2.3 对话占比（古风模式阈值35%，标准模式40%）
    # 自动检测是否为古风：检查关键词
    is_ancient_style = any(w in text[:500] for w in ['宫', '殿', '皇上', '陛下', '娘娘', '太子', '王爷',
                                                       '侯爷', '小姐', '丫鬟', '奴婢', '妾身', '臣女',
                                                       '本宫', '本侯', '孤', '朕', '圣旨', '凤冠'])
    dialog_ratio_target = 0.35 if is_ancient_style else 0.40
    total_chars = len(clean_text(text))
    dialog_chars, dialog_with_context = extract_dialog(text)
    if total_chars > 0:
        dialog_ratio = dialog_chars / total_chars
        if dialog_ratio < dialog_ratio_target:
            s2c_score = '🟡'
            s2c_detail = f'对话占比{dialog_ratio:.1%} < {dialog_ratio_target:.0%}（{"古风推荐" if is_ancient_style else "推荐"}）'
        else:
            s2c_score = '🟢'
            s2c_detail = f'对话占比{dialog_ratio:.1%} ✅（{"古风" if is_ancient_style else "标准"}模式）'
    else:
        s2c_score = '⚠️'
        s2c_detail = '无法计算'

    issues.append({
        'module': 'S2',
        'check': '对话占比',
        'score': s2c_score,
        'detail': s2c_detail
    })

    # 逐章对话比明细（新增）
    chapters = data.get('chapters', [])
    if chapters:
        ch_dialog_details = []
        for title, ctext in chapters:
            ch_chars = len(clean_text(ctext))
            ch_dialog, _ = extract_dialog(ctext)
            ch_ratio = ch_dialog / ch_chars if ch_chars > 0 else 0
            flag = '🔴' if ch_ratio < 0.15 else ('🟡' if ch_ratio < dialog_ratio_target else '🟢')
            ch_dialog_details.append(f'{flag} {title}: {ch_ratio:.1%}')
        # 只输出最低的5章和最高的2章
        sorted_ch = sorted(ch_dialog_details, key=lambda x: float(x.split(':')[1].strip('%').replace(',', '.')) if x.split(':')[1].strip('%').replace(',', '.').replace('.','',1).isdigit() else 0)
        worst = sorted_ch[:5]
        best = sorted_ch[-2:]
        ch_detail = '最低5章: ' + ' | '.join(worst) + ' | 最高2章: ' + ' | '.join(best)
        issues.append({
            'module': 'S2',
            'check': '逐章对话比明细',
            'score': '📊',
            'detail': ch_detail
        })

    # 2.4 段落控制
    paras = count_paragraphs(text)
    long_paras = [p for p in paras if len(p) > 100]  # 大于100字视为长段落
    if long_paras:
        para_ratio = len(long_paras) / len(paras) if paras else 0
        if para_ratio > 0.3:
            s2d_score = '🟡'
            s2d_detail = f'{len(long_paras)}/{len(paras)}段偏长，建议拆分'
        else:
            s2d_score = '🟢'
            s2d_detail = '段落控制合理'
    else:
        s2d_score = '🟢'
        s2d_detail = '段落控制合理'

    issues.append({
        'module': 'S2',
        'check': '段落控制',
        'score': s2d_score,
        'detail': s2d_detail
    })

    return issues

# ══════════════════════════════════════════
#  S3: 章末钩子质量检测
# ══════════════════════════════════════════

# 四种钩子类型
HOOK_TYPES = {
    '断章取义型': [
        r'(刚要|正要|正准备|刚想)',
        r'(话还没说完|话音未落|就在[^\n]{0,10}时)',
        r'(突然.*?发现|发现.*?竟然|看到.*?是)',
        r'(门开了|门被推开|门被踹开|脚步声逼近)',
    ],
    '危机降临型': [
        r'(危险|威胁|杀意|杀气|致命|完了|不妙)',
        r'(尖叫|惊呼|惨叫声|救命|出事了)',
        r'(冲进来|闯进来|包围|围住|逼近|追来)',
        r'(不好|糟了|糟糕|小心|快跑)',
    ],
    '情绪反转型': [
        r'(没想到|万万没想到|竟然|居然|原来)',
        r'(不是.*?而是|不是.*?是)',
        r'(真相|秘密|揭露|揭穿|暴露)',
        r'(你.*?骗|竟敢|背叛|出卖|欺骗)',
    ],
    '伏笔植入型': [
        r'(一封信|一张照片|一个盒子|一件物品|一把钥匙)',
        r'(黑影|身影|人影|脚步声|敲门声)',
        r'(突然想起|忽然想起|记起|回忆|记忆)',
        r'(不认识的人|陌生|从未见过)',
    ],
    # 新增：情感收束型 — 女频古言常用
    '情感收束型': [
    r'(不过是[^。，！？\n]{0,15})',
    r'(棋子|翻面|反手|还回去|拿回来|加倍奉还)',
    r'(这一世[^。，！？\n]{0,20})',
    r'(我不会再|再也不|休想|等着瞧)',
    # 对话宣言式（有标点）
        f'{LQ}[^。，！？\\n]{{10,60}}[！？]{RQ}',
        f'{LQ_ALT}[^{RQ_ALT}。，！？\\n]{{10,60}}[！？]{RQ_ALT}',
        f'{LQ_STRAIGHT}[^。，！？\\n]{{10,60}}[！？]{RQ_STRAIGHT}',
        # 对话宣言式（无标点，支持口语化收尾）
        f'{LQ}[^！？\\n]{{2,30}}[。！？吧的么了嘛呢哦啊嗯]{RQ}',
        f'{LQ_ALT}[^！？\\n]{{2,30}}[。！？吧的么了嘛呢哦啊嗯]{RQ_ALT}',
        f'{LQ_STRAIGHT}[^！？\\n]{{2,30}}[。！？吧的么了嘛呢哦啊嗯]{RQ_STRAIGHT}',
    # 金句收尾
    r'(上辈子[^。，！？\n]{0,20}这一世)',
    r'(不过是[^。，！？\n]{0,15})',
    ],
}

def scan_S3(data):
    """章末钩子质量检测"""
    issues = []
    chapters = data.get('chapters', [])
    
    if not chapters:
        # 无章节分割，按段落分析
        paras = data['text'].split('\n\n')
        # 只检测最后的段落
        last_part = paras[-3:] if len(paras) >= 3 else paras
        last_text = '\n'.join(last_part)
        hook_matches = []
        for htype, patterns in HOOK_TYPES.items():
            for pat in patterns:
                m = re.search(pat, last_text[-300:])
                if m:
                    hook_matches.append((htype, m.group()))
        if hook_matches:
            issues.append({
                'module': 'S3',
                'check': '结尾钩子',
                'score': '🟢',
                'detail': f'检测到钩子: {hook_matches[0][0]}（"{hook_matches[0][1]}"）'
            })
        else:
            issues.append({
                'module': 'S3',
                'check': '结尾钩子',
                'score': '🔴',
                'detail': '结尾无钩子，读者可随时放下'
            })
        return issues
    
    # 按章节检测
    hook_stats = []
    for title, ctext in chapters:
        end_part = ctext[-300:] if len(ctext) > 300 else ctext
        hooks_found = []
        for htype, patterns in HOOK_TYPES.items():
            for pat in patterns:
                m = re.search(pat, end_part)
                if m:
                    hooks_found.append(htype)
                    break
        hook_stats.append({
            'title': title,
            'has_hook': len(hooks_found) > 0,
            'hook_types': list(set(hooks_found)),
            'end_text': end_part[-60:].replace('\n', ' ')
        })
    
    # 统计
    hookless = [h for h in hook_stats if not h['has_hook']]
    if hookless:
        ratio = len(hookless) / len(hook_stats)
        if ratio > 0.5:
            s3_score = '🔴'
            s3_detail = f'{len(hookless)}/{len(hook_stats)}章无钩子，大量章节读者可随时弃书'
        elif ratio > 0.2:
            s3_score = '🟡'
            s3_detail = f'{len(hookless)}/{len(hook_stats)}章无钩子，建议补充'
        else:
            s3_score = '🟢'
            s3_detail = f'{len(hookless)}/{len(hook_stats)}章无钩子，整体合格'
    else:
        s3_score = '🟢'
        s3_detail = f'全部{len(hook_stats)}章有章末钩子 ✅'
    
    issues.append({
        'module': 'S3',
        'check': '章末钩子覆盖率',
        'score': s3_score,
        'detail': s3_detail
    })
    
    # 钩子类型多样性
    all_types = []
    for h in hook_stats:
        all_types.extend(h['hook_types'])
    if all_types:
        type_counts = Counter(all_types)
        if len(type_counts) >= 3:
            issues.append({
                'module': 'S3',
                'check': '钩子类型多样性',
                'score': '🟢',
                'detail': f'使用了{len(type_counts)}种钩子类型: {", ".join(type_counts.keys())}'
            })
        elif len(type_counts) == 2:
            issues.append({
                'module': 'S3',
                'check': '钩子类型多样性',
                'score': '🟡',
                'detail': f'仅使用了{len(type_counts)}种钩子类型，建议增加变化'
            })
        else:
            issues.append({
                'module': 'S3',
                'check': '钩子类型多样性',
                'score': '🟡',
                'detail': f'钩子类型单一（仅{", ".join(type_counts.keys())}），读者容易疲劳'
            })
    
    # 列出无钩子章节
    if hookless:
        titles = [h['title'] for h in hookless[:5]]
        issues.append({
            'module': 'S3',
            'check': '无钩子章节',
            'score': '⚠️',
            'detail': f'{"、".join(titles)}{"等" if len(hookless)>5 else ""}'
        })

    return issues

# ══════════════════════════════════════════
#  S4: 情绪节奏检测
# ══════════════════════════════════════════

# 爽点关键词（按强度）
PAYOFF_WEAK = [
    '笑了', '赢了', '拿到', '获得', '突破', '升级', '发现',
    '明白了', '懂了', '想起来了',
]
PAYOFF_MEDIUM = [
    '碾压', '震惊', '全场', '跪下', '求饶', '震惊', '不敢置信',
    '打脸', '反击', '反转', '揭穿', '当众',
]
PAYOFF_STRONG = [
    '杀', '灭', '废', '死', '跪求', '痛哭', '认输',
    '臣服', '拜服', '跪', '全场死寂', '鸦雀无声',
]
SUFFER_MARKERS = [
    '羞辱', '侮辱', '欺', '辱', '伤害', '背叛', '抛弃',
    '吐血', '受伤', '哭', '绝望', '崩溃', '痛苦',
    '憋屈', '忍', '委屈', '冤枉',
]

def scan_S4(data):
    """情绪节奏检测"""
    issues = []
    text = data['text']
    chapters = data.get('chapters', [])
    
    if chapters:
        # 逐章分析情绪
        ch_emotions = []
        for title, ctext in chapters:
            weak = sum(len(re.findall(p, ctext)) for p in PAYOFF_WEAK)
            medium = sum(len(re.findall(p, ctext)) for p in PAYOFF_MEDIUM)
            strong = sum(len(re.findall(p, ctext)) for p in PAYOFF_STRONG)
            suffer = sum(len(re.findall(p, ctext)) for p in SUFFER_MARKERS)
            payoff_score = weak * 1 + medium * 3 + strong * 5
            ch_emotions.append({
                'title': title,
                'payoff': payoff_score,
                'suffer_signal': suffer,
            })
        
        # 爽点间隔检测
        dead_chapters = [c for c in ch_emotions if c['payoff'] < 3]
        if dead_chapters:
            # 找连续无爽点
            streak = 0
            max_streak = 0
            for c in ch_emotions:
                if c['payoff'] < 3:
                    streak += 1
                    max_streak = max(max_streak, streak)
                else:
                    streak = 0
            if max_streak > MAX_PLAIN_CHAPTERS:
                s4a_score = '🔴'
                s4a_detail = f'连续{max_streak}章无爽点（上限{MAX_PLAIN_CHAPTERS}章），读者会弃书'
            elif max_streak > 2:
                s4a_score = '🟡'
                s4a_detail = f'连续{max_streak}章无爽点，需注意节奏'
            else:
                s4a_score = '🟢'
                s4a_detail = f'爽点分布合理，最大空隙{max_streak}章'
        else:
            s4a_score = '🟢'
            s4a_detail = '每章都有爽点 ✅'
        
        issues.append({
            'module': 'S4',
            'check': '爽点间隔（≤3章）',
            'score': s4a_score,
            'detail': s4a_detail
        })
        
        # 虐爽比例
        total_suffer = sum(c['suffer_signal'] for c in ch_emotions)
        total_payoff = sum(c['payoff'] for c in ch_emotions)
        if total_payoff + total_suffer > 0:
            suffer_ratio = total_suffer / (total_payoff + total_suffer)
            if suffer_ratio > 0.5:
                s4b_score = '🔴'
                s4b_detail = f'虐感信号占比{suffer_ratio:.0%} > 50%，读者可能压抑弃书'
            elif suffer_ratio > 0.3:
                s4b_score = '🟡'
                s4b_detail = f'虐感信号占比{suffer_ratio:.0%}，建议控制≤30%'
            else:
                s4b_score = '🟢'
                s4b_detail = f'虐感信号占比{suffer_ratio:.0%}（推荐≤30%）'
        else:
            s4b_score = '🟡'
            s4b_detail = '未检测到明显情绪信号'

        issues.append({
            'module': 'S4',
            'check': '虐爽比例',
            'score': s4b_score,
            'detail': s4b_detail
        })

    else:
        # 无章节分割，整体分析
        total_payoff = 0
        for markers, weight in [(PAYOFF_WEAK, 1), (PAYOFF_MEDIUM, 3), (PAYOFF_STRONG, 5)]:
            for m in markers:
                total_payoff += len(re.findall(m, text)) * weight
        total_suffer = sum(len(re.findall(m, text)) for m in SUFFER_MARKERS)
        
        # 分段检测前半段 vs 后半段情绪
        half = len(text) // 2
        first_half = text[:half]
        second_half = text[half:]
        
        f_payoff = sum(len(re.findall(m, first_half)) * w 
                       for markers, w in [(PAYOFF_WEAK, 1), (PAYOFF_MEDIUM, 3), (PAYOFF_STRONG, 5)] 
                       for m in markers)
        s_payoff = sum(len(re.findall(m, second_half)) * w 
                       for markers, w in [(PAYOFF_WEAK, 1), (PAYOFF_MEDIUM, 3), (PAYOFF_STRONG, 5)] 
                       for m in markers)
        
        if s_payoff > f_payoff * 1.5 and f_payoff > 0:
            s4c_score = '🟢'
            s4c_detail = '情绪走势上升：后半段爽点密度高于前半段 ✅'
        elif s_payoff < f_payoff * 0.5:
            s4c_score = '🟡'
            s4c_detail = '情绪走势下降：后半段爽点密度低于前半段'
        else:
            s4c_score = '🟢'
            s4c_detail = '情绪走势平稳'
        
        issues.append({
            'module': 'S4',
            'check': '情绪走势（升→降）',
            'score': s4c_score,
            'detail': s4c_detail
        })

    return issues

# ══════════════════════════════════════════
#  S5: 人设逻辑检测
# ══════════════════════════════════════════

# 降智信号（反派/主角行为逻辑问题）
DUMB_SIGNALS = [
    r'(怎么会这样|不可能|这怎么可能)',
    r'(突然就.*?了|莫名其妙)',
    r'(降智|智商不在线|不合逻辑)',
]
# 恋爱脑信号（女主不清醒）
LOVE_BRAIN_SIGNALS = [
    r'(他肯定有苦衷|他不是故意的|我相信他)',
    r'(原谅|算了|不怪你|没关系)',
    r'(虽然[^。]{0,30}但我还是爱他)',
    r'(他其实很爱我|他只是太在乎我)',
]
# 情感转变无依据信号
EMO_TURN_SIGNALS = [
    r'(突然就爱上了|莫名其妙就喜欢|一眼就爱上)',
    r'(忽然心动了|不知不觉就爱上了)',
]

def scan_S5(data):
    """人设逻辑检测"""
    issues = []
    text = data['text']
    # 只检测非对话部分的叙事文本（排除角色对话中的假性信号）
    narrative_text = re.sub(f'{LQ}[^{RQ}]*{RQ}', '', text)
    narrative_text = re.sub(f'{LQ_ALT}[^{RQ_ALT}]*{RQ_ALT}', '', narrative_text)
    narrative_text = re.sub(f'"{LQ}[^"]*"', '', narrative_text)

    # 5.1 反派降智检测
    dumb_count = sum(len(re.findall(p, text)) for p in DUMB_SIGNALS)
    if dumb_count > 5:
        s5a_score = '🔴'
        s5a_detail = f'检测到{dumb_count}处降智信号，反派可能过于愚蠢'
    elif dumb_count > 2:
        s5a_score = '🟡'
        s5a_detail = f'检测到{dumb_count}处降智信号'
    else:
        s5a_score = '🟢'
        s5a_detail = '反派降智信号正常'

    issues.append({
        'module': 'S5',
        'check': '反派降智检测',
        'score': s5a_score,
        'detail': s5a_detail
    })

    # 5.2 女主恋爱脑检测
    love_count = sum(len(re.findall(p, narrative_text)) for p in LOVE_BRAIN_SIGNALS)
    if love_count > 5:
        s5b_score = '🔴'
        s5b_detail = f'叙事中检测到{love_count}处恋爱脑信号，女主缺乏清醒感'
    elif love_count > 2:
        s5b_score = '🟡'
        s5b_detail = f'叙事中检测到{love_count}处恋爱脑信号'
    else:
        s5b_score = '🟢'
        s5b_detail = '女主清醒度正常'

    issues.append({
        'module': 'S5',
        'check': '女主恋爱脑检测',
        'score': s5b_score,
        'detail': s5b_detail
    })

    # 5.3 情感转变无依据检测
    emo_count = sum(len(re.findall(p, narrative_text)) for p in EMO_TURN_SIGNALS)
    if emo_count > 3:
        s5c_score = '🟡'
        s5c_detail = f'检测到{emo_count}处情感转变无依据'
    else:
        s5c_score = '🟢'
        s5c_detail = '情感转变逻辑正常'

    issues.append({
        'module': 'S5',
        'check': '情感转变依据',
        'score': s5c_score,
        'detail': s5c_detail
    })

    return issues

# ══════════════════════════════════════════
#  S6: 爆款综合指标
# ══════════════════════════════════════════

def scan_S6(data, all_issues):
    """综合评分 + 爆款潜力预测"""
    issues = []
    
    # 计算各模块得分
    scores = {'S1': 0, 'S2': 0, 'S3': 0, 'S4': 0, 'S5': 0}
    score_map = {'🟢': 100, '🟡': 50, '🔴': 0, '⚠️': 25}
    
    for iss in all_issues:
        mod = iss['module']
        if mod in scores:
            sc = score_map.get(iss['score'], 25)
            # 取最低分（最严重的问题决定模块评分）
            if scores[mod] == 0 or sc < scores[mod]:
                scores[mod] = sc
    
    # 加权总分
    weights = {'S1': 0.25, 'S2': 0.15, 'S3': 0.20, 'S4': 0.25, 'S5': 0.15}
    total = sum(scores[m] * weights[m] for m in scores)
    
    # 评级
    if total >= 85:
        grade = 'S 🏆 爆款潜力极高'
        grade_detail = '结构完整、节奏优秀、钩子密集，具备短故事爆款条件'
    elif total >= 70:
        grade = 'A ⭐ 优秀'
        grade_detail = '整体质量高，建议针对薄弱项优化'
    elif total >= 55:
        grade = 'B 👍 合格'
        grade_detail = '基本合格，但有多处可优化空间'
    elif total >= 40:
        grade = 'C 📋 待优化'
        grade_detail = '结构性问题较多，建议重审开篇和节奏'
    else:
        grade = 'D ❌ 风险'
        grade_detail = '存在严重结构性问题，不建议直接投稿'
    
    issues.append({
        'module': 'S6',
        'check': f'综合评分 {total:.0f}/100',
        'score': '🟢' if total >= 70 else ('🟡' if total >= 40 else '🔴'),
        'detail': grade
    })
    issues.append({
        'module': 'S6',
        'check': '评级说明',
        'score': 'ℹ️',
        'detail': grade_detail
    })
    
    # 各模块得分详情
    for m in ['S1', 'S2', 'S3', 'S4', 'S5']:
        mod_names = {'S1': '黄金三章', 'S2': '章节结构', 'S3': '钩子质量', 'S4': '情绪节奏', 'S5': '人设逻辑'}
        s = scores[m]
        s_icon = '✅' if s >= 80 else ('⚠️' if s >= 40 else '❌')
        issues.append({
            'module': 'S6',
            'check': f'  {mod_names[m]}',
            'score': f'{s_icon} {s:.0f}分',
            'detail': f'权重{weights[m]:.0%}'
        })
    
    # 关键改良建议
    recommendations = []
    for iss in all_issues:
        if iss['score'] == '🔴':
            recommendations.append(f"⚠️ {iss['check']}: {iss['detail']}")
    for iss in all_issues:
        if iss['score'] == '🟡' and len(recommendations) < 6:
            recommendations.append(f"💡 {iss['check']}: {iss['detail']}")
    
    if recommendations:
        issues.append({
            'module': 'S6',
            'check': '改进建议',
            'score': '📋',
            'detail': '\n'.join(recommendations[:6])
        })
    
    return issues

# ══════════════════════════════════════════
#  AI腔辅助检测（短故事特别版）
# ══════════════════════════════════════════

AI_PATTERNS = {
    '不是X而是Y句式': r'不是[^。，！？]{1,30}而是[^。，！？]{0,30}',
    '过度衔接词': r'(然而|但是|不过|当然|显然|实际上|其实|换句话说|也就是说|值得注意的是)',
    '叙事比喻': r'(像[^。，！？]{1,15}一样|仿佛[^。，！？]{1,15}|如同[^。，！？]{1,15}|宛如[^。，！？]{1,15})',
    'AI副词': r'(默默地|缓缓地|轻轻地|静静地|悄悄地|微微地|渐渐地|慢慢地|深深地|狠狠地)',
    '叙事总结': r'(他/她/它知道|他/她/它明白|他/她/它意识到|他/她/它发现|原来|这才)',
}

def scan_AI(text):
    """AI腔检测"""
    issues = []
    for name, pat in AI_PATTERNS.items():
        matches = re.findall(pat, text)
        if matches:
            count = len(matches)
            if count > 5:
                score = '🔴'
            elif count > 2:
                score = '🟡'
            else:
                score = '🟢'
            issues.append({
                'module': 'AI',
                'check': name,
                'score': score,
                'detail': f'共{count}处' if count <= 5 else f'共{count}处（严重密集）'
            })
    return issues

# ══════════════════════════════════════════
#  S7: 叙事质量检测（移植自 wn-check B1/B2/F/H）
# ══════════════════════════════════════════

# AI句式模式
AI_SENTENCE_PATTERNS = [
    ('不是X而是Y', r'不是[^，。！？\\n]{1,30}而是'),
    ('不是X，是Y', r'不是[^，。！？\\n]{1,15}[，。][^，。！？\\n]{1,20}是'),
    ('并非X而是Y', r'并非[^，。！？\\n]{1,30}而是'),
    ('并非X，是Y', r'并非[^，。！？\\n]{1,15}[，][^，。！？\\n]{1,20}是'),
    ('不是X。是Y', r'不是[^，。！？\\n]{1,15}[。][^，。！？\\n]{1,20}是'),
]

# AI副词（禁用）
AI_ADVERBS = ['突然', '猛然', '骤然', '猝然', '瞬间', '刹时', '不禁', '不由', '忍不住', '下意识', '猛地']

# 叙事比喻
NARRATIVE_METAPHOR = [r'像[^，。\\n]{1,10}一样', r'仿佛[^，。\\n]{1,15}', r'宛如[^，。\\n]{1,15}']

# 全知视角泄露词
OMNISCIENT_LEAKS = [
    '他不知道的是', '他不知道', '他并不知道',
    '她不知道的是', '她不知道', '她并不知道',
    '他意识到', '她意识到',
    '他明白', '她明白',
    '他想起', '她想起',
    '他突然想起', '她突然想起',
    '他记得', '她记得',
    '他脑子里', '她脑子里',
    '他心中', '她心中',
    '他心里想', '她心里想',
    '他心想', '她心想',
]

# 叙事者总结心理
PSYCH_PATTERNS = [
    r'他[^。，！？]{0,8}想[，。]',
    r'她[^。，！？]{0,8}想[，。]',
    r'回忆[^。，！？]{0,5}涌',
    r'记忆[^。，！？]{0,5}涌',
    r'他[^。，！？]{0,4}沉默了',
    r'她[^。，！？]{0,4}沉默了',
    r'他脸色[^。，！？]{0,8}了',
    r'她脸色[^。，！？]{0,8}了',
]

# 时间锚违规
TIME_ANCHOR_VIOLATIONS = ['与此同时', '同一时间', '同一时刻', '同一夜']

# 叙事过渡违规
TRANSITION_VIOLATIONS = ['第二天一早', '第二天早上', '半小时后', '一个小时后']

# 场景词（用于场景跳转检测）
SCENE_WORDS = {
    '室内': ['房间', '卧室', '客厅', '书房', '厨房', '阳台', '走廊', '门口', '大厅', '花厅', '正房', '厢房'],
    '室外': ['街上', '路边', '巷口', '马路', '路口', '院墙', '花园', '后院', '前院'],
    '办公': ['办公室', '书房', '书房', '书房'],
    '餐饮': ['茶楼', '酒楼', '饭馆', '茶馆', '花厅'],
    '车轿': ['马车', '轿子', '车内', '车里'],
}


def scan_S7(data):
    """叙事质量检测"""
    issues = []
    paras = data['text'].split('\n')
    content_paras = [p for p in paras if p.strip()]
    
    # 7.1 AI句式（不是X而是Y类）
    ai_sentence_hits = []
    for i, p in enumerate(content_paras):
        s = p.strip()
        if s.startswith(LQ) or s.startswith(LQ_ALT) or s.startswith('"'): 
            continue
        for desc, pat in AI_SENTENCE_PATTERNS:
            for m in re.finditer(pat, p):
                ai_sentence_hits.append((desc, m.group()[:35]))
    
    if len(ai_sentence_hits) > 5:
        s7a_score = '🔴'
    elif len(ai_sentence_hits) > 2:
        s7a_score = '🟡'
    elif len(ai_sentence_hits) > 0:
        s7a_score = '🟢'
    else:
        s7a_score = '🟢'
    examples = ', '.join(f'[{d}]{t}' for d, t in ai_sentence_hits[:3])
    issues.append({
        'module': 'S7',
        'check': 'AI句式（不是X而是Y）',
        'score': s7a_score,
        'detail': f'共{len(ai_sentence_hits)}处' + (f': {examples}' if ai_sentence_hits else ' ✅')
    })
    
    # 7.2 AI副词
    adverb_hits = []
    for i, p in enumerate(content_paras):
        for adv in AI_ADVERBS:
            if adv in p:
                adverb_hits.append((adv, p.strip()[:30]))
    if len(adverb_hits) > 10:
        s7b_score = '🔴'
    elif len(adverb_hits) > 5:
        s7b_score = '🟡'
    else:
        s7b_score = '🟢'
    examples = ', '.join(f'"{w}"' for w, _ in adverb_hits[:5])
    issues.append({
        'module': 'S7',
        'check': 'AI副词（突然/猛然/不禁等）',
        'score': s7b_score,
        'detail': f'共{len(adverb_hits)}处' + (f': {examples}' if adverb_hits else ' ✅')
    })
    
    # 7.3 叙事比喻
    meta_hits = []
    for i, p in enumerate(content_paras):
        for pat in NARRATIVE_METAPHOR:
            for m in re.finditer(pat, p):
                meta_hits.append(m.group()[:25])
    if len(meta_hits) > 5:
        s7c_score = '🔴'
    elif len(meta_hits) > 2:
        s7c_score = '🟡'
    else:
        s7c_score = '🟢'
    issues.append({
        'module': 'S7',
        'check': '叙事比喻（像…一样/仿佛/宛如）',
        'score': s7c_score,
        'detail': f'共{len(meta_hits)}处' + (f'（如: {meta_hits[0]}）' if meta_hits else ' ✅')
    })
    
    # 7.4 全知视角泄露
    leak_hits = []
    for i, p in enumerate(content_paras):
        if p.startswith(LQ) or p.startswith(LQ_ALT) or p.startswith('"'):
            continue
        for pat in OMNISCIENT_LEAKS:
            if pat in p:
                leak_hits.append((pat, p.strip()[:40]))
                break
    if len(leak_hits) > 5:
        s7d_score = '🔴'
    elif len(leak_hits) > 2:
        s7d_score = '🟡'
    elif len(leak_hits) > 0:
        s7d_score = '🟢'
    else:
        s7d_score = '🟢'
    examples = ', '.join(f'"{w}"' for w, _ in leak_hits[:3])
    issues.append({
        'module': 'S7',
        'check': '全知视角泄露（他知道/她想起等）',
        'score': s7d_score,
        'detail': f'共{len(leak_hits)}处' + (f': {examples}' if leak_hits else ' ✅')
    })
    
    # 7.5 叙事者总结心理
    psych_hits = []
    for i, p in enumerate(content_paras):
        if p.startswith(LQ) or p.startswith(LQ_ALT) or p.startswith('"'):
            continue
        for pat in PSYCH_PATTERNS:
            m = re.search(pat, p)
            if m:
                psych_hits.append((m.group(), p.strip()[:35]))
                break
    if len(psych_hits) > 5:
        s7e_score = '🔴'
    elif len(psych_hits) > 2:
        s7e_score = '🟡'
    elif len(psych_hits) > 0:
        s7e_score = '🟢'
    else:
        s7e_score = '🟢'
    issues.append({
        'module': 'S7',
        'check': '叙事者总结心理（他想/她沉默了/脸色变了）',
        'score': s7e_score,
        'detail': f'共{len(psych_hits)}处' + (f'（如: {psych_hits[0][0]}）' if psych_hits else ' ✅')
    })
    
    # 7.6 时间锚违规
    time_hits = []
    for i, p in enumerate(content_paras):
        for tw in TIME_ANCHOR_VIOLATIONS:
            if tw in p:
                time_hits.append((tw, p.strip()[:30]))
    if len(time_hits) > 3:
        s7f_score = '🔴'
    elif len(time_hits) > 0:
        s7f_score = '🟡'
    else:
        s7f_score = '🟢'
    examples = ', '.join(f'"{w}"' for w, _ in time_hits[:3])
    issues.append({
        'module': 'S7',
        'check': '时间锚违规（与此同时/同一时间）',
        'score': s7f_score,
        'detail': f'共{len(time_hits)}处' + (f': {examples}' if time_hits else ' ✅')
    })
    
    # 7.7 叙事过渡违规
    trans_hits = []
    for i, p in enumerate(content_paras):
        for tw in TRANSITION_VIOLATIONS:
            if tw in p:
                trans_hits.append((tw, p.strip()[:30]))
    if len(trans_hits) > 3:
        s7g_score = '🟡'
        s7g_detail = f'共{len(trans_hits)}处叙事过渡，短故事中建议控制在2次以内'
    elif len(trans_hits) > 0:
        s7g_score = '🟢'
        s7g_detail = f'共{len(trans_hits)}处，短故事中可接受'
    else:
        s7g_score = '🟢'
        s7g_detail = '叙事过渡自然 ✅'
    issues.append({
        'module': 'S7',
        'check': '叙事过渡违规（第二天一早/半小时后）',
        'score': s7g_score,
        'detail': s7g_detail + (f'（如: {trans_hits[0][0]}）' if trans_hits else '')
    })
    
    # 7.8 场景跳转检测
    zone_hits = []
    # 建立反查表
    word_to_zone = {}
    for zone, words in SCENE_WORDS.items():
        for w in words:
            word_to_zone[w] = zone
    for i in range(len(content_paras) - 1):
        cur = content_paras[i]
        nxt = content_paras[i + 1]
        if len(nxt) < 10:
            continue
        cur_zones = set()
        for w, z in word_to_zone.items():
            if w in cur:
                cur_zones.add(z)
        nxt_zones = set()
        for w, z in word_to_zone.items():
            if w in nxt:
                nxt_zones.add(z)
        if not cur_zones or not nxt_zones:
            continue
        # 有重叠 = 同一场景，不报警
        if cur_zones & nxt_zones:
            continue
        # 以对话开头 = 自然衔接
        if nxt.startswith(LQ) or nxt.startswith(LQ_ALT) or nxt.startswith('"'):
            continue
        # 以人物动作开头 = 自然衔接
        if nxt.startswith(('他', '她', '顾', '沈', '陈', '赵')):
            continue
        zone_hits.append(f'{list(cur_zones)[0]}→{list(nxt_zones)[0]}')
    
    if len(zone_hits) > 3:
        s7h_score = '🟡'
        s7h_detail = f'{len(zone_hits)}处场景跳转可能无过渡'
    elif len(zone_hits) > 0:
        s7h_score = '🟢'
        s7h_detail = f'{len(zone_hits)}处场景跳转，数量可控'
    else:
        s7h_score = '🟢'
        s7h_detail = '场景衔接自然 ✅'
    issues.append({
        'module': 'S7',
        'check': '场景跳转无过渡',
        'score': s7h_score,
        'detail': s7h_detail
    })

    return issues


# ══════════════════════════════════════════
#  S8: 对话格式检测（移植自 wn-check B5/A2）
# ══════════════════════════════════════════

def scan_S8(data):
    """对话格式检测"""
    issues = []
    paras = data['text'].split('\n')
    content_paras = [p for p in paras if p.strip()]
    text = data['text']
    
    # 8.1 引号配对（两种引号）
    lq_full = text.count(LQ) + text.count(LQ_ALT)
    rq_full = text.count(RQ) + text.count(RQ_ALT)
    
    if lq_full != rq_full:
        diff = abs(lq_full - rq_full)
        if diff > 5:
            s8a_score = '🔴'
        elif diff > 2:
            s8a_score = '🟡'
        else:
            s8a_score = '🟢'
    else:
        s8a_score = '🟢'
    issues.append({
        'module': 'S8',
        'check': '引号配对',
        'score': s8a_score,
        'detail': f'左{lq_full} ≠ 右{rq_full}' if lq_full != rq_full else f'左{lq_full} = 右{rq_full} ✅'
    })
    
    # 8.2 对话标签密度
    dialog_tags = len(re.findall(f'[^。，！？\\n]{{0,10}}{LQ}', text))
    if dialog_tags > 0:
        issues.append({
            'module': 'S8',
            'check': '对话出现频率',
            'score': '🟢',
            'detail': f'约{dialog_tags}处对话起始标记'
        })
    
    # 8.3 孤立的引号片段（引号内容只有1-2个字=可能的对话碎片）
    short_quotes = re.findall(f'{LQ}[^{RQ}]{{1,3}}{RQ}', text)
    if len(short_quotes) > 3:
        issues.append({
            'module': 'S8',
            'check': '过短对话片段',
            'score': '🟡',
            'detail': f'{len(short_quotes)}处引号内仅1-3字，可能是对话碎片'
        })

    return issues


# ══════════════════════════════════════════
#  S9: 文字层检测（移植自 wn-check A1/A2/I）
# ══════════════════════════════════════════

# 缺字模式
MISSING_CHAR_PATTERNS = {
    '缺"最"→后一':           r'(?<!最)后一(?!次|天|世|年|代|刻|页|轮|步|个|位|场|线|片|句|口)',
    '缺"最"→好别':           r'好别(查|动|去|来|说|问|管|碰|惹)',
    '缺"如"→果':             r'(?<!如)果(你|他|我|她|这|那|不|没|是|在|要|能)',
    # '缺"阳光/太阳"→阳':  已移除——阳光/太阳/夕阳等正确词汇误报率太高
    '缺"越来越"→来':         r'(?<!越)来(快|亮|大|密|远|小|重)(?=[了的，。\n])',
    '缺"挺"→背得直':         r'(?<!挺)[的她他]背得直',
    '缺"挺"→脊背得直':       r'脊背得直',
    '缺"像"→平稳得在':       r'(?<!像)平稳得在',
    '缺"可"→不可逆':         r'(?<!可)不逆的',
    '缺"有"→有没有':         r'(?<!有)(她|他)有没(有|发现|办法)',
    '缺"最"→粗/大那':        r'(?<!最)(粗|大)那(根|个|把|条|块|片)',
    '缺"最"→快/早一':        r'(?<!最)(快|早)一(点|步|个|次)',
}

# 命名规范
SURNAMES = '周李陈张赵王沈刘马孙'
JOB_PREFIXES = ['工头', '司机', '队长', '经理', '主任', '保安', '护士', '厨师']
RELATION_PREFIXES = ['陈妻', '沈妻', '王妻', '赵妻', '周妻', '李妻']


def scan_S9(data):
    """文字层检测：缺字 / 标点 / 命名规范"""
    issues = []
    text = data['text']
    lines = text.split('\n')
    
    # 9.1 缺字检测
    missing_hits = []
    for desc, pat in MISSING_CHAR_PATTERNS.items():
        for m in re.finditer(pat, text):
            start = max(0, m.start() - 8)
            end = min(len(text), m.end() + 8)
            ctx = text[start:end].replace('\n', ' ')
            missing_hits.append((desc, m.group(), ctx))
    
    if len(missing_hits) > 8:
        s9a_score = '🔴'
    elif len(missing_hits) > 3:
        s9a_score = '🟡'
    elif len(missing_hits) > 0:
        s9a_score = '🟢'
    else:
        s9a_score = '🟢'
    examples = '; '.join(f'[{d}]「{m}」' for d, m, _ in missing_hits[:5])
    issues.append({
        'module': 'S9',
        'check': '缺字检测（后→最后/果→如果/阳→阳光等）',
        'score': s9a_score,
        'detail': f'共{len(missing_hits)}处' + (f': {examples}' if missing_hits else ' ✅')
    })
    
    # 9.2 标点检测
    punct_issues = []
    
    # 孤立引号行
    for i, line in enumerate(lines):
        s = line.strip()
        if s in (LQ, RQ, LQ_ALT, RQ_ALT, '"', "'"):
            punct_issues.append(('孤立引号行', repr(s), f'L{i+1}'))
    
    # 英文省略号
    for m in re.finditer(r'\\.{3,}', text):
        punct_issues.append(('英文省略号(应为……)', m.group(), ''))
    
    # 重复标点
    for m in re.finditer(r'[，。！？、；：]{2,}', text):
        punct_issues.append(('重复标点', m.group(), ''))
    
    # 标点前空格
    for m in re.finditer(r' ([，。！？、；：）】])', text):
        punct_issues.append(('标点前多余空格', m.group().strip(), ''))
    
    if punct_issues:
        if len(punct_issues) > 5:
            s9b_score = '🟡'
        else:
            s9b_score = '🟢'
    else:
        s9b_score = '🟢'
    p_detail = '; '.join(f'{t}({p})' for t, p, _ in punct_issues[:4])
    issues.append({
        'module': 'S9',
        'check': '标点检测（孤立引号/英文省略号/重复标点/空格）',
        'score': s9b_score,
        'detail': f'共{len(punct_issues)}处' + (f': {p_detail}' if punct_issues else ' ✅')
    })
    
    # 9.3 命名规范检测
    naming_issues = []
    for i, p in enumerate(text.split('\n')):
        s = p.strip()
        if not s:
            continue
        # 职业标签（工头周/司机李）
        for jp in JOB_PREFIXES:
            if jp in s:
                idx = s.find(jp)
                after = s[idx+len(jp):idx+len(jp)+1]
                if after in SURNAMES:
                    naming_issues.append((f'职业标签: {jp}{after}', f'P{i}'))
        # 关系标签（陈妻/沈妻）
        for rp in RELATION_PREFIXES:
            if rp in s:
                naming_issues.append((f'关系标签: {rp}', f'P{i}'))
    
    if naming_issues:
        s9c_score = '🟡'
    else:
        s9c_score = '🟢'
    n_examples = '; '.join(f'{t}' for t, _ in naming_issues[:4])
    issues.append({
        'module': 'S9',
        'check': '命名规范（工头周→老周/陈妻→陈天华的妻子）',
        'score': s9c_score,
        'detail': f'共{len(naming_issues)}处' + (f': {n_examples}' if naming_issues else ' ✅')
    })
    
    return issues


# ══════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='ss-check — 短故事爆款结构检测')
    parser.add_argument('--file', '-f', required=True, help='短篇正文文件（txt）')
    parser.add_argument('--module', '-m', default='all', help='指定模块，逗号分隔，如 S1,S3')
    parser.add_argument('--full', action='store_true', default=True, help='全量检测（默认）')
    parser.add_argument('--summary-only', action='store_true', help='只出综合评分')
    args = parser.parse_args()
    
    # 读取文件
    text = load_file(args.file)
    
    # 尝试分割章节
    chapters = split_chapters(text)
    
    # 数据字典
    data = {
        'text': text,
        'chapters': chapters if chapters else [],
        'filename': os.path.basename(args.file),
    }
    
    # 确定检测模块
    if args.module == 'all':
        modules = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'S9', 'AI']
    else:
        modules = args.module.split(',')
    
    # 执行检测
    all_issues = []
    
    if 'S1' in modules:
        all_issues.extend(scan_S1(data))
    if 'S2' in modules:
        all_issues.extend(scan_S2(data))
    if 'S3' in modules:
        all_issues.extend(scan_S3(data))
    if 'S4' in modules:
        all_issues.extend(scan_S4(data))
    if 'S5' in modules:
        all_issues.extend(scan_S5(data))
    if 'S7' in modules:
        all_issues.extend(scan_S7(data))
    if 'S8' in modules:
        all_issues.extend(scan_S8(data))
    if 'S9' in modules:
        all_issues.extend(scan_S9(data))
    if 'AI' in modules:
        all_issues.extend(scan_AI(text))
    
    # S6需要所有其他结果
    if 'S6' in modules:
        all_issues.extend(scan_S6(data, all_issues))
    
    # 输出
    print(f"\n{'='*60}")
    print(f"  ss-check — 短故事爆款结构检测")
    print(f"  文件: {data['filename']}")
    total_chars = len(clean_text(text))
    print(f"  字数: {total_chars:,}字 | 章节: {len(chapters) if chapters else 1}")
    if chapters:
        print(f"  章节列表: {' → '.join(c[0] for c in chapters[:10])}{'...' if len(chapters)>10 else ''}")
    print(f"{'='*60}\n")
    
    if args.summary_only:
        # 只显示S6
        for iss in all_issues:
            if iss['module'] == 'S6':
                icon = '✅' if iss['score'] == '🟢' else ('⚠️' if iss['score'] in ['🟡','ℹ️'] else '❌')
                print(f"  {icon} {iss['check']}: {iss['score']}")
                print(f"       {iss['detail']}")
        return
    
    # 按模块分组显示
    current_module = None
    for iss in all_issues:
        if iss['module'] != current_module:
            current_module = iss['module']
            mod_names = {
                'S1': '【S1】黄金三章结构',
                'S2': '【S2】每章章节结构',
                'S3': '【S3】章末钩子质量',
                'S4': '【S4】情绪节奏',
                'S5': '【S5】人设逻辑',
                'S6': '【S6】爆款综合指标',
                'S7': '【S7】叙事质量（移植自wn-check）',
                'S8': '【S8】对话格式',
                'S9': '【S9】文字层（移植自wn-check）',
                'AI': '【AI】AI腔检测',
            }
            print(f"\n  {mod_names.get(current_module, current_module)}")
            print(f"  {'─'*50}")
        
        icon = '✅' if iss['score'] == '🟢' else ('⚠️' if iss['score'] in ['🟡','ℹ️','📋'] else '❌')
        print(f"  {icon} [{iss['score']}] {iss['check']}")
        if not args.summary_only:
            detail = iss['detail']
            if len(detail) > 100:
                detail = detail[:100] + '...'
            print(f"       {detail}")
    
    print(f"\n{'='*60}")
    
    # 统计
    green = sum(1 for i in all_issues if i['score'] == '🟢')
    yellow = sum(1 for i in all_issues if i['score'] in ('🟡', 'ℹ️', '📋', '⚠️'))
    red = sum(1 for i in all_issues if i['score'] == '🔴')
    print(f"  汇总: ✅ {green}项合格  ⚠️ {yellow}项提醒  ❌ {red}项需修复")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    main()
