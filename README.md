<!-- markdownlint-disable MD033 MD041 -->

<p align="center">
  <img alt="LOGO" src="https://github.com/ravizhan/MWU/blob/main/logo.jpg" width="256" height="256" />
</p>

<div align="center">

# MWU

<!-- prettier-ignore-start -->
<!-- markdownlint-disable-next-line MD036 -->
_✨ 基于 **[Vue](https://github.com/vuejs/vue)** 和 **[FastAPI](https://github.com/fastapi/fastapi)**  的 **[MAAFramework](https://github.com/MaaXYZ/MaaFramework)** 通用 WebUI 项目 ✨_

**本项目尚未Production-Ready，欢迎测试并提供反馈**
<!-- prettier-ignore-end -->

  <img alt="license" src="https://img.shields.io/github/license/ravizhan/MWU">
  <img alt="Python" src="https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fravizhan%2FMWU%2Frefs%2Fheads%2Fmain%2Fpyproject.toml">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blueviolet">
  <img alt="commit" src="https://img.shields.io/github/commit-activity/m/ravizhan/MWU">
  <img alt="stars" src="https://img.shields.io/github/stars/ravizhan/MWU?style=social">
  <a href="https://deepwiki.com/ravizhan/MWU" target="_blank"><img alt="deepwiki" src="https://deepwiki.com/badge.svg"></a>
</div>

## ✨ 项目特点

- 🚀 **现代化技术栈** - 前后端分离架构，Vue 3 + FastAPI
- 🎨 **美观易用** - 基于 NaiveUI 组件库，界面简洁美观，支持深色模式自动切换
- 🔌 **魔改 Agent 实现** - 通过动态解析导入，无需额外 Python 环境
- 🔧 **高度可定制** - Python 代码简洁易修改，轻松实现各种定制需求
- 🔔 **系统通知** - 依托 Plyer 和浏览器API实现跨平台双渠道系统通知
- 🔄 **自动更新** - 支持 GitHub 自动下载更新
- 📱 **跨平台兼容** - Windows / Linux / macOS 全平台支持，基于浏览器提供统一的用户体验
- ⚡ **开箱即用** - 强兼官方模板，极致简单的步骤，快速接入
- 🎯 **弃繁从简** - 抛弃一切不必要的组件，提供尽可能小巧的体积

## 📋 环境需求

| 组件       | 要求                                                   |
| ---------- | :----------------------------------------------------- |
| **系统**   | Windows 10+、Linux、macOS                              |
| **资源**   | 基于 MaaFramework 的资源项目                           |
| **浏览器** | Chrome >=111；Edge >=111；Firefox >=114；Safari >=16.4 |

## 🚀 快速开始

> 请先阅读[MaaFW文档](https://maafw.com/docs/1.1-QuickStarted)，选择一种集成方案

如果您选择低代码或低代码+Agent方案，只需按照指引使用 [MaaFramework 项目模板](https://github.com/MaaXYZ/MaaPracticeBoilerplate) 创建项目，然后将其中的 `.github/workflows/install.yml` 替换为本项目的 [deploy/install.yaml](https://github.com/ravizhan/MWU/blob/main/deploy/install.yml) 即可。

如果您选择全代码开发集成，并且也想使用本项目的UI，请继续阅读 [项目架构与开发](https://github.com/ravizhan/MWU#%EF%B8%8F-%E9%A1%B9%E7%9B%AE%E6%9E%B6%E6%9E%84%E4%B8%8E%E5%BC%80%E5%8F%91)

### ⚙️ 配置清单

| 配置         | 默认值                  | 修改方法                                                     |
| ------------ | ----------------------- | ------------------------------------------------------------ |
| 压缩包名     | 仓库名-版本号-平台-架构 | [deploy/install.yml#L170](https://github.com/ravizhan/MWU/blob/baeec32ecc5db8ea6390ceb5575d73e2d2754ba6/deploy/install.yml#L170)，注意下方各处也要一并修改 |
| 可执行文件名 | MWU               | 暂不可修改                                                   |
| LOGO         |                         | 暂不可修改                                                   |

## 🏗️ 项目架构与开发

> **如果您需要更多的定制化功能或想为本项目做出贡献，请阅读以下部分**

### 📐 架构概览

项目采用前后端分离架构：

- **后端**：FastAPI (Python 3.12+)，提供 RESTful API 和 Server-Sent Events (SSE) 服务，运行在 `http://127.0.0.1:55666`
- **前端**：Vue 3 + NaiveUI + Vite + UnoCSS + Pinia，构建输出到 `page/` 目录
- **核心交互**：通过 SSE (Server-Sent Events) 实现任务状态和日志的实时推送

### 💻 开发指南

#### 🎨 前端开发

```bash
cd front
pnpm dev     # 开发服务器，自动代理 /api 到 localhost:55666
pnpm build   # 构建到 ../page 目录
pnpm lint    # 使用 oxlint 进行代码检查
pnpm format  # 使用 Prettier 格式化代码
```

#### 🔧 后端开发

```bash
uv run main.py  # 启动 FastAPI 服务
```

**依赖管理**：使用 `uv` 作为 Python 包管理器

#### 🧪 项目构建

``` bash
cd front && pnpm run build   # 前端构建
cd updater && go build       # 更新器构建
uv run python -m nuitka --standalone --assume-yes-for-downloads --user-package-configuration-file=nuitka-package.config.yml --output-dir=build --include-package=PIL --include-package=maa -o MWU main.py # 后端构建
```

#### 📁 项目文件目录

```
MWU/
├── main.py                      # FastAPI 应用入口，自动打开浏览器
├── maa_utils.py                 # MaaWorker 类，处理所有 MAA 框架交互
├── scheduler_manager.py         # 定时任务调度管理器
├── interface.json               # 项目接口配置（V2 协议）
│
├── config/                      # 配置文件目录
│   ├── settings.json            # 应用设置
│   ├── task_config.json         # 任务配置缓存
│   └── maa_option.json          # MAA 选项配置
│
├── models/                      # 数据模型目录
│   ├── api.py                   # API 请求/响应模型
│   ├── interface.py             # interface 数据模型（V2 协议）
│   ├── scheduler.py             # 定时任务相关模型
│   ├── settings.py              # 设置数据模型
│   └── task_config.py           # 任务配置模型
│
├── updater/                     # Go 更新器目录
│   ├── main.go                  # 更新器主程序
│   ├── go.mod                   # Go 模块定义
│   └── go.sum                   # Go 依赖校验
│
├── deploy/                      # 部署相关脚本
│   ├── install.yml              # GitHub Actions 安装脚本
│   ├── download_deps.py         # 依赖下载脚本
│   └── copy_resources.py        # 资源复制脚本
│
├── page/                        # 前端构建输出（FastAPI 静态服务）
│
├── resource/                    # MAA 资源文件目录
│
└── front/                       # 前端项目目录
    └── src/                     # 源代码目录
        ├── App.vue              # 根组件
        ├── main.ts              # 前端入口文件
        ├── components/          # Vue 组件
        │   ├── LeftPanel.vue    # 左侧面板组件
        │   ├── MediumPanel.vue  # 中间面板组件
        │   ├── OptionItem.vue   # 选项项组件
        │   └── RightPanel.vue   # 右侧面板组件
        ├── router/              # Vue Router 路由配置
        │   └── index.ts
        ├── script/              # API 和 WebSocket 工具函数
        │   ├── api.ts
        │   └── ws.ts
        ├── stores/              # Pinia 状态管理
        │   ├── index.ts         # Store 入口
        │   ├── interface.ts     # 接口状态管理
        │   ├── settings.ts      # 设置状态管理
        │   └── userConfig.ts    # 用户配置状态管理
        ├── types/               # TypeScript 类型定义
        │   ├── interface.ts     # interface 类型
        │   └── settings.ts      # 设置类型
        └── views/               # 页面视图组件
            ├── PanelView.vue    # 主面板视图
            └── SettingView.vue  # 设置视图
```

### 全代码开发集成

> 以下仅为推荐写法，对于全代码开发，选择权都在您的手上

#### 🔧 扩展 MaaWorker 类

`MaaWorker` 是处理 MAA 框架交互的核心类，您可以直接修改此类来添加自定义功能：

```python
# maa_utils.py

class MaaWorker:
    def __init__(self, queue: SimpleQueue, interface):
        # ... 原有初始化代码 ...
        self.send_log("MAA初始化成功")
        self.agent_process: subprocess.Popen | None = None
        self.load_agent()
        self.send_log("Agent加载完成")
        self.http_client = httpx.Client(timeout=30)

    # ========== 在此添加您的自定义方法 ==========

    def my_custom_task(self, param: str):
        """自定义任务示例"""
        self.send_log(f"开始执行自定义任务: {param}")

        # 获取当前屏幕截图
        image = self.controller.post_screencap().wait().get()

        # 执行 pipeline 任务
        result = self.tasker.post_task("MyCustomEntry").wait().get()

        # 处理结果
        if result.status.succeeded:
            self.send_log("任务执行成功")
        else:
            self.send_log("任务执行失败")

        return result.status.succeeded

    def detect_custom_objects(self) -> tuple[list, list]:
        """自定义识别示例 - 使用 YOLO 检测"""
        result = self.tasker.post_task("yolo_detect").wait().get()
        if result.status.failed:
            return [], []

        details = result.nodes[0].recognition.raw_detail["all"]
        boxes, labels = [], []
        for detail in details:
            boxes.append(detail["box"])
            labels.append(detail["label"])
        return boxes, labels

    # ========== 自定义方法结束 ==========
```

#### 📝 自定义 Action 和 Recognition

您可以在 `maa_utils.py` 中添加自定义的 Action 和 Recognition：

```python
# maa_utils.py

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition
from maa.define import TaskDetail
import numpy as np
from PIL import Image


# ========== 自定义 Recognition ==========
@resource.custom_recognition("MyCustomReco")
class MyCustomRecognition(CustomRecognition):
    def analyze(self, context, argv: CustomRecognition.AnalyzeArg):
        """自定义识别逻辑"""
        # 获取当前屏幕图像
        image = context.tasker.controller.post_screencap().wait().get()

        # 您的识别逻辑...
        # 返回识别结果
        return CustomRecognition.AnalyzeResult(
            box=(x, y, w, h),  # 识别框坐标
            detail="识别详情"
        )


# ========== 自定义 Action ==========
@resource.custom_action("MyCustomAction")
class MyCustomAction(CustomAction):
    def run(self, context, argv: CustomAction.RunArg):
        """自定义操作逻辑"""
        # 获取点击坐标
        box = argv.rec_box
        x, y = box[0] + box[2] // 2, box[1] + box[3] // 2

        # 执行点击
        context.tasker.controller.post_click(x, y).wait()

        return CustomAction.RunResult(success=True)
```

#### 🔌 集成自定义逻辑到任务流程

修改 `_run_process` 方法或添加新的任务入口，将您的自定义逻辑集成到任务流程中：

```python
# maa_utils.py

def _run_process(self, task_list):
    """任务执行主流程 - 可在此扩展"""
    self.send_log("任务开始")
    try:
        for task in task_list:
            if self.stop_flag:
                self.tasker.post_stop().wait()
                self.send_log("任务已终止")
                return

            # 原有任务执行
            if task == "启动游戏":
                self._startup_game()
            elif task == "我的自定义任务":
                # 调用您的自定义方法
                self.my_custom_task("参数")
            else:
                # 默认 pipeline 任务
                t = self.tasker.post_task(task)
                self.send_log("正在运行任务: " + task)
                while not t.done:
                    time.sleep(0.5)
                    if self.stop_flag:
                        self.tasker.post_stop().wait()
                        self.send_log("任务已终止")
                        return

    except Exception:
        traceback.print_exc()
        self.send_notification("错误", "任务出现异常")
        self.send_log("任务出现异常，请检查终端日志")
    finally:
        self.running = False
        self._task_thread = None
        self.send_log("所有任务完成")


def _startup_game(self):
    """封装启动游戏逻辑"""
    self.send_log("正在启动游戏...")
    self.tasker.post_task("StartUp").wait()
```

#### 📋 interface.json 配置

如果您想在WebUI展示自定义任务，您也需要在 `interface.json` 中添加您的自定义任务。

#### 💡 开发建议

1. **日志输出**：使用 `self.send_log(msg)` 输出日志，会自动推送到前端
2. **通知推送**：使用 `self.send_notification(title, message)` 发送系统通知和浏览器通知
3. **截图获取**：`self.controller.post_screencap().wait().get()` 获取当前屏幕
4. **任务状态**：通过 `self.running` 和 `self.stop_flag` 控制任务生命周期
6. **配置读取**：通过 `self.interface` 访问 `interface.json` 的配置

## 📄 开源许可

**MWU** 基于 **[AGPL-3.0 许可证](./LICENSE)** 开源。

## 🙏 致谢

### 📦 开源项目

- **[NaiveUI](https://github.com/tusen-ai/naive-ui)**\
  A Vue 3 Component Library. Fairly Complete. Theme Customizable. Uses TypeScript. Fast.
  
- **[FastAPI](https://github.com/fastapi/fastapi)**\
  FastAPI framework, high performance, easy to learn, fast to code, ready for production

- **[Nuitka](https://github.com/Nuitka/Nuitka)**\
  Nuitka is a Python compiler written in Python.

- **[Vite](https://github.com/vitejs/vite)**\
  Next Generation Frontend Tooling. It's fast!
  
- **[MaaFramework](https://github.com/MaaAssistantArknights/MaaFramework)**\
  基于图像识别的自动化黑盒测试框架。
  
- **[VueDraggablePlus](https://github.com/Alfred-Skyblue/vue-draggable-plus)**\
  支持 Vue2 和 Vue3 的拖拽组件
  
- **[Plyer](https://github.com/kivy/plyer)**\
  Plyer is a platform-independent Python wrapper for platform-dependent APIs
  
- **[marked](https://github.com/markedjs/marked)**\
  A markdown parser and compiler. Built for speed.
  
- **[tailwindcss](https://github.com/tailwindlabs/tailwindcss)**\
  A utility-first CSS framework for rapid UI development.

- **[Oxlint](https://oxc.rs/docs/guide/usage/linter.html)**\
  Oxlint is designed to catch erroneous or useless code without requiring any configurations by default.

### 👥 开发者

感谢所有为 **MWU** 做出贡献的开发者，以及 MAA 社区各位小伙伴提供的无私帮助与建议。

<a href="https://github.com/ravizhan/MWU/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ravizhan/MWU&max=1000" alt="Contributors to MWU"/>
</a>