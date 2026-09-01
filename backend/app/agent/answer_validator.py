"""答案质量验证器：检测潜在的过时信息风险。

用于 Agent Harness 的输出验证层——在答案返回给用户前，检查是否包含
"可能基于过时训练数据的时效性断言"，配合知识库覆盖状态和联网状态，
决定是否需要拦截并强制模型重新搜索确认。
"""
import re
from datetime import datetime


def contains_time_sensitive_claims(text: str, strict: bool = False) -> dict:
    """检测文本是否包含时效性断言（版本号、日期、"最新"等）。

    Args:
        text: 待检测的答案文本
        strict: 是否启用严格模式（包含"最新"等弱信号）

    Returns:
        {
            "has_risk": bool,           # 是否有风险
            "signals": [str],           # 命中的信号类型列表
            "examples": [str],          # 提取的具体示例（前3个）
            "confidence": "high"|"medium"|"low"
        }
    """
    signals = []
    examples = []

    # ---- 1. 版本号检测（强信号）----
    # 匹配: v1.2.3, Java 21, Python 3.11, Spring Boot 2.7.x, SDK v3
    version_pattern = r"""
        (?:
            (?:v|V|版本|version)\s*[\d.]+[a-zA-Z0-9.-]*   # v1.2.3, 版本3.2
            |
            (?:Java|Python|Node|Go|Ruby|PHP|\.NET|Spring|Django|React|Vue)\s+\d+(?:\.\d+)*  # Java 21, Python 3.11
            |
            \b\d+\.\d+(?:\.\d+)?(?:\.\d+)?[a-zA-Z0-9-]*\b  # 纯版本号 1.2.3, 3.11.5-rc1
        )
    """
    version_matches = re.findall(version_pattern, text, re.VERBOSE | re.IGNORECASE)
    if version_matches:
        signals.append("version")
        examples.extend(version_matches[:2])  # 取前2个

    # ---- 2. 年份/日期检测（强信号）----
    # 只检测近期年份（避免误杀历史讨论）：当前年份前后5年
    current_year = datetime.now().year
    year_range = range(current_year - 5, current_year + 2)

    # 匹配: 2023年, 2025-11, 于2026年, 截至2024
    date_pattern = rf"""
        (?:
            (?:20[12]\d)年                    # 2023年
            |
            (?:20[12]\d)[-/]\d{{1,2}}         # 2025-11, 2024/3
            |
            (?:于|在|截至|从|到|自)\s*(?:20[12]\d) # 于2023, 截至2026
        )
    """
    date_matches = re.findall(date_pattern, text, re.VERBOSE)
    # 过滤：只保留在 year_range 内的
    recent_dates = [d for d in date_matches if any(str(y) in d for y in year_range)]
    if recent_dates:
        signals.append("recent_date")
        examples.extend(recent_dates[:2])

    # ---- 3. "最新"类关键词（中等信号，仅严格模式或配合版本号）----
    latest_keywords = [
        "最新版本", "最新的", "当前版本", "当前的", "目前的", "现在的",
        "latest", "current", "newest", "up-to-date"
    ]
    has_latest = any(kw in text.lower() for kw in latest_keywords)
    if has_latest and (strict or version_matches):  # 严格模式 或 已有版本号
        signals.append("latest_keyword")
        matched_kw = [kw for kw in latest_keywords if kw in text.lower()]
        examples.append(f"关键词: {matched_kw[0] if matched_kw else 'latest'}")

    # ---- 4. 时间副词（弱信号，仅严格模式）----
    if strict:
        time_adverbs = ["最近", "近期", "近日", "刚刚", "即将", "不久前", "recently", "lately"]
        has_time_adv = any(adv in text.lower() for adv in time_adverbs)
        if has_time_adv:
            signals.append("time_adverb")

    # ---- 5. 具体数据+单位（市值、下载量等，弱信号，仅严格模式）----
    if strict:
        # 匹配: $1.2B, 500万次, 排名第3, 3.5亿用户
        data_pattern = r"""
            (?:
                \$[\d.]+[KMBT]              # $1.2B
                |
                \d+(?:\.\d+)?[万亿千百]+     # 500万, 3.5亿
                |
                排名第\d+                    # 排名第3
            )
        """
        data_matches = re.findall(data_pattern, text, re.VERBOSE)
        if data_matches:
            signals.append("specific_data")
            examples.append(f"数据: {data_matches[0]}")

    # ---- 决策逻辑 ----
    has_risk = False
    confidence = "low"

    if "version" in signals or "recent_date" in signals:
        # 强信号：版本号或近期日期 → 高风险
        has_risk = True
        confidence = "high"
    elif "latest_keyword" in signals and len(signals) > 1:
        # "最新" + 其他信号 → 中等风险
        has_risk = True
        confidence = "medium"
    elif strict and len(signals) >= 2:
        # 严格模式下，多个弱信号叠加 → 低风险但标记
        has_risk = True
        confidence = "low"

    return {
        "has_risk": has_risk,
        "signals": signals,
        "examples": examples[:3],  # 最多返回3个示例
        "confidence": confidence,
    }


# ---- 测试用例 ----
if __name__ == "__main__":
    test_cases = [
        # 高风险
        ("Java 21 是最新的 LTS 版本，于 2023 年 9 月发布", True),
        ("当前 Python 3.11 的性能提升了 25%", True),
        ("Spring Boot 2.7.x 是稳定版本", True),
        ("截至 2026 年 1 月，该库已有 500 万下载", True),

        # 中风险
        ("最新版本增加了虚拟线程支持", True),  # 严格模式才触发
        ("这是当前最流行的框架", False),  # 无版本号，宽松模式不触发

        # 无风险
        ("快速排序的时间复杂度是 O(n log n)", False),
        ("HTTP 状态码 200 表示成功", False),
        ("该公司成立于 2010 年，经历了快速发展", False),  # 历史年份，不在近期范围
        ("使用装饰器可以优雅地扩展函数功能", False),
    ]

    print("=" * 60)
    print("宽松模式测试（生产推荐）")
    print("=" * 60)
    for text, expected in test_cases:
        result = contains_time_sensitive_claims(text, strict=False)
        status = "✓" if result["has_risk"] == expected else "✗"
        print(f"\n{status} {text[:50]}...")
        if result["has_risk"]:
            print(f"   风险: {result['confidence']} | 信号: {result['signals']}")
            print(f"   示例: {result['examples']}")

    print("\n\n" + "=" * 60)
    print("严格模式测试（高风险场景）")
    print("=" * 60)
    for text, _ in test_cases:
        result = contains_time_sensitive_claims(text, strict=True)
        if result["has_risk"]:
            print(f"\n⚠ {text[:50]}...")
            print(f"   风险: {result['confidence']} | 信号: {result['signals']}")
