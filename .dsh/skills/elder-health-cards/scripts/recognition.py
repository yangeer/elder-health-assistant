"""Local OCR and conservative extraction for clear Chinese report and label photos."""
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import unicodedata

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
KNOWLEDGE = HERE.parent / 'references/knowledge.json'
NUMBER = r'[+-]?\d+(?:\.\d+)?'
VALUE = rf'[<>≤≥]?\s*{NUMBER}'
RANGE_VALUE = rf'(?:{NUMBER}\s*(?:-|–|—|~|～|至)\s*{NUMBER}|[<>≤≥]\s*{NUMBER})'
RANGE = rf'(?:{RANGE_VALUE}|\(\s*{RANGE_VALUE}\s*\))'
UNIT = r'(?:mmol\s*/\s*L|[μµu]mol\s*/\s*L|mg\s*/\s*dL|[mμµu]?g\s*/\s*L|[UI]\s*/\s*L|%|(?:[x×＊*]\s*)?10\s*\^?\s*(?:9|12)\s*/\s*L)'
FLAG = r'(?P<flag>[↑↓])?'
REPORT_PATTERNS = [
    re.compile(rf'^\s*(?P<value>{VALUE})\s*{FLAG}\s*(?P<unit>{UNIT})\s*(?P<range>{RANGE})\s*(?P<end>[↑↓])?\s*$', re.I),
    re.compile(rf'^\s*(?P<value>{VALUE})\s*{FLAG}\s+(?P<range>{RANGE})\s*(?P<unit>{UNIT})\s*(?P<end>[↑↓])?\s*$', re.I),
]
REPORT_ALIASES = {
    'Hb': ('Haemoglobin', 'Hemoglobin', '紅血球素', '血色素', '血紅蛋白'),
    'WBC': ('White Cell Count', 'White Blood Cell Count', '白血球計數', '白血球计数', '白細胞計數'),
    'PLT': ('Platelets', 'Platelet Count', '血小板計數'),
}
SUPERSCRIPTS = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹', '0123456789')
MEALS = {'早': 'breakfast', '午': 'lunch', '中': 'lunch', '晚': 'dinner'}
MEAL = re.compile(r'(早|午|中|晚)(?:餐|饭)(?:饭|餐)?(前|后|随餐|时)')
COUNT = r'(?:\d+(?:\.\d+)?|半|一|二|两|三|四|五|六|七|八|九|十)'
DAILY = re.compile(r'每日|每天|一天|一日')
UNSUPPORTED = re.compile(r'按需|必要时|遵医嘱|隔日|每隔|每周|每晚|不超过|最多|首次|首日|逐渐|递增|递减|或|(?:连续|连服|共)[\d一二两三四五六七八九十]+天|(?:每日|每天|一天|一日)(?:[2-9]\d*|\d{2,}|[二两三四五六七八九十])次')
NAME = re.compile(r'^(?:药品(?:通用)?名(?:称)?|通用名称|品名|药名)[:：](.{2,55})$')


def normalize(text):
    return unicodedata.normalize('NFKC', text)


def recognize(image_bytes, *, report_retry=False):
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format not in {'JPEG', 'PNG', 'WEBP'} or image.width * image.height > 24_000_000:
                raise ValueError('请选择不超过 2400 万像素的 JPG、PNG 或 WebP 照片。')
            gray = ImageOps.autocontrast(ImageOps.exif_transpose(image).convert('L'))
            gray.thumbnail((2600, 2600))
            if report_retry and max(gray.size) < 1700:
                scale = 1700 / max(gray.size)
                gray = gray.resize(tuple(round(side * scale) for side in gray.size), Image.Resampling.LANCZOS)
            payload = BytesIO()
            gray.save(payload, format='PNG')
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError('图片无法读取，请换一张清晰的 JPG、PNG 或 WebP。') from exc

    try:
        result = subprocess.run(
            ['tesseract', 'stdin', 'stdout', '-l', 'eng+chi_sim' if report_retry else 'chi_sim+eng',
             '--psm', '6'],
            input=payload.getvalue(), capture_output=True, timeout=20, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError('本地 OCR 未就绪，请安装 Tesseract 和简体中文语言包。') from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError('识别超时。可以裁剪到指标表或药袋用法区域再试。') from exc
    text = result.stdout.decode('utf-8', errors='replace').strip()
    if not text:
        raise ValueError('没有识别到文字，请拍清楚后重试。')
    return text


def read_metrics(text):
    metrics = json.loads(KNOWLEDGE.read_text(encoding='utf-8'))['metrics']
    aliases = {item['id']: {item['name'], item['id'], *item['aliases'],
                            *REPORT_ALIASES.get(item['id'], ())} for item in metrics}

    def label_pattern(label):
        return r'\s*'.join(re.escape(char) for char in label if not char.isspace())

    labels = sorted([(label, metric) for metric, names in aliases.items() for label in names],
                    key=lambda item: -len(item[0]))
    found = {}
    for raw in text.splitlines():
        # Preserve exponent syntax before NFKC converts Unicode superscripts to digits.
        line = normalize(re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹]+',
                                lambda match: '^' + match[0].translate(SUPERSCRIPTS), raw))
        for label, metric in labels:
            prefix = re.match(
                rf'^\s*(?:\d+[.、]?\s+)?{label_pattern(label)}(?![A-Za-z\u4e00-\u9fff])', line, re.I)
            if not prefix:
                continue
            tail = line[prefix.end():].lstrip(' :：')
            # A bilingual row may repeat the same metric name in a second column.
            # Discard only a recognized synonym for that metric.
            for alias in sorted(aliases[metric], key=len, reverse=True):
                secondary = re.match(rf'^\(?\s*{label_pattern(alias)}\s*\)?(?=\s|$)', tail, re.I)
                if secondary:
                    tail = tail[secondary.end():].lstrip(' :：')
                    break
            for pattern in REPORT_PATTERNS:
                match = pattern.match(tail)
                if match:
                    row = {key: match[key].strip() for key in ('value', 'unit', 'range')}
                    row.update(metric=metric, flag=match['flag'] or match['end'] or '', source=raw.strip())
                    if metric not in found:
                        found[metric] = row
                    elif found[metric] != row:
                        found[metric] = None  # Conflicting readings require manual review.
                    break
            break
    return sorted((row for row in found.values() if row), key=lambda row: not row['flag'])


