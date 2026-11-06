"""Make a made-up exam, whole class, for testing CAM2 by hand. All of it is made up.

    python tools/make_sample_exam.py <output folder>

Creates one folder per language, sample-exam-en and sample-exam-ja, each with:
    exam-whole-class.pdf  6 students' papers of 4 pages each, as scanned images,
                          each a few millimetres off, like real scans
    class_list.xlsx       the class list
    rubrics.xlsx          three sample rubrics to upload (CAM2 ships no rubric text;
                          this wording is only for testing)
    Test-guide.pdf        what to do, the grades to give, and the results to expect

The expected results are worked out here with plain arithmetic, not by CAM2's
engine, so comparing them with the app is a real check.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf as fitz  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from engine import i18n, reports  # noqa: E402

MM = 72 / 25.4
PAGE_W, PAGE_H = 210 * MM, 297 * MM
PAGES_PER_STUDENT = 4
LANGUAGES = ("en", "ja")
OUT_OF = {"Q1": 10, "Q2": 6, "Q3": 8, "Q4": 8, "Q5": 8, "Q6": 8, "Q7": 8}
SHARES = (34, 33, 33)       # equal shares of three sections, leftover to the first
NA = None                   # the student left it blank: give *Not answered*

# The grades to give. Q5 is (Criterion B, Criterion C) on the rubric paper, and its
# first number on the marks paper. Students answer one of Q6 and Q7: the third
# student answered both, and the last answered neither.
GRADES = [
    {"Q1": 9, "Q2": 5, "Q3": 7, "Q4": 7, "Q5": (6, 7), "Q6": 7, "Q7": NA},
    {"Q1": 7, "Q2": 4, "Q3": 5, "Q4": 5, "Q5": (4, 5), "Q6": NA, "Q7": 5},
    {"Q1": 10, "Q2": 6, "Q3": 8, "Q4": 8, "Q5": (8, 7), "Q6": 8, "Q7": 3},
    {"Q1": 5, "Q2": 2, "Q3": 3, "Q4": 3, "Q5": (2, 3), "Q6": 3, "Q7": NA},
    {"Q1": 6, "Q2": 3, "Q3": NA, "Q4": 4, "Q5": (4, 4), "Q6": NA, "Q7": 4},
    {"Q1": 8, "Q2": 4, "Q3": 6, "Q4": 6, "Q5": (5, 6), "Q6": NA, "Q7": NA},
]

STUDENTS = {
    "en": [("Clarke", "Emma"), ("Patel", "Liam"), ("Rossi", "Sofia"), ("Kim", "Noah"), ("Haddad", "Ava"), ("Novak", "Leo")],
    "ja": [("田中", "花"), ("佐藤", "健"), ("鈴木", "結衣"), ("伊藤", "芽衣"), ("渡辺", "空"), ("山本", "陸")],
}

# (question, options, index of the right option)
MULTIPLE_CHOICE = {
    "en": [
        ("1.1 Which gas do plants take in?", ("oxygen", "carbon dioxide", "nitrogen", "hydrogen"), 1),
        ("1.2 Where in a cell is DNA mostly kept?", ("nucleus", "cell wall", "vacuole", "membrane"), 0),
        ("1.3 What is the unit of force?", ("joule", "watt", "newton", "volt"), 2),
        ("1.4 Which is a metal?", ("sulfur", "copper", "carbon", "neon"), 1),
        ("1.5 What does a thermometer measure?", ("mass", "time", "volume", "temperature"), 3),
        ("1.6 Which organ pumps blood?", ("heart", "lung", "liver", "kidney"), 0),
        ("1.7 Water boils at sea level at about:", ("50 °C", "100 °C", "150 °C", "200 °C"), 1),
        ("1.8 Which planet is nearest the Sun?", ("Venus", "Earth", "Mercury", "Mars"), 2),
        ("1.9 Which is a producer in a food chain?", ("fox", "rabbit", "hawk", "grass"), 3),
        ("1.10 Sound cannot travel through:", ("a vacuum", "water", "steel", "air"), 0),
    ],
    "ja": [
        ("1.1 植物が取り入れる気体はどれか。", ("酸素", "二酸化炭素", "窒素", "水素"), 1),
        ("1.2 細胞の中で主にDNAがある場所はどこか。", ("核", "細胞壁", "液胞", "細胞膜"), 0),
        ("1.3 力の単位はどれか。", ("ジュール", "ワット", "ニュートン", "ボルト"), 2),
        ("1.4 金属はどれか。", ("硫黄", "銅", "炭素", "ネオン"), 1),
        ("1.5 温度計がはかるものはどれか。", ("質量", "時間", "体積", "温度"), 3),
        ("1.6 血液を送り出す器官はどれか。", ("心臓", "肺", "肝臓", "腎臓"), 0),
        ("1.7 海面の高さで水が沸騰する温度はおよそ何度か。", ("50 ℃", "100 ℃", "150 ℃", "200 ℃"), 1),
        ("1.8 太陽に最も近い惑星はどれか。", ("金星", "地球", "水星", "火星"), 2),
        ("1.9 食物連鎖で生産者にあたるものはどれか。", ("キツネ", "ウサギ", "タカ", "草"), 3),
        ("1.10 音が伝わらないものはどれか。", ("真空", "水", "鉄", "空気"), 0),
    ],
}

# Each written question: its wording, then an answer that is strong, middling and weak.
WRITTEN = {
    "en": {
        "Q2": ("Name the parts of a plant that take in water and make food, and say what each does.",
               ("Roots take in water and minerals from the soil. Leaves make food by photosynthesis using light.",
                "Roots take in water. Leaves make food.", "Leaves are green.")),
        "Q3": ("Explain why the Moon seems to change shape during a month.",
               ("The Moon orbits Earth, so we see different amounts of its sunlit half. That is why the phases change.",
                "The Moon moves around Earth and the Sun lights it up.", "Clouds cover part of the Moon.")),
        "Q4": ("Plan an experiment to test how light affects plant growth.",
               ("Grow six plants at three light levels for two weeks. Keep water and soil the same. Measure height every day.",
                "Put some plants in the dark and some in light, then measure them.", "Give plants more light.")),
        "Q5": ("Here are some results: 2 cm, 5 cm and 9 cm of growth at low, medium and high light. Draw a conclusion and "
               "say how the experiment could be improved.",
               ("More light gives more growth: 9 cm at high light against 2 cm at low. Repeating each level would make it more reliable.",
                "Plants grew more with more light. We could do it again.", "The plants grew.")),
        "Q6": ("Explain how a food chain moves energy from the Sun to a hawk.",
               ("Grass stores the Sun's energy. A rabbit eats the grass and a hawk eats the rabbit, and some energy is lost at each step.",
                "The grass gets energy from the Sun, and then animals eat it.", "Hawks eat things.")),
        "Q7": ("Explain why a metal spoon feels colder than a wooden spoon in the same room.",
               ("Both are at room temperature, but metal conducts heat away from your hand much faster than wood does.",
                "Metal takes heat from your hand faster.", "Metal is cold.")),
    },
    "ja": {
        "Q2": ("水を吸収する部分と養分をつくる部分の名前を答え、それぞれのはたらきを説明しなさい。",
               ("根は土から水と養分を吸収する。葉は光を使って光合成を行い、養分をつくる。",
                "根が水を吸う。葉が養分をつくる。", "葉は緑色である。")),
        "Q3": ("1か月の間に月の形が変わって見える理由を説明しなさい。",
               ("月が地球のまわりを公転するので、太陽に照らされた半分の見え方が変わるから。",
                "月が地球のまわりを回り、太陽に照らされるから。", "雲が月をかくすから。")),
        "Q4": ("光の量が植物の成長にどう影響するかを調べる実験を計画しなさい。",
               ("6株の植物を3段階の明るさで2週間育てる。水と土は同じにして、毎日高さをはかる。",
                "暗い所と明るい所に植物を置いて、あとで高さをはかる。", "光をたくさん当てる。")),
        "Q5": ("光が弱い・中くらい・強いとき、成長はそれぞれ2 cm、5 cm、9 cmだった。結論を述べ、実験の改善点を答えなさい。",
               ("光が強いほどよく成長する。強い光で9 cm、弱い光で2 cmだった。各条件をくり返すと信頼性が上がる。",
                "光が多いとよく育った。もう一度やるとよい。", "植物は育った。")),
        "Q6": ("太陽のエネルギーがタカまで伝わるしくみを、食物連鎖を使って説明しなさい。",
               ("草が太陽のエネルギーをたくわえ、ウサギが草を、タカがウサギを食べる。各段階でエネルギーの一部は失われる。",
                "草が太陽からエネルギーを得て、動物がそれを食べる。", "タカはえものを食べる。")),
        "Q7": ("同じ部屋にあるのに、金属のスプーンが木のスプーンより冷たく感じる理由を説明しなさい。",
               ("どちらも室温だが、金属は木よりずっと速く手から熱を伝えて奪うから。",
                "金属は手の熱を速くうばうから。", "金属は冷たいから。")),
    },
}

RUBRICS = {
    "en": [
        ("Criterion A", (("0", "Does not reach the level below."), ("1-2", "Recalls some facts."),
                         ("3-4", "States ideas and applies them to familiar problems."),
                         ("5-6", "Outlines ideas and applies them to some unfamiliar problems."),
                         ("7-8", "Explains ideas fully and applies them to new problems."))),
        ("Criterion B", (("0", "Does not reach the level below."), ("1-2", "States part of a method."),
                         ("3-4", "Describes a simple method."), ("5-6", "Plans a workable method and explains most choices."),
                         ("7-8", "Plans a fair method and justifies every choice."))),
        ("Criterion C", (("0", "Does not reach the level below."), ("1-2", "Reads some values from data."),
                         ("3-4", "Describes patterns in data."), ("5-6", "Interprets data and draws a conclusion."),
                         ("7-8", "Analyses data and draws a conclusion the evidence fully supports."))),
    ],
    "ja": [
        ("基準A", (("0", "下の段階に達していない。"), ("1-2", "いくつかの事実を思い出せる。"),
                 ("3-4", "考えを述べ、なじみのある問題に使える。"), ("5-6", "考えを説明し、なじみのない問題にも一部使える。"),
                 ("7-8", "考えを十分に説明し、新しい問題に使える。"))),
        ("基準B", (("0", "下の段階に達していない。"), ("1-2", "方法の一部を述べられる。"),
                 ("3-4", "簡単な方法を説明できる。"), ("5-6", "実行できる方法を計画し、選択の理由を説明できる。"),
                 ("7-8", "公平な方法を計画し、すべての選択の理由を示せる。"))),
        ("基準C", (("0", "下の段階に達していない。"), ("1-2", "データからいくつかの値を読み取れる。"),
                 ("3-4", "データの傾向を説明できる。"), ("5-6", "データを解釈し、結論を述べられる。"),
                 ("7-8", "データを分析し、根拠が十分に支える結論を述べられる。"))),
    ],
}

PAPER_TEXT = {
    "en": {"title": "Grade 8 Science: Term 2 Exam", "name": "Name:", "minutes": "60 minutes. Answer in the spaces given.",
           "section_a": "Section A: Multiple choice. Circle one answer for each. (Q1, 10 marks)",
           "section_b": "Section B: Short answers", "section_c": "Section C: Investigation",
           "choose": "Answer ONE of Q6 or Q7.", "marks": "({n} marks)"},
    "ja": {"title": "中学2年 理科 2学期 期末試験", "name": "氏名：", "minutes": "60分。解答らんに答えなさい。",
           "section_a": "セクションA：選択問題。正しいものを1つ丸で囲みなさい。（問1、10点）",
           "section_b": "セクションB：短い記述", "section_c": "セクションC：探究",
           "choose": "Q6かQ7のどちらか1問に答えなさい。", "marks": "（{n}点）"},
}

WRITING_CSS = {"en": "* { font-family: serif; font-style: italic; color: #1a1a80; font-size: 13pt; line-height: 1.5; }",
               "ja": "* { font-family: sans-serif; color: #1a1a80; font-size: 12pt; line-height: 1.6; }"}
PRINT_CSS = "* { font-family: sans-serif; color: #111111; font-size: 10.5pt; line-height: 1.3; } b { font-size: 12pt; }"


def full_name(family: str, given: str, language: str) -> str:
    return f"{family} {given}" if language == "ja" else f"{given} {family}"


def number(grade) -> int:
    """The grade on a paper of marks: Q5's first number, and 0 for *Not answered*."""
    if isinstance(grade, tuple):
        return grade[0]
    return 0 if grade is NA else grade


