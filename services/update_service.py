import platform

import httpx

from models.settings import SettingsModel

MIRRORCHYAN_API_BASES = [
    "https://mirrorchyan.com/api/resources",
    "https://mirrorchyan.net/api/resources",
]


def get_platform_info() -> tuple[str, str]:
    """获取当前平台和架构信息"""
    plat = "linux"
    match platform.system():
        case "Windows":
            plat = "win"
        case "Darwin":
            plat = "macos"
        case "Linux":
            plat = "linux"

    arch = "x86_64"
    machine = platform.machine().lower()
    match machine:
        case "x86_64" | "amd64":
            arch = "x86_64"
        case "arm" | "aarch64" | "arm64":
            arch = "aarch64"

    return plat, arch


def check_mirrorchyan_update(
    rid: str,
    current_version: str,
    cdk: str,
    settings: SettingsModel,
):
    """通过 Mirror酱 API 检查更新"""
    plat, arch = get_platform_info()
    params = {
        "current_version": current_version,
        "user_agent": "MWU",
        "os": plat,
        "arch": arch,
        "channel": settings.update.updateChannel,
    }
    if cdk:
        params["cdk"] = cdk

    proxy = settings.update.proxy or None

    last_error: Exception | None = None
    for api_base in MIRRORCHYAN_API_BASES:
        try:
            resp = httpx.get(
                f"{api_base}/{rid}/latest",
                params=params,
                proxy=proxy,
                timeout=15,
            )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 记录后继续尝试镜像地址
            last_error = exc
            continue
        if data.get("code") == 0:
            return data
        last_error = RuntimeError(
            f"MirrorChyan 返回错误码 {data.get('code')}: {data.get('msg', '')}".strip()
        )

    raise RuntimeError(f"MirrorChyan 更新检查失败: {last_error}")


def check_github_update(
    github_url: str,
    current_version: str,
    settings: SettingsModel,
):
    """通过 GitHub Releases API 检查更新"""
    repo_parts = github_url.split("/")
    if len(repo_parts) < 5:
        return None

    repo_name = repo_parts[3] + "/" + repo_parts[4]
    proxy = settings.update.proxy or None

    response = httpx.get(
        f"https://api.github.com/repos/{repo_name}/releases/latest",
        proxy=proxy,
        timeout=15,
    ).json()
    latest_version = response.get("tag_name")
    if not latest_version:
        raise RuntimeError("GitHub Releases 响应缺少 tag_name")

    plat, arch = get_platform_info()
    platform_arch = f"{plat}-{arch}"
    matching_assets = [
        asset for asset in response.get("assets", []) if platform_arch in asset["name"]
    ]

    if not matching_assets:
        return None

    selected_asset = next(
        (asset for asset in matching_assets if "mwu" in asset["name"].lower()),
        matching_assets[0],
    )

    download_url = selected_asset["browser_download_url"]
    file_hash = selected_asset.get("digest", "").replace("sha256:", "").strip()
    return {
        "latest_version": latest_version,
        "current_version": current_version,
        "is_update_available": latest_version != current_version,
        "release_notes": response.get("body", ""),
        "download_url": download_url,
        "file_hash": file_hash,
        "file_name": selected_asset["name"],
        "download_source": "github",
    }


async def download_file(url: str, dest: str, proxy: str | None = None):
    async with httpx.AsyncClient(follow_redirects=True, proxy=proxy) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)
