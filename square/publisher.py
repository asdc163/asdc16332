"""幣安廣場 Creator OpenAPI 發文客戶端。

契約來自幣安官方開源的 square-post skill：
https://github.com/binance/binance-skills-hub/tree/main/skills/binance/square-post

  取得預簽名網址   POST {v2}/image/presignedUrl   {imageName} → {presignedUrl, fileTicket}
  上傳圖片         PUT  presignedUrl              raw bytes + Content-Type
  輪詢處理狀態     POST {v2}/image/imageStatus    {fileTicket} → {status, imageUrl, failedReason}
                                                  status 1=完成 2=失敗，最多輪詢 10 次、每次間隔 3 秒
  發布內容         POST {v1}/content/add          見 _content_body()

  標頭  X-Square-OpenAPI-Key / Content-Type: application/json / clienttype: binanceSkill
  成功  回應的 code == "000000"

金鑰只能發文，碰不到資產與交易。永遠從環境變數 BINANCE_SQUARE_OPENAPI_KEY 讀取，
不進版控、不寫進指令參數（指令參數會出現在 process list 與 shell history）。
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

V1 = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi"
V2 = "https://www.binance.com/bapi/composite/v2/public/pgc/openApi"

KEY_ENV = "BINANCE_SQUARE_OPENAPI_KEY"
KEY_FILE = Path.home() / ".config" / "binance-square" / "openapi-key"

SUCCESS = "000000"
IMAGE_POLL_ATTEMPTS = 10
IMAGE_POLL_INTERVAL = 3

# 官方文件列出的每日上限，我們一週 11 篇，遠低於此。
DAILY_POST_LIMIT = 100
DAILY_UPLOAD_LIMIT = 400

ERROR_HINTS = {
    "220003": "找不到這把金鑰。到廣場創作者中心確認金鑰還在，或重新建立一把。",
    "220004": "金鑰已過期，到創作者中心重新產生。",
    "220009": "今天的發文次數已達上限（100 篇／日）。",
    "220014": "今天的上傳次數已達上限（400 次／日）。",
}


class PublishError(RuntimeError):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code

    @property
    def is_retryable(self) -> bool:
        """業務錯誤重試沒有意義，而且重試發文有重複發布的風險。"""
        return self.code is None


class MissingKeyError(PublishError):
    pass


def load_key() -> str:
    """環境變數優先，其次是本機設定檔。找不到就明確報錯。"""
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise MissingKeyError(
        f"找不到廣場 OpenAPI 金鑰。設定環境變數 {KEY_ENV}，"
        f"或把金鑰存進 {KEY_FILE}。\n"
        "金鑰在 https://www.binance.com/square/creator-center/home 建立。"
    )


def redact(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) > 12 else "…"


@dataclass
class PublishResult:
    slug: str
    kind: str
    status: str  # published / skipped / failed
    content_id: str | None = None
    url: str | None = None
    error: str | None = None
    images: list[str] = field(default_factory=list)


class SquareClient:
    def __init__(self, api_key: str, timeout: int = 60, dry_run: bool = False):
        self.api_key = api_key
        self.timeout = timeout
        self.dry_run = dry_run

    # ------------------------------------------------------------ 低階呼叫

    def _headers(self) -> dict:
        return {
            "X-Square-OpenAPI-Key": self.api_key,
            "Content-Type": "application/json",
            "clienttype": "binanceSkill",
        }

    def _api(self, base: str, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(base + path, data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # 官方 skill 把 /content/add 的 504 視為已送出但沒拿到 id，
            # 不能當失敗重試，否則會重複發文。
            if exc.code == 504 and path == "/content/add":
                raise PublishError("__gateway_timeout__", code="504") from exc
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise PublishError(f"{path} HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise PublishError(f"{path} 連線失敗: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PublishError(f"{path} 回應不是 JSON: {raw[:400]}") from exc

        code = str(data.get("code", ""))
        if code != SUCCESS:
            message = data.get("message") or data.get("msg") or "(無錯誤訊息)"
            hint = ERROR_HINTS.get(code)
            text = f"{path} 回傳錯誤 [{code}]: {message}"
            if hint:
                text += f"\n  → {hint}"
            raise PublishError(text, code=code)
        return data.get("data") or {}

    # ------------------------------------------------------------ 圖片上傳

    def upload_image(self, path: Path) -> str:
        if self.dry_run:
            return f"dry-run://{path.name}"

        payload = self._api(V2, "/image/presignedUrl", {"imageName": path.name})
        presigned = payload.get("presignedUrl")
        ticket = payload.get("fileTicket")
        if not presigned or not ticket:
            raise PublishError(f"presignedUrl 回應缺少欄位: {payload}")

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        put = urllib.request.Request(
            presigned,
            data=path.read_bytes(),
            headers={"Content-Type": content_type},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(put, timeout=self.timeout) as resp:
                if resp.status not in (200, 204):
                    raise PublishError(f"圖片上傳失敗，HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            raise PublishError(f"圖片上傳失敗，HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise PublishError(f"圖片上傳連線失敗: {exc}") from exc

        for attempt in range(IMAGE_POLL_ATTEMPTS):
            status = self._api(V2, "/image/imageStatus", {"fileTicket": ticket})
            code = status.get("status")
            if code == 1:
                url = status.get("imageUrl")
                if not url:
                    raise PublishError(f"imageStatus 回報完成卻沒有 imageUrl: {status}")
                return url
            if code == 2:
                raise PublishError(f"圖片處理失敗: {status.get('failedReason')}")
            if attempt < IMAGE_POLL_ATTEMPTS - 1:
                time.sleep(IMAGE_POLL_INTERVAL)

        raise PublishError(f"圖片處理逾時（{IMAGE_POLL_ATTEMPTS} 次輪詢後仍未完成）")

    # ------------------------------------------------------------ 發布

    @staticmethod
    def _content_body(text: str, images: list[str], title: str | None) -> dict:
        """contentType 1＝短貼文（可帶最多 4 張圖），2＝長文（帶標題與單張封面）。"""
        if title:
            body = {"contentType": 2, "bodyTextOnly": text, "title": title}
            if images:
                body["cover"] = images[0]
            return body
        body = {"contentType": 1, "bodyTextOnly": text}
        if images:
            body["imageList"] = images[:4]
        return body

    def publish(self, text: str, images: list[str] | None = None, title: str | None = None) -> dict:
        body = self._content_body(text, images or [], title)
        if self.dry_run:
            return {"dryRun": True, "body": body}
        try:
            return self._api(V1, "/content/add", body)
        except PublishError as exc:
            if exc.code == "504":
                # 已送達但沒回 id。當成成功，絕對不重試。
                return {"publishStatus": "success_without_post_id"}
            raise
