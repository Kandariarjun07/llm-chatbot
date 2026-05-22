with open(r"C:\Users\arjun\OneDrive\Desktop\llm-chatbot\frontend\src\pages\Architect.tsx", "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")
# Find some key structures
for idx, line in enumerate(lines):
    if "sidebar" in line.lower() or "aside" in line.lower() or "panel" in line.lower() or "console" in line.lower() or "addnode" in line.lower():
        if idx % 20 == 0 or "aside" in line:
            print(f"Line {idx+1}: {line.strip()}")
