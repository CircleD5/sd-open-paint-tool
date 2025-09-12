# PaintTool for Stable Diffusion WebUI Forge

外部ペイントツール（既定: CLIP STUDIO）で、ギャラリーの画像（未選択なら先頭）をワンクリックで開く拡張。

---

## ユーザーがやること（最短手順）

1. 拡張を配置  
   stable-diffusion-webui-forge/extensions/paint-tool/scripts/extension.py

2. 設定ファイルを用意  
   stable-diffusion-webui-forge/extensions/paint-tool/config.json を作成（下記サンプルをコピペして編集）

3. Forge を再起動

4. 画像を生成し、ギャラリー下の「🖌️ Paint」ボタンを押す  
   - 未選択なら 0 番（先頭）を自動で開く  
   - メモリ上の画像は `export_dir` に書き出してから開く

---

## config.json（サンプル）
```json
{
  "editor_path": "C:\\Program Files\\CELSYS\\CLIP STUDIO 1.5\\CLIP STUDIO PAINT\\CLIPStudioPaint.exe",
  "export_dir": "D:\\SD\\PaintExports",
  "always_export_copy": false,
  "export_format": "PNG",
  "export_jpeg_quality": 95,
  "export_naming": "{datetime}_{tab}_{index}_{counter}",
  "export_cleanup_days": 0
}
```

### 必須編集ポイント
- editor_path: 自分の環境の CLIP STUDIO（または他のペイントツール）の実行ファイルに変更する  
  例: C:\\Program Files\\CELSYS\\CLIP STUDIO 2.0\\CLIP STUDIO PAINT\\CLIPStudioPaint.exe
- export_dir: 書き出し先フォルダ（永続化したい場所）に変更する

### 主なオプション
- always_export_copy (false/true)  
  既にパスがある画像でも毎回 `export_dir` にコピーしてから開く（元ファイルを汚したくない場合は true）
- export_format (PNG/JPG), export_jpeg_quality: 書き出し形式と品質
- export_naming: ファイル名テンプレ。{datetime} {tab} {index} {counter} が使用可
- export_cleanup_days: Forge起動時に `export_dir` を日数基準で自動掃除（0 なら無効）

---

## 補足
- 対象タブ: txt2img / img2img / extras  
- editor_path が無効なら OS 既定アプリで開く（Windows: os.startfile, macOS: open, Linux: xdg-open）

## トラブル時
- 起動しない: editor_path の存在チェック。無効でも既定アプリで開くログが出ます
- 書き出されない: export_dir の権限/空き容量を確認
