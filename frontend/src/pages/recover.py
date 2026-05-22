import json

log_path = r"C:\Users\arjun\.gemini\antigravity\brain\574f5869-da9c-4319-9089-70f1c414da59\.system_generated\logs\transcript.jsonl"
with open(log_path, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if "export default function Architect()" in line:
            print(f"Match found on line {i}!")
            try:
                data = json.loads(line)
                def find_all_strings(d, results):
                    if isinstance(d, str) and "export default function Architect()" in d:
                        results.append(d)
                    elif isinstance(d, dict):
                        for k, v in d.items():
                            find_all_strings(v, results)
                    elif isinstance(d, list):
                        for item in d:
                            find_all_strings(item, results)
                
                results = []
                find_all_strings(data, results)
                for j, res in enumerate(results):
                    print(f"  Snippet {j} length: {len(res)}")
                    filename = f"recovered_architect_{i}_{j}.tsx"
                    with open(filename, "w", encoding="utf-8") as out:
                        out.write(res)
            except Exception as e:
                print(f"Error decoding line {i}: {e}")
