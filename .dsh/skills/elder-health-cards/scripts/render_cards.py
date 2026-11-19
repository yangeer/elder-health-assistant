#!/usr/bin/env python3
"""Deterministic, offline typesetting. No OCR, diagnosis, prescribing, or TTS."""
import argparse
import json
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1240, 1754  # A4 at 150 dpi; export at 2x / 300 dpi
INK, TEAL, BG, BORDER = '#17342F', '#145B4B', '#FAFAF4', '#D7E0D8'
DISCLAIMER = '仅作健康常识解释，不替代执业医师诊断与处方调整。'
SLOTS = ['早饭前', '早饭时', '早饭后', '午饭前', '午饭时', '午饭后', '晚饭前', '晚饭时', '晚饭后', '睡前', '明确钟点']
SOURCES = {'prescription', 'pharmacy-label', 'pharmacist'}
BASE = Path(__file__).resolve().parents[1]


def text(value):
    return str(value).strip() if value is not None else ''


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('输入须为 JSON 对象')
    for key in ['demo', 'urgent']:
        if type(data.get(key)) is not bool:
            raise ValueError(f'{key} 须显式填写 true 或 false')
    for key in ['reports', 'medications', 'restrictions']:
        if not isinstance(data.get(key), list):
            raise ValueError(f'{key} 须为数组')
    if not text(data.get('date')):
        raise ValueError('须填写卡片日期 date')
    if any(not isinstance(x, str) for x in data['restrictions']):
        raise ValueError('restrictions 只接受字符串')
    for key in ['reports', 'medications']:
        if any(not isinstance(x, dict) for x in data[key]):
            raise ValueError(f'{key} 中各项须为对象')
    if len(data['medications']) > 5:
        raise ValueError('每组最多 5 种药，请按个人方案分组核对')
    if data['urgent']:
        raise ValueError('已标记紧急情况：请立即联系当地急救/就医，暂停常规卡片生成。')


def timing_matches(event):
    if not isinstance(event, dict):
        return False
    slot, timing = event.get('slot'), text(event.get('timing'))
    if slot not in SLOTS or not timing:
        return False
    normalized = timing.replace('早餐', '早饭').replace('午餐', '午饭').replace('晚餐', '晚饭')
    if slot == '明确钟点':
        return bool(re.search(r'\d{1,2}(?:[:：]\d{2}|\s*[点时])', timing))
    if slot == '睡前':
        return '睡前' in normalized
    meal, relation = slot[:2], slot[2]
    return meal in normalized and (slot in normalized or (relation == '时' and '随餐' in normalized))


def partition_meds(data):
    ready, pending = [], []
    for med in data['medications']:
        missing = [k for k in ['name', 'form', 'strength', 'dose', 'source_id', 'source_quote'] if not text(med.get(k))]
        events = med.get('events')
        valid = (med.get('confirmed') is True and med.get('conflict') is False
                 and med.get('source_type') in SOURCES and not missing
                 and re.search(r'每次.+(?:片|粒|毫升|mL|ml|mg|毫克|克|单位|喷|滴|袋|丸|支|贴|枚|微克|μg|ug)', text(med.get('dose')))
                 and isinstance(events, list) and bool(events) and all(timing_matches(e) for e in events))
        if valid:
            ready.append(med)
        else:
            reason = text(med.get('pending_reason')) or '个人用法、来源或具体时间尚未完整核实，请向医师或药师确认。'
            if med.get('conflict') is not False:
                reason = '来源有冲突或冲突状态未核实，请联系开方医师或药师。'
            pending.append((text(med.get('name')) or '药名待确认', reason))
    return ready, pending


