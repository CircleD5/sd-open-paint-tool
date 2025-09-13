# extensions/paint-tool/scripts/extension.py
# -------------------------------------------------------------------
# PaintTool extension
# - Injects a button into the same button row (image_buttons_{tab})
# - Opens the selected image (or first if none) in an external editor
# - If the gallery item has no path (PIL in-memory), exports to a user-
#   configurable persistent directory (export_dir) before opening
# - When export_dir is empty or missing, falls back to Forge/A1111 output
#   directory (outdir_{tab}_samples or outdir_samples)
# - Editor and export settings are configurable via config.json
# -------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import subprocess
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set

import gradio as gr
from PIL import Image

from modules import script_callbacks
from modules.ui_components import ToolButton

# =========================
# Constants & Config paths
# =========================

EXT_NAME       = "paint-tool"
ICON_PAINT     = "🖌️"
DEFAULT_EDITOR = r"C:\Program Files\CELSYS\CLIP STUDIO 1.5\CLIP STUDIO PAINT\CLIPStudioPaint.exe"

EXT_ROOT   = os.path.dirname(os.path.dirname(__file__))             # .../extensions/paint-tool
CFG_PATH   = os.path.join(EXT_ROOT, "config.json")
LOG_PREFIX = f"[{EXT_NAME}]"

ROW_ID_PREFIX     = "image_buttons_"
GALLERY_ID_SUFFIX = "_gallery"

TARGET_TABS = {"txt2img", "img2img", "extras"}

# =========================
# Small utilities
# =========================

def log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}")

def strip_query(p: str) -> str:
    return p.split("?", 1)[0] if p else p

def sanitize_filename(name: str) -> str:
    bad = '<>:"/\\|?*\n\r\t'
    for ch in bad:
        name = name.replace(ch, "_")
    return name

# =========================
# Config management
# =========================

_DEFAULT_CONFIG = {
    "editor_path": DEFAULT_EDITOR,
    "export_dir": os.path.join(EXT_ROOT, "exports"),
    "always_export_copy": False,
    "export_format": "PNG",           # "PNG" or "JPG"
    "export_jpeg_quality": 95,        # 1-100
    "export_naming": "{datetime}_{tab}_{index}_{counter}",
    "export_cleanup_days": 0          # 0 = no cleanup
}

def load_config() -> Dict[str, Any]:
    cfg = dict(_DEFAULT_CONFIG)
    try:
        if os.path.exists(CFG_PATH):
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            # 型ゆらぎに耐性を持たせる
            merged: Dict[str, Any] = {}
            for k, v in _DEFAULT_CONFIG.items():
                uv = user.get(k, v)
                if k == "export_cleanup_days":
                    try:
                        uv = int(uv)
                    except Exception:
                        uv = v
                elif k == "export_jpeg_quality":
                    try:
                        uv = int(uv)
                    except Exception:
                        uv = v
                elif k == "always_export_copy":
                    uv = bool(uv)
                elif k == "export_format":
                    uv = str(uv).upper() if isinstance(uv, (str, bytes)) else v
                    if uv not in ("PNG", "JPG"):
                        uv = "PNG"
                else:
                    # 文字列系
                    if isinstance(v, str):
                        uv = str(uv)
                merged[k] = uv
            cfg.update(merged)
    except Exception as e:
        log(f"config load warning: {e}")
    return cfg

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def cleanup_dir(path: str, days: int) -> None:
    if not days or days <= 0:
        return
    try:
        cutoff = datetime.now() - timedelta(days=days)
        for name in os.listdir(path):
            p = os.path.join(path, name)
            try:
                if os.path.isfile(p):
                    mtime = datetime.fromtimestamp(os.path.getmtime(p))
                    if mtime < cutoff:
                        os.remove(p)
            except Exception:
                pass
    except Exception:
        pass

# =========================
# Export dir resolver
# =========================

def resolve_export_dir(tab: str, cfg: Dict[str, Any]) -> str:
    """
    Returns export directory with fallbacks:
      1) User-configured export_dir if non-empty and exists
      2) shared.opts.outdir_{tab}_samples (Forge/A1111) if available
      3) shared.opts.outdir_samples if available
      4) extensions/paint-tool/exports (final fallback)
    """
    # 1) user-configured directory (must exist)
    user_dir = str(cfg.get("export_dir") or "").strip()
    if user_dir and os.path.isdir(user_dir):
        return user_dir

    # 2) Forge/A1111 outdir for the tab, or global samples
    try:
        from modules import shared  # lazy import for compatibility
        per_tab_attr = f"outdir_{tab}_samples"
        outdir = getattr(shared.opts, per_tab_attr, None) or getattr(shared.opts, "outdir_samples", None)
        if outdir:
            ensure_dir(outdir)
            return outdir
    except Exception:
        pass

    # 3) final fallback to extension-local exports
    fallback = os.path.join(EXT_ROOT, "exports")
    ensure_dir(fallback)
    return fallback

# =========================
# Export helpers
# =========================

