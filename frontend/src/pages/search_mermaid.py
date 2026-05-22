with open(r"C:\Users\arjun\OneDrive\Desktop\llm-chatbot\frontend\src\pages\Chat.tsx", "r", encoding="utf-8") as f:
    content = f.read()

import re
matches = [m.start() for m in re.finditer("MermaidRenderer", content)]
print(f"Occurrences of MermaidRenderer in Chat.tsx: {len(matches)}")
for m in matches:
    start = max(0, m - 100)
    end = min(len(content), m + 200)
    print(f"--- Context ---")
    print(content[start:end])
