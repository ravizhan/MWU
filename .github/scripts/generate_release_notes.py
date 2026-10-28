import datetime
import json
import os
import sys
import uuid

import httpx


def get_latest_version(repo):
    """获取上一个版本的 tag name；失败时直接抛出，不构造无效的 compare 链接。"""
    resp = httpx.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=10)
    resp.raise_for_status()
    return resp.json()["tag_name"]


def read_streamed_content(response):
    content_parts = []

    for line in response.iter_lines():
        if not line:
            continue

        if isinstance(line, bytes):
            line = line.decode("utf-8")

        if not line.startswith("data:"):
            continue

        payload_text = line.removeprefix("data:").strip()
        if payload_text == "[DONE]":
            break

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue

        choices = payload.get("choices", [])
        if choices:
            content = choices[0].get("delta", {}).get("content")
            if content:
                content_parts.append(content)

    return "".join(content_parts)


def main():
    repo = "ravizhan/MWU"
    current_version = os.getenv("GITHUB_REF_NAME")
    api_key = os.getenv("API_KEY")
    if not current_version or not api_key:
        sys.exit("缺少 GITHUB_REF_NAME 或 API_KEY 环境变量")

    latest_version = get_latest_version(repo)

    patch_url = (
        f"https://github.com/{repo}/compare/{latest_version}...{current_version}.patch"
    )
    resp = httpx.get(patch_url, timeout=30)
    resp.raise_for_status()
    patch = resp.text

    if not patch.strip():
        sys.exit("未发现代码变更内容")

    prompt = """你是一个专业的软件更新日志分析助手。请阅读两个版本之间的代码变更补丁（git patch），并生成一份精炼的中文更新日志。

要求：
1. **严格分类**：只能从以下指定的 Section 中选择（若无相关变更则不显示该分类），且必须添加对应的 Emoji：
   - ✨ 新功能
   - 🐛 Bug修复
   - 📝 文档
   - 📦 依赖更新
   - ⚡ 性能优化
   - ♻️ 代码重构
   - 💄 样式
   - 👷 持续集成
   - 🔒 安全
2. **分类原则**：基于代码变更的实际影响进行归类，忽略 commit message 中可能不规范或错误的分类标识。
3. **内容精炼**：
   - 使用中文生成，每条记录必须精简为一句话概括。
   - 重点描述对用户或开发者有意义的变化，忽略单纯的版本号变更或自动生成文件的变动。
   - 尽量合并相似的变更项。
4. **输出格式**：各 Section 使用 ### 作为标题，下方使用无序列表（-）。

示例输出：
### ✨ 新功能
- 新增自动识别游戏窗口位置的功能
- 添加了对自定义配置文件的支持

### 🐛 Bug修复
- 修复了高分辨率屏幕下的点击偏移问题

### 📝 文档
- 更新了快速开始指南
"""

    data = {
        "model": "deepseek-v4-flash",
        "stream": True,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"以下是对比补丁内容：\n\n{patch}"},
        ],
    }

    with httpx.stream(
        "POST",
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=data,
        timeout=180,
    ) as resp:
        resp.raise_for_status()
        result = read_streamed_content(resp)

    if not result.strip():
        sys.exit("AI 未返回更新日志内容")

    date = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))
    ).strftime("%Y-%m-%d")
    release_notes = f"## 更新日志（{date}）\n\n{result}"

    delimiter = f"EOF_{uuid.uuid4().hex}"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"notes<<{delimiter}\n")
        f.write(release_notes)
        f.write(f"\n{delimiter}\n")
    print("已将更新日志写入 GITHUB_OUTPUT")


if __name__ == "__main__":
    main()
