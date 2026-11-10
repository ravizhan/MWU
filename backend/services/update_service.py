"""更新检查：把 MirrorChyan 与 GitHub 的结果归一为 UpdatePlan。

渠道只负责找到目标版本和下载地址；装什么由包内容决定（见 updater）。
GitHub 发布约定（deploy/install.yml 生成）：
- 完整包 ``<名称>-<os>-<arch>-<tag>.7z``：MWU 本体 + 资源；
- 资源包 ``<名称>-resource-<os>.<arch>-<tag>.7z``：只含资源文件与安装清单。平台段用 ``.``
  连接，是为了不被按 ``<os>-<arch>`` 子串选包的旧版客户端误当作完整包；
- ``mwu-release.json``：``{"version", "mwu_version"}``，本次发布所用的 MWU 版本。
发布所用 MWU 版本与本地安装清单一致时只下资源包，否则（含无清单的源码运行或旧安装）下完整包。
"""

import platform
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from backend.core.install_manifest import InstallManifest
from backend.models.settings import SettingsModel
from backend.models.update import UpdatePlan

MIRRORCHYAN_API_BASES = [
    "https://mirrorchyan.com/api/resources",
    "https://mirrorchyan.net/api/resources",
]
RELEASE_INFO_ASSET = "mwu-release.json"


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


def check_update(
    *,
    current_version: str,
    mirrorchyan_rid: str | None,
    github_url: str | None,
    settings: SettingsModel,
    manifest: InstallManifest | None,
    log: Callable[[str], None],
) -> UpdatePlan:
    """MirrorChyan 优先；它给出下载地址就直接用，否则按其版本号到 GitHub 取同一 tag 的包。"""
    proxy = settings.update.proxy.strip() or None
    repo = _github_repo(github_url) if github_url else None
    mirrorchyan_error: Exception | None = None

    if mirrorchyan_rid:
        try:
            data = _check_mirrorchyan(mirrorchyan_rid, current_version, settings, proxy)
        except RuntimeError as exc:
            # 配置了 MirrorChyan 时仍回退 GitHub，但失败原因必须可见
            log(f"MirrorChyan 更新检查失败，回退 GitHub: {exc}")
            mirrorchyan_error = exc
        else:
            latest_version = data.get("version_name", "")
            has_update = bool(latest_version) and latest_version != current_version
            release_notes = data.get("release_note", "")
            if not has_update or data.get("url"):
                return UpdatePlan(
                    current_version=current_version,
                    latest_version=latest_version,
                    is_update_available=has_update,
                    release_notes=release_notes,
                    download_source="mirrorchyan",
                    package_type=(
                        "incremental"
                        if data.get("update_type") == "incremental"
                        else "full"
                    ),
                    current_client_version=manifest.mwu_version if manifest else None,
                    download_url=data.get("url", ""),
                    file_hash=data.get("sha256", ""),
                    file_name=f"update-{latest_version}.7z",
                )
            if repo is None:
                raise RuntimeError(
                    "MirrorChyan 未返回下载地址（缺少 CDK），且未配置 GitHub"
                )
            release = _github_release(repo, latest_version, None, proxy)
            plan = _plan_from_github(release, current_version, manifest, proxy)
            if release_notes:
                plan.release_notes = release_notes
            return plan

    if repo is None:
        if mirrorchyan_error is not None:
            raise mirrorchyan_error
        raise RuntimeError("未配置更新源")
    release = _github_release(repo, None, settings.update.updateChannel, proxy)
    return _plan_from_github(release, current_version, manifest, proxy)