def one_decimal(value: Fraction) -> Decimal:
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return exact.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def expected_results(grades: dict) -> dict:
    """What the guide tells testers to expect, by plain arithmetic.

    ``all_marks`` is the paper with marks on every question (the better of Q6 and
    Q7 counts), ``weighted`` the same paper in three sections at SHARES, and
    ``mixed_marks`` the paper where only Q1 to Q3 have marks.
    """
    a = number(grades["Q1"])
    b = number(grades["Q2"]) + number(grades["Q3"])
    c = number(grades["Q4"]) + number(grades["Q5"]) + max(number(grades["Q6"]), number(grades["Q7"]))
    total = a + b + c
    weighted = Fraction(a, 10) * SHARES[0] + Fraction(b, 14) * SHARES[1] + Fraction(c, 24) * SHARES[2]
    return {"all_marks": total, "all_percent": one_decimal(Fraction(total * 100, 48)),
            "weighted": one_decimal(weighted),
            "mixed_marks": a + b, "mixed_percent": one_decimal(Fraction((a + b) * 100, 24))}


# --- The papers ---------------------------------------------------------------------------

def _answer(language: str, question: str, grade) -> str:
    if grade is NA:
        return ""
    words = WRITTEN[language][question][1]
    score = number(grade) * 8 / OUT_OF[question]
    return words[0 if score >= 6 else 1 if score >= 3 else 2]