class Canvas:
    def __init__(self, font):
        self.font_path = font
        self.cache = {}

    def font(self, size):
        if size not in self.cache:
            self.cache[size] = ImageFont.truetype(self.font_path, size)
        return self.cache[size]

    def wrap(self, value, size, width):
        out = []
        for paragraph in text(value).split('\n'):
            line = ''
            for c in paragraph:
                if line and self.draw.textlength(line + c, font=self.font(size)) > width:
                    out.append(line)
                    line = c
                else:
                    line += c
            out.append(line)
        return out

    def write(self, x, y, value, size=50, color=INK, width=1112):
        for line in self.wrap(value, size, width):
            self.draw.text((x, y), line, font=self.font(size), fill=color, stroke_width=0)
            y += int(size * 1.42)
        return y

    def fresh(self):
        self.im = Image.new('RGB', (W, H), BG)
        self.draw = ImageDraw.Draw(self.im)


class Pages(Canvas):
    def __init__(self, title, data, font, subtitle=''):
        super().__init__(font)
        self.title, self.data, self.subtitle = title, data, subtitle
        self.pages = []
        self.new_page()

    def new_page(self):
        self.fresh()
        self.draw.rectangle((0, 0, W, 20), fill=TEAL)
        tag = '演示，不能作为服药依据' if self.data['demo'] else '信息整理卡 · 请对照原始材料'
        self.write(64, 46, tag, 38, TEAL)
        self.write(64, 110, self.title, 64)
        self.write(64, 208, f"{text(self.data.get('person')) or '长辈'} · {self.data['date']}", 38)
        self.y = 290
        if self.subtitle:
            self.y = self.write(64, self.y, self.subtitle, 38) + 20

    def flush(self):
        self.draw.line((64, 1508, W-64, 1508), fill=BORDER, width=2)
        self.write(64, 1530, DISCLAIMER, 38)
        self.write(64, 1650, f'第 {len(self.pages)+1} 页 · 保留原始材料供核对', 38, TEAL)
        self.pages.append(self.im.copy())

    def panel(self, lines, fill='#FFFFFF'):
        height = 44 + sum(len(self.wrap(t, size, 1032)) * int(size*1.42) + 10 for t, size, _ in lines)
        if height > 1190:
            raise ValueError('单项内容过长，请拆分成完整条目，不能缩小字号或截断')
        if self.y + height > 1480:
            self.flush()
            self.new_page()
        self.draw.rounded_rectangle((64, self.y, W-64, self.y+height), radius=22, fill=fill, outline=BORDER, width=2)
        y = self.y + 22
        for t, size, color in lines:
            y = self.write(104, y, t, size, color, 1032) + 10
        self.y += height + 22

    def save(self, output, name):
        self.flush()
        save_images(self.pages, output, name)


def save_images(images, output, name):
    large = [im.resize((2480, 3508), Image.Resampling.LANCZOS) for im in images]
    for i, im in enumerate(large, 1):
        im.save(output / f'{name}-{i:02}.png', dpi=(300, 300))
    large[0].save(output / f'{name}.pdf', 'PDF', resolution=300, save_all=True, append_images=large[1:])


