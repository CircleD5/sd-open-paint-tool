# extensions/paint-tool/scripts/extension.py
# -------------------------------------------------------------------
# PaintTool extension
# - Adds a button into the same button row (image_buttons_{tab})
# - Saves/copies the selected (or first) image into the per-tab output:
#     txt2img  -> shared.opts.outdir_txt2img_samples (or default)
#     img2img  -> shared.opts.outdir_img2img_samples (or default)
#     extras   -> shared.opts.outdir_extras_samples  (or default)
# - File naming: <YYYYMMDD_HHMMSS>_<index>_<counter>_painted.<ext>
#   (tab name is NOT included in the filename)
# - If the gallery item has no path (PIL in-memory), writes it there first
# - Editor path is read from config.json; if invalid/missing, falls back to
#   Windows Paint (C:\Windows\System32\mspaint.exe) or OS default opener
# -------------------------------------------------------------------

from __future__ import annotations

import os
import json
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional

import gradio as gr
from PIL import Image

from modules import script_callbacks
from modules.ui_components import ToolButton

# =========================
# Constants & Config paths
# =========================

EXT_NAME       = "paint-tool"
ICON_PAINT     = "🖌️"

# Program default: Windows built-in Paint
DEFAULT_EDITOR = r"C:\Windows\System32\mspaint.exe"

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
# NOTE: cleanup や export_dir は廃止しています

_DEFAULT_CONFIG = {
    "editor_path": r"C:\Program Files\CELSYS\CLIP STUDIO 1.5\CLIP STUDIO PAINT\CLIPStudioPaint.exe",  # sample; program default uses mspaint.exe
    "export_format": "PNG",           # "PNG" or "JPG"
    "export_jpeg_quality": 95         # 1-100
}

def load_config() -> Dict[str, Any]:
    cfg = dict(_DEFAULT_CONFIG)
    try:
        if os.path.exists(CFG_PATH):
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            merged: Dict[str, Any] = {}
            for k, v in _DEFAULT_CONFIG.items():
                uv = user.get(k, v)
                if k == "export_jpeg_quality":
                    try:
                        uv = int(uv)
                    except Exception:
                        uv = v
                elif k == "export_format":
                    uv = str(uv).upper() if isinstance(uv, (str, bytes)) else v
                    if uv not in ("PNG", "JPG"):
                        uv = "PNG"
                else:
                    if isinstance(v, str):
                        uv = str(uv)
                merged[k] = uv
            cfg.update(merged)
    except Exception as e:
        log(f"config load warning: {e}")
    return cfg

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

# =========================
# Per-tab outdir resolver
# =========================

