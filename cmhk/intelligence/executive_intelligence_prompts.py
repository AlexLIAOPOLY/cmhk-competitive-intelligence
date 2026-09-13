"""Shared few-shot writing guidance, not acceptance rules or generated copy."""

import json

STRATEGIC_PROMPT_VERSION = "strategic_few_shot_v2"

STRATEGIC_WRITING_GUIDE = """
写给需要理解竞争格局的业务负责人：标题先说一个具体的经营判断，正文用关键事实解释这个判断为什么成立。
先看有哪些事实能放在一起解释，再选择盈利状态、客户经营、资本投入或业务结构等合适角度；不预设哪家领先。
选择能说明问题的公司和指标，讲清楚谁在赚什么钱、增长靠什么已知变化、投入节奏如何、竞争发生在哪个层面。
有趋势才谈变化，有直接证据才谈原因。只有规模数据时，就说明业务覆盖或资源体量所能支持的有限判断，不推断效率。
跨域分析可以对照不同经营模式，不必强行做金额排行榜。口径差异只在影响结论时简短交代；单指标分析可放入risk。
正文宜一至两句，少堆数字。语言自然，不需要套连接词、凑术语或写“持续关注、提升竞争力”等空话。
以下是虚构教学样例，只学习“事实如何支持判断”的写法。样例公司、数字、来源都不是本次证据，不能带入真实输出。
样例只示范文案字段；实际返回结构、实体和来源按本次任务要求。

样例一：从客户指标看收入来源
输入：甲运营商同一年度移动服务收入同比增长4%，移动客户数下降2%，移动ARPU增长6%。
输出：{"headline":"甲运营商增收靠存量客户变现","analysis":"甲运营商移动客户数下降2%，移动ARPU增长6%，移动服务收入仍增长4%，增收与单客收入提升同步，客户扩张并非本期增长主线。","risk":"现有指标尚不能区分提价与客户组合变化。"}

样例二：从两域趋势看资本投入节奏
输入：乙运营商2025年资本开支同比下降8%；丙云厂商2025年集团资本开支同比增长35%。
输出：{"title":"运营商收缩投入，云厂商加码建设","detail":"乙运营商2025年资本开支下降8%，丙云厂商同期集团资本开支增长35%，资本投入呈现收缩与扩张两种节奏；这组趋势并不说明两者投资回报的高低。"}

样例三：币种不同也能解释盈利状态
输入：丁香港运营商2025年净利润-2亿港元；戊云厂商2025年云业务营业利润30亿美元。
输出：{"title":"本地亏损修复与云业务盈利扩张并存","detail":"丁运营商2025年净利润-2亿港元，戊云业务同期营业利润30亿美元，本地业务面临盈利修复，云业务已有盈利支撑扩张；两项利润口径和币种不同，不能直接比较金额。"}

现在依据本次真实输入独立分析。不要照搬样例的结论；证据只支持有限判断时，具体说清这个判断即可。
"""


def discovery_few_shot_messages(*, batch: bool) -> list[dict[str, str]]:
    """Show complete response shapes separately from the real evidence message."""
    examples = [
        ("local", "mainland", "甲运营商FY2025净利润-2亿港元；乙运营商FY2025净利润30亿元。",
         "本地盈利修复与内地盈利积累并存",
         "甲运营商FY2025净利润-2亿港元，乙运营商同期净利润30亿元，甲仍有盈利修复压力，乙已有盈利积累；币种不同，不能直接比较金额。"),
        ("international", "cloud", "丙运营商FY2025集团资本开支10百万美元；丁云厂商FY2025集团资本开支100百万美元。",
         "丁云厂商承担更大的建设投入",
         "丙运营商FY2025集团资本开支10百万美元，丁云厂商同期100百万美元，丁承担了更大规模的建设投入，项目回报对其后续经营更为关键。"),
        ("mainland", "international", "乙运营商FY2025移动客户10亿户、净利润30亿元；丙运营商FY2025移动ARPU20美元/月、净利润-2百万美元。",
         "乙有盈利积累，丙仍有扭亏压力",
         "乙运营商FY2025净利润30亿元，丙运营商同期净利润-2百万美元，乙已形成盈利积累，丙仍有扭亏压力；币种不同，不能直接比较金额。"),
        ("cloud", "local", "丁云业务FY2025营业利润30百万美元；甲运营商FY2025净利润-2亿港元。",
         "云业务形成经营盈余，本地仍待扭亏",
         "丁云业务FY2025营业利润30百万美元，甲运营商同期净利润-2亿港元，云业务已形成经营盈余，甲仍有扭亏压力；利润口径和币种不同，不能直接比较金额。"),
    ]
    packets = []
    for source, target, facts, title, detail in examples:
        urls = [f"https://example.invalid/{source}", f"https://example.invalid/{target}"]
        packets.append((
            {"from": source, "to": target, "facts": facts, "source_urls": urls},
            {"from": source, "to": target, "title": title, "detail": detail,
             "kind": "AI综合研判", "source_urls": urls},
        ))
    demonstrations = [(dict(items=[p[0] for p in packets]), dict(items=[p[1] for p in packets]))] if batch else packets[:2]
    messages = []
    for facts, answer in demonstrations:
        messages.extend([
            {"role": "user", "content": "虚构教学样例，只示范写法与JSON结构，不属于真实证据：" + json.dumps(facts, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
        ])
    return messages
