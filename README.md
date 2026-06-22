# 拾掇猫

帮你收拾文件的猫。一个文件整理工具箱，GUI + CLI 双模式，打包为单文件 exe，无需 Python 环境。

## 功能

| 编号 | 功能 | 说明 |
|------|------|------|
| 1 | 子文件夹提取 | 把嵌套文件拉到根目录，前缀拼接命名，清理空子目录 |
| 2 | GIF 统一重命名 | 三格式文件合并去重，统一编号 |
| 3 | (n) 标记去重 | 处理重复文件，哈希比对，一致删除，不一致改名 |
| 4 | 去重还原 | 从 dedup-map.json 还原功能 3 的改名操作 |
| 5 | 图片视频分离 | 递归提取嵌套视频到同级 文件夹名_视频 目录 |
| 6 | CBZ 打包 | 漫画图片文件夹打包为 .cbz，自动生成 ComicInfo.xml |
| 7 | 按作者分类 | 从文件名提取作者，散文件归入 [作者]合集 文件夹 |
| 8 | 操作回溯 | 扫描所有回溯文件，一键批量还原全部历史操作 |

## 特性

- 一步后悔药：每个功能执行后自动保存回溯文件，可一键还原
- 三种目标选择：Enter 批量全部 / 输入路径指定单个 / s 从列表勾选
- 碰撞安全：文件名冲突自动加序号后缀，不丢失任何文件
- SHA256 去重：哈希级比对，不靠文件名判断
- 双模式：CLI 命令行菜单 + GUI 图形界面
- 零依赖：exe 双击即用

## 文件结构

\`\`\`
nyako_core.py       核心逻辑模块（GUI 和 CLI 共用）
nyako-toolbox.py    CLI 入口（命令行菜单）
nyako-gui.py        GUI 入口（Tkinter 图形界面）
dist/
  ShiduoCat.exe     打包好的 exe
\`\`\`

## 使用方式

### GUI

双击 ShiduoCat.exe，左侧选中文件夹，点击右侧功能按钮。

### CLI

\`\`\`bash
python nyako-toolbox.py
\`\`\`

## 构建

\`\`\`bash
pip install pyinstaller
pyinstaller --onefile --windowed --name ShiduoCat --add-data "nyako_core.py;." nyako-gui.py
\`\`\`
