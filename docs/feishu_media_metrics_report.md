# 飞书科普内容传播统计

`scripts/feishu_media_metrics_report.py` 会读取配置中的 CMHK 已发布消息及云文件，只发送一条富文本消息：一行“截至”时间及一张 1920×780 横版五列表格图片。表格字段为发布内容、发布时间、消息已读、文件打开人数、文件打开/已读。

- 所有人数和比例均由脚本确定性计算；`DeepSeek-V4-Pro` 只负责发送前的数据一致性校验，不改写统计值。
- 飞书消息已读接口只允许查询机器人七日内发送的消息，因此脚本会持续保存最后一次成功读数，过期后沿用最终缓存。
- 个人预览与群发使用不同目标，发送前会实时校验会话类型和名称；群发按日期及时段幂等，避免重复。
- 密钥只从项目现有的、Git 已忽略的 `ai_config.json` 读取。实际飞书目标配置位于同样被忽略的 `config/feishu_media_metrics.local.json`。
- 后台服务由 `scripts/install_feishu_media_metrics_daemon.sh` 安装。登录后自动启动，异常退出自动拉起；每天香港时间 10:00 和 17:00 执行，并补做当天十二小时内错过的时段。

常用检查：

```bash
python3 scripts/feishu_media_metrics_report.py --dry-run
python3 scripts/feishu_media_metrics_report.py --send-preview
launchctl print gui/$(id -u)/com.liaowang.cmhk-feishu-media-metrics
```