def _draw_paper(language: str, name: str, grades: dict, rng: random.Random) -> fitz.Document:
    text = PAPER_TEXT[language]
    written = WRITTEN[language]
    dx, dy = rng.uniform(-3, 3) * MM, rng.uniform(-3, 3) * MM     # scan offset

    def rect(x0, y0, x1, y1):
        return fitz.Rect(x0 * MM + dx, y0 * MM + dy, x1 * MM + dx, y1 * MM + dy)

    def printed(page, box, html):
        page.insert_htmlbox(rect(*box), html, css=PRINT_CSS)

    def written_question(page, top, height, qid):
        printed(page, (20, top, 190, top + 16),
                f"<b>{qid}</b> {written[qid][0]} {text['marks'].format(n=OUT_OF[qid])}")
        page.draw_rect(rect(20, top + 16, 190, top + height), color=(0.35, 0.35, 0.35), width=0.6)
        page.insert_htmlbox(rect(24, top + 19, 186, top + height - 2), _answer(language, qid, grades[qid]),
                            css=WRITING_CSS[language])

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    printed(page, (20, 12, 190, 22), f"<b>{text['title']}</b>")
    page.draw_rect(rect(20, 23, 120, 37), color=(0, 0, 0), width=0.8)
    printed(page, (22, 24, 40, 30), text["name"])
    page.insert_htmlbox(rect(40, 26, 118, 36), name, css=WRITING_CSS[language])
    printed(page, (125, 26, 190, 37), text["minutes"])
    printed(page, (20, 42, 190, 50), f"<b>{text['section_a']}</b>")
    # A student with n marks gets the first n of a shuffled list right.
    items = MULTIPLE_CHOICE[language]
    order = list(range(len(items)))
    rng.shuffle(order)
    right = set(order[:grades["Q1"]])
    for i, (question, options, key) in enumerate(items):
        top = 52 + i * 22
        printed(page, (20, top, 190, top + 8), question)
        chosen = key if i in right else (key + 1 + rng.randrange(3)) % 4
        for j, option in enumerate(options):
            x = 26 + j * 41
            printed(page, (x, top + 9, x + 6, top + 17), "ABCD"[j])
            printed(page, (x + 6, top + 9, x + 40, top + 17), option)
            if j == chosen:
                page.draw_circle(fitz.Point((x + 1.6) * MM + dx, (top + 11.2) * MM + dy), 3.4 * MM,
                                 color=(0.1, 0.1, 0.5), width=1.1)

    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    printed(page, (20, 14, 190, 22), f"<b>{text['section_b']}</b>")
    written_question(page, 26, 120, "Q2")
    written_question(page, 152, 120, "Q3")

    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    printed(page, (20, 14, 190, 22), f"<b>{text['section_c']}</b>")
    written_question(page, 26, 120, "Q4")
    written_question(page, 152, 120, "Q5")

    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    printed(page, (20, 14, 190, 22), f"<b>{text['choose']}</b>")
    written_question(page, 26, 120, "Q6")
    written_question(page, 152, 120, "Q7")
    return doc


