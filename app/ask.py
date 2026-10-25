"""第1回: 素のLLMに1回だけ質問するスクリプト。

使い方:
    uv run python -m app.ask "LoRAとは何ですか？"
    uv run python -m app.ask            # 質問を省略すると、講座に固有の質問をする

ツールも会話履歴も持たない「素の」呼び出し。
講座に固有のことを聞くと、「分からない」と答えるか、一般論でもっともらしく答える
（講座の実際とは違う）ことを確かめよう。
（第3回で、用語集を検索できるエージェントにして改善する）
"""

import argparse
import time
import os
import math
import statistics
from dataclasses import asdict, dataclass, fields

from google import genai
from google.genai import errors

from app.config import MODEL, api_error_message, get_api_key


# 講座に固有の質問。正しい答えは data/glossary.json の homework-levels にある
DEFAULT_QUESTION = "AIE2026の講座の宿題にある「3レベル」とは何ですか？"
DEFAULT_QUESTIONS = [
    "LoRAとは何ですか？",
    #"Attentionの計算量が系列長の2乗になる理由は？",
    "RLHFとDPOの違いは？",
    "KVキャッシュとは何か？",
]
DEFAULT_MODELS = "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
MODELS_STR = os.getenv("AIE_MODELS", DEFAULT_MODELS)
MODELS = MODELS_STR.split(",")
DEFAULT_REPEATS = 3  # 同じ(モデル, 質問)の反復回数。中央値を取るため 3 以上を推奨
PACE_RPM: float | None = 5.0  # モデルごとの送信間隔 = 60/PACE_RPM 秒。None で間隔制御なし（上限の実測用）
RATE_LIMITS: dict[str, dict[str, int | None]] = {
    "gemini-3.6-flash": {"rpm": 5, "tpm": 250_000, "rpd": 20},
    "gemini-3.5-flash-lite": {"rpm": 15, "tpm": 250_000, "rpd": 500},
    "gemini-3.1-flash-lite": {"rpm": 15, "tpm": 250_000, "rpd": 500},
}
MAX_RETRIES = 3
RETRYABLE_CODES = (429, 500, 503)
BACKOFF_BASE_SEC = 5.0  # 待機 = BASE * 2**retries

CHAT_INFO = {
    "play": False,
    "model": None,
    "contents": [],
}

@dataclass
class Row:
    ok: bool  # API 呼び出しが成功したか（本文が空でも True。finish で判別）
    model: str
    q_idx: int  # -1 はウォームアップ
    repeat: int
    elapsed: float | None  # 成功した試行1回分の秒数（ペーシング・バックオフ待機は含まない）
    prompt_tokens: int | None
    output_tokens: int | None
    thought_tokens: int | None
    text_chars: int | None
    finish: str
    retries: int
    error: str | None


def measure(client, model, question, q_idx, repeat, before_attempt, sleep):
    retries = 0
    while True:
        before_attempt(model)
        t0 = time.perf_counter()

        try:
            resp = client.models.generate_content(model=model, contents=question)
        except errors.APIError as e:
            if e.code in RETRYABLE_CODES and retries < MAX_RETRIES:
                sleep(BACKOFF_BASE_SEC * 2**retries)
                retries += 1
                continue
            return Row(False, model, q_idx, repeat, None, None, None, None, None, "", retries, f"{e.code} {e.status}")
        except Exception as e:  # タイムアウト等。ベンチを止めず記録して続行する
            return Row(False, model, q_idx, repeat, None, None, None, None, None, "", retries, type(e).__name)

        elapsed = time.perf_counter() - t0

        if CHAT_INFO["play"] and CHAT_INFO["model"] == None:
            CHAT_INFO["model"] = model
            CHAT_INFO["contents"].append({"role": "user", "parts": [{"text": question}]})
            CHAT_INFO["contents"].append({"role": "model", "parts": [{"text": resp.text}]})

        usage = resp.usage_metadata
        cand = resp.candidates[0] if resp.candidates else None
        finish = cand.finish_reason.name if cand is not None and cand.finish_reason else ""
        print(f"Q{q_idx} ({model}): {question}")
        print(resp.text)
        print("\n", "=" * 30, "\n", "=" * 30, "\n")
        return Row(
            True,
            model,
            q_idx,
            repeat,
            elapsed,
            usage.prompt_token_count if usage else None,
            usage.candidates_token_count if usage else None,
            usage.thoughts_token_count if usage else None,
            len(resp.text or ""),
            finish,
            retries,
            None
        )


