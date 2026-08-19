# -*- coding: utf-8 -*-
"""
修復 source/GenRyuMin2TW-R.ttf，讓瀏覽器願意載入它。

背景
----
原始字型檔有兩處不符規範，Chromium 的字型檢查器 (OTS) 會直接拒絕載入：

    OTS parsing error: maxp: Bad maxZones: 0
    cmap: Failed to read segment 1609
    cmap: Failed to parse format 4 cmap subtable 0

reportlab（xhtml2pdf 用的）比較寬鬆，照收不誤，所以以前轉 PDF 看不出問題；
但只要是瀏覽器 —— 包含「開立繳費單」的 HTML 預覽視窗、以及現在用來轉 PDF 的
Chromium —— 都會靜默改用系統預設字型（實測會變成 PMingLiU），
於是預覽與 PDF 的字都不是原本要的源流明體。

修法
----
1. maxp.maxZones 0 -> 1
   規範只允許 1（不使用 twilight zone）或 2，0 是無效值。

2. 移除壞掉的 format 4 cmap 子表
   這個字型另有 format 12 的子表 ((0,4) 與 (3,10))，涵蓋完整 Unicode，
   format 4 只能表示 BMP、本來就是相容性用途，刪掉不影響中文顯示。

用法
----
    python tools/repair_quotation_font.py

會就地覆寫 source/GenRyuMin2TW-R.ttf，並先備份成 .orig。
字型檔約 19MB，處理需要數十秒。
"""
import os
import shutil
import sys

from fontTools.ttLib import TTFont

FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'source', 'GenRyuMin2TW-R.ttf')


def repair(path=FONT_PATH):
    if not os.path.exists(path):
        print(f'找不到字型檔：{path}')
        return 1

    backup = path + '.orig'
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print(f'已備份原始檔 -> {backup}')

    font = TTFont(backup if os.path.exists(backup) else path, fontNumber=0)

    changed = []

    if font['maxp'].maxZones != 1:
        print(f"maxp.maxZones: {font['maxp'].maxZones} -> 1")
        font['maxp'].maxZones = 1
        changed.append('maxp.maxZones')

    cmap = font['cmap']
    before = [(t.platformID, t.platEncID, t.format) for t in cmap.tables]
    # 只留 format 12（完整 Unicode）；壞掉的 format 4 直接拿掉
    kept = [t for t in cmap.tables if t.format != 4]
    if kept and len(kept) != len(cmap.tables):
        cmap.tables = kept
        after = [(t.platformID, t.platEncID, t.format) for t in kept]
        print(f'cmap 子表: {before} -> {after}')
        changed.append('cmap')
    elif not kept:
        print('警告：移除 format 4 後就沒有 cmap 子表了，保持原樣不動。')

    if not changed:
        print('沒有需要修正的地方。')
        return 0

    font.save(path)
    size = os.path.getsize(path) / 1048576
    print(f'已寫回 {path}（{size:.1f} MB），修正項目：{", ".join(changed)}')
    return 0


if __name__ == '__main__':
    sys.exit(repair())
