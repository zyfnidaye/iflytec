#!/usr/bin/env python3
"""
智能客服机器人评测脚本

功能：
1. 读取测试问题集
2. 逐条调用机器人 API
3. 评估回答质量（关键词匹配 + 人工标注）
4. 生成评测报告
"""
import json
import time
from pathlib import Path

import httpx

# 配置
API_URL = "http://127.0.0.1:8123/api/chat"
TEST_QUESTIONS_FILE = Path(__file__).parent / "test_questions.json"
RESULTS_FILE = Path(__file__).parent / "evaluation_results.json"


def load_test_questions():
    """加载测试问题集"""
    with open(TEST_QUESTIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def ask_bot(question: str, thread_id: str = "eval-test") -> str:
    """调用机器人 API"""
    payload = {
        "message": question,
        "thread_id": thread_id,
        "use_knowledge": True,
        "use_web": False,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            # 消费 SSE 流
            answer_parts = []
            with client.stream("POST", API_URL, json=payload) as resp:
                if resp.status_code != 200:
                    return f"[ERROR] API 返回 {resp.status_code}"

                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        try:
                            obj = json.loads(data)
                        except Exception:
                            continue

                        if event == "token" and "text" in obj:
                            answer_parts.append(obj["text"])
                        elif event == "error":
                            return f"[ERROR] {obj.get('message', '未知错误')}"

            return "".join(answer_parts).strip()
    except Exception as e:
        return f"[EXCEPTION] {e}"


def auto_evaluate(question: dict, answer: str) -> dict:
    """自动评估回答质量（基于关键词匹配）"""
    keywords = question.get("expected_answer_keywords", [])
    if not keywords:
        return {"score": None, "matched_keywords": [], "reason": "无关键词"}

    matched = [kw for kw in keywords if kw in answer]
    score = len(matched) / len(keywords)

    return {
        "score": score,
        "matched_keywords": matched,
        "total_keywords": len(keywords),
        "reason": f"匹配 {len(matched)}/{len(keywords)} 个关键词"
    }


def run_evaluation():
    """执行完整评测"""
    questions = load_test_questions()
    results = []

    print(f"开始评测，共 {len(questions)} 个问题...\n")

    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['category']} - {q['question']}")

        # 调用机器人
        answer = ask_bot(q["question"])

        # 自动评估
        evaluation = auto_evaluate(q, answer)

        # 记录结果
        result = {
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "answer": answer,
            "auto_evaluation": evaluation,
            "manual_rating": None,  # 待人工标注：good / ok / bad
            "manual_comment": ""     # 待人工补充
        }
        results.append(result)

        print(f"  回答长度: {len(answer)} 字")
        print(f"  自动评分: {evaluation['score']:.2f} ({evaluation['reason']})")
        print()

        # 避免请求过快
        time.sleep(0.5)

    # 保存结果
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"评测完成！结果已保存到: {RESULTS_FILE}")
    print("\n请手动审核结果，补充 manual_rating 和 manual_comment 字段")

    # 统计
    scores = [r["auto_evaluation"]["score"] for r in results if r["auto_evaluation"]["score"] is not None]
    if scores:
        avg_score = sum(scores) / len(scores)
        print(f"\n自动评估平均分: {avg_score:.2%}")

        # 按类别统计
        categories = {}
        for r in results:
            cat = r["category"]
            if cat not in categories:
                categories[cat] = []
            if r["auto_evaluation"]["score"] is not None:
                categories[cat].append(r["auto_evaluation"]["score"])

        print("\n分类准确率:")
        for cat, cat_scores in categories.items():
            if cat_scores:
                print(f"  {cat}: {sum(cat_scores) / len(cat_scores):.2%}")


if __name__ == "__main__":
    run_evaluation()