def make_papers(language: str, path: str) -> None:
    """The whole class as one PDF of page images, as from a photocopier."""
    rng = random.Random(8)
    with fitz.open() as scan:
        for (family, given), grades in zip(STUDENTS[language], GRADES):
            with _draw_paper(language, full_name(family, given, language), grades, rng) as paper:
                for page in paper:
                    image = page.get_pixmap(dpi=150).tobytes("jpeg", jpg_quality=78)
                    scan.new_page(width=PAGE_W, height=PAGE_H).insert_image(fitz.Rect(0, 0, PAGE_W, PAGE_H), stream=image)
        scan.save(path, garbage=4, deflate=True)


def make_class_list(language: str, path: str) -> None:
    wb = Workbook()
    wb.active.append(["番号", "姓", "名"] if language == "ja" else ["No.", "Family name", "Given name"])
    for i, (family, given) in enumerate(STUDENTS[language], 1):
        wb.active.append([i, family, given])
    wb.save(path)


def make_rubrics(language: str, path: str) -> None:
    wb = Workbook()
    wb.active.append(["基準", "レベル", "記述"] if language == "ja" else ["Criterion", "Levels", "Descriptor"])
    for name, bands in RUBRICS[language]:
        for levels, descriptor in bands:
            wb.active.append([name, levels, descriptor])
    wb.save(path)


