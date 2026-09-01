#!/usr/bin/env python3
"""清理数据库中的警告文字"""
import sqlite3

DB_PATH = "./store/chat.db"
WARNING_TEXT = "⚠️ 本回答未经知识库检索核实，可能存在不准确或与公司文档不符之处，请谨慎参考。"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 查找包含警告的消息
cursor.execute("SELECT id, content FROM messages WHERE content LIKE ?", (f"%{WARNING_TEXT}%",))
rows = cursor.fetchall()

print(f"找到 {len(rows)} 条包含警告的消息")

# 清理警告文字
for row_id, content in rows:
    new_content = content.replace(WARNING_TEXT, "").replace("\n\n\n", "\n\n").strip()
    cursor.execute("UPDATE messages SET content = ? WHERE id = ?", (new_content, row_id))
    print(f"  清理消息 {row_id}")

conn.commit()
conn.close()
print("清理完成！")
