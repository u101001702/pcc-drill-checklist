# PCC 演習檢核表（TCH-015）

延長照護（Prolonged Casualty Care, PCC）演習用的評分檢核表，場景設定為基層醫療衛生單位的延長照護。

- 網頁版：開啟 `index.html`（GitHub Pages）
- 內容：主要傷情 A–Q、技術處置與管路 T1–T14、PCC 團隊流程；每題分「未發生：監測」與「已發生：治療」
- 頁面底部有「監測與治療計畫總表」，依選擇的傷情與各題狀態自動彙整
- 主要依據：JTS CPG 91 Prolonged Casualty Care、PFC WG 2014 十大核心能力、ATLS 11e、相關 JTS CPG；部分項目參考 Tintinalli 9e
- 本表為教學演習用，不取代臨床判斷與各單位規範

## 重建網頁

```bash
python3 build_checklist.py --data data --out index.html
```
