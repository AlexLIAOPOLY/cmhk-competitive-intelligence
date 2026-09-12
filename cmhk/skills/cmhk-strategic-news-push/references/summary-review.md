# 独立简介审核少样本

以下均为虚构的格式与判定示例，不是本次新闻资料。实际只引用本次输入的编号。

<examples>
<example>
标题：企业在香港举办算力交流会
原文：交流会在甲酒店举行，展出了乙架构服务器及丙数据库。
简介：企业在甲酒店举办交流会，现场展出乙架构服务器及丙数据库。
summary_details[0]：现场展出乙架构服务器及丙数据库
source_quotes[0]：展出了乙架构服务器及丙数据库
输出：{"summary_detail_index":0,"source_quote_index":0,"reason":"具体展品是标题之外的新增事实，原文支持。","verdict":"accept"}
</example>
<example>
标题：某AI服务在香港开放
原媒体标题：某AI服务在香港开放 支援图片输入
正文摘录：用户可以通过独立应用及example.test网站使用。后文因订阅限制不可见。
简介：用户可通过独立应用及example.test网站使用该服务，也支援图片输入。
summary_details[0]：用户可通过独立应用及example.test网站使用该服务
source_quotes[0]：用户可以通过独立应用及example.test网站使用
输出：{"summary_detail_index":0,"source_quote_index":0,"reason":"入口为具体增量；图片输入另有原媒体标题支持，正文截断不否定该证据。","verdict":"accept"}
</example>
<example>
标题：公司推出企业服务
原文：首批服务对象为制造企业，提供库存管理和员工操作培训。
简介：公司推出企业服务，首批面向制造企业提供库存管理及操作培训。
summary_details[0]：首批面向制造企业提供库存管理及操作培训
source_quotes[0]：首批服务对象为制造企业，提供库存管理和员工操作培训
输出：{"summary_detail_index":0,"source_quote_index":0,"reason":"对象和功能为有依据的具体增量，不要求每句都有增量。","verdict":"accept"}
</example>
<example>
标题：券商上调评级至买入
原文：券商上调评级至买入，目标价为7.10港元。
简介：券商上调评级至买入，目标价为9.80港元。
输出：{"summary_detail_index":-1,"source_quote_index":-1,"reason":"简介目标价与来源冲突，须改为原文数值后重审。","verdict":"rewrite"}
</example>
<example>
标题：某国要求实施制裁
原网页标题：某国要求实施制裁
抓取正文：当地餐厅推出新菜式，游客品尝美食。
简介：某国要求实施制裁，造成十人受伤。
输出：{"summary_detail_index":-1,"source_quote_index":-1,"reason":"正文属于其他事件，伤亡数字没有依据。","verdict":"source_unavailable"}
</example>
<example>
comparison_title：公司更换董事及提名委员会成员
原媒体标题：公司公布董事变更及生效日
source_quotes[0]：甲先生将于9月15日起出任董事会主席，乙先生将于同日离任。
简介：甲先生将于9月15日起出任董事会主席，乙先生将于同日离任。
summary_details[0]：甲先生将于9月15日起出任董事会主席
输出：{"summary_detail_index":0,"source_quote_index":0,"reason":"推送标题没有具体人名和生效日，简介补充这两项原文事实，可以直接复述事实来源。","verdict":"accept"}
错误判断：简介复述source_quotes[0]已有内容，因此没有新增事实。
</example>
<example>
comparison_title：创新服务在香港推出
原媒体标题：创新服务在香港推出 首批支持两所大学
source_quotes[0]：创新服务在香港推出 首批支持两所大学
简介：服务首批支持两所大学。
summary_details[0]：服务首批支持两所大学
输出：{"summary_detail_index":0,"source_quote_index":0,"reason":"首批两所大学是推送标题之外的具体对象与数量，原媒体标题可作证据。","verdict":"accept"}
</example>
</examples>
