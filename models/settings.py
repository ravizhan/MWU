import re
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from models.device_address import DeviceType
from models.scheduler import TaskOptionValue


def _normalize_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


_GITHUB_SSH_REPO_REGEX = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    re.IGNORECASE,
)


def _parse_github_repo(url: str) -> tuple[str, str] | None:
    """Parse common GitHub repo URL formats.

    Returns (repo_url, owner) when the URL looks like a GitHub repository.
    """

    url = _normalize_str(url)
    if not url:
        return None

    match = _GITHUB_SSH_REPO_REGEX.match(url)
    if match:
        owner = match.group("owner")
        repo = match.group("repo")
        return f"https://github.com/{owner}/{repo}", owner

    lower_url = url.lower()
    if lower_url.startswith(("github.com/", "www.github.com/")):
        url = f"https://{url}"

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    netloc = parsed.netloc.lower()
    if netloc not in {"github.com", "www.github.com"}:
        return None

    parts = [part for part in (parsed.path or "").split("/") if part]
    if len(parts) < 2:
        return None

    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    repo_url = f"https://github.com/{owner}/{repo}"
    return repo_url, owner


class Update(BaseModel):
    autoUpdate: bool = True
    updateChannel: Literal["stable", "beta"] = "stable"
    proxy: str = ""
    mirrorchyanCdk: str = ""


class Notification(BaseModel):
    systemNotification: bool = False
    browserNotification: bool = False
    externalNotification: bool = False
    webhook: str = ""
    contentType: Literal["application/json", "application/x-www-form-urlencoded"] = (
        "application/json"
    )
    headers: str = ""
    body: str = ""
    username: str = ""
    password: str = ""
    method: Literal["POST", "GET"] = "POST"
    notifyOnComplete: bool = True
    notifyOnError: bool = True


class UI(BaseModel):
    darkMode: bool | str | None = "auto"
    language: Literal["zh-CN", "en-US"] = "zh-CN"


class Runtime(BaseModel):
    timeout: int = Field(default=300, ge=60, le=3600)
    reminderInterval: int = Field(default=30, ge=5, le=120)
    autoRetry: bool = True
    maxRetryCount: int = Field(default=3, ge=1, le=10)
    retryInterval: int = Field(default=5, ge=1)


class About(BaseModel):
    version: str = ""
    author: str = ""
    github: str = ""
    license: str = ""
    description: str = ""
    contact: str = ""
    issueUrl: str = ""


class PanelLastConnectedDevice(BaseModel):
    type: DeviceType
    controller_name: str = ""
    fingerprint: str = ""
    adb_path: str = ""
    address: str = ""
    class_name: str = ""
    window_name: str = ""
    hWnd: int = 0
    gamepad_type: int = 0
    uuid: str = ""


class CustomDevice(BaseModel):
    """Persisted custom device address record.

    Stored in panel.customDevices within settings.json and merged with
    scan results at read time via DeviceService.
    """

    controller_name: str
    type: DeviceType
    address: str


class Panel(BaseModel):
    lastResource: str = ""
    lastConnectedDevice: PanelLastConnectedDevice | None = None
    recentDevices: list[PanelLastConnectedDevice] | None = None
    customDevices: list[CustomDevice] = []

    @field_validator("recentDevices")
    @classmethod
    def truncate_recent_devices(
        cls, v: list[PanelLastConnectedDevice] | None
    ) -> list[PanelLastConnectedDevice] | None:
        if v is not None and len(v) > 5:
            return v[:5]
        return v


class TelemetryConsent(BaseModel):
    """Persisted user consent for the currently configured telemetry target."""

    consent: Literal["unknown", "granted", "denied"] = "unknown"
    configId: str = ""
    failureAttachments: bool = False


class SettingsModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def inject_about_from_interface(cls, data: Any, info: ValidationInfo):
        if not isinstance(data, dict):
            return data

        context = info.context if isinstance(info.context, dict) else {}
        interface = context.get("interface")
        if interface is None:
            return data

        about_raw = data.get("about")
        about: dict[str, Any]
        if isinstance(about_raw, dict):
            about = dict(about_raw)
        else:
            about = {}

        updated = dict(data)
        updated["about"] = about

        interface_github = _normalize_str(getattr(interface, "github", ""))
        interface_version = _normalize_str(getattr(interface, "version", ""))
        interface_license = _normalize_str(getattr(interface, "license", ""))
        interface_contact = _normalize_str(getattr(interface, "contact", ""))
        interface_description = _normalize_str(getattr(interface, "description", ""))

        if interface_version:
            about["version"] = interface_version
        if interface_license:
            about["license"] = interface_license
        if interface_contact:
            about["contact"] = interface_contact
        if interface_description:
            about["description"] = interface_description

        if interface_github:
            parsed = _parse_github_repo(interface_github)
            if parsed is not None:
                repo_url, owner = parsed
                about["github"] = repo_url
                about["author"] = owner
                about["issueUrl"] = f"{repo_url}/issues"
            else:
                about["github"] = interface_github

        return updated

    update: Update = Update()
    notification: Notification = Notification()
    ui: UI = UI()
    runtime: Runtime = Runtime()
    about: About = About()
    panel: Panel = Panel()
    globalOptionValues: dict[str, TaskOptionValue] = Field(default_factory=dict)
    telemetry: TelemetryConsent = TelemetryConsent()
