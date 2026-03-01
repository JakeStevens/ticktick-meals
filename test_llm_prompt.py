def get_ingredients_from_llm(recipe_name, session_id=None, ignore_recipe=None):
    system_prompt = "You are a helpful culinary assistant. Provide only a simple bulleted list of high-level ingredient names. Do not include any Markdown code blocks, JSON formatting, or preamble/postamble. If no ingredients are needed, return an empty response."
    user_prompt = f"List the ingredients required for a typical version of {recipe_name}. Keep the ingredients high level, things like spices can be assumed to be available. Provide the list as a simple bulleted list of ingredient names only. If the entry is something that doesn't need ingredients, such as 'left overs', 'freezer meal', 'takeout', 'Brassica', 'date night', or similar non-recipe items, return an empty response."

    if ignore_recipe:
        user_prompt += f" Ignore the ingredients for {ignore_recipe} since its ingredients are extracted separately."

    print("USER PROMPT:", user_prompt)

get_ingredients_from_llm("sloppy Joe, shrimp, smiley face fries", ignore_recipe="Sloppy Joes II")