# --- The guide -----------------------------------------------------------------------------

def _guide_text(language: str) -> dict:
    words = {key: i18n.t(key, language).replace("→", "").replace("✂", "").strip() for key in (
        "step1.combined", "step1.pages_per_student", "step2.mode.marks", "step2.mode.rubric",
        "step2.boxes.add_criteria", "step2.rubric.upload", "step2.sections.start", "step2.sections.start_short",
        "step2.sub.choice", "step2.sub.slice", "step5.option.overall_criteria", "step5.option.section_results",
        "step5.option.images_for", "step5.weighting", "step5.preview", "step5.make_all", "grade.not_answered")}
    if language == "ja":
        return dict(words, **{
            "title": "CAM2 テストの手順", "lead": "架空の理科の試験と、架空の生徒6人の答案です。試験を2回つくって、CAM2の主な使い方を試します。"
            "所要時間はそれぞれ約15分です。採点を考える必要はありません。下の表のとおりに入力して、結果を比べてください。",
            "files": "<b>ファイル：</b> exam-whole-class.pdf（クラス全員、1人4ページ）、class_list.xlsx（名簿）、rubrics.xlsx（ルーブリック）。",
            "grades": "つける採点", "student": "生徒", "dash": "「—」は「{na}」を押します。Q5の「6/7」は、試験1では6点、試験2では基準B 6・基準C 7です。",
            "start": "どちらの試験も同じように始めます", "boxes": "氏名欄と各問に枠を描きます（Q1は1ページ目、Q2・Q3は2ページ目、Q4・Q5は3ページ目、Q6・Q7は4ページ目）。「{choice}」で、Q6とQ7を「1問に解答」にします。氏名の照合では class_list.xlsx を使います。",
            "new": "新しいセッションで「{combined}」を選び、exam-whole-class.pdf を指定します。1人のページ数は 4 です。",
            "exam1": "試験1：点数だけ → あとから基準とセクションを追加", "exam2": "試験2：ルーブリックから始める → あとから点数を追加（点数とルーブリックの混在）",
            "e1": ["はじめ方で「{marks}」を選びます。配点は Q1 10点、Q2 6点、Q3〜Q7 各8点です。",
                   "<b>確認：</b>ルーブリックの画面に一度も案内されないこと（「任意」と書かれたタブは表示されたままです）。全問を採点すると、合計が下の「試験1 合計」と同じになること。レポートに基準やセクションが出ないこと。",
                   "設問の設定に戻り、「{add_criteria}」から rubrics.xlsx をアップロードします。切り取りの表で全問に基準Aのチェックを入れ、Q2とQ4の行で「{start_short}」を押します。",
                   "<b>確認：</b>切り取り直しが不要で、採点が残っていること。",
                   "確認と出力で「{weighting}」「{overall}」にチェックを入れます。比重は 34・33・33 になります。",
                   "<b>確認：</b>全体の割合が下の「試験1 比重あり」と同じで、基準Aの点数も同じであること。比重を1つ入力しても合計が100%のままであること。",
                   "最終レベルを1人だけ入力し、「{section_results}」にチェックを入れ、「{preview}」を押します。「{make_all}」を押します。",
                   "<b>確認：</b>入力したレベルの帯に色がつくこと。空欄の生徒について警告が出ること。Excelにセクションの列があること。"],
            "e2": ["はじめ方で「{rubric}」を選び、「{upload}」で rubrics.xlsx を読み込みます。",
                   "基準のチェック：Q1〜Q3は基準A、Q4は基準B、Q5は基準Bと基準C、Q6・Q7は基準C。",
                   "切り取りの表で配点を入力します：Q1 10点、Q2 6点、Q3 8点。Q4の行で「{start_short}」を押します。",
                   "<b>確認：</b>Q4〜Q7がルーブリックで採点する設問として名前が出ること。",
                   "採点します。<b>確認：</b>Q1〜Q3は点数のボタン、Q4〜Q7はレベルのボタンが出ること。Q5は基準ごとにタブがあること。",
                   "確認と出力で「{overall}」にチェックを入れ、「{images}」で1つのセクションのチェックを外して、「{preview}」を押します。",
                   "<b>確認：</b>合計が下の「試験2 点数」と同じで、レベルが足されていないこと。レポートに B7、C7 のように出ること。画像を外したセクションが一覧になること。"],
            "expect": "期待される結果", "exam1_total": "試験1 合計（/48）", "exam1_weighted": "試験1 比重あり", "exam2_marks": "試験2 点数（/24）",
            "report": "おかしな点があれば、どの手順で何が起きたかをメモして知らせてください。名前や答案は架空のものなので、共有しても問題ありません。",
        })
    return dict(words, **{
        "title": "CAM2 test guide",
        "lead": "A made-up science exam and 6 made-up students' papers. You set up two exams, which between them try the main "
                "ways of using CAM2, in about 15 minutes each. You don't have to decide any grades: give the ones in the table "
                "below, then compare your results.",
        "files": "<b>Files:</b> exam-whole-class.pdf (the whole class, 4 pages each), class_list.xlsx, rubrics.xlsx.",
        "grades": "The grades to give", "student": "Student",
        "dash": "“—” means press “{na}”. Q5 “6/7” means 6 marks in Exam 1, and Criterion B 6 and Criterion C 7 in Exam 2.",
        "start": "Start both exams the same way",
        "new": "Start a new session, choose “{combined}” and pick exam-whole-class.pdf. Each paper has 4 pages.",
        "boxes": "Draw the name box and a box for each question (Q1 is on page 1, Q2 and Q3 on page 2, Q4 and Q5 on page 3, "
                 "Q6 and Q7 on page 4). In “{choice}”, make Q6 and Q7 “answer 1”. Use class_list.xlsx when matching names.",
        "exam1": "Exam 1: marks only, then add criteria and sections later",
        "exam2": "Exam 2: start from a rubric, then add marks later (a mixed paper)",
        "e1": ["On the first screen choose “{marks}”. Marks: Q1 10, Q2 6, Q3 to Q7 8 each.",
               "<b>Check:</b> you are never sent to a rubric screen (its tab stays there, marked optional). When all are graded, each total matches “Exam 1 total” below. "
               "The report shows no criteria or sections.",
               "Go back to Set up questions. Use “{add_criteria}” to upload rubrics.xlsx. In the Slice screen's table, tick "
               "Criterion A on every question, and press “{start_short}” on the Q2 and Q4 rows.",
               "<b>Check:</b> nothing needs slicing again, and every grade is still there.",
               "In Review & export, tick “{weighting}” and “{overall}”. The shares are 34, 33 and 33.",
               "<b>Check:</b> the percentages match “Exam 1 weighted” below, and Criterion A's match them too. Typing one "
               "share keeps the total at 100%.",
               "Type a final level for one student only, tick “{section_results}”, and press “{preview}”. Then press “{make_all}”.",
               "<b>Check:</b> the band of that final level is shaded. You are warned about the blank final levels. The Excel "
               "file has columns for each section."],
        "e2": ["On the first screen choose “{rubric}”, and use “{upload}” to load rubrics.xlsx.",
               "Tick the criteria: Q1 to Q3 Criterion A, Q4 Criterion B, Q5 Criteria B and C, Q6 and Q7 Criterion C.",
               "In the Slice screen's table, type marks: Q1 10, Q2 6, Q3 8. Press “{start_short}” on the Q4 row.",
               "<b>Check:</b> Q4 to Q7 are named as the questions graded with rubric levels.",
               "Grade. <b>Check:</b> Q1 to Q3 show mark buttons, Q4 to Q7 show levels, and Q5 has a tab for each criterion.",
               "In Review & export, tick “{overall}”, untick one section under “{images}”, and press “{preview}”.",
               "<b>Check:</b> the total matches “Exam 2 marks” below, with no levels added in. The report shows grades like B7 "
               "and C7. The section with images off prints as a grid."],
        "expect": "The results to expect", "exam1_total": "Exam 1 total (/48)", "exam1_weighted": "Exam 1 weighted", "exam2_marks": "Exam 2 marks (/24)",
        "report": "If anything looks wrong, note which step and what happened. The names and papers are all made up, so they are "
                  "safe to share.",
    })


