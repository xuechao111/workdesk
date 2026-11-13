# 副看板代码包

独立 Windows 工作台，端口 **8766**，连接器 **1.6.77**。

包含教学数据、班级课程、异常学员、直播参播/回放、完课、续费、教学服务、本地展示与配置功能；外部写入范围由使用者的工作簿配置和账号权限决定。

首次使用：安装 Python 3.11+、Node.js 22+、Chrome；执行 `首次安装一键配置.bat`，加载本目录的 `chrome-extension`，执行 `启动组长工作台.bat`。在 `http://127.0.0.1:8766/` 配置自己的 CRM 和钉钉连接。群播图片功能需 `python -m pip install -r requirements.txt`。

代码只附空白/示例配置，首次更新前没有学员数据。主包使用独立根目录配置；副包干净安装时运行数据默认保存在 `instances/test`，兼容已有根目录配置。请勿混用两包的连接器和配置。

一键更新来自 `xuechao111/workdesk` 的 `replica-dashboard` 子目录，安装前验证 SHA256 和包身份。保留本机配置、CRM登录及运行数据。

测试：`python -m unittest discover -s tests -p "test_*.py"`；`node --test tests/*.test.mjs`。PowerShell 测试单独执行，其中部分需要 Windows 进程管理权限。
