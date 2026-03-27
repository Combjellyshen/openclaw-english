# HEARTBEAT.md

## 心跳唤醒规则

1. **检查待发交付物**：是否有已生成但未发送的精读 PDF 或词卡 PDF。若有，发送简短提醒。
2. **检查 pipeline 状态**：是否有中断或运行中的精读 pipeline run（`reading-log/runs/` 下 manifest 状态非 delivered）。若有，优先汇报 `current_stage`、已完成步骤、失败点；不要只说“还在处理”。
3. **运行中也要报进度**：如果 close-reading / daily-vocab / weekly-vocab 正在 running，每次 heartbeat 都返回一次精简进度：`任务类型 + 当前 stage + 已完成数/总数 + 是否卡在失败重试`。
4. **精读 autorun 自愈**：如果发现最新 close-reading run 处于 running/blocked 且还没到 `index_updated=done`，允许尝试一次：
   - `python3 scripts/close_reading_autorun.py --run-dir <run_dir>`
   但不要并发重复启动多个 autorun；先确认没有同类活跃进程。
5. **静默时段**：Asia/Shanghai 22:00–07:00 保持静默，只回复 `HEARTBEAT_OK`，除非有已生成未发送的交付物。
6. **无待办则安静**：没有待发结果或进展，直接回复 `HEARTBEAT_OK`。
7. **不主动修改配置**：心跳唤醒时不主动编辑 workspace 配置文件。
