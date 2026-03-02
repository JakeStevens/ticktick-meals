import re
URL_PATTERN = re.compile(r'https?://[^\s\)\>\]\"\'\s]+')
def test(all_text):
    urls = URL_PATTERN.findall(all_text)
    print("URLS:", urls)

    # how to extract remainder?
    remainder = all_text
    for url in urls:
        remainder = remainder.replace(url, "")
    print("REMAINDER:", remainder)

test("Title: https://www.allrecipes.com/recipe/24264/sloppy-joes-ii/ Description: sloppy Joe, shrimp, smiley face fries")
test("Title: sloppy Joe, shrimp smiley face fries, Description: https://www.allrecipes.com/recipe/24264/sloppy-joes-ii/")
