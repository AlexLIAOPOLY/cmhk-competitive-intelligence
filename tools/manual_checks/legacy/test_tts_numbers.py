import re

def _integer_to_chinese(n: int) -> str:
    if n == 0:
        return "零"
    digits = "零一二三四五六七八九"
    
    def _section(num: int) -> str:
        if num == 0:
            return ""
        units = ["", "十", "百", "千"]
        parts = []
        zero_pending = False
        for pos in range(len(str(num)) - 1, -1, -1):
            divisor = 10 ** pos
            digit = num // divisor % 10
            if digit == 0:
                if parts and num % divisor:
                    zero_pending = True
                continue
            if zero_pending:
                parts.append("零")
                zero_pending = False
            if digit == 2 and pos == 3 and not parts:
                parts.append("两")
            elif digit == 1 and pos == 1 and not parts:
                pass
            else:
                parts.append(digits[digit])
            parts.append(units[pos])
        return "".join(parts)

    if n < 10_000:
        return _section(n)
    if n < 100_000_000:
        wan = n // 10_000
        rest = n % 10_000
        wan_str = "两" if wan == 2 else _section(wan)
        result = wan_str + "万"
        if rest == 0:
            return result
        if rest < 1000:
            result += "零"
        result += _section(rest)
        return result
    yi = n // 100_000_000
    rest = n % 100_000_000
    yi_str = "两" if yi == 2 else _section(yi)
    result = yi_str + "亿"
    if rest == 0:
        return result
    wan = rest // 10_000
    remainder = rest % 10_000
    if wan:
        if rest < 10_000_000:
            result += "零"
        wan_str = "两" if wan == 2 else _section(wan)
        result += wan_str + "万"
    if remainder:
        if rest % 10_000 < 1000:
            result += "零"
        result += _section(remainder)
    return result

def _percentage_number_to_chinese(value: str) -> str:
    sign = ""
    number = value.replace(",", "")
    if number.startswith(("+", "-")):
        sign = "正" if number[0] == "+" else "负"
        number = number[1:]
    integer_text, dot, decimal_text = number.partition(".")
    integer = int(integer_text or "0")
    integer_spoken = _integer_to_chinese(integer)
    digits = "零一二三四五六七八九"
    if dot:
        return f"{sign}{integer_spoken}点{''.join(digits[int(char)] for char in decimal_text)}"
    return f"{sign}{integer_spoken}"

def prepare_tts_text(value: str) -> str:
    text = re.sub(r"[*#`]+", "", value)
    text = text.replace("：", "，").replace("；", "。").replace("、", "，")
    
    text = re.sub(r"(\d{1,2}):(\d{2})", lambda m: f"{_integer_to_chinese(int(m.group(1)))}时{_integer_to_chinese(int(m.group(2)))}分", text)
    
    text = re.sub(
        r"(?<![\d.])([+-]?\d[\d,]*(?:\.\d+)?)\s*[%％]",
        lambda match: "百分之" + _percentage_number_to_chinese(match.group(1)),
        text,
    )
    
    def _year_replacer(match: re.Match) -> str:
        digits_map = "零一二三四五六七八九"
        return "".join(digits_map[int(d)] for d in match.group(1)) + "年"
    text = re.sub(r"(\d{4})年", _year_replacer, text)
    
    def _num_replacer(match: re.Match) -> str:
        num_str = match.group(1).replace(",", "")
        sign = ""
        if num_str.startswith(("+", "-")):
            sign = "正" if num_str[0] == "+" else "负"
            num_str = num_str[1:]
        
        if "." in num_str:
            integer_part, _, decimal_part = num_str.partition(".")
            int_spoken = _integer_to_chinese(int(integer_part)) if integer_part else "零"
            digits_map = "零一二三四五六七八九"
            dec_spoken = "".join(digits_map[int(d)] for d in decimal_part)
            return f"{sign}{int_spoken}点{dec_spoken}"
        else:
            return f"{sign}{_integer_to_chinese(int(num_str))}"

    text = re.sub(r"(?<![a-zA-Z0-9.\-_])([+-]?\d[\d,]*(?:\.\d+)?)(?![a-zA-Z0-9.\-_])", _num_replacer, text)
    
    text = re.sub(r"(?<=\d)\.(?=\d)", "点", text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

cases = [
    ('166家外资企业', '一百六十六家外资企业'),
    ('2025年第一季度', '二零二五年第一季度'),
    ('2024年', '二零二四年'),
    ('-5个百分点', '负五个百分点'),
    ('17:30发布', '十七时三十分发布'),
    ('**重点关注**政策动向', '重点关注政策动向'),
    ('## 行业资讯', '行业资讯'),
    ('第166名', '第一百六十六名'),
    ('约1.5亿用户', '约一点五亿用户'),
    ('IPv6覆盖率', 'IPv6覆盖率'),
    ('API接口', 'API接口'),
    ('CEO表示', 'CEO表示'),
    ('4G用户', '4G用户'),
    ('GB内存', 'GB内存'),
    ('50000家', '五万家'),
    ('1200万用户', '一千二百万用户'),
    ('3.5亿', '三点五亿'),
    ('增长8.3个百分点', '增长八点三个百分点'),
    ('6月10日', '六月十日'),
    ('一季度增长12.5%', '一季度增长百分之十二点五'),
    ('下降-4.2%', '下降百分之负四点二'),
]

for t, expected in cases:
    res = prepare_tts_text(t)
    if res != expected:
        print(f"FAIL: {t} -> {res} (Expected: {expected})")
    else:
        print(f"PASS: {t}")