def make_guide(language: str, path: str) -> None:
    words = _guide_text(language)
    fill = dict(combined=words["step1.combined"], choice=words["step2.sub.choice"], marks=words["step2.mode.marks"],
                rubric=words["step2.mode.rubric"], add_criteria=words["step2.boxes.add_criteria"],
                upload=words["step2.rubric.upload"], start_short=words["step2.sections.start_short"],
                weighting=words["step5.weighting"], overall=words["step5.option.overall_criteria"],
                section_results=words["step5.option.section_results"], images=words["step5.option.images_for"],
                preview=words["step5.preview"], make_all=words["step5.make_all"], na=words["grade.not_answered"])
    names = [full_name(family, given, language) for family, given in STUDENTS[language]]

    def shown(grade):
        return "—" if grade is NA else f"{grade[0]}/{grade[1]}" if isinstance(grade, tuple) else str(grade)

    with fitz.open() as doc:
        w = reports._Writer(doc, words["title"])
        w.html(f"<h1>{words['title']}</h1>", gap=6)
        w.html(f"<p>{words['lead']}</p>", gap=4)
        w.html(f"<p>{words['files']}</p>", gap=8)
        w.html(f"<h2>{words['start']}</h2>", gap=3)
        w.html(f"<p>{words['new'].format(**fill)}</p><p>{words['boxes'].format(**fill)}</p>", gap=8)
        for title, steps in ((words["exam1"], words["e1"]), (words["exam2"], words["e2"])):
            w.ensure(80)
            w.html(f"<h2>{title}</h2>", gap=3)
            for step in steps:
                w.html(f"<p>{step.format(**fill)}</p>", gap=2)
            w.y += 6
        w.ensure(150)
        w.html(f"<h2>{words['grades']}</h2>", gap=3)
        questions = list(OUT_OF)
        widths = [reports.CONTENT_W - 7 * 44] + [44] * 7
        rows = [[f"<p><b>{words['student']}</b></p>"] + [f"<p><b>{q} /{OUT_OF[q]}</b></p>" for q in questions]]
        rows += [[f"<p>{name}</p>"] + [f"<p>{shown(grades[q])}</p>" for q in questions]
                 for name, grades in zip(names, GRADES)]
        reports._table(w, widths, rows, [reports.HEADING] + [None] * len(names))
        w.y += 4
        w.html(f"<p class='muted'>{words['dash'].format(**fill)}</p>", gap=8)
        w.ensure(130)
        w.html(f"<h2>{words['expect']}</h2>", gap=3)
        rows = [[f"<p><b>{text}</b></p>" for text in (words["student"], words["exam1_total"], words["exam1_weighted"], words["exam2_marks"])]]
        for name, grades in zip(names, GRADES):
            result = expected_results(grades)
            rows.append([f"<p>{name}</p>", f"<p>{result['all_marks']} · {result['all_percent']}%</p>",
                         f"<p>{result['weighted']}%</p>", f"<p>{result['mixed_marks']} · {result['mixed_percent']}%</p>"])
        reports._table(w, [reports.CONTENT_W - 3 * 110] + [110] * 3, rows, [reports.HEADING] + [None] * len(names))
        w.y += 8
        w.html(f"<p>{words['report']}</p>")
        w.finish()
        doc.subset_fonts()
        doc.save(path, garbage=4, deflate=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    args = parser.parse_args(argv)
    for language in LANGUAGES:
        folder = os.path.join(args.out, f"sample-exam-{language}")
        os.makedirs(folder, exist_ok=True)
        make_papers(language, os.path.join(folder, "exam-whole-class.pdf"))
        make_class_list(language, os.path.join(folder, "class_list.xlsx"))
        make_rubrics(language, os.path.join(folder, "rubrics.xlsx"))
        make_guide(language, os.path.join(folder, "Test-guide.pdf"))
        print(f"Made {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