def template(output, font):
    c = Canvas(font)
    c.fresh()
    c.draw.rectangle((0, 0, W, 20), fill=TEAL)
    c.write(64, 44, '空白模板 · 未核实前不能作为服药依据', 38, TEAL)
    c.write(64, 108, '每日用药时刻表', 72)
    c.write(64, 220, '称呼：______    方案日期：________', 42)
    for row, meal in enumerate(['早', '午', '晚']):
        for col, rel in enumerate(['饭前', '饭后']):
            x, y, width = 64 + col*568, 320 + row*334, 544
            c.draw.rounded_rectangle((x, y, x+width, y+310), radius=18, fill='#FFFFFF', outline=BORDER, width=2)
            c.draw.rounded_rectangle((x, y, x+width, y+84), radius=18, fill=TEAL if col == 0 else '#DCEAE0')
            c.write(x+24, y+9, meal+rel, 50, '#FFFFFF' if col == 0 else INK, width-48)
            c.write(x+24, y+106, '药名：______', 50, INK, width-48)
            c.write(x+24, y+169, '每次：___单位', 50, INK, width-48)
            c.write(x+24, y+240, '规格/来源：____', 38, INK, width-48)
    c.write(64, 1350, '随餐、睡前、明确钟点用药：另页记录。', 42)
    c.write(64, 1420, '待确认：________________________', 42)
    c.draw.line((64, 1508, W-64, 1508), fill=BORDER, width=2)
    c.write(64, 1530, DISCLAIMER, 38)
    c.write(64, 1650, '医嘱有变化，请重新核对本表。', 38, TEAL)
    save_images([c.im], output, '每日用药时刻表-空白模板')
    # Supplement preserves timing beyond the six mealtime cells.
    data = {'person':'______', 'date':'________', 'demo':False}
    p = Pages('其他时段用药记录', data, font, '空白模板 · 按完整个人医嘱填写，不能推算。')
    for label in ['早 / 午 / 晚 · 随餐', '睡前', '明确钟点 / 特定间隔']:
        p.panel([(label, 50, TEAL), ('药名 / 剂型 / 规格：________', 50, INK), ('每次剂量：____  时间原文：____', 50, INK), ('个人用法来源 / 核对人：______', 38, INK)])
    p.save(output, '每日用药时刻表-其他时段附页')


