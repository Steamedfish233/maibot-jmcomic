"""
JMComic 助手 - MaiBot 第三方插件

功能：
1. /JM下载 <id>：下载 JM 作品，转换为 PDF，通过 NapCat 发送给用户。
2. JM验车 <id>：下载 JM 作品前几张图，通过 QQ 合并转发发送。
3. JM搜索 <关键词>：搜索 JM 作品并返回标题和车牌号。

插件只在自身目录内工作，不修改 MaiBot 主程序代码。
"""

from __future__ import annotations

import asyncio
import base64
import random
import re
import shutil
from pathlib import Path
from typing import Any, List, Optional, Tuple

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ActivationType, ToolParameterInfo, ToolParamType


# ── 配置模型 ──────────────────────────────────────────────


class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置结构版本号")


class JmConfig(PluginConfigBase):
    __ui_label__ = "JMComic 设置"
    __ui_icon__ = "book-open"
    __ui_order__ = 1

    option_file: str = Field(default="", description="JMComic option.yml 路径，留空则自动生成临时配置")
    temp_dir: str = Field(default="data/temp", description="临时工作目录，下载、PDF、验车图片会在发送后清理")
    max_search_results: int = Field(default=5, description="JM搜索最多返回数量")
    preview_image_count: int = Field(default=5, description="JM验车发送前几张图片")


class SendConfig(PluginConfigBase):
    __ui_label__ = "发送设置"
    __ui_icon__ = "send"
    __ui_order__ = 2

    notice_before_download: bool = Field(default=True, description="下载前是否提示正在处理")
    pdf_quality: int = Field(default=90, description="PDF 图片质量，范围 1-95")
    recall_notice_messages: bool = Field(default=True, description="是否自动撤回处理提示、完成提示和错误提示")
    recall_after_seconds: int = Field(default=60, description="提示消息自动撤回延迟秒数，0 表示不撤回")


class PrivacyConfig(PluginConfigBase):
    __ui_label__ = "隐私白名单"
    __ui_icon__ = "shield"
    __ui_order__ = 3

    allowed_users: List[str] = Field(default_factory=list, description="允许使用插件的用户 QQ 号白名单，例如 [\"123456\"]")
    allowed_groups: List[str] = Field(default_factory=list, description="允许使用插件的群聊 QQ 号白名单，例如 [\"123456\"]")


class JMPluginConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    jm: JmConfig = Field(default_factory=JmConfig)
    send: SendConfig = Field(default_factory=SendConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)


# ── 插件主类 ──────────────────────────────────────────────


