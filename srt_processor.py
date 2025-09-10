#!/usr/bin/env python3
"""
Chinese SRT Subtitle Processor
Processes all SRT files in 'input' folder and moves results to 'output' folder.
"""

import re
import os
import sys
import shutil
import glob
from googletrans import Translator
import jieba
from pypinyin import lazy_pinyin, Style

def install_requirements():
    """Install required packages if not available."""
    try:
        import googletrans
        import jieba
        import pypinyin
    except ImportError:
        print("Installing required packages...")
        os.system("pip install googletrans==4.0.0rc1 jieba pypinyin")
        print("Packages installed. Please run the script again.")
        sys.exit(1)

def parse_srt_file(filepath):
    """Parse SRT file and return list of subtitle entries."""
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Split by double newlines to separate subtitle blocks
    blocks = re.split(r'\n\s*\n', content.strip())
    subtitles = []
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            subtitle_num = lines[0]
            timestamp = lines[1]
            text = '\n'.join(lines[2:])
            subtitles.append({
                'number': subtitle_num,
                'timestamp': timestamp,
                'text': text
            })
    
    return subtitles

def get_pinyin(word):
    """Get pinyin for a Chinese word."""
    pinyin_list = lazy_pinyin(word, style=Style.TONE_MARKS)
    return ''.join(pinyin_list)

def translate_text(text, translator):
    """Translate Chinese text to English."""
    try:
        result = translator.translate(text, src='zh', dest='en')
        return result.text
    except Exception as e:
        print(f"Translation error: {e}")
        return "[Translation failed]"

def get_vocabulary_breakdown(text, translator):
    """Get vocabulary breakdown for Chinese text."""
    # Segment the text into words
    words = jieba.cut(text)
    unique_words = []
    seen = set()
    
    for word in words:
        word = word.strip()
        # Only include Chinese characters and avoid duplicates
        if word and re.search(r'[\u4e00-\u9fff]', word) and word not in seen:
            seen.add(word)
            unique_words.append(word)
    
    vocabulary = []
    for word in unique_words:
        try:
            pinyin = get_pinyin(word)
            english = translate_text(word, translator)
            vocabulary.append(f"{word}     {pinyin}     {english}")
        except Exception as e:
            print(f"Error processing word '{word}': {e}")
            continue
    
    return vocabulary

def process_srt_file(input_filepath, output_dir):
    """Process a single SRT file and create enhanced version in output directory."""
    # Initialize translator
    translator = Translator()
    
    # Parse the original SRT file
    subtitles = parse_srt_file(input_filepath)
    
    # Create output filename
    filename = os.path.basename(input_filepath)
    name, ext = os.path.splitext(filename)
    output_filepath = os.path.join(output_dir, f"EN_{name}{ext}")
    
    print(f"Processing {filename} with {len(subtitles)} subtitle entries...")
    
    # Process each subtitle
    enhanced_subtitles = []
    for i, subtitle in enumerate(subtitles):
        if (i + 1) % 10 == 0:  # Progress update every 10 subtitles
            print(f"  Processing subtitle {i+1}/{len(subtitles)}")
        
        original_text = subtitle['text']
        
        # Skip if no Chinese characters
        if not re.search(r'[\u4e00-\u9fff]', original_text):
            enhanced_subtitles.append(subtitle)
            continue
        
        # Get English translation
        english_translation = translate_text(original_text, translator)
        
        # Get vocabulary breakdown
        vocabulary = get_vocabulary_breakdown(original_text, translator)
        
        # Create enhanced text
        enhanced_text = original_text + '\n' + english_translation
        if vocabulary:
            enhanced_text += '\n' + '\n'.join(vocabulary)
        
        enhanced_subtitle = {
            'number': subtitle['number'],
            'timestamp': subtitle['timestamp'],
            'text': enhanced_text
        }
        enhanced_subtitles.append(enhanced_subtitle)
    
    # Write the enhanced SRT file
    with open(output_filepath, 'w', encoding='utf-8') as file:
        for i, subtitle in enumerate(enhanced_subtitles):
            file.write(f"{subtitle['number']}\n")
            file.write(f"{subtitle['timestamp']}\n")
            file.write(f"{subtitle['text']}\n")
            
            # Add blank line between subtitles (except for the last one)
            if i < len(enhanced_subtitles) - 1:
                file.write('\n')
    
    print(f"  Enhanced file created: EN_{name}{ext}")
    return output_filepath

def main():
    """Main function to process all SRT files in input folder."""
    install_requirements()
    
    # Get script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir = os.path.join(script_dir, "input")
    output_dir = os.path.join(script_dir, "output")
    
    # Check if input folder exists
    if not os.path.exists(input_dir):
        print("Could not find 'input' folder.")
        sys.exit(1)
    
    # Create output folder if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output folder: {output_dir}")
    
    # Find all SRT files in input folder
    srt_pattern = os.path.join(input_dir, "*.srt")
    srt_files = glob.glob(srt_pattern)
    
    if not srt_files:
        print("No SRT files found in the input folder.")
        return
    
    print(f"Found {len(srt_files)} SRT file(s) to process:")
    for srt_file in srt_files:
        print(f"  - {os.path.basename(srt_file)}")
    print()
    
    # Process each SRT file
    processed_files = []
    for srt_file in srt_files:
        try:
            enhanced_file = process_srt_file(srt_file, output_dir)
            processed_files.append((srt_file, enhanced_file))
            print(f"✓ Successfully processed {os.path.basename(srt_file)}\n")
        except Exception as e:
            print(f"✗ Error processing {os.path.basename(srt_file)}: {e}\n")
            continue
    
    # Move original files to output folder
    print("Moving original files to output folder...")
    for original_file, enhanced_file in processed_files:
        try:
            original_filename = os.path.basename(original_file)
            destination = os.path.join(output_dir, original_filename)
            shutil.move(original_file, destination)
            print(f"  Moved {original_filename}")
        except Exception as e:
            print(f"  Error moving {original_filename}: {e}")
    
    print(f"\nProcessing complete!")
    print(f"All files have been moved to: {output_dir}")
    
    # Check if input folder is now empty
    remaining_files = os.listdir(input_dir)
    if not remaining_files:
        print("Input folder is now empty.")
    else:
        print(f"Note: {len(remaining_files)} file(s) remain in input folder (non-SRT or failed processing)")

if __name__ == "__main__":
    main()
