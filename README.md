# PaintTool for Stable Diffusion WebUI Forge

外部ペイントツールで、ギャラリーの画像（未選択なら先頭）をワンクリックで開く拡張。プログラム上の既定は Windows の「mspaint.exe」。config.json に設定があればそれを優先（例: CLIP STUDIO）。

---

## ユーザーがやること（最短手順）

1. 拡張をインストール  
   webui の [Extensions] > [Install from URL] の URL に以下を入力して [Install]  
    `https://github.com/CircleD5/sd-open-paint-tool.git`
2. Forge を再起動
3. 画像を生成し、ギャラリー下の「🖌️ Paint」ボタンを押す

---

## config.json（サンプル）
{
  "editor_path": "C:\\Program Files\\CELSYS\\CLIP STUDIO 1.5\\CLIP STUDIO PAINT\\CLIPStudioPaint.exe",
  "export_format": "PNG",
  "export_jpeg_quality": 95
}

### 必須編集ポイント
- editor_path: 自分の環境の CLIP STUDIO（または他のエディタ）に変更可能  
  例: C:\\Program Files\\CELSYS\\CLIP STUDIO 2.0\\CLIP STUDIO PAINT\\CLIPStudioPaint.exe

---

## 補足
- 対象タブ: txt2img / img2img / extras  
- 画像は各タブの出力先（outdir_txt2img_samples / outdir_img2img_samples / outdir_extras_samples 既定）へ保存されます  
- ファイル名: YYYYMMDD_HHMMSS_index_counter_painted.<拡張子>（tab 名は含めません）  
