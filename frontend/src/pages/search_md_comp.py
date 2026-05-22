with open(r"C:\Users\arjun\OneDrive\Desktop\llm-chatbot\frontend\src\pages\Chat.tsx", "r", encoding="utf-8") as f:
    content = f.read()

import re
matches = [m.start() for m in re.finditer("markdownComponents", content)]
print(f"Occurrences of markdownComponents: {len(matches)}")
for m in matches:
    start = max(0, m - 100)
    end = min(len(content), m + 250)
    print(f"--- Context ---")
    print(content[start:end])
