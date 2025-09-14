import re

with open("EN_DouWenTao1_markdown.srt", "r", encoding="utf-8") as f:
    content = f.read()

# Pattern: double newline followed by index number at start of line
block_start_re = re.compile(r"\n\n(?=\d+\n)")

# Split into blocks
blocks = block_start_re.split(content)

# Remove all other double newlines within blocks
cleaned_blocks = [re.sub(r"\n\n(?!\d+\n)", "\n", block) for block in blocks]

# Rejoin blocks with double newline before index
result = "\n\n".join(cleaned_blocks)

with open("EN_DouWenTao1_markdown.srt", "w", encoding="utf-8") as f:
    f.write(result)
