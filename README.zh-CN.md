# AntScan Toolkit

AntScan Toolkit 是一个面向 AntScan 数据集处理的小型开源工具集：

- `downloader/`：增量发现和下载 AntScan STL 文件，也提供显式的 TIF
  体数据发现/下载命令。
- `renderer/`：用 Blender 后台模式把 STL 表面模型批量渲染成多视角 2D
  PNG 图片。
- `skills/`：给 Codex 使用的 skill 合约，说明智能体应该如何调用这两个工具，
  而不是重新实现流程。

这个项目的默认策略偏保守：下载器默认低并发，渲染器默认单个 Blender 任务顺序
处理，并支持对失败/未完成 specimen 做续跑重试。

## 目录结构

```text
antscan-toolkit/
  downloader/                # Python 包：发现、下载、SQLite 状态、导出
  renderer/                  # Blender STL 到 PNG 批量渲染器
  renderer/manifests/        # 脱敏后的示例 batch manifest
  skills/                    # Codex skill 入口
  docs/                      # 端到端工作流说明
```

## 环境要求

- Python 3.11+
- 真实 STL 渲染需要 Blender
- 真实发现/下载需要能访问公开 AntScan 网站

下载器测试使用 mock HTTP，不需要真实联网。渲染器单元测试默认使用 fake
renderer；真实 Blender smoke test 需要显式设置 `BLENDER_EXE`。

## 下载器快速开始

```powershell
cd downloader
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e .
python -m antscan_downloader.cli init-config --config config.toml
python -m antscan_downloader.cli run-once --config config.toml --limit 20
```

长期定时收集建议使用：

```powershell
python -m antscan_downloader.cli run-scheduled --config config.toml --resume-limit 10 --limit 100
```

它会执行 pending 恢复、发现、新 STL 下载和导出。失败项不会自动重试；需要人工
恢复失败项时，再显式运行 `retry-failed`。

TIF 体数据命令是独立入口：

```powershell
python -m antscan_downloader.cli discover-tif --config config.toml --limit 100
python -m antscan_downloader.cli download-new-tif --config config.toml --limit 100
```

## 渲染器快速开始

先安装 Blender，然后基于下面的示例创建 batch manifest：

```text
renderer/manifests/batch.example.json
```

运行一批 STL 导图：

```powershell
cd renderer
python .\run_batch.py --manifest .\manifests\batch.example.json --blender-exe "C:\Program Files\Blender Foundation\Blender\blender.exe"
```

对已有 run 目录重试未完成或失败项：

```powershell
python .\run_batch.py --resume-run .\runs\<run_id> --blender-exe "C:\Program Files\Blender Foundation\Blender\blender.exe"
```

渲染器会在 manifest 的 `output_root` 下写出每个 specimen 的多视角 PNG 和批次
汇总 CSV。

## 测试

下载器：

```powershell
cd downloader
python -m pip install -e .
python -m pytest tests -q
```

渲染器：

```powershell
cd renderer
python -m pytest tests -q
```

如果已经安装 Blender，可以显式运行真实 smoke test：

```powershell
$env:BLENDER_EXE = "C:\Program Files\Blender Foundation\Blender\blender.exe"
python -m pytest tests\test_blender_smoke.py -q
```

## 数据和使用边界

本仓库不包含 AntScan 原始数据、已下载 mesh、渲染图片、SQLite 状态库或实际运行
manifest。使用者需要自行确认 AntScan 数据集条款，并保持低影响、礼貌的下载设置。

## 许可证

MIT。