def _check_mirrorchyan(
    rid: str, current_version: str, settings: SettingsModel, proxy: str | None
) -> dict[str, Any]:
    plat, arch = get_platform_info()
    params = {
        "current_version": current_version,
        "user_agent": "MWU",
        "os": plat,
        "arch": arch,
        "channel": settings.update.updateChannel,
    }
    if settings.update.mirrorchyanCdk:
        params["cdk"] = settings.update.mirrorchyanCdk

    last_error: Exception | None = None
    for api_base in MIRRORCHYAN_API_BASES:
        try:
            resp = httpx.get(
                f"{api_base}/{rid}/latest", params=params, proxy=proxy, timeout=15
            )
            data = resp.json()
        except Exception as exc:
            last_error = exc
            continue
        if data.get("code") == 0:
            return data.get("data", {})
        last_error = RuntimeError(
            f"MirrorChyan 返回错误码 {data.get('code')}: {data.get('msg', '')}".strip()
        )

    raise RuntimeError(f"MirrorChyan 更新检查失败: {last_error}")


def _github_repo(github_url: str) -> str:
    parts = github_url.rstrip("/").split("/")
    if len(parts) < 5:
        raise RuntimeError(f"interface.github 不是仓库地址: {github_url}")
    return f"{parts[3]}/{parts[4]}"


def _github_release(
    repo: str, tag: str | None, channel: str | None, proxy: str | None
) -> dict[str, Any]:
    api = f"https://api.github.com/repos/{repo}/releases"
    if tag:
        url = f"{api}/tags/{tag}"
    elif channel == "beta":
        url = f"{api}?per_page=1"
    else:
        url = f"{api}/latest"
    resp = httpx.get(url, proxy=proxy, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        if not data:
            raise RuntimeError(f"GitHub 仓库 {repo} 没有发布")
        data = data[0]
    if not data.get("tag_name"):
        raise RuntimeError("GitHub Releases 响应缺少 tag_name")
    return data


def _plan_from_github(
    release: dict[str, Any],
    current_version: str,
    manifest: InstallManifest | None,
    proxy: str | None,
) -> UpdatePlan:
    tag = release["tag_name"]
    current_client_version = manifest.mwu_version if manifest else None
    if tag == current_version:
        return UpdatePlan(
            current_version=current_version,
            latest_version=tag,
            is_update_available=False,
            download_source="github",
            package_type="full",
            current_client_version=current_client_version,
        )
    plat, arch = get_platform_info()
    assets = release.get("assets", [])
    full = _find_asset(assets, f"-{plat}-{arch}-{tag}.7z")
    if full is None:
        raise RuntimeError(f"未找到适合当前平台的更新包: {plat}-{arch}")
    resource = _find_asset(assets, f"-resource-{plat}.{arch}-{tag}.7z")
    info = next((a for a in assets if a["name"] == RELEASE_INFO_ASSET), None)
    client_version = (
        _download_json(info["browser_download_url"], proxy)["mwu_version"]
        if info
        else None
    )
    resource_only = (
        resource is not None
        and client_version is not None
        and client_version == current_client_version
    )
    asset = resource if resource_only and resource else full
    return UpdatePlan(
        current_version=current_version,
        latest_version=tag,
        is_update_available=True,
        release_notes=release.get("body") or "",
        download_source="github",
        package_type="resource" if resource_only else "full",
        client_version=client_version,
        current_client_version=current_client_version,
        download_url=asset["browser_download_url"],
        file_hash=asset.get("digest", "").removeprefix("sha256:").strip(),
        file_name=asset["name"],
    )


def _find_asset(assets: list[dict[str, Any]], suffix: str) -> dict[str, Any] | None:
    return next((a for a in assets if a["name"].endswith(suffix)), None)


def _download_json(url: str, proxy: str | None) -> dict[str, Any]:
    resp = httpx.get(url, proxy=proxy, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


async def download_file(url: str, dest: Path, proxy: str | None = None):
    async with (
        httpx.AsyncClient(follow_redirects=True, proxy=proxy) as client,
        client.stream("GET", url) as resp,
    ):
        resp.raise_for_status()
        with dest.open("wb") as f:
            async for chunk in resp.aiter_bytes():
                f.write(chunk)