def run_benchmark(client, models, questions, repeats, pace_rpm, warmup, sleep=time.sleep):
    """反復 → 質問 → モデルの順に回す（時間帯の偏りが特定モデルに乗らないように）。"""
    last_start: dict[str, float] = {}
    rows = []
    total = len(models) * (len(questions) * repeats + (1 if warmup else 0))

    def before_attempt(model: str) -> None:
        if pace_rpm:
            wait = last_start.get(model, -math.inf) + 60.0 / pace_rpm - time.monotonic()
            if wait > 0:
                sleep(wait)
        last_start[model] = time.monotonic()

    def run(model: str, question: str, q_idx: int, repeat: int) -> None:
        row = measure(client, model, question, q_idx, repeat, before_attempt, sleep)
        rows.append(row)

    t_start = time.perf_counter()
    if warmup:
        for model in models:
            run(model, "こんにちは", -1, 0)
    for rep in range(repeats):
        for qi, q in enumerate(questions):
            for model in models:
                run(model, q, qi, rep)
    return rows, time.perf_counter() - t_start


def dry_run(questions: list[str], warmup: bool, repeats: int) -> None:
    per_model = len(questions) * repeats + (1 if warmup else 0)
    interval = 60.0 / PACE_RPM if PACE_RPM else 0.0
    print(f"モデルあたり {per_model} リクエスト{"（ウォームアップ含む）" if warmup else ""}、合計 {per_model * len(MODELS)}")
    print(f"PACE_RPM={PACE_RPM} → モデルあたり最短 {per_model * interval:.0f} 秒")
    for m in MODELS:
        rpd = RATE_LIMITS.get(m, {}).get("rpd")
        print(f"  {m}: RPD 消費 {per_model}" + (f" / {rpd}" if rpd else "（RPD 未設定）"))


# ============================================================== 集計
def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else math.nan


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else math.nan


def f(x: float, spec: str = ".2f") -> str:
    return "-" if x is None or math.isnan(x) else format(x, spec)


def gen_tokens(r: Row) -> int:
    return (r.output_tokens or 0) + (r.thought_tokens or 0)


def print_summary(rows, wall_sec, models, questions) -> None:
    print("\n=== モデル別サマリ ===")
    print(
        f"{'model':26}{'n':>4}{'err':>5}{'retry':>6}{'nonSTOP':>8}"
        f"{'med_s':>8}{'max_s':>8}{'in_tok':>8}{'out_tok':>9}{'think_tok':>10}{'tok/s':>8}"
    )
    data = [r for r in rows if r.q_idx >= 0]
    for m in models:
        mr = [r for r in data if r.model == m]
        ok = [r for r in mr if r.ok]
        rate = [gen_tokens(r) / r.elapsed for r in ok if r.elapsed]
        print(
            f"{m:26}{len(ok):>4}{len(mr) - len(ok):>5}{sum(r.retries for r in mr):>6}"
            f"{sum(1 for r in ok if r.finish != 'STOP'):>8}"
            f"{f(median([r.elapsed for r in ok])):>8}{f(max((r.elapsed for r in ok), default=math.nan)):>8}"
            f"{f(mean([r.prompt_tokens for r in ok]), '.0f'):>8}"
            f"{f(mean([r.output_tokens for r in ok]), '.0f'):>9}"
            f"{f(mean([r.thought_tokens for r in ok]), '.0f'):>10}"
            f"{f(median(rate), '.1f'):>8}"
        )
    print("tok/s = (出力+思考)/全体時間。prefill と思考待ちを含む実効値で、純粋なデコード速度ではない")

    print("\n=== モデル × 質問（中央値秒 / 生成tok平均[出力+思考]）===")
    print(f"{'model':26}" + "".join(f"{'Q' + str(i):>14}" for i in range(1, len(questions) + 1)))
    for m in models:
        cells = []
        for qi in range(len(questions)):
            rs = [r for r in data if r.model == m and r.q_idx == qi and r.ok]
            cells.append(f"{f(median([r.elapsed for r in rs]), '.1f')}s/{f(mean([gen_tokens(r) for r in rs]), '.0f')}")
        print(f"{m:26}" + "".join(f"{c:>14}" for c in cells))


