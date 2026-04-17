from __future__ import annotations

from collections import Counter, defaultdict

import jieba

from modules import db
from modules.utils import current_date_str


STOPWORDS = {
    "的", "了", "和", "是", "在", "就", "都", "而", "及", "与", "着", "或", "一个",
    "一种", "我们", "你们", "他们", "是否", "可以", "需要", "自己", "这个", "那个",
    "如果", "因为", "所以", "对于", "进行", "相关", "办理", "按照", "根据", "以及",
    "通过", "已经", "没有", "还有", "但是", "就是", "什么", "怎么", "如何", "哪些",
    "这里", "那里", "一下", "一下子", "目前", "最新", "一般", "情况", "问题", "内容",
    "文章", "官方", "深圳市", "深圳", "公安局", "页面", "资料", "信息", "说明",
}


CATEGORY_RULES = {
    "核心词": {"入户", "深户", "户口", "迁移", "积分入户", "迁入"},
    "区域词": {"龙岗", "龙华", "宝安", "南山", "福田", "罗湖", "盐田", "光明", "坪山"},
    "问题词": {"条件", "流程", "材料", "办理", "申请", "怎么办", "多久", "入口"},
    "动作词": {"预约", "提交", "审核", "迁入", "申报", "受理"},
}


def classify_keyword(word: str) -> str:
    for category, words in CATEGORY_RULES.items():
        if word in words:
            return category
    return "其他"


def tokenize(text: str) -> list[str]:
    words = []
    for word in jieba.lcut(text, cut_all=False):
        word = word.strip()
        if len(word) < 2:
            continue
        if word in STOPWORDS:
            continue
        if word.isdigit():
            continue
        if any(char.isdigit() for char in word) and len(word) > 8:
            continue
        words.append(word)
    return words


def rebuild_keyword_tables(article_keyword_limit: int = 15) -> dict[str, int]:
    articles = db.get_all_articles()
    global_counter: Counter[str] = Counter()
    keyword_article_ids: defaultdict[str, set[int]] = defaultdict(set)
    article_keyword_rows: list[dict[str, object]] = []
    today = current_date_str()

    for article in articles:
        combined_text = f"{article['title']} {article['title']} {article['content']}"
        tokens = tokenize(combined_text)
        if not tokens:
            continue
        article_counter = Counter(tokens)
        total = sum(article_counter.values()) or 1
        for keyword, freq in article_counter.items():
            global_counter[keyword] += freq
            keyword_article_ids[keyword].add(int(article["id"]))
        for keyword, freq in article_counter.most_common(article_keyword_limit):
            article_keyword_rows.append(
                {
                    "article_id": int(article["id"]),
                    "keyword": keyword,
                    "weight": round(freq / total, 4),
                }
            )

    keyword_rows = [
        {
            "keyword": keyword,
            "category": classify_keyword(keyword),
            "freq": int(freq),
            "article_count": len(keyword_article_ids[keyword]),
            "last_seen": today,
        }
        for keyword, freq in global_counter.most_common()
    ]
    db.replace_keywords(keyword_rows, article_keyword_rows)
    return {
        "article_count": len(articles),
        "keyword_count": len(keyword_rows),
    }

