# 安装说明

## 1. 运行前提

如果你只打算使用手动模式，只需要能正常运行 Codex。

如果你要使用自动模式，当前要求：

- Windows 桌面环境
- 可用的 PowerShell
- Node.js
- 至少一个受支持的 Chromium 浏览器
  - Edge
  - Chrome
  - Brave
  - Vivaldi
  - Arc

建议优先安装 Edge。原因很简单：如果一台电脑上一个可用的后台浏览器都没有，首次启动会直接提示先安装 Edge，再继续首次测试。

## 2. 从 GitHub 安装

如果目标机器已经装好了 Codex，可以直接用本机自带的 skill installer：

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo ningda-li/codex-midjourney-assistant `
  --path midjourney-assistant `
  --ref main
```

安装完成后，重启 Codex。

## 3. 手工安装

也可以直接把仓库里的 `midjourney-assistant` 目录复制到目标机器：

```text
%USERPROFILE%\.codex\skills\midjourney-assistant
```

复制完成后，重启 Codex。

## 4. 首次启动会发生什么

首次启动时，skill 会先进入首次引导，而不是直接冲进正式任务。

- 默认先尝试自动模式的后台链路
- 自动检查当前机器是否满足 Windows / PowerShell / Node.js / Chromium 浏览器前提
- 自动尝试拉起独立浏览器
- 如果独立浏览器还没有 Midjourney 登录态，只会要求用户在那套独立浏览器里登录一次
- 首次最小测试跑通后，才进入正式任务

如果用户明确要求手动模式，就不会启动网页自动操作，只输出需求整理、英文 prompt、参数建议和迭代建议。

## 5. 自动模式与手动模式

- 自动模式
  - skill 负责网页操作、提交、读回结果和继续迭代
- 手动模式
  - skill 只负责需求理解、解法规划、英文 prompt、参数建议和结果判断，用户自己去 Midjourney 里生成

两种模式共用同一套知识链，差别只在于谁来执行网页动作。

## 6. 发布建议

如果你要固定一个可安装版本，建议在 GitHub 上打 tag，再让别人按 tag 安装，例如 `--ref v0.3.0`。