class JMComicPlugin(MaiBotPlugin):
    config_model = JMPluginConfig

    async def on_load(self) -> None:
        self._plugin_dir = Path(__file__).resolve().parent
        self._data_dir = self._plugin_dir / "data"
        self._temp_dir = self._resolve_path(self.config.jm.temp_dir)
        self._prepare_dirs()
        self.ctx.logger.info("[JMComicPlugin] 插件已加载，临时目录: %s", self._temp_dir)

    async def on_unload(self) -> None:
        self.ctx.logger.info("[JMComicPlugin] 插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        self._temp_dir = self._resolve_path(self.config.jm.temp_dir)
        self._prepare_dirs()
        self.ctx.logger.info(
            "[JMComicPlugin] 配置已热重载: scope=%s, version=%s, temp_dir=%s, users=%d, groups=%d",
            scope,
            version,
            self._temp_dir,
            len(self.config.privacy.allowed_users),
            len(self.config.privacy.allowed_groups),
        )

    def _prepare_dirs(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self._plugin_dir / path
        return path.resolve()

    def _extract_text(self, kwargs: dict) -> str:
        message = kwargs.get("message", {})
        if isinstance(message, dict):
            return str(message.get("plain_text", "") or message.get("text", "") or message.get("raw_message", ""))
        return str(kwargs.get("plain_text", "") or kwargs.get("text", "") or kwargs.get("raw_message", ""))

    def _extract_album_id(self, text: str) -> Optional[str]:
        match = re.search(r"(?:JM)?\s*(\d{3,})", str(text), flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _target(self, group_id: str = "", user_id: str = "") -> Tuple[str, Any]:
        if group_id:
            return "group", int(group_id) if str(group_id).isdigit() else group_id
        if user_id:
            return "private", int(user_id) if str(user_id).isdigit() else user_id
        return "", ""

    def _normalize_id(self, value: Any) -> str:
        return str(value or "").strip()

    def _is_allowed(self, group_id: str = "", user_id: str = "") -> Tuple[bool, str]:
        allowed_users = {self._normalize_id(item) for item in self.config.privacy.allowed_users if self._normalize_id(item)}
        allowed_groups = {self._normalize_id(item) for item in self.config.privacy.allowed_groups if self._normalize_id(item)}
        current_user = self._normalize_id(user_id)
        current_group = self._normalize_id(group_id)

        if current_group:
            if current_group not in allowed_groups:
                return False, "当前群聊不在 JMComic 插件群聊白名单中，无法使用此功能。"
            if not current_user:
                return False, "当前会话缺少 QQ 用户信息，无法进行用户白名单校验。"
            if current_user not in allowed_users:
                return False, "当前用户不在 JMComic 插件用户白名单中，无法使用此功能。"
            return True, ""

        if current_user:
            if current_user not in allowed_users:
                return False, "当前用户不在 JMComic 插件用户白名单中，无法使用此功能。"
            return True, ""

        return False, "当前会话缺少 QQ 用户或群聊信息，无法进行白名单校验。"

    async def _check_permission_or_reply(self, stream_id: str, group_id: str = "", user_id: str = "") -> bool:
        allowed, reason = self._is_allowed(group_id, user_id)
        if not allowed:
            await self._send_recallable_text(reason, stream_id, group_id, user_id)
        return allowed

    def _safe_filename(self, value: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", str(value)).strip(" ._")
        return cleaned[:80] or "未命名"

    def _get_jm_module(self):
        try:
            import jmcomic  # type: ignore
        except ImportError as exc:
            raise RuntimeError("未安装 jmcomic。请在 MaiBot 运行环境中执行: pip install jmcomic -U") from exc
        return jmcomic

    def _get_option_file(self, album_temp_dir: Optional[Path] = None) -> Path:
        configured = self.config.jm.option_file.strip()
        if configured:
            option_path = Path(configured).expanduser()
            if not option_path.is_absolute():
                option_path = self._plugin_dir / option_path
            return option_path.resolve()

        option_path = self._data_dir / "jm_option.yml"
        base_dir = str(album_temp_dir or self._temp_dir).replace("\\", "/")
        option_path.write_text(
            "version: '2.1'\n"
            "dir_rule:\n"
            f"  base_dir: {base_dir}\n"
            "  rule: Bd_Aid_Pindex\n"
            "download:\n"
            "  image:\n"
            "    suffix: .jpg\n",
            encoding="utf-8",
        )
        return option_path

    def _create_option(self, album_temp_dir: Optional[Path] = None):
        jmcomic = self._get_jm_module()
        option_file = self._get_option_file(album_temp_dir)
        if not option_file.exists():
            raise RuntimeError(f"JMComic 配置文件不存在: {option_file}")
        return jmcomic.create_option_by_file(str(option_file))

    def _find_images(self, directory: Path) -> List[Path]:
        suffixes = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        return sorted(
            [path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in suffixes],
            key=lambda path: str(path),
        )

    def _download_album_to_temp_sync(self, album_id: str) -> Tuple[Path, str, List[Path]]:
        album_dir = self._temp_dir / f"JM{album_id}"
        if album_dir.exists():
            shutil.rmtree(album_dir, ignore_errors=True)
        album_dir.mkdir(parents=True, exist_ok=True)

        jmcomic = self._get_jm_module()
        option = self._create_option(album_dir)
        jmcomic.download_album(album_id, option)

        images = self._find_images(album_dir)
        if not images:
            raise RuntimeError(f"JM{album_id} 下载完成，但没有找到图片文件。")

        title = self._get_album_title_sync(album_id)
        return album_dir, title, images

    def _get_album_title_sync(self, album_id: str) -> str:
        try:
            option = self._create_option()
            client = option.new_jm_client()
            album = client.get_album_detail(album_id)
            return str(getattr(album, "title", f"JM{album_id}"))
        except Exception:
            return f"JM{album_id}"

    def _get_album_info_text_sync(self, album_id: str, fallback_title: str = "", page_count: int = 0) -> str:
        title = fallback_title or f"JM{album_id}"
        author = "未知"
        tags: List[str] = []
        try:
            option = self._create_option()
            client = option.new_jm_client()
            album = client.get_album_detail(album_id)
            title = str(getattr(album, "title", title) or title)
            author = str(getattr(album, "author", "未知") or "未知")
            raw_tags = getattr(album, "tags", []) or getattr(album, "tag_list", []) or []
            if isinstance(raw_tags, str):
                tags = [raw_tags]
            else:
                tags = [str(item) for item in raw_tags if str(item).strip()]
            page_count = int(getattr(album, "page_count", 0) or getattr(album, "page_count_real", 0) or page_count)
        except Exception:
            pass

        lines = [
            f"JM{album_id}",
            f"标题：{title}",
            f"作者：{author}",
        ]
        if page_count:
            lines.append(f"页数：{page_count}")
        if tags:
            lines.append("标签：" + "、".join(tags[:12]))
        return "\n".join(lines)

    def _random_album_id_sync(self) -> str:
        option = self._create_option()
        client = option.new_jm_client()
        for _ in range(12):
            album_id = str(random.randint(100000, 900000))
            try:
                client.get_album_detail(album_id)
                return album_id
            except Exception:
                continue
        raise RuntimeError("随机本子获取失败，请稍后重试。")

    def _encrypt_pdf_sync(self, source_path: Path, password: str) -> Path:
        encrypted_path = source_path.with_name(source_path.stem + "_加密.pdf")
        try:
            from pypdf import PdfReader, PdfWriter  # type: ignore

            reader = PdfReader(str(source_path))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.encrypt(user_password=str(password), owner_password=str(password), use_128bit=True)
            with encrypted_path.open("wb") as file:
                writer.write(file)
            source_path.unlink(missing_ok=True)
            return encrypted_path
        except ImportError as exc:
            source_path.unlink(missing_ok=True)
            raise RuntimeError("未安装 pypdf，无法加密 PDF。请执行: pip install pypdf -U") from exc
        except Exception:
            source_path.unlink(missing_ok=True)
            encrypted_path.unlink(missing_ok=True)
            raise

    def _convert_images_to_pdf_sync(self, album_id: str) -> Tuple[Path, Path]:
        try:
            from PIL import Image  # type: ignore
        except ImportError as exc:
            raise RuntimeError("未安装 Pillow，无法生成 PDF。请执行: pip install pillow -U") from exc

        album_dir, title, images = self._download_album_to_temp_sync(album_id)
        pdf_path = self._temp_dir / f"JM{album_id}_{self._safe_filename(title)}.pdf"
        if pdf_path.exists():
            pdf_path.unlink()

        converted = []
        for image_path in images:
            with Image.open(image_path) as image:
                if image.mode in ("RGBA", "P"):
                    image = image.convert("RGB")
                else:
                    image = image.copy().convert("RGB")
                converted.append(image)

        if not converted:
            raise RuntimeError(f"JM{album_id} 没有可转换为 PDF 的图片。")

        quality = max(1, min(int(self.config.send.pdf_quality), 95))
        first, rest = converted[0], converted[1:]
        first.save(pdf_path, "PDF", save_all=True, append_images=rest, quality=quality)
        for image in converted:
            image.close()
        encrypted_path = self._encrypt_pdf_sync(pdf_path, album_id)
        return encrypted_path, album_dir

    def _preview_images_sync(self, album_id: str) -> Tuple[Path, str, List[Path]]:
        album_dir, title, images = self._download_album_to_temp_sync(album_id)
        count = max(1, int(self.config.jm.preview_image_count))
        info_text = self._get_album_info_text_sync(album_id, title, len(images))
        return album_dir, info_text, images[:count]

    def _search_sync(self, keyword: str) -> List[dict]:
        option = self._create_option()
        client = option.new_jm_client()
        page = client.search_site(search_query=keyword)
        results = getattr(page, "content", []) or getattr(page, "data", []) or []
        if not results:
            return []

        items: List[dict] = []
        limit = max(1, int(self.config.jm.max_search_results))
        for item in results[:limit]:
            if isinstance(item, tuple) and len(item) >= 2:
                album_id = str(item[0])
                info = item[1] if isinstance(item[1], dict) else {}
                title = str(info.get("name") or info.get("title") or f"JM{album_id}")
            else:
                album_id = str(getattr(item, "album_id", getattr(item, "id", "")))
                title = str(getattr(item, "title", getattr(item, "name", str(item))))
            items.append({"album_id": album_id, "title": title, "cover_url": self._album_cover_url(album_id)})
        return items

    def _format_search_results(self, items: List[dict]) -> str:
        if not items:
            return "没有找到相关作品。"
        lines = [f"{index}. 《{item['title']}》 - JM{item['album_id']}" for index, item in enumerate(items, start=1)]
        return "搜索结果：\n" + "\n".join(lines)

    async def _run_blocking(self, func, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args))

    async def _send_text_via_api(self, text: str, stream_id: str, group_id: str = "", user_id: str = "") -> Optional[Any]:
        target_type, target_id = self._target(group_id, user_id)
        if not target_type:
            await self.ctx.send.text(text, stream_id)
            return None

        params = {
            "message_type": target_type,
            "message": [{"type": "text", "data": {"text": text}}],
        }
        if target_type == "group":
            params["group_id"] = target_id
        else:
            params["user_id"] = target_id

        try:
            result = await self.ctx.api.call("adapter.napcat.message.send_msg", version="1", params=params)
            if isinstance(result, dict):
                return result.get("message_id") or (result.get("data") or {}).get("message_id") or result.get("external_message_id")
        except Exception as exc:
            self.ctx.logger.error("[JMComicPlugin] send_msg 文本发送失败: %s", exc)
            await self.ctx.send.text(text, stream_id)
        return None

    async def _delete_message_later(self, message_id: Any, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
            await self.ctx.api.call("adapter.napcat.message.delete_msg", version="1", message_id=int(str(message_id).strip()))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.ctx.logger.debug("[JMComicPlugin] 自动撤回消息失败: %s", exc)

    async def _send_recallable_text(self, text: str, stream_id: str, group_id: str = "", user_id: str = "") -> None:
        message_id = await self._send_text_via_api(text, stream_id, group_id, user_id)
        seconds = int(self.config.send.recall_after_seconds)
        if self.config.send.recall_notice_messages and seconds > 0 and message_id:
            asyncio.create_task(self._delete_message_later(message_id, seconds))

    async def _send_pdf_file(self, pdf_path: Path, stream_id: str, group_id: str = "", user_id: str = "") -> None:
        target_type, target_id = self._target(group_id, user_id)
        if not target_type:
            await self._send_recallable_text("PDF 已生成，但当前会话缺少 QQ 目标，无法自动发送文件。", stream_id)
            return

        params = {"file": str(pdf_path), "name": pdf_path.name}
        if target_type == "group":
            params["group_id"] = target_id
            api_name = "adapter.napcat.file.upload_group_file"
        else:
            params["user_id"] = target_id
            api_name = "adapter.napcat.file.upload_private_file"

        await self.ctx.api.call(api_name, version="1", params=params)

    def _image_to_base64(self, image_path: Path) -> str:
        return base64.b64encode(image_path.read_bytes()).decode("ascii")

    def _album_cover_url(self, album_id: str) -> str:
        try:
            jmcomic = self._get_jm_module()
            jm_text = getattr(jmcomic, "JmcomicText", None)
            if jm_text is None:
                return ""
            return str(jm_text.get_album_cover_url(album_id, size="_3x4") or "")
        except Exception as exc:
            self.ctx.logger.debug("[JMComicPlugin] 获取 JM%s 首页图失败: %s", album_id, exc)
            return ""

    async def _get_bot_identity(self) -> Tuple[str, str]:
        try:
            result = await self.ctx.api.call("adapter.napcat.system.get_login_info", version="1", params={})
            data = result.get("data", result) if isinstance(result, dict) else {}
            user_id = str(data.get("user_id") or data.get("uin") or data.get("account") or "10000")
            nickname = str(data.get("nickname") or data.get("name") or "JMComic 助手")
            return nickname, user_id
        except Exception as exc:
            self.ctx.logger.warning("[JMComicPlugin] 获取机器人账号信息失败，使用默认合并转发身份: %s", exc)
            return "JMComic 助手", "10000"

    async def _send_forward_images(self, album_id: str, info_text: str, image_paths: List[Path], stream_id: str, group_id: str = "", user_id: str = "") -> None:
        target_type, target_id = self._target(group_id, user_id)
        if not target_type:
            await self.ctx.send.text(info_text, stream_id)
            for image_path in image_paths:
                await self.ctx.send.image(self._image_to_base64(image_path), stream_id)
            return

        bot_name, bot_uin = await self._get_bot_identity()
        nodes = [
            {
                "type": "node",
                "data": {
                    "name": bot_name,
                    "uin": bot_uin,
                    "content": [{"type": "text", "data": {"text": info_text}}],
                },
            }
        ]
        for image_path in image_paths:
            nodes.append(
                {
                    "type": "node",
                    "data": {
                        "name": bot_name,
                        "uin": bot_uin,
                        "content": [{"type": "image", "data": {"file": "base64://" + self._image_to_base64(image_path)}}],
                    },
                }
            )

        if target_type == "group":
            params = {"group_id": target_id, "messages": nodes}
            api_name = "adapter.napcat.message.send_group_forward_msg"
        else:
            params = {"user_id": target_id, "messages": nodes}
            api_name = "adapter.napcat.message.send_private_forward_msg"

        await self.ctx.api.call(api_name, version="1", params=params)

    async def _send_search_forward(self, keyword: str, items: List[dict], stream_id: str, group_id: str = "", user_id: str = "") -> None:
        content = self._format_search_results(items)
        target_type, target_id = self._target(group_id, user_id)
        if not target_type:
            await self.ctx.send.text(content, stream_id)
            return

        bot_name, bot_uin = await self._get_bot_identity()
        nodes = [
            {
                "type": "node",
                "data": {
                    "name": bot_name,
                    "uin": bot_uin,
                    "content": [{"type": "text", "data": {"text": f"JM搜索：{keyword}\n共返回 {len(items)} 条结果"}}],
                },
            }
        ]
        if not items:
            nodes.append(
                {
                    "type": "node",
                    "data": {
                        "name": bot_name,
                        "uin": bot_uin,
                        "content": [{"type": "text", "data": {"text": "没有找到相关作品。"}}],
                    },
                }
            )
        for index, item in enumerate(items, start=1):
            node_content = [{"type": "text", "data": {"text": f"{index}. 《{item['title']}》 - JM{item['album_id']}"}}]
            if item.get("cover_url"):
                node_content.append({"type": "image", "data": {"file": item["cover_url"]}})
            nodes.append(
                {
                    "type": "node",
                    "data": {
                        "name": bot_name,
                        "uin": bot_uin,
                        "content": node_content,
                    },
                }
            )

        if target_type == "group":
            params = {"group_id": target_id, "messages": nodes}
            api_name = "adapter.napcat.message.send_group_forward_msg"
        else:
            params = {"user_id": target_id, "messages": nodes}
            api_name = "adapter.napcat.message.send_private_forward_msg"

        await self.ctx.api.call(api_name, version="1", params=params)

    async def _download_pdf_and_send(self, album_id: str, stream_id: str, group_id: str = "", user_id: str = "") -> None:
        album_dir: Optional[Path] = None
        pdf_path: Optional[Path] = None
        try:
            if self.config.send.notice_before_download:
                await self._send_recallable_text(f"收到，正在下载 JM{album_id} 并转换为 PDF。", stream_id, group_id, user_id)
            pdf_path, album_dir = await self._run_blocking(self._convert_images_to_pdf_sync, album_id)
            await self._send_pdf_file(pdf_path, stream_id, group_id, user_id)
            await self._send_recallable_text(f"JM{album_id} 加密 PDF 已发送完成，打开密码为：{album_id}", stream_id, group_id, user_id)
        except Exception as exc:
            self.ctx.logger.error("[JMComicPlugin] PDF 发送失败: %s", exc, exc_info=True)
            await self._send_recallable_text(f"JM{album_id} 下载或发送失败，请稍后重试。", stream_id, group_id, user_id)
        finally:
            if album_dir:
                shutil.rmtree(album_dir, ignore_errors=True)
            if pdf_path and pdf_path.exists():
                pdf_path.unlink(missing_ok=True)

    async def _preview_and_send(self, album_id: str, stream_id: str, group_id: str = "", user_id: str = "") -> None:
        album_dir: Optional[Path] = None
        try:
            if self.config.send.notice_before_download:
                await self._send_recallable_text(f"收到，正在准备 JM{album_id} 验车图。", stream_id, group_id, user_id)
            album_dir, info_text, images = await self._run_blocking(self._preview_images_sync, album_id)
            await self._send_forward_images(album_id, info_text, images, stream_id, group_id, user_id)
        except Exception as exc:
            self.ctx.logger.error("[JMComicPlugin] 验车失败: %s", exc, exc_info=True)
            await self._send_recallable_text(f"JM{album_id} 验车失败，请稍后重试。", stream_id, group_id, user_id)
        finally:
            if album_dir:
                shutil.rmtree(album_dir, ignore_errors=True)

    async def _random_preview_and_send(self, stream_id: str, group_id: str = "", user_id: str = "") -> None:
        try:
            if self.config.send.notice_before_download:
                await self._send_recallable_text("收到，正在随机抽取本子并准备验车图。", stream_id, group_id, user_id)
            album_id = await self._run_blocking(self._random_album_id_sync)
            await self._preview_and_send(album_id, stream_id, group_id, user_id)
        except Exception as exc:
            self.ctx.logger.error("[JMComicPlugin] 随机本子失败: %s", exc, exc_info=True)
            await self._send_recallable_text("随机本子失败，请稍后重试。", stream_id, group_id, user_id)

    def _help_text(self) -> str:
        return (
            "JMComic 助手指令：\n"
            "1. /JM下载 123456：下载指定作品，转换为加密 PDF 并通过 QQ 文件发送。PDF 密码为车牌号，例如 123456。\n"
            "2. /JM验车 123456：发送作品信息和前几张预览图的 QQ 合并转发消息。\n"
            "3. /JM搜索 关键词 或 /JM 搜索 关键词：搜索作品并返回标题与 JM 车牌号。\n"
            "4. 随机本子：随机抽取一个作品，并按 JM验车 形式发送预览。\n"
            "5. /JM help：查看本帮助。\n"
            "注意：下载、验车、搜索、随机本子都需要命中插件白名单。"
        )

    # ── Tool: 下载并发送 PDF ────────────────────────────────

    @Tool(
        "jm_download_pdf",
        description=(
            "下载 JM/JMComic 漫画、本子、作品并转换为 PDF，通过 QQ/NapCat 文件发送给用户。"
            "当用户表达 /JM下载、JM下载、下载本子、发我本子、把 JM 漫画发给我等意图时必须调用。"
            "只需要 album_id，例如 123456 或 JM123456。"
        ),
        activation_type=ActivationType.ALWAYS,
        parameters=[
            ToolParameterInfo(
                name="album_id",
                param_type=ToolParamType.STRING,
                description="JM 作品 ID，例如 123456 或 JM123456",
                required=True,
            )
        ],
    )
    async def handle_download_pdf_tool(self, album_id: str, stream_id: str = "", group_id: str = "", user_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return {"name": "jm_download_pdf", "content": "JMComic 插件未启用。"}
        real_id = self._extract_album_id(album_id)
        if not real_id:
            return {"name": "jm_download_pdf", "content": "请提供正确的 JM 作品 ID，例如 123456 或 JM123456。"}
        group = str(group_id or kwargs.get("group_id", ""))
        user = str(user_id or kwargs.get("user_id", ""))
        allowed, reason = self._is_allowed(group, user)
        if not allowed:
            return {"name": "jm_download_pdf", "content": reason}
        asyncio.create_task(
            self._download_pdf_and_send(
                real_id,
                stream_id,
                group_id=group,
                user_id=user,
            )
        )
        return {"name": "jm_download_pdf", "content": f"已开始处理 JM{real_id}，完成后会通过 QQ 文件发送 PDF。"}

    # ── Tool: 验车合并转发 ─────────────────────────────────

    @Tool(
        "jm_preview_forward",
        description=(
            "JM验车工具。下载指定 JM 作品的前几张图，并通过 QQ 合并转发消息发送给用户。"
            "当用户发送 /JM验车 123456、JM验车 123456、验车、看看 JM 前几页、预览本子时必须调用。"
            "只需要 album_id，例如 123456 或 JM123456。"
        ),
        activation_type=ActivationType.ALWAYS,
        parameters=[
            ToolParameterInfo(
                name="album_id",
                param_type=ToolParamType.STRING,
                description="JM 作品 ID，例如 123456 或 JM123456",
                required=True,
            )
        ],
    )
    async def handle_preview_tool(self, album_id: str, stream_id: str = "", group_id: str = "", user_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return {"name": "jm_preview_forward", "content": "JMComic 插件未启用。"}
        real_id = self._extract_album_id(album_id)
        if not real_id:
            return {"name": "jm_preview_forward", "content": "请提供正确的 JM 作品 ID，例如 JM验车 123456。"}
        group = str(group_id or kwargs.get("group_id", ""))
        user = str(user_id or kwargs.get("user_id", ""))
        allowed, reason = self._is_allowed(group, user)
        if not allowed:
            return {"name": "jm_preview_forward", "content": reason}
        asyncio.create_task(
            self._preview_and_send(
                real_id,
                stream_id,
                group_id=group,
                user_id=user,
            )
        )
        return {"name": "jm_preview_forward", "content": f"已开始准备 JM{real_id} 的验车合并转发消息。"}

    # ── Tool: 搜索 ─────────────────────────────────────────

    @Tool(
        "jm_search",
        description="搜索 JM/JMComic 作品。当用户使用 /JM搜索、/JM 搜索、JM搜索 或想按关键词查找漫画、查找车牌号时必须调用。",
        activation_type=ActivationType.ALWAYS,
        parameters=[
            ToolParameterInfo(
                name="keyword",
                param_type=ToolParamType.STRING,
                description="搜索关键词",
                required=True,
            )
        ],
    )
    async def handle_search_tool(self, keyword: str, stream_id: str = "", group_id: str = "", user_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return {"name": "jm_search", "content": "JMComic 插件未启用。"}
        keyword = str(keyword).strip()
        if not keyword:
            return {"name": "jm_search", "content": "请输入搜索关键词，例如 JM搜索 关键词。"}
        group = str(group_id or kwargs.get("group_id", ""))
        user = str(user_id or kwargs.get("user_id", ""))
        allowed, reason = self._is_allowed(group, user)
        if not allowed:
            return {"name": "jm_search", "content": reason}
        try:
            items = await self._run_blocking(self._search_sync, keyword)
            if stream_id:
                await self._send_search_forward(keyword, items, stream_id, group, user)
                return {"name": "jm_search", "content": "搜索结果已通过合并转发发送。"}
            return {"name": "jm_search", "content": self._format_search_results(items)}
        except Exception as exc:
            self.ctx.logger.error("[JMComicPlugin] 搜索失败: %s", exc, exc_info=True)
            return {"name": "jm_search", "content": "搜索失败，请稍后重试。"}

    # ── Tool: 随机本子 ─────────────────────────────────────

    @Tool(
        "jm_random_preview",
        description="随机本子工具。当用户发送 随机本子、随机JM、随机验车、随便来一本时必须调用。会随机选取一个 JM 作品并按 JM验车 形式发送预览。",
        activation_type=ActivationType.ALWAYS,
        parameters=[],
    )
    async def handle_random_preview_tool(self, stream_id: str = "", group_id: str = "", user_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return {"name": "jm_random_preview", "content": "JMComic 插件未启用。"}
        group = str(group_id or kwargs.get("group_id", ""))
        user = str(user_id or kwargs.get("user_id", ""))
        allowed, reason = self._is_allowed(group, user)
        if not allowed:
            return {"name": "jm_random_preview", "content": reason}
        asyncio.create_task(self._random_preview_and_send(stream_id, group, user))
        return {"name": "jm_random_preview", "content": "已开始随机抽取本子，稍后会按 JM验车 形式发送预览。"}

    # ── Commands ──────────────────────────────────────────

    @Command(
        "jm",
        description="JMComic 综合命令，用法: /JM搜索、/JM下载、/JM验车、/JM help",
        pattern=r"(?P<jm_command>^/[Jj][Mm](?:\s*.+)?\s*$)",
    )
    async def handle_jm_command(self, stream_id: str = "", matched_groups: dict | None = None, **kwargs):
        self.ctx.logger.info("[JMComicPlugin] /JM 综合命令被调用: stream_id=%s", stream_id)
        raw_command = str((matched_groups or {}).get("jm_command", "") or kwargs.get("text", "") or self._extract_text(kwargs)).strip()
        self.ctx.logger.info("[JMComicPlugin] /JM 原始命令: %s", raw_command)
        body = re.sub(r"^/[Jj][Mm]\s*", "", raw_command, count=1).strip()

        if not body or body.lower() == "help":
            await self.ctx.send.text(self._help_text(), stream_id)
            return True, "帮助已发送", True

        if not self.config.plugin.enabled:
            await self._send_recallable_text("JMComic 插件未启用。", stream_id)
            return True, "插件未启用", True

        group = str(kwargs.get("group_id", ""))
        user = str(kwargs.get("user_id", ""))

        if body.startswith("搜索"):
            keyword = body[2:].strip()
            if not keyword:
                await self._send_recallable_text("请输入搜索关键词，例如: /JM搜索 关键词", stream_id)
                return True, "缺少关键词", True
            if not await self._check_permission_or_reply(stream_id, group, user):
                return True, "白名单拒绝", True
            try:
                items = await self._run_blocking(self._search_sync, keyword)
                await self._send_search_forward(keyword, items, stream_id, group, user)
                return True, "搜索完成", True
            except Exception as exc:
                self.ctx.logger.error("[JMComicPlugin] 搜索命令失败: %s", exc, exc_info=True)
                await self._send_recallable_text("搜索失败，请稍后重试。", stream_id)
                return False, "搜索失败", True

        if body.startswith("下载"):
            album_id = self._extract_album_id(body)
            if not album_id:
                await self._send_recallable_text("请提供正确的 JM 作品 ID，例如: /JM下载 123456", stream_id)
                return True, "ID 错误", True
            if not await self._check_permission_or_reply(stream_id, group, user):
                return True, "白名单拒绝", True
            asyncio.create_task(self._download_pdf_and_send(album_id, stream_id, group_id=group, user_id=user))
            return True, f"已开始处理 JM{album_id}", True

        if body.startswith("验车"):
            album_id = self._extract_album_id(body)
            if not album_id:
                await self._send_recallable_text("请提供正确的 JM 作品 ID，例如: /JM验车 123456", stream_id)
                return True, "ID 错误", True
            if not await self._check_permission_or_reply(stream_id, group, user):
                return True, "白名单拒绝", True
            asyncio.create_task(self._preview_and_send(album_id, stream_id, group_id=group, user_id=user))
            return True, f"已开始验车 JM{album_id}", True

        await self.ctx.send.text(self._help_text(), stream_id)
        return True, "未知 JM 指令，已发送帮助", True

    @Command("jm_random", description="随机本子，用法: 随机本子", pattern=r"^随机本子")
    async def handle_jm_random_command(self, stream_id: str = "", **kwargs):
        self.ctx.logger.info("[JMComicPlugin] 随机本子 命令被调用: stream_id=%s", stream_id)
        if not self.config.plugin.enabled:
            await self._send_recallable_text("JMComic 插件未启用。", stream_id)
            return True, "插件未启用", True
        group = str(kwargs.get("group_id", ""))
        user = str(kwargs.get("user_id", ""))
        if not await self._check_permission_or_reply(stream_id, group, user):
            return True, "白名单拒绝", True
        asyncio.create_task(self._random_preview_and_send(stream_id, group, user))
        return True, "已开始随机本子", True


def create_plugin():
    return JMComicPlugin()
