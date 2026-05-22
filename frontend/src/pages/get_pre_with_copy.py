with open(r"C:\Users\arjun\OneDrive\Desktop\llm-chatbot\frontend\src\pages\Chat.tsx", "r", encoding="utf-8") as f:
    content = f.read()

import re
match = re.search(r"function PreWithCopy.*?(?=function|\nclass |\nconst |\nexport )", content, re.DOTALL)
if match:
    print(match.group(0))
else:
    print("Could not find PreWithCopy")
