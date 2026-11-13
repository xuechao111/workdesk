# 教学数据工作台 · 主看板与副看板

本仓库保存两套独立的 Windows 源代码包。主、副看板分别保留当前功能与连接器，不共用配置、任务状态或运行数据。

| 代码包 | 地址 | Chrome 连接器 | 用途 |
| --- | --- | --- | --- |
| [main-dashboard](main-dashboard/) | http://127.0.0.1:8765 | 1.6.79 | 正式主看板，包含教学更新恢复保护及班型缺失修复 |
| [replica-dashboard](replica-dashboard/) | http://127.0.0.1:8766 | 1.6.77 | 独立副看板，保留副本采集、更新和隔离功能 |

在 GitHub 点击 **Code → Download ZIP** 后，分别使用上述两个目录。两个独立 ZIP 位于 [packages](packages/)，每个 ZIP 只包含对应代码包。

## 安装

1. Windows 10/11，准备 Python 3.11+、Node.js 22+、Chrome 和 Windows PowerShell。也可执行包内 `首次安装一键配置.bat` 检查安装依赖。
2. 在需要使用的包内执行 `启动组长工作台.bat` 或 `start-workbench.bat`。
3. Chrome 扩展管理页加载该包的 `chrome-extension` 目录；如同时使用主、副看板，各自加载对应连接器。
4. 登录自己的 CRM，在工作台配置自己的钉钉工作簿和连接信息、班级与课期 ID，再运行更新。
5. 群播图片功能需额外运行 `python -m pip install -r requirements.txt` 安装 Pillow。

首次运行没有业务快照，需完成配置与数据更新后查看看板。仓库不含任何正式工作簿配置、访问密钥、CRM 登录资料、学员数据或运行日志。

## 更新与开发

两个包的 `self-update.ps1` 均下载本仓库对应子目录，校验包身份、端口及 SHA256 清单后安装，保留本机配置和数据。请勿将主包代码覆盖到副包目录，反之亦然。

每包 `release-manifest.json` 包含源文件校验清单。`packages/SHA256SUMS.json` 校验两个 ZIP；变更源码后须重新生成清单和 ZIP。

本仓库是 2026-11-13 的源码快照；本次上传不切换本机正在运行的工作台目录。现有安装需使用新包或单独迁移更新入口。
