"""重放确定性检查并汇总 Codex 逐条复核记录；不是人工相关性标注。"""
import argparse
from collections import Counter
import json
from pathlib import Path
from three_tower_smoke import validate_generated


def rows(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('directory', type=Path)
    args = ap.parse_args()
    root = args.directory
    items = {r['item_id']: r for r in rows(root/'generation_inputs.jsonl')}
    historical = json.loads((root/'agent_review.json').read_text(encoding='utf-8'))
    qwen_rejects = {(r['item_id'], r['language']): r['reason']
                    for r in historical['decisions'] if r['decision'] == 'reject'}
    # 本次统一执行历史提示词“不写品牌、型号”要求，纠正旧复核漏检。
    for key in [('B07Z64KSG9','zh'), ('B07FY72VRN','zh'),
                ('B07FY72VRN','en'), ('B09Z2PPHXT','zh')]:
        qwen_rejects[key] = '本轮通用需求要求不含品牌/产品系列；兼容性需求应另设生成任务'
    luna_rejects = {
        ('B07FY72VRN','en'): '包含 Blink 品牌，违反本轮通用需求的提示词约束',
        ('B097BHNV2G','zh'): '兼容打印机的打印头未给出有效属性，需求过于笼统',
    }
    summary, decisions = {}, []
    for model, filename, exclusions in [('qwen','generation_raw.jsonl',qwen_rejects),
                                         ('luna','luna_raw.jsonl',luna_rejects)]:
        counts = Counter()
        for row in rows(root/filename):
            item = items[row['item_id']]
            key = (row['item_id'], row['requested_language'])
            counts['attempted'] += 1
            payload, passed, reason = {}, False, ''
            try:
                content = row['output']
                payload = json.loads(content[content.index('{'):content.rindex('}')+1])
                counts['json_parseable'] += 1
                accepted, _ = validate_generated({'queries':[payload]}, item)
                passed = bool(accepted) and payload.get('language') == row['requested_language']
                if not passed:
                    reason = '历史自动检查未通过：语言/长度/引用字段与连续原文'
            except (ValueError, TypeError, AttributeError):
                reason = 'JSON 无法解析'
            counts['automatic_pass'] += int(passed)
            # 80 字符是原提示词要求，历史自动检查没有覆盖，单独报告。
            overlong = any(len(e.get('quote','')) > 80 for e in payload.get('evidence',[]))
            counts['overlong_evidence'] += int(overlong)
            counts['review_keep_before_quote_length'] += int(passed and key not in exclusions)
            reasons = [s for s in [reason, exclusions.get(key),
                       '引用超过提示词规定的 80 字符' if overlong else ''] if s]
            keep = passed and not reasons
            counts['review_keep'] += int(keep)
            decisions.append({'model':model,'item_id':key[0],'language':key[1],
                'query':payload.get('query'), 'automatic_pass':passed, 'decision':'keep' if keep else 'reject',
                'reasons':reasons, 'reviewer':'codex_agent_not_human',
                'fact_review':'已对照完整输入核对；引用存在不等于引用覆盖全部主张'})
        summary[model] = dict(counts)
    summary['limitations'] = ['同一代理非盲审，20 商品小样本，无人工黄金标注',
        '通用需求约束会排除事实正确的品牌/型号查询，不代表这些查询在真实搜索中无效',
        '引用长度在本轮对两个模型统一检查；与历史保留 26 条不是同一筛选口径',
        '生成质量不是召回收益；未测训练和独立搜索相关性',
        '相同可见提示词和输出上限，模型分词器、模板、运行环境不同']
    (root/'comparison_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'paired_review.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2),encoding='utf-8')
    kept = {(r['item_id'],r['language']) for r in decisions if r['model']=='luna' and r['decision']=='keep'}
    samples = []
    for r in rows(root/'luna_raw.jsonl'):
        if (r['item_id'],r['requested_language']) in kept:
            p = json.loads(r['output']); item = items[r['item_id']]
            samples.append({**p,'item_id':r['item_id'],'item_index':item['index'],
                           'split':item['split'],'group':item['group'],
                           'review_status':'codex_agent_not_human'})
    (root/'luna_samples_reviewed.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in samples),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
