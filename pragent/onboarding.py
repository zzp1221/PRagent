"""First-run onboarding: probe credentials, persist them, subscribe repositories.

The wizard exists so a non-technical user can go from "double-clicked the
launcher" to "my pull requests are reviewed automatically" without editing
environment variables. Everything it writes lives in runtime_settings so it
survives restarts, and every read path masks secrets before they reach a
browser.
"""
import re
import secrets
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .github import GitHubClient
from .llm import JsonChatClient
from .network import inspect_public_base_url, webhook_endpoint
from .service import DEPLOYMENT_SCOPE, KEY_GITHUB_TOKEN, ReviewService


KEY_LLM_PROVIDER = "llm.provider"
KEY_LLM_BASE_URL = "llm.base_url"
KEY_LLM_MODEL = "llm.model"
KEY_LLM_API_KEY = "llm.api_key"
KEY_GITHUB_TOKEN_SOURCE = "github.token_source"
KEY_GITHUB_ACCOUNT = "github.account"
KEY_GITHUB_SCOPES = "github.scopes"
KEY_WEBHOOK_SECRET = "github.webhook_secret"
KEY_WATCH_INTERVAL = "watch.interval_seconds"

DEFAULT_WATCH_INTERVAL_SECONDS = 180
MIN_WATCH_INTERVAL_SECONDS = 30
GH_TIMEOUT_SECONDS = 15
LLM_PROBE_TIMEOUT_SECONDS = 30
_REPO_SCOPES = {"repo", "public_repo", "admin:repo_hook", "read:repo_hook"}
_ACCOUNT_PATTERN = re.compile(r"account\s+([A-Za-z0-9_.-]+)")
_SCOPE_PATTERN = re.compile(r"Token scopes:\s*(.+)")


def mask_secret(value: str) -> str:
    """Show just enough of a secret to recognise it, never enough to use it."""
    if not value:
        return ""
    if len(value) <= 6:
        return "****"
    return value[:4] + "****"


def _run_gh(args: List[str], timeout: int = GH_TIMEOUT_SECONDS):
    """Run a GitHub CLI command capturing output as UTF-8.

    The CLI prints box drawing and check mark characters, so the platform
    default (cp936 on a Chinese Windows install) cannot decode it.
    """
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )


def probe_github_cli() -> Dict[str, Any]:
    """Detect a local GitHub CLI login.

    The returned dict carries the raw token for the caller to persist, but the
    HTTP layer must project only the safe fields out of it. Detection failure is
    a normal result, not an error: the wizard falls back to a pasted token.
    """
    report: Dict[str, Any] = {
        "found": False, "account": "", "scopes": [], "token": "",
        "token_masked": "", "reason": "", "missing_repo_scope": False,
    }
    binary = shutil.which("gh")
    if not binary:
        report["reason"] = "未检测到 GitHub CLI，请手动填写访问令牌"
        return report
    try:
        status = _run_gh([binary, "auth", "status"])
    except (OSError, subprocess.SubprocessError) as exc:
        report["reason"] = "调用 GitHub CLI 失败：%s" % exc
        return report
    output = (status.stdout or "") + (status.stderr or "")
    if status.returncode != 0 or "Logged in" not in output:
        first_line = next(
            (line.strip() for line in output.splitlines() if line.strip()), ""
        )
        report["reason"] = (
            "GitHub CLI 未登录：%s" % first_line if first_line
            else "GitHub CLI 未登录，请先执行 gh auth login，或手动填写访问令牌"
        )
        return report
    account = ""
    match = _ACCOUNT_PATTERN.search(output)
    if match:
        account = match.group(1)
    scopes: List[str] = []
    scope_match = _SCOPE_PATTERN.search(output)
    if scope_match:
        scopes = [item.strip() for item in re.findall(r"'([^']+)'", scope_match.group(1))]
    try:
        token_result = _run_gh([binary, "auth", "token"])
    except (OSError, subprocess.SubprocessError) as exc:
        report["reason"] = "读取 GitHub CLI 令牌失败：%s" % exc
        return report
    token = (token_result.stdout or "").strip()
    if token_result.returncode != 0 or not token:
        report["reason"] = "无法读取 GitHub CLI 令牌，请手动填写访问令牌"
        return report
    report.update({
        "found": True,
        "account": account,
        "scopes": scopes,
        "token": token,
        "token_masked": mask_secret(token),
        "missing_repo_scope": bool(scopes) and not _REPO_SCOPES.intersection(scopes),
    })
    return report


