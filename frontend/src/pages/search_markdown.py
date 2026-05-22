with open(r"C:\Users\arjun\OneDrive\Desktop\llm-chatbot\frontend\src\pages\Chat.tsx", "r", encoding="utf-8") as f:
    content = f.read()

import re
matches = [m.start() for m in re.finditer("ReactMarkdown", content)]
print(f"Occurrences of ReactMarkdown in Chat.tsx: {len(matches)}")
for m in matches:
    start = max(0, m - 150)
    end = min(len(content), m + 350)
    print(f"--- Context ---")
    print(content[start:end])