def resolve_tab_outdir(tab: str) -> str:
    """
    Decide per-tab output directory:
      1) shared.opts.outdir_{tab}_samples if set/non-empty
      2) default under data_path/outputs/{txt2img-images|img2img-images|extras-images}
      3) final fallback: extensions/paint-tool/exports
    """
    try:
        from modules import shared, paths  # lazy import
        per_tab_key = f"outdir_{tab}_samples"
        per_tab_val = getattr(shared.opts, per_tab_key, "")
        if isinstance(per_tab_val, str) and per_tab_val.strip():
            d = per_tab_val.strip()
            ensure_dir(d)
            return d

        # default locations (matching A1111/Forge options defaults)
        default_output_dir = os.path.join(paths.data_path, "outputs")
        sub_map = {
            "txt2img": "txt2img-images",
            "img2img": "img2img-images",
            "extras":  "extras-images",
        }
        sub = sub_map.get(tab, "txt2img-images")
        d = os.path.join(default_output_dir, sub)
        ensure_dir(d)
        return d

    except Exception as e:
        log(f"resolve_tab_outdir fallback due to: {e}")

    # ultimate fallback
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

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def next_base_name(self, index: int) -> str:
        """
        Filename base without tab (requested), and must include _painted.
        Pattern: <YYYYMMDD_HHMMSS>_<index>_<counter>_painted
        """
        self.counter += 1
        base = f"{self._timestamp()}_{index}_{self.counter}_painted"
        return sanitize_filename(base)

    def ext_for_export(self) -> str:
        fmt = (self.cfg.get("export_format") or "PNG").upper()
        return ".jpg" if fmt == "JPG" else ".png"

    def export_image(self, img: Image.Image, tab: str, index: int) -> str:
        outdir = resolve_tab_outdir(tab)
        name = self.next_base_name(index) + self.ext_for_export()
        dest = os.path.join(outdir, name)

        fmt = (self.cfg.get("export_format") or "PNG").upper()
        if fmt == "JPG":
            img = img.convert("RGB")
            quality = int(self.cfg.get("export_jpeg_quality", 95))
            img.save(dest, format="JPEG", quality=quality, optimize=True)
        else:
            img.save(dest, format="PNG", optimize=True)
        return dest

    def copy_file(self, src_path: str, tab: str, index: int) -> str:
        outdir = resolve_tab_outdir(tab)
        # keep original extension, add _painted suffix
        root, ext = os.path.splitext(strip_query(src_path))
        if not ext:
            # if original has no extension, fall back to export format
            ext = self.ext_for_export()
        name = self.next_base_name(index) + ext
        dest = os.path.join(outdir, name)
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
        """
        Save/copy into per-tab outdir and return the saved path.
        """
        # dict {"name": "..."} → copy to outdir with painted suffix
        if isinstance(item, dict):
            p = strip_query(item.get("name") or "")
            if p and os.path.exists(p):
                return self.exporter.copy_file(p, tab, index)

        # string path → copy to outdir with painted suffix
        if isinstance(item, str):
            p = strip_query(item)
            if os.path.exists(p):
                return self.exporter.copy_file(p, tab, index)

        # (PIL.Image, ...) → export to outdir
        if isinstance(item, (tuple, list)) and item:
            maybe_img = item[0]
            if isinstance(maybe_img, Image.Image):
                return self.exporter.export_image(maybe_img, tab, index)

        # PIL.Image → export to outdir
        if isinstance(item, Image.Image):
            return self.exporter.export_image(item, tab, index)

        return None

    # ---------- Action (button click) ----------

    def open_in_editor(self, images: Any, index: Optional[Any], tab: Optional[str] = None) -> None:
        try:
            # Validate images
            if not isinstance(images, (list, tuple)) or len(images) == 0:
                log("未実行: ギャラリーに画像がありません")
                return

            # Normalize index
            try:
                idx = int(index)
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
                    # editor invalid → OS default opener
                    log(f"editor_path 無効/未設定。既定アプリで開きます: {path}")
                    if os.name == "nt":
                        os.startfile(path)  # type: ignore[attr-defined]
                    elif os.name == "posix":
                        # macOS / Linux
                        try:
                            subprocess.Popen(["open", path])  # macOS
                        except Exception:
                            subprocess.Popen(["xdg-open", path])  # Linux
                    else:
                        # last resort
                        subprocess.Popen([path])
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
                tooltip="Save to per-tab outdir (_painted) and open in external editor",
            )
            btn.click(
                fn=self.open_in_editor,
                _js="""
                (images, tabName) => {
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

        # 1) capture galleries
        if elem_id.endswith(GALLERY_ID_SUFFIX):
            tab = elem_id[:-len(GALLERY_ID_SUFFIX)]
            if tab:
                self.galleries[tab] = component
                pending_row = self.pending_rows.pop(tab, None)
                if pending_row is not None:
                    self.inject_button_into_row(tab, pending_row)

        # 2) inject into button rows
        if elem_id.startswith(ROW_ID_PREFIX):
            tab = elem_id[len(ROW_ID_PREFIX):]
            self.inject_button_into_row(tab, component)

# =========================
# Register callbacks
# =========================

_instance = PaintTool()
script_callbacks.on_after_component(_instance.on_after_component)