class OnboardingService:
    def __init__(self, service: ReviewService):
        self.service = service
        self.store = service.store
        self.settings = service.settings

    # --- runtime setting helpers -------------------------------------------

    def _get(self, key: str, default: str = "") -> str:
        return self.store.get_runtime_setting(DEPLOYMENT_SCOPE, key) or default

    def _set(self, key: str, value: str) -> None:
        self.store.set_runtime_setting(DEPLOYMENT_SCOPE, key, value)

    def github_token(self) -> str:
        return self._get(KEY_GITHUB_TOKEN) or self.settings.github_token

    def webhook_secret(self) -> str:
        """Secret used to verify deliveries, persisted value first."""
        return self._get(KEY_WEBHOOK_SECRET) or self.settings.github_webhook_secret

    def watch_interval_seconds(self) -> int:
        """Effective poll interval: wizard value, then the configured default."""
        fallback = self.settings.watch_poll_interval_seconds or DEFAULT_WATCH_INTERVAL_SECONDS
        raw = self._get(KEY_WATCH_INTERVAL, "")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return fallback
        return value if value >= MIN_WATCH_INTERVAL_SECONDS else fallback

    # --- status -------------------------------------------------------------

    def status(self, tenant_id: str) -> Dict[str, Any]:
        stored = self.store.list_runtime_settings(DEPLOYMENT_SCOPE)
        base_url = stored.get(KEY_LLM_BASE_URL, "")
        model = stored.get(KEY_LLM_MODEL, "")
        api_key = stored.get(KEY_LLM_API_KEY, "")
        config = self.service.llm_config or {}
        token = self.github_token()
        public_ok, public_reason = inspect_public_base_url(self.settings.public_base_url)
        return {
            "llm": {
                "configured": bool(config),
                "provider": str(config.get("provider", "")),
                "model": model or str(self.settings.llm_model),
                "base_url": base_url or str(self.settings.llm_base_url),
                "api_key_masked": mask_secret(api_key),
                "from_wizard": bool(base_url and model and api_key),
            },
            "github": {
                "has_token": bool(token),
                "token_masked": mask_secret(token),
                "source": stored.get(KEY_GITHUB_TOKEN_SOURCE, ""),
                "account": stored.get(KEY_GITHUB_ACCOUNT, ""),
                "scopes": [
                    item for item in stored.get(KEY_GITHUB_SCOPES, "").split(",") if item
                ],
            },
            "webhook": {
                "available": public_ok,
                "reason": public_reason,
                "endpoint": webhook_endpoint(self.settings.public_base_url),
                "has_secret": bool(self.webhook_secret()),
            },
            "watches": self.store.list_watches(tenant_id),
            "watch_interval_seconds": self.watch_interval_seconds(),
        }

    # --- model configuration ------------------------------------------------

    def _verify_llm(self, base_url: str, model: str, api_key: str) -> None:
        """Spend one real call so "connected" means connected."""
        client = JsonChatClient(
            base_url, api_key, model, "custom", timeout=LLM_PROBE_TIMEOUT_SECONDS,
        )
        try:
            answer = client.complete_json(
                "onboarding",
                "You verify model credentials. Reply with a JSON object only.",
                'Reply exactly {"ok": true} as a JSON object with no other keys.',
                max_tokens=32,
            )
        except RuntimeError as exc:
            raise ValueError("模型连接失败：%s" % exc) from None
        if not isinstance(answer, dict):
            raise ValueError("模型返回内容不是 JSON 对象，请确认该地址兼容 OpenAI 接口")

    def save_llm(self, base_url: str, model: str, api_key: str) -> Dict[str, Any]:
        base_url = (base_url or "").strip().rstrip("/")
        model = (model or "").strip()
        api_key = (api_key or "").strip()
        missing = [
            label for label, value in
            (("URL", base_url), ("模型", model), ("API Key", api_key)) if not value
        ]
        if missing:
            raise ValueError("缺少必填项：%s" % "、".join(missing))
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        self._verify_llm(base_url, model, api_key)
        self._set(KEY_LLM_PROVIDER, "custom")
        self._set(KEY_LLM_BASE_URL, base_url)
        self._set(KEY_LLM_MODEL, model)
        self._set(KEY_LLM_API_KEY, api_key)
        return self.service.reload_llm()

    # --- github identity ----------------------------------------------------

    def save_github_token(self, token: str, source: str = "manual") -> Dict[str, Any]:
        value = (token or "").strip()
        if not value:
            raise ValueError("访问令牌不能为空")
        try:
            user = GitHubClient(value).get_authenticated_user()
        except RuntimeError as exc:
            raise ValueError("令牌校验失败：%s" % exc) from None
        login = str(user.get("login") or "")
        self._set(KEY_GITHUB_TOKEN, value)
        self._set(KEY_GITHUB_TOKEN_SOURCE, source or "manual")
        self._set(KEY_GITHUB_ACCOUNT, login)
        return {
            "account": login, "token_masked": mask_secret(value), "source": source,
        }

    def adopt_github_cli(self) -> Dict[str, Any]:
        """Persist the CLI token when detection succeeded, else explain why not."""
        report = probe_github_cli()
        if not report["found"]:
            raise ValueError(report["reason"] or "未检测到 GitHub CLI 登录")
        saved = self.save_github_token(report["token"], "gh-cli")
        saved["scopes"] = report["scopes"]
        self._set(KEY_GITHUB_SCOPES, ",".join(report["scopes"]))
        saved["missing_repo_scope"] = report["missing_repo_scope"]
        return saved

    def list_repositories(self, limit: int = 100) -> List[Dict[str, Any]]:
        token = self.github_token()
        if not token:
            raise ValueError("尚未配置 GitHub 访问令牌")
        try:
            return GitHubClient(token).list_repositories(limit)
        except RuntimeError as exc:
            raise ValueError("读取仓库列表失败：%s" % exc) from None

    # --- watches ------------------------------------------------------------

    def save_watches(self, tenant_id: str, entries: Any) -> Dict[str, Any]:
        if not isinstance(entries, list):
            raise ValueError("watches 必须是数组")
        desired: Dict[str, Dict[str, Any]] = {}
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("每一条订阅都必须是对象")
            repository = str(item.get("repository") or "").strip()
            if not repository:
                raise ValueError("订阅缺少 repository 字段")
            mode = str(item.get("mode") or "poll")
            if mode not in {"poll", "webhook", "both"}:
                raise ValueError("不支持的订阅模式：%s" % mode)
            desired[repository] = {
                "mode": mode, "enabled": bool(item.get("enabled", True)),
            }
        existing = {row["repository"] for row in self.store.list_watches(tenant_id)}
        for repository, config in desired.items():
            self.store.upsert_watch(
                tenant_id, repository, config["mode"], config["enabled"],
            )
            # Subscription implies authorisation; the reverse is not true, so a
            # removed subscription keeps the grant for manual reviews.
            self.store.grant_repository(tenant_id, repository)
        for repository in existing - set(desired):
            self.store.delete_watch(tenant_id, repository)
        return {"watches": self.store.list_watches(tenant_id)}

    # --- webhook helpers ----------------------------------------------------

    def rotate_webhook_secret(self) -> Dict[str, Any]:
        value = secrets.token_hex(32)
        self._set(KEY_WEBHOOK_SECRET, value)
        return {
            "secret": value,
            "endpoint": webhook_endpoint(self.settings.public_base_url),
            "content_type": "application/json",
            "events": ["Pull requests"],
        }

    def latest_delivery(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        return self.store.latest_webhook_delivery(tenant_id)