def render(data, output, font):
    validate(data)
    kb = json.loads((BASE/'references/knowledge.json').read_text(encoding='utf-8'))
    metrics = {m['id']:m for m in kb['metrics']}
    ready, pending = partition_meds(data)
    leaflets = [
        med for med in data['medications']
        if med.get('source_type') == 'leaflet'
        and all(text(med.get(key)) for key in ('name', 'source_id', 'source_quote'))
    ]
    if leaflets:
        leaflet_page = Pages('说明书用法大字卡', data, font)
        for med in leaflets:
            name = text(med['name'])
            form = text(med.get('form'))
            details = ' · '.join(filter(None, ('' if form in name else form, text(med.get('strength')))))
            quote = re.sub(r'(?<=。)(?=\S)', '\n', text(med['source_quote']), count=1)
            leaflet_page.y += 24
            leaflet_page.panel([
                ('药品信息', 38, TEAL),
                (name, 64, INK),
                *([(details, 46, INK)] if details else []),
            ])
            leaflet_page.y += 18
            leaflet_page.panel([
                ('用法用量 · 原文', 38, TEAL),
                (quote, 56, INK),
            ], '#EAF5EF')
            leaflet_page.y += 18
            leaflet_page.panel([
                ('说明书通用信息，请核对个人用法。', 42, INK),
                ('来源：' + text(med['source_id']), 38, TEAL),
            ])
        leaflet_page.save(output, '说明书用法大字卡')
    if data['reports']:
        p = Pages('体检指标大白话卡', data, font, '箭头不是诊断，下一步请结合医生评估。')
        for r in data['reports']:
            m = metrics.get(r.get('metric_id'))
            verified = r.get('confirmed') is True and m and text(r.get('name')) in [m['name'], *m['aliases']] and all(text(r.get(k)) for k in ['name','value','unit','reference','source_id','source_quote','test_date'])
            if not verified:
                p.panel([(text(r.get('name')) or '指标待确认', 52, TEAL), ('待确认：请核对指标名称、结果、单位、原参考范围与来源。', 50, INK)], '#FFF0DB')
                continue
            p.panel([(r['name'], 56, TEAL), (f"报告：{r['value']} {r['unit']} {text(r.get('flag'))}", 50, INK), (f"原参考范围：{r['reference']}；检验日期：{r['test_date']}", 38, INK), (m['plain'], 50, INK), (m['context'], 50, INK), (f"下一步：带原报告咨询医生。 来源：{r['source_id']}", 38, TEAL)])
        # Generic, low-dependency reminders do not override user restrictions.
        p.panel([('日常记住这两件事', 52, TEAL), ('规律进餐、作息；复诊带上旧报告与正在用的药。', 50, INK), ('饮食、饮水、活动以医生对您的具体安排为准。', 50, INK)])
        p.save(output, '体检指标大白话卡')
    if data['medications']:
        subtitle = '待确认草稿：有药物未核实，未形成完整个人服药方案。' if pending else '根据提供的个人用法整理；本工具不审核处方真实性或适宜性。'
        subtitle += ' 方案日期：' + (text(data.get('plan_date')) or '待确认')
        p = Pages('每日用药时刻表', data, font, subtitle)
        for slot in SLOTS:
            for med in ready:
                for event in med['events']:
                    if event['slot'] != slot:
                        continue
                    p.panel([(event['slot']+' · '+event['timing'], 52, TEAL), (med['name'], 56, INK), (f"{med['form']} · {med['strength']}", 50, INK), (med['dose'], 64, INK), (f"依据：{med['source_id']}", 38, TEAL)])
        if not ready:
            p.panel([('尚未生成可执行服药安排', 56, TEAL), ('请带药盒、药袋与现行处方向医师或药师核对。', 50, INK)], '#FFF0DB')
        if pending:
            p.panel([('仍有待确认药物，见待确认清单。', 50, INK)], '#FFF0DB')
        p.panel([('医嘱有变化，请重新核对本表。', 50, TEAL), ('未列出的时段不代表可以停药或漏服。', 50, INK)])
        p.save(output, '每日用药时刻表')
        if pending:
            q = Pages('用药待确认清单', data, font, '此页不能作为服药依据。请咨询医师或药师。')
            for name, reason in pending:
                q.panel([(name, 56, TEAL), (reason, 50, INK)], '#FFF0DB')
            q.save(output, '用药待确认清单')
    if data['restrictions']:
        q = Pages('个人限制核对记录', data, font, '以下按用户提供的信息记录，不构成新的饮食或用药建议。')
        for item in data['restrictions']:
            q.panel([(item, 50, INK)])
        q.save(output, '个人限制核对记录')
    voice = ('您好，这份卡片把已有信息整理成了大字。体检箭头不能单独说明是什么病，复诊时请带上原报告和用药清单。'
             '药量和时间只按已经核实的个人医嘱；待确认的地方先问医生或药师。医嘱有变化，请重新核对卡片。'
             '规律吃饭，好好休息。这些内容不替代医生诊断和处方调整。')
    (output/'语音叮嘱稿.txt').write_text('【仅文稿，尚未生成音频；合成后须实测不超过60秒】\n'+voice+'\n', encoding='utf-8')
    record = '# 来源核对记录\n\n' + ('演示数据，不能用于服药。\n\n' if data['demo'] else '')
    for category in ['reports', 'medications']:
        for item in data[category]:
            record += f"- {text(item.get('name'))}｜{text(item.get('source_id'))}｜原文：{text(item.get('source_quote'))}\n"
    record += '\n## 指标知识来源\n\n'
    used = {metrics[r['metric_id']]['source'] for r in data['reports'] if r.get('metric_id') in metrics}
    for s in kb['sources']:
        if s['id'] in used:
            record += f"- [{s['publisher']}：{s['title']}]({s['url']})\n"
    (output/'来源核对记录.md').write_text(record, encoding='utf-8')


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--input', type=Path)
    a.add_argument('--output', required=True, type=Path)
    a.add_argument('--font', required=True, help='本机可用的中文 TTF/OTF/TTC 字体')
    a.add_argument('--template', action='store_true')
    args = a.parse_args()
    if bool(args.input) == bool(args.template):
        a.error('--input 与 --template 必须且只能选择一个')
    if not Path(args.font).is_file():
        a.error('找不到字体，请提供可用中文字体的路径')
    # Validate before creating artifacts: urgent inputs must not emit routine cards.
    data = None
    if args.input:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        validate(data)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.template:
        template(args.output, args.font)
    else:
        render(data, args.output, args.font)
    print(f'已生成：{args.output.resolve()}')


if __name__ == '__main__':
    main()
