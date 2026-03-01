import re

def strip_days(text):
    days_pattern = re.compile(r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b[:\-]?\s*', re.IGNORECASE)
    return days_pattern.sub('', text)

print(strip_days("Monday: https://www.allrecipes.com/recipe/24264/sloppy-joes-ii/"))
print(strip_days("Title: sloppy Joe, shrimp smiley face fries,"))