DIET_FOOD = re.compile(r'酒|食物|饮食|饮品|果汁|葡萄柚|西柚|咖啡|牛奶|乳制品|茶|高脂|油腻|辛辣|高盐')
DIET_ACTION = re.compile(r'^(?:(?:用药|服药|服用本品|治疗)期间[，,：:]?)?(?:请勿|不得|禁止|避免|忌|不宜|不可|不要|不能)')
DIET_HEAD = re.compile(r'^[【\[]?(?:饮食禁忌|饮食注意事项|注意事项|禁忌)[】\]]?[:：]?')


def read_diet(lines):
    """Keep one complete explicit food warning from the label in its original wording."""
    accepted = []
    for line in lines:
        text = DIET_HEAD.sub('', line).strip('。')
        if (0 < len(text) <= 55 and DIET_ACTION.match(text) and DIET_FOOD.search(text)
                and not re.search(r'或|例外|详见|\.\.\.|…|[A-Za-z<>@]|[;；]|(?:及|与|和|或者|同时|以及|[，、：:])$', text)):
            accepted.append(text)
    unique = list(dict.fromkeys(accepted))
    return unique[0] if len(unique) == 1 else ''


def read_medication(text):
    lines = [re.sub(r'\s+', '', normalize(line)) for line in text.splitlines()]
    name = next((match[1] for line in lines if (match := NAME.match(line))), '')
    if not name:
        name = next((line for line in lines if re.fullmatch(
            r'[\u4e00-\u9fffA-Za-z]{3,24}(?:片|胶囊|颗粒|丸|口服液)', line)
            and not re.search(r'一次|一粒|每次|每片|规格|用量', line)), '')
    # Read only the usage section or individual lines with explicit usage clues.
    section = []
    in_usage = False
    for line in lines:
        if re.match(r'^[【\[]?(?:用法用量|用法|服用方法)', line):
            in_usage = True
        elif re.match(r'^[【\[]?(?:规格|注意事项|禁忌|不良反应|批准文号|有效期|贮藏|生产|成份|成分|仅用于)', line):
            in_usage = False
        if in_usage or (DAILY.search(line) and MEAL.search(line)):
            section.append(line)
    usage = '；'.join(section)[:600]
    meal_candidates = {(m[1], m[2]) for m in MEAL.finditer(usage)}
    explicit_doses = re.findall(rf'(?:每次|一次)(?:服用|服)?({COUNT}(?:片|粒|丸|袋|支|毫升|mL))', usage, re.I)
    direct_doses = re.findall(rf'(?:前|后|随餐|时)(?:\d+分钟)?(?:服用|服)?({COUNT}(?:片|粒|丸|袋|支|毫升|mL))', usage, re.I)
    doses = set(explicit_doses + direct_doses)
    offsets = set(re.findall(r'(?:前|后)(\d+)分钟', usage))
    unspecified_offsets = re.search(r'(?:前|后)(?:约|至少|提前|半小时|[一二两三四五六七八九十]+(?:小时|分钟)|[\d.]+小时)', usage)
    # More than one condition, duration or a range is intentionally left ambiguous.
    ambiguous = len(meal_candidates) != 1 or len(doses) != 1 or len(offsets) > 1
    ambiguous |= bool(unspecified_offsets or UNSUPPORTED.search(usage) or re.search(
        rf'(?:{COUNT})(?:-|~|至|或)(?:{COUNT})|(?:儿童|成人|老年人)\s*[:：]|(?:连服|疗程|共)\d+天',
        usage,
    ))
    if not name or not DAILY.search(usage) or ambiguous:
        return {'name': name, 'source': usage, 'complete': False}
    meal, relation = next(iter(meal_candidates))
    offset = int(next(iter(offsets))) if offsets else None
    if offset is not None and not 1 <= offset <= 180:
        return {'name': name, 'source': usage, 'complete': False}
    return {'name': name, 'source': usage[:160], 'complete': True,
            'meal': MEALS[meal], 'relation': {'前': 'before', '后': 'after', '随餐': 'at', '时': 'at'}[relation],
            'dose': next(iter(doses)), 'minutes': offset, 'diet': read_diet(lines)}
