"""The task suite: 12 deterministic tasks with exact, checkable answers."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Task:
    id: str
    category: str
    instruction: str
    expected: str
    kind: str  # "number" | "text"

    def check(self, answer) -> bool:
        if answer is None:
            return False
        a = str(answer).strip()
        if self.kind == "number":
            m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*", a.replace(",", ""))
            return bool(m) and abs(float(m.group(1)) - float(self.expected)) < 1e-6
        return a.strip(" .\"'").lower() == self.expected.lower()

    def payload(self):
        d = asdict(self)
        d.pop("expected")
        return d


TASKS = [
    Task("t01_arith", "tool-use", "Compute (17 * 23) + (144 / 12). Answer with the number only.", "403", "number"),
    Task("t02_price", "lookup", "What is the unit price in USD of SKU A-102? Answer with the number only.", "12.5", "number"),
    Task("t03_order_total", "multi-hop", "What is the total price in USD of 3 units of SKU A-102 and 2 units of SKU B-220? Answer with the number only.", "52", "number"),
    Task("t04_log_errors", "file", "How many lines in /data/log.txt contain the word ERROR? Answer with the number only.", "3", "number"),
    Task("t05_hq_city", "retrieval", "In which city is Kitsune Labs headquartered? Answer with the city name only.", "Osaka", "text"),
    Task("t06_convert", "tool-use", "Convert 26.2 miles to km, rounded to 1 decimal place. Answer with the number only.", "42.2", "number"),
    Task("t07_customer_email", "multi-hop", "Read /data/order.json and return the email address of the customer who placed the order.", "aiko.tanaka@example.com", "text"),
    Task("t08_top_scorer", "file", "Read /data/scores.csv and return the name of the person with the highest score.", "Mika", "text"),
    Task("t09_days_between", "tool-use", "How many days are there from 2026-01-15 to 2026-03-01? Answer with the number only.", "45", "number"),
    Task("t10_stock_check", "multi-hop", "Read /data/order.json. Is every item in the order in stock? Answer yes or no.", "no", "text"),
    Task("t11_refund_window", "retrieval", "According to the refund policy document, within how many days are refunds accepted? Answer with the number only.", "30", "number"),
    Task("t12_reverse", "no-tool", "Reverse the string 'benchmark'. Answer with the reversed string only.", "kramhcneb", "text"),
]

TASKS_BY_ID = {t.id: t for t in TASKS}
