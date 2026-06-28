import sys
sys.stdout.reconfigure(encoding="utf-8")
with open("scripts/first_run_setup.py", "r", encoding="utf-8") as f:
    content = f.read()
msg_idx = content.index("MESSAGES")
zh_key = content.index('"zh": {', msg_idx)
zh_open = content.index("{", zh_key)
depth = 1; pos = zh_open + 1
while depth > 0:
    if content[pos] == "{": depth += 1
    elif content[pos] == "}": depth -= 1
    pos += 1
zh_close = pos - 1
en_key = content.index('"en": {', zh_close)
en_open = content.index("{", en_key)
depth = 1; pos = en_open + 1
while depth > 0:
    if content[pos] == "{": depth += 1
    elif content[pos] == "}": depth -= 1
    pos += 1
en_close = pos - 1
zh_nl = content.rindex("\n", zh_open, zh_close)
en_nl = content.rindex("\n", en_open, en_close)
print("zh", zh_nl, "en", en_nl)