def print_rate_limit_report(rows, wall_sec, models) -> None:
    wall_min = max(wall_sec, 1e-9) / 60.0
    print("\n=== レート制限との関係 ===")
    print(f"実行時間 {wall_sec:.0f}秒（ペーシング待機・バックオフ含む）")
    for m in MODELS:
        mr = [r for r in rows if r.model == m]
        attempts = sum(r.retries + 1 for r in mr)  # 429 で弾かれた試行もリクエスト数に含める
        in_tok = sum(r.prompt_tokens or 0 for r in mr if r.ok)
        lat = median([r.elapsed for r in mr if r.ok and r.q_idx >= 0])
        seq_rpm = 60.0 / lat if lat and not math.isnan(lat) else math.nan

        print(f"[{m}]")
        print(f"  この実行の平均: {attempts / wall_min:.1f} RPM / 入力 {in_tok / wall_min:.0f} TPM（試行 {attempts} 回）")
        print(f"  逐次実行の理論上限: 60 / 中央値{f(lat, '.1f')}s = {f(seq_rpm, '.1f')} RPM")

        lim = RATE_LIMITS.get(m, {})
        rpm, tpm, rpd = lim.get("rpm"), lim.get("tpm"), lim.get("rpd")
        if rpm and not math.isnan(seq_rpm):
            if seq_rpm < rpm:
                print(f"  RPM {rpm}: 逐次では到達しない（到達には並列度 ≈ {rpm / seq_rpm:.1f} 必要）")
            else:
                print(f"  RPM {rpm}: 逐次でも超過しうる → 送信間隔 {60.0 / rpm:.1f}s 以上が必要")
            if PACE_RPM and PACE_RPM > rpm:
                print(f"  ! PACE_RPM={PACE_RPM} が上限 {rpm} を超えています")
        if tpm:
            print(f"  TPM {tpm}: 入力側の使用率 {in_tok / wall_min / tpm:.2%}（TPM は入力トークンのみ対象）")
        if rpd:
            print(f"  RPD {rpd}: この構成なら 1日 {rpd // attempts} 回分（1回 = {attempts} 試行）")
        if not (rpm or tpm or rpd):
            print("  RATE_LIMITS 未設定: AI Studio の値を入れると上限との比較を表示します")

def report(rows, wall, questions):
    print_summary(rows, wall, MODELS, questions)
    print_rate_limit_report(rows, wall, MODELS)


def ask_benchmark(client, questions: list[str], repeats: int, warmup: bool) -> None:
    return run_benchmark(client, MODELS, questions, repeats, PACE_RPM, warmup)


def ask(question: str) -> str:
    client = genai.Client(api_key=get_api_key())
    started_at = time.perf_counter()
    response = client.models.generate_content(model=MODEL, contents=question)
    elapsed = time.perf_counter() - started_at
    print(f"[応答時間] {elapsed:.2f}秒")

    usage = response.usage_metadata
    if usage is not None:
        print(f"[トークン数] 入力: {usage.prompt_token_count}, 出力: {usage.candidates_token_count}")

    return response.text


def main() -> None:
    parser = argparse.ArgumentParser(description="素のLLMに質問する")
    parser.add_argument("--dry-run", action="store_true", help="ベンチマークの実行はせず、リクエスト数と最短時間を表示する")
    parser.add_argument("--no-warmup", action="store_false", dest="warmup", help="ウォームアップを行わない")
    parser.add_argument("--warmup", action="store_true", help="ウォームアップを行う（最初に1回だけ実行し接続確立などの初回コストを除外する）")
    parser.add_argument("--repeat", type=int, dest="repeats", default=DEFAULT_REPEATS, help="同じ(モデル, 質問)の反復回数。中央値を取るため 3 以上を推奨")
    parser.add_argument("--no-report", action="store_true", help="レポートを表示しない")
    parser.add_argument("--chat", action="store_true", help="チャットモードで質問する")
    parser.add_argument("questions", nargs="*", default=DEFAULT_QUESTIONS)
    args = parser.parse_args()

    if args.dry_run:
        dry_run(args.questions, args.warmup, args.repeats)
        return

    if args.chat:
        CHAT_INFO["play"] = True

    client = genai.Client(api_key=get_api_key())
    rows, wall = ask_benchmark(client, args.questions, args.repeats, args.warmup)
    if not args.no_report:
        report(rows, wall, args.questions)

    if args.chat:
        print("\n\n会話を続けます。\n")
        while True:
            question = input("質問を入力してください（終了するには空でEnter）: ")
            if not question.strip():
                break
            CHAT_INFO["contents"].append({"role": "user", "parts": [{"text": question}]})
            response = client.models.generate_content(model=CHAT_INFO["model"], contents=CHAT_INFO["contents"])
            print(f"{CHAT_INFO["model"]}: {response.text}\n")
            CHAT_INFO["contents"].append({"role": "model", "parts": [{"text": response.text}]})

if __name__ == "__main__":
    main()
