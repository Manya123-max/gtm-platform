import re

log_path = r"C:\Users\govin\.gemini\antigravity-ide\brain\b451d663-d9af-458d-b716-37ab11fcb22f\.system_generated\tasks\task-119.log"

def main():
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        print(f"Total lines in log: {len(lines)}")
        
        keywords = ["failed", "error", "exception", "Message generation"]
        printed = 0
        for i, line in enumerate(lines):
            if any(kw.lower() in line.lower() for kw in keywords):
                # Print the line and a few context lines
                print(f"--- Line {i+1} ---")
                start = max(0, i - 2)
                end = min(len(lines), i + 5)
                for j in range(start, end):
                    marker = ">> " if j == i else "   "
                    print(f"{marker}{lines[j].strip()}")
                print("-" * 50)
                printed += 1
                if printed > 30:
                    print("Truncating further matches...")
                    break
    except Exception as e:
        print("Failed to read log file:", e)

if __name__ == "__main__":
    main()
