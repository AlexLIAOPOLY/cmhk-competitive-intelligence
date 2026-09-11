# 战略新闻配图修复（2026-09-11）

用户要求：推送的每条新闻都必须有相关图片；原文没图时由 Agent 按具体新闻关键词联网补图；广告图过滤写入 skill，反复测试，并更新所有账户的新闻。

## 实现

- 原文 Article/NewsArticle、正文及懒加载图片优先；og:image/twitter:image 仅为候选。
- 原文无合格图时，文本 Agent 生成具体主体/事件查询，检索网页及图片并打开出处页。支持真实相关资料图并显示“相关资料图”，新闻原文链接不变。
- 过滤广告/推荐区、其他文章链接、图标/横幅/占位图。Qwen 视觉模型实际看图，要求可见内容、来源依据、相关性分类及置信度，拒绝栏目封面、促销及不相关活动照片。
- 审核与上传使用同一图片字节，保存 SHA-256、图片/出处 URL、模型、技能版本、判定和关键词。旧缓存失效；失效接口、超时、截断等保留批次与检查点重试。
- 正式结构化新闻卡片构建前逐条检查合格图片；自动、人工、重试和分卡共用此关卡。已发送或发送结果不明的回执保留原请求与幂等键。
- 规则：`cmhk/skills/cmhk-strategic-news-push/SKILL.md`；代码：`cmhk/services/news_image_quality.py`、`news_delivery_assets.py`、`news_delivery_guard.py`。

## 验证

170 项专项测试通过：图片抽取、广告拒绝、关键词补图、资料图标注、缓存、发送失败恢复、多订阅者、早晚/人工去重、分卡与发送前关卡。

更广的临近检查有 6 项 `tests.test_subscription_admin` 既有失败；在 Git HEAD 原文件上复跑得到相同结果，涉及既有文案/CSS/版本常量，未列入本次通过范围。

真实网络复测已找到 PCCW Global/Harmony 同一签约照片、HKBN/博云官方签约图，以及紫荆文章正文的港深会面图；视觉审核明确拒绝“紫荆早茶”栏目封面。扩大复测又发现 UDN 推荐阅读图片混入正文，增加跨文章链接过滤后重新验收。全账户图片准备、消息更新、正式激活及最终回读仍在执行，最终结果另行补充。

私有证据目录：`var/subscriptions/image-quality-20260911/`。包含真实模型审核、失败/恢复、原始卡片备份、账户核对与后续消息回读；不将个人账户标识写入公开文档。

## 参考

- [Google Article 结构化数据](https://developers.google.com/search/docs/appearance/structured-data/article)：图片应与文章内容相关，图片属性不是内容审核结果。
- [Open Graph 协议](https://ogp.me/)：og:image 是分享对象的图片字段，不能据此假定属于某条新闻正文。
- [Qwen3-VL 官方模型说明](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Thinking)：支持图片输入和视觉理解；本实现使用实际图像输入。
- [DDGS 官方实现](https://github.com/deedy5/ddgs)：网页及图片检索能力。
