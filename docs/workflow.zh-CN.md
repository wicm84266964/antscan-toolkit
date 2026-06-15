# 工作流

1. 使用 `downloader` 发现并下载 AntScan STL 文件。
2. 导出下载器 manifest。
3. 把选中的 STL 行转换成 renderer batch manifest。
4. 使用 `renderer/run_batch.py` 把 STL 模型渲染为多视角 PNG 图片。
5. 使用 `renderer/run_batch.py --resume-run` 重试未完成或失败的 specimen。

下载器和渲染器有意保持分离。下载器维护 SQLite 状态和文件 manifest；渲染器消费
明确的 STL 路径，并把图片输出写入 run 目录。
