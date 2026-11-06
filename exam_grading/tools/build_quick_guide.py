"""Make the quick guide that goes in each download: one page of English, one of Japanese.

    python tools/build_quick_guide.py <output.pdf> [windows|mac]

Uses PyMuPDF and its built-in Japanese font, like the student reports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf as fitz

PICTURES = Path(__file__).resolve().parent / "guide_images"

CSS = """
* { font-family: sans-serif; color: #1f2937; }
h1 { font-size: 22pt; color: #2563eb; margin: 0 0 4pt 0; }
h2 { font-size: 13pt; color: #2563eb; margin: 13pt 0 3pt 0; }
p, li { font-size: 10.5pt; line-height: 1.4; margin: 2pt 0; }
"""

ENGLISH = """
<h1>CAM2 Exam Grading</h1>
<p>Grade scanned exam papers one question at a time, then make a report for every student.</p>

<h2>Starting CAM2</h2>
<ol>
{start_steps}
<li>CAM2 opens in your web browser. Nothing is installed, and your papers stay on this computer.</li>
</ol>

<h2>Before you start</h2>
<ul>
<li>Your scanned papers. Scan the whole class into one PDF at the photocopier, or a few batches.</li>
<li>The paper size: A4, B5, A3 or a slide size.</li>
<li>If you have one, your class list in Excel or CSV.</li>
</ul>

<h2>The five steps</h2>
<ol>
<li><b>Exam &amp; scans:</b> name the exam, choose the scans and where to save.</li>
<li><b>Set up questions:</b> draw a box around each question and its answer on the first paper, and give it marks or a criterion.</li>
<li><b>Match names:</b> match each paper to a student.</li>
<li><b>Grade:</b> grade one question at a time.</li>
<li><b>Review &amp; export:</b> check the results, choose what goes on the report, and make the student reports and Excel gradebook.</li>
</ol>

<h2>Good to know</h2>
<ul>
<li>Every grade is saved as you give it. To carry on later, choose <b>Continue a previous session</b>.</li>
<li>To stop, click <b>Quit CAM2</b> on the start screen.</li>
<li>Choose <b>How to scan your papers</b> on the start screen for scanning advice.</li>
<li>Switch between English and 日本語 at the top of the start screen.</li>
</ul>
"""

JAPANESE = """
<h1>CAM2 Exam Grading</h1>
<p>スキャンした答案を設問ごとに採点し、生徒一人ひとりのレポートを作ります。</p>

<h2>CAM2の起動</h2>
<ol>
{start_steps}
<li>CAM2はWebブラウザーで開きます。インストールは不要で、答案はこのコンピューターの中だけで扱います。</li>
</ol>

<h2>用意するもの</h2>
<ul>
<li>スキャンした答案。コピー機でクラス全員分を1つのPDFに（または数回に分けて）スキャンします。</li>
<li>用紙サイズ：A4、B5、A3、スライドのいずれか。</li>
<li>クラス名簿（ExcelまたはCSV、あれば）。</li>
</ul>

<h2>5つのステップ</h2>
<ol>
<li><b>試験とスキャン：</b>試験名・スキャン・保存先を決めます。</li>
<li><b>設問の設定：</b>1枚目の答案で各設問と解答欄を枠で囲み、配点または基準を決めます。</li>
<li><b>氏名の照合：</b>答案と生徒を対応させます。</li>
<li><b>採点：</b>設問ごとに採点します。</li>
<li><b>確認と出力：</b>結果を確認し、レポートの内容を選んで、生徒レポートとExcelの成績表を作ります。</li>
</ol>

<h2>知っておくと便利なこと</h2>
<ul>
<li>採点はその都度保存されます。続きは<b>「前回の採点を続ける」</b>から始められます。</li>
<li>終了するには、スタート画面の<b>「CAM2を終了」</b>をクリックします。</li>
<li>スキャンの方法は、スタート画面の案内をご覧ください。</li>
<li>スタート画面の上部で、Englishと日本語を切り替えられます。</li>
</ul>
"""


START_STEPS = {
    "windows": (
        """
<li>Unzip the download, open the folder and double-click <b>Start CAM2 Exam Grading</b>.</li>
<li>If Windows says <i>Windows protected your PC</i>, click <b>More info</b>, then <b>Run anyway</b>.</li>
<li>If those options aren't there, as on some school computers, or it still won't start, right-click <b>Start CAM2 Exam Grading</b> and choose <b>Properties</b>. On the <b>General</b> tab, tick <b>Unblock</b>, then click <b>OK</b>.</li>
""",
        """
<li>ダウンロードしたzipを展開し、フォルダーを開いて<b>「Start CAM2 Exam Grading」</b>をダブルクリックします。</li>
<li>「WindowsによってPCが保護されました」と表示されたら、<b>「詳細情報」</b>、<b>「実行」</b>の順にクリックします。</li>
<li>学校のコンピューターなどでこれらが表示されないときや、それでも起動しないときは、<b>「Start CAM2 Exam Grading」</b>を右クリックして<b>「プロパティ」</b>を選び、<b>「全般」</b>タブの<b>「許可する」</b>にチェックを入れて<b>「OK」</b>をクリックします。</li>
"""),
    "mac": (
        """
<li>Double-click the download to unzip it, open the folder and double-click <b>Start CAM2 Exam Grading</b>.</li>
<li>The first time, your Mac says it could not verify CAM2, because CAM2 isn't signed. Click <b>Done</b>, not <b>Move to Trash</b>, and follow the pictures below. You only do this once.</li>
<li>If your Mac asks whether CAM2 may use a folder such as Documents, click <b>Allow</b>.</li>
""",
        """
<li>ダウンロードしたファイルをダブルクリックして展開し、フォルダーを開いて<b>「Start CAM2 Exam Grading」</b>をダブルクリックします。</li>
<li>初回は、署名がないためMacが確認できないと表示されます。<b>「ゴミ箱に入れる」</b>ではなく<b>「完了」</b>をクリックし、下の画像のとおりに進めます。これは最初の1回だけです。</li>
<li>書類フォルダーなどへのアクセスを求められたら、<b>「許可」</b>をクリックします。</li>
"""),
}


# Screenshots of the first-run approval, in tools/guide_images: file, width on the page.
MAC_PICTURES = (("mac_blocked.png", 128), ("mac_settings.png", 203), ("mac_confirm.png", 128))
MAC_PICTURES_HEIGHT = 128
MAC_CAPTIONS = (
    ("Opening CAM2 for the first time on a Mac",
     ("1. Click <b>Done</b>.",
      "2. In <b>System Settings &gt; Privacy &amp; Security</b>, scroll down and click <b>Open Anyway</b>.",
      "3. Click <b>Open Anyway</b>, then enter your password and click <b>OK</b>.")),
    ("Macで初めてCAM2を開くとき（画面は英語表示の例）",
     ("1. <b>「完了」</b>をクリックします。",
      "2. <b>「システム設定」＞「プライバシーとセキュリティ」</b>を下へスクロールし、<b>「このまま開く」</b>をクリックします。",
      "3. <b>「このまま開く」</b>をクリックし、パスワードを入力して<b>「OK」</b>をクリックします。")),
)
CONTENT = fitz.Rect(48, 48, 547, 794)


def add_mac_pictures(page, heading: str, captions) -> None:
    """Three pictures in a row at the foot of the page, each with its caption above."""
    top = CONTENT.y1 - MAC_PICTURES_HEIGHT - 72
    spare, _scale = page.insert_htmlbox(fitz.Rect(CONTENT.x0, top, CONTENT.x1, top + 24),
                                        f"<h2>{heading}</h2>", css=CSS + "h2 { margin: 0; }", scale_low=1)
    assert spare >= 0, "the Mac pictures' heading no longer fits"
    gap = (CONTENT.width - sum(width for _name, width in MAC_PICTURES)) / (len(MAC_PICTURES) - 1)
    left = CONTENT.x0
    for (name, width), caption in zip(MAC_PICTURES, captions):
        spare, _scale = page.insert_htmlbox(
            fitz.Rect(left, top + 24, left + width, top + 72), f"<p>{caption}</p>",
            css=CSS + "p { font-size: 8.5pt; line-height: 1.25; }", scale_low=1)
        assert spare >= 0, "a Mac picture's caption no longer fits"
        page.insert_image(fitz.Rect(left, top + 72, left + width, CONTENT.y1),
                          filename=str(PICTURES / name))
        left += width + gap


def build(output: str, system: str = "windows") -> None:
    doc = fitz.open()
    for body, steps, (heading, captions) in zip((ENGLISH, JAPANESE), START_STEPS[system], MAC_CAPTIONS):
        page = doc.new_page(width=595, height=842)
        body = body.replace("{start_steps}", steps)
        spare, _scale = page.insert_htmlbox(CONTENT, body, css=CSS, scale_low=1)
        assert spare >= 0, "the quick guide no longer fits on its page"
        if system == "mac":
            assert spare >= MAC_PICTURES_HEIGHT + 72, "the Mac pictures no longer fit on the page"
            add_mac_pictures(page, heading, captions)
    doc.subset_fonts()
    doc.save(output, garbage=4, deflate=True)
    doc.close()


if __name__ == "__main__":
    build(*sys.argv[1:])