class Exporter:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.counter = 0
        self._cleaned_dirs: Set[str] = set()

    def _maybe_prepare_dir(self, path: str) -> None:
        ensure_dir(path)
        days = int(self.cfg.get("export_cleanup_days", 0))
        if days > 0 and path not in self._cleaned_dirs:
            cleanup_dir(path, days)
            self._cleaned_dirs.add(path)

    def next_name(self, tab: str, index: int) -> str:
        self.counter += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self.cfg.get("export_naming", _DEFAULT_CONFIG["export_naming"]).format(
            datetime=ts, tab=tab, index=index, counter=self.counter
        )
        return sanitize_filename(base)

    def ext(self) -> str:
        fmt = (self.cfg.get("export_format") or "PNG").upper()
        return ".jpg" if fmt == "JPG" else ".png"

    def export_image(self, img: Image.Image, tab: str, index: int) -> str:
        export_dir = resolve_export_dir(tab, self.cfg)
        self._maybe_prepare_dir(export_dir)

        name = self.next_name(tab, index) + self.ext()
        dest = os.path.join(export_dir, name)

        fmt = (self.cfg.get("export_format") or "PNG").upper()
        if fmt == "JPG":
            img = img.convert("RGB")
            quality = int(self.cfg.get("export_jpeg_quality", 95))
            img.save(dest, format="JPEG", quality=quality, optimize=True)
        else:
            img.save(dest, format="PNG", optimize=True)
        return dest

    def copy_file(self, src_path: str, tab: str, index: int) -> str:
        export_dir = resolve_export_dir(tab, self.cfg)
        self._maybe_prepare_dir(export_dir)

        name = self.next_name(tab, index) + os.path.splitext(strip_query(src_path))[-1]
        dest = os.path.join(export_dir, name)
        shutil.copy2(strip_query(src_path), dest)
        return dest

# =========================
# Core class
# =========================

class PaintTool:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.exporter = Exporter(self.cfg)
        self.galleries: Dict[str, Any] = {}
        self.pending_rows: Dict[str, Any] = {}

    # ---------- Resolve path from gallery item ----------

    def ensure_path_from_gallery_item(self, item: Any, tab: str, index: int) -> Optional[str]:
        # dict {"name": "..."}
        if isinstance(item, dict):
            p = strip_query(item.get("name") or "")
            if p and os.path.exists(p):
                return self.exporter.copy_file(p, tab, index) if self.cfg.get("always_export_copy") else p

        # 文字列
        if isinstance(item, str):
            p = strip_query(item)
            if os.path.exists(p):
                return self.exporter.copy_file(p, tab, index) if self.cfg.get("always_export_copy") else p

        # (PIL.Image, ...)
        if isinstance(item, (tuple, list)) and item:
            maybe_img = item[0]
            if isinstance(maybe_img, Image.Image):
                return self.exporter.export_image(maybe_img, tab, index)

        # PIL.Image
        if isinstance(item, Image.Image):
            return self.exporter.export_image(item, tab, index)

        return None

    # ---------- Action (button click) ----------

    def open_in_editor(self, images: Any, index: Optional[Any], tab: Optional[str] = None) -> None:
        try:
            # images が配列でないケースにも防御
            if not isinstance(images, (list, tuple)):
                log("未実行: ギャラリーに画像がありません（images が配列ではありません）")
                return
            if len(images) == 0:
                log("未実行: ギャラリーに画像がありません")
                return

            # index を安全に int 化
            try:
                idx = int(index)  # ここで '3' のような文字列を数値化
            except Exception:
                idx = 0
            if idx < 0 or idx >= len(images):
                idx = 0

            tab = (tab or "unknown") if isinstance(tab, str) else "unknown"

            item = images[idx]
            path = self.ensure_path_from_gallery_item(item, tab, idx)
            if not path:
                log("画像パス生成に失敗（Gallery要素にパス無し）")
                return
            if not os.path.exists(path):
                log(f"ファイルが見つかりません: {path}")
                return

            editor = (self.cfg.get("editor_path") or "").strip()
            try:
                if editor and os.path.exists(editor):
                    log(f"Launch editor: {editor} {path}")
                    subprocess.Popen([editor, path])
                else:
                    log(f"editor_path 無効/未設定。既定アプリで開きます: {path}")
                    if os.name == "nt":
                        os.startfile(path)  # type: ignore[attr-defined]
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", path])
                    else:
                        subprocess.Popen(["xdg-open", path])
            except Exception as e:
                log(f"外部起動エラー: {e}")

        except Exception as e:
            log(f"例外: {e}")

    # ---------- UI Injection ----------

    def inject_button_into_row(self, tab: str, row_component: Any) -> None:
        if tab not in TARGET_TABS:
            return

        gallery = self.galleries.get(tab)
        if not gallery:
            self.pending_rows[tab] = row_component
            log(f"gallery not found yet; pending row for tab={tab}")
            return

        with row_component:
            btn = ToolButton(
                ICON_PAINT,
                elem_id=f"{ROW_ID_PREFIX}{tab}_paint_tool",
                tooltip="Open image in external editor (PaintTool)",
            )
            btn.click(
                fn=self.open_in_editor,
                _js="""
                (images, tabName) => {
                    // index は数値だが、送受信時に文字列化される場合があるため
                    const getIdx = () => (typeof selected_gallery_index === "function") ? selected_gallery_index() : null;
                    const i   = getIdx();
                    const len = Array.isArray(images) ? images.length : 0;
                    const idx = (i == null || i < 0 || i >= len) ? 0 : i;
                    return [images, idx, tabName];
                }
                """,
                inputs=[gallery, gr.State(tab)],
                outputs=[],
                show_progress=False,
            )

    def on_after_component(self, component: Any, **kwargs) -> None:
        elem_id = (kwargs.get("elem_id") or "").strip()

        # 1) ギャラリー捕捉
        if elem_id.endswith(GALLERY_ID_SUFFIX):
            tab = elem_id[:-len(GALLERY_ID_SUFFIX)]
            if tab:
                self.galleries[tab] = component
                pending_row = self.pending_rows.pop(tab, None)
                if pending_row is not None:
                    self.inject_button_into_row(tab, pending_row)

        # 2) ボタン行（Row）に注入
        if elem_id.startswith(ROW_ID_PREFIX):
            tab = elem_id[len(ROW_ID_PREFIX):]
            self.inject_button_into_row(tab, component)

# =========================
# Register callbacks
# =========================

_instance = PaintTool()
script_callbacks.on_after_component(_instance.on_after_component)
